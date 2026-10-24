"""Tarefas de tradução de um projeto, em segundo plano, com progresso e teto de gasto.

Uma tarefa traduz os segmentos pendentes das páginas pedidas, seção por seção
(um lote nunca mistura seções), e grava cada resultado no projeto assim que a
seção termina: interromper no meio não perde o que já foi pago. O custo real
é somado a cada seção pelo preço do catálogo; passando do teto escolhido pelo
usuário, a tarefa para (``stopped_budget``). Cancelar vale entre seções.
Uma tarefa por projeto de cada vez.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from itertools import groupby

from app.translation.cache import TranslationCache
from app.translation.engines import Engine, Prices
from app.translation.provider import TranslationProvider
from app.translation.service import translate

from .project_store import ProjectStore, StoreError, _now

ACTIVE = ("queued", "running", "cancel_requested")
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


@dataclass
class Job:
    id: int
    engine: str
    model: str
    pages: str
    state: str  # queued | running | cancel_requested | done | done_with_warnings | cancelled | stopped_budget | failed
    total: int
    done: int
    tokens_in: int
    tokens_out: int
    cost: float
    estimate: float | None
    budget: float
    counts: dict
    error: str | None
    author: str
    created_at: str
    finished_at: str | None


def _row(r) -> Job:
    d = dict(r)
    d["counts"] = json.loads(d.pop("counts_json"))
    return Job(**d)


def list_jobs(store: ProjectStore) -> list[Job]:
    with store._db() as db:
        return [_row(r) for r in db.execute("SELECT * FROM job ORDER BY id DESC")]


def get_job(store: ProjectStore, job_id: int) -> Job:
    with store._db() as db:
        r = db.execute("SELECT * FROM job WHERE id=?", (job_id,)).fetchone()
    if r is None:
        raise StoreError(f"tarefa inexistente: {job_id}")
    return _row(r)


def cancel_job(store: ProjectStore, job_id: int) -> Job:
    with store._db() as db:
        db.execute("UPDATE job SET state='cancel_requested' WHERE id=? AND state IN ('queued','running')", (job_id,))
    return get_job(store, job_id)


def start_job(store: ProjectStore, eng: Engine, pages: set[int], pages_spec: str, budget: float, author: str,
              provider: TranslationProvider, prices: Prices, estimate: float | None = None,
              background: bool = True) -> Job:
    """Cria a tarefa e a executa (em outra thread, se ``background``)."""
    with _guard:
        lock = _locks.setdefault(str(store.db_path), threading.Lock())
    if not lock.acquire(blocking=False):
        raise StoreError("já há uma tarefa de tradução em andamento neste projeto")
    try:
        with store._db() as db:
            if db.execute("SELECT 1 FROM job WHERE state IN ('queued','running','cancel_requested')").fetchone():
                raise StoreError("já há uma tarefa de tradução em andamento neste projeto")
            items = store.sources(pages)
            cur = db.execute(
                "INSERT INTO job (engine, model, pages, state, total, budget, estimate, author, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (eng.id, eng.model, pages_spec, "queued", len(items), budget, estimate, author, _now()))
            job_id = cur.lastrowid
    except BaseException:
        lock.release()
        raise

    def work() -> None:
        try:
            _run(store, job_id, items, eng, provider, prices)
        finally:
            lock.release()

    if background:
        threading.Thread(target=work, name=f"traducao-{store.id}-{job_id}", daemon=True).start()
    else:
        work()
    return get_job(store, job_id)


def _run(store: ProjectStore, job_id: int, items, eng: Engine, provider: TranslationProvider, prices: Prices) -> None:
    def update(**fields) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        with store._db() as db:
            db.execute(f"UPDATE job SET {sets} WHERE id=?", (*fields.values(), job_id))  # chaves vêm só deste módulo

    def state() -> str:
        with store._db() as db:
            return db.execute("SELECT state FROM job WHERE id=?", (job_id,)).fetchone()["state"]

    price_in, price_out = prices.by_model.get(eng.model, eng.fallback_price)
    budget = get_job(store, job_id).budget
    counts: Counter[str] = Counter()
    done = tokens_in = tokens_out = 0
    cost = 0.0
    update(state="running")
    try:
        glossary = store.glossary()
        cache = TranslationCache(store.dir / "cache.sqlite")
        style = store.style
        for label, group in groupby(items, key=lambda x: x[0]):
            if state() == "cancel_requested":
                update(state="cancelled", finished_at=_now(), counts_json=json.dumps(counts))
                return
            sources = [s for _, s in group]
            run = translate(sources, provider, glossary, section=label, style=style, cache=cache)
            with store._db() as db:
                for res in run.results:
                    counts[store.record_machine(db, {
                        "id": res.id, "status": res.status.value, "text": res.text,
                        "raw_translation": res.raw_translation, "warnings": res.warnings, "problems": res.problems,
                        "provider": res.provider, "model": res.model}, author=f"motor {eng.id}")] += 1
            t = run.tokens()
            tokens_in += t["input"]
            tokens_out += t["output"]
            cost = tokens_in * price_in + tokens_out * price_out
            done += len(sources)
            update(done=done, tokens_in=tokens_in, tokens_out=tokens_out, cost=round(cost, 5),
                   counts_json=json.dumps(counts))
            if cost > budget:
                update(state="stopped_budget", finished_at=_now(),
                       error=f"gasto real {cost:.4f} passou do teto {budget:.4f}; o que já foi traduzido está salvo")
                return
        problems = counts["needs_review"] + counts["failed"]
        update(state="done_with_warnings" if problems else "done", finished_at=_now())
    except Exception as exc:  # noqa: BLE001 - a tarefa registra qualquer falha e não derruba o servidor
        update(state="failed", finished_at=_now(), error=f"{type(exc).__name__}: {exc}")


ProviderFactory = Callable[[Engine], TranslationProvider]

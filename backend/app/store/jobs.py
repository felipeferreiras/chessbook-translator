"""Tarefas de tradução de um projeto, em segundo plano, com progresso, teto de gasto e retomada.

Uma tarefa traduz os segmentos escolhidos (``ProjectStore.select_sources``)
das páginas pedidas, seção por seção (um lote nunca mistura seções), e grava
cada resultado no projeto assim que a seção termina: interromper no meio não
perde o que já foi pago, e os lotes já respondidos de uma seção interrompida
ficam no cache.

Gastos: o custo real é somado a cada seção pelo preço do catálogo. Antes de
cada seção, o custo previsto dela é comparado com o que sobra do teto; se não
couber, a tarefa para (``stopped_budget``) sem enviar. O teto de cada tarefa
nunca passa do que sobra do teto do projeto, quando houver.

Retomada: uma tarefa ativa cujo processo morreu (servidor encerrado, queda de
energia) aparece como ``interrupted``. ``resume_job`` cria uma tarefa nova com
o mesmo motor e seleção, pulando os segmentos que a anterior já tratou.

Cancelar vale entre seções. Uma tarefa por projeto de cada vez.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby

from app.translation.cache import TranslationCache
from app.translation.engines import Engine, Prices, estimate
from app.translation.prompt import glossary_signature
from app.translation.provider import TranslationProvider
from app.translation.service import translate

from .project_store import ProjectStore, StoreError, _now

ACTIVE = ("queued", "running", "cancel_requested")
RESUMABLE = ("interrupted", "cancelled", "stopped_budget", "failed")
PROCESS_TOKEN = uuid.uuid4().hex[:12]
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()
_running: set[tuple[str, int]] = set()  # (projeto, tarefa) com thread viva neste processo


@dataclass
class Job:
    id: int
    engine: str
    model: str
    pages: str
    state: str  # queued | running | cancel_requested | done | done_with_warnings | cancelled | stopped_budget | failed | interrupted
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
    mode: str = "pending"
    segment_ids: list[str] | None = None
    fresh: bool = False
    heartbeat_at: str | None = None
    resumed_from: int | None = None


def _row(r) -> Job:
    d = dict(r)
    d["counts"] = json.loads(d.pop("counts_json"))
    d["segment_ids"] = json.loads(d.pop("segment_ids_json"))
    d["fresh"] = bool(d["fresh"])
    d.pop("runner")
    return Job(**d)


STALE_SECONDS = 30 * 60  # sem sinal de vida há mais que isso: interrompida, mesmo com o processo vivo


def _runner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{PROCESS_TOKEN}"


def _alive(store: ProjectStore, job_id: int, runner: str | None, heartbeat: str | None = None) -> bool:
    """A thread que executa a tarefa ainda existe? (neste processo ou em outro processo vivo)

    Outro processo só conta como vivo se der sinal recente (``heartbeat_at``,
    gravado a cada seção): o número de um processo morto pode ser reaproveitado.
    """
    if not runner:
        return False
    parts = runner.split(":")
    host, pid_text, token = parts if len(parts) == 3 else ("", *(parts + [""])[:2])
    if token == PROCESS_TOKEN:
        # a trava do projeto fica presa desde antes de gravar a tarefa até o fim: cobre o instante
        # entre gravar e marcar a thread como viva
        lock = _locks.get(str(store.db_path))
        return (str(store.db_path), job_id) in _running or bool(lock and lock.locked())
    try:
        fresh = (datetime.now(UTC) - datetime.fromisoformat(heartbeat)).total_seconds() < STALE_SECONDS
    except (TypeError, ValueError):
        fresh = False
    if not fresh:
        return False
    if host and host != socket.gethostname():
        return True  # outra máquina com o mesmo armazenamento: vale o sinal de vida
    try:
        os.kill(int(pid_text), 0)
    except (OSError, ValueError):
        return False
    return int(pid_text) != os.getpid()  # mesmo pid com outro token: o processo foi reiniciado


def recover_orphans(store: ProjectStore) -> list[int]:
    """Marca como ``interrupted`` as tarefas ativas sem ninguém executando. Devolve os ids."""
    with store._db() as db:
        rows = db.execute("SELECT id, runner, heartbeat_at FROM job"
                          " WHERE state IN ('queued','running','cancel_requested')").fetchall()
        orphans = [r["id"] for r in rows if not _alive(store, r["id"], r["runner"], r["heartbeat_at"])]
        for job_id in orphans:
            db.execute("UPDATE job SET state='interrupted', finished_at=?, error=? WHERE id=?",
                       (_now(), "interrompida: o processo que a executava parou; o que já foi gravado está salvo",
                        job_id))
    return orphans


def list_jobs(store: ProjectStore) -> list[Job]:
    recover_orphans(store)
    with store._db() as db:
        return [_row(r) for r in db.execute("SELECT * FROM job ORDER BY id DESC")]


def get_job(store: ProjectStore, job_id: int) -> Job:
    recover_orphans(store)
    with store._db() as db:
        r = db.execute("SELECT * FROM job WHERE id=?", (job_id,)).fetchone()
    if r is None:
        raise StoreError(f"tarefa inexistente: {job_id}")
    return _row(r)


def cancel_job(store: ProjectStore, job_id: int) -> Job:
    with store._db() as db:
        db.execute("UPDATE job SET state='cancel_requested' WHERE id=? AND state IN ('queued','running')", (job_id,))
    return get_job(store, job_id)


def handled_segments(store: ProjectStore, job_id: int) -> frozenset[str]:
    """Segmentos já tratados por esta tarefa e pelas que ela retomou."""
    out: set[str] = set()
    current: int | None = job_id
    with store._db() as db:
        while current is not None:
            out |= {r[0] for r in db.execute("SELECT segment_id FROM job_segment WHERE job_id=?", (current,))}
            row = db.execute("SELECT resumed_from FROM job WHERE id=?", (current,)).fetchone()
            current = row["resumed_from"] if row else None
    return frozenset(out)


def effective_budget(store: ProjectStore, budget: float) -> float:
    """O teto da tarefa, limitado ao que sobra do teto do projeto."""
    limit = store.spend_limit
    if limit is None:
        return budget
    remaining = round(limit - store.spent(), 5)
    if remaining <= 0:
        raise StoreError(f"o teto de gasto do projeto ({limit:.4f}) já foi atingido; aumente-o para continuar")
    return min(budget, remaining)


def start_job(store: ProjectStore, eng: Engine, pages: set[int], pages_spec: str, budget: float, author: str,
              provider: TranslationProvider, prices: Prices, estimate: float | None = None,
              background: bool = True, mode: str = "pending", ids: frozenset[str] = frozenset(),
              fresh: bool = False, resumed_from: int | None = None) -> Job:
    """Cria a tarefa e a executa (em outra thread, se ``background``)."""
    with _guard:
        lock = _locks.setdefault(str(store.db_path), threading.Lock())
    if not lock.acquire(blocking=False):
        raise StoreError("já há uma tarefa de tradução em andamento neste projeto")
    try:
        recover_orphans(store)
        budget = effective_budget(store, budget)
        exclude = handled_segments(store, resumed_from) if resumed_from else frozenset()
        items, _ = store.select_sources(pages, mode, ids, exclude)
        with store._db() as db:
            if db.execute("SELECT 1 FROM job WHERE state IN ('queued','running','cancel_requested')").fetchone():
                raise StoreError("já há uma tarefa de tradução em andamento neste projeto")
            cur = db.execute(
                "INSERT INTO job (engine, model, pages, state, total, budget, estimate, author, created_at, mode,"
                " segment_ids_json, fresh, runner, heartbeat_at, resumed_from) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eng.id, eng.model, pages_spec, "queued", len(items), budget, estimate, author, _now(), mode,
                 json.dumps(sorted(ids)), int(fresh), _runner(), _now(), resumed_from))
            job_id = cur.lastrowid
        _running.add((str(store.db_path), job_id))
    except BaseException:
        lock.release()
        raise

    def work() -> None:
        try:
            _run(store, job_id, items, eng, provider, prices, fresh)
        finally:
            _running.discard((str(store.db_path), job_id))
            lock.release()

    if background:
        threading.Thread(target=work, name=f"traducao-{store.id}-{job_id}", daemon=True).start()
    else:
        work()
    return get_job(store, job_id)


def resume_plan(store: ProjectStore, job_id: int) -> tuple[Job, set[int], frozenset[str]]:
    """(tarefa original, páginas, segmentos a pular) para retomar ``job_id``."""
    from app.pipeline.segments import parse_pages

    old = get_job(store, job_id)
    if old.state not in RESUMABLE:
        raise StoreError(f"a tarefa {job_id} não pode ser retomada (estado {old.state})")
    return old, parse_pages(old.pages, store.info["pages"]), handled_segments(store, job_id)


def resume_job(store: ProjectStore, job_id: int, author: str, provider: TranslationProvider, prices: Prices,
               eng: Engine, budget: float | None = None, estimate: float | None = None,
               background: bool = True) -> Job:
    """Continua uma tarefa interrompida, cancelada ou parada pelo teto, sem repetir o que ela já tratou."""
    old, pages, _ = resume_plan(store, job_id)
    if budget is None:
        budget = round(old.budget - old.cost, 5)
        if budget <= 0:
            raise StoreError("o teto da tarefa original já foi usado; informe um novo teto para continuar")
    return start_job(store, eng, pages, old.pages, budget, author, provider, prices, estimate, background,
                     old.mode, frozenset(old.segment_ids or ()), old.fresh, resumed_from=job_id)


def _run(store: ProjectStore, job_id: int, items, eng: Engine, provider: TranslationProvider, prices: Prices,
         fresh: bool = False) -> None:
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
    update(state="running", heartbeat_at=_now(), error=None)
    try:
        glossary = store.glossary()
        cache = TranslationCache(store.dir / "cache.sqlite")
        style = store.style
        for label, group in groupby(items, key=lambda x: x[0]):
            if state() == "cancel_requested":
                update(state="cancelled", finished_at=_now(), counts_json=json.dumps(counts))
                return
            sources = [s for _, s in group]
            predicted = estimate([(label, sources)], glossary, eng, prices, style, None if fresh else cache).cost
            if cost + predicted > budget:
                update(state="stopped_budget", finished_at=_now(),
                       error=f"o próximo trecho ({label or 'sem seção'}, previsto {predicted:.4f}) passaria do teto "
                             f"{budget:.4f} (gasto até aqui {cost:.4f}); nada dele foi enviado")
                return
            run = translate(sources, provider, glossary, section=label, style=style, cache=cache,
                            cache_read=not fresh)
            with store._db() as db:
                for res in run.results:
                    outcome = store.record_machine(db, {
                        "id": res.id, "status": res.status.value, "text": res.text,
                        "raw_translation": res.raw_translation, "warnings": res.warnings, "problems": res.problems,
                        "provider": res.provider, "model": res.model,
                        "glossary_sig": glossary_signature(res.masked, glossary)}, author=f"motor {eng.id}")
                    counts[outcome] += 1
                    db.execute("INSERT OR REPLACE INTO job_segment VALUES (?,?,?)", (job_id, res.id, outcome))
            t = run.tokens()
            tokens_in += t["input"]
            tokens_out += t["output"]
            cost = tokens_in * price_in + tokens_out * price_out
            done += len(sources)
            update(done=done, tokens_in=tokens_in, tokens_out=tokens_out, cost=round(cost, 5),
                   counts_json=json.dumps(counts), heartbeat_at=_now())
            if cost > budget:
                update(state="stopped_budget", finished_at=_now(),
                       error=f"gasto real {cost:.4f} passou do teto {budget:.4f}; o que já foi traduzido está salvo")
                return
        problems = counts["needs_review"] + counts["failed"] + counts["retry_failed"]
        update(state="done_with_warnings" if problems else "done", finished_at=_now())
    except Exception as exc:  # noqa: BLE001 - a tarefa registra qualquer falha e não derruba o servidor
        update(state="failed", finished_at=_now(), error=f"{type(exc).__name__}: {exc}")


ProviderFactory = Callable[[Engine], TranslationProvider]

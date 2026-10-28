"""Montagem do PDF traduzido de um projeto, em outro processo, com andamento e cancelamento.

A montagem usa ~400 MB e minutos de CPU no livro inteiro; roda num processo
separado (``scripts.assemble_pdf``) para não travar a API nem dividir a
memória com ela. O andamento vem de ``output/progress.json``; cancelar cria
``output/stop`` e o processo para entre partes.

Retomada: as partes de 20 páginas prontas ficam em ``output/partes``. Uma
montagem interrompida (servidor encerrado, cancelamento) recomeça pelas
partes que faltam, e uma montagem depois de revisar algumas páginas refaz só
as partes delas (``app.layout.assemble``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .project_store import ProjectStore, StoreError, _now

BACKEND = Path(__file__).resolve().parents[2]
_procs: dict[tuple[str, int], subprocess.Popen] = {}
_guard = threading.Lock()


@dataclass
class Assembly:
    id: int
    state: str  # running | done | failed | cancelled | interrupted
    author: str
    created_at: str
    finished_at: str | None
    error: str | None
    summary: dict | None
    progress: dict | None
    outdated: bool  # houve mudança de texto depois desta montagem


def _out(store: ProjectStore) -> Path:
    return store.dir / "output"


def _alive(store: ProjectStore, row) -> bool:
    proc = _procs.get((str(store.db_path), row["id"]))
    if proc is not None:
        return proc.poll() is None
    if not row["pid"]:
        return False
    try:
        os.kill(row["pid"], 0)
    except OSError:
        return False
    return True  # processo de outra instância do servidor, ainda vivo


def _view(store: ProjectStore, row) -> Assembly:
    progress = None
    path = _out(store) / "progress.json"
    if row["state"] == "running" and path.exists():
        try:
            progress = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            progress = None
    outdated = False
    if row["state"] == "done" and (_out(store) / "relatorio.json").exists():
        from app.layout.assemble import content_hash

        summary = json.loads((_out(store) / "relatorio.json").read_text(encoding="utf-8"))["summary"]
        outdated = summary.get("content_sha256") != content_hash(store.export_result())
    return Assembly(row["id"], row["state"], row["author"], row["created_at"], row["finished_at"], row["error"],
                    json.loads(row["summary_json"]) if row["summary_json"] else None, progress, outdated)


def latest(store: ProjectStore) -> Assembly | None:
    with store._db() as db:
        row = db.execute("SELECT * FROM assembly ORDER BY id DESC LIMIT 1").fetchone()
        if row is not None and row["state"] == "running" and not _alive(store, row):
            db.execute("UPDATE assembly SET state='interrupted', finished_at=?, error=? WHERE id=?",
                       (_now(), "interrompida: o processo parou; montar de novo reaproveita as partes prontas",
                        row["id"]))
            row = db.execute("SELECT * FROM assembly WHERE id=?", (row["id"],)).fetchone()
    return None if row is None else _view(store, row)


def start(store: ProjectStore, author: str, wait: bool = False) -> Assembly:
    """Exporta o texto atual e monta o PDF em outro processo."""
    if not store.verify_original():
        raise StoreError("o original do projeto não confere com o sha256 registrado")
    from app.extraction.ocr import cache_is_current

    if not cache_is_current(store.dir / "ocr.json"):
        raise StoreError("o OCR do livro foi feito por uma versão anterior do programa: "
                         "Projeto → Sincronizar com a versão atual antes de montar")
    with _guard:
        current = latest(store)
        if current is not None and current.state == "running":
            raise StoreError("já há uma montagem em andamento neste projeto")
        out = _out(store)
        export = out / "export"
        export.mkdir(parents=True, exist_ok=True)
        (out / "stop").unlink(missing_ok=True)
        (out / "progress.json").unlink(missing_ok=True)
        (export / "resultado.json").write_text(json.dumps(store.export_result(), ensure_ascii=False),
                                               encoding="utf-8")
        log = open(out / "montagem.log", "w", encoding="utf-8")  # noqa: SIM115 - fechado pelo observador
        proc = subprocess.Popen(
            [sys.executable, "-m", "scripts.assemble_pdf", str(store.original_path), str(export), str(out),
             "--cache", str(out / "partes"), "--progress", str(out / "progress.json"), "--stop", str(out / "stop"),
             *(["--ocr-cache", str(store.dir / "ocr.json")] if (store.dir / "ocr.json").exists() else [])],
            cwd=BACKEND, stdout=log, stderr=subprocess.STDOUT)
        with store._db() as db:
            job_id = db.execute("INSERT INTO assembly (state, pid, author, created_at) VALUES ('running',?,?,?)",
                                (proc.pid, author, _now())).lastrowid
        _procs[(str(store.db_path), job_id)] = proc

    def watch() -> None:
        code = proc.wait()
        log.close()
        tail = (out / "montagem.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        summary = None
        if code == 0 and (out / "relatorio.json").exists():
            s = json.loads((out / "relatorio.json").read_text(encoding="utf-8"))["summary"]
            summary = {k: s[k] for k in ("blocks", "blocks_placed", "chunks", "chunks_reused", "pages_ok", "pages")}
            summary["pages_ok"], summary["pages"] = len(summary["pages_ok"]), len(summary["pages"])
        state = "done" if code == 0 else "cancelled" if code == 3 else "failed"
        lines = tail.strip().splitlines()
        error = None if code == 0 else lines[-1] if lines else f"saída {code}"
        with store._db() as db:
            db.execute("UPDATE assembly SET state=?, finished_at=?, error=?, summary_json=? WHERE id=?",
                       (state, _now(), error, json.dumps(summary) if summary else None, job_id))
        _procs.pop((str(store.db_path), job_id), None)

    watcher = threading.Thread(target=watch, name=f"montagem-{store.id}-{job_id}", daemon=True)
    watcher.start()
    if wait:
        watcher.join()
    return latest(store)


def cancel(store: ProjectStore) -> Assembly | None:
    current = latest(store)
    if current is not None and current.state == "running":
        (_out(store) / "stop").touch()
    return latest(store)

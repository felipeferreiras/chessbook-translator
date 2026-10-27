"""Reprocessamento do projeto em outro processo: sincronizar e reler com as figurinas confirmadas.

Num livro digitalizado, sincronizar depois de atualizar o programa refaz o
OCR (dezenas de minutos), e confirmar as figurinas relê todas as páginas; por
isso os dois rodam em ``scripts.project``, num processo próprio, como a
criação e a montagem. Um por projeto de cada vez. O estado fica em
``<projeto>/reprocessamento.json`` (um processo que morreu aparece como
interrompido; basta pedir de novo: o que já foi feito é refeito do começo, sem
perder traduções).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from app.extraction.ocr import WHITE_FIGURINES

from .project_store import ProjectStore, StoreError, _now

BACKEND = Path(__file__).resolve().parents[2]
KINDS = {"sync": "sincronizar com a versão atual", "figurines": "reler com as figurinas confirmadas"}
_procs: dict[str, subprocess.Popen] = {}


def _paths(store: ProjectStore) -> tuple[Path, Path, Path, Path]:
    d = store.dir
    return (d / "reprocessamento.json", d / "reprocessamento.progress.json", d / "reprocessamento.result.json",
            d / "reprocessamento.log")


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def start(store: ProjectStore, kind: str, author: str, labels: dict[str, str] | None = None) -> dict:
    """``sync``: alinha os parágrafos com a extração atual. ``figurines``: grava as figurinas
    confirmadas (grupo → figurina, "" = não é peça), relê as páginas e sincroniza."""
    if kind not in KINDS:
        raise StoreError(f"reprocessamento desconhecido: {kind}")
    current = status(store)
    if current and current["state"] == "running":
        raise StoreError(f"já há um reprocessamento em andamento ({KINDS[current['kind']]})")
    state_path, progress, result, log_path = _paths(store)
    progress.unlink(missing_ok=True)
    result.unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "scripts.project", kind, store.id, "--progress", str(progress),
           "--result", str(result), "--author", author]
    if kind == "figurines":
        if not labels:
            raise StoreError("nenhuma figurina informada")
        bad = {k: v for k, v in labels.items() if v and v not in WHITE_FIGURINES}
        if bad or not all(str(k).isdigit() for k in labels):
            raise StoreError(f"figurina inválida: {bad or labels}")
        cmd += ["--labels", json.dumps(labels, ensure_ascii=False)]
    log = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 - fechado pelo observador
    proc = subprocess.Popen(cmd, cwd=BACKEND, stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "CHESSBOOK_STORAGE": str(store.root)})
    _procs[store.id] = proc
    state = {"kind": kind, "state": "running", "pid": proc.pid, "author": author, "started_at": _now(),
             "finished_at": None, "error": None, "result": None}
    _write(state_path, state)

    def watch() -> None:
        code = proc.wait()
        log.close()
        lines = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        done = None
        if code == 0 and result.exists():
            done = json.loads(result.read_text(encoding="utf-8"))
        state.update(state="done" if code == 0 else "failed", finished_at=_now(), result=done,
                     error=None if code == 0 else (lines[-1] if lines else f"saída {code}"))
        _write(state_path, state)
        _procs.pop(store.id, None)

    threading.Thread(target=watch, name=f"reprocessamento-{store.id}", daemon=True).start()
    return status(store) or state


def status(store: ProjectStore) -> dict | None:
    state_path, progress, _result, _log = _paths(store)
    if not state_path.exists():
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state["state"] == "running" and store.id not in _procs:
        try:
            os.kill(state["pid"], 0)
        except OSError:
            state.update(state="interrupted", error="interrompido: o servidor parou; peça de novo")
            _write(state_path, state)
    if state["state"] == "running" and progress.exists():
        try:
            state["progress"] = json.loads(progress.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return state


def figurines(store: ProjectStore) -> dict:
    """Os desenhos de peça achados pelo OCR, agrupados, com a figurina sugerida e a confirmada."""
    path = store.dir / "ocr.json"
    if not path.exists():
        return {"available": False, "reason": "o livro não foi lido por OCR", "groups": [], "labels": {}}
    stored = json.loads(path.read_text(encoding="utf-8"))
    groups = stored.get("figurine_groups")
    if groups is None:
        return {"available": False, "groups": [], "labels": {},
                "reason": "OCR feito por uma versão anterior: sincronize com a versão atual primeiro"}
    return {"available": True, "reason": "", "labels": stored.get("labels") or {},
            "groups": [{k: v for k, v in g.items() if k != "vec"} for g in groups]}

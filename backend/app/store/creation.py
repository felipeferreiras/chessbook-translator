"""Criação de projetos pela interface: o PDF enviado vira projeto em outro processo, com andamento.

A extração leva segundos num livro digital e dezenas de minutos num livro
digitalizado (OCR); por isso roda em ``scripts.project create``, num processo
próprio, como a montagem. O estado de cada criação fica em
``<armazenamento>/.criacoes/<id>.json`` (sobrevive a um reinício do servidor:
um processo que morreu aparece como interrompido, e basta enviar de novo).

O PDF recebido é conferido antes: tamanho máximo, assinatura ``%PDF-``, abre
sem erro, tem páginas e não passa do limite de páginas.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pymupdf

from .project_store import StoreError, _now

BACKEND = Path(__file__).resolve().parents[2]
MAX_BYTES = int(os.environ.get("CHESSBOOK_MAX_UPLOAD_MB", "500")) * 1024 * 1024
MAX_PAGES = int(os.environ.get("CHESSBOOK_MAX_PAGES", "3000"))
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_procs: dict[str, subprocess.Popen] = {}


def _dir(root: Path) -> Path:
    d = root / ".criacoes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def slug(name: str) -> str:
    """Id de projeto a partir do nome: "Dvoretsky's Endgame Manual" → "dvoretskys-endgame-manual"."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:64] or "livro"


def check_pdf(path: Path) -> int:
    """Confere o PDF enviado e devolve o número de páginas. Levanta ``StoreError`` com o motivo."""
    if path.stat().st_size > MAX_BYTES:
        raise StoreError(f"arquivo grande demais (máximo {MAX_BYTES // 1024 // 1024} MB)")
    with path.open("rb") as fh:
        if not fh.read(1024).lstrip().startswith(b"%PDF-"):
            raise StoreError("o arquivo não é um PDF")
    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                raise StoreError("PDF protegido por senha")
            pages = doc.page_count
    except StoreError:
        raise
    except Exception as exc:
        raise StoreError(f"o PDF não pôde ser aberto: {exc}") from exc
    if not 0 < pages <= MAX_PAGES:
        raise StoreError(f"número de páginas fora do limite (1–{MAX_PAGES}): {pages}")
    return pages


def start(root: Path, project_id: str, name: str, pdf: Path, ocr: str = "auto") -> dict:
    """Cria o projeto em outro processo. ``pdf`` é um arquivo temporário: é apagado no fim."""
    if not _ID.match(project_id):
        raise StoreError("id de projeto: só letras, números, '-' e '_' (até 64)")
    if ocr not in ("auto", "on", "off"):
        raise StoreError("modo de OCR inválido")
    if (root / project_id).exists() or project_id in _procs:
        raise StoreError(f"já existe um projeto {project_id}")
    pages = check_pdf(pdf)
    status_path = _dir(root) / f"{project_id}.json"
    progress = _dir(root) / f"{project_id}.progress.json"
    log = open(_dir(root) / f"{project_id}.log", "w", encoding="utf-8")  # noqa: SIM115 - fechado pelo observador
    proc = subprocess.Popen([sys.executable, "-m", "scripts.project", "create", project_id, name, str(pdf),
                             "--ocr", ocr, "--progress", str(progress)],
                            cwd=BACKEND, stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "CHESSBOOK_STORAGE": str(root)})
    _procs[project_id] = proc
    state = {"id": project_id, "name": name, "pages": pages, "ocr": ocr, "state": "running", "pid": proc.pid,
             "started_at": _now(), "finished_at": None, "error": None}
    _write(status_path, state)

    def watch() -> None:
        code = proc.wait()
        log.close()
        pdf.unlink(missing_ok=True)
        lines = (_dir(root) / f"{project_id}.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()
        state.update(state="done" if code == 0 else "failed", finished_at=_now(),
                     error=None if code == 0 else (lines[-1] if lines else f"saída {code}"))
        _write(status_path, state)
        _procs.pop(project_id, None)

    threading.Thread(target=watch, name=f"criacao-{project_id}", daemon=True).start()
    return status(root, project_id)


def status(root: Path, project_id: str) -> dict:
    path = _dir(root) / f"{project_id}.json"
    if not path.exists():
        raise StoreError(f"criação inexistente: {project_id}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state["state"] == "running" and project_id not in _procs:
        try:
            os.kill(state["pid"], 0)
        except OSError:
            state.update(state="interrupted", error="interrompida: o servidor parou; envie o PDF de novo")
            _write(path, state)
    progress = _dir(root) / f"{project_id}.progress.json"
    if state["state"] == "running" and progress.exists():
        try:
            state["progress"] = json.loads(progress.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return state


def all_status(root: Path) -> list[dict]:
    d = _dir(root)
    return [status(root, p.stem) for p in sorted(d.glob("*.json"))
            if not p.name.endswith(".progress.json") and not p.name.endswith(".tmp")]

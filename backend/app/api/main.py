"""API local de revisão (FastAPI). Serve também a interface compilada (``frontend/dist``).

Executar (a partir de backend/):
    CHESSBOOK_STORAGE=/caminho/dos/projetos .venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8000

Só escuta em ``127.0.0.1``: os projetos contêm o livro e a tradução. Nenhum
caminho de arquivo vem do cliente; projetos e segmentos são identificados
por id validado.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict
from pathlib import Path

import pymupdf
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.store.project_store import GuardViolation, ProjectStore, SegmentView, StoreError
from app.translation.glossary import Glossary, GlossaryEntry

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "frontend" / "dist"
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SEGMENT = re.compile(r"^p\d{1,5}-\d{1,7}$")

app = FastAPI(title="chessbook-translator", docs_url="/api/docs", openapi_url="/api/openapi.json")


def storage_root() -> Path:
    return Path(os.environ.get("CHESSBOOK_STORAGE", ROOT / "storage"))


def _store(project_id: str) -> ProjectStore:
    if not _ID.match(project_id):
        raise HTTPException(400, "id de projeto inválido")
    try:
        return ProjectStore(storage_root(), project_id)
    except StoreError as exc:
        raise HTTPException(404, str(exc)) from exc


def _segment_id(segment_id: str) -> str:
    if not _SEGMENT.match(segment_id):
        raise HTTPException(400, "id de segmento inválido")
    return segment_id


def _view(s: SegmentView) -> dict:
    out = asdict(s)
    out["needs_attention"] = s.needs_attention
    return out


class EditIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    author: str = Field(min_length=1, max_length=80)


class RevertIn(BaseModel):
    version: int = Field(ge=1)
    author: str = Field(min_length=1, max_length=80)


class ApproveIn(BaseModel):
    approved: bool = True
    author: str = Field(min_length=1, max_length=80)


class GlossaryIn(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    preferred: str = Field(min_length=1, max_length=200)
    alternatives: list[str] = []
    avoid: list[str] = []
    context: str = ""
    category: str = "geral"
    case_sensitive: bool = False
    check: bool = True
    author: str = Field(min_length=1, max_length=80)


@app.get("/api/projects")
def list_projects() -> list[dict]:
    root = storage_root()
    out = []
    for d in sorted(root.iterdir()) if root.exists() else []:
        if (d / "app.db").exists() and _ID.match(d.name):
            info = ProjectStore(root, d.name).info
            out.append({"id": info["id"], "name": info["name"], "pages": info["pages"]})
    return out


@app.get("/api/projects/{project_id}")
def project(project_id: str) -> dict:
    store = _store(project_id)
    segs = store.segments()
    return {**store.info, "original_ok": store.verify_original(), "pages_with_segments": store.pages(),
            "attention": [s.id for s in segs if s.needs_attention],
            "approved": sum(s.approved for s in segs), "segments": len(segs),
            "has_translated_pdf": (store.dir / "output" / "traduzido.pdf").exists()}


@app.get("/api/projects/{project_id}/pages/{page}/segments")
def page_segments(project_id: str, page: int) -> list[dict]:
    return [_view(s) for s in _store(project_id).segments(page)]


@app.get("/api/projects/{project_id}/segments/{segment_id}/history")
def history(project_id: str, segment_id: str) -> list[dict]:
    return [asdict(v) for v in _store(project_id).history(_segment_id(segment_id))]


@app.put("/api/projects/{project_id}/segments/{segment_id}")
def edit(project_id: str, segment_id: str, body: EditIn) -> dict:
    store = _store(project_id)
    try:
        store.edit(_segment_id(segment_id), body.text, body.author)
    except GuardViolation as exc:
        raise HTTPException(422, {"message": "a notação não está intacta", "problems": exc.problems}) from exc
    except StoreError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _view(store.segment(segment_id))


@app.post("/api/projects/{project_id}/segments/{segment_id}/revert")
def revert(project_id: str, segment_id: str, body: RevertIn) -> dict:
    store = _store(project_id)
    try:
        store.revert(_segment_id(segment_id), body.version, body.author)
    except StoreError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _view(store.segment(segment_id))


@app.post("/api/projects/{project_id}/segments/{segment_id}/approve")
def approve(project_id: str, segment_id: str, body: ApproveIn) -> dict:
    store = _store(project_id)
    try:
        store.approve(_segment_id(segment_id), body.author, body.approved)
    except StoreError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _view(store.segment(segment_id))


@app.get("/api/projects/{project_id}/revisions")
def revisions(project_id: str, entity: str | None = None, entity_id: str | None = None) -> list[dict]:
    return _store(project_id).revisions(entity, entity_id)


@app.get("/api/projects/{project_id}/glossary")
def glossary(project_id: str) -> list[dict]:
    """Glossário em vigor (padrão + projeto), dizendo de onde vem cada termo."""
    store = _store(project_id)
    own = {e.term for e in Glossary.load(store.glossary_path).entries} if store.glossary_path.exists() else set()
    return [{**asdict(e), "source": "projeto" if e.term in own else "padrão"}
            for e in sorted(store.glossary().entries, key=lambda e: e.term.lower())]


@app.put("/api/projects/{project_id}/glossary")
def set_glossary(project_id: str, body: GlossaryIn) -> dict:
    store = _store(project_id)
    data = body.model_dump()
    author = data.pop("author")
    store.set_glossary_entry(GlossaryEntry(**data), author)
    return {"ok": True}


@app.get("/api/projects/{project_id}/pages/{page}/image")
def page_image(project_id: str, page: int, which: str = "original", dpi: int = 110) -> Response:
    """PNG da página do original ou do PDF traduzido montado (``output/traduzido.pdf``)."""
    store = _store(project_id)
    if which not in ("original", "translated") or not 40 <= dpi <= 200:
        raise HTTPException(400, "parâmetros inválidos")
    if which == "original":
        doc, index = pymupdf.open(store.original_path), page - 1
    else:
        path = store.dir / "output" / "traduzido.pdf"
        pages = (store.dir / "output" / "pages.txt")
        if not path.exists() or not pages.exists():
            raise HTTPException(404, "PDF traduzido ainda não montado")
        order = [int(x) for x in pages.read_text().split()]
        if page not in order:
            raise HTTPException(404, "página fora do PDF traduzido")
        doc, index = pymupdf.open(path), order.index(page)
    if not 0 <= index < doc.page_count:
        raise HTTPException(404, "página inexistente")
    png = doc[index].get_pixmap(dpi=dpi).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "rota inexistente")  # a interface nunca responde por uma rota da API
        return FileResponse(DIST / "index.html")

"""API local de revisão (FastAPI). Serve também a interface compilada (``frontend/dist``).

Executar (a partir de backend/):
    CHESSBOOK_STORAGE=/caminho/dos/projetos .venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8000

Só escuta em ``127.0.0.1``: os projetos contêm o livro e a tradução. Nenhum
caminho de arquivo vem do cliente; projetos e segmentos são identificados
por id validado.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.api.security import LocalOnlyMiddleware
from app.pipeline.segments import parse_pages
from app.store import assembly as assembler
from app.store import audit as audit_store
from app.store import creation, reprocess
from app.store import jobs as job_runner
from app.store.backup import create_backup, restore_backup
from app.store.project_store import MODES, GuardViolation, ProjectStore, SegmentView, StoreError
from app.translation.cache import TranslationCache
from app.translation.config import load_env_file, provider_from_env
from app.translation.engines import ENGINES, Engine, Prices, estimate, group_by_section, load_prices
from app.translation.engines import engine as engine_by_id
from app.translation.glossary import Glossary, GlossaryEntry
from app.translation.provider import ConfigurationError, TranslationProvider

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "frontend" / "dist"
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SEGMENT = re.compile(r"^p\d{1,5}-\d{1,7}$")

app = FastAPI(title="chessbook-translator", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(LocalOnlyMiddleware)  # DNS rebinding e CSRF (ver app/api/security.py)
load_env_file(ROOT / ".env")  # chave da Pollinations e CHESSBOOK_PRIVACY_MODE, sem sobrescrever o ambiente


def provider_for(eng: Engine) -> TranslationProvider:
    """Provedor do motor escolhido (substituído nos testes)."""
    return provider_from_env(name="pollinations", model=eng.model)


def prices() -> Prices:
    """Preços do catálogo da Pollinations, com cache de um dia (substituído nos testes)."""
    return load_prices(storage_root() / "pollinations-catalog.json")


def storage_root() -> Path:
    return Path(os.environ.get("CHESSBOOK_STORAGE") or ROOT / "storage")


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
    out["kept_as_image"] = s.kept_as_image
    return out


class AuthorIn(BaseModel):
    author: str = Field(min_length=1, max_length=80)


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


async def _receive(upload: UploadFile, suffix: str, limit: int) -> Path:
    """Grava o arquivo enviado em ``<armazenamento>/.envios``, com nome próprio e limite de tamanho."""
    import uuid

    folder = storage_root() / ".envios"
    folder.mkdir(parents=True, exist_ok=True)
    stem = creation.slug(Path(upload.filename or "arquivo").stem)[:40]
    path = folder / f"{uuid.uuid4().hex[:8]}-{stem}{suffix}"
    size = 0
    with path.open("wb") as out:
        while chunk := await upload.read(1 << 20):
            size += len(chunk)
            if size > limit:
                out.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, f"arquivo grande demais (máximo {limit // 1024 // 1024} MB)")
            out.write(chunk)
    return path


@app.get("/api/settings")
def settings() -> dict:
    """Como o aplicativo está configurado (a chave nunca sai do servidor: só se ela existe)."""
    import shutil

    env = os.environ
    return {
        "storage": str(storage_root()),
        "privacy_mode": env.get("CHESSBOOK_PRIVACY_MODE", "local_only"),
        "remote_allowed": env.get("CHESSBOOK_PRIVACY_MODE") == "remote_allowed",
        "pollinations_key": bool(env.get("POLLINATIONS_API_KEY")),
        "workers": job_runner.default_workers(),
        "tesseract": shutil.which("tesseract") is not None,
        "max_upload_mb": creation.MAX_BYTES // 1024 // 1024,
        "max_pages": creation.MAX_PAGES,
    }


@app.post("/api/projects")
async def create_project(file: UploadFile = File(...), name: str = Form(..., min_length=1, max_length=200),  # noqa: B008
                         project_id: str = Form("", max_length=64), ocr: str = Form("auto")) -> dict:
    """Novo projeto a partir do PDF enviado; a extração (e o OCR, se houver) roda em outro processo."""
    pid = project_id.strip() or creation.slug(name)
    path = await _receive(file, ".pdf", creation.MAX_BYTES)
    try:
        return creation.start(storage_root(), pid, name.strip(), path, ocr)
    except StoreError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/creations")
def creations() -> list[dict]:
    return creation.all_status(storage_root())


@app.get("/api/creations/{project_id}")
def creation_status(project_id: str) -> dict:
    if not _ID.match(project_id):
        raise HTTPException(400, "id de projeto inválido")
    try:
        return creation.status(storage_root(), project_id)
    except StoreError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/backups/restore")
async def restore(file: UploadFile = File(...), project_id: str = Form("", max_length=64)) -> dict:  # noqa: B008
    """Restaura um backup enviado; nunca sobrescreve um projeto existente."""
    path = await _receive(file, ".zip", 16 * 1024**3)
    try:
        store = restore_backup(path, storage_root(), project_id.strip() or None)
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)
    return {"id": store.id, "name": store.info["name"]}


@app.get("/api/projects/{project_id}/backup")
def backup(project_id: str) -> FileResponse:
    store = _store(project_id)
    path = create_backup(store, storage_root() / "backups")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.get("/api/projects/{project_id}/download")
def download(project_id: str) -> FileResponse:
    """O PDF traduzido montado."""
    store = _store(project_id)
    path = store.dir / "output" / "traduzido.pdf"
    if not path.exists():
        raise HTTPException(404, "PDF traduzido ainda não montado")
    return FileResponse(path, media_type="application/pdf", filename=f"{creation.slug(store.info['name'])}-pt.pdf")


@app.post("/api/projects/{project_id}/sync")
def sync(project_id: str, body: AuthorIn) -> dict:
    """Alinha o projeto com a extração do código atual, sem perder traduções (em outro processo:
    num livro digitalizado, refaz o OCR). O andamento sai em ``/reprocess``."""
    try:
        return reprocess.start(_store(project_id), "sync", body.author)
    except StoreError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/projects/{project_id}/reprocess")
def reprocess_status(project_id: str) -> dict:
    return reprocess.status(_store(project_id)) or {"state": "none"}


class FigurinesIn(BaseModel):
    labels: dict[str, str] = Field(min_length=1, max_length=200)
    author: str = Field(min_length=1, max_length=80)


@app.get("/api/projects/{project_id}/figurines")
def figurines(project_id: str) -> dict:
    """Desenhos de peça achados pelo OCR, agrupados: o usuário confirma qual figurina é cada grupo."""
    return reprocess.figurines(_store(project_id))


@app.put("/api/projects/{project_id}/figurines")
def set_figurines(project_id: str, body: FigurinesIn) -> dict:
    """Grava as figurinas confirmadas e relê o livro com elas (em outro processo), depois sincroniza."""
    store = _store(project_id)
    if not reprocess.figurines(store)["available"]:
        raise HTTPException(409, reprocess.figurines(store)["reason"])
    try:
        return reprocess.start(store, "figurines", body.author, body.labels)
    except StoreError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/projects/{project_id}")
def project(project_id: str) -> dict:
    store = _store(project_id)
    segs = store.segments()
    return {**store.info, "original_ok": store.verify_original(), "pages_with_segments": store.pages(),
            "attention": [s.id for s in segs if s.needs_attention],
            "approved": sum(s.approved for s in segs), "segments": len(segs),
            "has_translated_pdf": (store.dir / "output" / "traduzido.pdf").exists(),
            "spent": store.spent(), "spend_limit": store.spend_limit}


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


@app.post("/api/projects/{project_id}/pages/{page}/approve")
def approve_page(project_id: str, page: int, body: AuthorIn) -> dict:
    """Aprova o que a página tem de traduzido; recusas da proteção e falhas ficam de fora."""
    return _store(project_id).approve_page(page, body.author)


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


@app.get("/api/projects/{project_id}/quality")
def quality(project_id: str) -> dict:
    """Relatório da última montagem do PDF traduzido: o que cada página tem de pendente."""
    store = _store(project_id)
    path = store.dir / "output" / "relatorio.json"
    if not path.exists():
        raise HTTPException(404, "PDF traduzido ainda não montado")
    report = json.loads(path.read_text(encoding="utf-8"))
    pages = []
    for p in report["pages"]:
        blocks = p["blocks"]
        issues = {
            "not_written": [b["region_id"] for b in blocks if not b["placed"]],
            "review": [b["region_id"] for b in blocks if b["placed"] and b["scale"] < 0.85],
            "missing_text": p["missing_text"], "cut_text": p.get("cut_text", []),
            "missing_notation": p["missing_notation"], "overlaps": p.get("overlaps", []),
            "leftover_original": p["leftover_original"],
            "diagrams_changed": [x for x in p["diagram_changed_pct"] if x > 0],
        }
        reduced = [b["scale"] for b in blocks if b["placed"] and b["scale"] < 1]
        pages.append({"page": p["page"], "ok": p["ok"], "blocks": len(blocks), "reduced": len(reduced),
                      "min_scale": min(reduced, default=1.0), "issues": {k: v for k, v in issues.items() if v}})
    s = report["summary"]
    return {"summary": {k: s[k] for k in ("blocks", "blocks_placed", "blocks_expanded", "blocks_reduced",
                                          "diagrams_checked", "font_substitutions") if k in s},
            "pages_ok": len(s["pages_ok"]), "pages_total": len(s["pages"]), "pages": pages,
            "assembled_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")}


class Selection(BaseModel):
    """O que traduzir: páginas e modo (``MODES``); ``segment_ids`` só no modo ``ids``."""

    pages: str = Field(min_length=1, max_length=400)
    mode: str = "pending"
    segment_ids: list[str] = Field(default=[], max_length=5000)
    fresh: bool = False  # ignora o cache: pede uma tradução nova ao motor
    resume_of: int | None = None  # previsão da retomada de uma tarefa


class PagesIn(Selection):
    pass


class JobIn(Selection):
    engine: str
    budget: float = Field(gt=0, le=1000)
    author: str = Field(min_length=1, max_length=80)


class ResumeIn(BaseModel):
    author: str = Field(min_length=1, max_length=80)
    budget: float | None = Field(default=None, gt=0, le=1000)


class LimitIn(BaseModel):
    spend_limit: float | None = Field(default=None, ge=0, le=100_000)
    author: str = Field(min_length=1, max_length=80)


def _pages(store: ProjectStore, spec: str) -> set[int]:
    try:
        return parse_pages(spec, store.info["pages"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _selection(store: ProjectStore, body: Selection) -> tuple[set[int], str, frozenset[str], frozenset[str], bool]:
    """(páginas, modo, ids, segmentos a pular, ignorar cache) validados."""
    if body.resume_of is not None:
        try:
            old, pages, exclude = job_runner.resume_plan(store, body.resume_of)
        except StoreError as exc:
            raise HTTPException(409, str(exc)) from exc
        return pages, old.mode, frozenset(old.segment_ids or ()), exclude, old.fresh
    if body.mode not in MODES:
        raise HTTPException(400, f"modo desconhecido: {body.mode}")
    ids = frozenset(_segment_id(i) for i in body.segment_ids)
    if body.mode == "ids" and not ids:
        raise HTTPException(400, "nenhum segmento escolhido")
    pages = _pages(store, body.pages)
    return pages, body.mode, ids, frozenset(), body.fresh


def _estimates(store: ProjectStore, items: list, engines: tuple[Engine, ...], fresh: bool = False) -> list[dict]:
    groups = group_by_section(items)
    table = prices()
    glossary, style = store.glossary(), store.style
    cache = None if fresh else TranslationCache(store.dir / "cache.sqlite")
    out = []
    for eng in engines:
        e = estimate(groups, glossary, eng, table, style, cache, workers=job_runner.default_workers())
        price_in, price_out = table.by_model.get(eng.model, eng.fallback_price)
        out.append({"engine": eng.id, "label": eng.label, "model": eng.model, "status": eng.status, "note": eng.note,
                    "price_in_per_million": round(price_in * 1e6, 4), "price_out_per_million": round(price_out * 1e6, 4),
                    "segments_to_send": e.segments_to_send, "cached": e.cached, "calls": e.calls,
                    "input_tokens": e.input_tokens, "output_tokens": e.output_tokens, "cost": e.cost,
                    "cost_low": e.cost_low, "cost_high": e.cost_high, "minutes": e.minutes,
                    "price_source": e.price_source, "notes": e.notes})
    return out


@app.get("/api/engines")
def engines() -> list[dict]:
    return [{"id": e.id, "label": e.label, "model": e.model, "status": e.status, "note": e.note} for e in ENGINES]


@app.get("/api/modes")
def modes() -> dict:
    return MODES


@app.post("/api/projects/{project_id}/estimate")
def estimate_cost(project_id: str, body: PagesIn) -> dict:
    """Previsão de custo e tempo de cada motor para a seleção, antes de traduzir."""
    store = _store(project_id)
    pages, mode, ids, exclude, fresh = _selection(store, body)
    try:
        items, skipped = store.select_sources(pages, mode, ids, exclude)
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    in_pages = [s for s in store.segments() if s.page in pages]
    limit = store.spend_limit
    return {"pages": len(pages), "segments": len(in_pages), "mode": mode,
            "already_translated": sum(s.current is not None for s in in_pages),
            "notation_only": sum(s.status == "not_needed" for s in in_pages),
            "pending": len(store.sources(pages)), "selected": len(items), "skipped": skipped,
            "spent": store.spent(), "spend_limit": limit,
            "remaining": None if limit is None else round(limit - store.spent(), 5),
            "estimates": _estimates(store, items, ENGINES, fresh)}


@app.get("/api/projects/{project_id}/jobs")
def jobs(project_id: str) -> list[dict]:
    return [asdict(j) for j in job_runner.list_jobs(_store(project_id))]


@app.post("/api/projects/{project_id}/jobs")
def start_job(project_id: str, body: JobIn) -> dict:
    """Inicia a tradução com o motor escolhido; para sozinha se o gasto real passar do teto."""
    store = _store(project_id)
    try:
        eng = engine_by_id(body.engine)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    body.resume_of = None
    pages, mode, ids, _, fresh = _selection(store, body)
    try:
        provider = provider_for(eng)
    except ConfigurationError as exc:
        raise HTTPException(400, f"motor não configurado: {exc}") from exc
    try:
        items, _ = store.select_sources(pages, mode, ids)
        predicted = _estimates(store, items, (eng,), fresh)[0]["cost"]
        job = job_runner.start_job(store, eng, pages, body.pages, body.budget, body.author, provider, prices(),
                                   estimate=predicted, mode=mode, ids=ids, fresh=fresh)
    except StoreError as exc:
        raise HTTPException(409, str(exc)) from exc
    return asdict(job)


@app.post("/api/projects/{project_id}/jobs/{job_id}/resume")
def resume_job(project_id: str, job_id: int, body: ResumeIn) -> dict:
    """Continua uma tarefa interrompida, cancelada ou parada pelo teto, sem repetir o que ela já tratou."""
    store = _store(project_id)
    try:
        old, pages, exclude = job_runner.resume_plan(store, job_id)
        eng = engine_by_id(old.engine)
        provider = provider_for(eng)
        items, _ = store.select_sources(pages, old.mode, frozenset(old.segment_ids or ()), exclude)
        predicted = _estimates(store, items, (eng,), old.fresh)[0]["cost"]
        job = job_runner.resume_job(store, job_id, body.author, provider, prices(), eng, body.budget, predicted)
    except ConfigurationError as exc:
        raise HTTPException(400, f"motor não configurado: {exc}") from exc
    except (StoreError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return asdict(job)


@app.get("/api/projects/{project_id}/assembly")
def assembly_status(project_id: str) -> dict | None:
    """Última montagem do PDF traduzido: estado, andamento e se já há edições depois dela."""
    current = assembler.latest(_store(project_id))
    return asdict(current) if current else None


@app.post("/api/projects/{project_id}/assembly")
def start_assembly(project_id: str, body: AuthorIn) -> dict:
    """Monta o PDF com o texto atual; refaz só as partes de 20 páginas que mudaram."""
    try:
        return asdict(assembler.start(_store(project_id), body.author))
    except StoreError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/projects/{project_id}/assembly/cancel")
def cancel_assembly(project_id: str) -> dict | None:
    current = assembler.cancel(_store(project_id))
    return asdict(current) if current else None


@app.get("/api/projects/{project_id}/audit")
def last_audit(project_id: str) -> dict | None:
    return audit_store.last(_store(project_id))


@app.post("/api/projects/{project_id}/audit")
def run_audit(project_id: str) -> dict:
    """Confere a integridade do livro inteiro (original, extração, notação de cada versão, montagem)."""
    return audit_store.audit(_store(project_id))


@app.put("/api/projects/{project_id}/limits")
def set_limits(project_id: str, body: LimitIn) -> dict:
    """Teto de gasto do projeto inteiro (``null``: sem teto)."""
    store = _store(project_id)
    store.set_spend_limit(body.spend_limit, body.author)
    return {"spent": store.spent(), "spend_limit": store.spend_limit}


@app.post("/api/projects/{project_id}/jobs/{job_id}/cancel")
def cancel_job(project_id: str, job_id: int) -> dict:
    try:
        return asdict(job_runner.cancel_job(_store(project_id), job_id))
    except StoreError as exc:
        raise HTTPException(404, str(exc)) from exc


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "rota inexistente")  # a interface nunca responde por uma rota da API
        return FileResponse(DIST / "index.html")

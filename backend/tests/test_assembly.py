"""Montagem em partes: reaproveitamento, remontagem seletiva, retomada e tarefa pela API."""

import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

import app.api.main as api
from app.layout import assemble as asm
from app.pipeline.notation_pass import collect
from app.pipeline.segments import book_segments
from app.store.jobs import _run
from app.store.project_store import ProjectStore
from app.translation.engines import ENGINES, Prices
from app.translation.providers.fake import FakeProvider
from tests.fixtures import synthetic as syn


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Livro de 3 páginas iguais, traduzido pelo provedor falso, com partes de 1 página."""
    monkeypatch.setattr(asm, "CHUNK_PAGES", 1)
    page = pymupdf.open(stream=syn.build_page("fan_unicode").pdf_bytes, filetype="pdf")
    book = pymupdf.open()
    for _ in range(3):
        book.insert_pdf(page)
    pdf = tmp_path / "livro.pdf"
    book.save(pdf)
    doc = pymupdf.open(pdf)
    notation = collect(doc)
    store = ProjectStore.create(tmp_path / "storage", "livro", "Livro", pdf, 3, notation.style)
    store.add_book_segments([{"id": b.id, "page": b.page, "section": b.section.label,
                              "source": b.region.resolved.text, "kind": b.kind, "bold": b.region.main_mask,
                              "italic": b.region.italic_mask, "blocked": b.blocked}
                             for b in book_segments(notation, "Livro")])
    with store._db() as db:
        db.execute("INSERT INTO job (engine, model, pages, state, budget, author, created_at)"
                   " VALUES ('fake','fake-1','1-3','queued',1,'t','t')")
    _run(store, 1, store.sources({1, 2, 3}), ENGINES[0], FakeProvider(), Prices({}, "teste"))
    return store, notation


def _assemble(store, notation, **kw):
    return asm.assemble(store.original_path, store.export_result(), store.dir / "output", notation=notation, **kw)


def test_unchanged_parts_are_reused_and_only_the_edited_page_is_redone(project):
    store, notation = project
    first = _assemble(store, notation)
    assert (first["chunks"], first["chunks_reused"]) == (3, 0)
    assert first["blocks_placed"] == first["blocks"] > 0 and len(first["pages_ok"]) == 3
    pdf_before = (store.dir / "output" / "traduzido.pdf").read_bytes()
    again = _assemble(store, notation)
    assert again["chunks_reused"] == 3
    assert {k: v for k, v in again.items() if k != "chunks_reused"} == \
        {k: v for k, v in first.items() if k != "chunks_reused"}  # o relatório vem junto com a parte
    seg = next(s for s in store.segments(2) if s.current is not None)
    store.edit(seg.id, seg.current.text.replace("[PT-TESTE]", "[REVISTO]"), "revisor")
    edited = _assemble(store, notation)
    assert edited["chunks_reused"] == 2
    out = pymupdf.open(store.dir / "output" / "traduzido.pdf")
    assert "[REVISTO]" in out[1].get_text() and "[REVISTO]" not in out[0].get_text()
    assert out.page_count == 3 and (store.dir / "output" / "traduzido.pdf").read_bytes() != pdf_before
    assert len(list((store.dir / "output" / "partes").glob("c0001-*.pdf"))) == 1  # a parte antiga foi apagada


def test_interrupted_assembly_resumes_from_the_parts_already_done(project):
    store, notation = project
    calls = {"n": 0}

    def stop_after_first():
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(asm.AssemblyStopped):
        _assemble(store, notation, should_stop=stop_after_first)
    assert not (store.dir / "output" / "traduzido.pdf").exists()  # nada pela metade no lugar do PDF
    resumed = _assemble(store, notation)
    assert (resumed["chunks"], resumed["chunks_reused"]) == (3, 1)


def test_code_change_invalidates_parts(project, monkeypatch):
    store, notation = project
    _assemble(store, notation)
    monkeypatch.setattr(asm, "code_version", lambda: "outra-versao")
    assert _assemble(store, notation)["chunks_reused"] == 0


def test_assembly_job_through_the_api(project, monkeypatch):
    store, _ = project
    monkeypatch.setenv("CHESSBOOK_STORAGE", str(store.root))
    client = TestClient(api.app)
    assert client.get("/api/projects/livro/assembly").json() is None
    started = client.post("/api/projects/livro/assembly", json={"author": "eu"})
    assert started.status_code == 200 and started.json()["state"] == "running"
    assert client.post("/api/projects/livro/assembly", json={"author": "eu"}).status_code == 409
    end = time.time() + 120
    while (job := client.get("/api/projects/livro/assembly").json())["state"] == "running" and time.time() < end:
        time.sleep(0.2)
    assert job["state"] == "done", job
    assert job["summary"]["pages"] == 3 and job["summary"]["pages_ok"] == 3 and not job["outdated"]
    assert client.get("/api/projects/livro/quality").json()["pages_ok"] == 3
    assert client.get("/api/projects/livro/pages/2/image?which=translated").status_code == 200
    seg = next(s for s in store.segments(1) if s.current is not None)
    store.edit(seg.id, seg.current.text + " ", "revisor")
    assert client.get("/api/projects/livro/assembly").json()["outdated"]


def test_assembly_whose_process_died_is_reported_interrupted(project):
    from app.store import assembly

    store, _ = project
    with store._db() as db:
        db.execute("INSERT INTO assembly (state, pid, author, created_at) VALUES ('running', 999999, 'eu', 'x')")
    current = assembly.latest(store)
    assert current.state == "interrupted" and "reaproveita" in current.error

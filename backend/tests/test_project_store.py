"""Projeto em SQLite: original imutável, versões, histórico, edição protegida."""

import os

import pytest

from app.store.project_store import GuardViolation, ProjectStore, StoreError
from app.translation.glossary import GlossaryEntry
from app.translation.guard import protect
from tests.fixtures import synthetic as syn

SOURCE = "After 1.e4 e5 2.Nf3 the deflection on b5 wins."
MASKED_PT = "Depois de ⟦1⟧ o desvio em b5 vence."


def _result():
    p = protect(SOURCE)
    assert p.masked == "After ⟦1⟧ the deflection on b5 wins."
    return {"segments": [
        {"id": "p1-0", "page": 1, "section": "Chapter 1", "source": SOURCE, "status": "translated",
         "text": "Depois de 1.e4 e5 2.Nf3 o desvio em b5 vence.", "raw_translation": MASKED_PT,
         "warnings": [], "provider": "fake", "model": "m"},
        {"id": "p1-1", "page": 1, "section": "Chapter 1", "source": "1.e4 e5", "status": "not_needed",
         "text": "1.e4 e5", "raw_translation": None},
        {"id": "p2-2", "page": 2, "section": "Chapter 1", "source": "White wins.", "status": "needs_review",
         "text": None, "raw_translation": "x", "problems": ["marcador ausente"]},
    ]}


@pytest.fixture
def store(tmp_path):
    pdf = tmp_path / "livro.pdf"
    pdf.write_bytes(syn.build_page("fan_unicode").pdf_bytes)
    s = ProjectStore.create(tmp_path / "storage", "amostra", "Amostra", pdf, pages=1)
    s.import_translation(_result())
    return s


def test_original_is_a_read_only_verified_copy(store, tmp_path):
    assert store.verify_original()
    assert not os.access(store.original_path, os.W_OK) or os.geteuid() == 0  # root ignora permissões
    assert oct(store.original_path.stat().st_mode & 0o777) == "0o440"
    with pytest.raises(StoreError):
        ProjectStore.create(tmp_path / "storage", "amostra", "x", tmp_path / "livro.pdf", 1)


def test_import_keeps_machine_version_and_states(store):
    segs = {s.id: s for s in store.segments()}
    assert segs["p1-0"].current.kind == "machine" and segs["p1-0"].current.version == 1
    assert segs["p1-1"].current is None and segs["p1-1"].status == "not_needed"
    assert segs["p2-2"].needs_attention and segs["p2-2"].machine_problems == ["marcador ausente"]
    assert store.pages() == [
        {"page": 1, "segments": 2, "approved": 0, "translated": 1, "notation_only": 1},
        {"page": 2, "segments": 1, "approved": 0, "translated": 0, "notation_only": 0}]
    assert store.import_translation(_result()) == 0  # reimportar não duplica


def test_edit_is_versioned_and_logged(store):
    v = store.edit("p1-0", "Após 1.e4 e5 2.Nf3, o desvio em b5 vence.", "revisor")
    assert v.version == 2 and v.kind == "edit" and v.author == "revisor"
    log = store.revisions("segment", "p1-0")
    assert log[-1]["kind"] == "edit" and log[-1]["old_value"].startswith("Depois de")
    assert [h.kind for h in store.history("p1-0")] == ["machine", "edit"]


def test_edit_that_changes_notation_or_squares_is_refused(store):
    with pytest.raises(GuardViolation, match="alterado ou removido"):
        store.edit("p1-0", "Após 1.e4 e6 2.Nf3, o desvio em b5 vence.", "revisor")
    with pytest.raises(GuardViolation, match="casas"):
        store.edit("p1-0", "Após 1.e4 e5 2.Nf3, o desvio em b4 vence.", "revisor")
    assert len(store.history("p1-0")) == 1  # nada foi gravado


def test_revert_creates_a_new_version_and_approval_resets_on_change(store):
    store.edit("p1-0", "Após 1.e4 e5 2.Nf3, o desvio em b5 vence.", "revisor")
    store.approve("p1-0", "revisor")
    assert store.segment("p1-0").approved
    v = store.revert("p1-0", 1, "revisor")
    assert v.version == 3 and v.kind == "revert" and v.text.startswith("Depois de")
    assert not store.segment("p1-0").approved  # mudou o texto: precisa de nova aprovação
    with pytest.raises(StoreError):
        store.approve("p1-1", "revisor")  # sem tradução


def test_project_glossary_is_used_in_edit_checks_and_logged(store):
    store.set_glossary_entry(GlossaryEntry("deflection", "desvio", avoid=["atração"]), "revisor")
    v = store.edit("p1-0", "Após 1.e4 e5 2.Nf3, a atração em b5 vence.", "revisor")
    assert any(w.startswith("glossario_evitar:") for w in v.warnings)
    assert store.segment("p1-0").needs_attention
    assert store.revisions("glossary")[-1]["entity_id"] == "deflection"


def test_export_feeds_the_pdf_assembly(store):
    store.edit("p1-0", "Após 1.e4 e5 2.Nf3, o desvio em b5 vence.", "revisor")
    out = {s["id"]: s for s in store.export_result()["segments"]}
    assert out["p1-0"]["status"] == "reviewed"
    assert out["p1-0"]["raw_translation"] == "Após ⟦1⟧, o desvio em b5 vence."
    assert out["p1-1"]["status"] == "not_needed" and out["p1-1"]["text"] == "1.e4 e5"
    assert out["p2-2"]["status"] == "needs_review" and out["p2-2"]["text"] is None


def test_book_segments_start_pending_and_machine_never_overwrites_human(store):
    assert store.add_book_segments([{"id": "p3-0", "page": 3, "section": "Cap. 2", "source": "Black wins."}]) == 1
    assert [sid for _, s in store.sources({3}) for sid in [s.id]] == ["p3-0"]
    assert store.sources({1}) == []  # p1-0 já traduzido, p1-1 só notação
    store.edit("p1-0", "Após 1.e4 e5 2.Nf3, o desvio em b5 vence.", "revisor")
    with store._db() as db:
        outcome = store.record_machine(db, {"id": "p1-0", "status": "translated", "text": "Outra 1.e4 e5 2.Nf3 b5.",
                                            "raw_translation": "Outra ⟦1⟧ b5."})
    assert outcome == "kept_human" and store.segment("p1-0").current.kind == "edit"

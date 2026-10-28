"""Backup e restauração: tudo volta igual, e um pacote adulterado ou malicioso é recusado."""

import json
import zipfile

import pytest

from app.store.backup import create_backup, read_manifest, restore_backup
from app.store.project_store import ProjectStore, StoreError
from tests.fixtures import synthetic as syn


@pytest.fixture
def store(tmp_path):
    pdf = tmp_path / "livro.pdf"
    pdf.write_bytes(syn.build_page("fan_unicode").pdf_bytes)
    s = ProjectStore.create(tmp_path / "storage", "livro", "Livro", pdf, pages=1)
    s.add_book_segments([{"id": "p1-0", "page": 1, "source": "White wins after 1.e4 e5."}])
    with s._db() as db:
        s.record_machine(db, {"id": "p1-0", "status": "translated", "text": "As brancas vencem após 1.e4 e5.",
                              "raw_translation": "As brancas vencem após ⟦1⟧.", "warnings": []})
    s.edit("p1-0", "As brancas ganham após 1.e4 e5.", "revisor")
    (s.dir / "output").mkdir()
    (s.dir / "output" / "traduzido.pdf").write_bytes(b"%PDF-1.7 teste")
    return s


def test_backup_and_restore_bring_everything_back(store, tmp_path):
    (store.dir / "ocr.json").write_text("{}")
    (store.dir / "ocr-figurinas.json").write_text('[{"group": 2, "char": "♕"}]')  # decisão do usuário
    (store.dir / "ocr-passe1.json.gz").write_bytes(b"\x1f\x8b")
    path = create_backup(store, tmp_path / "backups")
    manifest = read_manifest(path)
    assert {"app.db", "original/livro.pdf", "output/traduzido.pdf", "ocr.json", "ocr-figurinas.json",
            "ocr-passe1.json.gz"} <= set(manifest["files"])
    restored = restore_backup(path, tmp_path / "outro-lugar")
    assert (restored.dir / "ocr-figurinas.json").read_text() == (store.dir / "ocr-figurinas.json").read_text()
    assert restored.verify_original() and restored.info["name"] == "Livro"
    assert [v.text for v in restored.history("p1-0")] == [v.text for v in store.history("p1-0")]
    assert restored.segment("p1-0").current.kind == "edit"
    assert any(r["kind"] == "restore" for r in restored.revisions("project"))
    copy = restore_backup(path, tmp_path / "storage", project_id="livro-copia")  # ao lado do original
    assert copy.info["id"] == "livro-copia" and copy.segment("p1-0").current.text.startswith("As brancas ganham")


def test_restore_never_overwrites(store, tmp_path):
    path = create_backup(store, tmp_path / "backups")
    with pytest.raises(StoreError, match="já existe"):
        restore_backup(path, tmp_path / "storage")


def _rewrite(path, tmp_path, change):
    """Copia o zip aplicando ``change(name, data)``: devolve (name, data) ou None para tirar a entrada."""
    out = tmp_path / "alterado.zip"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            got = change(info.filename, src.read(info.filename))
            if got:
                dst.writestr(got[0], got[1])
    return out


def test_tampered_file_is_refused(store, tmp_path):
    path = create_backup(store, tmp_path / "backups")
    bad = _rewrite(path, tmp_path, lambda n, d: (n, d + b"x") if n == "output/traduzido.pdf" else (n, d))
    with pytest.raises(StoreError, match="sha256"):
        restore_backup(bad, tmp_path / "novo")
    assert not (tmp_path / "novo" / "livro").exists()  # nada pela metade


def test_unexpected_or_traversal_entries_are_refused(store, tmp_path):
    path = create_backup(store, tmp_path / "backups")
    for evil in ("../fora.txt", "/etc/passwd", "original/../../x.pdf", "app.py"):
        def add(n, d, evil=evil):
            return (n, d)
        bad = _rewrite(path, tmp_path, add)
        with zipfile.ZipFile(bad, "a") as z:
            z.writestr(evil, b"oi")
        with pytest.raises(StoreError, match="não permitida"):
            restore_backup(bad, tmp_path / "novo")
    missing = _rewrite(path, tmp_path, lambda n, d: None if n == "manifest.json" else (n, d))
    with pytest.raises(StoreError, match="manifest"):
        restore_backup(missing, tmp_path / "novo")
    extra = _rewrite(path, tmp_path, lambda n, d: (n, json.dumps({**json.loads(d), "files": {}}).encode())
                     if n == "manifest.json" else (n, d))
    with pytest.raises(StoreError, match="manifesto"):
        restore_backup(extra, tmp_path / "novo")
    with pytest.raises(StoreError, match="id de projeto"):
        restore_backup(path, tmp_path / "novo", project_id="../x")

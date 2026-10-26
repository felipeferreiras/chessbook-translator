"""Ciclo do projeto pela API: enviar o PDF, acompanhar a criação, baixar, fazer backup e restaurar."""

import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

import app.api.main as api
from tests.fixtures import synthetic as syn


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESSBOOK_STORAGE", str(tmp_path / "storage"))
    return TestClient(api.app)


def _wait(client, pid, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/creations/{pid}").json()
        if st["state"] != "running":
            return st
        time.sleep(0.3)
    raise AssertionError("a criação não terminou")


def test_upload_creates_the_project_in_the_background(client, tmp_path):
    pdf = syn.build_page("fan_unicode").pdf_bytes
    r = client.post("/api/projects", data={"name": "Livro de Teste", "ocr": "auto"},
                    files={"file": ("../../meu livro.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "livro-de-teste" and r.json()["pages"] == 1
    st = _wait(client, "livro-de-teste")
    assert st["state"] == "done", st
    project = client.get("/api/projects/livro-de-teste").json()
    assert project["original_ok"] and project["segments"] > 0
    assert not list((tmp_path / "storage" / ".envios").glob("*"))  # o envio temporário foi apagado
    # o nome enviado ("../../meu livro.pdf") nunca vira caminho
    stored = [p.name for p in (tmp_path / "storage" / "livro-de-teste" / "original").iterdir()]
    assert len(stored) == 1 and stored[0].endswith(".pdf") and ".." not in stored[0]
    assert client.post("/api/projects", data={"name": "Livro de Teste"},
                       files={"file": ("x.pdf", pdf, "application/pdf")}).status_code == 400  # já existe


@pytest.mark.parametrize("content, message", [
    (b"not a pdf at all", "não é um PDF"),
    (b"%PDF-1.7\nlixo sem estrutura", "não pôde ser aberto"),
])
def test_bad_files_are_refused(client, content, message):
    r = client.post("/api/projects", data={"name": "Ruim"}, files={"file": ("x.pdf", content, "application/pdf")})
    assert r.status_code == 400 and message in r.json()["detail"]


def test_upload_size_limit(client, monkeypatch):
    from app.store import creation

    monkeypatch.setattr(creation, "MAX_BYTES", 1000)
    r = client.post("/api/projects", data={"name": "Grande"},
                    files={"file": ("x.pdf", b"%PDF-" + b"0" * 5000, "application/pdf")})
    assert r.status_code == 413


def test_settings_never_expose_the_key(client, monkeypatch):
    monkeypatch.setenv("POLLINATIONS_API_KEY", "sk_segredo_de_teste")
    out = client.get("/api/settings").json()
    assert out["pollinations_key"] is True and "sk_segredo" not in str(out)


def test_backup_download_and_restore_through_the_api(client, tmp_path):
    pdf = syn.build_page("fan_unicode").pdf_bytes
    client.post("/api/projects", data={"name": "Original"}, files={"file": ("a.pdf", pdf, "application/pdf")})
    assert _wait(client, "original")["state"] == "done"
    r = client.get("/api/projects/original/backup")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "manifest.json" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    refused = client.post("/api/backups/restore", files={"file": ("b.zip", r.content, "application/zip")})
    assert refused.status_code == 400 and "já existe" in refused.json()["detail"]
    ok = client.post("/api/backups/restore", data={"project_id": "copia"},
                     files={"file": ("b.zip", r.content, "application/zip")})
    assert ok.status_code == 200 and ok.json()["id"] == "copia"
    assert client.get("/api/projects/copia").json()["original_ok"]
    assert client.get("/api/projects/copia/download").status_code == 404  # ainda não montado
    sync = client.post("/api/projects/copia/sync", json={"author": "eu"}).json()
    assert sync["added"] == 0 and sync["removed"] == 0

"""API local protegida contra páginas da web abertas no mesmo navegador (DNS rebinding e CSRF)."""

import pytest
from fastapi.testclient import TestClient

import app.api.main as api
from app.store.project_store import ProjectStore
from tests.fixtures import synthetic as syn


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESSBOOK_STORAGE", str(tmp_path / "storage"))
    pdf = tmp_path / "livro.pdf"
    pdf.write_bytes(syn.build_page("fan_unicode").pdf_bytes)
    ProjectStore.create(tmp_path / "storage", "livro", "Livro", pdf, pages=1)
    return TestClient(api.app)


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "[::1]:8000", "localhost"])
def test_local_hosts_are_served(client, host):
    assert client.get("/api/projects", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "192.168.0.10:8000"])
def test_other_hosts_are_refused_even_for_reading(client, host):
    r = client.get("/api/projects/livro", headers={"Host": host})
    assert r.status_code == 403 and "host" in r.json()["detail"]


def test_configured_extra_host_is_allowed(client, monkeypatch):
    monkeypatch.setenv("CHESSBOOK_ALLOWED_HOSTS", "meu-notebook.local")
    assert client.get("/api/projects", headers={"Host": "meu-notebook.local:8000"}).status_code == 200


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_changes_from_another_site_are_refused(client, headers):
    for method, path in (("post", "/api/projects/livro/assembly/cancel"), ("post", "/api/projects/livro/audit"),
                         ("put", "/api/projects/livro/limits")):
        r = getattr(client, method)(path, headers=headers, json={"spend_limit": 1, "author": "x"})
        assert r.status_code == 403, (path, headers)


def test_changes_from_the_app_itself_are_accepted(client):
    r = client.put("/api/projects/livro/limits", json={"spend_limit": 2, "author": "eu"},
                   headers={"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200
    r = client.get("/api/projects")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"

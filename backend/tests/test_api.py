"""API local de revisão."""

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.store.project_store import ProjectStore
from tests.fixtures import synthetic as syn
from tests.test_project_store import _result


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESSBOOK_STORAGE", str(tmp_path / "storage"))
    pdf = tmp_path / "livro.pdf"
    pdf.write_bytes(syn.build_page("fan_unicode").pdf_bytes)
    ProjectStore.create(tmp_path / "storage", "amostra", "Amostra", pdf, pages=1).import_translation(_result())
    return TestClient(app)


def test_project_listing_and_summary(client):
    assert client.get("/api/projects").json() == [{"id": "amostra", "name": "Amostra", "pages": 1}]
    info = client.get("/api/projects/amostra").json()
    assert info["original_ok"] and info["segments"] == 3 and info["attention"] == ["p2-2"]


def test_edit_refused_with_reasons_then_accepted(client):
    bad = client.put("/api/projects/amostra/segments/p1-0", json={"text": "Após 1.e4 e6 2.Nf3, b5.", "author": "eu"})
    assert bad.status_code == 422 and "alterado ou removido" in bad.json()["detail"]["problems"][0]
    ok = client.put("/api/projects/amostra/segments/p1-0",
                    json={"text": "Após 1.e4 e5 2.Nf3, o desvio em b5 vence.", "author": "eu"})
    assert ok.status_code == 200 and ok.json()["current"]["kind"] == "edit"
    hist = client.get("/api/projects/amostra/segments/p1-0/history").json()
    assert [h["kind"] for h in hist] == ["machine", "edit"]


def test_revert_and_approve(client):
    client.put("/api/projects/amostra/segments/p1-0", json={"text": "Após 1.e4 e5 2.Nf3, o desvio em b5 vence.",
                                                            "author": "eu"})
    r = client.post("/api/projects/amostra/segments/p1-0/revert", json={"version": 1, "author": "eu"})
    assert r.json()["current"]["kind"] == "revert"
    a = client.post("/api/projects/amostra/segments/p1-0/approve", json={"author": "eu"})
    assert a.json()["approved"]
    assert client.post("/api/projects/amostra/segments/p1-1/approve", json={"author": "eu"}).status_code == 409
    kinds = [r["kind"] for r in client.get("/api/projects/amostra/revisions").json()]
    assert kinds == ["edit", "revert:v1", "approve"]


def test_glossary_merges_default_and_project_terms(client):
    client.put("/api/projects/amostra/glossary", json={"term": "deflection", "preferred": "desvio",
                                                         "avoid": ["atração"], "author": "eu"})
    entries = {e["term"]: e for e in client.get("/api/projects/amostra/glossary").json()}
    assert entries["deflection"]["source"] == "projeto" and entries["deflection"]["avoid"] == ["atração"]
    assert entries["outpost"]["source"] == "padrão"


def test_ids_are_validated_and_no_path_comes_from_the_client(client):
    assert client.get("/api/projects/..%2F..%2Fetc").status_code in (400, 404)
    assert client.get("/api/nao-existe").status_code == 404
    assert client.get("/api/projects/amostra/segments/../../x/history").status_code in (400, 404)
    assert client.get("/api/projects/inexistente").status_code == 404
    assert client.get("/api/projects/amostra/pages/1/image?which=x").status_code == 400
    img = client.get("/api/projects/amostra/pages/1/image")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get("/api/projects/amostra/pages/1/image?which=translated").status_code == 404

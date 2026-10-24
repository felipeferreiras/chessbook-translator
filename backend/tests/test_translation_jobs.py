"""Motores, estimativa de custo e tarefas de tradução pela API."""

import time

import pytest
from fastapi.testclient import TestClient

import app.api.main as api
from app.store.project_store import ProjectStore
from app.translation.engines import ENGINES, Prices, estimate, group_by_section, load_prices
from app.translation.glossary import Glossary
from app.translation.provider import BatchResult, Usage
from app.translation.providers.fake import FakeProvider
from app.translation.service import SourceSegment
from tests.fixtures import synthetic as syn

PRICES = Prices({e.model: (1e-6, 4e-6) for e in ENGINES}, "teste")
SEGMENTS = [
    {"id": "p1-0", "page": 1, "section": "Cap. 1", "source": "White wins after 1.e4 e5 2.Nf3 because of the pin."},
    {"id": "p1-1", "page": 1, "section": "Cap. 1", "source": "1.e4 e5"},
    {"id": "p2-0", "page": 2, "section": "Cap. 2", "source": "The outpost on d5 decides the game."},
    {"id": "p3-0", "page": 3, "section": "Cap. 2", "source": "Black draws with a waiting move."},
]


class CountingProvider(FakeProvider):
    """Como o falso, mas declara 1000 tokens de entrada e 500 de saída por chamada."""

    def translate_batch(self, request):
        r = super().translate_batch(request)
        return BatchResult(r.translations, r.provider, r.model, Usage(1000, 500, 0), r.raw_text)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESSBOOK_STORAGE", str(tmp_path / "storage"))
    pdf = tmp_path / "livro.pdf"
    pdf.write_bytes(syn.build_page("fan_unicode").pdf_bytes)
    ProjectStore.create(tmp_path / "storage", "livro", "Livro", pdf, pages=3).add_book_segments(SEGMENTS)
    monkeypatch.setattr(api, "prices", lambda: PRICES)
    monkeypatch.setattr(api, "provider_for", lambda eng: CountingProvider())
    return TestClient(api.app)


def _wait(client, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        job = next(j for j in client.get("/api/projects/livro/jobs").json() if j["id"] == job_id)
        if job["state"] not in ("queued", "running", "cancel_requested"):
            return job
        time.sleep(0.05)
    raise AssertionError("a tarefa não terminou")


def test_every_engine_is_listed_with_an_estimate(client):
    assert {e["id"] for e in client.get("/api/engines").json()} == {e.id for e in ENGINES}
    out = client.post("/api/projects/livro/estimate", json={"pages": "1-3"}).json()
    assert (out["segments"], out["pending"], out["notation_only"]) == (4, 3, 1)  # "1.e4 e5" já sai marcado
    by = {e["engine"]: e for e in out["estimates"]}
    assert set(by) == {e.id for e in ENGINES}
    sonnet = by["sonnet-5.5"]
    assert sonnet["segments_to_send"] == 3  # "1.e4 e5" é só notação: não vai ao provedor
    assert sonnet["calls"] == 2  # duas seções, dois lotes
    assert 0 < sonnet["cost_low"] < sonnet["cost"] < sonnet["cost_high"]
    assert by["qwen-3.8-27b"]["notes"]  # experimental avisa


def test_invalid_pages_are_refused(client):
    assert client.post("/api/projects/livro/estimate", json={"pages": "0-2"}).status_code == 400
    assert client.post("/api/projects/livro/estimate", json={"pages": "abc"}).status_code == 400
    assert client.post("/api/projects/livro/jobs", json={"engine": "nao-existe", "pages": "1", "budget": 1,
                                                         "author": "eu"}).status_code == 400


def test_job_translates_pending_segments_and_records_cost(client):
    job = client.post("/api/projects/livro/jobs", json={"engine": "sonnet-5.5", "pages": "1-3", "budget": 1.0,
                                                        "author": "eu"}).json()
    done = _wait(client, job["id"])
    assert done["state"] == "done" and done["done"] == done["total"] == 3
    assert done["tokens_in"] == 2000 and done["cost"] == pytest.approx(2000 * 1e-6 + 1000 * 4e-6)
    seg = client.get("/api/projects/livro/pages/2/segments").json()[0]
    assert seg["current"]["kind"] == "machine" and seg["current"]["text"].startswith("[PT-TESTE]")
    # nada pendente: estimar de novo não manda nada
    again = client.post("/api/projects/livro/estimate", json={"pages": "1-3"}).json()
    assert again["pending"] == 0 and all(e["segments_to_send"] == 0 for e in again["estimates"])


def test_job_stops_when_real_cost_passes_the_budget(client):
    job = client.post("/api/projects/livro/jobs", json={"engine": "opus-5.5", "pages": "1-3", "budget": 0.0001,
                                                        "author": "eu"}).json()
    done = _wait(client, job["id"])
    assert done["state"] == "stopped_budget" and done["done"] < done["total"]
    assert "passou do teto" in done["error"]


def test_engine_not_configured_is_reported(client, monkeypatch):
    from app.translation.provider import ConfigurationError

    def refuse(eng):
        raise ConfigurationError("defina CHESSBOOK_PRIVACY_MODE=remote_allowed")
    monkeypatch.setattr(api, "provider_for", refuse)
    r = client.post("/api/projects/livro/jobs", json={"engine": "sonnet-5.5", "pages": "1", "budget": 1,
                                                      "author": "eu"})
    assert r.status_code == 400 and "remote_allowed" in r.json()["detail"]


def test_estimate_matches_what_translation_sends():
    """A estimativa monta os mesmos lotes que a tradução (contagem de chamadas e segmentos)."""
    from app.translation.service import translate

    items = [(s["section"], SourceSegment(s["id"], s["source"])) for s in SEGMENTS]
    groups = group_by_section(items)
    est = estimate(groups, Glossary.load(), ENGINES[0], PRICES)
    provider = FakeProvider()
    for section, sources in groups:
        translate(sources, provider, Glossary.load(), section=section)
    assert est.calls == len(provider.calls)
    assert est.segments_to_send == sum(len(c.segments) for c in provider.calls)


def test_prices_fall_back_to_the_recorded_table_without_network(tmp_path):
    p = load_prices(tmp_path / "catalogo.json", fetch=False)
    assert "2026-10-24" in p.source and p.by_model["anthropic/claude-sonnet-5.5"] == (1.5e-6, 7.5e-6)

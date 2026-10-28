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
    monkeypatch.setattr(api, "provider_for", lambda eng: _as_engine(CountingProvider(), eng))
    return TestClient(api.app)


def _as_engine(provider, eng):
    """Faz o provedor falso usar o nome e o modelo do motor, como o real (as chaves do cache dependem deles)."""
    provider.name, provider.model = "pollinations", eng.model
    return provider


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


def test_job_stops_before_a_section_that_would_pass_the_budget(client):
    job = client.post("/api/projects/livro/jobs", json={"engine": "opus-5.5", "pages": "1-3", "budget": 0.0001,
                                                        "author": "eu"}).json()
    done = _wait(client, job["id"])
    assert done["state"] == "stopped_budget" and done["done"] == 0 and done["cost"] == 0
    assert "nada dele foi enviado" in done["error"]


def test_job_stops_when_real_cost_passes_the_budget(client, monkeypatch):
    class Expensive(FakeProvider):  # gasta muito mais do que a previsão
        def translate_batch(self, request):
            r = super().translate_batch(request)
            return BatchResult(r.translations, r.provider, r.model, Usage(100_000, 50_000, 0), r.raw_text)
    monkeypatch.setattr(api, "provider_for", lambda eng: Expensive())
    monkeypatch.setenv("CHESSBOOK_TRANSLATION_WORKERS", "1")  # em paralelo, as seções já enviadas também terminam
    job = client.post("/api/projects/livro/jobs", json={"engine": "sonnet-5.5", "pages": "1-3", "budget": 0.01,
                                                        "author": "eu"}).json()
    done = _wait(client, job["id"])
    assert done["state"] == "stopped_budget" and 0 < done["done"] < done["total"]
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


def _job(client, **body):
    payload = {"engine": "sonnet-5.5", "pages": "1-3", "budget": 1.0, "author": "eu", **body}
    r = client.post("/api/projects/livro/jobs", json=payload)
    assert r.status_code == 200, r.text
    return _wait(client, r.json()["id"])


def _store(tmp_path):
    return ProjectStore(tmp_path / "storage", "livro")


def test_orphaned_job_is_marked_interrupted_and_resumes_without_repeating(client, tmp_path):
    """Servidor morto no meio: a tarefa aparece interrompida e a retomada traduz só o que faltou."""
    store = _store(tmp_path)
    with store._db() as db:  # tarefa "rodando" num processo que já não existe, com p1-0 tratado
        db.execute("INSERT INTO job (engine, model, pages, state, total, done, budget, author, created_at, runner)"
                   " VALUES ('sonnet-5.5','anthropic/claude-sonnet-5.5','1-3','running',3,1,1.0,'eu','x','999999:morto')")
        db.execute("INSERT INTO job_segment VALUES (1, 'p1-0', 'translated')")
    jobs = client.get("/api/projects/livro/jobs").json()
    assert jobs[0]["state"] == "interrupted" and "processo" in jobs[0]["error"]
    # nova tarefa no mesmo projeto já não fica bloqueada pela órfã
    plan = client.post("/api/projects/livro/estimate", json={"pages": "1-3", "resume_of": 1}).json()
    assert plan["selected"] == 2  # p1-0 já tratado
    r = client.post("/api/projects/livro/jobs/1/resume", json={"author": "eu"})
    assert r.status_code == 200, r.text
    done = _wait(client, r.json()["id"])
    assert done["state"] == "done" and done["total"] == 2 and done["resumed_from"] == 1
    assert store.segment("p1-0").current is None  # o órfão foi pulado (o registro dele era só de teste)
    assert store.segment("p2-0").current.kind == "machine"
    assert client.post("/api/projects/livro/jobs/2/resume", json={"author": "eu"}).status_code == 409  # concluída


def test_other_process_needs_a_recent_heartbeat(tmp_path, client):
    """Processo vivo (pid 1 sempre existe) sem sinal recente: a tarefa é dada como interrompida."""
    from datetime import UTC, datetime, timedelta

    from app.store import jobs as runner

    store = _store(tmp_path)
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    new = datetime.now(UTC).isoformat()
    host = runner.socket.gethostname()
    with store._db() as db:
        for hb in (old, new):
            db.execute("INSERT INTO job (engine, model, pages, state, total, budget, author, created_at, runner,"
                       " heartbeat_at) VALUES ('sonnet-5.5','m','1','running',1,1.0,'eu','x',?,?)", (f"{host}:1:outro", hb))
    assert runner.recover_orphans(store) == [1]  # só a que não deu sinal há duas horas


def test_live_job_in_this_process_is_not_taken_for_an_orphan(client, tmp_path):
    from app.store import jobs as runner

    store = _store(tmp_path)
    with store._db() as db:
        db.execute("INSERT INTO job (engine, model, pages, state, total, budget, author, created_at, runner)"
                   " VALUES ('sonnet-5.5','m','1','running',1,1.0,'eu','x',?)", (runner._runner(),))
    runner._running.add((str(store.db_path), 1))
    try:
        assert runner.recover_orphans(store) == []
    finally:
        runner._running.discard((str(store.db_path), 1))
    assert runner.recover_orphans(store) == [1]


def test_project_spend_limit_caps_every_job(client, tmp_path):
    r = client.put("/api/projects/livro/limits", json={"spend_limit": 0.002, "author": "eu"})
    assert r.json() == {"spent": 0, "spend_limit": 0.002}
    done = _job(client, pages="1", budget=1.0)
    # teto da tarefa reduzido ao do projeto; a chamada real (0,003) passou dele
    assert done["budget"] == 0.002 and done["cost"] == pytest.approx(0.003)
    assert done["state"] == "stopped_budget"
    r = client.post("/api/projects/livro/jobs", json={"engine": "sonnet-5.5", "pages": "2-3", "budget": 1.0,
                                                      "author": "eu"})
    assert r.status_code == 409 and "teto de gasto do projeto" in r.json()["detail"]
    est = client.post("/api/projects/livro/estimate", json={"pages": "1-3"}).json()
    assert est["remaining"] < 0 and est["spent"] == pytest.approx(0.003)
    assert any(x["kind"] == "spend_limit" for x in client.get("/api/projects/livro/revisions").json())


def test_retranslate_modes_select_what_they_promise(client, tmp_path):
    store = _store(tmp_path)
    _job(client)
    est = client.post("/api/projects/livro/estimate", json={"pages": "1-3", "mode": "machine"}).json()
    assert est["selected"] == 3 and est["skipped"] == {"not_needed": 1}
    # o cache devolveria o mesmo texto de graça; "fresh" pede outra tradução e prevê o custo
    by = {e["engine"]: e for e in est["estimates"]}
    assert by["sonnet-5.5"]["segments_to_send"] == 0
    fresh = client.post("/api/projects/livro/estimate", json={"pages": "1-3", "mode": "machine", "fresh": True}).json()
    assert {e["engine"]: e for e in fresh["estimates"]}["sonnet-5.5"]["segments_to_send"] == 3
    # versão humana nunca é selecionada
    store.edit("p2-0", "O posto avançado em d5 decide a partida.", "revisor")
    est = client.post("/api/projects/livro/estimate", json={"pages": "1-3", "mode": "machine"}).json()
    assert est["selected"] == 2 and est["skipped"]["human"] == 1
    assert client.post("/api/projects/livro/estimate", json={"pages": "1-3", "mode": "problems"}).json()["selected"] == 0
    assert client.post("/api/projects/livro/estimate", json={"pages": "1-3", "mode": "glossary"}).json()["selected"] == 0
    assert client.post("/api/projects/livro/estimate", json={"pages": "1", "mode": "nada"}).status_code == 400
    assert client.post("/api/projects/livro/estimate", json={"pages": "1", "mode": "ids"}).status_code == 400
    ids = client.post("/api/projects/livro/estimate",
                      json={"pages": "1", "mode": "ids", "segment_ids": ["p3-0", "p2-0"]}).json()
    assert ids["selected"] == 1  # p2-0 é humano


def test_glossary_change_marks_only_segments_that_use_the_term(client, tmp_path):
    from app.translation.glossary import GlossaryEntry

    store = _store(tmp_path)
    _job(client)
    store.set_glossary_entry(GlossaryEntry("waiting move", "lance de espera alterado"), "eu")
    est = client.post("/api/projects/livro/estimate", json={"pages": "1-3", "mode": "glossary"}).json()
    assert est["selected"] == 1  # só p3-0 tem "waiting move"
    done = _job(client, mode="glossary")
    assert done["total"] == 1 and done["counts"] == {"translated": 1}
    assert [v.kind for v in store.history("p3-0")] == ["machine", "machine"]  # histórico preservado


def test_failed_retranslation_keeps_the_previous_translation(client, tmp_path, monkeypatch):
    from app.translation.provider import ProviderError

    store = _store(tmp_path)
    _job(client)
    before = store.segment("p3-0").current.text

    class Broken(FakeProvider):
        def translate_batch(self, request):
            raise ProviderError("Pollinations 500: fora do ar")
    monkeypatch.setattr(api, "provider_for", lambda eng: Broken())
    done = _job(client, mode="ids", pages="3", segment_ids=["p3-0"], fresh=True)
    assert done["state"] == "done_with_warnings" and done["counts"] == {"retry_failed": 1}
    seg = store.segment("p3-0")
    assert seg.current.text == before and seg.status == "translated" and not seg.needs_attention


def test_sections_run_in_parallel_and_the_budget_counts_reservations(tmp_path, client):
    """Três seções ao mesmo tempo; o teto vale para o conjunto (reserva do previsto antes de enviar)."""
    import threading

    from app.store.jobs import _run
    from app.translation.engines import engine

    pdf = tmp_path / "livro.pdf"
    store = ProjectStore.create(tmp_path / "outro", "par", "Paralelo", pdf, pages=3)
    store.add_book_segments([{"id": f"p{p}-0", "page": p, "section": f"Cap. {p}",
                              "source": f"The rook on the seventh rank wins in chapter {p}."} for p in range(1, 4)])
    live = {"now": 0, "max": 0}
    guard = threading.Lock()
    release = threading.Event()

    class Slow(CountingProvider):
        def translate_batch(self, request):
            with guard:
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
                if live["max"] >= 3:
                    release.set()
            release.wait(5)
            try:
                return super().translate_batch(request)
            finally:
                with guard:
                    live["now"] -= 1

    with store._db() as db:
        db.execute("INSERT INTO job (engine, model, pages, state, budget, author, created_at)"
                   " VALUES ('sonnet-5.5','m','1-3','queued',1.0,'t','t')")
    items, _ = store.select_sources({1, 2, 3})
    _run(store, 1, items, engine("sonnet-5.5"), _as_engine(Slow(), engine("sonnet-5.5")), PRICES, workers=3)
    job = runner_job(store, 1)
    assert live["max"] >= 3 and job.state == "done" and job.done == len(items)
    assert job.cost == pytest.approx(len({s for s, _ in items}) * (1000 * 1e-6 + 500 * 4e-6))
    # teto que cabe uma seção prevista, mas não duas ao mesmo tempo: a segunda não é enviada
    store2 = store
    with store2._db() as db:
        db.execute("UPDATE segment SET current_version=NULL, status='pending'")
        db.execute("INSERT INTO job (engine, model, pages, state, budget, author, created_at)"
                   " VALUES ('sonnet-5.5','m','1-3','queued',?,'t','t')", (0.0,))
    from app.translation.engines import estimate as est
    one = est([("Cap. 1", [items[0][1]])], store2.glossary(), engine("sonnet-5.5"), PRICES, store2.style).cost
    with store2._db() as db:
        db.execute("UPDATE job SET budget=? WHERE id=2", (one * 1.5,))
    release.set()
    _run(store2, 2, store2.select_sources({1, 2, 3})[0], engine("sonnet-5.5"),
         _as_engine(Slow(), engine("sonnet-5.5")), PRICES, fresh=True, workers=3)
    job = runner_job(store2, 2)
    assert job.state == "stopped_budget" and "nada dele foi enviado" in job.error and "em andamento" in job.error


def runner_job(store, job_id):
    from app.store.jobs import get_job

    return get_job(store, job_id)

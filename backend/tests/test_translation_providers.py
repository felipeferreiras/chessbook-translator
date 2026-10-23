"""Adaptadores de tradução: pedido montado e resposta lida com os tipos reais dos SDKs.

Nenhuma chamada de rede é feita: o cliente é substituído por um objeto que
registra os argumentos e devolve uma resposta construída com as classes do
próprio SDK. Isso verifica a montagem do pedido e a leitura da resposta, mas
não substitui um teste com chave real (ver docs/quality/plano-de-testes.md).
"""

import json
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaMessage
from google.genai import types as gtypes
from openai.types.chat import ChatCompletion
from openai.types.responses import Response

from app.translation.config import load_env_file, model_warnings, provider_from_env
from app.translation.glossary import Glossary
from app.translation.prompt import build_request
from app.translation.provider import OUTPUT_SCHEMA, ConfigurationError, ProviderError, ProviderRefusal, Segment
from app.translation.providers.anthropic_provider import AnthropicProvider
from app.translation.providers.gemini_provider import GeminiProvider
from app.translation.providers.openai_provider import OpenAIProvider
from app.translation.providers.pollinations_provider import BASE_URL, PollinationsProvider

SEGMENTS = [Segment("p1", "White wins after ⟦1⟧ because the king reaches e5."),
            Segment("p2", "Black is in zugzwang.", context_before="White wins after ⟦1⟧")]
OUT = json.dumps({"translations": [{"id": "p1", "text": "As brancas vencem após ⟦1⟧ porque o rei chega a e5."},
                                   {"id": "p2", "text": "As pretas estão em zugzwang."}]}, ensure_ascii=False)


def request():
    return build_request(SEGMENTS, Glossary.load(), section="Chapter 1")


class Recorder:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.response


# --- prompt -------------------------------------------------------------------

def test_prompt_contains_rules_glossary_and_masked_segments():
    req = request()
    assert "⟦1⟧" in req.system_prompt and "Não resuma" in req.system_prompt
    assert "zugzwang → zugzwang" in req.system_prompt and "queenside → ala da dama" in req.system_prompt
    payload = json.loads(req.user_payload)
    assert payload["section"] == "Chapter 1" and [s["id"] for s in payload["segments"]] == ["p1", "p2"]
    assert "♔" not in req.user_payload  # o provedor só recebe texto mascarado


def test_glossary_relevance_is_word_based():
    g = Glossary.load()
    terms = [e.term for e in g.relevant("The exchange on the queenside; a passed pawn.")]
    assert {"exchange", "queenside", "passed pawn"} <= set(terms)
    assert "draw" not in [e.term for e in g.relevant("withdrawal")]


# --- Anthropic ---------------------------------------------------------------

def anthropic_message(stop_reason="end_turn", text=OUT, model="claude-opus-5-5", details=None):
    content = [{"type": "text", "text": text}] if text is not None else []
    return BetaMessage.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": content,
        "stop_reason": stop_reason, "stop_sequence": None, "stop_details": details,
        "usage": {"input_tokens": 900, "output_tokens": 120, "cache_read_input_tokens": 700},
    })


def anthropic_provider(response, **kw):
    rec = Recorder(response)
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=rec)))
    return AnthropicProvider(client=client, **kw), rec


def test_anthropic_request_and_response():
    prov, rec = anthropic_provider(anthropic_message())
    out = prov.translate_batch(request())
    k = rec.kwargs
    assert k["model"] == "claude-opus-5-5" and k["max_tokens"] == 16000
    assert k["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
    assert k["fallbacks"] == "default" and k["betas"] == ["server-side-fallback-2026-07-01"]
    assert k["cache_control"] == {"type": "ephemeral"} and "temperature" not in k
    assert out.translations["p2"] == "As pretas estão em zugzwang."
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cached_input_tokens) == (900, 120, 700)


def test_anthropic_fallbacks_can_be_disabled():
    prov, rec = anthropic_provider(anthropic_message(), fallbacks=False)
    prov.translate_batch(request())
    assert "fallbacks" not in rec.kwargs and "betas" not in rec.kwargs


def test_anthropic_refusal_is_checked_before_content():
    prov, _ = anthropic_provider(anthropic_message("refusal", text=None,
                                                   details={"type": "refusal", "category": None, "explanation": None}))
    with pytest.raises(ProviderRefusal):
        prov.translate_batch(request())


def test_anthropic_truncated_output_is_an_error():
    prov, _ = anthropic_provider(anthropic_message("max_tokens", text='{"translations": ['))
    with pytest.raises(ProviderError, match="max_tokens"):
        prov.translate_batch(request())


def test_anthropic_fallback_model_is_reported():
    prov, _ = anthropic_provider(anthropic_message(model="claude-opus-4-8"))
    out = prov.translate_batch(request())
    assert out.model == "claude-opus-4-8" and out.notes


# --- OpenAI ------------------------------------------------------------------

def openai_response(content=None, status="completed", incomplete=None):
    content = content or [{"type": "output_text", "text": OUT, "annotations": []}]
    return Response.model_validate({
        "id": "resp_1", "object": "response", "created_at": 0, "model": "modelo-configurado",
        "status": status, "incomplete_details": incomplete,
        "output": [{"type": "message", "id": "m1", "role": "assistant", "status": "completed", "content": content}],
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
        "usage": {"input_tokens": 800, "output_tokens": 100, "total_tokens": 900,
                  "input_tokens_details": {"cached_tokens": 640, "cache_write_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    })


def openai_provider(response, **kw):
    rec = Recorder(response)
    client = SimpleNamespace(responses=SimpleNamespace(create=rec))
    return OpenAIProvider(model="modelo-configurado", client=client, **kw), rec


def test_openai_request_and_response():
    prov, rec = openai_provider(openai_response(), reasoning_effort="medium")
    out = prov.translate_batch(request())
    k = rec.kwargs
    assert k["model"] == "modelo-configurado" and k["store"] is False
    assert k["text"]["format"] == {"type": "json_schema", "name": "translations", "schema": OUTPUT_SCHEMA, "strict": True}
    assert k["instructions"].startswith("Você é tradutor") and k["reasoning"] == {"effort": "medium"}
    assert out.translations["p1"].startswith("As brancas")
    assert out.usage.cached_input_tokens == 640


def test_openai_refusal_and_incomplete():
    prov, _ = openai_provider(openai_response(content=[{"type": "refusal", "refusal": "não"}]))
    with pytest.raises(ProviderRefusal):
        prov.translate_batch(request())
    prov, _ = openai_provider(openai_response(status="incomplete", incomplete={"reason": "max_output_tokens"}))
    with pytest.raises(ProviderError, match="max_output_tokens"):
        prov.translate_batch(request())


# --- Gemini ------------------------------------------------------------------

def gemini_response(text=OUT, finish=gtypes.FinishReason.STOP, block=None):
    return gtypes.GenerateContentResponse(
        candidates=[gtypes.Candidate(content=gtypes.Content(role="model", parts=[gtypes.Part(text=text)]),
                                     finish_reason=finish)],
        prompt_feedback=gtypes.GenerateContentResponsePromptFeedback(block_reason=block) if block else None,
        usage_metadata=gtypes.GenerateContentResponseUsageMetadata(
            prompt_token_count=850, candidates_token_count=110, cached_content_token_count=0),
        model_version="modelo-gemini",
    )


def gemini_provider(response):
    rec = Recorder(response)
    client = SimpleNamespace(models=SimpleNamespace(generate_content=rec))
    return GeminiProvider(model="modelo-gemini", client=client), rec


def test_gemini_request_and_response():
    prov, rec = gemini_provider(gemini_response())
    out = prov.translate_batch(request())
    cfg = rec.kwargs["config"]
    assert rec.kwargs["model"] == "modelo-gemini" and json.loads(rec.kwargs["contents"])["segments"]
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema == OUTPUT_SCHEMA
    assert cfg.system_instruction.startswith("Você é tradutor")
    assert out.translations["p2"] == "As pretas estão em zugzwang." and out.usage.input_tokens == 850


@pytest.mark.parametrize("kwargs, error", [
    ({"finish": gtypes.FinishReason.SAFETY}, ProviderRefusal),
    ({"block": gtypes.BlockedReason.SAFETY}, ProviderRefusal),
    ({"finish": gtypes.FinishReason.MAX_TOKENS}, ProviderError),
])
def test_gemini_blocks_and_truncation(kwargs, error):
    prov, _ = gemini_provider(gemini_response(**kwargs))
    with pytest.raises(error):
        prov.translate_batch(request())


def test_malformed_json_is_an_error():
    prov, _ = gemini_provider(gemini_response(text="Aqui está a tradução: ..."))
    with pytest.raises(ProviderError, match="JSON"):
        prov.translate_batch(request())


# --- Configuração -------------------------------------------------------------

def test_remote_providers_require_explicit_privacy_opt_in():
    with pytest.raises(ConfigurationError, match="remote_allowed"):
        provider_from_env({"CHESSBOOK_TRANSLATION_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "x"})


@pytest.mark.parametrize("env, message", [
    ({"CHESSBOOK_TRANSLATION_PROVIDER": "anthropic"}, "ANTHROPIC_API_KEY"),
    ({"CHESSBOOK_TRANSLATION_PROVIDER": "openai", "OPENAI_API_KEY": "x"}, "CHESSBOOK_OPENAI_MODEL"),
    ({"CHESSBOOK_TRANSLATION_PROVIDER": "gemini"}, "GEMINI_API_KEY"),
    ({"CHESSBOOK_TRANSLATION_PROVIDER": "gemini", "GEMINI_API_KEY": "x"}, "CHESSBOOK_GEMINI_MODEL"),
    ({"CHESSBOOK_TRANSLATION_PROVIDER": "deepl"}, "desconhecido"),
])
def test_missing_configuration_is_explicit(env, message):
    with pytest.raises(ConfigurationError, match=message):
        provider_from_env({"CHESSBOOK_PRIVACY_MODE": "remote_allowed", **env})


def test_configured_providers_are_built(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
    monkeypatch.setenv("OPENAI_API_KEY", "teste")
    monkeypatch.setenv("GEMINI_API_KEY", "teste")
    base = {"CHESSBOOK_PRIVACY_MODE": "remote_allowed", "ANTHROPIC_API_KEY": "teste",
            "OPENAI_API_KEY": "teste", "GEMINI_API_KEY": "teste"}
    a = provider_from_env({**base, "CHESSBOOK_TRANSLATION_PROVIDER": "anthropic", "CHESSBOOK_ANTHROPIC_FALLBACKS": "off"})
    assert (a.name, a.model, a.fallbacks) == ("anthropic", "claude-opus-5-5", False)
    o = provider_from_env({**base, "CHESSBOOK_TRANSLATION_PROVIDER": "openai", "CHESSBOOK_OPENAI_MODEL": "m-o"})
    g = provider_from_env({**base, "CHESSBOOK_TRANSLATION_PROVIDER": "gemini", "CHESSBOOK_GEMINI_MODEL": "m-g"})
    assert (o.name, o.model, g.name, g.model) == ("openai", "m-o", "gemini", "m-g")
    assert provider_from_env({}).name == "fake"  # padrão: nada sai da máquina


def test_env_file_does_not_override_environment(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comentário\nA=1\nB='dois'\nC=\n", encoding="utf-8")
    env = {"A": "já definido"}
    load_env_file(f, env)
    assert env == {"A": "já definido", "B": "dois"}


# --- Pollinations (API compatível com OpenAI) ---------------------------------



def chat_completion(content=OUT, finish="stop", refusal=None, model="openai/gpt-5.5"):
    return ChatCompletion.model_validate({
        "id": "c1", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "finish_reason": finish,
                     "message": {"role": "assistant", "content": content, "refusal": refusal}}],
        "usage": {"prompt_tokens": 700, "completion_tokens": 90, "total_tokens": 790,
                  "prompt_tokens_details": {"cached_tokens": 500}},
    })


def pollinations_provider(response, **kw):
    rec = Recorder(response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=rec)))
    return PollinationsProvider(model="openai/gpt-5.5", client=client, **kw), rec


def test_pollinations_request_and_response():
    prov, rec = pollinations_provider(chat_completion(), reasoning_effort="low")
    out = prov.translate_batch(request())
    k = rec.kwargs
    assert k["model"] == "openai/gpt-5.5" and k["reasoning_effort"] == "low"
    assert [m["role"] for m in k["messages"]] == ["system", "user"]
    assert k["response_format"]["type"] == "json_schema"
    assert k["response_format"]["json_schema"]["schema"] == OUTPUT_SCHEMA
    assert out.translations["p2"] == "As pretas estão em zugzwang."
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cached_input_tokens) == (700, 90, 500)


def test_pollinations_json_modes():
    prov, rec = pollinations_provider(chat_completion(), json_mode="object")
    prov.translate_batch(request())
    assert rec.kwargs["response_format"] == {"type": "json_object"}
    prov, rec = pollinations_provider(chat_completion("```json\n" + OUT + "\n```"), json_mode="none")
    out = prov.translate_batch(request())
    assert "response_format" not in rec.kwargs and out.translations["p1"].startswith("As brancas")


@pytest.mark.parametrize("kwargs, error", [
    ({"finish": "length"}, ProviderError),
    ({"finish": "content_filter"}, ProviderRefusal),
    ({"refusal": "não posso"}, ProviderRefusal),
    ({"content": "Safety: Safe\nCategories: None"}, ProviderError),  # saída típica de modelo de moderação
])
def test_pollinations_failures(kwargs, error):
    prov, _ = pollinations_provider(chat_completion(**kwargs))
    with pytest.raises(error):
        prov.translate_batch(request())


def test_pollinations_config_and_base_url():
    env = {"CHESSBOOK_PRIVACY_MODE": "remote_allowed", "CHESSBOOK_TRANSLATION_PROVIDER": "pollinations",
           "POLLINATIONS_API_KEY": "sk_teste", "CHESSBOOK_POLLINATIONS_MODEL": "google/gemini-3.8-flash"}
    p = provider_from_env(env)
    assert (p.name, p.model, p.json_mode) == ("pollinations", "google/gemini-3.8-flash", "schema")
    assert str(p.client.base_url).rstrip("/") == BASE_URL
    assert provider_from_env(env, model="openai/gpt-5.5").model == "openai/gpt-5.5"
    with pytest.raises(ConfigurationError, match="POLLINATIONS_API_KEY"):
        provider_from_env({k: v for k, v in env.items() if k != "POLLINATIONS_API_KEY"})
    with pytest.raises(ConfigurationError, match="CHESSBOOK_POLLINATIONS_JSON"):
        provider_from_env({**env, "CHESSBOOK_POLLINATIONS_JSON": "xml"})


def test_moderation_model_is_flagged():
    assert model_warnings("qwen/qwen3guard-gen-8b")
    assert model_warnings("openai/gpt-5.5") == []

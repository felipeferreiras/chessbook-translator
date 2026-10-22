"""Escolha do provedor de tradução a partir de variáveis de ambiente.

| Variável | Uso |
|---|---|
| ``CHESSBOOK_TRANSLATION_PROVIDER`` | ``anthropic`` · ``openai`` · ``gemini`` · ``fake`` |
| ``CHESSBOOK_PRIVACY_MODE`` | ``local_only`` (padrão) bloqueia provedores remotos; ``remote_allowed`` libera |
| ``ANTHROPIC_API_KEY`` · ``OPENAI_API_KEY`` · ``GEMINI_API_KEY`` | credenciais (nunca no código) |
| ``CHESSBOOK_ANTHROPIC_MODEL`` | padrão ``claude-opus-5-5`` |
| ``CHESSBOOK_ANTHROPIC_EFFORT`` | ``low``…``max``; padrão ``high`` |
| ``CHESSBOOK_ANTHROPIC_FALLBACKS`` | ``on`` (padrão) ou ``off`` |
| ``CHESSBOOK_OPENAI_MODEL`` | obrigatório para ``openai`` |
| ``CHESSBOOK_OPENAI_REASONING_EFFORT`` | opcional (para modelos com raciocínio) |
| ``CHESSBOOK_GEMINI_MODEL`` | obrigatório para ``gemini`` |
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from .provider import ConfigurationError, TranslationProvider

PROVIDERS = ("anthropic", "openai", "gemini", "fake")


def load_env_file(path: Path, environ: dict[str, str] | None = None) -> None:
    """Carrega ``CHAVE=valor`` de um arquivo .env sem sobrescrever o ambiente."""
    target = os.environ if environ is None else environ
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in target:
            target[key] = value


def _require(env: Mapping[str, str], key: str, why: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigurationError(f"defina {key} ({why})")
    return value


def provider_from_env(env: Mapping[str, str] | None = None, name: str | None = None) -> TranslationProvider:
    env = os.environ if env is None else env
    name = (name or env.get("CHESSBOOK_TRANSLATION_PROVIDER", "fake")).strip().lower()
    if name not in PROVIDERS:
        raise ConfigurationError(f"provedor desconhecido {name!r}; use um de {', '.join(PROVIDERS)}")
    if name == "fake":
        from .providers.fake import FakeProvider

        return FakeProvider()
    if env.get("CHESSBOOK_PRIVACY_MODE", "local_only").strip() != "remote_allowed":
        raise ConfigurationError(
            f"o provedor {name!r} envia texto para fora desta máquina; defina "
            "CHESSBOOK_PRIVACY_MODE=remote_allowed para autorizar"
        )
    if name == "anthropic":
        from .providers.anthropic_provider import DEFAULT_MODEL, AnthropicProvider

        _require(env, "ANTHROPIC_API_KEY", "chave da API Claude")
        return AnthropicProvider(
            model=env.get("CHESSBOOK_ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            effort=env.get("CHESSBOOK_ANTHROPIC_EFFORT", "high").strip() or "high",
            fallbacks=env.get("CHESSBOOK_ANTHROPIC_FALLBACKS", "on").strip().lower() != "off",
        )
    if name == "openai":
        from .providers.openai_provider import OpenAIProvider

        _require(env, "OPENAI_API_KEY", "chave da API OpenAI")
        model = _require(env, "CHESSBOOK_OPENAI_MODEL", "nome do modelo OpenAI a usar")
        return OpenAIProvider(model=model, reasoning_effort=env.get("CHESSBOOK_OPENAI_REASONING_EFFORT") or None)
    from .providers.gemini_provider import GeminiProvider

    if not (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")):
        raise ConfigurationError("defina GEMINI_API_KEY (chave da API Gemini)")
    return GeminiProvider(model=_require(env, "CHESSBOOK_GEMINI_MODEL", "nome do modelo Gemini a usar"))

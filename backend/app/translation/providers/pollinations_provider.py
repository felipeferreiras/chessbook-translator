"""Adaptador da Pollinations (gen.pollinations.ai), compatível com a API OpenAI.

Uma única chave ``sk_`` dá acesso a modelos de vários fornecedores pelo mesmo
endpoint (``openai/...``, ``google/...``, ``qwen/...``, ``anthropic/...``).
Usa o SDK oficial ``openai`` apontado para ``https://gen.pollinations.ai/v1``
e a rota Chat Completions, que a documentação da Pollinations (v0.3.0) declara
totalmente compatível, com saída estruturada.

Privacidade: o texto passa pela Pollinations e pelo fornecedor do modelo
escolhido. A documentação consultada não descreve a retenção de texto.

Modos de JSON (``CHESSBOOK_POLLINATIONS_JSON``):
* ``schema`` (padrão): ``response_format`` JSON Schema estrito;
* ``object``: só exige JSON válido, para modelos sem suporte a esquema;
* ``none``: sem ``response_format``; o JSON é extraído da resposta.
"""

from __future__ import annotations

from ..provider import (
    OUTPUT_SCHEMA,
    BatchResult,
    ProviderError,
    ProviderRefusal,
    TranslationRequest,
    Usage,
    parse_output,
)

BASE_URL = "https://gen.pollinations.ai/v1"
JSON_MODES = ("schema", "object", "none")


class PollinationsProvider:
    name = "pollinations"
    remote = True

    def __init__(self, model: str, api_key: str | None = None, json_mode: str = "schema",
                 reasoning_effort: str | None = None, max_tokens: int = 16000,
                 base_url: str = BASE_URL, client=None):
        if json_mode not in JSON_MODES:
            raise ValueError(f"json_mode deve ser um de {JSON_MODES}")
        if client is None:
            import openai

            client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.client = client
        self.model = model
        self.json_mode = json_mode
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens

    def request_kwargs(self, request: TranslationRequest) -> dict:
        kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_payload},
            ],
            "max_tokens": self.max_tokens,
        }
        if self.json_mode == "schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "translations", "schema": OUTPUT_SCHEMA, "strict": True},
            }
        elif self.json_mode == "object":
            kwargs["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs

    def translate_batch(self, request: TranslationRequest) -> BatchResult:
        import openai

        try:
            response = self.client.chat.completions.create(**self.request_kwargs(request))
        except openai.APIStatusError as exc:
            raise ProviderError(f"Pollinations {exc.status_code}: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(f"Pollinations: falha de conexão: {exc}") from exc
        if not response.choices:
            raise ProviderError("Pollinations não devolveu resposta")
        choice = response.choices[0]
        message = choice.message
        if getattr(message, "refusal", None):
            raise ProviderRefusal(f"o modelo recusou o pedido: {message.refusal}")
        if choice.finish_reason == "content_filter":
            raise ProviderRefusal("resposta bloqueada por filtro de conteúdo")
        usage = response.usage
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        billed = Usage(
            usage.prompt_tokens if usage else None,
            usage.completion_tokens if usage else None,
            getattr(details, "cached_tokens", None) if details else None,
        )
        if choice.finish_reason == "length":
            raise ProviderError("resposta cortada por limite de tokens; reduza o lote", billed)
        raw = message.content or ""
        try:
            translations = parse_output(raw, [s.id for s in request.segments])
        except ProviderError as exc:
            exc.usage = billed
            raise
        return BatchResult(
            translations=translations,
            provider=self.name,
            model=response.model or self.model,
            usage=billed,
            raw_text=raw,
        )

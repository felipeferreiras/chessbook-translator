"""Adaptador da API Claude (Anthropic), via SDK oficial ``anthropic``.

* Saída estruturada com ``output_config.format`` (JSON Schema).
* ``fallbacks: "default"`` (beta ``server-side-fallback-2026-07-01``): se o
  modelo recusar por política, a API reexecuta o pedido em outro modelo. Pode
  ser desligado com ``CHESSBOOK_ANTHROPIC_FALLBACKS=off``.
* Cache de prompt automático (``cache_control``) para o prefixo fixo
  (regras + glossário).
* A recusa é verificada em ``stop_reason`` antes de ler o conteúdo.
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

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"
    remote = True

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "high", fallbacks: bool = True,
                 max_tokens: int = 16000, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()  # chave via ANTHROPIC_API_KEY
        self.client = client
        self.model = model
        self.effort = effort
        self.fallbacks = fallbacks
        self.max_tokens = max_tokens

    def request_kwargs(self, request: TranslationRequest) -> dict:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_payload}],
            "output_config": {"effort": self.effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            "cache_control": {"type": "ephemeral"},
        }
        if self.fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    def translate_batch(self, request: TranslationRequest) -> BatchResult:
        import anthropic

        try:
            response = self.client.beta.messages.create(**self.request_kwargs(request))
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"Anthropic: falha de conexão: {exc}") from exc
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            raise ProviderRefusal(f"Anthropic recusou o pedido (categoria: {category})")
        if response.stop_reason == "max_tokens":
            raise ProviderError("resposta cortada por max_tokens; reduza o lote")
        raw = next((b.text for b in response.content if b.type == "text"), "")
        usage = response.usage
        notes = [f"servido por {response.model}"] if response.model != self.model else []
        return BatchResult(
            translations=parse_output(raw, [s.id for s in request.segments]),
            provider=self.name,
            model=response.model,
            usage=Usage(usage.input_tokens, usage.output_tokens, usage.cache_read_input_tokens),
            raw_text=raw,
            notes=notes,
        )

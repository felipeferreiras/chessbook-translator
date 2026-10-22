"""Adaptador da OpenAI (ChatGPT), via SDK oficial ``openai`` e Responses API.

* Saída estruturada com ``text.format`` do tipo ``json_schema`` estrito.
* ``store=False``: pede para a resposta não ser armazenada pela OpenAI para
  recuperação posterior (a retenção efetiva segue os termos da conta).
* O modelo não tem padrão: é obrigatório configurá-lo
  (``CHESSBOOK_OPENAI_MODEL``), para não fixar no código um nome que mude.
* Recusas e respostas incompletas viram erro explícito.
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


class OpenAIProvider:
    name = "openai"
    remote = True

    def __init__(self, model: str, reasoning_effort: str | None = None, max_output_tokens: int = 16000, client=None):
        if client is None:
            import openai

            client = openai.OpenAI()  # chave via OPENAI_API_KEY
        self.client = client
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens

    def request_kwargs(self, request: TranslationRequest) -> dict:
        kwargs: dict = {
            "model": self.model,
            "instructions": request.system_prompt,
            "input": request.user_payload,
            "max_output_tokens": self.max_output_tokens,
            "store": False,
            "text": {"format": {"type": "json_schema", "name": "translations", "schema": OUTPUT_SCHEMA,
                                "strict": True}},
        }
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        return kwargs

    def translate_batch(self, request: TranslationRequest) -> BatchResult:
        import openai

        try:
            response = self.client.responses.create(**self.request_kwargs(request))
        except openai.APIStatusError as exc:
            raise ProviderError(f"OpenAI {exc.status_code}: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(f"OpenAI: falha de conexão: {exc}") from exc
        for item in response.output or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise ProviderRefusal(f"OpenAI recusou o pedido: {part.refusal}")
        if response.status != "completed":
            reason = response.incomplete_details.reason if response.incomplete_details else response.status
            raise ProviderError(f"resposta incompleta da OpenAI: {reason}")
        raw = response.output_text
        usage = response.usage
        cached = usage.input_tokens_details.cached_tokens if usage and usage.input_tokens_details else None
        return BatchResult(
            translations=parse_output(raw, [s.id for s in request.segments]),
            provider=self.name,
            model=response.model,
            usage=Usage(usage.input_tokens if usage else None, usage.output_tokens if usage else None, cached),
            raw_text=raw,
        )

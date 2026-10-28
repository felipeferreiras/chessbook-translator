"""Adaptador do Google Gemini, via SDK oficial ``google-genai``.

* Saída estruturada com ``response_mime_type="application/json"`` e
  ``response_json_schema``.
* Chave via ``GEMINI_API_KEY`` (ou ``GOOGLE_API_KEY``), lida pelo próprio SDK.
* O modelo não tem padrão: é obrigatório configurá-lo
  (``CHESSBOOK_GEMINI_MODEL``).
* Bloqueios de segurança (``prompt_feedback.block_reason`` ou
  ``finish_reason`` diferente de STOP) viram erro explícito.
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


class GeminiProvider:
    name = "gemini"
    remote = True

    def __init__(self, model: str, max_output_tokens: int = 16000, client=None):
        if client is None:
            from google import genai

            client = genai.Client()
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens

    def config(self, request: TranslationRequest):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            response_mime_type="application/json",
            response_json_schema=OUTPUT_SCHEMA,
            max_output_tokens=self.max_output_tokens,
        )

    def translate_batch(self, request: TranslationRequest) -> BatchResult:
        from google.genai import errors

        try:
            response = self.client.models.generate_content(
                model=self.model, contents=request.user_payload, config=self.config(request)
            )
        except errors.APIError as exc:
            raise ProviderError(f"Gemini {exc.code}: {exc.message}") from exc
        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason:
            raise ProviderRefusal(f"Gemini bloqueou o pedido: {feedback.block_reason}")
        candidate = (response.candidates or [None])[0]
        if candidate is None:
            raise ProviderError("Gemini não devolveu candidatos")
        reason = str(candidate.finish_reason.value if hasattr(candidate.finish_reason, "value") else candidate.finish_reason)
        if reason in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"):
            raise ProviderRefusal(f"Gemini interrompeu a resposta: {reason}")
        if reason == "MAX_TOKENS":
            raise ProviderError("resposta cortada por limite de tokens; reduza o lote")
        if reason not in ("STOP", "None"):
            raise ProviderError(f"Gemini terminou com {reason}")
        raw = response.text or ""
        meta = response.usage_metadata
        return BatchResult(
            translations=parse_output(raw, [s.id for s in request.segments]),
            provider=self.name,
            model=response.model_version or self.model,
            usage=Usage(
                meta.prompt_token_count if meta else None,
                meta.candidates_token_count if meta else None,
                meta.cached_content_token_count if meta else None,
            ),
            raw_text=raw,
        )

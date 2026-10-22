"""Provedor local de teste: não traduz, só marca o texto.

Serve para testar o fluxo e o layout sem custo nem envio de dados. Nunca deve
ser confundido com tradução: cada texto sai com o prefixo ``[PT-TESTE]``.
"""

from __future__ import annotations

import json

from ..provider import BatchResult, TranslationRequest, Usage


class FakeProvider:
    name = "fake"
    model = "fake-1"
    remote = False

    def __init__(self, transform=None):
        self.transform = transform or (lambda s: f"[PT-TESTE] {s}")
        self.calls: list[TranslationRequest] = []

    def translate_batch(self, request: TranslationRequest) -> BatchResult:
        self.calls.append(request)
        translations = {s.id: self.transform(s.text) for s in request.segments}
        raw = json.dumps({"translations": [{"id": k, "text": v} for k, v in translations.items()]}, ensure_ascii=False)
        return BatchResult(translations, self.name, self.model, Usage(0, 0, 0), raw)

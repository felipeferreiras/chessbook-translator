"""Provedor local de teste: não traduz, só marca o texto.

Serve para testar o fluxo e o layout sem custo nem envio de dados. Nunca deve
ser confundido com tradução: cada texto sai com o prefixo ``[PT-TESTE]``.
"""

from __future__ import annotations

import json
import re

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


_WORD = re.compile(r"(?<![⟦\w<])([A-Za-z]{3,})(?![\w⟧>])")


class PseudoProvider(FakeProvider):
    """Pseudotradução local para testar o layout no livro inteiro sem custo.

    Alonga o texto como o português alonga o inglês (por padrão, uma letra a
    cada duas palavras: cerca de +8 %, acima da média medida de +2–3 %).
    Marcadores, marcas <b>/<i>, números, casas, símbolos e quebras ficam
    intactos, então a saída passa pela mesma proteção de uma tradução real.
    Nunca é tradução: serve só para ensaio de diagramação.
    """

    name = "pseudo"
    model = "pseudo-1"

    def __init__(self, every: int = 2):
        def lengthen(text: str) -> str:
            count = 0

            def grow(m: re.Match[str]) -> str:
                nonlocal count
                count += 1
                return m.group(1) + ("a" if count % every == 0 else "")
            return _WORD.sub(grow, text)
        super().__init__(transform=lengthen)

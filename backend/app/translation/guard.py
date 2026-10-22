"""Proteção da notação durante a tradução automática.

Antes de enviar um texto ao tradutor, cada trecho de notação é substituído por
um marcador opaco (``⟦1⟧``, ``⟦2⟧``...). O tradutor de prosa nunca vê os
lances. Na volta, a restauração exige que todos os marcadores estejam presentes
exatamente uma vez e que as referências a casas fora da notação ("o cavalo em
f3") sejam as mesmas do original. Qualquer divergência gera ``GuardViolation``:
o segmento vai para revisão em vez de ser aceito.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.chess.notation.lexer import AtomKind, lex

PLACEHOLDER_RE = re.compile(r"⟦(\d+)⟧")
SQUARE_RE = re.compile(r"(?<![\w])[a-h][1-8](?![\w])")
NUMBER_RE = re.compile(r"(?<![\w⟦])\d+(?![\w⟧])")


class GuardViolation(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Protected:
    original: str
    masked: str
    slots: dict[str, str]
    squares: Counter[str]
    numbers: Counter[str]


@dataclass
class Restored:
    text: str
    warnings: list[str] = field(default_factory=list)


def protect(text: str) -> Protected:
    lexed = lex(text)
    parts: list[str] = []
    slots: dict[str, str] = {}
    cursor = 0
    for span in lexed.spans:
        if not any(a.kind in (AtomKind.MOVE, AtomKind.SUSPICIOUS, AtomKind.DESCRIPTIVE) for a in span.atoms):
            continue
        key = str(len(slots) + 1)
        slots[key] = text[span.start:span.end]
        parts.append(text[cursor:span.start])
        parts.append(f"⟦{key}⟧")
        cursor = span.end
    parts.append(text[cursor:])
    masked = "".join(parts)
    prose = PLACEHOLDER_RE.sub(" ", masked)
    return Protected(
        original=text, masked=masked, slots=slots,
        squares=Counter(SQUARE_RE.findall(prose)), numbers=Counter(NUMBER_RE.findall(prose)),
    )


def restore(translated: str, protected: Protected) -> Restored:
    problems: list[str] = []
    found = Counter(PLACEHOLDER_RE.findall(translated))
    for key in protected.slots:
        if found[key] == 0:
            problems.append(f"marcador ⟦{key}⟧ ausente ({protected.slots[key]!r})")
        elif found[key] > 1:
            problems.append(f"marcador ⟦{key}⟧ duplicado")
    for key in found:
        if key not in protected.slots:
            problems.append(f"marcador desconhecido ⟦{key}⟧")
    prose = PLACEHOLDER_RE.sub(" ", translated)
    squares = Counter(SQUARE_RE.findall(prose))
    if squares != protected.squares:
        problems.append(
            f"casas na prosa divergem: original={dict(protected.squares)} tradução={dict(squares)}"
        )
    if problems:
        raise GuardViolation(problems)
    warnings: list[str] = []
    numbers = Counter(NUMBER_RE.findall(prose))
    if numbers != protected.numbers:
        warnings.append(f"números na prosa divergem: original={dict(protected.numbers)} tradução={dict(numbers)}")
    order = [int(k) for k in PLACEHOLDER_RE.findall(translated)]
    if order != sorted(order):
        warnings.append("ordem dos trechos de notação foi alterada pela tradução")
    text = PLACEHOLDER_RE.sub(lambda m: protected.slots[m.group(1)], translated)
    return Restored(text=text, warnings=warnings)

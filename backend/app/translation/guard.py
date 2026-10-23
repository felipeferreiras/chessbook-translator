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

from app.chess.notation.lexer import DEFAULT_STYLE, AtomKind, LexStyle, lex

PLACEHOLDER_RE = re.compile(r"⟦(\d+)⟧")
SQUARE_RE = re.compile(r"(?<![\w])[a-h][1-8](?![\w])")
NUMBER_RE = re.compile(r"(?<![\w⟦])\d+(?![\w⟧])")
# Símbolos de avaliação e anotação fora da notação ("△ ...", "+−" isolado).
SYMBOL_RE = re.compile(r"\+−|−\+|[⊙△□⇆∞±∓⩲⩱]")


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
    symbols: Counter[str] = field(default_factory=Counter)
    slot_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)  # posição no original


@dataclass
class Restored:
    text: str
    warnings: list[str] = field(default_factory=list)
    pieces: list[tuple[int, int, str]] = field(default_factory=list)  # (início, fim, marcador) no texto final


_NOTATION_KINDS = (AtomKind.MOVE, AtomKind.SUSPICIOUS, AtomKind.DESCRIPTIVE, AtomKind.ROUTE)


def _groups(span, text: str) -> list[list]:
    """Divide um trecho nos parênteses de prosa e nas quebras de linha.

    Os dois devem ficar visíveis ao tradutor. Uma quebra separa, por exemplo, o
    lance da partida em linha própria ("1 Bd1+!? Kh4??") da correção que vem
    na linha seguinte ("1...Kg6! was necessary"); num marcador único, o
    tradutor não teria como saber a qual dos dois a prosa se refere.
    """
    groups: list[list] = [[]]
    for atom in span.atoms:
        if atom.kind in (AtomKind.PAREN_OPEN, AtomKind.PAREN_CLOSE):
            groups.append([])
            continue
        if groups[-1] and "\n" in text[groups[-1][-1].end:atom.start]:
            groups.append([])
        groups[-1].append(atom)
    return [g for g in groups if g and any(a.kind in _NOTATION_KINDS for a in g)]


def protect(text: str, style: LexStyle = DEFAULT_STYLE) -> Protected:
    lexed = lex(text, style)
    parts: list[str] = []
    slots: dict[str, str] = {}
    ranges: dict[str, tuple[int, int]] = {}
    cursor = 0
    for span in lexed.spans:
        for group in _groups(span, text):
            start, end = group[0].start, group[-1].end
            key = str(len(slots) + 1)
            slots[key] = text[start:end]
            ranges[key] = (start, end)
            parts.append(text[cursor:start])
            parts.append(f"⟦{key}⟧")
            cursor = end
    parts.append(text[cursor:])
    masked = "".join(parts)
    prose = PLACEHOLDER_RE.sub(" ", masked)
    return Protected(
        original=text, masked=masked, slots=slots,
        squares=Counter(SQUARE_RE.findall(prose)), numbers=Counter(NUMBER_RE.findall(prose)),
        symbols=Counter(SYMBOL_RE.findall(prose)), slot_ranges=ranges,
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
    symbols = Counter(SYMBOL_RE.findall(prose))
    if symbols != protected.symbols:
        problems.append(
            f"símbolos de avaliação divergem: original={dict(protected.symbols)} tradução={dict(symbols)}"
        )
    # Números da prosa são dados (diagramas 1-21, exercícios 1/6, páginas, anos):
    # qualquer número a mais ou a menos bloqueia a aceitação.
    numbers = Counter(NUMBER_RE.findall(prose))
    if numbers != protected.numbers:
        diff = {k: (protected.numbers.get(k, 0), numbers.get(k, 0))
                for k in sorted(set(numbers) | set(protected.numbers), key=int)
                if protected.numbers.get(k, 0) != numbers.get(k, 0)}
        problems.append(
            "números na prosa divergem (número: original → tradução): "
            + ", ".join(f"{k}: {a} → {b}" for k, (a, b) in diff.items())
        )
    # Quebras e tabulações são estrutura (itens de índice, sumário, lance
    # destacado em linha própria). Perdê-las desloca palavras para o lance errado.
    for ch, name in (("\n", "quebras de linha"), ("\t", "tabulações")):
        if translated.count(ch) != protected.masked.count(ch):
            problems.append(f"{name} divergem: original={protected.masked.count(ch)} tradução={translated.count(ch)}")
    if not problems and "\n" in protected.masked:
        lines_src = [sorted(PLACEHOLDER_RE.findall(line)) for line in protected.masked.split("\n")]
        lines_out = [sorted(PLACEHOLDER_RE.findall(line)) for line in translated.split("\n")]
        if lines_src != lines_out:
            problems.append("trechos de notação mudaram de linha na tradução")
    if problems:
        raise GuardViolation(problems)
    warnings: list[str] = []
    order = [int(k) for k in PLACEHOLDER_RE.findall(translated)]
    if order != sorted(order):
        warnings.append("ordem dos trechos de notação foi alterada pela tradução")
    out: list[str] = []
    pieces: list[tuple[int, int, str]] = []
    cursor = length = 0
    for m in PLACEHOLDER_RE.finditer(translated):
        out.append(translated[cursor:m.start()])
        length += m.start() - cursor
        slot = protected.slots[m.group(1)]
        pieces.append((length, length + len(slot), m.group(1)))
        out.append(slot)
        length += len(slot)
        cursor = m.end()
    out.append(translated[cursor:])
    return Restored(text="".join(out), warnings=warnings, pieces=pieces)

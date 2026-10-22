"""Detecção da convenção de notação predominante num conjunto de textos.

A detecção é estatística e explicável: devolve as contagens que a sustentam.
Ela nunca é tratada como definitiva; a interface deve permitir que o usuário
confirme ou corrija a convenção por documento, capítulo ou região.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from .alphabets import ENGLISH_ONLY, FIGURINE, PORTUGUESE_ONLY, Convention
from .lexer import AtomKind, lex


@dataclass(frozen=True)
class ConventionReport:
    convention: Convention
    confident: bool
    evidence: dict[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


def detect_convention(texts: Iterable[str], min_evidence: int = 3) -> ConventionReport:
    counts: Counter[str] = Counter()
    for text in texts:
        for atom in lex(text).atoms:
            if atom.kind == AtomKind.DESCRIPTIVE:
                counts["descriptive"] += 1
            elif atom.kind == AtomKind.MOVE and atom.move and atom.move.piece_char:
                ch = atom.move.piece_char
                if ch in FIGURINE:
                    counts["figurine"] += 1
                elif ch in ENGLISH_ONLY:
                    counts["english_only_letter"] += 1
                elif ch in PORTUGUESE_ONLY:
                    counts["portuguese_only_letter"] += 1
                else:
                    counts["shared_letter"] += 1  # R ou B
    evidence = dict(counts)
    en, pt = counts["english_only_letter"], counts["portuguese_only_letter"]
    fig, desc = counts["figurine"], counts["descriptive"]
    notes: list[str] = []

    if desc and desc >= max(en, pt, fig):
        notes.append("notação descritiva detectada: conversão não suportada; preservar o original")
        return ConventionReport(Convention.DESCRIPTIVE, desc >= min_evidence, evidence, tuple(notes))
    if fig and fig >= en + pt:
        if en or pt:
            notes.append("há letras de peça junto com figurinas; confirmar a convenção dessas regiões")
        return ConventionReport(Convention.FIGURINE, fig >= min_evidence and not (en and pt), evidence, tuple(notes))
    if en and pt:
        notes.append("letras exclusivas do inglês e do português aparecem juntas; convenção mista")
        winner = Convention.ENGLISH if en > pt else Convention.PORTUGUESE
        return ConventionReport(winner if max(en, pt) >= 4 * min(en, pt) else Convention.UNDETERMINED, False, evidence, tuple(notes))
    if en:
        return ConventionReport(Convention.ENGLISH, en >= min_evidence, evidence, tuple(notes))
    if pt:
        return ConventionReport(Convention.PORTUGUESE, pt >= min_evidence, evidence, tuple(notes))
    if counts["shared_letter"]:
        notes.append("apenas R e B observados: R pode ser torre (inglês) ou rei (português)")
    return ConventionReport(Convention.UNDETERMINED, False, evidence, tuple(notes))

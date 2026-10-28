"""Capítulo e subseção de cada região, para dar contexto ao tradutor.

Títulos são reconhecidos pelo tamanho em relação ao corpo do texto (o tamanho
mais usado no livro), não por fontes de um livro específico:

* nível 1 (capítulo): 1,35× o corpo ou mais; títulos de nível 1 seguidos são
  um só ("Chapter 10" + "Rook versus Knight");
* nível 2 (subseção): 1,15× o corpo ou mais, em negrito.

Os dois precisam ser curtos (até duas linhas, 90 caracteres) e sem lances.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.chess.notation import AtomKind, lex
from app.chess.notation.lexer import LexStyle

from .notation_pass import Region

CHAPTER_RATIO = 1.35
SUBSECTION_RATIO = 1.15
MAX_HEADING_CHARS = 90


@dataclass(frozen=True)
class SectionInfo:
    chapter: str
    subsection: str = ""
    heading_level: int = 0  # 1 ou 2 se a própria região é um título

    @property
    def label(self) -> str:
        return f"{self.chapter} › {self.subsection}" if self.subsection else self.chapter


def body_size(regions: list[Region]) -> float:
    weight: Counter[float] = Counter()
    for r in regions:
        if r.layout is not None and r.role == "text":
            weight[r.layout.size] += len(r.resolved.text)
    return weight.most_common(1)[0][0] if weight else 10.0


def heading_level(region: Region, body: float, style: LexStyle) -> int:
    lay = region.layout
    text = region.resolved.text.strip()
    if lay is None or region.role != "text" or lay.lines > 2 or not text or len(text) > MAX_HEADING_CHARS:
        return 0
    if not any(ch.isalpha() for ch in text) or any(a.kind == AtomKind.MOVE for a in lex(text, style).atoms):
        return 0
    if lay.size >= body * CHAPTER_RATIO:
        return 1
    if lay.size >= body * SUBSECTION_RATIO and lay.bold:
        return 2
    return 0


def assign_sections(regions: list[Region], style: LexStyle, start: str = "") -> list[SectionInfo]:
    """Uma ``SectionInfo`` por região, na ordem de leitura de ``regions``."""
    body = body_size(regions)
    chapter, subsection = start, ""
    run_start: int | None = None  # início da sequência atual de títulos de capítulo
    out: list[SectionInfo] = []
    for r in regions:
        level = heading_level(r, body, style)
        title = " ".join(r.resolved.text.split())
        if level == 1:
            if run_start is None:
                run_start, chapter = len(out), title
            else:  # "Chapter 10" + "Rook versus Knight": um só capítulo, para todos os títulos dele
                chapter = f"{chapter} — {title}"
                out[run_start:] = [SectionInfo(chapter, "", o.heading_level) for o in out[run_start:]]
            subsection = ""
        else:
            if level == 2:
                subsection = title
            if r.role == "text":
                run_start = None
        out.append(SectionInfo(chapter, subsection, level))
    return out

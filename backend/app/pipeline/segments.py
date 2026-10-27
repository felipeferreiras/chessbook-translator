"""Segmentos do livro com id estável, seção e estilo: a unidade de tradução e de revisão.

O id é ``p{página}-{posição na página}`` (regiões de texto em ordem de
leitura). Ele não depende de quais páginas foram pedidas: o mesmo parágrafo
tem o mesmo id na tradução, na montagem, no relatório e no projeto.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.translation.service import SourceSegment

from .notation_pass import DocumentNotation, Region
from .sections import SectionInfo, assign_sections

# Marcas ao lado do diagrama: vez de jogar ("W", "B?") e tipo de exercício ("Play"). Não são traduzidas:
# o modelo as trocava de forma inconsistente ("W?" virou "As brancas?" e até "B?", que muda o sentido).
# bloco curto ilegível do OCR (rótulo, coordenada, marca): fica como na imagem sem pedir conferência
OCR_SHORT_MARK = "ocr: texto curto lido sem confiança"
DIAGRAM_LABEL = re.compile(r"^(?:[WB][?!]*|Play|Draw|Win)(?:\s+(?:[WB][?!]*|Play|Draw|Win))*$")


@dataclass
class BookSegment:
    id: str
    page: int
    region: Region
    section: SectionInfo

    @property
    def kind(self) -> str:
        if DIAGRAM_LABEL.match(self.region.resolved.text.strip()):
            return "label"
        return "heading" if self.section.heading_level else "paragraph"

    @property
    def blocked(self) -> str:
        """Motivo para não traduzir automaticamente (vazio se pode)."""
        if self.region.vector_glyphs:
            return (f"{self.region.vector_glyphs} glifos desenhados como vetor (lances sem texto extraível): "
                    "o bloco fica no original para revisão")
        text = self.region.resolved.text.strip()
        low = sum(f.startswith("ocr_baixa_confianca") for f in self.region.source_flags)
        if len(text) <= 12 and low:
            return f"{OCR_SHORT_MARK} (rótulo ou marca); fica como na imagem"
        words = len(text.split())
        if words and low / words >= 0.5:
            return "ocr: a maior parte do texto foi lida sem confiança (provavelmente não é texto); fica como na imagem"
        return ""

    @property
    def flags(self) -> list[str]:
        """Dúvidas sobre o texto de origem (OCR): o segmento pede conferência antes da aprovação."""
        return list(self.region.source_flags)

    def source(self) -> SourceSegment:
        r = self.region
        return SourceSegment(self.id, r.resolved.text, kind=self.kind, bold=tuple(r.main_mask),
                             italic=tuple(r.italic_mask))


def book_segments(notation: DocumentNotation, title: str = "", pages: set[int] | None = None) -> list[BookSegment]:
    """Segmentos de texto do livro (``notation`` do livro inteiro; ``pages`` só filtra a saída)."""
    text = [r for r in notation.regions if r.role == "text"]
    per_page: Counter[int] = Counter()
    out = []
    for region, section in zip(text, assign_sections(text, notation.style, title), strict=True):
        k = per_page[region.page]
        per_page[region.page] += 1
        if pages is None or region.page in pages:
            out.append(BookSegment(f"p{region.page}-{k}", region.page, region, section))
    return out


def parse_pages(spec: str, max_page: int) -> set[int]:
    """'21,438' ou '1-40,62' → conjunto de páginas, validado contra o tamanho do livro."""
    pages: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        a, sep, b = part.partition("-")
        if not a.isdigit() or (sep and not b.isdigit()):
            raise ValueError(f"intervalo inválido: {part!r}")
        lo, hi = int(a), int(b) if sep else int(a)
        if lo < 1 or hi > max_page or lo > hi:
            raise ValueError(f"páginas fora do livro (1–{max_page}): {part!r}")
        pages.update(range(lo, hi + 1))
    if not pages:
        raise ValueError("nenhuma página informada")
    return pages

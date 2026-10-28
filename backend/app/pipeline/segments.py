"""Segmentos do livro com id estável, seção e estilo: a unidade de tradução e de revisão.

O id é ``p{página}-{posição na página}`` (regiões de texto em ordem de
leitura). Ele não depende de quais páginas foram pedidas: o mesmo parágrafo
tem o mesmo id na tradução, na montagem, no relatório e no projeto.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.chess.notation import MoveStatus
from app.chess.notation.validate import ContextSource
from app.translation.service import SourceSegment

from .notation_pass import DocumentNotation, Region
from .sections import SectionInfo, assign_sections

# Marcas ao lado do diagrama: vez de jogar ("W", "B?") e tipo de exercício ("Play"). Não são traduzidas:
# o modelo as trocava de forma inconsistente ("W?" virou "As brancas?" e até "B?", que muda o sentido).
_CHECK_WARNINGS = {"check_marker_without_check", "missing_check_marker", "mate_marker_without_mate"}
# bloco curto ilegível do OCR (rótulo, coordenada, marca): fica como na imagem sem pedir conferência
OCR_SHORT_MARK = "ocr: texto curto lido sem confiança"
_MOVE_LIKE = re.compile(r"^\(?\d{1,3}\.|[a-h][1-8]")
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
        if self.region.role != "text":
            return "heading"  # título corrente da página
        return "heading" if self.section.heading_level else "paragraph"

    @property
    def blocked(self) -> str:
        """Motivo para não traduzir automaticamente (vazio se pode)."""
        if self.region.vector_glyphs:
            return (f"{self.region.vector_glyphs} glifos desenhados como vetor (lances sem texto extraível): "
                    "o bloco fica no original para revisão")
        text = self.region.resolved.text.strip()
        low = sum(f.startswith("ocr_baixa_confianca") for f in self.region.source_flags)
        # lance curto mal lido ("28...Belt!", "29.8xel") não é marca: fica à vista para corrigir
        if len(text) <= 12 and low and not _MOVE_LIKE.search(text):
            return f"{OCR_SHORT_MARK} (rótulo ou marca); fica como na imagem"
        words = len(text.split())
        if words and low / words >= 0.5:
            return "ocr: a maior parte do texto foi lida sem confiança (provavelmente não é texto); fica como na imagem"
        return ""

    @property
    def flags(self) -> list[str]:
        """Dúvidas sobre o texto de origem (OCR): o segmento pede conferência antes da aprovação.

        Num livro digitalizado, também o lance que a posição do diagrama desmente (lance impossível,
        sinal de xeque sem xeque ou xeque sem sinal): costuma ser casa ou símbolo mal lido.
        """
        flags = list(self.region.source_flags)
        analysis = self.region.analysis
        if not flags or analysis is None:
            return flags
        for m in analysis.moves:
            if m.context not in (ContextSource.FEN_PROPOSED, ContextSource.FEN_CONFIRMED, ContextSource.CONTINUATION):
                continue
            if m.status == MoveStatus.ILLEGAL:
                flags.append(f"ocr_lance_impossivel: '{m.atom.text}' não confere com a posição do diagrama acima"
                             " (casa ou peça mal lida? ou lance de outra variante)")
            elif m.status == MoveStatus.VALIDATED and set(m.warnings) & _CHECK_WARNINGS:
                flags.append(f"ocr_sinal_de_xeque: '{m.atom.text}' — o sinal de xeque não confere com a posição"
                             " (± lido como +, ou † perdido?)")
        return flags

    def source(self) -> SourceSegment:
        r = self.region
        return SourceSegment(self.id, r.resolved.text, kind=self.kind, bold=tuple(r.main_mask),
                             italic=tuple(r.italic_mask))


def book_segments(notation: DocumentNotation, title: str = "", pages: set[int] | None = None) -> list[BookSegment]:
    """Segmentos de texto do livro (``notation`` do livro inteiro; ``pages`` só filtra a saída)."""
    # o cabeçalho e o rodapé correntes também são traduzidos ("Chapter 1 — Candidate Moves");
    # o número de página sozinho fica como está (só notação/número: não precisa de tradução)
    text = [r for r in notation.regions if r.role in ("text", "header", "footer")]
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

"""Passagem de notação sobre um PDF: regiões, diagramas e validação encadeada.

Esta etapa não altera nada no documento. Ela produz, para cada região de
texto, o texto resolvido (glifos especiais trocados pelo que desenham), os
lances com seu estado de validação e as posições propostas dos diagramas.
É a base do relatório de diagnóstico e, depois, da tradução e do layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

from app.chess.diagrams.font_diagram import DiagramReading, read_font_diagram, side_from_label
from app.chess.notation import Context, Convention, RegionAnalysis, analyze_region
from app.chess.notation.convention import detect_convention, detect_style
from app.chess.notation.lexer import LexStyle
from app.extraction.font_profiles import (
    KNOWN_PROFILES,
    FontRole,
    ResolvedText,
    SpanText,
    profile_for,
    resolve_spans,
)
from app.extraction.lines import join as join_lines
from app.extraction.lines import vocabulary


@dataclass
class Region:
    page: int  # 1-based
    bbox: tuple[float, float, float, float]
    column: int
    resolved: ResolvedText
    main_mask: list[bool]
    analysis: RegionAnalysis | None = None
    role: str = "text"  # text | header | footer


@dataclass
class Diagram:
    page: int
    bbox: tuple[float, float, float, float]
    reading: DiagramReading
    label: str | None = None  # "1-21"
    white_to_move: bool | None = None
    exercise: bool = False

    @property
    def fen(self) -> str | None:
        if self.white_to_move is None:
            return None
        return self.reading.fen(self.white_to_move)


@dataclass
class DocumentNotation:
    regions: list[Region] = field(default_factory=list)
    diagrams: list[Diagram] = field(default_factory=list)
    convention: Convention = Convention.UNDETERMINED
    style: LexStyle = field(default_factory=LexStyle)
    evidence: dict[str, int] = field(default_factory=dict)


def _is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16) or "Bold" in span["font"]


def _block_parts(
    block: dict, vocab: set[str] | None = None
) -> tuple[list[SpanText], list[bool], list[str], pymupdf.Rect]:
    """Separa um bloco em texto (com negrito por caractere) e linhas de diagrama.

    Devolve também a caixa só do tabuleiro: o bloco pode incluir o cabeçalho
    da partida ("Alekhine – Yates / Hamburg 1910").
    """
    spans: list[SpanText] = []
    bold: list[bool] = []
    diagram_lines: list[str] = []
    board_rect = pymupdf.Rect()
    for line_no, line in enumerate(block["lines"]):
        line_diagram = []
        line_text: list[dict] = []
        for span in line["spans"]:
            prof = profile_for(span["font"])
            if prof is not None and prof.role == FontRole.DIAGRAM:
                line_diagram.append(span["text"])
                board_rect |= pymupdf.Rect(span["bbox"])
            else:
                line_text.append(span)
        if line_diagram:
            diagram_lines.append("".join(line_diagram))
        if line_text:
            if spans and line_no > 0:
                _join_previous(spans, bold, "".join(sp["text"] for sp in line_text).lstrip(), vocab or set())
                line_text = [dict(line_text[0], text=line_text[0]["text"].lstrip())] + line_text[1:]
            for span in line_text:
                spans.append(SpanText(span["text"], span["font"], bold=_is_bold(span)))
                bold.extend([_is_bold(span)] * len(span["text"]))
    return spans, bold, diagram_lines, board_rect


def _join_previous(spans: list[SpanText], bold: list[bool], next_line: str, vocab: set[str]) -> None:
    """Une a linha anterior à próxima conforme ``lines.join`` (hífen no fim da linha)."""
    while spans and spans[-1].text != spans[-1].text.rstrip():
        last = spans[-1]
        stripped = last.text.rstrip()
        del bold[len(bold) - (len(last.text) - len(stripped)):]
        spans[-1] = SpanText(stripped, last.font, last.bold, last.italic)
        if not stripped:
            spans.pop()
    if not spans:
        return
    previous = "".join(sp.text for sp in spans[-3:])
    separator, drop_hyphen = join_lines(previous, next_line, vocab)
    if drop_hyphen:
        last = spans[-1]
        spans[-1] = SpanText(last.text[:-1], last.font, last.bold, last.italic)
        bold.pop()
        if not spans[-1].text:
            spans.pop()
    if separator:
        spans.append(SpanText(separator, ""))
        bold.append(bold[-1] if bold else False)


def _main_mask(resolved: ResolvedText, raw_bold: list[bool]) -> list[bool]:
    return [raw_bold[i] if i < len(raw_bold) else False for i in resolved.origin]


def _order(blocks: list[dict], page: pymupdf.Page) -> list[tuple[int, dict]]:
    mid = page.rect.width / 2
    keyed = []
    for b in blocks:
        x0, y0, _x1, _ = b["bbox"]
        if y0 < 55:
            band, col = 0, 0
        elif y0 > page.rect.height - 45:
            band, col = 2, 0
        else:
            band, col = 1, 0 if x0 < mid - 5 else 1
        keyed.append(((band, col, y0, x0), col, b))
    keyed.sort(key=lambda k: k[0])
    return [(col, b) for _, col, b in keyed]


def collect(doc: pymupdf.Document, pages: range | None = None) -> DocumentNotation:
    """Extrai regiões e diagramas (sem validar ainda)."""
    result = DocumentNotation()
    page_numbers = list(pages or range(doc.page_count))
    # Vocabulário do próprio documento, para desfazer a hifenização de fim de linha.
    vocab = vocabulary([doc[p].get_text() for p in range(doc.page_count)])
    for pno in page_numbers:
        page = doc[pno]
        blocks = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
        labels: list[tuple[pymupdf.Rect, str]] = []
        for col, block in _order(blocks, page):
            spans, raw_bold, diagram_lines, board_rect = _block_parts(block, vocab)
            bbox = tuple(round(v, 1) for v in block["bbox"])
            if diagram_lines:
                board_bbox = tuple(round(v, 1) for v in board_rect)
                result.diagrams.append(Diagram(pno + 1, board_bbox, read_font_diagram(diagram_lines)))
            text = "".join(s.text for s in spans).strip()
            if not text:
                continue
            first_line = "".join(sp["text"] for sp in block["lines"][0]["spans"]).strip()
            if len(first_line) <= 6 and not diagram_lines:
                labels.append((pymupdf.Rect(block["bbox"]), first_line))
            resolved = resolve_spans(spans, KNOWN_PROFILES)
            role = "header" if block["bbox"][1] < 55 else "footer" if block["bbox"][1] > page.rect.height - 45 else "text"
            result.regions.append(Region(pno + 1, bbox, col, resolved, _main_mask(resolved, raw_bold), role=role))
        # Rótulos ao lado dos diagramas: número ("1-21") e vez de jogar ("W", "B?").
        for diagram in (d for d in result.diagrams if d.page == pno + 1):
            area = pymupdf.Rect(diagram.bbox)
            area.x0 -= 45
            for rect, text in labels:
                if area.intersects(rect) and rect.x1 <= diagram.bbox[0] + 20:
                    white, exercise = side_from_label(text)
                    if white is not None:
                        diagram.white_to_move, diagram.exercise = white, exercise
                    elif "-" in text and text.replace("-", "").isdigit():
                        diagram.label = text
    texts = [r.resolved.text for r in result.regions if r.role == "text"]
    result.style, result.evidence = detect_style(texts)
    report = detect_convention(texts)
    result.convention = report.convention
    result.evidence |= {f"convention:{k}": v for k, v in report.evidence.items()}
    return result


def validate(result: DocumentNotation) -> None:
    """Valida os lances em ordem de leitura, reiniciando a posição a cada diagrama."""
    events: list[tuple[tuple, str, object]] = []
    for r in result.regions:
        if r.role == "text":
            events.append(((r.page, r.column, r.bbox[1], 1), "region", r))
    for d in result.diagrams:
        events.append(((d.page, 0 if d.bbox[0] < 255 else 1, d.bbox[1], 0), "diagram", d))
    events.sort(key=lambda e: e[0])
    ctx = Context.unknown()
    for _, kind, item in events:
        if kind == "diagram":
            fen = item.fen  # type: ignore[union-attr]
            ctx = Context.from_proposed_fen(fen) if fen else Context.unknown()
            continue
        region: Region = item  # type: ignore[assignment]
        region.analysis = analyze_region(
            region.resolved.text, ctx, result.convention, style=result.style, main_mask=region.main_mask
        )
        ctx = region.analysis.end_context

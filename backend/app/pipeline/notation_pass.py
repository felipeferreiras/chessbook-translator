"""Passagem de notação sobre um PDF: regiões, diagramas e validação encadeada.

Esta etapa não altera nada no documento. Ela produz, para cada região de
texto, o texto resolvido (glifos especiais trocados pelo que desenham), os
lances com seu estado de validação e as posições propostas dos diagramas.
É a base do relatório de diagnóstico e, depois, da tradução e do layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

from app.chess.diagrams.font_diagram import RANK_LINE, DiagramReading, read_font_diagram, side_from_label
from app.chess.notation import AtomKind, Context, Convention, MoveStatus, RegionAnalysis, analyze_region, lex
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
class BlockLayout:
    """Geometria e estilo de um bloco de texto, para a montagem do PDF."""

    text_rect: tuple[float, float, float, float]  # caixa só do texto (sem tabuleiro)
    span_rects: list[tuple[float, float, float, float]]  # o que será apagado
    font: str
    size: float
    color: int
    bold: bool  # bloco inteiro em negrito
    italic: bool
    align: str  # left | justify | center | right
    indent: float  # recuo da primeira linha (pt)
    line_height: float  # distância entre linhas (pt)
    lines: int


@dataclass
class Region:
    page: int  # 1-based
    bbox: tuple[float, float, float, float]
    column: int
    resolved: ResolvedText
    main_mask: list[bool]  # negrito por caractere do texto resolvido (linha principal na notação)
    analysis: RegionAnalysis | None = None
    role: str = "text"  # text | header | footer
    layout: BlockLayout | None = None
    italic_mask: list[bool] = field(default_factory=list)  # itálico por caractere do texto resolvido
    vector_glyphs: int = 0  # contornos escuros dentro do texto: lances desenhados como vetor, sem texto extraível


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


def _is_italic(span: dict) -> bool:
    return bool(span["flags"] & 2) or "Italic" in span["font"] or "Oblique" in span["font"]


def _italic_chars(spans: list[SpanText]) -> list[bool]:
    """Itálico por caractere; separadores inseridos na junção herdam o anterior."""
    out: list[bool] = []
    for sp in spans:
        flag = sp.italic if sp.font else (out[-1] if out else False)
        out.extend([flag] * len(sp.text))
    return out


def visual_rows(lines: list[dict], tolerance: float = 2.0) -> list[list[dict]]:
    """Agrupa os objetos "linha" do PDF em linhas visuais.

    Geradores como o Calibre posicionam cada palavra de uma linha justificada
    como um objeto separado; juntá-los pela posição vertical recupera a linha
    que o leitor vê.
    """
    rows: list[list[dict]] = []
    for line in sorted(lines, key=lambda ln: ((ln["bbox"][1] + ln["bbox"][3]) / 2, ln["bbox"][0])):
        mid = (line["bbox"][1] + line["bbox"][3]) / 2
        if rows:
            last = rows[-1]
            last_mid = sum((ln["bbox"][1] + ln["bbox"][3]) / 2 for ln in last) / len(last)
            if abs(mid - last_mid) <= tolerance:
                last.append(line)
                continue
        rows.append([line])
    return [sorted(r, key=lambda ln: ln["bbox"][0]) for r in rows]


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
    rows = visual_rows(block["lines"])
    text_rows = [[sp for ln in row for sp in ln["spans"] if not _is_diagram_span(sp)] for row in rows]
    extents = [(min(sp["bbox"][0] for sp in r if sp["text"].strip()), max(sp["bbox"][2] for sp in r if sp["text"].strip()))
               for r in text_rows if any(sp["text"].strip() for sp in r)]
    full_x0 = min((e[0] for e in extents), default=0.0)
    full_x1 = max((e[1] for e in extents), default=0.0)
    prev_x1: float | None = None
    prev_tab = False
    for row in rows:
        row_diagram: list[str] = []
        row_text: list[dict] = []
        last_ink: float | None = None  # fim do último texto visível da linha
        pending_space = False  # o texto anterior terminava em espaço
        for line in row:
            for span in line["spans"]:
                if _is_diagram_span(span):
                    row_diagram.append(span["text"])
                    board_rect |= pymupdf.Rect(span["bbox"])
                    continue
                original = span["text"]
                if not original.strip():
                    pending_space = pending_space or last_ink is not None
                    continue
                if last_ink is not None:
                    gap = span["bbox"][0] - last_ink
                    if gap > TAB_GAP:
                        row_text.append(dict(span, text="\t"))  # coluna de tabela ou sumário
                    elif gap > 0.8 or pending_space or original[0].isspace():
                        row_text.append(dict(span, text=" "))
                row_text.append(dict(span, text=original.strip() if last_ink is not None else original.rstrip()))
                last_ink = span["bbox"][2]
                pending_space = original[-1].isspace()
        if row_diagram:
            diagram_lines.append("".join(row_diagram))
        if not any(sp["text"].strip() for sp in row_text):
            continue
        if spans:
            hard = prev_tab or (
                prev_x1 is not None and prev_x1 < full_x1 - HARD_BREAK_SLACK * max(1.0, full_x1 - full_x0))
            _join_previous(spans, bold, "".join(sp["text"] for sp in row_text).lstrip(), vocab or set(), hard)
            while row_text and not row_text[0]["text"].strip():
                row_text = row_text[1:]
            row_text = [dict(row_text[0], text=row_text[0]["text"].lstrip())] + row_text[1:]
        for span in row_text:
            spans.append(SpanText(span["text"], span["font"], bold=_is_bold(span), italic=_is_italic(span)))
            bold.extend([_is_bold(span)] * len(span["text"]))
        prev_x1 = max(sp["bbox"][2] for sp in row_text if sp["text"].strip())
        prev_tab = any(sp["text"] == "\t" for sp in row_text)
    return spans, bold, diagram_lines, board_rect


HARD_BREAK_SLACK = 0.15  # linha que termina antes de 85 % da largura: quebra forte
TAB_GAP = 15.0  # espaço horizontal (pt) entre textos de uma linha que indica coluna


def _is_diagram_span(span: dict) -> bool:
    prof = profile_for(span["font"])
    return prof is not None and prof.role == FontRole.DIAGRAM


def _join_previous(spans: list[SpanText], bold: list[bool], next_line: str, vocab: set[str],
                   hard_break: bool = False) -> None:
    """Une a linha anterior à próxima conforme ``lines.join`` (hífen no fim da linha).

    Uma linha que termina bem antes da margem direita do bloco (item de lista,
    entrada de índice) é unida com "\n", preservada na tradução e no layout.
    """
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
    if hard_break and not drop_hyphen and separator == " ":
        separator = "\n"
    if drop_hyphen:
        last = spans[-1]
        spans[-1] = SpanText(last.text[:-1], last.font, last.bold, last.italic)
        bold.pop()
        if not spans[-1].text:
            spans.pop()
    if separator:
        spans.append(SpanText(separator, ""))
        bold.append(bold[-1] if bold else False)


def _block_layout(block: dict) -> BlockLayout | None:
    text_spans = [sp for ln in block["lines"] for sp in ln["spans"] if not _is_diagram_span(sp) and sp["text"].strip()]
    if not text_spans:
        return None
    rows = [r for r in visual_rows(block["lines"])
            if any(not _is_diagram_span(sp) and sp["text"].strip() for ln in r for sp in ln["spans"])]
    # Só trechos com tinta: espaços soltos à esquerda criariam um recuo falso.
    inked = [[sp["bbox"] for ln in r for sp in ln["spans"] if sp["text"].strip()] for r in rows]
    lines = [{"bbox": (min(b[0] for b in r), min(b[1] for b in r), max(b[2] for b in r), max(b[3] for b in r))}
             for r in inked]
    rect = pymupdf.Rect()
    for sp in text_spans:
        rect |= pymupdf.Rect(sp["bbox"])
    weight: dict[tuple, int] = {}
    for sp in text_spans:
        key = (sp["font"], round(sp["size"], 1), sp["color"])
        weight[key] = weight.get(key, 0) + len(sp["text"])
    font, size, color = max(weight, key=weight.get)
    total = sum(len(sp["text"].strip()) for sp in text_spans)
    bold_chars = sum(len(sp["text"].strip()) for sp in text_spans if _is_bold(sp))
    italic_chars = sum(len(sp["text"].strip()) for sp in text_spans if _is_italic(sp))
    x0s = [ln["bbox"][0] for ln in lines]
    x1s = [ln["bbox"][2] for ln in lines]
    centers = [(a + b) / 2 for a, b in zip(x0s, x1s, strict=True)]
    # Linha única: a montagem decide se é centralizada, comparando com a coluna.
    if len(lines) > 1 and max(centers) - min(centers) < 3 and max(x0s) - min(x0s) > 3:
        align = "center"
    elif len(lines) >= 3 and sum(1 for x in x1s[:-1] if x > rect.x1 - 2) >= 0.7 * (len(lines) - 1):
        align = "justify"
    else:
        align = "left"
    indent = x0s[0] - min(x0s[1:]) if len(lines) > 1 and x0s[0] - min(x0s[1:]) > 3 else 0.0
    if len(lines) > 1:
        line_height = (lines[-1]["bbox"][1] - lines[0]["bbox"][1]) / (len(lines) - 1)
    else:
        line_height = size * 1.15
    return BlockLayout(
        text_rect=tuple(round(v, 2) for v in rect),
        span_rects=[tuple(sp["bbox"]) for sp in text_spans],
        font=font, size=float(size), color=int(color),
        bold=total > 0 and bold_chars / total > 0.9, italic=total > 0 and italic_chars / total > 0.9,
        align=align, indent=round(indent, 1), line_height=round(line_height, 2), lines=len(lines),
    )


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


def _vector_glyphs(page: pymupdf.Page) -> list[pymupdf.Point]:
    """Centros de contornos pequenos e escuros: glifos desenhados como vetor.

    No livro de amostra, lances em negrito itálico de alguns quadros foram
    convertidos em curvas (6 páginas). Eles não aparecem no texto extraído; o
    bloco que os contém não pode ser traduzido sem perder lances.
    """
    out = []
    for d in page.get_drawings():
        r, fill = d["rect"], d.get("fill")
        if d.get("type") in ("f", "fs") and fill and max(fill) < 0.3 and r.width < 15 and r.height < 15 \
                and len(d["items"]) > 3:
            out.append(pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    return out


def _diagram_rows(block: dict) -> list[tuple[str, pymupdf.Rect]]:
    """Linhas do tabuleiro do bloco, cada uma com sua caixa."""
    rows = []
    for row in visual_rows(block["lines"]):
        spans = [sp for ln in row for sp in ln["spans"] if _is_diagram_span(sp)]
        if spans:
            rect = pymupdf.Rect()
            for sp in spans:
                rect |= pymupdf.Rect(sp["bbox"])
            rows.append(("".join(sp["text"] for sp in spans), rect))
    return rows


def _split_boards(rows: list[tuple[str, pymupdf.Rect]]) -> list[tuple[list[str], pymupdf.Rect]]:
    """Separa tabuleiros empilhados num mesmo bloco: moldura, 8 fileiras, moldura.

    No livro de amostra, 21 blocos traziam 2 a 4 tabuleiros juntos e eram lidos
    como um só (16, 24 ou 32 fileiras), sem posição para nenhum deles.
    """
    boards: list[list[tuple[str, pymupdf.Rect]]] = []
    current: list[tuple[str, pymupdf.Rect]] = []
    ranks = 0
    for text, rect in rows:
        is_rank = bool(RANK_LINE.match(text.strip()))
        current.append((text, rect))
        if is_rank:
            ranks += 1
        elif ranks == 8:  # moldura de baixo: o tabuleiro está completo
            boards.append(current)
            current, ranks = [], 0
    if current:
        boards.append(current)
    out = []
    for board in boards:
        rect = pymupdf.Rect()
        for _, r in board:
            rect |= r
        out.append(([t for t, _ in board], rect))
    return out


def _merge_board_strips(diagrams: list[Diagram], page: int) -> None:
    """Junta a faixa de cima (só a moldura) ao tabuleiro logo abaixo dela.

    O PDF às vezes põe a moldura superior num bloco e o resto do tabuleiro no
    seguinte; lidos separados, viravam um "diagrama" sem fileiras e um
    tabuleiro sem moldura (7 casos no livro de amostra).
    """
    on_page = [d for d in diagrams if d.page == page]
    for strip in on_page:
        if not any("encontradas 0" in issue for issue in strip.reading.issues):
            continue
        below = next((d for d in on_page if d is not strip and abs(d.bbox[0] - strip.bbox[0]) < 15
                      and 0 <= d.bbox[1] - strip.bbox[3] < 6), None)
        if below is not None:
            merged = pymupdf.Rect(strip.bbox) | pymupdf.Rect(below.bbox)
            below.bbox = tuple(round(v, 1) for v in merged)
            diagrams.remove(strip)


def _split_around_board(block: dict, board: pymupdf.Rect) -> list[dict]:
    """Divide um bloco que tem texto acima e abaixo do tabuleiro em partes separadas.

    O PDF pode pôr no mesmo bloco a legenda acima do diagrama ("Bad Homburg
    1927"), as linhas do tabuleiro e o parágrafo abaixo dele. Como um bloco só,
    a área do texto cobriria o tabuleiro e a tradução seria escrita sobre ele
    (achado na montagem do livro inteiro, p. 19).
    """
    groups: dict[str, list[dict]] = {"above": [], "middle": [], "below": []}
    for line in block["lines"]:
        mid = (line["bbox"][1] + line["bbox"][3]) / 2
        groups["above" if mid < board.y0 else "below" if mid > board.y1 else "middle"].append(line)
    parts = []
    for key in ("above", "middle", "below"):
        if groups[key]:
            rect = pymupdf.Rect()
            for line in groups[key]:
                rect |= pymupdf.Rect(line["bbox"])
            parts.append(dict(block, lines=groups[key], bbox=tuple(rect)))
    return parts


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
        ink = _vector_glyphs(page)
        for col, whole in _order(blocks, page):
            _, _, diagram_lines, board_rect = _block_parts(whole, vocab)
            for lines, rect in _split_boards(_diagram_rows(whole)) if diagram_lines else []:
                result.diagrams.append(Diagram(pno + 1, tuple(round(v, 1) for v in rect), read_font_diagram(lines)))
            for block in _split_around_board(whole, board_rect) if diagram_lines else [whole]:
                spans, raw_bold, part_diagram, _ = _block_parts(block, vocab)
                bbox = tuple(round(v, 1) for v in block["bbox"])
                text = "".join(s.text for s in spans).strip()
                if not text:
                    continue
                first_line = "".join(sp["text"] for sp in block["lines"][0]["spans"]).strip()
                if len(first_line) <= 6 and not part_diagram:
                    labels.append((pymupdf.Rect(block["bbox"]), first_line))
                resolved = resolve_spans(spans, KNOWN_PROFILES)
                role = ("header" if block["bbox"][1] < 55
                        else "footer" if block["bbox"][1] > page.rect.height - 45 else "text")
                layout = _block_layout(block)
                area = pymupdf.Rect(layout.text_rect if layout else block["bbox"]) + (-2, -2, 2, 2)
                result.regions.append(Region(pno + 1, bbox, col, resolved, _main_mask(resolved, raw_bold), role=role,
                                             layout=layout, italic_mask=_main_mask(resolved, _italic_chars(spans)),
                                             vector_glyphs=sum(area.contains(c) for c in ink)))
        _merge_board_strips(result.diagrams, pno + 1)
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


def _following_diagram(events: list[tuple[tuple, str, object]], pos: int, key: tuple, style: LexStyle) -> str | None:
    """FEN do próximo diagrama na mesma página e coluna, se nenhum lance vier antes dele."""
    for other_key, kind, item in events[pos + 1:]:
        if other_key[:2] != key[:2]:
            return None
        if kind == "diagram":
            return item.fen  # type: ignore[union-attr]
        if any(a.kind == AtomKind.MOVE for a in lex(item.resolved.text, style).atoms):  # type: ignore[union-attr]
            return None
    return None


def _count(analysis: RegionAnalysis, status: MoveStatus) -> int:
    return sum(m.status == status for m in analysis.moves)


def _score(analysis: RegionAnalysis) -> int:
    return _count(analysis, MoveStatus.VALIDATED)


def validate(result: DocumentNotation) -> None:
    """Valida os lances em ordem de leitura, reiniciando a posição a cada diagrama.

    A ordem usa o centro vertical de cada região e de cada tabuleiro: a caixa
    dos glifos do tabuleiro começa acima da moldura visível, e a última linha
    do parágrafo de cima pode cair dentro dela (p. 177).
    """
    events: list[tuple[tuple, str, object]] = []
    for r in result.regions:
        if r.role == "text":
            events.append(((r.page, r.column, (r.bbox[1] + r.bbox[3]) / 2, 1), "region", r))
    for d in result.diagrams:
        events.append(((d.page, 0 if d.bbox[0] < 255 else 1, (d.bbox[1] + d.bbox[3]) / 2, 0), "diagram", d))
    events.sort(key=lambda e: e[0])
    ctx = Context.unknown()
    for pos, (key, kind, item) in enumerate(events):
        if kind == "diagram":
            fen = item.fen  # type: ignore[union-attr]
            ctx = Context.from_proposed_fen(fen) if fen else Context.unknown()
            continue
        region: Region = item  # type: ignore[assignment]
        region.analysis = analyze_region(
            region.resolved.text, ctx, result.convention, style=result.style, main_mask=region.main_mask
        )
        following = _following_diagram(events, pos, key, result.style)
        if following is not None and region.analysis.moves:
            # Texto antes do próprio diagrama ("1 ♔g3? ..." acima do diagrama 1-8):
            # vale a posição do diagrama seguinte se ela explica melhor os lances.
            alt = analyze_region(region.resolved.text, Context.from_proposed_fen(following), result.convention,
                                 style=result.style, main_mask=region.main_mask)
            if _score(alt) > _score(region.analysis) and _count(alt, MoveStatus.ILLEGAL) <= _count(
                    region.analysis, MoveStatus.ILLEGAL):
                for m in alt.moves:
                    if m.status != MoveStatus.NO_CONTEXT:
                        m.warnings.append("context_from_following_diagram")
                region.analysis = alt
        ctx = region.analysis.end_context

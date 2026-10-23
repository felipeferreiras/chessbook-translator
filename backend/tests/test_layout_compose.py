"""Montagem da página traduzida (app/layout/compose.py) em páginas sintéticas."""

import numpy as np
import pymupdf
import pytest

from app.layout.compose import (
    BlockJob,
    _frame,
    _single_line_area,
    away_from,
    block_html,
    compose_page,
    family_for,
    verify_text,
)
from app.pipeline.notation_pass import BlockLayout

TEXT_RECT = (72, 100, 300, 140)
BOARD = pymupdf.Rect(72, 150, 232, 310)


def layout(rect=TEXT_RECT, spans=None, lines=3, font="TimesNewRomanPSMT") -> BlockLayout:
    return BlockLayout(text_rect=rect, span_rects=spans or [rect], font=font, size=10, color=0,
                       bold=False, italic=False, align="justify", indent=0, line_height=12, lines=lines)


def page_with_board() -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=500)
    page.insert_textbox(pymupdf.Rect(TEXT_RECT), "White wins with a waiting move. " * 3, fontsize=10)
    page.draw_rect(BOARD, color=(0, 0, 0), width=2)
    for i in range(8):
        for j in range(8):
            if (i + j) % 2:
                x, y = BOARD.x0 + i * 20, BOARD.y0 + j * 20
                page.draw_rect(pymupdf.Rect(x, y, x + 20, y + 20), fill=(0.6, 0.6, 0.6), width=0)
    return doc


def compose(doc, jobs, boards=(BOARD,)):
    original = pymupdf.open()
    original.insert_pdf(doc)
    report = compose_page(doc[0], original[0], jobs, list(boards), [], 1)
    verify_text(doc[0], report, jobs, {j.region_id: ["1.♔e2"] for j in jobs if "♔" in j.text})
    return report


def test_translation_replaces_original_and_keeps_board():
    doc = page_with_board()
    job = BlockJob("p1-0", layout(), 0, "As brancas vencem com 1.♔e2, um lance de espera.", [(22, 27)])
    report = compose(doc, [job])
    text = doc[0].get_text()
    assert "White wins" not in text
    assert "lance de espera" in text and "♔e2" in text
    assert report.blocks[0].placed and report.blocks[0].scale == 1
    assert report.diagram_changed_pct == [0.0]
    assert report.ok


def test_long_translation_expands_then_reduces_without_dropping_text():
    doc = page_with_board()
    long = "Texto traduzido mais longo que o original. " * 8
    report = compose(doc, [BlockJob("p1-0", layout(), 0, long)])
    block = report.blocks[0]
    assert block.placed and block.expanded
    # O tabuleiro abaixo é obstáculo: a expansão não pode invadi-lo.
    assert block.rect[3] <= BOARD.y0
    assert report.diagram_changed_pct == [0.0]
    assert not report.missing_text


def test_text_that_cannot_fit_is_reported_not_silently_dropped():
    doc = page_with_board()
    tiny = (72, 100, 90, 104)
    report = compose(doc, [BlockJob("p1-0", layout(tiny, lines=1), 0, "palavra " * 400)], boards=[BOARD])
    assert report.blocks[0].needs_review
    assert not report.ok


def test_redaction_never_reaches_the_board():
    caption = pymupdf.Rect(72, 300, 232, 320)  # caixa do glifo invade a moldura
    clipped = away_from(caption, [BOARD])
    assert clipped.y0 > BOARD.y1
    above = away_from(pymupdf.Rect(72, 140, 232, 155), [BOARD])
    assert above.y1 < BOARD.y0
    untouched = pymupdf.Rect(250, 150, 300, 170)
    assert away_from(untouched, [BOARD]) == untouched


def test_frame_restricts_comparison_to_the_drawn_board():
    gray = np.full((100, 100), 255, dtype=np.uint8)
    gray[10, 10:90] = gray[89, 10:90] = 0
    gray[10:90, 10] = gray[10:90, 89] = 0
    gray[95:, 20:40] = 0  # texto vizinho dentro da caixa, fora da moldura
    rows, cols = _frame(gray)
    assert (rows.start, rows.stop, cols.start, cols.stop) == (10, 90, 10, 90)
    assert _frame(np.full((50, 50), 255, dtype=np.uint8)) == (slice(None), slice(None))


def test_block_html_marks_main_line_and_symbols():
    job = BlockJob("x", layout(), 0, "Assim 1.♔e2 +− e\nfim", [(6, 11)])
    body, css = block_html(job)
    assert "<b>1.<span class=\"fig\">♔</span>e2</b>" in body
    assert "<span class=\"fig\">+−</span>" in body
    assert "<br>" in body
    assert "text-align:justify" in css


def test_block_html_tabular_puts_page_numbers_right():
    job = BlockJob("x", layout(), 0, "Prefácio\t5\nCapítulo 1\t13", tabular=True)
    body, _ = block_html(job)
    assert body.count("<tr>") == 2
    assert "<td class=n>13</td>" in body


def test_font_family_substitutions_are_reported():
    assert family_for("TimesNewRomanPS-BoldMT") == ("serif", None)
    assert family_for("LinaresFigurine") == ("serif", None)
    assert family_for("CenturyGothic")[1] == "Century Gothic → Liberation Sans"
    assert family_for("Desconhecida")[1] == "Desconhecida → Liberation Serif"


def test_verify_text_flags_missing_notation():
    doc = page_with_board()
    job = BlockJob("p1-0", layout(), 0, "As brancas vencem.")
    original = pymupdf.open()
    original.insert_pdf(doc)
    report = compose_page(doc[0], original[0], [job], [BOARD], [], 1)
    verify_text(doc[0], report, [job], {"p1-0": ["1.♔e2"]})
    assert report.missing_notation == ["p1-0: 1.♔e2"]
    assert not report.ok


def test_longer_block_pushes_the_next_one_down_instead_of_covering_it():
    """Caso real (p. 21): o bloco seguinte começava 1,3 pt dentro da folga do anterior e foi coberto."""
    doc = page_with_board()
    first = BlockJob("p1-0", layout((72, 60, 300, 80), lines=2), 0, "Tradução mais longa que o original. " * 6)
    second = BlockJob("p1-1", layout((72, 80.4, 300, 104), lines=2), 0, "Bloco seguinte.")
    report = compose(doc, [first, second])
    a, b = report.blocks
    assert a.scale == b.scale == 1
    assert b.rect[1] + b.margin >= a.rect[3] - a.margin and "deslocado" in b.notes[0]
    assert b.rect[3] <= BOARD.y0
    assert report.overlaps == []


def test_board_between_blocks_stops_the_flow():
    doc = page_with_board()
    above = BlockJob("p1-0", layout((72, 120, 300, 140), lines=2), 0, "Tradução bem mais longa. " * 12)
    below = BlockJob("p1-1", layout((72, 320, 300, 340), lines=2), 0, "Abaixo do tabuleiro.")
    report = compose(doc, [above, below])
    assert report.blocks[0].rect[3] <= BOARD.y0
    assert report.blocks[1].rect[1] == pytest.approx(320 - report.blocks[1].margin)
    assert report.diagram_changed_pct == [0.0]


def test_single_line_centered_on_page_gets_full_width():
    """Caso real (p. 256): "Chapter 10" virou "Capítulo / 10" numa caixa estreita."""
    title = pymupdf.Rect(223, 66, 298, 79)
    rect, centered = _single_line_area(title, (48, 254), (48, 473), [])
    assert centered and (rect.x0, rect.x1) == (48, 473)


def test_single_line_never_grows_over_a_neighbour():
    label = pymupdf.Rect(66, 200, 90, 210)
    board = pymupdf.Rect(110, 180, 250, 320)
    rect, centered = _single_line_area(label, (48, 254), (48, 473), [board])
    assert not centered and rect.x1 <= board.x0
    name = pymupdf.Rect(110, 480, 190, 490)
    rect, centered = _single_line_area(name, (48, 254), (48, 473), [pymupdf.Rect(230, 478, 250, 492)])
    assert centered and rect.x1 <= 227 and (rect.x0 + rect.x1) / 2 == 150


def test_block_html_applies_prose_italic_and_bold_together():
    job = BlockJob("x", layout(), 0, "Em Manual de Finais e depois", [(3, 9)], italic_ranges=[(3, 19)])
    body, _ = block_html(job)
    assert body == "Em <b><i>Manual</i></b><i> de Finais</i> e depois"


def test_block_html_tabular_keeps_bold_chapter_line():
    text = "Capítulo 2 Cavalo contra Peões\nRei no Canto\t72"
    job = BlockJob("x", layout(), 0, text, [(0, 30)], tabular=True, italic_ranges=[(31, 34)])
    body, _ = block_html(job)
    assert "<td colspan=2><b>Capítulo 2 Cavalo contra Peões</b></td>" in body
    assert "<td><i>Rei</i> no Canto</td><td class=n>72</td>" in body


def test_shading_is_removed_but_text_and_board_stay():
    doc = page_with_board()
    page = doc[0]
    shade = pymupdf.Rect(72, 400, 300, 440)
    page.draw_rect(shade, fill=(0.87, 0.87, 0.86), width=0)
    page.insert_textbox(shade, "Notação: 1.e4 e5 fica.", fontsize=10)
    page.draw_rect(pymupdf.Rect(BOARD.x0, BOARD.y0, BOARD.x0 + 20, BOARD.y0 + 20), fill=(0.8, 0.8, 0.8), width=0)
    original = pymupdf.open()
    original.insert_pdf(doc)
    report = compose_page(page, original[0], [], [BOARD], [], 1)
    assert report.shading_removed == 1
    assert "1.e4 e5 fica" in page.get_text()
    gray = page.get_pixmap(clip=pymupdf.Rect(250, 430, 299, 439), colorspace=pymupdf.csGRAY)
    assert min(gray.samples) > 250  # sem o cinza do fundo
    assert report.diagram_changed_pct == [0.0]

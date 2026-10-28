"""Posição dos diagramas digitalizados: peças pelo contorno, hachura ignorada, vez de jogar pela marca."""

import numpy as np
import pymupdf
import pytest

from app.extraction import boards

FEN = "r4rk1/pb3pp1/1p1ppq1p/8/2PR3n/P1N1P1P1/1PQ1BP1P/5RK1"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _diagram(fen: str, black_to_move: bool) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Diagrama como nos livros: casas escuras hachuradas, figurinas, moldura e a marca ▼/△ ao lado."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=260)
    page.insert_font(fontname="dj", fontfile=FONT)
    x0, y0, sq = 40.0, 20.0, 24.0
    rows = []
    for row in fen.split("/"):
        cells = []
        for ch in row:
            cells += [""] * int(ch) if ch.isdigit() else [ch]
        rows.append(cells)
    for r in range(8):
        for c in range(8):
            rect = pymupdf.Rect(x0 + c * sq, y0 + r * sq, x0 + (c + 1) * sq, y0 + (r + 1) * sq)
            if (r + c) % 2:
                for k in range(-24, 24, 4):  # hachura diagonal
                    a, b = pymupdf.Point(rect.x0 + max(0, k), rect.y0 + max(0, -k)), None
                    b = pymupdf.Point(rect.x0 + min(sq, sq + k), rect.y0 + min(sq, sq - k))
                    page.draw_line(a, b, color=(0, 0, 0), width=0.6)
            if rows[r][c]:
                page.insert_text((rect.x0 + 2, rect.y1 - 4), boards.FIGURINE[rows[r][c]], fontsize=20,
                                 fontname="dj")
    page.draw_rect(pymupdf.Rect(x0, y0, x0 + 8 * sq, y0 + 8 * sq), color=(0, 0, 0), width=1.2)
    tip = (x0 + 8 * sq + 8, y0 + 8 * sq - 10)
    tri = [pymupdf.Point(*tip), pymupdf.Point(tip[0] + 12, tip[1]), pymupdf.Point(tip[0] + 6, tip[1] + 10)]
    if not black_to_move:
        tri = [pymupdf.Point(tip[0], tip[1] + 10), pymupdf.Point(tip[0] + 12, tip[1] + 10),
               pymupdf.Point(tip[0] + 6, tip[1])]
    page.draw_polyline([*tri, tri[0]], color=(0, 0, 0), fill=(0, 0, 0) if black_to_move else None, width=1.2)
    pix = page.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w)
    return gray, (x0, y0, x0 + 8 * sq, y0 + 8 * sq)


@pytest.mark.parametrize("black", [True, False])
def test_position_read_from_piece_outlines_and_side_from_the_mark(black):
    gray, board = _diagram(FEN, black)
    scale = 300 / 72
    assert boards.side_to_move(gray, board, scale) == ("b" if black else "w")
    shapes = boards.board_shapes(boards.board_cells(gray, board, scale))
    expected = [ch for row in FEN.split("/") for ch in "".join("." * int(x) if x.isdigit() else x for x in row)]
    assert [s is not None for s in shapes] == [ch != "." for ch in expected]  # hachura não vira peça
    groups = boards.group_shapes([s for s in shapes if s is not None])
    # mesmo desenho, mesmo grupo; cada grupo, uma peça só
    by_group: dict[int, set[str]] = {}
    for s, ch in zip(shapes, expected, strict=True):
        if s is not None:
            by_group.setdefault(s.group, set()).add(ch)
    assert all(len(v) == 1 for v in by_group.values())
    assert all(s is None or s.black == ch.islower() for s, ch in zip(shapes, expected, strict=True))
    labels = {str(g): next(iter(v)) for g, v in by_group.items()}
    squares = [-1 if s is None else s.group for s in shapes]
    placement, issues = boards.placement(squares, labels)
    assert placement == FEN and issues == []
    # sem decidir um grupo, a posição fica incompleta, com a casa dita
    del labels[str(squares[6])]
    placement, issues = boards.placement(squares, labels)
    assert placement is None and "g8" in issues[0]
    assert len(groups) == len(by_group)


def test_impossible_positions_are_reported():
    assert boards.check_placement(FEN) == []
    assert any("reis" in x for x in boards.check_placement("8/8/8/8/8/8/8/K7"))
    assert any("peão" in x for x in boards.check_placement("P3k3/8/8/8/8/8/8/4K3"))
    assert boards.check_placement("8/8") == ["posição mal formada"]


def test_cells_follow_the_frame_not_a_fixed_margin():
    """Com uma margem fixa (1/60 do tabuleiro) as casas de baixo saíam deslocadas para cima e a base
    das peças ficava de fora: o cavalo, aberto embaixo, perdia o miolo fechado e a casa parecia vazia."""
    import numpy as np

    from app.extraction import boards

    side, frame = 606, 3
    img = np.full((side, side), 255, np.uint8)
    img[:frame], img[-frame:], img[:, :frame], img[:, -frame:] = 0, 0, 0, 0
    sq = (side - 2 * frame) / 8
    y0 = round(frame + 7 * sq)  # fileira 1: um traço na base da casa a1
    img[y0 + int(sq) - 6:y0 + int(sq) - 2, frame + 10:frame + 60] = 0
    cells = boards.board_cells(img, (0, 0, side, side), 1.0)
    bottom = cells[56]
    assert (bottom < 128).any(axis=1)[-12:].any()  # a base da peça está dentro da casa
    assert not (cells[48] < 128).any()  # e não vazou para a casa de cima

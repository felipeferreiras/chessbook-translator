"""Convenções encontradas em livros reais (Fase 2).

As sequências e posições abaixo foram construídas para os testes; nenhum
trecho de livro é reproduzido.
"""

import chess
import pymupdf
import pytest

from app.chess.diagrams.font_diagram import read_font_diagram, side_from_label
from app.chess.notation import AtomKind, Context, Convention, MoveStatus, analyze_region, lex
from app.chess.notation.convention import detect_style
from app.chess.notation.lexer import LexStyle
from app.extraction.font_profiles import LINARES_DIAGRAM_SQUARES, SpanText, resolve_spans
from app.extraction.glyph_probe import probe_embedded_font
from tests.fixtures import synthetic as syn

BOOK = LexStyle(numbers_without_dot=True, abbreviated_pawn_captures=True)


def run(text, fen, style=BOOK, mask=None, proposed=False):
    ctx = Context.from_proposed_fen(fen) if proposed else Context.from_fen(fen)
    return analyze_region(text, ctx, Convention.FIGURINE, style=style, main_mask=mask)


def statuses(r):
    return [(m.atom.text, m.status) for m in r.moves]


# --- Estilo: números sem ponto e capturas abreviadas -------------------------

def test_numbers_without_dot_only_when_style_enabled():
    text = "1 ♔d2 ♔d5 2 ♔d3"
    assert [a.kind for a in lex(text).atoms if a.kind == AtomKind.MOVE_NUMBER] == []
    nums = [a.number for a in lex(text, BOOK).atoms if a.kind == AtomKind.MOVE_NUMBER]
    assert nums == [1, 2]


def test_number_without_dot_followed_by_prose_is_not_a_move_number():
    atoms = lex("White needs 4 moves to win and 2 pawns.", BOOK).atoms
    assert atoms == []


def test_abbreviated_pawn_capture_requires_adjacent_files_and_anchor():
    assert [a.text for a in lex("3 ♔f5! hg 4 hg", BOOK).moves] == ["♔f5!", "hg", "hg"]
    assert lex("so he said that he can be", BOOK).moves == []  # "he", "be": não são capturas
    assert [a.text for a in lex("3 ♔f5! hg", LexStyle(numbers_without_dot=True)).moves] == ["♔f5!"]


def test_abbreviated_capture_is_validated_against_the_board():
    fen = "4k3/8/8/8/6p1/7P/8/4K3 w - - 0 1"
    r = run("1 hg", fen)
    assert [m.uci for m in r.moves] == ["h3g4"]


def test_detect_style_from_counts():
    texts = ["1 ♔d2 ♔d5 2 ♔d3 ♔e5 3 ♔e3 ♔d5 4 ♔d3 hg 5 gh fe 6 ef gh 7 hg 8 ♔e4"]
    style, ev = detect_style(texts)
    assert style.numbers_without_dot and style.abbreviated_pawn_captures
    assert ev["numbers_with_dot"] == 0


# --- Símbolos do Informator colados ao lance --------------------------------

def test_informator_symbols_attached_to_moves():
    moves = lex("1 ♔b4!⊙ ♔b7 2 ♔c5+− g4= 3 ♔d6△", BOOK).moves
    assert [m.text for m in moves] == ["♔b4!⊙", "♔b7", "♔c5+−", "g4=", "♔d6△"]
    assert moves[2].move.check == "" and moves[2].move.info == "+−"


# --- Casa de destino alternativa: "♕d5(d4)" ----------------------------------

def test_alternative_destination_same_piece():
    r = run("1 ♕d5(d4)?", "4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    alt = r.moves[1]
    assert alt.atom.kind == AtomKind.ALT_DEST and alt.status == MoveStatus.VALIDATED and alt.uci == "d1d4"


def test_alternative_destination_ambiguous_between_piece_and_pawn():
    r = run("1 ♔f4 (g4)", "4k3/8/8/8/8/5K2/6P1/8 w - - 0 1")
    assert r.moves[1].status == MoveStatus.AMBIGUOUS
    assert sorted(r.moves[1].interpretations) == ["f3g4", "g2g4"]


# --- Parênteses de prosa com lances -----------------------------------------

def test_prose_parenthesis_returns_to_previous_line():
    text = "1 ♔b1 (but not 1 ♔a2? ♔c3 2 ♔b1) 1...♔c3"
    kinds = [a.kind for a in lex(text, BOOK).atoms]
    assert AtomKind.PAREN_OPEN in kinds and AtomKind.VAR_OPEN not in kinds
    r = run(text, "8/8/8/8/1k6/8/8/K7 w - - 0 1")
    assert [m.uci for m in r.moves] == ["a1b1", "a1a2", "b4c3", "a2b1", "b4c3"]
    assert r.moves[-1].status == MoveStatus.VALIDATED


# --- Linha principal em negrito ---------------------------------------------

def _mask(text: str, bold_parts: list[str]) -> list[bool]:
    mask = [False] * len(text)
    for part in bold_parts:
        start = text.index(part)
        for i in range(start, start + len(part)):
            mask[i] = True
    return mask


def test_gap_in_variation_does_not_kill_main_line():
    fen = "8/8/8/4k3/8/8/4P3/4K3 w - - 0 1"
    text = "1 ♔d2 ♔d5 Black could try 1...♔f4 3...♔e4 instead. 2 ♔d3 ♔e5"
    mask = _mask(text, ["1 ♔d2 ♔d5", "2 ♔d3 ♔e5"])
    with_mask = run(text, fen, mask=mask)
    assert with_mask.moves[-2].status == with_mask.moves[-1].status == MoveStatus.VALIDATED
    without = run(text, fen)
    assert without.moves[-1].status == MoveStatus.NO_CONTEXT


def test_branch_resolved_by_a_later_segment():
    # "6...♔g8" é legal após 6 a4 e após 6 ♔f1; só "7 a4" desempata.
    fen = "7k/p7/8/8/8/8/P7/4K3 w - - 0 6"
    text = "6 ♔f1! Again, not 6 a4? a5. Since 6...♔g8 allows 7 a4 ♔f8 8 a5"
    mask = _mask(text, ["6 ♔f1!"])
    r = run(text, fen, mask=mask)
    by_text = statuses(r)
    assert by_text[-3:] == [("a4", MoveStatus.VALIDATED), ("♔f8", MoveStatus.VALIDATED), ("a5", MoveStatus.VALIDATED)]
    warnings = [w for m in r.moves for w in m.warnings]
    assert "branch_ambiguous" in warnings and "branch_chosen_by_legality" in warnings


def test_moves_after_idea_symbol_are_not_a_sequence():
    r = run("1 ♔b1 △ ♔c2", "8/8/8/8/1k6/8/8/K7 w - - 0 1")
    assert r.moves[1].status == MoveStatus.NO_CONTEXT and "idea_move" in r.moves[1].warnings


def test_diagram_move_number_comes_from_text():
    r = run("Prose first. 35 ♔d2 ♔d5 36 ♔d3", "8/8/8/4k3/8/8/4P3/4K3 w - - 0 1", proposed=True)
    assert [m.status for m in r.moves] == [MoveStatus.VALIDATED] * 3
    assert "fullmove_number_from_text" in r.moves[0].warnings
    assert r.needs_review  # posição proposta, não confirmada


# --- Diagramas em fonte -------------------------------------------------------

_ENCODE = {(sym, color): ch for ch, (sym, color) in LINARES_DIAGRAM_SQUARES.items() if ch not in "Ds"}


def encode(fen: str) -> list[str]:
    board = chess.Board(fen)
    lines = ["cuuuuuuuuC"]
    for rank in range(7, -1, -1):
        row = ""
        for file in range(8):
            piece = board.piece_at(chess.square(file, rank))
            color = "dark" if (file + rank) % 2 == 0 else "light"
            row += _ENCODE[(piece.symbol() if piece else "", color)]
        lines.append("{" + row + "}")
    return lines + ["vllllllllV"]


@pytest.mark.parametrize("fen", [
    "8/8/7p/4K1pk/8/7P/2B5/8 w - - 0 1",
    "r3k2r/pp3ppp/2n5/3q4/3P4/2N5/PP3PPP/R2QK2R b KQkq - 0 1",
])
def test_font_diagram_round_trip(fen):
    reading = read_font_diagram(encode(fen))
    assert reading.ok and reading.placement == chess.Board(fen).board_fen()


def test_castling_rights_are_not_invented():
    reading = read_font_diagram(encode("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"))
    assert reading.fen(True).split()[2] == "-"
    assert any("roque" in n for n in reading.notes)


def test_piece_with_wrong_square_background_is_a_noted_defect():
    lines = encode("8/3k4/8/8/8/8/3K4/8 w - - 0 1")
    lines[2] = lines[2].replace("k", "i")  # rei preto desenhado com fundo de casa escura em d7 (clara)
    reading = read_font_diagram(lines)
    assert reading.ok and any("defeito tipográfico" in n for n in reading.notes)


def test_shifted_empty_squares_reject_the_reading():
    lines = encode("8/3k4/8/8/8/8/3K4/8 w - - 0 1")
    lines[5] = "{" + lines[5][2:-1] + "w}"  # fileira deslocada uma coluna
    assert not read_font_diagram(lines).ok


def test_diagram_without_kings_is_not_a_position():
    reading = read_font_diagram(encode("8/8/8/8/8/8/8/8 w - - 0 1"))
    assert not reading.ok and any("rei" in i for i in reading.issues)


@pytest.mark.parametrize("label, expected", [("W", (True, False)), ("B?", (False, True)), ("1-21", (None, False))])
def test_side_labels(label, expected):
    assert side_from_label(label) == expected


# --- Resolução de glifos por perfil de fonte ----------------------------------

def test_resolve_linares_spans_and_keep_origin():
    spans = [SpanText("1 Kd4? Ke6!*", "ABCDEF+LinaresFigurine"), SpanText(" thus", "Times"),
             SpanText("{wdwd}", "XYZABC+LinaresDiagram"), SpanText(" 9 Kd6i", "LinaresFigurineBold")]
    r = resolve_spans(spans)
    assert r.text == "1 ♔d4? ♔e6!⊙ thus 9 ♔d6+−"
    assert r.raw[r.origin[r.text.index("+−")]] == "i"
    assert not r.proposed_only and not r.unmapped  # perfil Linares confirmado pelo usuário


def test_unmapped_glyph_is_reported_not_guessed():
    r = resolve_spans([SpanText("Kd4%", "LinaresFigurine")])
    assert r.unmapped == [("LinaresFigurine", "%")]


def test_embedded_font_probe_identifies_figurine_drawn_by_letter():
    doc = pymupdf.open(stream=syn.build_page("fan_letter_font").pdf_bytes, filetype="pdf")
    xref = next(f[0] for f in doc[0].get_fonts(full=True) if "ChessFigurineTest" in f[3])
    obs = {o.char: o for o in probe_embedded_font(doc, xref)}
    assert obs["N"].best == "♘" and obs["N"].score > 0.9


def test_piece_route_is_notation_but_not_a_move():
    text = "White must take measures against ...♔e2-d2-c2−+ in time."
    kinds = [(a.kind, a.text) for a in lex(text, BOOK).atoms]
    assert (AtomKind.ROUTE, "♔e2-d2-c2−+") in kinds
    r = run(text, "8/8/8/8/8/8/4k3/K7 b - - 0 1")
    assert r.moves == []
    from app.translation.guard import protect
    assert "♔" not in protect(text, BOOK).masked


ABBREV = LexStyle(numbers_without_dot=True, abbreviated_pawn_captures=True)


def _abbreviated(text: str) -> list[str]:
    return [a.text.rstrip("?!") for a in lex(text, ABBREV).atoms if a.move and a.move.to_file is not None]


def test_abbreviated_capture_needs_notation_right_before_it():
    """Em português "de" é preposição: "em vista de 1...♔a7" não tem captura d×e."""
    assert _abbreviated("é um erro, em vista de 1...♔a7! e as brancas") == []
    assert _abbreviated("Depois de 21 ♔f1 ♔f3 o rei marcha") == []
    assert _abbreviated("3 ♔f1 d5 4 ed e4 5 d6") == ["ed"]
    assert _abbreviated("9 ♔g6 hg 10 ♔×g7") == ["hg"]
    assert _abbreviated("8...♖a5+! (8...hg? 9 ♔g6)") == ["hg"]


def test_prose_parenthesis_with_de_is_not_notation():
    kinds = [a.kind for a in lex("13 ♘f4 (conhecemos esta posição de empate) 13...♔c3!?", ABBREV).atoms]
    assert AtomKind.PAREN_OPEN not in kinds and AtomKind.VAR_OPEN not in kinds
    assert _abbreviated("(hg 9 ♔g6)") == ["hg"]


def _rows(boards: int, top: float = 100, frame: str = "!$$$$$$$$#") -> list:
    rows, y = [], top
    for _ in range(boards):
        rows.append((frame, pymupdf.Rect(80, y, 230, y + 12)))
        y += 12
        for _ in range(8):
            rows.append(("{" + "+" * 8 + "}", pymupdf.Rect(80, y, 230, y + 18)))
            y += 18
        rows.append((frame, pymupdf.Rect(80, y, 230, y + 12)))
        y += 20
    return rows


def test_stacked_boards_in_one_block_are_split():
    from app.pipeline.notation_pass import _split_boards

    boards = _split_boards(_rows(2))
    assert len(boards) == 2
    assert all(sum(1 for line in lines if line.startswith("{")) == 8 for lines, _ in boards)
    assert boards[0][1].y1 < boards[1][1].y0


def test_frame_strip_is_merged_into_the_board_below():
    from app.chess.diagrams.font_diagram import DiagramReading
    from app.pipeline.notation_pass import Diagram, _merge_board_strips

    strip = Diagram(5, (69, 480, 226, 505), DiagramReading(None, ["esperadas 8 fileiras, encontradas 0"]))
    board = Diagram(5, (76, 505, 226, 640), DiagramReading("8/8/8/8/8/8/8/K6k"))
    other_page = Diagram(6, (69, 480, 226, 505), DiagramReading(None, ["esperadas 8 fileiras, encontradas 0"]))
    diagrams = [strip, board, other_page]
    _merge_board_strips(diagrams, 5)
    assert diagrams == [board, other_page] and board.bbox == (69, 480, 226, 640)


def test_text_above_and_below_a_board_becomes_separate_parts():
    from app.pipeline.notation_pass import _split_around_board

    def line(y0, y1, text):
        return {"bbox": (50, y0, 250, y1), "spans": [{"text": text, "bbox": (50, y0, 250, y1)}]}
    block = {"bbox": (50, 240, 250, 470), "lines": [line(240, 250, "Caption"), line(300, 310, "rank"),
                                                    line(410, 420, "Paragraph below")]}
    parts = _split_around_board(block, pymupdf.Rect(76, 256, 226, 406))
    assert [[ln["spans"][0]["text"] for ln in p["lines"]] for p in parts] == [["Caption"], ["rank"],
                                                                             ["Paragraph below"]]
    assert parts[2]["bbox"][1] == 410


def test_moves_drawn_as_vector_outlines_block_the_paragraph():
    """Lances convertidos em curvas não aparecem no texto: o parágrafo não pode ir ao tradutor."""
    from app.pipeline.notation_pass import collect
    from app.pipeline.segments import book_segments

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_textbox(pymupdf.Rect(20, 80, 280, 120), "Conclusion: after the move Black must play.", fontsize=10)
    page.insert_text((20, 40), "Plain paragraph without drawings at all.", fontsize=10)
    for x in (95, 104, 113):  # três "glifos" desenhados como contornos pretos
        shape = page.new_shape()
        shape.draw_polyline([(x, 92), (x + 6, 92), (x + 7, 86), (x + 3, 84), (x, 88), (x, 92)])
        shape.finish(fill=(0, 0, 0), color=None)
        shape.commit()
    segs = book_segments(collect(doc))
    blocked = [s for s in segs if s.blocked]
    assert len(blocked) == 1 and blocked[0].region.vector_glyphs == 3
    assert "Conclusion" in blocked[0].region.resolved.text

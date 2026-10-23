"""Encadeamento de posições entre parágrafos e diagramas (Fase 3)."""

import chess

from app.chess.diagrams.font_diagram import DiagramReading
from app.chess.notation import Context, Convention, MoveStatus, analyze_region
from app.chess.notation.lexer import LexStyle
from app.extraction.font_profiles import ResolvedText
from app.pipeline.notation_pass import Diagram, DocumentNotation, Region, validate


def _region(page: int, y: float, text: str, column: int = 0, bold: bool = False) -> Region:
    """``bold``: o parágrafo inteiro em negrito (linha principal, como no livro)."""
    resolved = ResolvedText(text, list(range(len(text))), text)
    return Region(page, (50, y, 250, y + 20), column, resolved, [bold] * len(text))


def test_new_paragraph_can_go_back_to_a_move_of_the_previous_one():
    first = analyze_region("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6", Context.standard(), Convention.ENGLISH)
    second = analyze_region("Also good is 2...d6 3.d4 with a solid game.", first.end_context, Convention.ENGLISH)
    assert [m.status for m in second.moves] == [MoveStatus.VALIDATED] * 2
    assert second.moves[0].uci == "d7d6"
    assert "implicit_branch_by_move_number" in second.moves[0].warnings


def test_going_back_only_counts_if_the_segment_is_legal_there():
    """Outra partida citada no parágrafo seguinte não pode ser lida na linha anterior."""
    start = Context.from_proposed_fen("8/8/8/4k3/8/8/4P3/4K3 w - - 0 1")
    first = analyze_region("1.Kd2 Kd4 2.Ke1 Ke4", start, Convention.ENGLISH)
    assert all(m.status == MoveStatus.VALIDATED for m in first.moves)
    second = analyze_region("In another game 1.d4 d5 2.c4 was played.", first.end_context, Convention.ENGLISH)
    assert all(m.status == MoveStatus.NO_CONTEXT for m in second.moves)
    assert "no_position:after_move_number_gap" in second.moves[0].warnings


def test_missing_position_explains_why():
    out = analyze_region("Later 5.Nf3 was played.", None, Convention.ENGLISH)
    assert out.moves[0].status == MoveStatus.NO_CONTEXT
    assert "no_position:region_start" in out.moves[0].warnings


def test_text_above_its_diagram_uses_the_following_diagram():
    """Parágrafo que comenta o diagrama impresso logo abaixo dele, na mesma coluna."""
    old = chess.Board("8/8/8/8/8/2k5/8/K7 w - - 0 1")
    new = chess.Board("8/8/8/3k4/8/8/4P3/4K3 w - - 0 1")
    doc = DocumentNotation(convention=Convention.FIGURINE, style=LexStyle(numbers_without_dot=True))
    doc.diagrams = [Diagram(1, (60, 40, 200, 180), DiagramReading(old.board_fen()), white_to_move=True),
                    Diagram(1, (60, 300, 200, 440), DiagramReading(new.board_fen()), white_to_move=True)]
    doc.regions = [_region(1, 200, "After 1 ♔a2 the game is drawn."),
                   _region(1, 230, "Here 1 ♔d2 ♔e4 2 ♔c3 wins easily.")]
    validate(doc)
    moves = doc.regions[1].analysis.moves
    assert [m.status for m in moves] == [MoveStatus.VALIDATED] * 3
    assert "context_from_following_diagram" in moves[0].warnings


def test_pgn_export_follows_the_validated_main_line():
    from app.chess.pgn_export import export_games

    start = chess.Board("8/8/8/3k4/8/8/4P3/4K3 w - - 0 1")
    doc = DocumentNotation(convention=Convention.FIGURINE, style=LexStyle(numbers_without_dot=True))
    doc.diagrams = [Diagram(1, (60, 40, 200, 180), DiagramReading(start.board_fen()), label="1-1", white_to_move=True)]
    doc.regions = [_region(1, 200, "1 ♔d2 ♔e4 2 ♔c3", bold=True),
                   _region(1, 230, "Also 2 ♔e2 ♔d4 3 ♔d2 draws."),  # variante: não entra na linha principal
                   _region(1, 260, "2...♔e5 3 ♔d3", bold=True),
                   _region(1, 290, "9 ♔h8", bold=True)]
    validate(doc)
    (game,) = export_games(doc, "Teste")
    assert game.game.headers["Site"] == "p. 1" and game.game.headers["Round"] == "1-1"
    assert game.game.headers["FEN"] == start.fen()
    assert [m.uci() for m in game.game.mainline_moves()] == ["e1d2", "d5e4", "d2c3", "e4e5", "c3d3"]
    assert not game.complete  # "9 ♔h8" não segue a linha: a partida para e diz por quê

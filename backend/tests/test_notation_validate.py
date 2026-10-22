"""Validação: nunca validar sem posição, nunca adivinhar entre interpretações."""

import chess
import pytest

from app.chess.notation import Context, ContextSource, Convention, MoveStatus, analyze_region

RUY = "1.e4 e5 2.{N}f3 {N}c6 3.{B}b5 a6"


def run(text, **kw):
    return analyze_region(text, **kw)


def ucis(result):
    return [m.uci for m in result.moves]


def statuses(result):
    return [m.status for m in result.moves]


def test_standard_start_is_not_assumed_by_default():
    r = run("1.e4 e5 2.Nf3", convention=Convention.ENGLISH)
    assert statuses(r) == [MoveStatus.NO_CONTEXT] * 3


def test_standard_hypothesis_validates_but_requires_review():
    r = run("1.e4 e5 2.Nf3", convention=Convention.ENGLISH, assume_standard_start=True)
    assert ucis(r) == ["e2e4", "e7e5", "g1f3"]
    assert all(m.context == ContextSource.STANDARD_HYPOTHESIS for m in r.moves)
    assert "start_position_assumed_standard" in r.issues
    assert r.needs_review


@pytest.mark.parametrize(
    "conv, n, b",
    [(Convention.ENGLISH, "N", "B"), (Convention.PORTUGUESE, "C", "B"), (Convention.FIGURINE, "♘", "♗")],
)
def test_same_line_in_three_notations_gives_same_uci(conv, n, b):
    text = RUY.format(N=n, B=b)
    r = run(text, context=Context.standard(), convention=conv)
    assert ucis(r) == ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"]
    assert not r.needs_review


def test_captures_castling_check_and_mate():
    # Mate do pastor, com captura e mate.
    r = run("1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6 4.Qxf7#", context=Context.standard(), convention=Convention.ENGLISH)
    assert statuses(r) == [MoveStatus.VALIDATED] * 7
    assert r.moves[-1].canonical_san == "Qxf7#"
    assert r.moves[-1].warnings == []


def test_castling_with_zeros_and_letters():
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    r = run("1.0-0 O-O-O", context=Context.from_fen(fen), convention=Convention.ENGLISH)
    assert ucis(r) == ["e1g1", "e8c8"]


def test_king_move_notation_is_not_confused_with_castling():
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    r = run("1.Kg1", context=Context.from_fen(fen), convention=Convention.ENGLISH)
    assert statuses(r) == [MoveStatus.ILLEGAL]  # rei não chega a g1 sem rocar


@pytest.mark.parametrize("token, conv", [("e8=Q", Convention.ENGLISH), ("e8Q", Convention.ENGLISH),
                                         ("e8(D)", Convention.PORTUGUESE), ("e8=♕", Convention.FIGURINE)])
def test_promotion_forms(token, conv):
    fen = "8/4P3/8/8/8/k7/8/K7 w - - 0 1"
    r = run(f"1.{token}", context=Context.from_fen(fen), convention=conv)
    assert ucis(r) == ["e7e8q"]


def test_promotion_without_piece_is_ambiguous():
    fen = "8/4P3/8/8/8/k7/8/K7 w - - 0 1"
    r = run("1.e8", context=Context.from_fen(fen), convention=Convention.ENGLISH)
    assert r.moves[0].status == MoveStatus.AMBIGUOUS
    assert sorted(r.moves[0].interpretations) == ["e7e8b", "e7e8n", "e7e8q", "e7e8r"]


def test_underspecified_san_is_ambiguous_not_guessed():
    # Dois cavalos (b1 e f3) podem ir a d2.
    fen = "4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1"
    r = run("1.Nd2", context=Context.from_fen(fen), convention=Convention.ENGLISH)
    assert r.moves[0].status == MoveStatus.AMBIGUOUS
    assert sorted(r.moves[0].interpretations) == ["b1d2", "f3d2"]


@pytest.mark.parametrize("token, uci", [("Nbd2", "b1d2"), ("Nfd2", "f3d2")])
def test_file_disambiguation(token, uci):
    fen = "4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1"
    r = run(f"1.{token}", context=Context.from_fen(fen), convention=Convention.ENGLISH)
    assert ucis(r) == [uci]


def test_rank_and_square_disambiguation():
    fen = "4k3/8/8/R7/8/8/8/R3K3 w - - 0 1"
    assert ucis(run("1.R1a3", context=Context.from_fen(fen), convention=Convention.ENGLISH)) == ["a1a3"]
    assert ucis(run("1.Ra5a3", context=Context.from_fen(fen), convention=Convention.ENGLISH)) == ["a5a3"]


def test_letter_r_is_ambiguous_when_convention_unknown():
    # R = torre (inglês) ou rei (português). Ambos podem ir a f2? Rei em e1 e torre em f8.
    fen = "4k3/8/8/8/8/8/8/4K2R w - - 0 1"
    r = run("1.Rf1", context=Context.from_fen(fen), convention=Convention.UNDETERMINED)
    assert r.moves[0].status == MoveStatus.AMBIGUOUS
    assert sorted(r.moves[0].interpretations) == ["e1f1", "h1f1"]


def test_letter_r_resolved_only_by_legality_is_flagged():
    fen = "4k3/8/8/8/8/8/8/4K2R w - - 0 1"
    r = run("1.Rh2", context=Context.from_fen(fen), convention=Convention.UNDETERMINED)
    assert ucis(r) == ["h1h2"]
    assert "piece_letter_resolved_by_legality" in r.moves[0].warnings
    assert r.needs_review


def test_portuguese_r_is_king():
    fen = "4k3/8/8/8/8/8/8/4K2R w - - 0 1"
    assert ucis(run("1.Rf1", context=Context.from_fen(fen), convention=Convention.PORTUGUESE)) == ["e1f1"]
    assert ucis(run("1.Tf1", context=Context.from_fen(fen), convention=Convention.PORTUGUESE)) == ["h1f1"]


def test_illegal_move_stops_validation_of_the_rest():
    r = run("1.e4 e5 2.Nf4 Nc6 3.Bb5", context=Context.standard(), convention=Convention.ENGLISH)
    assert statuses(r) == [MoveStatus.VALIDATED, MoveStatus.VALIDATED, MoveStatus.ILLEGAL,
                           MoveStatus.NO_CONTEXT, MoveStatus.NO_CONTEXT]


def test_non_standard_start_position_from_fen():
    # Final de torre: as pretas jogam.
    fen = "8/8/8/4k3/8/8/4K3/R7 b - - 0 40"
    r = run("40...Kd4 41.Ra4+ Kc3", context=Context.from_fen(fen), convention=Convention.ENGLISH)
    assert ucis(r) == ["e5d4", "a1a4", "d4c3"]


def test_move_number_must_match_position():
    fen = "8/8/8/4k3/8/8/4K3/R7 b - - 0 40"
    r = run("12...Kd4", context=Context.from_fen(fen), convention=Convention.ENGLISH)
    assert r.moves[0].status == MoveStatus.NO_CONTEXT
    assert "move_number_gap" in r.moves[0].warnings


def test_variation_returns_to_main_line():
    text = "1.e4 e5 2.Nf3 (2.f4 exf4) 2...Nc6 3.Bb5"
    r = run(text, context=Context.standard(), convention=Convention.ENGLISH)
    assert ucis(r) == ["e2e4", "e7e5", "g1f3", "f2f4", "e5f4", "b8c6", "f1b5"]


def test_nested_variations():
    text = "1.e4 e5 (1...c5 2.Nf3 (2.c3 d5) 2...d6) 2.Nf3"
    r = run(text, context=Context.standard(), convention=Convention.ENGLISH)
    assert ucis(r) == ["e2e4", "e7e5", "c7c5", "g1f3", "c2c3", "d7d5", "d7d6", "g1f3"]


def test_illegal_move_inside_variation_does_not_break_main_line():
    text = "1.e4 e5 2.Nf3 (2.Nf4 Nc6) 2...Nc6"
    r = run(text, context=Context.standard(), convention=Convention.ENGLISH)
    assert statuses(r) == [MoveStatus.VALIDATED] * 3 + [MoveStatus.ILLEGAL, MoveStatus.NO_CONTEXT, MoveStatus.VALIDATED]


def test_implicit_branch_by_move_number_in_prose():
    # Padrão comum em livros: "Após 4.Ba4 Nf6 5.0-0 ...; a troca 4.Bxc6 dxc6 ...".
    text = "1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 Main line. After 4.Ba4 Nf6 5.0-0 White; the exchange 4.Bxc6 dxc6 gives"
    r = run(text, context=Context.standard(), convention=Convention.ENGLISH)
    assert ucis(r)[-2:] == ["b5c6", "d7c6"]
    assert "implicit_branch_by_move_number" in r.moves[-2].warnings
    assert not r.needs_review


def test_unnumbered_moves_after_prose_do_not_inherit_position():
    r = run("1.e4 e5 2.Nf3 Black must defend with ...d6 or ...Nc6",
            context=Context.standard(), convention=Convention.ENGLISH)
    assert statuses(r)[-2:] == [MoveStatus.NO_CONTEXT, MoveStatus.NO_CONTEXT]


def test_unnumbered_move_right_after_confirmed_diagram_is_validated():
    fen = chess.Board().fen()
    assert ucis(run("Nf3! is the most flexible.", context=Context.from_fen(fen),
                    convention=Convention.ENGLISH)) == ["g1f3"]


def test_wrong_check_marker_is_flagged_not_fixed():
    r = run("1.e4+", context=Context.standard(), convention=Convention.ENGLISH)
    assert r.moves[0].status == MoveStatus.VALIDATED
    assert "check_marker_without_check" in r.moves[0].warnings
    assert r.needs_review


def test_capture_marker_mismatch_is_flagged():
    r = run("1.Nxf3", context=Context.standard(), convention=Convention.ENGLISH)
    assert "capture_marker_without_capture" in r.moves[0].warnings


def test_en_passant():
    fen = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
    r = run("1.exd6 e.p.", context=Context.from_fen(fen), convention=Convention.ENGLISH)
    assert ucis(r) == ["e5d6"] and r.moves[0].warnings == []


def test_suspicious_ocr_breaks_context():
    r = run("1.e4 e5 2.\\f3 \\c6 3.865 a6", context=Context.standard(), convention=Convention.FIGURINE)
    assert statuses(r) == [MoveStatus.VALIDATED, MoveStatus.VALIDATED, MoveStatus.NO_CONTEXT]
    assert any(i.startswith("suspicious_notation") for i in r.issues)


def test_end_context_chains_regions():
    first = run("1.e4 e5 2.Nf3", context=Context.standard(), convention=Convention.ENGLISH)
    second = run("Now 2...Nc6 3.Bb5 is the Ruy Lopez.", context=first.end_context, convention=Convention.ENGLISH)
    assert ucis(second) == ["b8c6", "f1b5"]


def test_descriptive_notation_is_reported_unsupported():
    r = run("1.P-K4 P-K4 2.N-KB3", convention=Convention.DESCRIPTIVE)
    assert "descriptive_notation_unsupported" in r.issues and r.needs_review

"""Conversão de saída e detecção de convenção."""

import pytest

from app.chess.notation import (
    Context,
    Convention,
    ConversionPolicy,
    MoveStatus,
    OutputNotation,
    analyze_region,
    detect_convention,
    render_region,
)

TEXT_FAN = "1.e4 e5 2.♘f3 ♘c6 3.♗b5 a6 This is the main line; after 4.♗xc6 dxc6 5.0-0 the bishop pair..."


def render(text, source, target, context=None, policy=ConversionPolicy.STRICT):
    analysis = analyze_region(text, context=context, convention=source)
    return render_region(analysis, target, source, policy)


def test_preserve_is_byte_identical():
    out = render(TEXT_FAN, Convention.FIGURINE, OutputNotation.PRESERVE, Context.standard())
    assert out.text == TEXT_FAN and out.changes == []


@pytest.mark.parametrize(
    "target, expected",
    [
        (OutputNotation.ENGLISH, "1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 This is the main line; after 4.Bxc6 dxc6 5.0-0 the"),
        (OutputNotation.PORTUGUESE, "1.e4 e5 2.Cf3 Cc6 3.Bb5 a6 This is the main line; after 4.Bxc6 dxc6 5.0-0 the"),
    ],
)
def test_fan_to_letters(target, expected):
    out = render(TEXT_FAN, Convention.FIGURINE, target, Context.standard())
    assert out.text.startswith(expected)
    assert all(c.validated for c in out.changes)


def test_round_trip_en_pt_fan_en():
    en = "1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 5.O-O Be7 6.Re1 b5 7.Bb3 d6 8.c3 O-O 9.h3 Qd7"
    pt = render(en, Convention.ENGLISH, OutputNotation.PORTUGUESE, Context.standard()).text
    assert pt == "1.e4 e5 2.Cf3 Cc6 3.Bb5 a6 4.Ba4 Cf6 5.O-O Be7 6.Te1 b5 7.Bb3 d6 8.c3 O-O 9.h3 Dd7"
    fan = render(pt, Convention.PORTUGUESE, OutputNotation.FIGURINE, Context.standard()).text
    assert fan == "1.e4 e5 2.♘f3 ♘c6 3.♗b5 a6 4.♗a4 ♘f6 5.O-O ♗e7 6.♖e1 b5 7.♗b3 d6 8.c3 O-O 9.h3 ♕d7"
    back = render(fan, Convention.FIGURINE, OutputNotation.ENGLISH, Context.standard()).text
    assert back == en


def test_promotion_piece_is_converted():
    out = render("1.e8=Q+", Convention.ENGLISH, OutputNotation.PORTUGUESE,
                 Context.from_fen("8/4P3/8/8/8/k7/8/K7 w - - 0 1"))
    assert out.text == "1.e8=D+"


def test_author_disambiguation_and_annotations_are_kept():
    fen = "4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1"
    out = render("1.Nbd2!?", Convention.ENGLISH, OutputNotation.FIGURINE, Context.from_fen(fen))
    assert out.text == "1.♘bd2!?"


def test_strict_policy_keeps_unvalidated_moves():
    out = render("Black can answer with ...Nf6 or ...Nc6.", Convention.ENGLISH, OutputNotation.PORTUGUESE)
    assert out.text == "Black can answer with ...Nf6 or ...Nc6."
    assert [m for m, _ in out.not_converted] == ["Nf6", "Nc6"]


def test_symbol_only_policy_converts_unambiguous_letters_without_position():
    out = render("with ...Nf6 or ...Qe7", Convention.ENGLISH, OutputNotation.PORTUGUESE,
                 policy=ConversionPolicy.SYMBOL_ONLY)
    assert out.text == "with ...Cf6 or ...De7"
    assert not any(c.validated for c in out.changes)


def test_symbol_only_never_converts_ambiguous_letter():
    # Convenção indeterminada: R pode ser torre ou rei.
    out = render("with ...Re8", Convention.UNDETERMINED, OutputNotation.FIGURINE,
                 policy=ConversionPolicy.SYMBOL_ONLY)
    assert out.text == "with ...Re8"
    assert out.not_converted


def test_ambiguous_move_is_never_converted():
    fen = "4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1"
    out = render("1.Nd2", Convention.ENGLISH, OutputNotation.FIGURINE, Context.from_fen(fen))
    assert out.text == "1.Nd2" and out.not_converted == [("Nd2", "ambiguous")]


def test_descriptive_is_not_converted():
    out = render("1.P-K4 P-K4 2.N-KB3", Convention.DESCRIPTIVE, OutputNotation.ENGLISH)
    assert out.text == "1.P-K4 P-K4 2.N-KB3"


@pytest.mark.parametrize(
    "texts, expected, confident",
    [
        (["1.e4 e5 2.Nf3 Nc6 3.Bb5 Nf6 4.Qe2"], Convention.ENGLISH, True),
        (["1.e4 e5 2.Cf3 Cc6 3.Bb5 Cf6 4.De2"], Convention.PORTUGUESE, True),
        (["1.e4 e5 2.♘f3 ♘c6 3.♗b5 ♘f6"], Convention.FIGURINE, True),
        (["1.e4 e5 2.Rf1 Bb4"], Convention.UNDETERMINED, False),
        (["1.P-K4 P-K4 2.N-KB3 N-QB3 3.B-N5"], Convention.DESCRIPTIVE, True),
        (["2.Nf3 Nc6 3.Cf3"], Convention.UNDETERMINED, False),
    ],
)
def test_detect_convention(texts, expected, confident):
    report = detect_convention(texts)
    assert report.convention == expected
    assert report.confident == confident


def test_pawn_figurines_are_read_and_converted():
    text = "1.♙e4 ♟e5 2.♘f3 ♞c6 3.♗b5 ♟a6 4.♗×c6 ♟d×c6"
    analysis = analyze_region(text, Context.standard(), Convention.FIGURINE)
    assert all(m.status == MoveStatus.VALIDATED for m in analysis.moves)
    assert render_region(analysis, OutputNotation.ENGLISH, Convention.FIGURINE).text == \
        "1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.B×c6 d×c6"
    assert render_region(analysis, OutputNotation.FIGURINE, Convention.FIGURINE).text == \
        "1.♙e4 ♙e5 2.♘f3 ♘c6 3.♗b5 ♙a6 4.♗×c6 ♙d×c6"
    assert render_region(analysis, OutputNotation.PRESERVE, Convention.FIGURINE).text == text

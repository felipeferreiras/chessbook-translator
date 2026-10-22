"""Análise léxica: separar notação de prosa sem perder um caractere."""

import pytest

from app.chess.notation import AtomKind, lex


def kinds(text: str) -> list[tuple[str, str]]:
    return [(a.kind.value, a.text) for a in lex(text).atoms]


def moves(text: str) -> list[str]:
    return [a.text for a in lex(text).moves]


def test_offsets_reconstruct_original_text_exactly():
    text = "1.e4 e5 2.♘f3 ♘c6 3.♗b5 a6 This is the main line (see 4.♗a4)."
    for atom in lex(text).atoms:
        assert text[atom.start : atom.end] == atom.text


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1.e4 e5 2.Nf3 Nc6", ["e4", "e5", "Nf3", "Nc6"]),  # inglês
        ("1.e4 e5 2.Cf3 Cc6", ["e4", "e5", "Cf3", "Cc6"]),  # português
        ("1.e4 e5 2.♘f3 ♘c6", ["e4", "e5", "♘f3", "♘c6"]),  # FAN
        ("12...Nxe5!? 13.Qh5+", ["Nxe5!?", "Qh5+"]),
        ("5.0-0 0-0-0 6.O-O-O", ["0-0", "0-0-0", "O-O-O"]),
        ("15.e8=Q# 1-0", ["e8=Q#"]),
        ("15.e8Q+ e1(D)", ["e8Q+", "e1(D)"]),
        ("20.Rad1 Nbd7 21.R1e2 Qh4xe1", ["Rad1", "Nbd7", "R1e2", "Qh4xe1"]),
        ("1.e2-e4 e7-e5 2.Ng1-f3", ["e2-e4", "e7-e5", "Ng1-f3"]),  # algébrica longa
        ("8.exd6 e.p. Qxd6", ["exd6 e.p.", "Qxd6"]),
        ("1.e4 e5 2.Nf3 Nc6 1/2-1/2", ["e4", "e5", "Nf3", "Nc6"]),
    ],
)
def test_recognizes_move_forms(text, expected):
    assert moves(text) == expected


def test_black_move_numbers_and_ellipsis():
    atoms = lex("12...Nf6 13.Bg5 …h6").atoms
    num = atoms[0]
    assert num.kind == AtomKind.MOVE_NUMBER and num.number == 12 and num.black
    assert [a.kind for a in atoms][-2:] == [AtomKind.ELLIPSIS, AtomKind.MOVE]
    assert atoms[-1].ellipsis_prefix


def test_square_in_prose_is_not_a_move():
    assert kinds("The knight on f3 controls e5.") == [("square_ref", "f3"), ("square_ref", "e5")]


def test_hyphenated_square_in_prose_is_ignored():
    assert moves("defend the e5-pawn") == []


def test_prose_numbers_are_not_notation():
    assert lex("In 1995 he scored 3.5 points; see Figure 3.12 and Chapter 3.").atoms == []


def test_variation_parentheses_vs_prose_parentheses():
    text = "13.Qh5+ (13.Bxe5 Rxe5) 13...g6 (the only move) 14.fxg6"
    k = [a.kind for a in lex(text).atoms]
    assert k.count(AtomKind.VAR_OPEN) == 1 and k.count(AtomKind.VAR_CLOSE) == 1


def test_prose_inside_variation_closes_correct_parenthesis():
    # "(not 13...dxe5)" é parêntese de prosa; o ")" de "equality)" fecha a variante.
    text = "13.Qh5+ (13.Bxe5 is met by 13...Rxe5 (not 13...dxe5) with equality) 13...g6"
    atoms = lex(text).atoms
    opens = [a for a in atoms if a.kind == AtomKind.VAR_OPEN]
    closes = [a for a in atoms if a.kind == AtomKind.VAR_CLOSE]
    assert [a.start for a in opens] == [text.index("(13.")]
    assert [a.start for a in closes] == [text.index("equality)") + len("equality")]


def test_ocr_garbage_is_flagged_not_dropped():
    # Saída real do Tesseract para "1.e4 e5 2.♘f3 ♘c6 3.♗b5 a6" (spike da Fase 1).
    atoms = kinds("1.e4 e5 2.\\f3 \\c6 3.865 a6")
    assert ("suspicious", "\\f3") in atoms
    assert ("suspicious", "\\c6") in atoms
    assert ("suspicious", "3.865") in atoms


def test_descriptive_notation_is_detected():
    atoms = lex("1.P-K4 P-K4 2.N-KB3 N-QB3 3.B-N5 PxP").atoms
    assert sum(a.kind == AtomKind.DESCRIPTIVE for a in atoms) == 6


def test_figurine_followed_by_square_is_one_move():
    assert moves("2.♘f3 ♘c6") == ["♘f3", "♘c6"]

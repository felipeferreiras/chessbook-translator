"""Proteção dos lances durante a tradução."""

import pytest

from app.translation.guard import GuardViolation, protect, restore

EN = "1.e4 e5 2.♘f3 ♘c6 3.♗b5 a6 This is the main line. The knight on f3 controls e5."


def test_translator_never_sees_moves():
    p = protect(EN)
    assert "♘" not in p.masked and "e4" not in p.masked
    assert p.masked.startswith("⟦1⟧ This is the main line.")
    assert p.slots["1"] == "1.e4 e5 2.♘f3 ♘c6 3.♗b5 a6"


def test_restore_puts_original_notation_back():
    p = protect(EN)
    out = restore("⟦1⟧ Esta é a linha principal. O cavalo em f3 controla e5.", p)
    assert out.text == "1.e4 e5 2.♘f3 ♘c6 3.♗b5 a6 Esta é a linha principal. O cavalo em f3 controla e5."
    assert out.warnings == []


def test_missing_placeholder_is_rejected():
    p = protect(EN)
    with pytest.raises(GuardViolation, match="ausente"):
        restore("Esta é a linha principal. O cavalo em f3 controla e5.", p)


def test_duplicated_or_invented_placeholder_is_rejected():
    p = protect(EN)
    with pytest.raises(GuardViolation):
        restore("⟦1⟧ ⟦1⟧ O cavalo em f3 controla e5.", p)
    with pytest.raises(GuardViolation, match="desconhecido"):
        restore("⟦1⟧ ⟦2⟧ O cavalo em f3 controla e5.", p)


def test_changed_square_in_prose_is_rejected():
    p = protect(EN)
    with pytest.raises(GuardViolation, match="casas"):
        restore("⟦1⟧ Esta é a linha principal. O cavalo em f6 controla e5.", p)


def test_reordered_spans_produce_warning():
    p = protect("After 4.Ba4 Nf6 White plays 5.O-O quickly.")
    out = restore("As brancas jogam ⟦2⟧ rapidamente após ⟦1⟧.", p)
    assert "ordem" in out.warnings[0]
    assert out.text == "As brancas jogam 5.O-O rapidamente após 4.Ba4 Nf6."


def test_number_mismatch_is_rejected():
    # Num índice, números são referências a diagramas: um "2-" a mais corrompe o livro.
    p = protect("desperado: 9-46, 15-82 diagonal checks: 12-33")
    with pytest.raises(GuardViolation, match="2: 0 → 1"):
        restore("desperado: 9-46, 15-82, 2- xeques diagonais: 12-33", p)
    with pytest.raises(GuardViolation, match="números"):
        restore("Veja o Capítulo 6 após ⟦1⟧.", protect("See Chapter 5 after 1.e4 e5."))


def test_prose_parentheses_stay_visible_to_the_translator():
    from app.chess.notation.lexer import LexStyle

    text = "he replies 2 ♔e4 (but not 2 ♔f6? ♔c4! 3 ♔e6 ♔c5−+) 2...♔c4 3 ♔e3, with a draw."
    p = protect(text, LexStyle(numbers_without_dot=True))
    assert p.masked == "he replies ⟦1⟧ (but not ⟦2⟧) ⟦3⟧, with a draw."
    out = restore("ele responde ⟦1⟧ (mas não ⟦2⟧) ⟦3⟧, com empate.", p)
    assert out.text == "ele responde 2 ♔e4 (mas não 2 ♔f6? ♔c4! 3 ♔e6 ♔c5−+) 2...♔c4 3 ♔e3, com empate."


def test_restore_reports_where_each_notation_slot_landed():
    p = protect("After 4.Ba4 Nf6 White plays 5.O-O quickly.")
    out = restore("As brancas jogam ⟦2⟧ rapidamente após ⟦1⟧.", p)
    for start, end, key in out.pieces:
        assert out.text[start:end] == p.slots[key]
        a, b = p.slot_ranges[key]
        assert p.original[a:b] == p.slots[key]


def test_lost_line_break_blocks():
    p = protect("autopilot: 4-31, 4-33\nbarrier: 2-11")
    with pytest.raises(GuardViolation, match="quebras de linha"):
        restore("piloto automático: 4-31, 4-33 barreira: 2-11", p)
    assert restore("piloto automático: 4-31, 4-33\nbarreira: 2-11", p).warnings == []


def test_notation_moved_across_line_break_blocks():
    """Caso real: "1 Bd1+!? Kh4??\n1... Kg6! was necessary" virou "Era necessário 1 Bd1+!?..."."""
    p = protect("1.Bd1+!? Kh4??\n1...Kg6! was necessary, and Black resigned.")
    keys = list(p.slots)
    assert len(keys) == 2
    with pytest.raises(GuardViolation, match="mudaram de linha"):
        restore(f"⟦{keys[0]}⟧ ⟦{keys[1]}⟧\nera necessário, e as pretas abandonaram.", p)
    ok = restore(f"⟦{keys[0]}⟧\n⟦{keys[1]}⟧ era necessário, e as pretas abandonaram.", p)
    assert ok.text.startswith("1.Bd1+!? Kh4??\n1...Kg6! era")

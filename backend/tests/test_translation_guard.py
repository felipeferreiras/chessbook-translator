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


def _mask(text: str, styled: str) -> list[bool]:
    start = text.index(styled)
    return [start <= i < start + len(styled) for i in range(len(text))]


def test_prose_bold_and_italic_become_tags():
    text = "deflection: 2-29, 5-15\nbarrier: 2-11"
    bold = [a or b for a, b in zip(_mask(text, "deflection:"), _mask(text, "barrier:"), strict=True)]
    p = protect(text, bold=bold)
    assert p.masked == "<b>deflection:</b> 2-29, 5-15\n<b>barrier:</b> 2-11"
    assert p.tags == {"b": 2}
    out = restore("<b>desvio:</b> 2-29, 5-15\n<b>barreira:</b> 2-11", p)
    assert out.text == "desvio: 2-29, 5-15\nbarreira: 2-11"
    assert [out.text[a:b] for a, b, _ in out.styles] == ["desvio:", "barreira:"]
    assert out.warnings == []


def test_italic_title_inside_prose_and_notation_untouched():
    text = "In Dvoretsky's Endgame Manual after 1.e4 e5 White plays."
    p = protect(text, italic=_mask(text, "Dvoretsky's Endgame Manual"))
    assert p.masked == "In <i>Dvoretsky's Endgame Manual</i> after ⟦1⟧ White plays."
    out = restore("Em <i>Dvoretsky's Endgame Manual</i>, depois de ⟦1⟧, as brancas jogam.", p)
    assert out.styles == [(3, 29, "i")] and "1.e4 e5" in out.text


def test_style_covering_all_prose_is_not_tagged():
    text = "Usually, a knight draws easily against a rook."
    assert protect(text, bold=[True] * len(text), italic=[True] * len(text)).masked == text


def test_punctuation_alone_is_not_tagged():
    text = "1.e4, e5 and then"
    p = protect(text, bold=[True] * 5 + [False] * (len(text) - 5))
    assert "<b>" not in p.masked


def test_malformed_tags_block_and_lost_tags_warn():
    text = "barrier: 2-11 and more"
    p = protect(text, bold=_mask(text, "barrier:"))
    with pytest.raises(GuardViolation, match="não fechada"):
        restore("<b>barreira: 2-11 e mais", p)
    with pytest.raises(GuardViolation, match="sem abertura"):
        restore("barreira:</b> 2-11 e mais", p)
    with pytest.raises(GuardViolation, match="desconhecida"):
        restore("<strong>barreira:</strong> 2-11 e mais", p)
    out = restore("barreira: 2-11 e mais", p)
    assert any("negrito" in w for w in out.warnings) and out.styles == []

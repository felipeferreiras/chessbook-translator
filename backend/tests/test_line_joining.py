"""Junção de linhas com hífen no fim (casos tirados do livro de amostra)."""

import pytest

from app.extraction.lines import join, vocabulary
from app.pipeline.notation_pass import _block_parts

VOCAB = vocabulary(["the position is drawn regardless of the reciprocal\nsquare and corresponding squares here"])


@pytest.mark.parametrize("prev, nxt, expected", [
    ("(5-14), (5-17), (5-", "19)", ("", False)),          # referência a diagrama
    ("key square for the d5-", "pawn.", ("", False)),     # "d5-pawn"
    ("intends to play c2-", "c3, obtaining", ("", False)),  # lance "c2-c3"
    ("the g6-", "and g4-squares", (" ", False)),           # hífen suspenso
    ("an be a d-, e-, f-, g-", "or h- passed pawn", (" ", False)),
    ("in the game Hansen-", "Nimzovitch", ("", False)),   # nomes compostos
    ("White to move, the posi-", "tion is drawn", ("", True)),  # hifenização: "position"
    ("assures victory, re-", "gardless of", ("", True)),
    ("a queen-", "and-rook-pawn", ("", False)),            # composto: "queen-and-rook-pawn"
    ("a knight-", "fork appears", ("", False)),             # palavra inteira desconhecida: mantém o hífen
    ("plain line", "next line", (" ", False)),
])
def test_join_rules(prev, nxt, expected):
    assert join(prev, nxt, VOCAB) == expected


def test_vocabulary_skips_word_cut_at_line_end():
    v = vocabulary(["this is posi-\ntion"])
    assert "posi" not in v and "this" in v


def _block(lines):
    return {"lines": [{"spans": [{"text": t, "font": "Times", "flags": f, "bbox": (0, 0, 1, 1)} for t, f in line]}
                      for line in lines]}


def test_block_assembly_keeps_bold_aligned():
    block = _block([[("Index: (9-", 0)], [("158), the posi-  ", 0)], [("tion ", 0), ("1 Kd4", 16)]])
    spans, bold, _, _ = _block_parts(block, VOCAB)
    text = "".join(s.text for s in spans)
    assert text == "Index: (9-158), the position 1 Kd4"
    assert len(bold) == len(text)
    assert bold[text.index("1 Kd4")] and not bold[text.index("position")]

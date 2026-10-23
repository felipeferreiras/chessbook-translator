"""Sinais de fonte (nome, tipo, ToUnicode, uso privado) e fontes Type 3."""

import pymupdf

from app.chess.notation import Context, Convention, MoveStatus, analyze_region
from app.extraction.font_signals import FontGuess, font_signals
from app.extraction.glyph_probe import embedded_glyph_font, probe_page
from tests.fixtures import synthetic as syn
from tests.fixtures import type3


def _signals(pdf: bytes) -> dict:
    return {s.name: s for s in font_signals(pymupdf.open(stream=pdf, filetype="pdf"))}


def test_figurine_font_reusing_letters_is_flagged_for_the_embedded_probe():
    sig = _signals(syn.build_page("fan_letter_font").pdf_bytes)
    fig = next(s for s in sig.values() if "ChessFigurineTest" in s.name)
    assert fig.guess == FontGuess.LIKELY_FIGURINE and fig.probe == "embedded"
    assert all(s.guess == FontGuess.TEXT for s in sig.values() if s is not fig)


def test_type3_without_tounicode_extracts_letters_and_needs_the_page_probe():
    """Sem ToUnicode, o texto sai da codificação: "N" e "B", não o desenho."""
    pdf = type3.build(None)
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    assert doc[0].get_text().split() == ["1.e4", "e5", "2.Nf3", "Nc6", "3.Bb5"]
    t3 = _signals(pdf)["T3"]
    assert t3.subtype == "Type3" and not t3.has_tounicode
    assert t3.guess == FontGuess.UNKNOWN_SYMBOLS and t3.probe == "page"
    xref = next(f[0] for f in doc[0].get_fonts(full=True) if f[2] == "Type3")
    assert embedded_glyph_font(doc, xref) is None  # Type 3 não tem arquivo de fonte para redesenhar


def test_type3_with_figurine_tounicode_needs_no_map():
    pdf = type3.build({78: "♘", 66: "♗"})
    text = " ".join(pymupdf.open(stream=pdf, filetype="pdf")[0].get_text().split())
    assert text == "1.e4 e5 2.♘f3 ♘c6 3.♗b5"
    moves = analyze_region(text, Context.standard(), Convention.FIGURINE).moves
    assert all(m.status == MoveStatus.VALIDATED for m in moves)
    assert _signals(pdf)["T3"].guess == FontGuess.TEXT


def test_type3_with_letter_tounicode_is_a_likely_figurine_font():
    t3 = _signals(type3.build({78: "N", 66: "B"}))["T3"]
    assert t3.guess == FontGuess.LIKELY_FIGURINE and t3.probe == "page"


def test_page_probe_sees_type3_glyphs_but_only_proposes():
    """Caracterização: desenhos toscos também recebem nota alta; por isso o mapa é sempre confirmado."""
    obs = probe_page(pymupdf.open(stream=type3.build(None), filetype="pdf")[0])
    t3 = {o.char: o for o in obs if o.font == "T3"}
    assert set(t3) == {"N", "B"}
    assert all(0 <= o.score <= 1 for o in t3.values())

"""Capítulo e subseção de cada região (contexto para o tradutor)."""

from app.chess.notation.lexer import LexStyle
from app.extraction.font_profiles import ResolvedText
from app.pipeline.notation_pass import BlockLayout, Region
from app.pipeline.sections import assign_sections

STYLE = LexStyle(numbers_without_dot=True)


def _r(text: str, size: float = 10, bold: bool = False, lines: int = 3) -> Region:
    lay = BlockLayout((50, 0, 250, 20), [], "Times", size, 0, bold, False, "left", 0, size * 1.15, lines)
    return Region(1, (50, 0, 250, 20), 0, ResolvedText(text, list(range(len(text))), text), [False] * len(text),
                  layout=lay)


def test_chapter_title_in_two_headings_becomes_one_chapter():
    regions = [_r("Chapter 10", 14, True, 1), _r("Rook versus Knight", 16, True, 1),
               _r("The Lone Knight", 12, True, 1), _r("A knight draws easily against a rook. " * 4),
               _r("Exercises", 12, True, 1), _r("Find the win. " * 6)]
    secs = assign_sections(regions, STYLE)
    assert [s.label for s in secs] == [
        "Chapter 10 — Rook versus Knight", "Chapter 10 — Rook versus Knight",
        "Chapter 10 — Rook versus Knight › The Lone Knight", "Chapter 10 — Rook versus Knight › The Lone Knight",
        "Chapter 10 — Rook versus Knight › Exercises", "Chapter 10 — Rook versus Knight › Exercises"]
    assert [s.heading_level for s in secs] == [1, 1, 2, 0, 2, 0]


def test_short_bold_line_with_moves_is_not_a_heading():
    regions = [_r("Foreword", 14, True, 1), _r("1 ♔d2 ♔e4 2 ♔c3", 12, True, 1), _r("Body text here. " * 5)]
    secs = assign_sections(regions, STYLE)
    assert [s.heading_level for s in secs] == [1, 0, 0]
    assert {s.label for s in secs} == {"Foreword"}


def test_new_chapter_clears_the_subsection():
    regions = [_r("Chapter 1", 14, True, 1), _r("Mined Squares", 12, True, 1), _r("Text. " * 9),
               _r("Chapter 2", 14, True, 1), _r("More text. " * 9)]
    assert assign_sections(regions, STYLE)[-1].label == "Chapter 2"

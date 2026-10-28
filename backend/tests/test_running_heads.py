"""Cabeçalho e rodapé de página: só o que se repete; a primeira linha do texto nunca some."""

from types import SimpleNamespace

from app.pipeline.notation_pass import _running_heads


def _r(page: int, text: str, role: str = "header") -> SimpleNamespace:
    return SimpleNamespace(page=page, role=role, resolved=SimpleNamespace(text=text))


def test_only_repeated_lines_and_page_numbers_are_running_heads():
    regions = []
    for p in range(1, 6):
        regions += [_r(p, f"{20 + p}"), _r(p, "Chapter 1 — Candidate Moves")]
    first_lines = [_r(1, "1. Golod — Gerzhoy, Philadelphia 2011"), _r(2, "8. Gashimov — Navara, Wijk aan Zee 2012"),
                   _r(3, "White to play and win", "footer")]
    _running_heads(regions + first_lines)
    assert {r.role for r in regions} == {"header"}
    assert [r.role for r in first_lines] == ["text", "text", "text"]

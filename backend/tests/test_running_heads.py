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



def test_top_of_each_column_stays_in_its_column():
    """O começo das duas colunas cai na faixa do cabeçalho (44 pt): antes, o primeiro parágrafo da
    coluna da direita vinha logo depois do primeiro da esquerda, e a coluna da esquerda seguia depois."""
    from app.pipeline.notation_pass import Region, _reorder

    def region(name, x0, y0, role="text"):
        r = Region(1, (x0, y0, x0 + 180, y0 + 40), 0, None, [], role=role)
        r.name = name
        return r

    regions = [region("título", 160, 12, "header"), region("esq1", 52, 44), region("dir1", 255, 44),
               region("esq2", 51, 144), region("dir2", 254, 132)]
    _reorder(regions, {1: 248.0})
    assert [r.name for r in regions] == ["título", "esq1", "esq2", "dir1", "dir2"]
    assert [r.column for r in regions[1:]] == [0, 0, 1, 1]

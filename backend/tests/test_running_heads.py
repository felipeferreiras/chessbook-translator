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


def test_solutions_are_linked_to_the_exercise_diagrams_before_them():
    """Exercícios 1–3 (diagramas), depois as soluções "1. Fulano — Beltrano": cada uma, o seu."""
    from app.pipeline.notation_pass import _exercise_links

    intro = SimpleNamespace(name="exemplo")  # diagrama de exemplo antes dos exercícios: não entra
    d1, d2, d3 = (SimpleNamespace(name=f"ex{i}") for i in (1, 2, 3))
    s1 = SimpleNamespace(resolved=SimpleNamespace(text="1. Golod — Gerzhoy, Philadelphia 2011 18...♕f3!"))
    s2 = SimpleNamespace(resolved=SimpleNamespace(text="2. Romanko — Shulakova, Moscow 2012"))
    body = SimpleNamespace(resolved=SimpleNamespace(text="Black missed a direct win. 34...♗xa4"))
    s3 = SimpleNamespace(resolved=SimpleNamespace(text="3. A. Hunt — Galdunts, Gold Coast 2000"))
    events = [((1, 0, 1, 0), "diagram", intro), ((2, 0, 1, 0), "diagram", d1), ((2, 0, 2, 0), "diagram", d2),
              ((2, 1, 1, 0), "diagram", d3), ((3, 0, 1, 1), "region", s1), ((3, 0, 2, 1), "region", s2),
              ((3, 0, 3, 1), "region", body), ((4, 0, 1, 1), "region", s3)]
    links = _exercise_links(events)
    assert links == {id(s1): d1, id(s2): d2, id(s3): d3}

"""Montagem do PDF traduzido no modo fidelidade (estratégia A, ADR-0002).

Para cada página:

1. Apaga (redação) apenas os trechos de texto traduzidos. Imagens, vetores,
   fundos sombreados e diagramas compostos em fonte ficam intactos; trechos só
   de notação, não traduzidos, também ficam (mantêm a fonte figurina original).
2. Escreve a tradução na área do bloco original, com fonte, tamanho, cor,
   alinhamento, recuo e entrelinha medidos no original. A linha principal em
   negrito continua em negrito.
3. Se não couber, expande a área para o espaço livre abaixo do bloco e só
   então reduz a fonte, em passos registrados. Nada é descartado: o último
   recurso escreve com qualquer redução e marca o bloco para revisão.
4. Verifica a página gerada: presença de cada bloco, lances restaurados,
   diagramas idênticos ao original.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pymupdf

from app.pipeline.notation_pass import BlockLayout

LIB = Path("/usr/share/fonts/truetype/liberation")
FREE = Path("/usr/share/fonts/truetype/freefont")

# Família substituta por família original. Times New Roman e Arial têm
# substitutas com as mesmas métricas (Liberation, licença OFL); as demais são
# aproximações e ficam registradas no relatório.
FONT_FAMILY = (
    (re.compile(r"TimesNewRoman|Times", re.IGNORECASE), "serif", None),
    (re.compile(r"Arial|Helvetica", re.IGNORECASE), "sans", None),
    (re.compile(r"CenturyGothic", re.IGNORECASE), "sans", "Century Gothic → Liberation Sans"),
    (re.compile(r"Broadway", re.IGNORECASE), "sans", "Broadway → Liberation Sans"),
    (re.compile(r"Cambria|Calibri", re.IGNORECASE), "serif", "Cambria/Calibri → Liberation Serif"),
    # Figurinas são escritas na FreeSerif pelo HTML; o texto em volta é serifado.
    (re.compile(r"Linares", re.IGNORECASE), "serif", None),
)
SYMBOLS = re.compile(r"(\+−|−\+|[♔♕♖♗♘♙♚♛♜♝♞♟⊙△□⇆∞±∓⩲⩱−×])")

_FONT_FILES = {
    "serif": ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf",
              "LiberationSerif-Italic.ttf", "LiberationSerif-BoldItalic.ttf"),
    "sans": ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf",
             "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
}
# (área, redução mínima) em ordem: primeiro sem reduzir, depois expandindo,
# depois reduzindo em passos. A última tentativa aceita qualquer redução.
ATTEMPTS = (("exact", 1.0), ("expanded", 1.0), ("expanded", 0.92), ("expanded", 0.85),
            ("expanded", 0.75), ("expanded", 0.0))
MAX_SILENT_REDUCTION = 0.85  # abaixo disso o bloco vai para revisão
# Reduções tentadas para uma sequência inteira de blocos (ver ``_runs``) antes
# de recorrer ao ajuste bloco a bloco.
FLOW_SCALES = (1.0, 0.97, 0.94, 0.91, 0.88, 0.85)


def _archive() -> tuple[pymupdf.Archive, str]:
    arch = pymupdf.Archive()
    css = []
    for family, files in _FONT_FILES.items():
        for name, (weight, style) in zip(files, (("normal", "normal"), ("bold", "normal"),
                                                 ("normal", "italic"), ("bold", "italic")), strict=True):
            arch.add((LIB / name).read_bytes(), name)
            css.append(f"@font-face{{font-family:{family};font-weight:{weight};font-style:{style};src:url({name});}}")
    for name, weight in (("FreeSerif.ttf", "normal"), ("FreeSerifBold.ttf", "bold")):
        arch.add((FREE / name).read_bytes(), name)
        css.append(f"@font-face{{font-family:fig;font-weight:{weight};src:url({name});}}")
    return arch, "".join(css)


@dataclass
class BlockJob:
    region_id: str
    layout: BlockLayout
    column: int
    text: str  # tradução com notação restaurada
    bold_ranges: list[tuple[int, int]] = field(default_factory=list)  # trechos de linha principal
    tabular: bool = False


@dataclass
class BlockOutcome:
    region_id: str
    placed: bool
    scale: float
    expanded: bool
    rect: tuple[float, float, float, float]
    notes: list[str] = field(default_factory=list)
    margin: float = 0.0  # folga vertical incluída em ``rect`` (meia entrelinha)

    @property
    def needs_review(self) -> bool:
        return not self.placed or self.scale < MAX_SILENT_REDUCTION


@dataclass
class PageReport:
    page: int
    blocks: list[BlockOutcome]
    missing_text: list[str]  # blocos cujo início não aparece na página gerada
    missing_notation: list[str]  # trechos de notação não encontrados
    leftover_original: list[str]  # blocos com texto original não removido
    diagram_changed_pct: list[float]
    font_substitutions: list[str]
    overlaps: list[str] = field(default_factory=list)  # pares de blocos escritos um sobre o outro

    @property
    def ok(self) -> bool:
        return (not self.missing_text and not self.missing_notation and not self.leftover_original
                and not self.overlaps
                and all(not b.needs_review for b in self.blocks)
                and all(p == 0.0 for p in self.diagram_changed_pct))


def family_for(font: str) -> tuple[str, str | None]:
    for pattern, family, note in FONT_FAMILY:
        if pattern.search(font):
            return family, note
    return "serif", f"{font} → Liberation Serif"


def _inline_html(text: str, bold_ranges: list[tuple[int, int]]) -> str:
    """HTML do texto: negrito nos trechos da linha principal, símbolos na FreeSerif."""
    marks = [False] * len(text)
    for a, b in bold_ranges:
        for i in range(max(0, a), min(len(text), b)):
            marks[i] = True
    out: list[str] = []
    i = 0
    while i < len(text):
        j = i
        while j < len(text) and marks[j] == marks[i]:
            j += 1
        chunk = html.escape(text[i:j])
        chunk = SYMBOLS.sub(r'<span class="fig">\1</span>', chunk).replace("\n", "<br>")
        out.append(f"<b>{chunk}</b>" if marks[i] else chunk)
        i = j
    return "".join(out)


def _line_height(lay: BlockLayout) -> float:
    return lay.line_height if lay.lines > 1 else lay.size * 1.15


def block_html(job: BlockJob, scale: float = 1.0) -> tuple[str, str]:
    """HTML e CSS do bloco; ``scale`` reduz fonte e entrelinha juntas."""
    lay = job.layout
    family, _ = family_for(lay.font)
    color = f"#{lay.color:06x}"
    weight = "bold" if lay.bold else "normal"
    style = "italic" if lay.italic else "normal"
    align = lay.align
    size = round(lay.size * scale, 2)
    line_height = _line_height(lay) * scale
    css = (
        f"body{{margin:0;font-family:{family};font-size:{size}pt;line-height:{line_height:.2f}pt;"
        f"color:{color};font-weight:{weight};font-style:{style};text-align:{align};text-indent:{lay.indent}pt}}"
        f".fig{{font-family:fig}} table{{border-collapse:collapse;width:100%;margin:0}}"
        f"td{{padding:0;font-family:{family};font-size:{size}pt;color:{color};font-weight:{weight}}}"
        f"td.n{{text-align:right}}"
    )
    if job.tabular:
        rows = []
        for line in job.text.split("\n"):
            cells = line.split("\t")
            if len(cells) == 1:
                rows.append(f"<tr><td colspan=2>{_inline_html(cells[0], [])}</td></tr>")
            else:
                rows.append(f"<tr><td>{_inline_html(' '.join(cells[:-1]), [])}</td>"
                            f"<td class=n>{_inline_html(cells[-1], [])}</td></tr>")
        return f"<table>{''.join(rows)}</table>", css
    return _inline_html(job.text, job.bold_ranges), css


def _column_bounds(jobs: list[BlockJob], page: pymupdf.Page) -> dict[int, tuple[float, float]]:
    bounds: dict[int, tuple[float, float]] = {}
    for job in jobs:
        x0, _, x1, _ = job.layout.text_rect
        lo, hi = bounds.get(job.column, (x0, x1))
        bounds[job.column] = (min(lo, x0), max(hi, x1))
    return bounds


def _free_bottom(rect: pymupdf.Rect, obstacles: list[pymupdf.Rect], page: pymupdf.Page, gap: float = 3) -> float:
    limit = page.rect.height - 40  # acima do número da página
    for o in obstacles:
        # O bloco seguinte pode começar dentro da folga de entrelinha deste.
        if o.y0 > (rect.y0 + rect.y1) / 2 and o.x0 < rect.x1 - 1 and o.x1 > rect.x0 + 1:
            limit = min(limit, o.y0 - gap)
    return max(rect.y1, limit)


def _single_line_area(base: pymupdf.Rect, column: tuple[float, float] | None, area: tuple[float, float],
                      obstacles: list[pymupdf.Rect], gap: float = 3) -> tuple[pymupdf.Rect, bool]:
    """Largura disponível para um bloco de uma linha, que a tradução pode alongar.

    Uma linha centrada na coluna ou na página (títulos, nomes de jogadores)
    passa a ocupar a largura toda, centralizada; as demais podem crescer para
    a direita até o fim da coluna. Nunca sobre outro bloco ou tabuleiro na
    mesma altura.
    """
    center = (base.x0 + base.x1) / 2
    for lo, hi in (column, area):
        if lo is None or hi is None:
            continue
        if abs(center - (lo + hi) / 2) < 4 and base.width < 0.8 * (hi - lo):
            half = min(center - lo, hi - center)
            for o in obstacles:
                if o.y0 < base.y1 - 1 and o.y1 > base.y0 + 1 and not o.intersects(base):
                    half = min(half, (o.x0 - gap - center) if o.x0 >= center else (center - o.x1 - gap))
            if half > base.width / 2:
                return pymupdf.Rect(center - half, base.y0, center + half, base.y1), True
            return base, True
    out = pymupdf.Rect(base)
    right = column[1] if column else area[1]
    for o in obstacles:
        if o.y0 < base.y1 - 1 and o.y1 > base.y0 + 1 and o.x0 >= base.x1 - 1:
            right = min(right, o.x0 - gap)
    out.x1 = max(base.x1, right)
    return out, False


def away_from(rect: pymupdf.Rect, boards: list[pymupdf.Rect], margin: float = 0.3) -> pymupdf.Rect:
    """Recorta a área de redação para fora dos tabuleiros.

    Neste tipo de livro o tabuleiro é texto numa fonte de diagrama; a redação
    remove qualquer glifo que toque a área, então ela nunca pode alcançar a
    caixa do tabuleiro (incluindo a moldura).
    """
    out = pymupdf.Rect(rect)
    for board in boards:
        if not out.intersects(board):
            continue
        if (out.y0 + out.y1) / 2 >= (board.y0 + board.y1) / 2:
            out.y0 = max(out.y0, board.y1 + margin)
        else:
            out.y1 = min(out.y1, board.y0 - margin)
    return out


@dataclass
class _Prepared:
    idx: int
    job: BlockJob
    exact: pymupdf.Rect  # área do texto original, com meia entrelinha acima e abaixo
    margin: float


def _x_overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    return a.x0 < b.x1 - 1 and a.x1 > b.x0 + 1


def _runs(prepared: list[_Prepared], fixed: list[pymupdf.Rect]) -> list[list[_Prepared]]:
    """Sequências de blocos da mesma coluna sem nada fixo entre eles.

    Dentro de uma sequência a tradução mais longa pode empurrar os blocos
    seguintes para baixo; um tabuleiro ou um trecho que não foi traduzido
    (notação pura, rótulos) não se move e encerra a sequência.
    """
    runs: list[list[_Prepared]] = []
    for p in sorted(prepared, key=lambda q: (q.job.column, q.exact.y0)):
        if runs:
            prev = runs[-1][-1]
            gap_top, gap_bottom = prev.exact.y1 - prev.margin, p.exact.y0 + p.margin
            blocked = any(_x_overlap(o, p.exact) and o.y0 < gap_bottom and o.y1 > gap_top for o in fixed)
            if prev.job.column == p.job.column and _x_overlap(prev.exact, p.exact) and not blocked:
                runs[-1].append(p)
                continue
        runs.append([p])
    return runs


def _measure(job: BlockJob, width: float, scale: float, archive: pymupdf.Archive, font_css: str) -> float:
    body, css = block_html(job, scale)
    story = pymupdf.Story(html=body, user_css=font_css + css, archive=archive)
    _, filled = story.place(pymupdf.Rect(0, 0, width, 100_000))
    return pymupdf.Rect(filled).height


def _flow(run: list[_Prepared], scale: float, obstacles: list[pymupdf.Rect], page: pymupdf.Page,
          archive: pymupdf.Archive, font_css: str) -> list[tuple[pymupdf.Rect, float]] | None:
    """Posições dos blocos da sequência com a fonte em ``scale``, ou None se não couber."""
    out: list[tuple[pymupdf.Rect, float]] = []
    bottom = 0.0
    for k, p in enumerate(run):
        height = _measure(p.job, p.exact.width, scale, archive, font_css)
        top = p.exact.y0
        if k:
            prev = run[k - 1]
            gap = p.exact.y0 - (prev.exact.y1 - 1)  # espaço original entre os dois blocos
            top = max(top, bottom + gap)
        rect = pymupdf.Rect(p.exact.x0, top, p.exact.x1, top + height)
        inner = rect + (0, p.margin, 0, -p.margin)
        if any(inner.intersects(o) and (inner & o).height > 1 and (inner & o).width > 1 for o in obstacles):
            return None
        out.append((rect, height))
        bottom = rect.y1
    if bottom > _free_bottom(run[-1].exact, obstacles, page) + 1:
        return None
    return out


def _draw(page: pymupdf.Page, p: _Prepared, rect: pymupdf.Rect, height: float, scale: float,
          archive: pymupdf.Archive, font_css: str) -> BlockOutcome:
    body, css = block_html(p.job, scale)
    box = pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + height + 2 * p.margin + 2)
    spare, _ = page.insert_htmlbox(box, body, css=font_css + css, archive=archive, scale_low=1)
    outcome = BlockOutcome(p.job.region_id, spare >= 0, scale if spare >= 0 else 0.0,
                           rect.y0 > p.exact.y0 + 0.5 or rect.y1 > p.exact.y1 + 0.5, tuple(rect), margin=p.margin)
    if rect.y0 > p.exact.y0 + 0.5:
        outcome.notes.append(f"deslocado {rect.y0 - p.exact.y0:.0f} pt para baixo")
    if rect.y1 > p.exact.y1 + 0.5:
        outcome.notes.append(f"área expandida até y={rect.y1:.0f}")
    if scale < 1:
        outcome.notes.append(f"fonte reduzida a {scale:.0%}")
    if spare < 0:
        outcome.notes.append("não coube na área medida: bloco não escrito")
    return outcome


def _place_in_place(page: pymupdf.Page, p: _Prepared, obstacles: list[pymupdf.Rect],
                    archive: pymupdf.Archive, font_css: str) -> BlockOutcome:
    """Último recurso: o bloco no próprio lugar, expandindo e reduzindo até caber."""
    exact = p.exact
    expanded = pymupdf.Rect(exact.x0, exact.y0, exact.x1, _free_bottom(exact, obstacles, page))
    body, css = block_html(p.job)
    for area, low in ATTEMPTS:
        rect = exact if area == "exact" else expanded
        spare, scale = page.insert_htmlbox(rect, body, css=font_css + css, archive=archive, scale_low=low)
        if spare >= 0:
            used = pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y1 - spare * scale if scale else rect.y1)
            outcome = BlockOutcome(p.job.region_id, True, round(scale, 3), area != "exact", tuple(used),
                                   margin=p.margin)
            if area != "exact":
                outcome.notes.append(f"área expandida até y={rect.y1:.0f}")
            if scale < 1:
                outcome.notes.append(f"fonte reduzida a {scale:.0%}")
            return outcome
    outcome = BlockOutcome(p.job.region_id, False, 0.0, False, tuple(exact), margin=p.margin)
    outcome.notes.append("não coube nem com redução máxima: bloco não escrito")
    return outcome


def compose_page(page: pymupdf.Page, original: pymupdf.Page, jobs: list[BlockJob],
                 boards: list[pymupdf.Rect], keep: list[pymupdf.Rect], page_number: int) -> PageReport:
    """Substitui o texto dos ``jobs`` pela tradução. ``keep``: caixas que ficam (notação, rótulos)."""
    archive, font_css = _archive()
    redacted: dict[str, list[pymupdf.Rect]] = {}
    for job in jobs:
        for r in job.layout.span_rects:
            rect = away_from(pymupdf.Rect(r), boards)
            if rect.is_empty or rect.height < 1:
                continue
            redacted.setdefault(job.region_id, []).append(rect)
            page.add_redact_annot(rect)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    # Texto original que sobreviveu à redação ficaria sobreposto à tradução.
    leftovers = [rid for rid, rects in redacted.items()
                 if any(page.get_text("text", clip=r).strip() for r in rects)]

    columns = _column_bounds(jobs, page)
    originals = [pymupdf.Rect(j.layout.text_rect) for j in jobs]
    area_x0 = min((r.x0 for r in originals), default=0.0)
    area_x1 = max((r.x1 for r in originals), default=page.rect.width)
    substitutions: set[str] = set()
    prepared: list[_Prepared] = []
    for idx, job in enumerate(jobs):
        lay = job.layout
        _, note = family_for(lay.font)
        if note:
            substitutions.add(note)
        base = pymupdf.Rect(lay.text_rect)
        if lay.lines == 1:
            neighbours = [o for k, o in enumerate(originals) if k != idx] + boards + keep
            base, centered = _single_line_area(base, columns.get(job.column), (area_x0, area_x1), neighbours)
            if centered:
                lay = BlockLayout(**{**lay.__dict__, "align": "center"})
                job = BlockJob(job.region_id, lay, job.column, job.text, job.bold_ranges, job.tabular)
        pad = max(0.0, _line_height(lay) - lay.size)
        margin = pad / 2 + 1
        exact = pymupdf.Rect(base.x0, base.y0 - margin, base.x1, base.y1 + margin)
        prepared.append(_Prepared(idx, job, exact, margin))

    fixed = boards + keep
    placed: list[pymupdf.Rect] = []
    results: dict[int, BlockOutcome] = {}
    for run in _runs(prepared, fixed):
        members = {p.idx for p in run}
        others = [p.exact for p in prepared if p.idx not in members and p.idx not in results]
        obstacles = fixed + others + placed
        flowed = None
        for scale in FLOW_SCALES:
            flowed = _flow(run, scale, obstacles, page, archive, font_css)
            if flowed is not None:
                break
        if flowed is not None:
            for p, (rect, height) in zip(run, flowed, strict=True):
                results[p.idx] = _draw(page, p, rect, height, scale, archive, font_css)
                placed.append(pymupdf.Rect(results[p.idx].rect))
            continue
        for p in run:  # nem reduzindo o trecho inteiro coube: cada bloco no próprio lugar
            obstacles = fixed + [q.exact for q in prepared if q.idx != p.idx and q.idx not in results] + placed
            results[p.idx] = _place_in_place(page, p, obstacles, archive, font_css)
            if results[p.idx].placed:
                placed.append(pymupdf.Rect(results[p.idx].rect))
    outcomes = [results[i] for i in range(len(jobs))]

    return PageReport(
        page=page_number, blocks=outcomes,
        missing_text=[], missing_notation=[], leftover_original=leftovers,
        diagram_changed_pct=[_pixel_change(original, page, b) for b in boards],
        font_substitutions=sorted(substitutions), overlaps=_overlaps(outcomes),
    )


def _overlaps(outcomes: list[BlockOutcome], tolerance: float = 1.0) -> list[str]:
    """Blocos cujas áreas escritas se sobrepõem além da folga de entrelinha."""
    rects = [(o.region_id, pymupdf.Rect(o.rect) + (0, o.margin, 0, -o.margin)) for o in outcomes if o.placed]
    found = []
    for i, (a, ra) in enumerate(rects):
        for b, rb in rects[i + 1:]:
            inter = ra & rb
            if not inter.is_empty and inter.height > tolerance and inter.width > tolerance:
                found.append(f"{a} × {b}")
    return found


def _frame(gray: np.ndarray) -> tuple[slice, slice]:
    """Linhas e colunas da moldura do tabuleiro (traços escuros quase contínuos).

    A caixa dos glifos da fonte de diagrama vai além do desenho; o texto vizinho
    que cai nessa sobra não faz parte do diagrama.
    """
    ink = gray < 100
    rows = np.where(ink.mean(axis=1) > 0.6)[0]
    cols = np.where(ink.mean(axis=0) > 0.6)[0]
    if len(rows) >= 2 and len(cols) >= 2:
        return slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1)
    return slice(None), slice(None)


def _pixel_change(a: pymupdf.Page, b: pymupdf.Page, rect: pymupdf.Rect, dpi: int = 100) -> float:
    pa = a.get_pixmap(dpi=dpi, clip=rect, colorspace=pymupdf.csGRAY)
    pb = b.get_pixmap(dpi=dpi, clip=rect, colorspace=pymupdf.csGRAY)
    if (pa.width, pa.height) != (pb.width, pb.height):
        return 100.0
    x = np.frombuffer(pa.samples, dtype=np.uint8).reshape(pa.height, pa.width).astype(int)
    y = np.frombuffer(pb.samples, dtype=np.uint8).reshape(pb.height, pb.width).astype(int)
    rows, cols = _frame(x)
    return round(float((np.abs(x[rows, cols] - y[rows, cols]) > 32).mean() * 100), 3)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def verify_text(page: pymupdf.Page, report: PageReport, jobs: list[BlockJob], slots: dict[str, list[str]]) -> None:
    """Confere na página gerada o início de cada bloco e todos os trechos de notação."""
    content = _norm(page.get_text())
    for job in jobs:
        start = _norm(job.text.replace("\t", " "))[:30]
        if start and start not in content:
            report.missing_text.append(job.region_id)
        for slot in slots.get(job.region_id, []):
            if _norm(slot) not in content:
                report.missing_notation.append(f"{job.region_id}: {slot[:40]}")

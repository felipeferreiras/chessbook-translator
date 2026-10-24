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

import functools
import html
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pymupdf

from app.extraction.ocr import OCR_FONT
from app.pipeline.notation_pass import BlockLayout

LIB = Path("/usr/share/fonts/truetype/liberation")
FREE = Path("/usr/share/fonts/truetype/freefont")
BUNDLED = Path(__file__).parent / "fonts"  # fontes OFL que acompanham o projeto (ver OFL-*.txt)

# Família substituta por família original. Times New Roman e Arial têm
# substitutas com as mesmas métricas (Liberation, licença OFL); as demais são
# aproximações e ficam registradas no relatório. Century Gothic é geométrica:
# a Urbanist (OFL) é a parecida entre as livres comparadas (Didact Gothic não
# tem negrito; Poppins é mais larga e pesada). Os subconjuntos do PDF não têm
# letras acentuadas, então a fonte original não serve para o português.
FONT_FAMILY = (
    (re.compile(r"TimesNewRoman|Times", re.IGNORECASE), "serif", None),
    (re.compile(r"Arial|Helvetica", re.IGNORECASE), "sans", None),
    (re.compile(r"CenturyGothic", re.IGNORECASE), "geo", "Century Gothic → Urbanist"),
    (re.compile(r"Broadway", re.IGNORECASE), "geo", "Broadway → Urbanist"),
    (re.compile(r"Cambria|Calibri", re.IGNORECASE), "serif", "Cambria/Calibri → Liberation Serif"),
    # Figurinas são escritas na FreeSerif pelo HTML; o texto em volta é serifado.
    (re.compile(r"Linares", re.IGNORECASE), "serif", None),
    (re.compile(OCR_FONT), "serif", "texto de OCR (fonte desconhecida) → Liberation Serif"),
)
SYMBOLS = re.compile(r"(\+−|−\+|[♔♕♖♗♘♙♚♛♜♝♞♟⊙△□⇆∞±∓⩲⩱−×])")

# Por família: regular, negrito, itálico, negrito itálico.
_FONT_FILES = {
    "serif": tuple(LIB / f"LiberationSerif-{s}.ttf" for s in ("Regular", "Bold", "Italic", "BoldItalic")),
    "sans": tuple(LIB / f"LiberationSans-{s}.ttf" for s in ("Regular", "Bold", "Italic", "BoldItalic")),
    "geo": tuple(BUNDLED / f"Urbanist-{s}.ttf" for s in ("Regular", "Bold", "Italic", "BoldItalic")),
}
# (área, redução mínima) em ordem: primeiro sem reduzir, depois expandindo,
# depois reduzindo em passos. A última tentativa aceita qualquer redução.
ATTEMPTS = (("exact", 1.0), ("expanded", 1.0), ("expanded", 0.92), ("expanded", 0.85),
            ("expanded", 0.75), ("expanded", 0.0))
MAX_SILENT_REDUCTION = 0.85  # abaixo disso o bloco vai para revisão
# Reduções tentadas para uma sequência inteira de blocos (ver ``_runs``) antes
# de recorrer ao ajuste bloco a bloco.
FLOW_SCALES = (1.0, 0.97, 0.94, 0.91, 0.88, 0.85)


# Faixas mantidas nas fontes de texto: latim (com acentos e estendido), pontuação,
# moeda, símbolos de letras, setas e operadores. Figurinas e símbolos do
# Informator ficam na FreeSerif reduzida.
_TEXT_RANGES = ((0x20, 0x24F), (0x2000, 0x206F), (0x20A0, 0x20CF), (0x2100, 0x214F), (0x2190, 0x21FF),
                (0x2200, 0x22FF))
_FIG_CHARS = "♔♕♖♗♘♙♚♛♜♝♞♟⊙△□⇆∞±∓⩲⩱−×+"
# Prima e prima dupla ficam de fora: a Urbanist usa o mesmo desenho para ’/′ e
# ”/″, e o PDF gerado passava a devolver "′" ao copiar o texto (p. 2).
_TEXT_EXCLUDE = {0x2032, 0x2033}


def _subset(path: Path, codepoints: set[int]) -> bytes:
    """A fonte só com os caracteres pedidos: cada bloco embute a fonte, então o tamanho importa.

    Medido no livro inteiro: com as fontes completas (FreeSerif tem 3,7 MB), 40
    páginas ocupavam 1,2 GB de memória e o livro não chegava ao fim.
    """
    import io
    import logging

    from fontTools import subset

    logging.getLogger("fontTools.subset").setLevel(logging.ERROR)  # "FFTM NOT subset": tabela sem uso
    font = subset.load_font(str(path), subset.Options())
    options = subset.Options()
    options.layout_features = ["*"]
    options.notdef_outline = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=codepoints)
    sub.subset(font)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


@functools.cache
def _font_data() -> tuple[tuple[str, bytes, str], ...]:
    """(nome do arquivo, bytes, regra @font-face) de cada fonte, preparados uma vez por processo."""
    text = {c for lo, hi in _TEXT_RANGES for c in range(lo, hi + 1)} - _TEXT_EXCLUDE
    out = []
    for family, files in _FONT_FILES.items():
        for path, (weight, style) in zip(files, (("normal", "normal"), ("bold", "normal"),
                                                 ("normal", "italic"), ("bold", "italic")), strict=True):
            rule = (f"@font-face{{font-family:{family};font-weight:{weight};font-style:{style};"
                    f"src:url({path.name});}}")
            out.append((path.name, _subset(path, text), rule))
    for name, weight in (("FreeSerif.ttf", "normal"), ("FreeSerifBold.ttf", "bold")):
        out.append((name, _subset(FREE / name, {ord(c) for c in _FIG_CHARS}),
                    f"@font-face{{font-family:fig;font-weight:{weight};src:url({name});}}"))
    return tuple(out)


def _archive() -> tuple[pymupdf.Archive, str]:
    arch = pymupdf.Archive()
    css = []
    for name, data, rule in _font_data():
        arch.add(data, name)
        css.append(rule)
    return arch, "".join(css)


@dataclass
class BlockJob:
    region_id: str
    layout: BlockLayout
    column: int
    text: str  # tradução com notação restaurada
    bold_ranges: list[tuple[int, int]] = field(default_factory=list)  # linha principal e negrito da prosa
    tabular: bool = False
    italic_ranges: list[tuple[int, int]] = field(default_factory=list)


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
    shading_removed: int = 0  # fundos sombreados retirados (decisão do usuário, 2026-10-23)
    cut_text: list[str] = field(default_factory=list)  # início presente, fim ausente: texto cortado

    @property
    def ok(self) -> bool:
        return (not self.missing_text and not self.missing_notation and not self.leftover_original
                and not self.overlaps and not self.cut_text
                and all(not b.needs_review for b in self.blocks)
                and all(p == 0.0 for p in self.diagram_changed_pct))


def family_for(font: str) -> tuple[str, str | None]:
    for pattern, family, note in FONT_FAMILY:
        if pattern.search(font):
            return family, note
    return "serif", f"{font} → Liberation Serif"


def _inline_html(text: str, bold_ranges: list[tuple[int, int]], italic_ranges: list[tuple[int, int]] = (),
                 offset: int = 0) -> str:
    """HTML do texto: negrito e itálico nos trechos marcados, símbolos na FreeSerif.

    ``offset``: posição de ``text`` no texto do bloco (células do sumário).
    """
    marks = [(False, False)] * len(text)
    for ranges, which in ((bold_ranges, 0), (italic_ranges, 1)):
        for a, b in ranges:
            for i in range(max(0, a - offset), min(len(text), b - offset)):
                marks[i] = (True, marks[i][1]) if which == 0 else (marks[i][0], True)
    out: list[str] = []
    i = 0
    while i < len(text):
        j = i
        while j < len(text) and marks[j] == marks[i]:
            j += 1
        chunk = html.escape(text[i:j])
        chunk = SYMBOLS.sub(r'<span class="fig">\1</span>', chunk).replace("\n", "<br>")
        bold, italic = marks[i]
        if italic:
            chunk = f"<i>{chunk}</i>"
        if bold:
            chunk = f"<b>{chunk}</b>"
        out.append(chunk)
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
        pos = 0
        for line in job.text.split("\n"):
            cells = line.split("\t")
            head = " ".join(cells[:-1]) if len(cells) > 1 else cells[0]
            # ' '.join troca cada tabulação por um espaço: as posições não mudam.
            first = _inline_html(head, job.bold_ranges, job.italic_ranges, pos)
            if len(cells) == 1:
                rows.append(f"<tr><td colspan=2>{first}</td></tr>")
            else:
                last = _inline_html(cells[-1], job.bold_ranges, job.italic_ranges, pos + len(line) - len(cells[-1]))
                rows.append(f"<tr><td>{first}</td><td class=n>{last}</td></tr>")
            pos += len(line) + 1
        return f"<table>{''.join(rows)}</table>", css
    return _inline_html(job.text, job.bold_ranges, job.italic_ranges), css


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
                      obstacles: list[pymupdf.Rect], gap: float = 3,
                      growing: list[pymupdf.Rect] = ()) -> tuple[pymupdf.Rect, bool]:
    """Largura disponível para um bloco de uma linha, que a tradução pode alongar.

    Uma linha centrada na coluna ou na página (títulos, nomes de jogadores)
    passa a ocupar a largura toda, centralizada; as demais podem crescer para
    a direita até o fim da coluna. Nunca sobre um obstáculo fixo (tabuleiro,
    bloco não traduzido) na mesma altura. Diante de outro bloco traduzido
    (``growing``), que também pode crescer, cada um vai só até o meio do vão:
    dois títulos lado a lado se sobrepunham (p. 152 e 298).
    """
    def same_band(o: pymupdf.Rect) -> bool:
        return o.y0 < base.y1 - 1 and o.y1 > base.y0 + 1 and not o.intersects(base)

    def right_limit(o: pymupdf.Rect, shared: bool) -> float:
        return (base.x1 + o.x0) / 2 if shared else o.x0 - gap

    def left_limit(o: pymupdf.Rect, shared: bool) -> float:
        return (o.x1 + base.x0) / 2 if shared else o.x1 + gap

    beside = [(o, False) for o in obstacles if same_band(o)] + [(o, True) for o in growing if same_band(o)]
    center = (base.x0 + base.x1) / 2
    for lo, hi in (column, area):
        if lo is None or hi is None:
            continue
        if abs(center - (lo + hi) / 2) < 4 and base.width < 0.8 * (hi - lo):
            half = min(center - lo, hi - center)
            for o, shared in beside:
                half = min(half, right_limit(o, shared) - center if o.x0 >= center
                           else center - left_limit(o, shared))
            if half > base.width / 2:
                return pymupdf.Rect(center - half, base.y0, center + half, base.y1), True
            return base, True
    out = pymupdf.Rect(base)
    right = column[1] if column else area[1]
    for o, shared in beside:
        if o.x0 >= base.x1 - 1:
            right = min(right, right_limit(o, shared))
    out.x1 = max(base.x1, right)
    return out, False


def _is_shading(drawing: dict) -> bool:
    """Retângulo só preenchido, em cinza claro (fundo de destaque do livro)."""
    fill = drawing.get("fill")
    if drawing.get("type") != "f" or not fill or drawing.get("color"):
        return False
    return 0.6 <= min(fill) and max(fill) <= 0.97 and max(fill) - min(fill) < 0.05


def remove_shading(page: pymupdf.Page, boards: list[pymupdf.Rect]) -> int:
    """Retira os fundos cinza da página, sem tocar em texto, imagens nem tabuleiros.

    Quando a tradução desloca o texto, o fundo original não acompanha; o
    usuário decidiu que a versão traduzida pode ficar sem esses fundos. Só são
    removidos os vetores que tocam o centro de cada fundo ("totalmente
    coberto" falhava por imprecisão nas bordas: 2 de 18 fundos numa página).
    """
    areas = [pymupdf.Rect(d["rect"]) for d in page.get_drawings() if _is_shading(d)]
    areas = [r for r in areas if not any(r.intersects(b) for b in boards)]
    for rect in areas:
        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        dot = pymupdf.Rect(cx - 0.25, cy - 0.25, cx + 0.25, cy + 0.25) & rect
        page.add_redact_annot(dot, fill=False, cross_out=False)
    if areas:
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                              text=pymupdf.PDF_REDACT_TEXT_NONE)
    return len(areas)


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
    shading = remove_shading(page, boards)
    redacted: dict[str, list[pymupdf.Rect]] = {}
    # Página digitalizada: o texto original são pixels da imagem; a redação os pinta com a cor do
    # fundo em volta (papel amarelado ou quadro sombreado), não de branco.
    scanned = any(j.layout.font == OCR_FONT for j in jobs)
    for job in jobs:
        for r in job.layout.span_rects:
            rect = away_from(pymupdf.Rect(r), boards)
            if rect.is_empty or rect.height < 1:
                continue
            redacted.setdefault(job.region_id, []).append(rect)
            page.add_redact_annot(rect, fill=_background(original, rect) if scanned else (1, 1, 1))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS if scanned else pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE, text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    # Texto original que sobreviveu à redação ficaria sobreposto à tradução.
    leftovers = [rid for rid, rects in redacted.items()
                 if any(page.get_text("text", clip=r).strip() or (scanned and _ink(page, r) > 0.02) for r in rects)]
    # (a cor de fundo é clara: "tinta" é só o que ficou abaixo de 50 % de cinza)

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
            base, centered = _single_line_area(base, columns.get(job.column), (area_x0, area_x1), boards + keep,
                                               growing=[o for k, o in enumerate(originals) if k != idx])
            if centered:
                lay = BlockLayout(**{**lay.__dict__, "align": "center"})
                job = replace(job, layout=lay)
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
                outcome = _draw(page, p, rect, height, scale, archive, font_css)
                if not outcome.placed:
                    # A medida não previu o que a escrita recusou (palavra mais larga que
                    # um rótulo estreito): o bloco vai para o ajuste no próprio lugar.
                    obstacles = fixed + [q.exact for q in prepared if q.idx != p.idx and q.idx not in results] + placed
                    outcome = _place_in_place(page, p, obstacles, archive, font_css)
                results[p.idx] = outcome
                if outcome.placed:
                    placed.append(pymupdf.Rect(outcome.rect))
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
        font_substitutions=sorted(substitutions), overlaps=_overlaps(outcomes), shading_removed=shading,
    )


def _background(page: pymupdf.Page, rect: pymupdf.Rect, dpi: int = 72) -> tuple[float, float, float]:
    """Cor do papel no retângulo: o tom claro mais comum (as letras são a minoria escura)."""
    pix = page.get_pixmap(dpi=dpi, clip=rect, colorspace=pymupdf.csGRAY)
    if not pix.width or not pix.height:
        return (1.0, 1.0, 1.0)
    level = float(np.percentile(np.frombuffer(pix.samples, dtype=np.uint8), 90)) / 255
    return (level, level, level)


def _ink(page: pymupdf.Page, rect: pymupdf.Rect, dpi: int = 72) -> float:
    """Fração de pixels escuros no retângulo (o que sobrou da imagem depois da redação)."""
    pix = page.get_pixmap(dpi=dpi, clip=rect, colorspace=pymupdf.csGRAY)
    if not pix.width or not pix.height:
        return 0.0
    return float((np.frombuffer(pix.samples, dtype=np.uint8) < 128).mean())


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
    """Confere na página gerada o início e o fim de cada bloco e todos os trechos de notação.

    Início ausente: o bloco não está na página. Início presente e fim ausente:
    o texto foi cortado.
    """
    content = _norm(page.get_text())
    for job in jobs:
        text = _norm(job.text.replace("\t", " "))
        if text[:30] and text[:30] not in content:
            report.missing_text.append(job.region_id)
        elif text[-30:] and text[-30:] not in content:
            report.cut_text.append(job.region_id)
        for slot in slots.get(job.region_id, []):
            if _norm(slot) not in content:
                report.missing_notation.append(f"{job.region_id}: {slot[:40]}")

"""Inspeção visual de glifos para identificar símbolos de peças.

Quando o PDF mostra ``♘`` mas a camada de texto devolve ``N`` (fonte figurina
que reaproveita letras) ou ``\\ue004`` (Área de Uso Privado), o texto extraído
não basta. Este módulo recorta o glifo renderizado na própria página e o
compara com desenhos de referência de figurinas e de letras.

O resultado é uma **proposta** de mapeamento por (fonte, caractere), nunca
uma substituição automática: a interface deve pedir confirmação ao usuário e
o mapeamento vale apenas para aquela fonte naquele documento.

Duas formas de obter o glifo:

* ``probe_page``: recorta o glifo da página renderizada. Simples, mas sofre
  com caixas de caractere largas (invadem os vizinhos) e fundos coloridos.
* ``probe_embedded_font``: reconstrói o mapa caractere→glifo a partir do
  ``ToUnicode`` da fonte incorporada e desenha cada glifo isolado. Preferível
  sempre que a fonte for TrueType extraível (caso de livros reais testados).

Limitação conhecida: as referências são as fontes livres instaladas que têm
as 12 figurinas (DejaVu, FreeFont...). Desenhos de editoras diferem; por isso
o resultado é proposta, não decisão. Peão e bispo têm silhuetas parecidas e
ainda se confundem.
"""

from __future__ import annotations

import functools
import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

REFERENCE_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_DIRS = (Path("/usr/share/fonts"), Path("/usr/local/share/fonts"))
FIGURINE_REFS = "♔♕♖♗♘♚♛♜♝♞♙♟"
LETTER_REFS = "KQRBNDTCPkqrbndtcp"
CANDIDATE_CHARS = set("KQRBNDTCP") | set(FIGURINE_REFS)
SIZE = 32


@dataclass(frozen=True)
class GlyphObservation:
    font: str
    char: str
    count: int
    best: str
    score: float
    runner_up: str
    runner_up_score: float

    @property
    def looks_like_figurine(self) -> bool:
        return self.best in FIGURINE_REFS

    @property
    def text_differs_from_image(self) -> bool:
        """O caractere extraído não corresponde ao que está desenhado."""
        return self.best != self.char


def _normalize(gray: np.ndarray) -> np.ndarray | None:
    ink = gray < 128
    if not ink.any():
        return None
    ys, xs = np.where(ink)
    crop = ink[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    h, w = crop.shape
    side = max(h, w)
    canvas = np.zeros((side, side), dtype=np.uint8)
    canvas[(side - h) // 2 : (side - h) // 2 + h, (side - w) // 2 : (side - w) // 2 + w] = crop * 255
    img = Image.fromarray(canvas).resize((SIZE, SIZE), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def _render_clip(page: pymupdf.Page, rect: pymupdf.Rect, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, clip=rect, colorspace=pymupdf.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)


def _render_text(text: str, fontfile: str | None = None, fontbuffer: bytes | None = None) -> np.ndarray | None:
    doc = pymupdf.open()
    page = doc.new_page(width=90, height=70)
    page.insert_font(fontname="ref", fontfile=fontfile, fontbuffer=fontbuffer)
    page.insert_text((10, 50), text, fontsize=36, fontname="ref")
    return _normalize(_render_clip(page, page.rect, 144))


@functools.cache
def reference_fonts() -> tuple[Path, ...]:
    """Fontes instaladas com as 12 figurinas: cada uma é um desenho de referência.

    Medido no livro de amostra (12 glifos de peça confirmados pelo usuário):
    2 referências acertam 10; todas as instaladas (13 no ambiente), 11.
    """
    found = []
    for base in FONT_DIRS:
        for path in sorted(base.rglob("*")) if base.exists() else []:
            if path.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                font = pymupdf.Font(fontfile=str(path))
            except Exception as exc:  # noqa: BLE001 - fonte ilegível: só não serve de referência
                logging.getLogger(__name__).debug("fonte de referência ignorada: %s (%s)", path, exc)
                continue
            if all(font.has_glyph(ord(ch)) for ch in FIGURINE_REFS):
                found.append(path)
    return tuple(found) or ((REFERENCE_FONT,) if REFERENCE_FONT.exists() else ())


def _silhouette(vec: np.ndarray) -> np.ndarray:
    """O desenho com o interior preenchido: o contorno varia de editora para editora, a silhueta menos."""
    ink = np.where(vec > 0.5, 0, 255).astype(np.uint8)
    framed = Image.new("L", (ink.shape[1] + 2, ink.shape[0] + 2), 255)
    framed.paste(Image.fromarray(ink), (1, 1))
    ImageDraw.floodfill(framed, (0, 0), 128)  # o que o fundo externo alcança
    return (np.asarray(framed)[1:-1, 1:-1] != 128).astype(np.float32)


@functools.cache
def _references() -> dict[str, list[tuple[np.ndarray, np.ndarray]]]:
    refs: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for font in reference_fonts():
        for ch in FIGURINE_REFS + LETTER_REFS:
            vec = _render_text(ch, fontfile=str(font))
            if vec is not None:
                refs.setdefault(ch, []).append((vec, _silhouette(vec)))
    return refs


def _classify(vec: np.ndarray) -> tuple[tuple[float, str], tuple[float, str]]:
    """As duas referências mais parecidas: média da semelhança do contorno e da silhueta."""
    refs = _references()
    sil = _silhouette(vec)
    scored = sorted(
        ((max(0.5 * _similarity(vec, r) + 0.5 * _similarity(sil, rs) for r, rs in pairs), ch)
         for ch, pairs in refs.items()),
        reverse=True,
    )
    # A margem de segurança vale contra outra peça: ♗ e ♝ têm a mesma silhueta.
    best = scored[0]
    runner = next(sc for sc in scored[1:] if _piece_of(sc[1]) != _piece_of(best[1]))
    return best, runner


def _piece_of(ch: str) -> str:
    """Mesma chave para a figurina branca e a preta da mesma peça."""
    i = FIGURINE_REFS.find(ch)
    return "KQRBNKQRBNPP"[i] if i >= 0 else ch


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    a0, b0 = a - a.mean(), b - b.mean()
    den = float(np.sqrt((a0 * a0).sum() * (b0 * b0).sum()))
    return float((a0 * b0).sum() / den) if den else 0.0


def _is_candidate(ch: str) -> bool:
    return ch in CANDIDATE_CHARS or unicodedata.category(ch) == "Co"  # Co = uso privado


def probe_page(
    page: pymupdf.Page, dpi: int = 400, exclude: list[pymupdf.Rect] | None = None
) -> list[GlyphObservation]:
    """Compara cada (fonte, caractere) candidato com as referências.

    ``exclude`` recebe as regiões de diagrama: peças sobre casas coloridas não
    são notação e distorcem a comparação.
    """
    exclude = exclude or []
    seen: dict[tuple[str, str], tuple[pymupdf.Rect, int]] = {}
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for ch in span["chars"]:
                    c = ch["c"]
                    if not _is_candidate(c):
                        continue
                    key = (span["font"], c)
                    rect = pymupdf.Rect(ch["bbox"])
                    if any(r.intersects(rect) for r in exclude):
                        continue
                    if key in seen:
                        seen[key] = (seen[key][0], seen[key][1] + 1)
                    elif not rect.is_empty:
                        seen[key] = (rect, 1)
    out: list[GlyphObservation] = []
    for (font, c), (rect, count) in sorted(seen.items()):
        vec = _normalize(_render_clip(page, rect, dpi))
        if vec is None:
            continue
        (s1, c1), (s2, c2) = _classify(vec)
        out.append(GlyphObservation(font, c, count, c1, round(s1, 3), c2, round(s2, 3)))
    return out


def propose_glyph_map(
    observations: list[GlyphObservation], min_score: float = 0.8, min_margin: float = 0.1
) -> dict[str, dict[str, str]]:
    """Propõe {fonte: {caractere_extraído: figurina}} para confirmação humana."""
    proposal: dict[str, dict[str, str]] = {}
    for o in observations:
        if (
            o.looks_like_figurine
            and o.text_differs_from_image
            and o.score >= min_score
            and o.score - o.runner_up_score >= min_margin
        ):
            proposal.setdefault(o.font, {})[o.char] = o.best
    return proposal


_HEX = r"<([0-9A-Fa-f]+)>"


def parse_tounicode(cmap: str) -> dict[int, str]:
    """Lê os blocos ``bfchar`` e ``bfrange`` de um CMap ToUnicode."""
    out: dict[int, str] = {}

    def text(hexstr: str) -> str:
        data = bytes.fromhex(hexstr)
        return data.decode("utf-16-be", errors="replace")

    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.DOTALL):
        for src, dst in re.findall(rf"{_HEX}\s*{_HEX}", block):
            out[int(src, 16)] = text(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.DOTALL):
        for lo, hi, rest in re.findall(rf"{_HEX}\s*{_HEX}\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)", block):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            if rest.startswith("["):
                for i, dst in enumerate(re.findall(_HEX, rest)):
                    out[lo_i + i] = text(dst)
            else:
                base = int(rest.strip("<>"), 16)
                for i in range(hi_i - lo_i + 1):
                    out[lo_i + i] = chr(base + i)
    return out


def _ref_xref(doc: pymupdf.Document, xref: int, key: str) -> int | None:
    kind, value = doc.xref_get_key(xref, key)
    if kind == "xref":
        return int(value.split()[0])
    if kind == "array":
        m = re.search(r"(\d+) 0 R", value)
        return int(m.group(1)) if m else None
    return None


def embedded_glyph_font(doc: pymupdf.Document, xref: int) -> tuple[bytes, dict[str, int]] | None:
    """Recria uma fonte TrueType com ``cmap`` a partir do ``ToUnicode``.

    Fontes Type0/Identity-H incorporadas costumam não ter ``cmap``: o PDF
    endereça glifos por CID e o ``ToUnicode`` diz o texto. Para desenhar o
    glifo de um caractere extraído, invertemos esse caminho. Devolve a fonte
    reconstruída e o mapa caractere→CID, ou None se não for possível.
    """
    from fontTools.ttLib import TTFont, newTable
    from fontTools.ttLib.tables._c_m_a_p import cmap_format_4

    _name, ext, _type, buf = doc.extract_font(xref)
    tu_xref = _ref_xref(doc, xref, "ToUnicode")
    if not buf or ext != "ttf" or tu_xref is None:
        return None
    desc = _ref_xref(doc, xref, "DescendantFonts")
    if desc is not None and doc.xref_get_key(desc, "CIDToGIDMap")[0] == "xref":
        return None  # mapa CID→GID explícito: não suportado ainda
    to_unicode = parse_tounicode(doc.xref_stream(tu_xref).decode("latin-1"))
    logging.getLogger("fontTools").setLevel(logging.ERROR)  # avisos de cabeçalho de subconjuntos
    try:
        font = TTFont(io.BytesIO(buf))
    except Exception:  # noqa: BLE001 - fonte malformada: sem proposta
        return None
    order = font.getGlyphOrder()
    char_to_cid = {t: cid for cid, t in to_unicode.items() if len(t) == 1 and cid < len(order)}
    sub = cmap_format_4(4)
    sub.platformID, sub.platEncID, sub.language = 3, 1, 0
    # Pontos de uso privado evitam que o leitor de PDF confunda com texto real.
    sub.cmap = {0xE000 + i: order[cid] for i, cid in enumerate(char_to_cid.values())}
    table = newTable("cmap")
    table.tableVersion = 0
    table.tables = [sub]
    font["cmap"] = table
    out = io.BytesIO()
    font.save(out)
    return out.getvalue(), {ch: 0xE000 + i for i, ch in enumerate(char_to_cid)}


def probe_embedded_font(
    doc: pymupdf.Document, xref: int, chars: set[str] | None = None, font_label: str | None = None
) -> list[GlyphObservation]:
    """Compara cada glifo da fonte incorporada, desenhado isoladamente, com as referências."""
    rebuilt = embedded_glyph_font(doc, xref)
    if rebuilt is None:
        return []
    buf, codes = rebuilt
    label = font_label or doc.xref_get_key(xref, "BaseFont")[1].lstrip("/")
    out: list[GlyphObservation] = []
    for ch, code in sorted(codes.items()):
        if (chars is not None and ch not in chars) or not ch.strip():
            continue
        vec = _render_text(chr(code), fontbuffer=buf)
        if vec is None:
            continue
        (s1, c1), (s2, c2) = _classify(vec)
        out.append(GlyphObservation(label, ch, 0, c1, round(s1, 3), c2, round(s2, 3)))
    return out


def render_embedded_glyphs(doc: pymupdf.Document, xref: int, chars: str, dpi: int = 144) -> dict[str, bytes]:
    """PNG de cada glifo isolado, para a tela de confirmação do mapa."""
    rebuilt = embedded_glyph_font(doc, xref)
    if rebuilt is None:
        return {}
    buf, codes = rebuilt
    images: dict[str, bytes] = {}
    for ch in chars:
        if ch in codes:
            tmp = pymupdf.open()
            page = tmp.new_page(width=60, height=60)
            page.insert_font(fontname="g", fontbuffer=buf)
            page.insert_text((8, 44), chr(codes[ch]), fontsize=36, fontname="g")
            images[ch] = page.get_pixmap(dpi=dpi).tobytes("png")
    return images

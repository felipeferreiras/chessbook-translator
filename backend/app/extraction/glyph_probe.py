"""Inspeção visual de glifos para identificar símbolos de peças.

Quando o PDF mostra ``♘`` mas a camada de texto devolve ``N`` (fonte figurina
que reaproveita letras) ou ``\\ue004`` (Área de Uso Privado), o texto extraído
não basta. Este módulo recorta o glifo renderizado na própria página e o
compara com desenhos de referência de figurinas e de letras.

O resultado é uma **proposta** de mapeamento por (fonte, caractere), nunca
uma substituição automática: a interface deve pedir confirmação ao usuário e
o mapeamento vale apenas para aquela fonte naquele documento.

Limitação conhecida: as referências usam a DejaVu Sans. Fontes de editoras
(Merida, Alpha, Leipzig, fontes figurinas comerciais) têm desenhos diferentes;
a similaridade tende a ser menor e a margem entre candidatos, a decidir.
"""

from __future__ import annotations

import functools
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

REFERENCE_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
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


@functools.cache
def _references() -> dict[str, np.ndarray]:
    refs: dict[str, np.ndarray] = {}
    for ch in FIGURINE_REFS + LETTER_REFS:
        doc = pymupdf.open()
        page = doc.new_page(width=60, height=60)
        page.insert_text((10, 45), ch, fontsize=36, fontname="ref", fontfile=str(REFERENCE_FONT))
        vec = _normalize(_render_clip(page, page.rect, 144))
        if vec is not None:
            refs[ch] = vec
    return refs


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
    refs = _references()
    out: list[GlyphObservation] = []
    for (font, c), (rect, count) in sorted(seen.items()):
        vec = _normalize(_render_clip(page, rect, dpi))
        if vec is None:
            continue
        scored = sorted(((_similarity(vec, r), ch) for ch, r in refs.items()), reverse=True)
        (s1, c1), (s2, c2) = scored[0], scored[1]
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

"""Reaproveitar a fonte original do livro quando ela tem todas as letras da tradução.

Os PDFs trazem subconjuntos das fontes: só os glifos que o texto em inglês
usou. Um título traduzido pode precisar de letras que o subconjunto não tem
("ç", "ã"); nesse caso vale a fonte substituta. Quando todas estão lá, a
fonte original é recriada com um ``cmap`` Unicode (a partir do ``ToUnicode``
do PDF) e usada como está: mesmo desenho, mesmas métricas, e o texto do PDF
gerado continua copiável.
"""

from __future__ import annotations

import io
import logging

import pymupdf

from app.extraction.font_profiles import base_font_name
from app.extraction.glyph_probe import _ref_xref, parse_tounicode


def embedded_text_font(doc: pymupdf.Document, xref: int) -> tuple[bytes, frozenset[str]] | None:
    """(fonte TrueType com cmap Unicode, caracteres que ela tem) ou None se não der."""
    from fontTools.ttLib import TTFont, newTable
    from fontTools.ttLib.tables._c_m_a_p import cmap_format_4

    try:
        _name, ext, _type, buf = doc.extract_font(xref)
    except Exception:  # noqa: BLE001 - fonte não extraível: usa a substituta
        return None
    tu_xref = _ref_xref(doc, xref, "ToUnicode")
    if not buf or ext != "ttf" or tu_xref is None:
        return None
    desc = _ref_xref(doc, xref, "DescendantFonts")
    if desc is not None and doc.xref_get_key(desc, "CIDToGIDMap")[0] == "xref":
        return None
    to_unicode = parse_tounicode(doc.xref_stream(tu_xref).decode("latin-1"))
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    try:
        font = TTFont(io.BytesIO(buf))
        order = font.getGlyphOrder()
        mapping = {ord(t): order[cid] for cid, t in to_unicode.items()
                   if len(t) == 1 and 0 < cid < len(order) and ord(t) <= 0xFFFF}
        if not mapping:
            return None
        sub = cmap_format_4(4)
        sub.platformID, sub.platEncID, sub.language = 3, 1, 0
        sub.cmap = mapping
        table = newTable("cmap")
        table.tableVersion = 0
        table.tables = [sub]
        font["cmap"] = table
        out = io.BytesIO()
        font.save(out)
    except Exception:  # noqa: BLE001 - subconjunto malformado: usa a substituta
        return None
    return out.getvalue(), frozenset(chr(c) for c in mapping)


class OriginalFonts:
    """Fontes originais de um documento, recriadas uma vez por fonte."""

    def __init__(self, doc: pymupdf.Document):
        self.doc = doc
        self._cache: dict[int, tuple[bytes, frozenset[str]] | None] = {}

    def for_page(self, page: pymupdf.Page) -> dict[str, int]:
        """Nome base da fonte → xref, para as fontes usadas na página."""
        return {base_font_name(f[3]): f[0] for f in page.get_fonts(full=True)}

    def get(self, xref: int) -> tuple[bytes, frozenset[str]] | None:
        if xref not in self._cache:
            self._cache[xref] = embedded_text_font(self.doc, xref)
        return self._cache[xref]

    @staticmethod
    def missing(chars: frozenset[str], text: str) -> list[str]:
        """Letras do texto que a fonte não tem (espaço e quebras não contam)."""
        return sorted({ch for ch in text if not ch.isspace() and ch not in chars})

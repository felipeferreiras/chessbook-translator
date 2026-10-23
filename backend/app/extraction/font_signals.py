"""Sinais de cada fonte de um PDF: qual pode ser figurina ou diagrama, e como sondá-la.

Antes de pedir ao usuário que confirme um mapa de glifos, o sistema precisa
saber quais fontes merecem atenção e de que jeito o glifo pode ser visto:

* ``embedded``: a fonte é TrueType/CFF incorporada com ``ToUnicode``; cada
  glifo é desenhado isolado (``probe_embedded_font``), sem vizinhos.
* ``page``: Type 3 (glifos desenhados por procedimento) ou sem ``ToUnicode``;
  só dá para recortar o glifo da página renderizada (``probe_page``).

Nada aqui decide um mapa: os sinais só ordenam o que mostrar ao usuário.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

import pymupdf

from .font_profiles import KNOWN_PROFILES, FontProfile, FontRole, base_font_name, profile_for

# Famílias comuns de fontes de xadrez (figurinas e diagramas) em livros e revistas.
_CHESS_NAME = re.compile(
    r"figurin|chess|xadrez|schach|diagram|linares|merida|alpha|leipzig|cases|zurich|berlin|tilburg|"
    r"usc[fs]|habsburg|kingdom|marroquin|motif|condal|magnetic|lucena|informator",
    re.IGNORECASE,
)
_DIAGRAM_NAME = re.compile(r"diagram|board|tabuleiro", re.IGNORECASE)
_PIECE_LETTERS = set("KQRBNPDTC")


class FontGuess(StrEnum):
    KNOWN = "known"  # perfil confirmado pelo usuário
    LIKELY_FIGURINE = "likely_figurine"
    LIKELY_DIAGRAM = "likely_diagram"
    UNKNOWN_SYMBOLS = "unknown_symbols"  # uso privado ou sem ToUnicode: o texto extraído não diz o que é
    TEXT = "text"


@dataclass
class FontSignals:
    name: str
    xref: int
    subtype: str  # Type0, TrueType, Type1, Type3...
    has_tounicode: bool
    chars: Counter[str] = field(default_factory=Counter)
    long_runs: int = 0  # trechos de 8+ caracteres sem espaço (linhas de tabuleiro)
    spans: int = 0
    profile: FontProfile | None = None
    guess: FontGuess = FontGuess.TEXT
    probe: str | None = None  # "embedded" | "page" | None
    reasons: list[str] = field(default_factory=list)

    @property
    def private_use_share(self) -> float:
        total = sum(self.chars.values())
        pua = sum(n for ch, n in self.chars.items() if unicodedata.category(ch) == "Co")
        return pua / total if total else 0.0


def _descendant_has_fontfile(doc: pymupdf.Document, xref: int) -> bool:
    """A fonte incorporada pode ser redesenhada isoladamente (TrueType/CFF)?"""
    keys = [xref]
    kind, value = doc.xref_get_key(xref, "DescendantFonts")
    if kind == "array":
        keys += [int(x) for x in re.findall(r"(\d+) 0 R", value)]
    for key in keys:
        kind, value = doc.xref_get_key(key, "FontDescriptor")
        if kind == "xref":
            desc = int(value.split()[0])
            if any(doc.xref_get_key(desc, k)[0] == "xref" for k in ("FontFile2", "FontFile3", "FontFile")):
                return True
    return False


def _classify(sig: FontSignals, embeddable: bool) -> None:
    letters = sum(n for ch, n in sig.chars.items() if ch.isalpha() and unicodedata.category(ch) != "Co")
    total = sum(sig.chars.values()) or 1
    piece_letters = {ch for ch in sig.chars if ch in _PIECE_LETTERS}
    hint = _CHESS_NAME.search(sig.name)
    if sig.profile is not None:
        sig.guess = FontGuess.KNOWN
        sig.reasons.append(f"perfil {sig.profile.family} ({sig.profile.role.value}, {sig.profile.status.value})")
    elif hint and (_DIAGRAM_NAME.search(sig.name) or (sig.spans and sig.long_runs / sig.spans > 0.5)):
        sig.guess = FontGuess.LIKELY_DIAGRAM
        sig.reasons.append(f"nome sugere fonte de xadrez ({hint.group()}) e o texto forma linhas de tabuleiro")
    elif hint:
        sig.guess = FontGuess.LIKELY_FIGURINE
        sig.reasons.append(f"nome sugere fonte de xadrez ({hint.group()})")
    elif sig.private_use_share > 0.3:
        sig.guess = FontGuess.UNKNOWN_SYMBOLS
        sig.reasons.append(f"{sig.private_use_share:.0%} dos caracteres na Área de Uso Privado")
    elif not sig.has_tounicode and sig.subtype == "Type3":
        sig.guess = FontGuess.UNKNOWN_SYMBOLS
        sig.reasons.append("Type 3 sem ToUnicode: o texto extraído vem só da codificação")
    elif sig.chars and letters / total > 0.9 and piece_letters and len(set(sig.chars)) <= 8 and sig.spans:
        sig.guess = FontGuess.LIKELY_FIGURINE
        sig.reasons.append(f"só usa letras de peça ({''.join(sorted(piece_letters))}) em trechos curtos")
    if sig.subtype == "Type3":
        sig.reasons.append("Type 3: glifos desenhados por procedimento; só o recorte da página serve de probe")
    if sig.guess != FontGuess.TEXT:
        sig.probe = "embedded" if embeddable and sig.has_tounicode and sig.subtype != "Type3" else "page"


def font_signals(doc: pymupdf.Document, pages: range | None = None,
                 profiles: tuple[FontProfile, ...] = KNOWN_PROFILES) -> list[FontSignals]:
    """Sinais de todas as fontes das páginas, ordenadas das que mais pedem atenção."""
    by_name: dict[str, FontSignals] = {}
    for pno in pages or range(doc.page_count):
        page = doc[pno]
        for xref, _ext, subtype, basefont, *_ in page.get_fonts(full=True):
            name = base_font_name(basefont)
            if name not in by_name:
                has_tu = doc.xref_get_key(xref, "ToUnicode")[0] == "xref"
                by_name[name] = FontSignals(name, xref, subtype, has_tu, profile=profile_for(name, profiles))
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    sig = by_name.get(base_font_name(span["font"]))
                    if sig is None:
                        continue
                    sig.spans += 1
                    sig.chars.update(ch for ch in span["text"] if not ch.isspace())
                    sig.long_runs += sum(1 for tok in span["text"].split() if len(tok) >= 8)
    order = {FontGuess.UNKNOWN_SYMBOLS: 0, FontGuess.LIKELY_FIGURINE: 1, FontGuess.LIKELY_DIAGRAM: 2,
             FontGuess.KNOWN: 3, FontGuess.TEXT: 4}
    for sig in by_name.values():
        _classify(sig, _descendant_has_fontfile(doc, sig.xref))
    return sorted(by_name.values(), key=lambda s: (order[s.guess], s.name))


__all__ = ["FontGuess", "FontRole", "FontSignals", "font_signals"]

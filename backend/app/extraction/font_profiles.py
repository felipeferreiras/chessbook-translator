"""Perfis de fontes especiais de xadrez e resolução do texto extraído.

Um perfil diz o que cada caractere *extraído* de uma fonte realmente *desenha*.
Fontes figurinas de editoras reaproveitam letras ASCII: na família Linares,
``K`` desenha ♔ e ``i`` desenha "+−". Sem o perfil, a camada de texto do PDF
diz "Kd6i"; com ele, o texto resolvido é "♔d6+−".

Regras:

* O perfil vale para uma família de fontes identificada pelo nome (sem o
  prefixo de subconjunto ``ABCDEF+``). Um perfil ``proposed`` precisa de
  confirmação humana; até lá, regiões resolvidas com ele ficam marcadas.
* Caracteres da fonte que não estão no perfil nem na lista de identidade são
  reportados como ``unmapped``: nada é adivinhado.
* A resolução preserva a origem: cada caractere do texto resolvido aponta
  para o caractere extraído que o produziu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class ProfileStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"


class FontRole(StrEnum):
    FIGURINE = "figurine"  # notação dentro do texto
    DIAGRAM = "diagram"  # tabuleiro composto como texto


@dataclass(frozen=True)
class FontProfile:
    family: str  # regex sobre o nome da fonte sem prefixo de subconjunto
    role: FontRole
    char_map: dict[str, str]
    identity: str  # caracteres que desenham a si mesmos
    status: ProfileStatus
    evidence: str

    def matches(self, font_name: str) -> bool:
        return re.fullmatch(self.family, base_font_name(font_name)) is not None


def base_font_name(font_name: str) -> str:
    return font_name.split("+", 1)[1] if re.match(r"^[A-Z]{6}\+", font_name) else font_name


_LINARES_EVIDENCE = (
    "Leitura visual de cada glifo isolado da fonte incorporada (folha de contato), "
    "Dvoretsky's Endgame Manual (Russell Enterprises, 2020), 2026-10-22. "
    "Comparação automática com fontes livres foi inconclusiva para K e B. "
    "Glifos conferidos também renderizados isoladamente a partir da fonte incorporada. "
    "Mapa confirmado pelo usuário em 2026-10-22 (folha de confirmação)."
)

LINARES_FIGURINE = FontProfile(
    family=r"LinaresFigurine(Bold)?",
    role=FontRole.FIGURINE,
    char_map={
        "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "C": "♘", "P": "♙",
        "x": "×",
        "i": "+−", "o": "−+", "y": "±", "u": "∓", "r": "⩲", "t": "⩱",
        "q": "∞", "m": "⇆", "*": "⊙", "$": "△", "~": "□",
    },
    identity="abcdefgh0123456789O+-=!?#.:()  ",
    status=ProfileStatus.CONFIRMED,
    evidence=_LINARES_EVIDENCE,
)

# Diagrama Linares: cada caractere é uma casa (vazia ou com peça) já na cor da
# casa. Valor: (símbolo FEN ou "" para vazio, "light" | "dark").
LINARES_DIAGRAM_SQUARES: dict[str, tuple[str, str]] = {
    "w": ("", "light"), "s": ("", "light"), "d": ("", "dark"), "D": ("", "dark"),
    "K": ("K", "light"), "Q": ("Q", "light"), "R": ("R", "light"),
    "B": ("B", "light"), "N": ("N", "light"), "P": ("P", "light"),
    "I": ("K", "dark"), "!": ("Q", "dark"), "$": ("R", "dark"),
    "G": ("B", "dark"), "H": ("N", "dark"), ")": ("P", "dark"),
    "k": ("k", "light"), "q": ("q", "light"), "r": ("r", "light"),
    "b": ("b", "light"), "n": ("n", "light"), "p": ("p", "light"),
    "i": ("k", "dark"), "1": ("q", "dark"), "4": ("r", "dark"),
    "g": ("b", "dark"), "h": ("n", "dark"), "0": ("p", "dark"),
}
# Marcas sobre casas vazias (cruz) e moldura.
LINARES_DIAGRAM_MARKS = {"X": "light", "Z": "dark"}
LINARES_DIAGRAM_FRAME = set("cuCvlV{}")

LINARES_DIAGRAM = FontProfile(
    family=r"LinaresDiagram",
    role=FontRole.DIAGRAM,
    char_map={},
    identity="",
    status=ProfileStatus.CONFIRMED,
    evidence=_LINARES_EVIDENCE,
)

KNOWN_PROFILES: tuple[FontProfile, ...] = (LINARES_FIGURINE, LINARES_DIAGRAM)


def profile_for(font_name: str, profiles: tuple[FontProfile, ...] = KNOWN_PROFILES) -> FontProfile | None:
    return next((p for p in profiles if p.matches(font_name)), None)


@dataclass(frozen=True)
class SpanText:
    """Trecho extraído com a fonte que o desenhou (e o estilo)."""

    text: str
    font: str
    bold: bool = False
    italic: bool = False


@dataclass
class ResolvedText:
    text: str
    origin: list[int]  # para cada caractere resolvido, índice no texto extraído
    raw: str
    profiles_used: set[str] = field(default_factory=set)
    unmapped: list[tuple[str, str]] = field(default_factory=list)  # (fonte, caractere)
    proposed_only: bool = False  # algum perfil usado ainda não foi confirmado


def resolve_spans(spans: list[SpanText], profiles: tuple[FontProfile, ...] = KNOWN_PROFILES) -> ResolvedText:
    """Concatena os trechos de uma região trocando glifos especiais pelo que desenham.

    Trechos de fonte de diagrama não entram no texto: pertencem ao tabuleiro.
    """
    out: list[str] = []
    origin: list[int] = []
    raw_parts: list[str] = []
    used: set[str] = set()
    unmapped: list[tuple[str, str]] = []
    proposed = False
    raw_index = 0
    for span in spans:
        prof = profile_for(span.font, profiles)
        raw_parts.append(span.text)
        if prof is not None and prof.role == FontRole.DIAGRAM:
            raw_index += len(span.text)
            continue
        for ch in span.text:
            if prof is None:
                rep = ch
            else:
                used.add(prof.family)
                proposed |= prof.status == ProfileStatus.PROPOSED
                if ch in prof.char_map:
                    rep = prof.char_map[ch]
                elif ch in prof.identity:
                    rep = ch
                else:
                    rep = ch
                    unmapped.append((base_font_name(span.font), ch))
            out.append(rep)
            origin.extend([raw_index] * len(rep))
            raw_index += 1
    return ResolvedText(
        text="".join(out), origin=origin, raw="".join(raw_parts),
        profiles_used=used, unmapped=unmapped, proposed_only=proposed,
    )

"""Alfabetos de peças das convenções de notação suportadas.

Um alfabeto associa cada caractere de peça a um ou mais tipos de peça. Mais de
um tipo significa ambiguidade real: ``R`` é torre em inglês e rei em português.
Nesse caso o validador testa as interpretações e não escolhe sozinho.
"""

from __future__ import annotations

from enum import StrEnum

import chess


class Convention(StrEnum):
    ENGLISH = "english"  # K Q R B N
    PORTUGUESE = "portuguese"  # R D T B C
    FIGURINE = "figurine"  # ♔ ♕ ♖ ♗ ♘ (e equivalentes pretos)
    DESCRIPTIVE = "descriptive"  # P-K4, N-KB3 (detectada, não convertida)
    UNDETERMINED = "undetermined"


ENGLISH = {"K": chess.KING, "Q": chess.QUEEN, "R": chess.ROOK, "B": chess.BISHOP, "N": chess.KNIGHT}
PORTUGUESE = {"R": chess.KING, "D": chess.QUEEN, "T": chess.ROOK, "B": chess.BISHOP, "C": chess.KNIGHT}
FIGURINE_WHITE = {"♔": chess.KING, "♕": chess.QUEEN, "♖": chess.ROOK, "♗": chess.BISHOP, "♘": chess.KNIGHT}
FIGURINE_BLACK = {"♚": chess.KING, "♛": chess.QUEEN, "♜": chess.ROOK, "♝": chess.BISHOP, "♞": chess.KNIGHT}
FIGURINE = FIGURINE_WHITE | FIGURINE_BLACK

# Todos os caracteres que o analisador léxico aceita como possíveis peças.
ALL_PIECE_CHARS = "".join(sorted(set(ENGLISH) | set(PORTUGUESE) | set(FIGURINE)))

# Letras que sozinhas indicam uma convenção.
ENGLISH_ONLY = set(ENGLISH) - set(PORTUGUESE)  # K Q N
PORTUGUESE_ONLY = set(PORTUGUESE) - set(ENGLISH)  # D T C

OUTPUT_SYMBOL = {
    Convention.ENGLISH: {v: k for k, v in ENGLISH.items()},
    Convention.PORTUGUESE: {v: k for k, v in PORTUGUESE.items()},
    Convention.FIGURINE: {v: k for k, v in FIGURINE_WHITE.items()},
}

Alphabet = dict[str, frozenset[int]]


def alphabet_for(convention: Convention) -> Alphabet:
    """Devolve o alfabeto usado para interpretar lances numa convenção.

    Símbolos figurativos Unicode são inequívocos e sempre aceitos. Letras só são
    aceitas conforme a convenção; se ela não estiver determinada, usa-se a união
    dos alfabetos, com ``R`` ambíguo entre torre e rei.
    """
    out: dict[str, set[int]] = {ch: {pt} for ch, pt in FIGURINE.items()}
    if convention == Convention.ENGLISH:
        letters = [ENGLISH]
    elif convention == Convention.PORTUGUESE:
        letters = [PORTUGUESE]
    elif convention in (Convention.UNDETERMINED, Convention.FIGURINE):
        # Livros figurativos às vezes têm letras em índices ou tabelas; sem uma
        # convenção confirmada, as letras são tratadas como ambíguas.
        letters = [ENGLISH, PORTUGUESE]
    else:
        letters = []
    for table in letters:
        for ch, pt in table.items():
            out.setdefault(ch, set()).add(pt)
    return {ch: frozenset(types) for ch, types in out.items()}

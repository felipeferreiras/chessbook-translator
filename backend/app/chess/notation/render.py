"""Geração da representação de saída da notação.

A conversão troca apenas os caracteres de peça (e de promoção) dentro dos
limites exatos de cada lance. Desambiguação, separadores, roque, xeque e
sinais de avaliação do autor são mantidos. Todo o resto do texto é copiado
sem alteração.

Política padrão (``strict``): só lances ``VALIDATED`` são convertidos. Lances
sem contexto, ambíguos ou ilegais ficam com a grafia original e são
listados em ``not_converted``. A política ``symbol_only`` também converte
lances sem posição conhecida, desde que o caractere de peça tenha um único
significado no alfabeto de origem; esses lances são marcados para revisão.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import chess

from .alphabets import OUTPUT_SYMBOL, Alphabet, Convention, alphabet_for
from .validate import MoveAnalysis, MoveStatus, RegionAnalysis


class OutputNotation(StrEnum):
    PRESERVE = "preserve"
    ENGLISH = "english"
    PORTUGUESE = "portuguese"
    FIGURINE = "figurine"


class ConversionPolicy(StrEnum):
    STRICT = "strict"
    SYMBOL_ONLY = "symbol_only"


@dataclass(frozen=True)
class Change:
    start: int
    end: int
    original: str
    output: str
    validated: bool


@dataclass
class RenderResult:
    text: str
    changes: list[Change] = field(default_factory=list)
    not_converted: list[tuple[str, str]] = field(default_factory=list)  # (lance, motivo)


_TARGET = {
    OutputNotation.ENGLISH: Convention.ENGLISH,
    OutputNotation.PORTUGUESE: Convention.PORTUGUESE,
    OutputNotation.FIGURINE: Convention.FIGURINE,
}


def _piece_type(ch: str, alphabet: Alphabet) -> int | None:
    types = alphabet.get(ch)
    return next(iter(types)) if types and len(types) == 1 else None


def _convert_token(analysis: MoveAnalysis, target: Convention, alphabet: Alphabet) -> str | None:
    atom, mv = analysis.atom, analysis.atom.move
    assert mv is not None
    if mv.castle:
        return atom.text  # roque não tem letra de peça; mantém a grafia do livro
    symbols = OUTPUT_SYMBOL[target]
    text = atom.text
    if analysis.status == MoveStatus.VALIDATED and analysis.uci and analysis.fen_before:
        board = chess.Board(analysis.fen_before)
        move = chess.Move.from_uci(analysis.uci)
        piece_type = board.piece_type_at(move.from_square)
        promo_type = move.promotion
    else:
        piece_type = _piece_type(mv.piece_char, alphabet) if mv.piece_char else chess.PAWN
        promo_type = _piece_type(mv.promotion_char, alphabet) if mv.promotion_char else None
        if piece_type is None or (mv.promotion_char and promo_type is None):
            return None
    out = text
    if mv.pawn_char:
        # Letras não têm símbolo de peão ("e4"); em figurinas, a de peão branca, como as demais.
        assert out.startswith(mv.pawn_char)
        out = ("♙" if target == Convention.FIGURINE else "") + out[len(mv.pawn_char):]
    if mv.piece_char:
        assert out.startswith(mv.piece_char)
        out = symbols[piece_type] + out[len(mv.piece_char):]
    if mv.promotion_char and promo_type:
        idx = out.rfind(mv.promotion_char)
        out = out[:idx] + symbols[promo_type] + out[idx + len(mv.promotion_char):]
    return out


def render_region(
    analysis: RegionAnalysis,
    target: OutputNotation,
    source_convention: Convention,
    policy: ConversionPolicy = ConversionPolicy.STRICT,
) -> RenderResult:
    text = analysis.lexed.text
    if target == OutputNotation.PRESERVE:
        return RenderResult(text=text)
    if source_convention == Convention.DESCRIPTIVE:
        return RenderResult(text=text, not_converted=[(text, "descriptive_notation_unsupported")])
    target_conv = _TARGET[target]
    alphabet = alphabet_for(source_convention)
    pieces: list[str] = []
    changes: list[Change] = []
    skipped: list[tuple[str, str]] = []
    cursor = 0
    for m in analysis.moves:
        atom = m.atom
        allowed = m.status == MoveStatus.VALIDATED or (
            policy == ConversionPolicy.SYMBOL_ONLY and m.status == MoveStatus.NO_CONTEXT
        )
        new = _convert_token(m, target_conv, alphabet) if allowed else None
        if new is None:
            if atom.move and (atom.move.piece_char or atom.move.promotion_char):
                skipped.append((atom.text, m.status.value if not allowed else "ambiguous_piece_symbol"))
            continue
        if new != atom.text:
            pieces.append(text[cursor:atom.start])
            pieces.append(new)
            cursor = atom.end
            changes.append(Change(atom.start, atom.end, atom.text, new, m.status == MoveStatus.VALIDATED))
    pieces.append(text[cursor:])
    return RenderResult(text="".join(pieces), changes=changes, not_converted=skipped)

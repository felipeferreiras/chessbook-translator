"""Validação de lances e sequências com as regras do xadrez (python-chess).

Princípios aplicados:

* Um lance só é ``VALIDATED`` quando há uma posição conhecida e exatamente uma
  interpretação legal. Mais de uma interpretação é ``AMBIGUOUS``; nenhuma é
  ``ILLEGAL``; sem posição é ``NO_CONTEXT``. Nada é corrigido.
* Depois de um lance ambíguo, ilegal ou suspeito, a posição deixa de ser
  conhecida: os lances seguintes ficam ``NO_CONTEXT`` em vez de serem
  validados sobre uma posição possivelmente errada.
* A posição inicial padrão nunca é presumida, a menos que o chamador peça
  (``assume_standard_start``) e a região comece em "1." — e mesmo assim a
  região é marcada para revisão com a origem ``STANDARD_HYPOTHESIS``.
* Um trecho de notação que começa sem número de lance depois de prosa
  ("... com ...d6") não herda a posição, exceto se ela vier de um diagrama ou
  FEN confirmados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import chess

from .alphabets import FIGURINE_BLACK, Alphabet, Convention, alphabet_for
from .lexer import Atom, AtomKind, LexResult, lex


class MoveStatus(StrEnum):
    VALIDATED = "validated"
    AMBIGUOUS = "ambiguous"
    ILLEGAL = "illegal"
    NO_CONTEXT = "no_context"
    UNRECOGNIZED_PIECE = "unrecognized_piece"


class ContextSource(StrEnum):
    FEN_CONFIRMED = "fen_confirmed"
    STANDARD_CONFIRMED = "standard_confirmed"
    STANDARD_HYPOTHESIS = "standard_hypothesis"
    CONTINUATION = "continuation"
    UNKNOWN = "unknown"


# Avisos que exigem revisão humana. Os demais são informativos.
REVIEW_WARNINGS = frozenset({
    "piece_letter_resolved_by_legality",
    "capture_marker_without_capture",
    "capture_without_marker",
    "check_marker_without_check",
    "mate_marker_without_mate",
    "en_passant_marker_mismatch",
    "side_to_move_mismatch",
    "move_number_gap",
    "implicit_branch_inside_span",
    "promotion_piece_missing",
})


@dataclass
class Context:
    board: chess.Board | None
    source: ContextSource

    @classmethod
    def unknown(cls) -> Context:
        return cls(None, ContextSource.UNKNOWN)

    @classmethod
    def from_fen(cls, fen: str) -> Context:
        return cls(chess.Board(fen), ContextSource.FEN_CONFIRMED)

    @classmethod
    def standard(cls) -> Context:
        return cls(chess.Board(), ContextSource.STANDARD_CONFIRMED)


@dataclass
class MoveAnalysis:
    atom: Atom
    status: MoveStatus
    context: ContextSource
    fen_before: str | None = None
    uci: str | None = None
    canonical_san: str | None = None  # SAN inglês gerado pelo python-chess
    interpretations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return (
            self.status != MoveStatus.VALIDATED
            or self.context == ContextSource.STANDARD_HYPOTHESIS
            or any(w in REVIEW_WARNINGS for w in self.warnings)
        )


@dataclass
class RegionAnalysis:
    lexed: LexResult
    moves: list[MoveAnalysis]
    issues: list[str]
    end_context: Context

    @property
    def needs_review(self) -> bool:
        return bool(self.issues) or any(m.needs_review for m in self.moves)

    def by_status(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for m in self.moves:
            out[m.status.value] = out.get(m.status.value, 0) + 1
        return out


def _candidates(board: chess.Board, atom: Atom, alphabet: Alphabet) -> tuple[list[chess.Move], set[int] | None, list[str]]:
    mv = atom.move
    assert mv is not None
    warnings: list[str] = []
    if mv.castle:
        side = board.is_kingside_castling if mv.castle == "K" else board.is_queenside_castling
        return [m for m in board.legal_moves if side(m)], None, warnings
    if mv.piece_char is None:
        types: set[int] | None = {chess.PAWN}
    else:
        found = alphabet.get(mv.piece_char)
        types = set(found) if found else None
        if types is None:
            return [], None, warnings
    promo_types: set[int] | None = None
    if mv.promotion_char:
        found = alphabet.get(mv.promotion_char)
        promo_types = set(found) if found else set()
    to_sq = chess.parse_square(mv.to_square) if mv.to_square else None
    out = []
    for m in board.legal_moves:
        if board.is_castling(m) or m.to_square != to_sq:
            continue
        if board.piece_type_at(m.from_square) not in types:
            continue
        if mv.from_file and chess.square_file(m.from_square) != "abcdefgh".index(mv.from_file):
            continue
        if mv.from_rank and chess.square_rank(m.from_square) != int(mv.from_rank) - 1:
            continue
        if promo_types is not None and m.promotion not in promo_types:
            continue
        out.append(m)
    if mv.promotion_char is None and len(out) > 1 and all(m.promotion for m in out):
        warnings.append("promotion_piece_missing")
    return out, types, warnings


def _consistency(board: chess.Board, atom: Atom, move: chess.Move) -> list[str]:
    mv = atom.move
    assert mv is not None
    w: list[str] = []
    is_cap = board.is_capture(move)
    claims = mv.claims_capture
    if claims is True and not is_cap:
        w.append("capture_marker_without_capture")
    elif claims is False and is_cap:
        w.append("capture_without_marker")
    if mv.en_passant and not board.is_en_passant(move):
        w.append("en_passant_marker_mismatch")
    if mv.piece_char in FIGURINE_BLACK and board.turn == chess.WHITE:
        w.append("figurine_color_mismatch")
    gives_check = board.gives_check(move)
    board.push(move)
    mate = board.is_checkmate()
    board.pop()
    if mv.check in ("+", "++", "†") and not gives_check:
        w.append("check_marker_without_check")
    elif mv.check in ("#", "‡") and not mate:
        w.append("mate_marker_without_mate")
    elif not mv.check and mate:
        w.append("missing_mate_marker")
    elif not mv.check and gives_check:
        w.append("missing_check_marker")
    elif mv.check in ("+", "++", "†") and mate:
        w.append("mate_marked_as_check")
    return w


def analyze_region(
    text: str,
    context: Context | None = None,
    convention: Convention = Convention.UNDETERMINED,
    assume_standard_start: bool = False,
) -> RegionAnalysis:
    """Analisa uma região de texto (parágrafo, legenda, nota) com seus lances."""
    lexed = lex(text)
    alphabet = alphabet_for(convention)
    ctx = context or Context.unknown()
    history: list[chess.Board] = [ctx.board.copy()] if ctx.board else []
    source = ctx.source
    stack: list[tuple[list[chess.Board], ContextSource]] = []
    moves: list[MoveAnalysis] = []
    issues: list[str] = []

    def lose_context() -> None:
        nonlocal history, source
        history, source = [], ContextSource.UNKNOWN

    if convention == Convention.DESCRIPTIVE:
        issues.append("descriptive_notation_unsupported")

    for span_index, span in enumerate(lexed.spans):
        first = span.atoms[0]
        starts_numbered = first.kind == AtomKind.MOVE_NUMBER or (
            first.kind == AtomKind.VAR_OPEN and len(span.atoms) > 1 and span.atoms[1].kind == AtomKind.MOVE_NUMBER
        )
        if not history and assume_standard_start and span_index == 0 and first.kind == AtomKind.MOVE_NUMBER \
                and first.number == 1 and not first.black:
            history, source = [chess.Board()], ContextSource.STANDARD_HYPOTHESIS
            issues.append("start_position_assumed_standard")
        detached = not starts_numbered and not (span_index == 0 and source == ContextSource.FEN_CONFIRMED)
        pending_warning: list[str] = []
        for pos_in_span, atom in enumerate(span.atoms):
            if atom.kind == AtomKind.DESCRIPTIVE:
                issues.append(f"descriptive_notation_unsupported:{atom.text}")
            elif atom.kind == AtomKind.SUSPICIOUS:
                issues.append(f"suspicious_notation:{atom.text}")
                lose_context()
            elif atom.kind == AtomKind.VAR_OPEN:
                stack.append((list(history), source))
                history = history[:-1] if len(history) >= 2 else []
            elif atom.kind == AtomKind.VAR_CLOSE:
                if stack:
                    history, source = stack.pop()
                else:
                    issues.append("unbalanced_variation")
            elif atom.kind == AtomKind.MOVE_NUMBER and history and not detached:
                side = chess.BLACK if atom.black else chess.WHITE
                cur = history[-1]
                if cur.fullmove_number == atom.number and cur.turn == side:
                    continue
                idx = next(
                    (i for i, b in enumerate(history) if b.fullmove_number == atom.number and b.turn == side),
                    None,
                )
                if idx is None:
                    pending_warning.append("move_number_gap")
                    lose_context()
                else:
                    history = history[: idx + 1]
                    pending_warning.append(
                        "implicit_branch_by_move_number" if pos_in_span == 0 else "implicit_branch_inside_span"
                    )
            elif atom.kind == AtomKind.MOVE:
                warnings, pending_warning = pending_warning, []
                if detached or not history:
                    moves.append(MoveAnalysis(atom, MoveStatus.NO_CONTEXT, ContextSource.UNKNOWN, warnings=warnings))
                    continue
                board = history[-1]
                if atom.ellipsis_prefix and board.turn != chess.BLACK:
                    warnings.append("side_to_move_mismatch")
                    moves.append(MoveAnalysis(atom, MoveStatus.ILLEGAL, source, board.fen(), warnings=warnings))
                    lose_context()
                    continue
                cands, types, cand_warn = _candidates(board, atom, alphabet)
                warnings += cand_warn
                if types is None and atom.move and atom.move.piece_char and not atom.move.castle:
                    moves.append(MoveAnalysis(atom, MoveStatus.UNRECOGNIZED_PIECE, source, board.fen(), warnings=warnings))
                    lose_context()
                elif not cands:
                    moves.append(MoveAnalysis(atom, MoveStatus.ILLEGAL, source, board.fen(), warnings=warnings))
                    lose_context()
                elif len(cands) > 1:
                    moves.append(MoveAnalysis(
                        atom, MoveStatus.AMBIGUOUS, source, board.fen(),
                        interpretations=[m.uci() for m in cands], warnings=warnings,
                    ))
                    lose_context()
                else:
                    move = cands[0]
                    if types and len(types) > 1:
                        warnings.append("piece_letter_resolved_by_legality")
                    warnings += _consistency(board, atom, move)
                    moves.append(MoveAnalysis(
                        atom, MoveStatus.VALIDATED, source, board.fen(), uci=move.uci(),
                        canonical_san=board.san(move), warnings=warnings,
                    ))
                    nxt = board.copy(stack=False)
                    nxt.push(move)
                    history.append(nxt)
    # Uma posição presumida continua presumida nas regiões seguintes.
    end_source = source if source == ContextSource.STANDARD_HYPOTHESIS else ContextSource.CONTINUATION
    end = Context(history[-1].copy(), end_source) if history else Context.unknown()
    if stack:
        issues.append("unclosed_variation")
    return RegionAnalysis(lexed=lexed, moves=moves, issues=issues, end_context=end)

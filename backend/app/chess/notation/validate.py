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
from .lexer import DEFAULT_STYLE, Atom, AtomKind, LexResult, LexStyle, lex


class MoveStatus(StrEnum):
    VALIDATED = "validated"
    AMBIGUOUS = "ambiguous"
    ILLEGAL = "illegal"
    NO_CONTEXT = "no_context"
    UNRECOGNIZED_PIECE = "unrecognized_piece"


class ContextSource(StrEnum):
    FEN_CONFIRMED = "fen_confirmed"
    FEN_PROPOSED = "fen_proposed"  # posição lida de um diagrama, ainda não confirmada
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
    "branch_ambiguous",
})


@dataclass
class Context:
    board: chess.Board | None
    source: ContextSource
    # Só uma posição "fresca" (vinda direto de um diagrama ou FEN) aceita um
    # primeiro lance sem número; a posição herdada de outra região, não.
    fresh: bool = True
    # Diagramas não informam o número do lance; o primeiro número do texto vale.
    fullmove_known: bool = True

    @classmethod
    def unknown(cls) -> Context:
        return cls(None, ContextSource.UNKNOWN)

    @classmethod
    def from_fen(cls, fen: str) -> Context:
        return cls(chess.Board(fen), ContextSource.FEN_CONFIRMED)

    @classmethod
    def from_proposed_fen(cls, fen: str) -> Context:
        return cls(chess.Board(fen), ContextSource.FEN_PROPOSED, fullmove_known=False)

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
            or self.context in (ContextSource.STANDARD_HYPOTHESIS, ContextSource.FEN_PROPOSED)
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
    to_file = "abcdefgh".index(mv.to_file) if mv.to_file else None
    out = []
    for m in board.legal_moves:
        if board.is_castling(m):
            continue
        if to_file is not None:
            # Captura abreviada ("hg"): só a coluna de destino é conhecida.
            if chess.square_file(m.to_square) != to_file or not board.is_capture(m):
                continue
        elif m.to_square != to_sq:
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


@dataclass
class _Segment:
    atoms: list[Atom]
    main: bool


def _segments(lexed: LexResult, main_mask: list[bool] | None) -> list[_Segment]:
    """Divide os trechos de notação em segmentos de linha principal ou variante.

    Sem máscara, tudo é linha principal (uma só sequência). Com máscara (por
    exemplo, negrito = linha principal), um trecho é dividido onde a
    tipografia muda, exceto dentro de parênteses de variante.
    """
    if main_mask is None:
        return [_Segment(list(span.atoms), True) for span in lexed.spans]
    out: list[_Segment] = []
    for span in lexed.spans:
        depth = 0
        current: list[Atom] = []
        current_main: bool | None = None
        for atom in span.atoms:
            if atom.kind in (AtomKind.MOVE, AtomKind.MOVE_NUMBER) and depth == 0:
                is_main = atom.start < len(main_mask) and main_mask[atom.start]
                if current_main is None:
                    current_main = is_main
                elif is_main != current_main and not (
                    current and current[-1].kind in (AtomKind.MOVE_NUMBER, AtomKind.ELLIPSIS)
                ):
                    out.append(_Segment(current, current_main))
                    current, current_main = [], is_main
            if atom.kind == AtomKind.VAR_OPEN:
                depth += 1
            elif atom.kind == AtomKind.VAR_CLOSE:
                depth = max(0, depth - 1)
            current.append(atom)
        if current:
            out.append(_Segment(current, True if current_main is None else current_main))
    return out


def _has_position(line: list[chess.Board], number: int, side: chess.Color) -> bool:
    return any(b.fullmove_number == number and b.turn == side for b in line)


def _alt_destination(board: chess.Board, played: chess.Move, atom: Atom) -> list[chess.Move]:
    """Interpretações de "♕b5(c2)": a mesma peça indo à casa alternativa, ou um
    lance de peão para essa casa como alternativa ao lance jogado."""
    assert atom.move is not None and atom.move.to_square
    target = chess.parse_square(atom.move.to_square)
    same_piece = [m for m in board.legal_moves if m.from_square == played.from_square and m.to_square == target]
    pawn = [
        m for m in board.legal_moves
        if m.to_square == target and board.piece_type_at(m.from_square) == chess.PAWN and not board.is_capture(m)
    ]
    out = same_piece + [m for m in pawn if m not in same_piece]
    return out


def _trial(atoms: list[Atom], line: list[chess.Board], alphabet: Alphabet) -> tuple[bool, list[chess.Board]]:
    """Simula um segmento sobre uma linha: (todos os lances legais?, linha resultante).

    Ignora o conteúdo de parênteses. Usado só para escolher entre duas linhas
    candidatas a ponto de partida de uma variante.
    """
    hist = list(line)
    depth = 0
    for atom in atoms:
        if atom.kind in (AtomKind.VAR_OPEN, AtomKind.PAREN_OPEN):
            depth += 1
        elif atom.kind in (AtomKind.VAR_CLOSE, AtomKind.PAREN_CLOSE):
            depth = max(0, depth - 1)
        elif depth:
            continue
        elif atom.kind == AtomKind.MOVE_NUMBER:
            side = chess.BLACK if atom.black else chess.WHITE
            idx = next((i for i, b in enumerate(hist) if b.fullmove_number == atom.number and b.turn == side), None)
            if idx is None:
                return False, hist
            hist = hist[: idx + 1]
        elif atom.kind == AtomKind.EVAL and atom.text == "△":
            break  # o que vem depois é ideia, não sequência
        elif atom.kind == AtomKind.MOVE:
            cands, _, _ = _candidates(hist[-1], atom, alphabet)
            if len(cands) != 1:
                return False, hist
            nxt = hist[-1].copy(stack=False)
            nxt.push(cands[0])
            hist.append(nxt)
    return True, hist


def _branch_board(line: list[chess.Board], number: int, side: chess.Color) -> chess.Board | None:
    return next((b for b in line if b.fullmove_number == number and b.turn == side), None)


def _choose_branch(
    atoms: list[Atom], first: Atom, candidates: list[tuple[list[chess.Board], ContextSource]], alphabet: Alphabet,
) -> tuple[list[chess.Board], ContextSource, str | None, list[chess.Board] | None]:
    """Escolhe de qual linha parte uma variante numerada fora de parênteses.

    ``candidates`` vem em ordem de preferência: linha atual, alternativa ainda
    não descartada e linha principal. Só contam as que têm a posição indicada
    pelo número (posições iguais contam uma vez). Se sobra mais de uma, o
    segmento é simulado em cada: vence a única em que todos os lances são
    legais. Se mais de uma serve, usa-se a primeira, o segmento vai para
    revisão e a segunda continua viva como alternativa, para que um segmento
    posterior possa desempatar. Devolve (linha, origem, aviso, alternativa).
    """
    side = chess.BLACK if first.black else chess.WHITE
    viable: list[tuple[list[chess.Board], ContextSource]] = []
    seen: set[str] = set()
    for line, src in candidates:
        board = _branch_board(line, first.number or 0, side) if line else None
        if board is None or board.board_fen() + str(board.turn) in seen:
            continue
        seen.add(board.board_fen() + str(board.turn))
        viable.append((line, src))
    if not viable:
        main, main_source = candidates[-1]
        return list(main), main_source, None, None
    if len(viable) == 1:
        return list(viable[0][0]), viable[0][1], None, None
    results = [(line, src, *_trial(atoms, line, alphabet)) for line, src in viable]
    ok = [r for r in results if r[2]]
    if len(ok) == 1:
        return list(ok[0][0]), ok[0][1], "branch_chosen_by_legality", None
    pick = ok or results
    alternative = pick[1][3] if len(pick) > 1 else None
    return list(pick[0][0]), pick[0][1], "branch_ambiguous", alternative


def analyze_region(
    text: str,
    context: Context | None = None,
    convention: Convention = Convention.UNDETERMINED,
    assume_standard_start: bool = False,
    style: LexStyle = DEFAULT_STYLE,
    main_mask: list[bool] | None = None,
) -> RegionAnalysis:
    """Analisa uma região de texto (parágrafo, legenda, nota) com seus lances.

    ``main_mask`` marca, por caractere, o que a tipografia do livro indica como
    linha principal (por exemplo, lances em negrito). Variantes partem da linha
    atual ou da principal pelo número do lance e nunca alteram a principal;
    assim, uma ideia hipotética numa variante não faz a linha principal perder
    a posição. Parênteses de prosa com lances ("(but not 2 ♔f6? ...)") voltam à
    linha anterior ao serem fechados.
    """
    lexed = lex(text, style)
    alphabet = alphabet_for(convention)
    ctx = context or Context.unknown()
    main_history: list[chess.Board] = [ctx.board.copy()] if ctx.board else []
    main_source = ctx.source
    history = main_history
    source = main_source
    stack: list[tuple[list[chess.Board], ContextSource]] = []
    moves: list[MoveAnalysis] = []
    issues: list[str] = []
    last_played: tuple[chess.Board, chess.Move] | None = None

    def lose_context() -> None:
        nonlocal history, source, last_played
        history, source, last_played = [], ContextSource.UNKNOWN, None

    if convention == Convention.DESCRIPTIVE:
        issues.append("descriptive_notation_unsupported")

    pending_branch_warning: str | None = None
    alt_line: list[chess.Board] | None = None
    for seg_index, segment in enumerate(_segments(lexed, main_mask)):
        atoms = segment.atoms
        first = atoms[0]
        start_depth = len(stack)
        has_notation = any(a.kind in (AtomKind.MOVE, AtomKind.MOVE_NUMBER) for a in atoms)
        if start_depth == 0 and has_notation:
            if segment.main:
                history, source = main_history, main_source
                alt_line = None
            elif first.kind == AtomKind.MOVE_NUMBER:
                cands = [(history, source)]
                if alt_line:
                    cands.append((alt_line, source))
                cands.append((main_history, main_source))
                history, source, branch_warning, alt_line = _choose_branch(atoms, first, cands, alphabet)
                if branch_warning:
                    pending_branch_warning = branch_warning
            else:
                history, source = list(main_history), main_source
        starts_numbered = first.kind == AtomKind.MOVE_NUMBER or (
            first.kind in (AtomKind.VAR_OPEN, AtomKind.PAREN_OPEN)
            and len(atoms) > 1 and atoms[1].kind == AtomKind.MOVE_NUMBER
        )
        if not history and assume_standard_start and seg_index == 0 and first.kind == AtomKind.MOVE_NUMBER \
                and first.number == 1 and not first.black:
            history, source = [chess.Board()], ContextSource.STANDARD_HYPOTHESIS
            if segment.main:
                main_history, main_source = history, source
            issues.append("start_position_assumed_standard")
        detached = has_notation and not starts_numbered and not (
            seg_index == 0 and ctx.fresh and source in (ContextSource.FEN_CONFIRMED, ContextSource.FEN_PROPOSED)
        )
        pending_warning: list[str] = [pending_branch_warning] if pending_branch_warning else []
        pending_branch_warning = None
        idea_depth: int | None = None  # após "△", os lances são ideia, não sequência
        for pos_in_span, atom in enumerate(atoms):
            if idea_depth is not None and len(stack) < idea_depth:
                idea_depth = None
            if atom.kind == AtomKind.EVAL and atom.text == "△":
                idea_depth = len(stack)
            elif idea_depth is not None and atom.kind in (AtomKind.MOVE, AtomKind.ALT_DEST):
                moves.append(MoveAnalysis(atom, MoveStatus.NO_CONTEXT, ContextSource.UNKNOWN, warnings=["idea_move"]))
            elif atom.kind == AtomKind.DESCRIPTIVE:
                issues.append(f"descriptive_notation_unsupported:{atom.text}")
            elif atom.kind == AtomKind.SUSPICIOUS:
                issues.append(f"suspicious_notation:{atom.text}")
                lose_context()
            elif atom.kind == AtomKind.VAR_OPEN:
                stack.append((list(history), source))
                history = history[:-1] if len(history) >= 2 else []
                last_played = None
            elif atom.kind == AtomKind.PAREN_OPEN:
                stack.append((list(history), source))
                history = list(history)
            elif atom.kind in (AtomKind.VAR_CLOSE, AtomKind.PAREN_CLOSE):
                if stack:
                    history, source = stack.pop()
                else:
                    issues.append("unbalanced_variation")
                last_played = None
            elif atom.kind == AtomKind.ALT_DEST:
                if detached or last_played is None:
                    moves.append(MoveAnalysis(atom, MoveStatus.NO_CONTEXT, ContextSource.UNKNOWN,
                                              warnings=["alternative_destination"]))
                    continue
                before, played = last_played
                cands = _alt_destination(before, played, atom)
                base = MoveAnalysis(atom, MoveStatus.ILLEGAL, source, before.fen(), warnings=["alternative_destination"])
                if len(cands) == 1:
                    base.status, base.uci, base.canonical_san = MoveStatus.VALIDATED, cands[0].uci(), before.san(cands[0])
                elif cands:
                    base.status, base.interpretations = MoveStatus.AMBIGUOUS, [m.uci() for m in cands]
                moves.append(base)
            elif atom.kind == AtomKind.MOVE_NUMBER and history and not detached:
                side = chess.BLACK if atom.black else chess.WHITE
                cur = history[-1]
                if cur.fullmove_number == atom.number and cur.turn == side:
                    continue
                if not ctx.fullmove_known and len(history) == 1 and not moves and cur.turn == side:
                    # Um diagrama não informa o número do lance: o texto informa.
                    cur.fullmove_number = atom.number
                    pending_warning.append("fullmove_number_from_text")
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
                    last_played = None
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
                    last_played = (board, move)
        if segment.main and start_depth == 0 and has_notation:
            # Se o segmento terminou dentro de um parêntese, a linha principal é
            # a que estava em vigor quando o primeiro parêntese foi aberto.
            main_history, main_source = (stack[0] if stack else (history, source))
    if main_mask is not None and not stack:
        history, source = main_history, main_source
    # Uma posição presumida continua presumida nas regiões seguintes.
    keep = (ContextSource.STANDARD_HYPOTHESIS, ContextSource.FEN_PROPOSED)
    end_source = source if source in keep else ContextSource.CONTINUATION
    # Uma região sem lances (só prosa) não consome o frescor nem a numeração
    # desconhecida do diagrama: o próximo parágrafo ainda parte dele.
    untouched = not moves and len(history) == 1 and ctx.board is not None and history[0].fen() == ctx.board.fen()
    end = (
        Context(history[-1].copy(), end_source if not untouched else ctx.source,
                fresh=ctx.fresh if untouched else False,
                fullmove_known=ctx.fullmove_known if untouched else True)
        if history else Context.unknown()
    )
    if stack:
        issues.append("unclosed_variation")
    return RegionAnalysis(lexed=lexed, moves=moves, issues=issues, end_context=end)

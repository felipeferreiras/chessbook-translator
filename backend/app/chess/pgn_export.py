"""Exportação em PGN: uma partida por diagrama, com a linha principal validada.

A linha vem da própria validação (``Context.line`` do último parágrafo antes do
diagrama seguinte): só entram lances confirmados pelas regras. Nada é
inventado; quando a validação perdeu a posição no meio, a partida termina ali
e um comentário diz isso. A posição inicial é a do diagrama, ainda proposta
(lida da fonte), e o cabeçalho registra a página e o rótulo.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

import chess
import chess.pgn

from app.pipeline.notation_pass import Diagram, DocumentNotation


@dataclass
class ExportedGame:
    diagram: Diagram
    game: chess.pgn.Game
    plies: int
    complete: bool  # False: a validação perdeu a posição antes do próximo diagrama


def _move_between(before: chess.Board, after: chess.Board) -> chess.Move | None:
    target = (after.board_fen(), after.turn, after.castling_rights, after.ep_square)
    for move in before.legal_moves:
        trial = before.copy(stack=False)
        trial.push(move)
        if (trial.board_fen(), trial.turn, trial.castling_rights, trial.ep_square) == target:
            return move
    return None


def export_games(notation: DocumentNotation, title: str = "") -> list[ExportedGame]:
    """Partidas a partir de ``notation`` já validada (``validate``)."""
    events: list[tuple[tuple, str, object]] = []
    for r in notation.regions:
        if r.role == "text" and r.analysis is not None:
            events.append(((r.page, r.column, (r.bbox[1] + r.bbox[3]) / 2, 1), "region", r))
    for d in notation.diagrams:
        events.append(((d.page, 0 if d.bbox[0] < 255 else 1, (d.bbox[1] + d.bbox[3]) / 2, 0), "diagram", d))
    events.sort(key=lambda e: e[0])

    out: list[ExportedGame] = []
    current: Diagram | None = None
    line: tuple[chess.Board, ...] = ()
    lost = False

    def flush() -> None:
        if current is None or current.fen is None:
            return
        game = chess.pgn.Game()
        game.headers["Event"] = title or "?"
        game.headers["Site"] = f"p. {current.page}"
        game.headers["Round"] = current.label or "?"
        game.headers["Annotator"] = "chessbook-translator (posição do diagrama proposta; lances validados)"
        board = chess.Board(current.fen)
        game.setup(board)
        node: chess.pgn.GameNode = game
        plies = 0
        start = line[0] if line and line[0].board_fen() == board.board_fen() else None
        if start is not None:
            for before, after in pairwise(line):
                move = _move_between(before, after)
                if move is None:
                    break
                node = node.add_variation(move)
                plies += 1
        if lost:
            node.comment = "a validação perdeu a posição aqui; os lances seguintes do livro não entram"
        out.append(ExportedGame(current, game, plies, complete=not lost))

    for _, kind, item in events:
        if kind == "diagram":
            flush()
            current, line, lost = item, (), False  # type: ignore[assignment]
            continue
        analysis = item.analysis  # type: ignore[union-attr]
        if current is None:
            continue
        if analysis.end_context.line:
            line = analysis.end_context.line
        elif analysis.moves:
            lost = True
    flush()
    return out

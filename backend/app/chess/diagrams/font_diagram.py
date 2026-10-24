"""Leitura de diagramas compostos com fontes de diagrama (tabuleiro como texto).

Muitos livros desenham o tabuleiro com uma fonte em que cada caractere é uma
casa: vazia ou com uma peça, já na cor da casa. Isso permite ler a posição
sem visão computacional, mas a leitura continua sendo uma **proposta**:

* a cor de cada glifo precisa coincidir com a cor real da casa (a1 escura);
  qualquer divergência reprova a leitura;
* a posição precisa ter exatamente um rei de cada cor e nenhum peão na
  primeira ou na oitava fileira;
* a orientação (brancas embaixo) é presumida e registrada como tal, porque a
  paridade de cores não distingue um tabuleiro girado 180°;
* direitos de roque e en passant não aparecem no diagrama e ficam vazios,
  com aviso quando reis e torres estão nas casas iniciais.

A confirmação final vem da validação dos lances que seguem o diagrama e da
revisão humana.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import chess

from app.extraction.font_profiles import (
    LINARES_DIAGRAM_FRAME,
    LINARES_DIAGRAM_MARKS,
    LINARES_DIAGRAM_SQUARES,
)

RANK_LINE = re.compile(r"^\{(.{8})\}$")  # uma fileira: {8 casas}
MAX_PIECE_COLOR_DEFECTS = 2


@dataclass
class DiagramReading:
    placement: str | None  # campo de posição da FEN
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    marked_squares: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.placement is not None and not self.issues

    def fen(self, white_to_move: bool) -> str | None:
        if not self.ok:
            return None
        return f"{self.placement} {'w' if white_to_move else 'b'} - - 0 1"


def read_font_diagram(lines: list[str]) -> DiagramReading:
    """Lê as linhas de um diagrama Linares (moldura + 8 fileiras + moldura)."""
    ranks = [m.group(1) for line in lines if (m := RANK_LINE.match(line.strip()))]
    others = [line.strip() for line in lines if not RANK_LINE.match(line.strip()) and line.strip()]
    reading = DiagramReading(placement=None)
    if len(ranks) != 8:
        reading.issues.append(f"esperadas 8 fileiras, encontradas {len(ranks)}")
        return reading
    for line in others:
        if set(line) - LINARES_DIAGRAM_FRAME:
            reading.issues.append(f"linha de moldura com caracteres inesperados: {line!r}")
    board = chess.Board(None)
    mismatches: list[tuple[str, str, str, str, bool]] = []
    for row, rank_text in enumerate(ranks):
        rank = 7 - row  # primeira linha = oitava fileira (brancas embaixo)
        for file, ch in enumerate(rank_text):
            square = chess.square(file, rank)
            expected = "dark" if (file + rank) % 2 == 0 else "light"
            if ch in LINARES_DIAGRAM_SQUARES:
                symbol, color = LINARES_DIAGRAM_SQUARES[ch]
            elif ch in LINARES_DIAGRAM_MARKS:
                symbol, color = "", LINARES_DIAGRAM_MARKS[ch]
                reading.marked_squares.append(chess.square_name(square))
            else:
                reading.issues.append(f"glifo desconhecido {ch!r} em {chess.square_name(square)}")
                continue
            if color != expected:
                mismatches.append((chess.square_name(square), ch, color, expected, bool(symbol)))
            if symbol:
                board.set_piece_at(square, chess.Piece.from_symbol(symbol))
    # Uma ou duas peças com o fundo de casa trocado são defeito de composição
    # do original (a peça em si é inequívoca). Casas vazias com cor trocada,
    # ou muitas divergências, indicam leitura deslocada: a leitura é reprovada.
    if mismatches and (len(mismatches) > MAX_PIECE_COLOR_DEFECTS or not all(m[4] for m in mismatches)):
        reading.issues.extend(
            f"cor do glifo {ch!r} ({c}) não confere com {sq} ({e})" for sq, ch, c, e, _ in mismatches
        )
    else:
        reading.notes.extend(
            f"defeito tipográfico no original: peça em {sq} composta com fundo de casa {c}"
            for sq, _, c, _, _ in mismatches
        )
    if reading.issues:
        return reading
    for color, name in ((chess.WHITE, "brancas"), (chess.BLACK, "pretas")):
        kings = len(board.pieces(chess.KING, color))
        if kings != 1:
            reading.issues.append(f"{kings} rei(s) das {name}")
    pawns = board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK)
    if any(chess.square_rank(sq) in (0, 7) for sq in pawns):
        reading.issues.append("peão na primeira ou na oitava fileira")
    if reading.issues:
        return reading
    reading.placement = board.board_fen()
    reading.notes.append("orientação presumida: brancas embaixo")
    initial = [
        (chess.E1, chess.H1, chess.WHITE), (chess.E1, chess.A1, chess.WHITE),
        (chess.E8, chess.H8, chess.BLACK), (chess.E8, chess.A8, chess.BLACK),
    ]
    if any(
        board.piece_at(k) == chess.Piece(chess.KING, c) and board.piece_at(r) == chess.Piece(chess.ROOK, c)
        for k, r, c in initial
    ):
        reading.notes.append("rei e torre nas casas iniciais: direitos de roque desconhecidos (assumidos ausentes)")
    return reading


_SIDE_LABEL = re.compile(r"^\s*([WB])\s*([?!]*)\s*$")


def side_from_label(text: str) -> tuple[bool | None, bool]:
    """Interpreta rótulos como "W", "B", "W?" ao lado do diagrama.

    Devolve (brancas jogam?, é exercício?). ``None`` se o rótulo não for
    reconhecido: nesse caso a vez de jogar não é presumida.
    """
    m = _SIDE_LABEL.match(text)
    if not m:
        return None, False
    return m.group(1) == "W", "?" in m.group(2)

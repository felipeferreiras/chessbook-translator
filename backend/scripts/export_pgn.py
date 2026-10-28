"""Exporta o livro em PGN: uma partida por diagrama, só com lances validados.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.export_pgn LIVRO.pdf SAÍDA.pgn

A saída fica fora do repositório (é conteúdo do livro).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

from app.chess.pgn_export import export_games
from app.pipeline.notation_pass import collect, validate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    doc = pymupdf.open(args.pdf)
    notation = collect(doc)
    validate(notation)
    games = export_games(notation, title=doc.metadata.get("title", "") or args.pdf.stem)
    with args.out.open("w", encoding="utf-8") as fh:
        for g in games:
            print(g.game, file=fh, end="\n\n")
    with_moves = [g for g in games if g.plies]
    print(f"diagramas com posição: {len(games)}; com lances: {len(with_moves)}; "
          f"meios-lances: {sum(g.plies for g in games)}; "
          f"perderam a posição antes do diagrama seguinte: {sum(not g.complete for g in games)}")


if __name__ == "__main__":
    main()

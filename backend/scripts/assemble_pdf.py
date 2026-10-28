"""Monta o PDF traduzido a partir do original e do resultado de ``translate_pages``.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.assemble_pdf LIVRO.pdf TRADUÇÃO_DIR SAÍDA_DIR [--pages 1-40]
        [--cache DIR] [--progress ARQUIVO.json] [--stop ARQUIVO]

``TRADUÇÃO_DIR`` é o diretório gerado por ``translate_pages`` (com
``resultado.json``). O original não é alterado: as páginas são copiadas para
um documento novo. Saídas (fora do repositório): ``traduzido.pdf``,
``relatorio.json``, ``pages.txt`` e imagens lado a lado em ``paginas/``.

As partes de 20 páginas ficam em ``--cache`` (padrão ``SAÍDA_DIR/partes``):
rodar de novo só remonta as partes cujo texto ou código mudou
(``app.layout.assemble``). ``--progress`` grava o andamento em JSON;
``--stop`` interrompe entre partes quando o arquivo aparece.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.layout.assemble import AssemblyStopped, assemble
from app.pipeline.segments import parse_pages


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("translation", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--pages", help="só estas páginas do resultado (ex.: 1-40)")
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--progress", type=Path)
    ap.add_argument("--stop", type=Path)
    ap.add_argument("--ocr-cache", type=Path, help="OCR guardado das páginas digitalizadas (ocr.json do projeto)")
    args = ap.parse_args()

    data = json.loads((args.translation / "resultado.json").read_text(encoding="utf-8"))
    pages = data["summary"]["pages"]
    if args.pages:
        wanted = parse_pages(args.pages, max(pages))
        pages = [p for p in pages if p in wanted]

    def progress(state: dict) -> None:
        if args.progress:
            tmp = args.progress.with_name(args.progress.name + ".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            os.replace(tmp, args.progress)

    try:
        summary = assemble(args.pdf, data, args.out, pages, args.cache, progress,
                           (lambda: args.stop.exists()) if args.stop else None, ocr_cache=args.ocr_cache)
    except AssemblyStopped as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(3) from exc
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

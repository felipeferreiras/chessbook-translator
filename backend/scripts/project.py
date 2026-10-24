"""Projetos de tradução (SQLite) pela linha de comando.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.project create ID "Nome" LIVRO.pdf
    .venv/bin/python -m scripts.project import ID TRADUÇÃO_DIR      # resultado.json de translate_pages
    .venv/bin/python -m scripts.project export ID SAÍDA_DIR          # resultado.json para assemble_pdf
    .venv/bin/python -m scripts.project assemble ID                  # PDF traduzido em <projeto>/output/
    .venv/bin/python -m scripts.project status ID

Os projetos ficam em ``$CHESSBOOK_STORAGE`` (padrão: ``storage/`` na raiz do
repositório, fora do controle de versão): contêm o livro e a tradução.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pymupdf

from app.pipeline.notation_pass import collect
from app.pipeline.segments import book_segments
from app.store.project_store import ProjectStore

ROOT = Path(__file__).resolve().parents[2]


def storage_root() -> Path:
    return Path(os.environ.get("CHESSBOOK_STORAGE", ROOT / "storage"))


def style_masks(pdf: Path, pages: set[int]):
    """Negrito e itálico por segmento, com os mesmos ids de ``translate_pages``."""
    notation = collect(pymupdf.open(pdf))
    segs = book_segments(notation, pages=pages)
    return notation, {b.id: b.region.main_mask for b in segs}, {b.id: b.region.italic_mask for b in segs}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("id")
    c.add_argument("name")
    c.add_argument("pdf", type=Path)
    i = sub.add_parser("import")
    i.add_argument("id")
    i.add_argument("translation", type=Path)
    e = sub.add_parser("export")
    e.add_argument("id")
    e.add_argument("out", type=Path)
    a = sub.add_parser("assemble")
    a.add_argument("id")
    s = sub.add_parser("status")
    s.add_argument("id")
    args = ap.parse_args()
    root = storage_root()

    if args.cmd == "create":
        doc = pymupdf.open(args.pdf)
        notation = collect(doc)
        store = ProjectStore.create(root, args.id, args.name, args.pdf, doc.page_count, notation.style)
        segs = book_segments(notation, doc.metadata.get("title", "") or args.name)
        store.add_book_segments([{"id": b.id, "page": b.page, "section": b.section.label,
                                  "source": b.region.resolved.text, "kind": b.kind,
                                  "bold": b.region.main_mask, "italic": b.region.italic_mask,
                                  "blocked": b.blocked} for b in segs])
        print(f"projeto criado em {store.dir} (sha256 {store.info['sha256'][:12]}…): {len(segs)} segmentos")
        return
    store = ProjectStore(root, args.id)
    if not store.verify_original():
        raise SystemExit("o original do projeto não confere com o sha256 registrado")
    if args.cmd == "import":
        result = json.loads((args.translation / "resultado.json").read_text(encoding="utf-8"))
        _, bold, italic = style_masks(store.original_path, set(result["summary"]["pages"]))
        print(f"{store.import_translation(result, bold, italic)} segmentos importados")
    elif args.cmd == "export":
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "resultado.json").write_text(json.dumps(store.export_result(), ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
        print(f"exportado para {args.out / 'resultado.json'}")
    elif args.cmd == "assemble":
        export = store.dir / "output" / "export"
        export.mkdir(parents=True, exist_ok=True)
        result = store.export_result()
        (export / "resultado.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        subprocess.run([sys.executable, "-m", "scripts.assemble_pdf", str(store.original_path), str(export),
                        str(store.dir / "output")], check=True, cwd=Path(__file__).resolve().parents[1])
        (store.dir / "output" / "pages.txt").write_text(" ".join(map(str, result["summary"]["pages"])))
        print(f"PDF traduzido em {store.dir / 'output' / 'traduzido.pdf'}")
    elif args.cmd == "status":
        segs = store.segments()
        kinds = Counter(s.current.kind if s.current else s.status for s in segs)
        print(json.dumps({"segmentos": len(segs), "por_estado": dict(kinds),
                          "aprovados": sum(s.approved for s in segs),
                          "precisam_de_atencao": [s.id for s in segs if s.needs_attention]},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

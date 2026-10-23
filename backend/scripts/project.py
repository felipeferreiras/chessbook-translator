"""Projetos de tradução (SQLite) pela linha de comando.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.project create ID "Nome" LIVRO.pdf
    .venv/bin/python -m scripts.project import ID TRADUÇÃO_DIR      # resultado.json de translate_pages
    .venv/bin/python -m scripts.project export ID SAÍDA_DIR          # resultado.json para assemble_pdf
    .venv/bin/python -m scripts.project status ID

Os projetos ficam em ``$CHESSBOOK_STORAGE`` (padrão: ``storage/`` na raiz do
repositório, fora do controle de versão): contêm o livro e a tradução.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

import pymupdf

from app.pipeline.notation_pass import collect
from app.store.project_store import ProjectStore

ROOT = Path(__file__).resolve().parents[2]


def storage_root() -> Path:
    return Path(os.environ.get("CHESSBOOK_STORAGE", ROOT / "storage"))


def style_masks(pdf: Path, pages: set[int]):
    """Negrito e itálico por segmento, com os mesmos ids de ``translate_pages``."""
    notation = collect(pymupdf.open(pdf))
    regions = [r for r in notation.regions if r.page in pages and r.role == "text"]
    ids = [f"p{r.page}-{i}" for i, r in enumerate(regions)]
    return notation, {i: r.main_mask for i, r in zip(ids, regions, strict=True)}, \
        {i: r.italic_mask for i, r in zip(ids, regions, strict=True)}


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
    s = sub.add_parser("status")
    s.add_argument("id")
    args = ap.parse_args()
    root = storage_root()

    if args.cmd == "create":
        doc = pymupdf.open(args.pdf)
        notation = collect(doc)
        store = ProjectStore.create(root, args.id, args.name, args.pdf, doc.page_count, notation.style)
        print(f"projeto criado em {store.dir} (sha256 {store.info['sha256'][:12]}…)")
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
    elif args.cmd == "status":
        segs = store.segments()
        kinds = Counter(s.current.kind if s.current else s.status for s in segs)
        print(json.dumps({"segmentos": len(segs), "por_estado": dict(kinds),
                          "aprovados": sum(s.approved for s in segs),
                          "precisam_de_atencao": [s.id for s in segs if s.needs_attention]},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

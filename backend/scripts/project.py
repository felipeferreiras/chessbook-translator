"""Projetos de tradução (SQLite) pela linha de comando.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.project create ID "Nome" LIVRO.pdf
    .venv/bin/python -m scripts.project import ID TRADUÇÃO_DIR      # resultado.json de translate_pages
    .venv/bin/python -m scripts.project export ID SAÍDA_DIR          # resultado.json para assemble_pdf
    .venv/bin/python -m scripts.project assemble ID                  # PDF traduzido em <projeto>/output/
    .venv/bin/python -m scripts.project status ID
    .venv/bin/python -m scripts.project sync ID                      # depois de atualizar o código

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

from app.extraction.ocr import scanned_pages
from app.pipeline.notation_pass import collect
from app.pipeline.segments import book_segments
from app.store import assembly
from app.store.project_store import ProjectStore

ROOT = Path(__file__).resolve().parents[2]


def storage_root() -> Path:
    return Path(os.environ.get("CHESSBOOK_STORAGE", ROOT / "storage"))


def style_masks(pdf: Path, pages: set[int], ocr_cache: Path | None = None):
    """Negrito e itálico por segmento, com os mesmos ids de ``translate_pages``."""
    notation = collect(pymupdf.open(pdf), ocr_cache=ocr_cache,
                       ocr_mode="on" if ocr_cache is not None and ocr_cache.exists() else "off")
    segs = book_segments(notation, pages=pages)
    return notation, {b.id: b.region.main_mask for b in segs}, {b.id: b.region.italic_mask for b in segs}


def segment_dicts(segs) -> list[dict]:
    return [{"id": b.id, "page": b.page, "section": b.section.label, "source": b.region.resolved.text,
             "kind": b.kind, "bold": b.region.main_mask, "italic": b.region.italic_mask, "blocked": b.blocked,
             "flags": b.flags} for b in segs]


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("id")
    c.add_argument("name")
    c.add_argument("pdf", type=Path)
    c.add_argument("--ocr", choices=("auto", "on", "off"), default="auto",
                   help="páginas só de imagem: auto = OCR se a maioria do livro for digitalizada")
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
    y = sub.add_parser("sync", help="alinha o projeto com a extração do código atual, sem perder traduções")
    y.add_argument("id")
    args = ap.parse_args()
    root = storage_root()

    if args.cmd == "create":
        doc = pymupdf.open(args.pdf)
        # páginas digitalizadas: o OCR fica guardado no projeto, e a montagem relê exatamente o mesmo texto
        ocr_tmp = root / f".{args.id}-ocr.json"
        notation = collect(doc, ocr_cache=ocr_tmp, ocr_mode=args.ocr,
                           progress=lambda stage, i, n: print(f"\r{stage}: {i}/{n} páginas", end="", flush=True))
        images = scanned_pages(doc)
        if images and not ocr_tmp.exists():
            print(f"páginas só de imagem não lidas por OCR (capa, fotos?): {images[:20]} — use --ocr on para ler")
        store = ProjectStore.create(root, args.id, args.name, args.pdf, doc.page_count, notation.style)
        if ocr_tmp.exists():
            ocr_tmp.replace(store.dir / "ocr.json")
            print()
        segs = book_segments(notation, doc.metadata.get("title", "") or args.name)
        store.add_book_segments(segment_dicts(segs))
        print(f"projeto criado em {store.dir} (sha256 {store.info['sha256'][:12]}…): {len(segs)} segmentos")
        return
    store = ProjectStore(root, args.id)
    if not store.verify_original():
        raise SystemExit("o original do projeto não confere com o sha256 registrado")
    if args.cmd == "import":
        result = json.loads((args.translation / "resultado.json").read_text(encoding="utf-8"))
        _, bold, italic = style_masks(store.original_path, set(result["summary"]["pages"]), store.dir / "ocr.json")
        print(f"{store.import_translation(result, bold, italic)} segmentos importados")
    elif args.cmd == "export":
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "resultado.json").write_text(json.dumps(store.export_result(), ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
        print(f"exportado para {args.out / 'resultado.json'}")
    elif args.cmd == "assemble":  # o mesmo caminho da interface: partes prontas são reaproveitadas
        done = assembly.start(store, os.environ.get("USER", "linha de comando"), wait=True)
        if done.state != "done":
            raise SystemExit(f"montagem {done.state}: {done.error} (ver {store.dir / 'output' / 'montagem.log'})")
        print(json.dumps(done.summary, ensure_ascii=False))
        print(f"PDF traduzido em {store.dir / 'output' / 'traduzido.pdf'}")
    elif args.cmd == "sync":
        ocr_cache = store.dir / "ocr.json"
        doc = pymupdf.open(store.original_path)
        notation = collect(doc, ocr_cache=ocr_cache, ocr_mode="on" if ocr_cache.exists() else "off")
        segs = book_segments(notation, doc.metadata.get("title", "") or store.info["name"])
        print(json.dumps(store.sync_segments(segment_dicts(segs), os.environ.get("USER", "linha de comando")),
                         ensure_ascii=False))
    elif args.cmd == "status":
        segs = store.segments()
        kinds = Counter(s.current.kind if s.current else s.status for s in segs)
        print(json.dumps({"segmentos": len(segs), "por_estado": dict(kinds),
                          "aprovados": sum(s.approved for s in segs),
                          "precisam_de_atencao": [s.id for s in segs if s.needs_attention]},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

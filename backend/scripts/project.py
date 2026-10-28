"""Projetos de tradução (SQLite) pela linha de comando.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.project create ID "Nome" LIVRO.pdf
    .venv/bin/python -m scripts.project import ID TRADUÇÃO_DIR      # resultado.json de translate_pages
    .venv/bin/python -m scripts.project export ID SAÍDA_DIR          # resultado.json para assemble_pdf
    .venv/bin/python -m scripts.project assemble ID                  # PDF traduzido em <projeto>/output/
    .venv/bin/python -m scripts.project status ID
    .venv/bin/python -m scripts.project sync ID                      # depois de atualizar o código
    .venv/bin/python -m scripts.project figurines ID [--labels '{"3": "♕"}']  # figurinas do livro (OCR)
    .venv/bin/python -m scripts.project symbols ID [--labels '{"7": "?"}']    # símbolos do livro (OCR)
    .venv/bin/python -m scripts.project pieces ID [--labels '{"4": "q"}']     # peças dos diagramas (OCR)
    .venv/bin/python -m scripts.project audit ID                     # integridade do livro inteiro
    .venv/bin/python -m scripts.project backup ID [--dest PASTA]     # .zip com manifesto e sha256
    .venv/bin/python -m scripts.project restore ARQUIVO.zip [--como NOVO_ID]

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

from app.extraction.ocr import reread_with_figurines, scanned_pages
from app.pipeline.notation_pass import collect
from app.pipeline.segments import book_segments
from app.store import assembly
from app.store.audit import audit
from app.store.backup import create_backup, restore_backup
from app.store.project_store import ProjectStore
from app.translation.config import load_env_file

ROOT = Path(__file__).resolve().parents[2]


def storage_root() -> Path:
    return Path(os.environ.get("CHESSBOOK_STORAGE") or ROOT / "storage")


def style_masks(pdf: Path, pages: set[int], ocr_cache: Path | None = None):
    """Negrito e itálico por segmento, com os mesmos ids de ``translate_pages``."""
    notation = collect(pymupdf.open(pdf), ocr_cache=ocr_cache,
                       ocr_mode="on" if ocr_cache is not None and ocr_cache.exists() else "off")
    segs = book_segments(notation, pages=pages)
    return notation, {b.id: b.region.main_mask for b in segs}, {b.id: b.region.italic_mask for b in segs}


def check_moves(notation) -> None:
    """Livro digitalizado: confere os lances pelas posições dos diagramas (os avisos vão nos parágrafos)."""
    from app.pipeline.notation_pass import OCR_FLAG, validate

    if any(OCR_FLAG in r.source_flags for r in notation.regions):
        validate(notation)


def segment_dicts(segs) -> list[dict]:
    return [{"id": b.id, "page": b.page, "section": b.section.label, "source": b.region.resolved.text,
             "kind": b.kind, "bold": b.region.main_mask, "italic": b.region.italic_mask, "blocked": b.blocked,
             "flags": b.flags} for b in segs]


def progress_writer(path: Path | None):
    """Andamento no terminal e, se ``path``, em JSON (lido pela interface)."""
    def progress(stage: str, i: int = 0, n: int = 0) -> None:
        print(f"\r{stage}: {i}/{n} páginas", end="", flush=True)
        if path:
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps({"stage": stage, "done": i, "total": n}), encoding="utf-8")
            os.replace(tmp, path)
    return progress


def sync_project(store: ProjectStore, author: str, progress=None) -> dict:
    """Alinha o projeto com a extração do código atual (num livro digitalizado, refaz o OCR se mudou)."""
    ocr_cache = store.dir / "ocr.json"
    doc = pymupdf.open(store.original_path)
    notation = collect(doc, ocr_cache=ocr_cache, ocr_mode="on" if ocr_cache.exists() else "off", progress=progress)
    if progress:
        progress("conferindo os lances", doc.page_count, doc.page_count)
    check_moves(notation)
    segs = book_segments(notation, doc.metadata.get("title", "") or store.info["name"])
    return store.sync_segments(segment_dicts(segs), author)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("id")
    c.add_argument("name")
    c.add_argument("pdf", type=Path)
    c.add_argument("--ocr", choices=("auto", "on", "off"), default="auto",
                   help="páginas só de imagem: auto = OCR se a maioria do livro for digitalizada")
    c.add_argument("--progress", type=Path, help="andamento em JSON (usado pela interface)")
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
    f = sub.add_parser("figurines", help="figurinas achadas pelo OCR; com --labels, relê o livro com elas")
    f.add_argument("id")
    f.add_argument("--labels", help='JSON {grupo: figurina}; "" = não é peça. Grupos omitidos: a sugestão')
    sy = sub.add_parser("symbols", help="símbolos depois dos lances (†, ±, ?!…); com --labels, reescreve os lances")
    sy.add_argument("id")
    sy.add_argument("--labels", help='JSON {grupo: símbolo}; "" = não é símbolo')
    pc = sub.add_parser("pieces", help="peças dos diagramas digitalizados; com --labels, refaz as posições")
    pc.add_argument("id")
    pc.add_argument("--labels", help='JSON {grupo: letra FEN (KQRBNP brancas, kqrbnp pretas)}; "" = casa vazia')
    for q in (y, f, sy, pc):
        q.add_argument("--progress", type=Path, help="andamento em JSON (usado pela interface)")
        q.add_argument("--result", type=Path, help="resultado em JSON (usado pela interface)")
        q.add_argument("--author", default=os.environ.get("USER", "linha de comando"))
    u = sub.add_parser("audit", help="confere a integridade do livro inteiro (original, notação, montagem)")
    u.add_argument("id")
    k = sub.add_parser("backup", help="pacote .zip do projeto, com manifesto e sha256")
    k.add_argument("id")
    k.add_argument("--dest", type=Path, help="pasta de destino (padrão: <armazenamento>/backups)")
    k.add_argument("--sem-saida", action="store_true", help="sem o PDF traduzido e os relatórios")
    r = sub.add_parser("restore", help="restaura um backup (nunca sobrescreve)")
    r.add_argument("zip", type=Path)
    r.add_argument("--como", help="id do projeto restaurado (padrão: o original)")
    args = ap.parse_args()
    load_env_file(ROOT / ".env")  # CHESSBOOK_STORAGE e as demais configurações, como na interface
    root = storage_root()

    if args.cmd == "create":
        doc = pymupdf.open(args.pdf)
        # páginas digitalizadas: o OCR fica guardado no projeto, e a montagem relê exatamente o mesmo texto
        ocr_tmp = root / f".{args.id}-ocr.json"
        progress = progress_writer(args.progress)
        progress("extração", 0, doc.page_count)
        notation = collect(doc, ocr_cache=ocr_tmp, ocr_mode=args.ocr, progress=progress)
        progress("gravando o projeto", doc.page_count, doc.page_count)
        images = scanned_pages(doc)
        if images and not ocr_tmp.exists():
            print(f"páginas só de imagem não lidas por OCR (capa, fotos?): {images[:20]} — use --ocr on para ler")
        store = ProjectStore.create(root, args.id, args.name, args.pdf, doc.page_count, notation.style)
        if ocr_tmp.exists():
            ocr_tmp.replace(store.dir / "ocr.json")
            passe1 = root / f".{args.id}-ocr-passe1.json.gz"
            if passe1.exists():  # para reler com as figurinas confirmadas sem refazer o OCR
                passe1.replace(store.dir / "ocr-passe1.json.gz")
            print()
        check_moves(notation)
        segs = book_segments(notation, doc.metadata.get("title", "") or args.name)
        store.add_book_segments(segment_dicts(segs))
        print(f"projeto criado em {store.dir} (sha256 {store.info['sha256'][:12]}…): {len(segs)} segmentos")
        return
    if args.cmd == "restore":
        restored = restore_backup(args.zip, root, args.como)
        print(f"projeto {restored.id} restaurado em {restored.dir} (original e banco conferidos)")
        return
    store = ProjectStore(root, args.id)
    if args.cmd == "backup":  # mesmo com o original alterado: o backup é para salvar o que existe
        path = create_backup(store, args.dest or root / "backups", include_output=not args.sem_saida)
        print(f"backup em {path} ({path.stat().st_size / 1e6:.1f} MB)")
        return
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
    elif args.cmd in ("sync", "figurines", "symbols", "pieces"):
        progress = progress_writer(args.progress)
        reread = {}
        if args.cmd == "pieces":
            from app.extraction.ocr import relabel_pieces
            from app.store.reprocess import pieces_info

            if args.labels is None:
                info = pieces_info(store)
                if not info["available"]:
                    raise SystemExit(info["reason"])
                for g in info["groups"]:
                    label = info["labels"].get(str(g["id"]))
                    print(f"grupo {g['id']:>4}: {g['count']:>5} · {'preta' if g['black'] else 'branca'} · "
                          f"sugestão {g['auto'] or '-'}" + (f" · confirmado {label!r}" if label is not None else ""))
                return
            reread = relabel_pieces(store.dir / "ocr.json", json.loads(args.labels))
            print(f"posições: {reread}")
        if args.cmd == "symbols":
            from app.extraction.ocr import relabel_symbols
            from app.store.reprocess import symbols_info

            if args.labels is None:
                info = symbols_info(store)
                if not info["available"]:
                    raise SystemExit(info["reason"])
                for g in info["groups"]:
                    label = info["labels"].get(str(g["id"]))
                    print(f"grupo {g['id']:>4}: {g['count']:>5} · OCR leu {' '.join(g['read']) or '?'} · "
                          f"sugestão {g['auto'] or '-'}" + (f" · confirmado {label!r}" if label is not None else ""))
                return
            reread = relabel_symbols(store.dir / "ocr.json", json.loads(args.labels))
            print(f"lances reescritos: {reread}")
        if args.cmd == "figurines":
            from app.store.reprocess import figurines

            if args.labels is None:  # só mostra os grupos
                info = figurines(store)
                if not info["available"]:
                    raise SystemExit(info["reason"])
                for g in info["groups"]:
                    label = info["labels"].get(str(g["id"]))
                    print(f"grupo {g['id']:>4}: {g['count']:>4} lances · OCR leu {''.join(g['ocr']) or '?'} · "
                          f"sugestão {g['auto'] or '-'} (margem {g['margin']})"
                          + (f" · confirmado {label or 'não é peça'}" if label is not None else ""))
                return
            if not (store.dir / "ocr.json").exists():
                raise SystemExit("o livro não foi lido por OCR")
            labels = {int(k): v for k, v in json.loads(args.labels).items()}
            reread = reread_with_figurines(pymupdf.open(store.original_path), store.dir / "ocr.json", labels,
                                           progress=progress)
            print(f"\nrelido: {reread}")
        out = sync_project(store, args.author, progress)
        out = {**out, **{f"ocr_{k}": v for k, v in reread.items()}}
        print("\n" + json.dumps(out, ensure_ascii=False))
        if args.result:
            args.result.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    elif args.cmd == "audit":
        report = audit(store)
        print(json.dumps({k: report[k] for k in ("ok", "complete", "original_ok")}, ensure_ascii=False))
        print(json.dumps({"extração": report["extraction"], "segmentos": {k: v for k, v in report["segments"].items()
                                                                         if k != "unfinished"},
                          "montagem": report["assembly"]}, ensure_ascii=False, indent=1))
    elif args.cmd == "status":
        segs = store.segments()
        kinds = Counter(s.current.kind if s.current else s.status for s in segs)
        print(json.dumps({"segmentos": len(segs), "por_estado": dict(kinds),
                          "aprovados": sum(s.approved for s in segs),
                          "precisam_de_atencao": [s.id for s in segs if s.needs_attention]},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

"""Monta o PDF traduzido a partir do original e do resultado de ``translate_pages``.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.assemble_pdf LIVRO.pdf TRADUÇÃO_DIR SAÍDA_DIR

``TRADUÇÃO_DIR`` é o diretório gerado por ``translate_pages`` (com
``resultado.json``). O original não é alterado: as páginas são copiadas para
um documento novo. Saídas (fora do repositório): ``traduzido.pdf``,
``relatorio.json`` e imagens lado a lado em ``paginas/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path

import pymupdf
from PIL import Image

from app.layout.compose import BlockJob, compose_page, verify_text
from app.pipeline.notation_pass import collect
from app.pipeline.segments import book_segments, parse_pages
from app.translation.guard import protect, restore

CHUNK_PAGES = 20
ACCEPTED = {"translated", "cached", "reviewed"}  # reviewed: editado no projeto


def _runs(mask: list[bool], offset: int) -> list[tuple[int, int]]:
    """Trechos contíguos marcados de ``mask``, deslocados por ``offset``."""
    out: list[tuple[int, int]] = []
    for i, on in enumerate(mask):
        if on and out and out[-1][1] == offset + i:
            out[-1] = (out[-1][0], offset + i + 1)
        elif on:
            out.append((offset + i, offset + i + 1))
    return out


def side_by_side(original: pymupdf.Page, translated: pymupdf.Page, path: Path, dpi: int = 80) -> None:
    a = original.get_pixmap(dpi=dpi)
    b = translated.get_pixmap(dpi=dpi)
    ia = Image.frombytes("RGB", (a.width, a.height), a.samples)
    ib = Image.frombytes("RGB", (b.width, b.height), b.samples)
    canvas = Image.new("RGB", (ia.width + ib.width + 12, max(ia.height, ib.height)), "white")
    canvas.paste(ia, (0, 0))
    canvas.paste(ib, (ia.width + 12, 0))
    canvas.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("translation", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--pages", help="só estas páginas do resultado (ex.: 1-40)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "paginas").mkdir(exist_ok=True)

    data = json.loads((args.translation / "resultado.json").read_text(encoding="utf-8"))
    pages = data["summary"]["pages"]
    if args.pages:
        wanted = parse_pages(args.pages, max(pages))
        pages = [p for p in pages if p in wanted]
    by_id = {s["id"]: s for s in data["segments"]}

    source_bytes = args.pdf.read_bytes()
    sha_before = hashlib.sha256(source_bytes).hexdigest()
    original = pymupdf.open(stream=source_bytes, filetype="pdf")
    notation = collect(original)
    segs = book_segments(notation, pages=set(pages))
    regions = [b.region for b in segs]
    ids = [b.id for b in segs]
    mismatched = [i for i, r in zip(ids, regions, strict=True) if by_id.get(i, {}).get("source") != r.resolved.text]
    if mismatched:
        raise SystemExit(f"o resultado da tradução não corresponde ao texto extraído: {mismatched[:5]}")

    reports = []
    status_count: Counter[str] = Counter()

    def page_jobs(p: int) -> tuple[list[BlockJob], list[pymupdf.Rect], dict[str, list[str]]]:
        jobs: list[BlockJob] = []
        keep: list[pymupdf.Rect] = []
        slots: dict[str, list[str]] = {}
        for rid, region in zip(ids, regions, strict=True):
            if region.page != p or region.layout is None:
                continue
            seg = by_id[rid]
            status_count[seg["status"]] += 1
            if seg["status"] not in ACCEPTED or not seg["raw_translation"]:
                keep.append(pymupdf.Rect(region.layout.text_rect))
                continue
            prot = protect(region.resolved.text, notation.style, region.main_mask, region.italic_mask)
            restored = restore(seg["raw_translation"], prot)
            if restored.text != seg["text"]:
                raise SystemExit(f"{rid}: restauração diverge do resultado salvo")
            bold = [(a, b) for a, b, tag in restored.styles if tag == "b"]
            for start, end, key in restored.pieces:
                # Linha principal em negrito, variantes não: o trecho volta byte a
                # byte, então o negrito é copiado caractere a caractere do original.
                a, _ = prot.slot_ranges[key]
                bold.extend(_runs(region.main_mask[a:a + end - start], start))
            italic = [(a, b) for a, b, tag in restored.styles if tag == "i"]
            slots[rid] = list(prot.slots.values())
            jobs.append(BlockJob(rid, region.layout, region.column, restored.text, sorted(bold),
                                 tabular="\t" in region.resolved.text, italic_ranges=italic))
        return jobs, keep, slots

    # Em partes: cada bloco embute as fontes, e só ao salvar as cópias iguais viram
    # uma. Montar o livro inteiro de uma vez esgotava a memória (medido: 1,2 GB
    # para 40 páginas com fontes completas); em partes, o pico não cresce com o livro.
    chunk_files = []
    with tempfile.TemporaryDirectory(prefix="montagem-") as tmp:
        for c in range(0, len(pages), CHUNK_PAGES):
            chunk = pages[c:c + CHUNK_PAGES]
            out = pymupdf.open()
            for p in chunk:
                out.insert_pdf(original, from_page=p - 1, to_page=p - 1)
            for index, p in enumerate(chunk):
                page, orig_page = out[index], original[p - 1]
                jobs, keep, slots = page_jobs(p)
                boards = [pymupdf.Rect(d.bbox) for d in notation.diagrams if d.page == p]
                report = compose_page(page, orig_page, jobs, boards, keep, p)
                verify_text(page, report, jobs, slots)
                reports.append(report)
                side_by_side(orig_page, page, args.out / "paginas" / f"p{p:03d}.png")
            out.subset_fonts()
            path = Path(tmp) / f"parte-{c // CHUNK_PAGES:04d}.pdf"
            out.save(path, garbage=4, deflate=True)
            out.close()
            chunk_files.append(path)
        final = pymupdf.open()
        for path in chunk_files:
            with pymupdf.open(path) as part:
                final.insert_pdf(part)
        final.save(args.out / "traduzido.pdf", garbage=4, deflate=True)
        final.close()
    summary = {
        "source_sha256_before": sha_before,
        "source_sha256_after": hashlib.sha256(args.pdf.read_bytes()).hexdigest(),
        "pages": pages,
        "segments_by_status": dict(status_count),
        "blocks": sum(len(r.blocks) for r in reports),
        "blocks_placed": sum(b.placed for r in reports for b in r.blocks),
        "blocks_expanded": sum(b.expanded for r in reports for b in r.blocks),
        "blocks_reduced": sum(b.placed and b.scale < 1 for r in reports for b in r.blocks),
        "blocks_needing_review": [b.region_id for r in reports for b in r.blocks if b.needs_review],
        "missing_text": [x for r in reports for x in r.missing_text],
        "cut_text": [x for r in reports for x in r.cut_text],
        "missing_notation": [x for r in reports for x in r.missing_notation],
        "leftover_original": [x for r in reports for x in r.leftover_original],
        "overlaps": [x for r in reports for x in r.overlaps],
        "shading_removed": sum(r.shading_removed for r in reports),
        "diagrams_checked": sum(len(r.diagram_changed_pct) for r in reports),
        "diagrams_changed": [(r.page, pct) for r in reports for pct in r.diagram_changed_pct if pct > 0],
        "font_substitutions": sorted({s for r in reports for s in r.font_substitutions}),
        "pages_ok": [r.page for r in reports if r.ok],
    }
    detail = [{"page": r.page, "ok": r.ok, "blocks": [b.__dict__ for b in r.blocks], "missing_text": r.missing_text, "cut_text": r.cut_text,
               "missing_notation": r.missing_notation, "leftover_original": r.leftover_original, "overlaps": r.overlaps, "diagram_changed_pct": r.diagram_changed_pct,
               "font_substitutions": r.font_substitutions} for r in reports]
    (args.out / "relatorio.json").write_text(json.dumps({"summary": summary, "pages": detail}, ensure_ascii=False,
                                                        indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

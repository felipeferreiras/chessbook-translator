"""Montagem do PDF traduzido em partes de 20 páginas, com partes reaproveitadas.

Cada parte cobre um intervalo fixo de páginas do livro (1–20, 21–40, …) e é
guardada em ``cache_dir`` com uma chave que depende de tudo o que muda o seu
conteúdo: o original (sha256), as páginas, o texto atual de cada segmento
dessas páginas e o código da montagem. Assim:

* retomada: se a montagem for interrompida, as partes prontas não são refeitas;
* reprocessamento seletivo: depois de revisar uma página, só a parte dela é
  montada de novo; as outras vêm do cache com o relatório que tinham.

O original nunca é alterado (sha256 conferido antes e depois). As saídas são
gravadas em arquivos temporários e trocadas no fim, para que uma interrupção
nunca deixe um PDF pela metade no lugar do anterior.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import pymupdf
from PIL import Image

from app.layout.compose import BlockJob, BlockOutcome, PageReport, compose_page, verify_text
from app.pipeline.notation_pass import DocumentNotation, collect
from app.pipeline.segments import book_segments
from app.translation.guard import protect, restore

CHUNK_PAGES = 20
ACCEPTED = {"translated", "cached", "reviewed"}  # reviewed: editado no projeto
_CODE = ("layout/compose.py", "layout/assemble.py", "pipeline/notation_pass.py", "pipeline/segments.py",
         "translation/guard.py")


class AssemblyStopped(RuntimeError):
    """Interrompida a pedido (cancelamento): as partes prontas ficam no cache."""


def code_version() -> str:
    """Muda quando o código que decide o desenho da página muda: invalida as partes antigas."""
    root = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for rel in _CODE:
        h.update((root / rel).read_bytes())
    for font in sorted((root / "layout" / "fonts").glob("*.ttf")):
        h.update(font.name.encode())
    return h.hexdigest()[:16]


def content_hash(result: dict) -> str:
    """Impressão digital do texto que vai para a página: muda com qualquer tradução, edição ou reversão."""
    h = hashlib.sha256()
    for s in result["segments"]:
        h.update(json.dumps([s["id"], s["status"], s["text"], s.get("raw_translation")], ensure_ascii=False).encode())
    return h.hexdigest()


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


def _report_from(d: dict) -> PageReport:
    d = dict(d)
    d["blocks"] = [BlockOutcome(**{**b, "rect": tuple(b["rect"])}) for b in d["blocks"]]
    return PageReport(**d)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def assemble(pdf: Path, result: dict, out: Path, pages: list[int] | None = None, cache_dir: Path | None = None,
             progress: Callable[[dict], None] | None = None, should_stop: Callable[[], bool] | None = None,
             notation: DocumentNotation | None = None, ocr_cache: Path | None = None) -> dict:
    """Monta ``out/traduzido.pdf`` e ``out/relatorio.json``; devolve o resumo.

    ``result``: formato de ``resultado.json`` (``ProjectStore.export_result``).
    ``progress`` recebe {"pages_total", "pages_done", "chunks_total", "chunks_done", "chunks_reused"}.
    """
    out.mkdir(parents=True, exist_ok=True)
    (out / "paginas").mkdir(exist_ok=True)
    cache_dir = cache_dir or out / "partes"
    cache_dir.mkdir(parents=True, exist_ok=True)
    pages = sorted(pages if pages is not None else result["summary"]["pages"])
    by_id = {s["id"]: s for s in result["segments"]}

    source_bytes = pdf.read_bytes()
    sha_before = hashlib.sha256(source_bytes).hexdigest()
    original = pymupdf.open(stream=source_bytes, filetype="pdf")
    # OCR só se o projeto foi criado com ele (o ocr.json guarda a decisão e o texto lido)
    notation = notation or collect(original, ocr_cache=ocr_cache,
                                   ocr_mode="on" if ocr_cache is not None and ocr_cache.exists() else "off")
    segs = book_segments(notation, pages=set(pages))
    mismatched = [b.id for b in segs if by_id.get(b.id, {}).get("source") != b.region.resolved.text]
    if mismatched:
        raise ValueError(f"o resultado da tradução não corresponde ao texto extraído: {mismatched[:5]}")
    by_page: dict[int, list] = {}
    for b in segs:
        by_page.setdefault(b.region.page, []).append(b)

    chunks: dict[int, list[int]] = {}
    for p in pages:
        chunks.setdefault((p - 1) // CHUNK_PAGES, []).append(p)
    version = code_version()
    state = {"pages_total": len(pages), "pages_done": 0, "chunks_total": len(chunks), "chunks_done": 0,
             "chunks_reused": 0}
    if progress:
        progress(dict(state))

    def chunk_key(chunk: list[int]) -> str:
        h = hashlib.sha256()
        h.update(f"{version}|{sha_before}|{chunk}".encode())
        for p in chunk:
            for b in by_page.get(p, []):
                s = by_id[b.id]
                h.update(json.dumps([b.id, s["status"], s["text"], s["raw_translation"], s.get("source_text")],
                                    ensure_ascii=False).encode())
        return h.hexdigest()[:24]

    status_count: Counter[str] = Counter()

    def page_jobs(p: int) -> tuple[list[BlockJob], list[pymupdf.Rect], dict[str, list[str]]]:
        jobs: list[BlockJob] = []
        keep: list[pymupdf.Rect] = []
        slots: dict[str, list[str]] = {}
        for b in by_page.get(p, []):
            region = b.region
            if region.layout is None:
                continue
            seg = by_id[b.id]
            if seg["status"] not in ACCEPTED or not seg["raw_translation"]:
                keep.append(pymupdf.Rect(region.layout.text_rect))
                continue
            # original corrigido pelo usuário (OCR): a tradução foi feita sobre ele, sem negrito conhecido
            source = seg.get("source_text", region.resolved.text)
            main = region.main_mask if source == region.resolved.text else [False] * len(source)
            italic_mask = region.italic_mask if source == region.resolved.text else [False] * len(source)
            prot = protect(source, notation.style, main, italic_mask)
            restored = restore(seg["raw_translation"], prot)
            if restored.text != seg["text"]:
                raise ValueError(f"{b.id}: restauração diverge do resultado salvo")
            bold = [(x, y) for x, y, tag in restored.styles if tag == "b"]
            for start, end, key in restored.pieces:
                # Linha principal em negrito, variantes não: o trecho volta byte a
                # byte, então o negrito é copiado caractere a caractere do original.
                a, _ = prot.slot_ranges[key]
                bold.extend(_runs(main[a:a + end - start], start))
            italic = [(x, y) for x, y, tag in restored.styles if tag == "i"]
            slots[b.id] = list(prot.slots.values())
            jobs.append(BlockJob(b.id, region.layout, region.column, restored.text, sorted(bold),
                                 tabular="\t" in region.resolved.text, italic_ranges=italic))
        return jobs, keep, slots

    # Em partes: cada bloco embute as fontes, e só ao salvar as cópias iguais viram
    # uma. Montar o livro inteiro de uma vez esgotava a memória (medido: 1,2 GB
    # para 40 páginas com fontes completas); em partes, o pico não cresce com o livro.
    reports: list[PageReport] = []
    files: list[Path] = []
    for index, chunk in sorted(chunks.items()):
        for p in chunk:
            for b in by_page.get(p, []):
                status_count[by_id[b.id]["status"]] += 1
        key = chunk_key(chunk)
        pdf_part, json_part = cache_dir / f"c{index:04d}-{key}.pdf", cache_dir / f"c{index:04d}-{key}.json"
        if pdf_part.exists() and json_part.exists():
            reports.extend(_report_from(r) for r in json.loads(json_part.read_text(encoding="utf-8")))
            state["chunks_reused"] += 1
            state["pages_done"] += len(chunk)
        else:
            if should_stop and should_stop():
                raise AssemblyStopped("montagem cancelada; as partes prontas ficam guardadas")
            doc = pymupdf.open()
            for p in chunk:
                doc.insert_pdf(original, from_page=p - 1, to_page=p - 1)
            part_reports = []
            for i, p in enumerate(chunk):
                page, orig_page = doc[i], original[p - 1]
                jobs, keep, slots = page_jobs(p)
                boards = [pymupdf.Rect(d.bbox) for d in notation.diagrams if d.page == p]
                report = compose_page(page, orig_page, jobs, boards, keep, p)
                verify_text(page, report, jobs, slots)
                part_reports.append(report)
                side_by_side(orig_page, page, out / "paginas" / f"p{p:03d}.png")
                state["pages_done"] += 1
                if progress:
                    progress(dict(state))
            doc.subset_fonts()
            _write_atomic(pdf_part, doc.tobytes(garbage=4, deflate=True))
            doc.close()
            # O relatório vai por último: parte sem relatório não conta como pronta.
            _write_atomic(json_part, json.dumps([asdict(r) for r in part_reports], ensure_ascii=False).encode())
            for stale in cache_dir.glob(f"c{index:04d}-*"):
                if key not in stale.name:
                    stale.unlink(missing_ok=True)
            reports.extend(part_reports)
        files.append(pdf_part)
        state["chunks_done"] += 1
        if progress:
            progress(dict(state))

    final = pymupdf.open()
    for path in files:
        with pymupdf.open(path) as part:
            final.insert_pdf(part)
    _write_atomic(out / "traduzido.pdf", final.tobytes(garbage=4, deflate=True))
    final.close()
    summary = {
        "source_sha256_before": sha_before,
        "source_sha256_after": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "pages": pages,
        "chunks": len(chunks),
        "chunks_reused": state["chunks_reused"],
        "code_version": version,
        "content_sha256": content_hash(result),
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
    detail = [{"page": r.page, "ok": r.ok, "blocks": [b.__dict__ for b in r.blocks], "missing_text": r.missing_text,
               "cut_text": r.cut_text, "missing_notation": r.missing_notation,
               "leftover_original": r.leftover_original, "overlaps": r.overlaps,
               "diagram_changed_pct": r.diagram_changed_pct, "font_substitutions": r.font_substitutions}
              for r in reports]
    _write_atomic(out / "relatorio.json", json.dumps({"summary": summary, "pages": detail}, ensure_ascii=False,
                                                     indent=1, default=str).encode("utf-8"))
    _write_atomic(out / "pages.txt", " ".join(map(str, pages)).encode())
    if summary["source_sha256_after"] != sha_before:
        raise RuntimeError("o original mudou durante a montagem")
    return summary

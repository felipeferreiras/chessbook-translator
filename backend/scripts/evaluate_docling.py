"""Mede o Docling nas mesmas páginas e com o mesmo gabarito de ``evaluate_ocr``.

O Docling não é dependência do projeto (traz o PyTorch, ~6 GB). Rodar num
ambiente próprio, a partir de backend/:

    uv venv /root/docling-venv && uv pip install --python /root/docling-venv/bin/python docling pymupdf chess
    PYTHONPATH=. /root/docling-venv/bin/python -m scripts.evaluate_docling LIVRO.pdf --pages 21-26 \\
        [--ocr tesseract|rapidocr|easyocr] [--noise 0] [--out relatorio.json]

Os modelos de layout vêm do Hugging Face (``huggingface.co`` e os servidores
de arquivos dele: ``*.hf.co``, ``*.xethub.hf.co``). Mede: palavras na ordem de
leitura, lances com peça, diagramas detectados como imagem (``picture``) e
tempo por página. Só números saem do livro.
"""

from __future__ import annotations

import argparse
import difflib
import json
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pymupdf

from app.pipeline.notation_pass import collect
from app.pipeline.segments import parse_pages
from scripts.evaluate_ocr import TRUTH_MOVE, _words, rasterize

SKIP_LABELS = {"picture", "table", "chart"}


def converter(ocr: str):
    from docling.datamodel import pipeline_options as po
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption

    engines = {
        "tesseract": lambda: po.TesseractCliOcrOptions(lang=["eng"], force_full_page_ocr=True),
        "rapidocr": lambda: po.RapidOcrOptions(force_full_page_ocr=True),
        "easyocr": lambda: po.EasyOcrOptions(lang=["en"], force_full_page_ocr=True),
    }
    opts = po.PdfPipelineOptions(do_ocr=True, do_table_structure=False, ocr_options=engines[ocr]())
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--pages", required=True)
    ap.add_argument("--ocr", default="tesseract", choices=("tesseract", "rapidocr", "easyocr"))
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--noise", type=float, default=0.0)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    src = pymupdf.open(args.pdf)
    pages = sorted(parse_pages(args.pages, src.page_count))
    truth = collect(src, range(min(pages) - 1, max(pages)), ocr_mode="off")
    rng = np.random.default_rng(7)
    scans = pymupdf.open()
    for p in pages:
        scans.insert_pdf(rasterize(src[p - 1], args.dpi, args.noise, rng))
    conv = converter(args.ocr)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "digitalizado.pdf"
        scans.save(path)
        conv.convert(path, page_range=(1, 1))  # carrega os modelos fora da medida de tempo
        t = time.time()
        doc = conv.convert(path).document
        seconds = time.time() - t
    texts: dict[int, list[str]] = {}
    pictures: dict[int, list[pymupdf.Rect]] = {}
    labels: Counter[str] = Counter()
    for item, _level in doc.iterate_items():
        if not getattr(item, "prov", None):
            continue
        prov = item.prov[0]
        label = str(getattr(item.label, "value", item.label))
        labels[label] += 1
        height = doc.pages[prov.page_no].size.height
        box = prov.bbox.to_top_left_origin(page_height=height)
        if label in SKIP_LABELS:
            pictures.setdefault(prov.page_no, []).append(pymupdf.Rect(box.l, box.t, box.r, box.b))
        elif getattr(item, "text", ""):
            texts.setdefault(prov.page_no, []).append(item.text)
    totals: Counter[str] = Counter()
    for index, p in enumerate(pages, start=1):
        expected = _words(" ".join(r.resolved.text for r in truth.regions if r.page == p))
        got = _words(" ".join(texts.get(index, [])))
        sm = difflib.SequenceMatcher(a=expected, b=got, autojunk=False)
        totals["words_expected"] += len(expected)
        totals["words_matched"] += sum(m.size for m in sm.get_matching_blocks())
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            for k in range(i1, i2):
                truth_move = TRUTH_MOVE.match(expected[k])
                if not truth_move:
                    continue
                totals["moves_expected"] += 1
                j = j1 + (k - i1)
                read = TRUTH_MOVE.match(got[j]) if tag in ("equal", "replace") and j < j2 else None
                totals["moves_ok" if read and read.groups()[1:] == truth_move.groups()[1:] else "moves_wrong"] += 1
        boards = [pymupdf.Rect(d.bbox) for d in truth.diagrams if d.page == p]
        found = pictures.get(index, [])
        totals["boards_expected"] += len(boards)
        totals["boards_found"] += sum(any(f.contains((b.tl + b.br) / 2) for f in found) for b in boards)
        totals["pictures_not_boards"] += sum(not any(f.contains((b.tl + b.br) / 2) for b in boards) for f in found)
    report = {"engine": f"docling + {args.ocr}", "pages": len(pages), "dpi": args.dpi, "noise": args.noise,
              "seconds_per_page": round(seconds / len(pages), 2), **totals, "labels": dict(labels),
              "word_accuracy": round(totals["words_matched"] / max(1, totals["words_expected"]), 4),
              "moves_correct_rate": round(totals["moves_ok"] / max(1, totals["moves_expected"]), 4)}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

"""Mede o OCR contra um PDF digital: as páginas viram imagem, passam pelo OCR e são comparadas ao texto original.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.evaluate_ocr LIVRO.pdf --pages 21-30 [--dpi 300] [--noise 0] [--out relatorio.json]

O texto do PDF digital (com o mapa de glifos já resolvido) é o gabarito. Não
grava nada do livro: só números (acertos de palavras, de lances com peça, de
diagramas) e, com ``--examples``, alguns pares lidos × esperados.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pymupdf

from app.extraction.ocr import ocr_document
from app.pipeline.notation_pass import collect
from app.pipeline.segments import parse_pages

FIG_TO_LETTER = str.maketrans("♔♕♖♗♘♚♛♜♝♞", "KQRBNKQRBN")
TRUTH_MOVE = re.compile(r"^(\d{1,3}\.{0,3})?([KQRBN])([a-h]?[1-8]?x?[a-h][1-8])")


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.translate(FIG_TO_LETTER)) if w]


def rasterize(page: pymupdf.Page, dpi: int, noise: float, rng: np.random.Generator) -> pymupdf.Document:
    """A página como imagem (escala de cinza), com ruído gaussiano opcional, num PDF só de imagem."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    if noise:
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(np.float32)
        arr = np.clip(arr + rng.normal(0, noise, arr.shape), 0, 255).astype(np.uint8)
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pix.width, pix.height, arr.tobytes(), False)
    doc = pymupdf.open()
    out = doc.new_page(width=page.rect.width, height=page.rect.height)
    out.insert_image(out.rect, pixmap=pix)
    return doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--pages", required=True)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--noise", type=float, default=0.0, help="desvio do ruído gaussiano (0–255)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--examples", type=int, default=0)
    args = ap.parse_args()
    src = pymupdf.open(args.pdf)
    pages = sorted(parse_pages(args.pages, src.page_count))
    truth = collect(src, range(min(pages) - 1, max(pages)))
    rng = np.random.default_rng(7)
    totals: Counter[str] = Counter()
    examples: list[tuple[str, str, str]] = []
    confidences: list[tuple[float, bool, bool]] = []
    scans = pymupdf.open()
    for p in pages:
        scans.insert_pdf(rasterize(src[p - 1], args.dpi, args.noise, rng))
    t = time.time()
    results = ocr_document(scans, list(range(1, len(pages) + 1)))
    seconds = time.time() - t
    for index, p in enumerate(pages):
        res = results[index + 1]
        expected = _words(" ".join(r.resolved.text for r in truth.regions if r.page == p))
        got_raw = [s["text"].strip() for b in res.blocks for ln in b["lines"] for s in ln["spans"]]
        got = [w.translate(FIG_TO_LETTER) for w in got_raw]
        warned = " ".join(n for notes in res.warnings.values() for n in notes)
        totals["second_pass_pages"] += res.second_pass
        # palavras: alinhamento das sequências
        sm = difflib.SequenceMatcher(a=expected, b=got, autojunk=False)
        totals["words_expected"] += len(expected)
        totals["words_matched"] += sum(m.size for m in sm.get_matching_blocks())
        # lances com peça: o que o OCR leu na posição correspondente
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            for k in range(i1, i2):
                if not TRUTH_MOVE.match(expected[k]):
                    continue
                totals["moves_expected"] += 1
                read = got[j1 + (k - i1)] if tag in ("equal", "replace") and j1 + (k - i1) < j2 else None
                if read is None:
                    totals["moves_lost"] += 1
                    continue
                j = j1 + (k - i1)
                flagged = f"'{got_raw[j]}'" in warned
                truth_move, read_move = TRUTH_MOVE.match(expected[k]), TRUTH_MOVE.match(read)
                ok = bool(read_move) and read_move.groups()[1:] == truth_move.groups()[1:]
                key = ("moves_ok" if ok else "moves_wrong") + ("_flagged" if flagged else "_unflagged")
                totals[key] += 1
                if j in res.move_confidence:
                    confidences.append((round(res.move_confidence[j], 1), ok, flagged))
                if not ok and len(examples) < args.examples:
                    examples.append((expected[k], got_raw[j], "avisado" if flagged else "SEM AVISO"))
            # figurina posta onde o original não tinha peça
            if tag in ("equal", "replace"):
                for k in range(i1, min(i2, i1 + (j2 - j1))):
                    j = j1 + (k - i1)
                    if any(ch in "♔♕♖♗♘" for ch in got_raw[j]) and not re.search(r"[KQRBN]", expected[k]):
                        totals["figurines_spurious"] += 1
                        if len(examples) < args.examples:
                            examples.append((expected[k], got_raw[j], "figurina sem peça no original"))
        # diagramas: centro dentro de um tabuleiro do gabarito
        boards = [pymupdf.Rect(d.bbox) for d in truth.diagrams if d.page == p]
        found = [pymupdf.Rect(b) for b in res.boards]
        totals["boards_expected"] += len(boards)
        totals["boards_found"] += sum(any(b.contains((f.tl + f.br) / 2) for f in found) for b in boards)
        totals["boards_spurious"] += sum(not any(b.contains((f.tl + f.br) / 2) for b in boards) for f in found)
        totals["words_low_conf"] += res.low_confidence
    report = {"pages": len(pages), "dpi": args.dpi, "noise": args.noise,
              "seconds_per_page": round(seconds / len(pages), 2),
              **totals,
              "word_accuracy": round(totals["words_matched"] / max(1, totals["words_expected"]), 4),
              "moves_correct_rate": round((totals["moves_ok_flagged"] + totals["moves_ok_unflagged"])
                                          / max(1, totals["moves_expected"]), 4),
              "moves_wrong_without_warning": totals["moves_wrong_unflagged"]}
    if args.examples:  # quantos erros sem aviso cada limite de confiança da casa pegaria (e quantos acertos marcaria)
        report["conf_thresholds"] = {t: {"wrong_unflagged_caught": sum(c < t and not ok and not fl for c, ok, fl in confidences),
                                         "wrong_unflagged_left": sum(c >= t and not ok and not fl for c, ok, fl in confidences),
                                         "right_newly_flagged": sum(c < t and ok and not fl for c, ok, fl in confidences)}
                                     for t in (50, 60, 70, 80, 85, 90, 95)}
    if examples:
        report["examples"] = examples
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

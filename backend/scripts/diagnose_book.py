"""Diagnóstico de um livro em PDF: fontes, diagramas e notação.

Uso:
    .venv/bin/python scripts/diagnose_book.py LIVRO.pdf DIRETÓRIO_DE_SAÍDA [--pages 1-40]

O diretório de saída deve ficar FORA do repositório: o relatório detalhado
contém trechos do livro. Apenas métricas agregadas devem ir para a
documentação.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import pymupdf

from app.chess.notation import MoveStatus
from app.extraction.font_profiles import base_font_name
from app.pipeline.notation_pass import collect, validate


def page_range(spec: str | None, count: int) -> range:
    if not spec:
        return range(count)
    a, _, b = spec.partition("-")
    return range(int(a) - 1, int(b or a))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--pages")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    data = args.pdf.read_bytes()
    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = page_range(args.pages, doc.page_count)
    fonts: Counter[str] = Counter()
    images = 0
    for pno in pages:
        page = doc[pno]
        images += len(page.get_images())
        for f in page.get_fonts():
            fonts[base_font_name(f[3])] += 1

    result = collect(doc, pages)
    validate(result)

    statuses: Counter[str] = Counter()
    contexts: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    issues: Counter[str] = Counter()
    unmapped: Counter[str] = Counter()
    per_page: dict[int, Counter[str]] = {}
    detail = []
    for r in result.regions:
        if r.analysis is None:
            continue
        pc = per_page.setdefault(r.page, Counter())
        for font, ch in r.resolved.unmapped:
            unmapped[f"{font}:{ch!r}"] += 1
        for m in r.analysis.moves:
            statuses[m.status.value] += 1
            contexts[m.context.value] += 1
            pc[m.status.value] += 1
            for w in m.warnings:
                warnings[w] += 1
        for i in r.analysis.issues:
            issues[i.split(":")[0]] += 1
        detail.append({
            "page": r.page, "bbox": r.bbox, "text": r.resolved.text,
            "moves": [
                {"text": m.atom.text, "status": m.status.value, "uci": m.uci, "context": m.context.value,
                 "warnings": m.warnings, "interpretations": m.interpretations}
                for m in r.analysis.moves
            ],
            "issues": r.analysis.issues,
        })
    for d in result.diagrams:
        per_page.setdefault(d.page, Counter())["diagrams"] += 1
    diag_ok = sum(d.reading.ok for d in result.diagrams)
    diag_side = sum(d.white_to_move is not None for d in result.diagrams)
    diag_issues = Counter(i.split(" ")[0] for d in result.diagrams for i in d.reading.issues)
    total_moves = sum(statuses.values())
    summary = {
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "pages_analyzed": len(pages),
        "page_count": doc.page_count,
        "pages_without_text": sum(1 for p in pages if len(doc[p].get_text().strip()) < 30),
        "images": images,
        "fonts_by_pages": dict(fonts.most_common()),
        "style": {"numbers_without_dot": result.style.numbers_without_dot,
                  "abbreviated_pawn_captures": result.style.abbreviated_pawn_captures},
        "convention": result.convention.value,
        "evidence": result.evidence,
        "regions": len(result.regions),
        "diagrams": len(result.diagrams),
        "diagrams_read_ok": diag_ok,
        "diagrams_with_side_to_move": diag_side,
        "diagram_issue_kinds": dict(diag_issues),
        "moves_total": total_moves,
        "moves_by_status": dict(statuses.most_common()),
        "moves_by_context": dict(contexts.most_common()),
        "validated_pct": round(100 * statuses[MoveStatus.VALIDATED.value] / total_moves, 1) if total_moves else None,
        "warnings": dict(warnings.most_common()),
        "issues": dict(issues.most_common()),
        "unmapped_glyphs": dict(unmapped.most_common(30)),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "regions.json").write_text(json.dumps(detail, indent=1, ensure_ascii=False), encoding="utf-8")
    (args.out / "diagrams.json").write_text(json.dumps([
        {"page": d.page, "label": d.label, "bbox": d.bbox, "white_to_move": d.white_to_move,
         "exercise": d.exercise, "fen": d.fen, "issues": d.reading.issues, "notes": d.reading.notes}
        for d in result.diagrams
    ], indent=1, ensure_ascii=False), encoding="utf-8")
    (args.out / "pages.json").write_text(json.dumps({p: dict(c) for p, c in sorted(per_page.items())}, indent=1),
                                         encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

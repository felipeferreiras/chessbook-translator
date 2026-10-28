"""Auditoria de integridade de um projeto: o livro inteiro, do original ao PDF montado.

Confere, sem gastar nada e sem alterar o projeto:

* o original continua o mesmo (sha256);
* os segmentos do projeto batem com a extração do código atual (senão,
  ``scripts.project sync``);
* todo segmento tem um estado final (traduzido, revisado, só notação,
  bloqueado) e o que falta está listado;
* em **toda** versão atual (automática ou humana), cada trecho de notação da
  origem está lá byte a byte e as regras da proteção valem (``mask_edit``);
  nenhum marcador ``⟦n⟧`` ou marca ``<b>``/``<i>`` sobrou no texto;
* a última montagem cobre o texto atual (não há edição depois dela), tem o
  mesmo número de páginas e nenhuma pendência de layout, notação ou diagrama.

O resultado vai para ``output/auditoria.json``.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pymupdf

from app.translation.guard import PLACEHOLDER_RE, TAG_RE, GuardViolation, mask_edit, protect

from .project_store import ProjectStore

FINAL = {"translated", "cached", "not_needed", "reviewed", "discarded"}


def audit(store: ProjectStore, check_extraction: bool = True) -> dict:
    report: dict = {"project": store.id, "at": datetime.now(UTC).isoformat(timespec="seconds")}
    report["original_ok"] = store.verify_original()
    style = store.style

    from app.extraction.ocr import cache_is_current

    if check_extraction and not cache_is_current(store.dir / "ocr.json"):
        # refazer o OCR aqui levaria dezenas de minutos: quem refaz é a sincronização
        report["extraction"] = {"ok": False, "ocr_outdated": True, "missing_in_project": [], "only_in_project": [],
                                "source_differs": []}
    elif check_extraction:
        from app.pipeline.notation_pass import collect
        from app.pipeline.segments import book_segments

        ocr_cache = store.dir / "ocr.json"
        doc = pymupdf.open(store.original_path)
        segs = book_segments(collect(doc, ocr_cache=ocr_cache, ocr_mode="on" if ocr_cache.exists() else "off"),
                             doc.metadata.get("title", "") or store.info["name"])
        current = {s.id: s.source_extracted if s.source_extracted is not None else s.source for s in store.segments()}
        fresh = {b.id: b.region.resolved.text for b in segs}
        report["extraction"] = {
            "segments_project": len(current), "segments_extraction": len(fresh),
            "missing_in_project": sorted(set(fresh) - set(current))[:50],
            "only_in_project": sorted(set(current) - set(fresh))[:50],
            "source_differs": sorted(i for i in set(fresh) & set(current) if fresh[i] != current[i])[:50],
        }
        report["extraction"]["ok"] = not any(report["extraction"][k] for k in
                                             ("missing_in_project", "only_in_project", "source_differs"))

    states: Counter[str] = Counter()
    notation_broken, leftovers, unfinished = [], [], []
    with store._db() as db:
        rows = db.execute("SELECT s.*, t.kind AS vkind, t.text AS vtext FROM segment s LEFT JOIN translation t"
                          " ON t.segment_id = s.id AND t.version = s.current_version"
                          " WHERE s.status != 'obsolete' ORDER BY s.ordinal").fetchall()
    for r in rows:
        state = "discarded" if r["discarded"] else \
            ("reviewed" if r["vkind"] in ("edit", "revert") else "translated") if r["vtext"] is not None \
            else r["status"]
        states[state] += 1
        if state not in FINAL:
            unfinished.append(r["id"])
        if r["vtext"] is None or r["discarded"]:
            continue
        prot = protect(r["source"], style, json.loads(r["bold_json"]), json.loads(r["italic_json"]))
        try:
            mask_edit(r["vtext"], prot)
        except GuardViolation as exc:
            notation_broken.append({"id": r["id"], "problems": exc.problems[:3]})
        if PLACEHOLDER_RE.search(r["vtext"]) or TAG_RE.search(r["vtext"]):
            leftovers.append(r["id"])
    report["segments"] = {"total": len(rows), "by_state": dict(states), "unfinished": unfinished[:200],
                          "unfinished_count": len(unfinished), "notation_broken": notation_broken,
                          "markers_left": leftovers}

    out = store.dir / "output"
    rel = out / "relatorio.json"
    if rel.exists():
        summary = json.loads(rel.read_text(encoding="utf-8"))["summary"]
        assembled_at = datetime.fromtimestamp(rel.stat().st_mtime, UTC).isoformat(timespec="seconds")
        from app.layout.assemble import content_hash

        pdf = out / "traduzido.pdf"
        pages_pdf = pymupdf.open(pdf).page_count if pdf.exists() else 0
        report["assembly"] = {
            "assembled_at": assembled_at,
            "outdated": summary.get("content_sha256") != content_hash(store.export_result()),
            "pages_assembled": len(summary["pages"]), "pages_in_pdf": pages_pdf,
            "pages_in_book": int(store.info["pages"]),
            "pages_ok": len(summary["pages_ok"]),
            "blocks": summary["blocks"], "blocks_placed": summary["blocks_placed"],
            **{k: len(summary.get(k, [])) for k in ("missing_text", "cut_text", "missing_notation",
                                                     "leftover_original", "overlaps", "diagrams_changed",
                                                     "blocks_needing_review")},
            "original_unchanged_during_assembly": summary["source_sha256_before"] == summary["source_sha256_after"],
        }
        a = report["assembly"]
        a["ok"] = (pages_pdf == a["pages_assembled"] == a["pages_in_book"] and a["blocks_placed"] == a["blocks"]
                   and a["original_unchanged_during_assembly"]
                   and not any(a[k] for k in ("missing_text", "cut_text", "missing_notation", "leftover_original",
                                              "overlaps", "diagrams_changed")))
    else:
        report["assembly"] = None
    s = report["segments"]
    report["ok"] = bool(report["original_ok"] and not s["notation_broken"] and not s["markers_left"]
                        and report.get("extraction", {"ok": True})["ok"])
    report["complete"] = bool(report["ok"] and not s["unfinished_count"] and report["assembly"]
                              and report["assembly"]["ok"] and not report["assembly"]["outdated"])
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "auditoria.json.tmp"
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out / "auditoria.json")
    return report


def last(store: ProjectStore) -> dict | None:
    path = Path(store.dir / "output" / "auditoria.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

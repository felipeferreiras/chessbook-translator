"""Relatório da POC: critérios P1–P11 (``docs/quality/criterios-aceitacao.md``).

Uso (a partir de backend/):
    .venv/bin/python -m scripts.poc_report LIVRO.pdf TRADUÇÃO_DIR MONTAGEM_DIR

Lê o resultado de ``translate_pages`` e de ``assemble_pdf`` e relê o PDF
traduzido do zero: os lances e os diagramas são extraídos e validados de novo
e comparados com os do original nas mesmas páginas. Escreve, em MONTAGEM_DIR
(fora do repositório), ``poc.json`` e ``poc.html``, a página de revisão lado a
lado com cada parágrafo e sua tradução.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf
from PIL import Image

from app.chess.notation import MoveStatus
from app.chess.notation.validate import REVIEW_WARNINGS
from app.pipeline.notation_pass import DocumentNotation, collect, validate
from app.translation.guard import GuardViolation, protect, restore

ACCEPTED = {"translated", "cached"}
RATIO_RANGE = (0.8, 1.6)
CAPTION_DISTANCE = 25.0  # pt entre legenda e tabuleiro para contar como "junto"
CAPTION_TOLERANCE = 10.0  # quanto a legenda pode se afastar na tradução


def _subset(original: pymupdf.Document, pages: list[int]) -> pymupdf.Document:
    doc = pymupdf.open()
    for p in pages:
        doc.insert_pdf(original, from_page=p - 1, to_page=p - 1)
    return doc


def _analysed(doc: pymupdf.Document) -> DocumentNotation:
    notation = collect(doc)
    validate(notation)
    return notation


def _validated_moves(notation: DocumentNotation, flagged: bool = False) -> dict[int, Counter]:
    """Lances validados por página: (posição antes, lance UCI).

    ``flagged=False``: só os validados sem aviso de revisão (os confirmados);
    ``True``: só os validados com aviso, que a própria validação já põe em dúvida.
    """
    out: dict[int, Counter] = defaultdict(Counter)
    for r in notation.regions:
        if r.role != "text" or r.analysis is None:
            continue
        for m in r.analysis.moves:
            if m.status == MoveStatus.VALIDATED and any(w in REVIEW_WARNINGS for w in m.warnings) == flagged:
                out[r.page][(m.fen_before, m.uci)] += 1
    return out


def _compare(before: dict[int, Counter], after: dict[int, Counter], pages: list[int]) -> tuple[int, int, dict, dict]:
    missing, extra = {}, {}
    total = kept = 0
    for idx, p in enumerate(pages, start=1):
        a, b = before.get(idx, Counter()), after.get(idx, Counter())
        total += sum(a.values())
        kept += sum((a & b).values())
        if a - b:
            missing[p] = sum((a - b).values())
        if b - a:
            extra[p] = sum((b - a).values())
    return total, kept, missing, extra


def _gap_to_board(rect: pymupdf.Rect, board: pymupdf.Rect) -> tuple[str, float] | None:
    if rect.x0 >= board.x1 - 1 or rect.x1 <= board.x0 + 1:
        return None
    if rect.y1 <= board.y0 + 1:
        return "acima", board.y0 - rect.y1
    if rect.y0 >= board.y1 - 1:
        return "abaixo", rect.y0 - board.y1
    return None


def _jpeg(path: Path) -> str:
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "JPEG", quality=78)
    return base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("translation", type=Path)
    ap.add_argument("assembly", type=Path)
    args = ap.parse_args()

    trans = json.loads((args.translation / "resultado.json").read_text(encoding="utf-8"))
    assembly = json.loads((args.assembly / "relatorio.json").read_text(encoding="utf-8"))
    pages: list[int] = assembly["summary"]["pages"]
    segments = {s["id"]: s for s in trans["segments"]}

    source_bytes = args.pdf.read_bytes()
    original = pymupdf.open(stream=source_bytes, filetype="pdf")
    full = collect(original)
    regions = [r for r in full.regions if r.page in set(pages) and r.role == "text"]
    region_by_id = {f"p{r.page}-{i}": r for i, r in enumerate(regions)}
    criteria: dict[str, dict] = {}

    # P1 — original intacto
    sha_now = hashlib.sha256(source_bytes).hexdigest()
    s = assembly["summary"]
    p1 = sha_now == s.get("source_sha256_before") == s.get("source_sha256_after")
    criteria["P1"] = {"ok": p1, "tipo": "objetiva", "sha256": sha_now}

    # P2 — nenhum bloco perdido
    pending = [i for i, seg in segments.items() if seg["status"] not in ACCEPTED | {"not_needed"}]
    p2 = not s["missing_text"] and s["blocks_placed"] == s["blocks"]
    criteria["P2"] = {"ok": p2, "tipo": "objetiva", "blocos": s["blocks"], "escritos": s["blocks_placed"],
                      "ausentes": s["missing_text"], "pendentes_mantidos_no_original": pending}

    # P3 e P5 — o PDF traduzido relido do zero, contra o original nas mesmas páginas
    before = _analysed(_subset(original, pages))
    after = _analysed(pymupdf.open(args.assembly / "traduzido.pdf"))
    total, kept, missing_moves, extra_moves = _compare(_validated_moves(before), _validated_moves(after), pages)
    f_total, f_kept, f_missing, f_extra = _compare(_validated_moves(before, True), _validated_moves(after, True), pages)
    criteria["P3"] = {"ok": kept == total, "tipo": "objetiva",
                      "lances_validados_no_original": total, "iguais_no_traduzido": kept,
                      "faltando_por_pagina": missing_moves, "a_mais_por_pagina": extra_moves,
                      "validados_com_aviso_no_original": f_total, "validados_com_aviso_iguais": f_kept,
                      "com_aviso_faltando_por_pagina": f_missing, "com_aviso_a_mais_por_pagina": f_extra,
                      "nota": "a_mais: validados só na releitura (o original não tinha leitura confirmada)"}

    # P4 — nenhuma conversão silenciosa: toda a notação volta com a grafia original
    criteria["P4"] = {"ok": not s["missing_notation"], "tipo": "objetiva",
                      "trechos_de_notacao_alterados": s["missing_notation"],
                      "conversoes_de_notacao": 0, "nota": "a montagem não converte notação; a grafia original é mantida"}

    diag_problems = []
    by_page_before = defaultdict(list)
    by_page_after = defaultdict(list)
    for d in before.diagrams:
        by_page_before[d.page].append(d)
    for d in after.diagrams:
        by_page_after[d.page].append(d)
    for idx, p in enumerate(pages, start=1):
        da, db = by_page_before[idx], by_page_after[idx]
        if len(da) != len(db):
            diag_problems.append(f"p. {p}: {len(da)} diagramas no original, {len(db)} no traduzido")
            continue
        for x, y in zip(sorted(da, key=lambda d: d.bbox), sorted(db, key=lambda d: d.bbox), strict=True):
            if max(abs(u - v) for u, v in zip(x.bbox, y.bbox, strict=True)) > 1:
                diag_problems.append(f"p. {p}: diagrama mudou de posição ou tamanho")
            if (x.reading.placement, x.reading.issues) != (y.reading.placement, y.reading.issues):
                diag_problems.append(f"p. {p}: posição do diagrama difere")
    criteria["P5"] = {"ok": not diag_problems and not s["diagrams_changed"], "tipo": "objetiva + humana",
                      "diagramas": len(before.diagrams), "problemas": diag_problems,
                      "pixels_alterados": s["diagrams_changed"]}

    # P6 — legenda junto do diagrama
    placed = {b["region_id"]: b for pg in assembly["pages"] for b in pg["blocks"]}
    boards = defaultdict(list)
    for d in full.diagrams:
        boards[d.page].append(pymupdf.Rect(d.bbox))
    # Legenda: o bloco traduzido mais próximo de cada lado de cada tabuleiro.
    nearest: dict[tuple[int, int, str], tuple[float, str]] = {}
    for rid, region in region_by_id.items():
        if rid not in placed or region.layout is None:
            continue
        for b_idx, board in enumerate(boards[region.page]):
            g0 = _gap_to_board(pymupdf.Rect(region.layout.text_rect), board)
            if g0 is not None and g0[1] <= CAPTION_DISTANCE:
                key = (region.page, b_idx, g0[0])
                if key not in nearest or g0[1] < nearest[key][0]:
                    nearest[key] = (g0[1], rid)
    captions, far = len(nearest), []
    for (page, b_idx, side), (gap, rid) in sorted(nearest.items()):
        board = boards[page][b_idx]
        out = pymupdf.Rect(placed[rid]["rect"]) + (0, placed[rid]["margin"], 0, -placed[rid]["margin"])
        g1 = _gap_to_board(out, board)
        if g1 is None or g1[0] != side or g1[1] > gap + CAPTION_TOLERANCE:
            moved = f"{g1[0]} a {g1[1]:.0f} pt" if g1 else "sobre o tabuleiro"
            far.append(f"{rid}: {side} a {gap:.0f} pt → {moved}")
    criteria["P6"] = {"ok": not far, "tipo": "objetiva", "legendas": captions, "afastadas": far}

    # P7 — marcadores íntegros: nenhuma tradução aceita viola a proteção
    violations, rejected = [], []
    for rid, seg in segments.items():
        if seg["status"] in ACCEPTED and rid in region_by_id:
            r = region_by_id[rid]
            try:
                restore(seg["raw_translation"], protect(r.resolved.text, full.style, r.main_mask, r.italic_mask))
            except GuardViolation as exc:
                violations.append(f"{rid}: {exc}")
        elif seg["status"] == "needs_review":
            rejected.append(rid)
    criteria["P7"] = {"ok": not violations, "tipo": "objetiva", "aceitos_com_violacao": violations,
                      "rejeitados_pela_protecao": rejected}

    # P8 — omissão (heurística): razão de comprimento PT/EN
    ratios = {rid: len(seg["text"]) / max(1, len(seg["source"]))
              for rid, seg in segments.items() if seg["status"] in ACCEPTED and seg["text"]}
    outside = {rid: round(v, 2) for rid, v in ratios.items() if not RATIO_RANGE[0] <= v <= RATIO_RANGE[1]}
    criteria["P8"] = {"ok": True, "tipo": "heurística", "faixa": RATIO_RANGE, "fora_da_faixa": outside,
                      "nota": "itens fora da faixa são listados para revisão, não reprovam"}

    # P9 — qualidade da tradução: revisão humana
    criteria["P9"] = {"ok": None, "tipo": "humana", "nota": "revisar poc.html; aguardando o usuário"}

    # P10 — layout
    out_doc = pymupdf.open(args.assembly / "traduzido.pdf")
    outside_page = []
    for idx, pg in enumerate(assembly["pages"]):
        page_rect = out_doc[idx].rect
        for b in pg["blocks"]:
            r = pymupdf.Rect(b["rect"]) + (0, b["margin"], 0, -b["margin"])
            if b["placed"] and not page_rect.contains(r):
                outside_page.append(b["region_id"])
    blocks = [b for pg in assembly["pages"] for b in pg["blocks"]]
    unflagged = [b["region_id"] for b in blocks if b["placed"] and b["scale"] < 0.85
                 and b["region_id"] not in s["blocks_needing_review"]]
    criteria["P10"] = {"ok": not s["overlaps"] and not outside_page and not unflagged, "tipo": "objetiva",
                       "sobreposicoes": s["overlaps"], "fora_da_pagina": outside_page,
                       "reducao_acima_de_15pct_sem_sinal": unflagged,
                       "reduzidos": Counter(str(b["scale"]) for b in blocks if b["scale"] < 1),
                       "para_revisao": s["blocks_needing_review"]}

    criteria["P11"] = {"ok": True, "tipo": "objetiva", "nota": "este relatório"}

    report = {"pages": pages, "criteria": criteria,
              "translation": trans["summary"], "assembly": {k: v for k, v in s.items() if k != "pages"}}
    (args.assembly / "poc.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                                            encoding="utf-8")
    (args.assembly / "poc.html").write_text(_html(report, pages, segments, args.assembly), encoding="utf-8")
    for key, c in criteria.items():
        state = "pendente" if c["ok"] is None else "ok" if c["ok"] else "FALHOU"
        print(f"{key:4} {state:9} {c['tipo']}")


DESCRIPTIONS = {
    "P1": "Original intacto (sha256 antes = depois)",
    "P2": "Nenhum bloco perdido",
    "P3": "Notação nunca corrompida (lances validados relidos do PDF final)",
    "P4": "Nenhuma conversão silenciosa",
    "P5": "Diagramas preservados (posição, tamanho, peças, pixels)",
    "P6": "Legenda junto do diagrama",
    "P7": "Marcadores de tradução íntegros",
    "P8": "Tradução sem omissão (razão de comprimento)",
    "P9": "Qualidade da tradução (revisão do usuário)",
    "P10": "Layout (sobreposição, fora da página, redução > 15 %)",
    "P11": "Relatório gerado",
}


def _detail(c: dict) -> str:
    skip = {"ok", "tipo"}
    return "; ".join(f"{k}: {v}" for k, v in c.items() if k not in skip and v not in ([], {}, None))


def _html(report: dict, pages: list[int], segments: dict, assembly: Path) -> str:
    rows = []
    for key, c in report["criteria"].items():
        state = "pendente" if c["ok"] is None else "ok" if c["ok"] else "falhou"
        rows.append(f"<tr class={state}><td>{key}</td><td>{html.escape(DESCRIPTIONS[key])}</td>"
                    f"<td>{c['tipo']}</td><td>{state}</td><td>{html.escape(_detail(c))}</td></tr>")
    sections = []
    for p in pages:
        img = _jpeg(assembly / "paginas" / f"p{p:03d}.png")
        segs = [seg for rid, seg in segments.items() if rid.startswith(f"p{p}-")]
        items = []
        for seg in segs:
            if seg["status"] == "not_needed":
                continue
            notes = "; ".join(seg["warnings"] + seg["problems"])
            items.append(f"<tr><td class=id>{seg['id']}<br><small>{seg['status']}</small></td>"
                         f"<td>{html.escape(seg['source'])}</td><td>{html.escape(seg['text'] or '')}</td>"
                         f"<td class=note>{html.escape(notes)}</td></tr>")
        sections.append(f"<section id=p{p}><h2>Página {p}</h2><img src='data:image/jpeg;base64,{img}' "
                        f"alt='página {p}: original à esquerda, tradução à direita'>"
                        f"<table class=seg><tr><th>Bloco</th><th>Original</th><th>Tradução</th><th>Avisos</th></tr>"
                        f"{''.join(items)}</table></section>")
    nav = " ".join(f"<a href=#p{p}>{p}</a>" for p in pages)
    return f"""<!doctype html><html lang=pt-BR><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>Revisão da POC</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--muted:#666;--line:#ddd;--ok:#e6f4ea;--bad:#fde8e8;--wait:#fff6d6}}
@media (prefers-color-scheme: dark){{:root{{--bg:#161618;--fg:#eee;--muted:#aaa;--line:#333;--ok:#1d3325;--bad:#3d1f1f;--wait:#3a3318}}}}
body{{margin:0 auto;max-width:1200px;padding:16px;font:15px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg)}}
table{{border-collapse:collapse;width:100%;margin:8px 0 24px}} td,th{{border:1px solid var(--line);padding:6px;vertical-align:top;text-align:left}}
tr.ok td:nth-child(4){{background:var(--ok)}} tr.falhou td:nth-child(4){{background:var(--bad)}} tr.pendente td:nth-child(4){{background:var(--wait)}}
img{{width:100%;height:auto;border:1px solid var(--line)}} .id{{white-space:nowrap;color:var(--muted)}} .note{{color:var(--muted);font-size:13px}}
nav a{{margin-right:6px}} .seg td:nth-child(2),.seg td:nth-child(3){{width:42%}}
@media (max-width:700px){{.seg td,.seg th{{display:block;width:auto!important}}}}
</style></head><body>
<h1>Revisão da POC</h1>
<p>Original à esquerda, tradução à direita. Critérios medidos pelo próprio sistema; P9 depende da sua leitura.</p>
<table><tr><th>#</th><th>Critério</th><th>Tipo</th><th>Estado</th><th>Detalhe</th></tr>{''.join(rows)}</table>
<nav>Páginas: {nav}</nav>{''.join(sections)}</body></html>"""


if __name__ == "__main__":
    main()

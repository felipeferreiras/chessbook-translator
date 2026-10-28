"""Compara rodadas de ``translate_pages`` de modelos diferentes nas mesmas páginas.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.compare_models SAÍDA.html DIR_MODELO_1 DIR_MODELO_2 ... [--prices catalogo.json]

Imprime métricas (para a documentação) e grava ``SAÍDA.html`` com cada
segmento lado a lado em todos os modelos, para leitura humana. O HTML tem o
texto do livro: fica fora do repositório.

``--prices``: resposta de ``GET https://gen.pollinations.ai/text/models``, para
estimar o custo pelo catálogo (preço por token, em pollen).
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ACCEPTED = {"translated", "cached"}


def _prices(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("data", [])
    return {m.get("name") or m.get("id"): m.get("pricing", {}) for m in items}


def metrics(run: dict, prices: dict[str, dict]) -> dict:
    s, segs = run["summary"], run["segments"]
    sent = [x for x in segs if x["status"] != "not_needed"]
    warnings = [w for x in sent for w in x["warnings"]]
    ratios = [len(x["text"]) / max(1, len(x["source"])) for x in sent if x["status"] in ACCEPTED and x["text"]]
    price = prices.get(s["model"], {})
    tokens = s["tokens"]
    cost = None
    if price:
        cost = (tokens["input"] * float(price.get("promptTextTokens", 0))
                + tokens["output"] * float(price.get("completionTextTokens", 0)))
    return {
        "model": s["model"],
        "sent": len(sent),
        "accepted": sum(x["status"] in ACCEPTED for x in sent),
        "needs_review": sum(x["status"] == "needs_review" for x in sent),
        "failed": sum(x["status"] == "failed" for x in sent),
        "second_try": sum("aceito na segunda tentativa" in x["warnings"] for x in sent),
        "glossary_avoid": sum(w.startswith("glossario_evitar:") for w in warnings),
        "glossary_missing": sum(w.startswith("glossario_ausente:") for w in warnings),
        "other_warnings": sum(not w.startswith(("glossario_", "aceito na segunda")) for w in warnings),
        "ratio_mean": round(sum(ratios) / len(ratios), 2) if ratios else None,
        "calls": s["calls"],
        "call_errors": len(s["call_errors"]),
        "tokens_in": tokens["input"],
        "tokens_out": tokens["output"],
        "cost_pollen": round(cost, 4) if cost is not None else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("runs", type=Path, nargs="+")
    ap.add_argument("--prices", type=Path)
    args = ap.parse_args()
    prices = _prices(args.prices)
    runs = [json.loads((d / "resultado.json").read_text(encoding="utf-8")) for d in args.runs]
    table = [metrics(r, prices) for r in runs]
    print(json.dumps(table, ensure_ascii=False, indent=1))

    by_model = [{x["id"]: x for x in r["segments"]} for r in runs]
    head = "".join(f"<th>{html.escape(r['summary']['model'])}</th>" for r in runs)
    rows = []
    for seg in runs[0]["segments"]:
        if seg["status"] == "not_needed":
            continue
        cells = []
        for m in by_model:
            x = m.get(seg["id"], {})
            notes = "; ".join(x.get("warnings", []) + x.get("problems", []))
            cells.append(f"<td>{html.escape(x.get('text') or '—')}"
                         f"{f'<div class=n>{html.escape(notes)}</div>' if notes else ''}</td>")
        rows.append(f"<tr><td class=id>{seg['id']}</td><td>{html.escape(seg['source'])}</td>{''.join(cells)}</tr>")
    args.out.write_text(f"""<!doctype html><html lang=pt-BR><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>Comparação de modelos</title>
<style>:root{{--bg:#fff;--fg:#1d1d1f;--line:#ddd;--muted:#666}}
@media (prefers-color-scheme: dark){{:root{{--bg:#161618;--fg:#eee;--line:#333;--muted:#aaa}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;min-width:900px}}
td,th{{border:1px solid var(--line);padding:6px;vertical-align:top;text-align:left}}
.id{{white-space:nowrap;color:var(--muted)}} .n{{color:var(--muted);font-size:12px;margin-top:4px}}</style></head>
<body><h1>Comparação de modelos</h1><div class=wrap><table><tr><th>Bloco</th><th>Original</th>{head}</tr>
{''.join(rows)}</table></div></body></html>""", encoding="utf-8")


if __name__ == "__main__":
    main()

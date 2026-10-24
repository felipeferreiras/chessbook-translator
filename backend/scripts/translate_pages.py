"""Traduz páginas de um livro com o provedor configurado e gera um comparativo.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.translate_pages LIVRO.pdf SAÍDA --pages 15,21,62
        [--provider pollinations|anthropic|openai|gemini|fake] [--model ID] [--env-file ../.env]

Configuração em ``.env`` (ver ``.env.example`` e ``app/translation/config.py``).
O diretório de saída deve ficar FORA do repositório: contém o texto do livro.
O comparativo ``comparativo.html`` mostra original, tradução e estado de cada
segmento; ``resultado.json`` guarda tudo, inclusive a saída bruta do provedor.
"""

from __future__ import annotations

import argparse
import html
import json
from itertools import groupby
from pathlib import Path

import pymupdf

from app.pipeline.notation_pass import collect
from app.pipeline.segments import book_segments
from app.translation.cache import TranslationCache
from app.translation.config import load_env_file, model_warnings, provider_from_env
from app.translation.glossary import Glossary
from app.translation.provider import ConfigurationError
from app.translation.service import TranslationRun, translate

ROOT = Path(__file__).resolve().parents[2]


def parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        pages.extend(range(int(a), int(b or a) + 1))
    return pages


def write_html(path: Path, title: str, rows: list[dict]) -> None:
    status_color = {"translated": "#e7f6ea", "cached": "#e7f0f6", "not_needed": "#f4f4f4",
                    "needs_review": "#fff3d6", "failed": "#fde2e2"}
    body = []
    for r in rows:
        notes = "<br>".join(html.escape(x) for x in r["problems"] + r["warnings"])
        body.append(
            f"<tr style='background:{status_color.get(r['status'], '#fff')}'>"
            f"<td>{r['page']}</td><td>{html.escape(r['source'])}</td>"
            f"<td>{html.escape(r['text'] or '')}</td><td>{r['status']}<br><small>{notes}</small></td></tr>"
        )
    path.write_text(
        "<!doctype html><meta charset='utf-8'><title>" + html.escape(title) + "</title>"
        "<style>body{font-family:'Liberation Serif',serif;margin:16px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:6px;vertical-align:top}td:nth-child(2),td:nth-child(3){width:42%}"
        "small{color:#555}</style>"
        f"<h1>{html.escape(title)}</h1><table><tr><th>pág.</th><th>original</th><th>tradução</th><th>estado</th></tr>"
        + "".join(body) + "</table>",
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--pages", required=True, help="ex.: 15,21,60-62")
    ap.add_argument("--provider")
    ap.add_argument("--model", help="substitui o modelo do .env (ex.: openai/gpt-5.5 na Pollinations)")
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    ap.add_argument("--glossary", type=Path, help="glossário do projeto (JSON) que substitui/acrescenta termos")
    args = ap.parse_args()
    load_env_file(args.env_file)
    try:
        provider = provider_from_env(name=args.provider, model=args.model)
    except ConfigurationError as exc:
        raise SystemExit(f"Configuração: {exc}") from exc
    for warning in model_warnings(provider.model):
        print(f"AVISO: {warning}")
    args.out.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(args.pdf)
    notation = collect(doc)  # estilo e convenção detectados no livro inteiro
    wanted = set(parse_pages(args.pages))
    # Seções e ids do livro inteiro (o capítulo de uma página depende dos títulos anteriores).
    segs = book_segments(notation, doc.metadata.get("title", ""), wanted)
    glossary = Glossary.load(overrides=args.glossary)
    cache = TranslationCache(args.out / "cache.sqlite")
    run = TranslationRun([], [])
    # Um lote nunca mistura seções: cada grupo vai com o próprio capítulo e subseção.
    for label, group in groupby(segs, key=lambda b: b.section.label):
        # Bloco com lances desenhados como vetor não vai ao tradutor: perderia lances.
        sendable = [b.source() for b in group if not b.blocked]
        if sendable:
            part = translate(sendable, provider, glossary, section=label, style=notation.style, cache=cache)
            run.results.extend(part.results)
            run.calls.extend(part.calls)
    by_id = {res.id: res for res in run.results}

    rows = []
    for seg in segs:
        res = by_id.get(seg.id)
        if res is None:
            rows.append({"page": seg.page, "id": seg.id, "section": seg.section.label,
                         "source": seg.region.resolved.text, "masked": "", "text": None, "raw_translation": None,
                         "status": "blocked", "problems": [seg.blocked], "warnings": [], "provider": "", "model": ""})
            continue
        rows.append({"page": seg.page, "id": res.id, "section": seg.section.label,
                     "source": res.source, "masked": res.masked,
                     "text": res.text, "raw_translation": res.raw_translation, "status": res.status.value,
                     "problems": res.problems, "warnings": res.warnings, "provider": res.provider, "model": res.model})
    summary = {
        "provider": provider.name, "model": provider.model, "remote": provider.remote,
        "pages": sorted(wanted), "segments": len(segs), "by_status": {**run.counts(), **({"blocked": sum(1 for r in rows if r["status"] == "blocked")} if any(r["status"] == "blocked" for r in rows) else {})},
        "calls": len(run.calls), "call_errors": [c.error for c in run.calls if c.error],
        "tokens": run.tokens(),
    }
    (args.out / "resultado.json").write_text(json.dumps({"summary": summary, "segments": rows}, ensure_ascii=False,
                                                        indent=1), encoding="utf-8")
    write_html(args.out / "comparativo.html", f"{provider.name}/{provider.model} — páginas {args.pages}", rows)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

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
from pathlib import Path

import pymupdf

from app.pipeline.notation_pass import collect
from app.translation.cache import TranslationCache
from app.translation.config import load_env_file, model_warnings, provider_from_env
from app.translation.glossary import Glossary
from app.translation.provider import ConfigurationError
from app.translation.service import SourceSegment, translate

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
    regions = [r for r in notation.regions if r.page in wanted and r.role == "text"]
    sources = [SourceSegment(f"p{r.page}-{i}", r.resolved.text, bold=tuple(r.main_mask), italic=tuple(r.italic_mask))
               for i, r in enumerate(regions)]
    run = translate(sources, provider, Glossary.load(), section=doc.metadata.get("title", ""),
                    style=notation.style, cache=TranslationCache(args.out / "cache.sqlite"))

    rows = []
    for region, res in zip(regions, run.results, strict=True):
        rows.append({"page": region.page, "id": res.id, "source": res.source, "masked": res.masked,
                     "text": res.text, "raw_translation": res.raw_translation, "status": res.status.value,
                     "problems": res.problems, "warnings": res.warnings, "provider": res.provider, "model": res.model})
    summary = {
        "provider": provider.name, "model": provider.model, "remote": provider.remote,
        "pages": sorted(wanted), "segments": len(sources), "by_status": run.counts(),
        "calls": len(run.calls), "call_errors": [c.error for c in run.calls if c.error],
        "tokens": run.tokens(),
    }
    (args.out / "resultado.json").write_text(json.dumps({"summary": summary, "segments": rows}, ensure_ascii=False,
                                                        indent=1), encoding="utf-8")
    write_html(args.out / "comparativo.html", f"{provider.name}/{provider.model} — páginas {args.pages}", rows)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

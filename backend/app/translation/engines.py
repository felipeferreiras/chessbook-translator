"""Motores de tradução oferecidos ao usuário e estimativa de custo antes de traduzir.

Todos passam pela Pollinations (uma chave só). O preço vem do catálogo da
Pollinations (``GET /text/models``), lido na hora e guardado em cache; se não
der para ler, vale a tabela de 2026-10-24 abaixo, e a estimativa diz isso.

A estimativa monta exatamente os lotes que a tradução enviaria
(``prepare_segments`` + ``_batches`` + ``build_request``) e conta caracteres.
Os fatores de cada motor corrigem a conta pelo que o modelo realmente gastou
nas rodadas medidas (o Gemini e o Qwen cobram raciocínio como saída, por
exemplo). É uma previsão, com faixa de incerteza, não um preço fechado.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path

from app.chess.notation.lexer import DEFAULT_STYLE, LexStyle

from .cache import TranslationCache
from .glossary import Glossary
from .prompt import build_request, cache_key
from .service import SourceSegment, _batches, prepare_segments

CATALOG_URL = "https://gen.pollinations.ai/text/models"
CHARS_PER_TOKEN = 3.6  # média medida em texto de xadrez em inglês e português mascarado
OUTPUT_GROWTH = 1.05  # a tradução para o português é um pouco mais longa
JSON_OVERHEAD = 30  # {"id": ..., "text": ...} por segmento


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    model: str
    note: str
    input_factor: float = 1.0  # tokens reais / estimados, medido
    output_factor: float = 1.0
    seconds_per_call: float = 40.0
    uncertainty: float = 0.35  # faixa mostrada ao usuário (±), maior onde o gasto variou entre rodadas
    status: str = "disponível"  # recomendado | disponível | experimental
    fallback_price: tuple[float, float] = (0.0, 0.0)  # pollen por token: entrada, saída (2026-10-24)


# Fatores = tokens reais / estimados, medidos em rodadas reais (docs/research/11-motores-custo.md).
# Gemini variou de 4,1× a 7,2× na saída entre três rodadas (raciocínio): faixa maior.
ENGINES: tuple[Engine, ...] = (
    Engine("sonnet-5.5", "Claude Sonnet 5.5", "anthropic/claude-sonnet-5.5",
           "Qualidade igual ou melhor que o Gemini, ~2× mais rápido, mesmo custo.", status="recomendado",
           input_factor=1.89, output_factor=3.04, uncertainty=0.25, seconds_per_call=17,
           fallback_price=(1.5e-6, 7.5e-6)),
    Engine("opus-5.5", "Claude Opus 5.5", "anthropic/claude-opus-5.5",
           "O português mais natural da comparação; ~1,7× o custo do Sonnet.",
           input_factor=1.89, output_factor=2.43, uncertainty=0.25, seconds_per_call=18,
           fallback_price=(3e-6, 15e-6)),
    Engine("gemini-3.8-flash", "Gemini 3.8 Flash", "google/gemini-3.8-flash",
           "Escolha da Fase 2; um pouco mais literal; cobra raciocínio como saída.",
           input_factor=1.76, output_factor=5.3, uncertainty=0.45, seconds_per_call=40,
           fallback_price=(0.75e-6, 3.75e-6)),
    Engine("gpt-5.5", "GPT-5.5", "openai/gpt-5.5",
           "Terminologia correta na Fase 2; pontuação dupla ocasional; o mais caro por token.",
           input_factor=1.8, output_factor=2.33, seconds_per_call=40, fallback_price=(3.75e-6, 22.5e-6)),
    Engine("gpt-5.4-nano", "GPT-5.4 Nano", "openai/gpt-5.4-nano",
           "O mais barato; errou terminologia em listas e índices na Fase 2.",
           input_factor=1.8, output_factor=1.3, seconds_per_call=13, fallback_price=(0.15e-6, 0.9375e-6)),
    Engine("qwen-3.8-27b", "Qwen 3.8 27B (pesos abertos)", "qwen/qwen3.8-27b",
           "Candidato a rodar localmente; lento e instável com lotes grandes.", status="experimental",
           input_factor=1.4, output_factor=14.1, uncertainty=0.6, seconds_per_call=137,
           fallback_price=(0.041145e-6, 1.31875e-6)),
)


def engine(engine_id: str) -> Engine:
    found = next((e for e in ENGINES if e.id == engine_id), None)
    if found is None:
        raise KeyError(f"motor desconhecido: {engine_id}")
    return found


@dataclass
class Prices:
    by_model: dict[str, tuple[float, float]]
    source: str  # "catálogo (data)" | "tabela de 2026-10-24"


def load_prices(cache_file: Path | None = None, max_age: float = 86400, fetch: bool = True,
                timeout: float = 15) -> Prices:
    """Preços por token do catálogo da Pollinations, com cache local de um dia."""
    def parse(data: object) -> dict[str, tuple[float, float]]:
        items = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
        out = {}
        for m in items:
            p = m.get("pricing") or {}
            if "promptTextTokens" in p and "completionTextTokens" in p:
                out[m.get("name") or m.get("id")] = (float(p["promptTextTokens"]), float(p["completionTextTokens"]))
        return out

    if cache_file is not None and cache_file.exists() and time.time() - cache_file.stat().st_mtime < max_age:
        prices = parse(json.loads(cache_file.read_text(encoding="utf-8")))
        if prices:
            return Prices(prices, f"catálogo ({time.strftime('%Y-%m-%d', time.localtime(cache_file.stat().st_mtime))})")
    if fetch:
        try:
            with urllib.request.urlopen(CATALOG_URL, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            prices = parse(json.loads(raw))
            if prices:
                if cache_file is not None:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(raw, encoding="utf-8")
                return Prices(prices, f"catálogo ({time.strftime('%Y-%m-%d')})")
        except (OSError, ValueError):
            pass
    return Prices({e.model: e.fallback_price for e in ENGINES}, "tabela de 2026-10-24 (catálogo indisponível)")


@dataclass
class Estimate:
    engine: Engine
    segments_total: int
    segments_to_send: int  # sem os só de notação e sem os que já estão no cache
    cached: int
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float  # pollen
    cost_low: float
    cost_high: float
    minutes: float
    price_source: str
    notes: list[str] = field(default_factory=list)


def estimate(groups: list[tuple[str, list[SourceSegment]]], glossary: Glossary, eng: Engine, prices: Prices,
             style: LexStyle = DEFAULT_STYLE, cache: TranslationCache | None = None,
             max_chars: int = 6000, max_segments: int = 20, workers: int = 1) -> Estimate:
    """Custo previsto para traduzir ``groups`` [(seção, segmentos)] com ``eng`` (``workers`` seções ao mesmo tempo)."""
    total = sent = cached = calls = 0
    in_chars = out_chars = 0.0
    system = build_request([], glossary).system_prompt
    for section, sources in groups:
        pending = []
        for _src, _prot, seg, needed in prepare_segments(sources, style):
            total += 1
            if not needed:
                continue
            if cache is not None and cache.get(cache_key("pollinations", eng.model, system, seg, section, glossary)):
                cached += 1
                continue
            pending.append(seg)
        for batch in _batches(pending, max_chars, max_segments):
            req = build_request(batch, glossary, section)
            calls += 1
            sent += len(batch)
            in_chars += len(req.system_prompt) + len(req.user_payload)
            out_chars += sum(len(s.text) * OUTPUT_GROWTH + JSON_OVERHEAD for s in batch)
    tokens_in = round(in_chars / CHARS_PER_TOKEN * eng.input_factor)
    tokens_out = round(out_chars / CHARS_PER_TOKEN * eng.output_factor)
    price_in, price_out = prices.by_model.get(eng.model, eng.fallback_price)
    cost = tokens_in * price_in + tokens_out * price_out
    notes = []
    if eng.model not in prices.by_model:
        notes.append("preço do modelo fora do catálogo; usada a tabela de 2026-10-24")
    if eng.status == "experimental":
        notes.append("experimental: falhas de resposta podem exigir nova tentativa (custo extra)")
    return Estimate(eng, total, sent, cached, calls, tokens_in, tokens_out, round(cost, 4),
                    round(cost * (1 - eng.uncertainty), 4), round(cost * (1 + eng.uncertainty), 4),
                    round(calls * eng.seconds_per_call / 60 / max(1, min(workers, len(groups) or 1)), 1),
                    prices.source, notes)


def group_by_section(items: list[tuple[str, SourceSegment]]) -> list[tuple[str, list[SourceSegment]]]:
    """[(seção, segmento)] em ordem → grupos consecutivos da mesma seção (como a tradução envia)."""
    return [(label, [s for _, s in grp]) for label, grp in groupby(items, key=lambda x: x[0])]

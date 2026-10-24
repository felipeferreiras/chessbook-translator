"""Tradução de segmentos com notação protegida, cache, lotes e revisão.

Fluxo por segmento:

1. ``protect``: a notação vira marcadores; o tradutor nunca vê lances.
2. Segmentos sem prosa (só lances, números e pontuação) não são enviados.
3. Cache: o mesmo trecho com o mesmo provedor, modelo e prompt não é pago duas
   vezes.
4. Lotes limitados por caracteres e por quantidade de segmentos.
5. ``restore``: marcadores, casas citadas na prosa e símbolos de avaliação
   precisam voltar intactos. Se não voltarem, o segmento é reenviado sozinho
   uma vez; persistindo o problema, vai para revisão com a saída guardada.

Nada é descartado em silêncio: todo segmento termina com um estado explícito.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from app.chess.notation.lexer import DEFAULT_STYLE, LexStyle

from .cache import TranslationCache
from .glossary import Glossary
from .guard import PLACEHOLDER_RE, TAG_RE, GuardViolation, Protected, protect, restore
from .prompt import build_request, cache_key
from .provider import ProviderError, ProviderRefusal, Segment, TranslationProvider, Usage

LENGTH_RATIO_RANGE = (0.7, 1.8)
MAX_CONSECUTIVE_FAILURES = 2  # ex.: chave inválida; evita uma chamada por segmento  # heurística: fora disso, conferir omissão ou acréscimo


class SegmentStatus(StrEnum):
    TRANSLATED = "translated"
    CACHED = "cached"
    NOT_NEEDED = "not_needed"  # só notação/números: copiado sem tradução
    NEEDS_REVIEW = "needs_review"  # tradução recebida, mas a proteção falhou
    FAILED = "failed"  # provedor falhou ou recusou


@dataclass(frozen=True)
class SourceSegment:
    id: str
    text: str  # texto resolvido (glifos especiais já trocados)
    kind: str = "paragraph"
    bold: tuple[bool, ...] = ()  # negrito por caractere de ``text``
    italic: tuple[bool, ...] = ()


@dataclass
class SegmentResult:
    id: str
    source: str
    masked: str
    status: SegmentStatus
    text: str | None = None  # tradução com a notação original restaurada
    raw_translation: str | None = None  # saída mascarada do provedor
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""


@dataclass
class CallRecord:
    provider: str
    model: str
    segments: int
    usage: Usage
    error: str | None = None


@dataclass
class TranslationRun:
    results: list[SegmentResult]
    calls: list[CallRecord]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.results:
            out[r.status.value] = out.get(r.status.value, 0) + 1
        return out

    def tokens(self) -> dict[str, int]:
        total = {"input": 0, "output": 0, "cached_input": 0}
        for c in self.calls:
            total["input"] += c.usage.input_tokens or 0
            total["output"] += c.usage.output_tokens or 0
            total["cached_input"] += c.usage.cached_input_tokens or 0
        return total


def _needs_translation(masked: str) -> bool:
    prose = TAG_RE.sub("", PLACEHOLDER_RE.sub(" ", masked))
    return re.search(r"[A-Za-z]{2,}", prose) is not None


def _batches(segments: list[Segment], max_chars: int, max_segments: int) -> list[list[Segment]]:
    out: list[list[Segment]] = []
    current: list[Segment] = []
    size = 0
    for seg in segments:
        length = len(seg.text) + len(seg.context_before)
        if current and (size + length > max_chars or len(current) >= max_segments):
            out.append(current)
            current, size = [], 0
        current.append(seg)
        size += length
    if current:
        out.append(current)
    return out


def prepare_segments(sources: list[SourceSegment], style: LexStyle = DEFAULT_STYLE
                     ) -> list[tuple[SourceSegment, Protected, Segment, bool]]:
    """Mascara cada segmento e monta o que vai ao provedor: (fonte, proteção, segmento, precisa traduzir?).

    O contexto de cada segmento é o anterior, também mascarado. Usado pela
    tradução e pela estimativa de custo, para que as duas vejam o mesmo pedido.
    """
    out = []
    previous_masked = ""
    for src in sources:
        prot = protect(src.text, style, src.bold, src.italic)
        out.append((src, prot, Segment(src.id, prot.masked, context_before=previous_masked[-600:], kind=src.kind),
                    _needs_translation(prot.masked)))
        previous_masked = prot.masked
    return out


def translate(
    sources: list[SourceSegment],
    provider: TranslationProvider,
    glossary: Glossary,
    section: str = "",
    style: LexStyle = DEFAULT_STYLE,
    cache: TranslationCache | None = None,
    max_chars: int = 6000,
    max_segments: int = 20,
) -> TranslationRun:
    protected: dict[str, Protected] = {}
    results: dict[str, SegmentResult] = {}
    pending: list[Segment] = []
    calls: list[CallRecord] = []
    system = build_request([], glossary, section).system_prompt

    for src, prot, seg, needed in prepare_segments(sources, style):
        protected[src.id] = prot
        base = SegmentResult(src.id, src.text, prot.masked, SegmentStatus.NOT_NEEDED)
        if not needed:
            base.text = src.text
            results[src.id] = base
            continue
        if cache is not None:
            hit = cache.get(cache_key(provider.name, provider.model, system, seg, section, glossary))
            # Uma tradução em cache que não passa nas regras atuais é reenviada.
            if hit is not None and _accept(base, hit, prot, SegmentStatus.CACHED, provider, glossary):
                results[src.id] = base
                continue
            base = SegmentResult(src.id, src.text, prot.masked, SegmentStatus.NOT_NEEDED)
        results[src.id] = base
        pending.append(seg)

    failures = {"consecutive": 0, "last": ""}

    def call(batch: list[Segment]) -> dict[str, str] | None:
        if failures["consecutive"] >= MAX_CONSECUTIVE_FAILURES:
            for s in batch:
                results[s.id].status = SegmentStatus.FAILED
                results[s.id].problems = [f"não enviado: provedor falhou repetidamente ({failures['last']})"]
            return None
        request = build_request(batch, glossary, section)
        try:
            out = provider.translate_batch(request)
        except ProviderRefusal as exc:
            calls.append(CallRecord(provider.name, provider.model, len(batch), Usage(), f"recusa: {exc}"))
            for s in batch:
                results[s.id].status, results[s.id].problems = SegmentStatus.FAILED, [str(exc)]
            return None
        except ProviderError as exc:
            calls.append(CallRecord(provider.name, provider.model, len(batch), Usage(), str(exc)))
            failures["consecutive"] += 1
            failures["last"] = str(exc)
            return None
        failures["consecutive"] = 0
        calls.append(CallRecord(out.provider, out.model, len(batch), out.usage))
        for s in batch:
            results[s.id].provider, results[s.id].model = out.provider, out.model
        return out.translations

    retry_single: list[Segment] = []
    for batch in _batches(pending, max_chars, max_segments):
        got = call(batch)
        if got is None and all(results[s.id].status != SegmentStatus.FAILED for s in batch):
            got = call(batch)  # uma nova tentativa para JSON malformado ou falha transitória
        for seg in batch:
            res = results[seg.id]
            if res.status == SegmentStatus.FAILED:
                continue
            if got is None or seg.id not in got:
                retry_single.append(seg)
                continue
            if not _accept(res, got[seg.id], protected[seg.id], SegmentStatus.TRANSLATED, provider, glossary):
                retry_single.append(seg)
            elif cache is not None:
                cache.put(cache_key(provider.name, provider.model, system, seg, section, glossary),
                          provider.name, provider.model, got[seg.id])

    for seg in retry_single:
        res = results[seg.id]
        got = call([seg])
        if res.status == SegmentStatus.FAILED:
            continue
        if got is None or seg.id not in got:
            res.status = SegmentStatus.FAILED
            res.problems.append("o provedor não devolveu tradução para este segmento")
            continue
        if _accept(res, got[seg.id], protected[seg.id], SegmentStatus.TRANSLATED, provider, glossary):
            res.warnings.append("aceito na segunda tentativa")
            if cache is not None:
                cache.put(cache_key(provider.name, provider.model, system, seg, section, glossary),
                          provider.name, provider.model, got[seg.id])

    return TranslationRun([results[s.id] for s in sources], calls)


def _accept(res: SegmentResult, masked_translation: str, prot: Protected, ok_status: SegmentStatus,
            provider: TranslationProvider, glossary: Glossary | None = None) -> bool:
    res.raw_translation = masked_translation
    try:
        restored = restore(masked_translation, prot)
    except GuardViolation as exc:
        res.status, res.problems, res.text = SegmentStatus.NEEDS_REVIEW, exc.problems, None
        return False
    res.status, res.text, res.problems = ok_status, restored.text, []
    res.warnings = list(restored.warnings)
    if glossary is not None:
        res.warnings += glossary.check(prot.original, restored.text)
    ratio = len(restored.text) / max(1, len(prot.original))
    lo, hi = LENGTH_RATIO_RANGE
    if not lo <= ratio <= hi:
        res.warnings.append(f"razão de comprimento PT/EN = {ratio:.2f}: conferir omissão ou acréscimo")
    if not res.provider:
        res.provider, res.model = provider.name, provider.model
    return True

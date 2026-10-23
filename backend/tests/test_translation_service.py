"""Serviço de tradução: proteção, lotes, cache, novas tentativas e estados finais."""

import re

from app.chess.notation.lexer import LexStyle
from app.translation.cache import TranslationCache
from app.translation.glossary import Glossary
from app.translation.provider import BatchResult, ProviderError, ProviderRefusal, Usage
from app.translation.providers.fake import FakeProvider
from app.translation.service import SegmentStatus, SourceSegment, translate

BOOK = LexStyle(numbers_without_dot=True, abbreviated_pawn_captures=True)
SOURCES = [
    SourceSegment("p1", "The only winning try is 1 ♔d4! ♔b5 2 ♔c3, as the king on e5 is too far."),
    SourceSegment("p2", "1 ♔d3 ♔d7 2 e4! f4"),  # só notação: não é enviado
    SourceSegment("p3", "Black is in zugzwang △ and must give way."),
]
GLOSSARY = Glossary.load()


def toy_translate(masked: str) -> str:
    """Tradução de brinquedo que preserva marcadores, casas e símbolos."""
    return (masked.replace("The only winning try is", "A única tentativa de vitória é")
            .replace("as the king on", "pois o rei em").replace("is too far", "está longe demais")
            .replace("Black is in zugzwang", "As pretas estão em zugzwang")
            .replace("and must give way", "e precisam ceder"))


def test_end_to_end_with_notation_restored_exactly():
    prov = FakeProvider(toy_translate)
    run = translate(SOURCES, prov, GLOSSARY, style=BOOK)
    r1, r2, r3 = run.results
    assert r1.status == SegmentStatus.TRANSLATED
    assert r1.text == "A única tentativa de vitória é 1 ♔d4! ♔b5 2 ♔c3, pois o rei em e5 está longe demais."
    assert r2.status == SegmentStatus.NOT_NEEDED and r2.text == SOURCES[1].text
    assert r3.text == "As pretas estão em zugzwang △ e precisam ceder."
    sent = [s.text for call in prov.calls for s in call.segments]
    assert all("♔" not in t for t in sent) and len(sent) == 2


def test_context_before_is_masked_previous_segment():
    prov = FakeProvider(toy_translate)
    translate(SOURCES, prov, GLOSSARY, style=BOOK)
    seg3 = prov.calls[0].segments[1]
    assert seg3.id == "p3" and seg3.context_before == "⟦1⟧"  # p2 inteiro é notação, mascarado


def test_broken_placeholder_is_retried_then_sent_to_review():
    prov = FakeProvider(lambda s: re.sub(r"⟦\d+⟧", "", s))  # o "tradutor" perde a notação
    run = translate(SOURCES[:1], prov, GLOSSARY, style=BOOK)
    r = run.results[0]
    assert r.status == SegmentStatus.NEEDS_REVIEW and r.text is None
    assert any("ausente" in p for p in r.problems) and r.raw_translation is not None
    assert len(prov.calls) == 2  # lote + uma nova tentativa individual


def test_changed_square_or_symbol_is_rejected():
    prov = FakeProvider(lambda s: s.replace("e5", "e4"))
    assert translate(SOURCES[:1], prov, GLOSSARY, style=BOOK).results[0].status == SegmentStatus.NEEDS_REVIEW
    prov = FakeProvider(lambda s: s.replace("△", ""))
    assert translate(SOURCES[2:], prov, GLOSSARY, style=BOOK).results[0].status == SegmentStatus.NEEDS_REVIEW


def test_cache_avoids_paying_twice():
    cache = TranslationCache()
    first = FakeProvider(toy_translate)
    translate(SOURCES, first, GLOSSARY, style=BOOK, cache=cache)
    second = FakeProvider(toy_translate)
    run = translate(SOURCES, second, GLOSSARY, style=BOOK, cache=cache)
    assert second.calls == [] and run.counts() == {"cached": 2, "not_needed": 1}


def test_batches_respect_limits():
    many = [SourceSegment(f"s{i}", f"Paragraph number {i} about the king on e5.") for i in range(7)]
    prov = FakeProvider(toy_translate)
    translate(many, prov, GLOSSARY, max_segments=3)
    assert [len(c.segments) for c in prov.calls] == [3, 3, 1]


class FailingProvider(FakeProvider):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def translate_batch(self, request):
        self.calls.append(request)
        raise self.error


def test_repeated_provider_errors_stop_sending():
    many = [SourceSegment(f"s{i}", f"Paragraph {i} about the king.") for i in range(30)]
    prov = FailingProvider(ProviderError("401: chave inválida"))
    run = translate(many, prov, GLOSSARY, max_segments=5)
    assert len(prov.calls) == 2  # duas falhas seguidas e o envio para
    assert all(r.status == SegmentStatus.FAILED for r in run.results)
    assert "401" in run.results[-1].problems[0]


def test_refusal_marks_batch_failed_without_retry():
    prov = FailingProvider(ProviderRefusal("recusa"))
    run = translate(SOURCES[:1], prov, GLOSSARY, style=BOOK)
    assert run.results[0].status == SegmentStatus.FAILED and len(prov.calls) == 1


class PartialProvider(FakeProvider):
    """Na primeira chamada devolve só um dos dois segmentos."""

    def translate_batch(self, request):
        self.calls.append(request)
        ids = [s.id for s in request.segments]
        keep = ids if len(self.calls) > 1 else ids[:1]
        return BatchResult({s.id: toy_translate(s.text) for s in request.segments if s.id in keep},
                           "fake", "fake-1", Usage(10, 5, 0))


def test_missing_id_is_retried_individually():
    prov = PartialProvider()
    run = translate([SOURCES[0], SOURCES[2]], prov, GLOSSARY, style=BOOK)
    assert [r.status for r in run.results] == [SegmentStatus.TRANSLATED] * 2
    assert "segunda tentativa" in run.results[1].warnings[0]
    assert run.tokens()["input"] == 20


def test_length_ratio_warning():
    prov = FakeProvider(lambda s: "Curto.")
    run = translate([SourceSegment("x", "A long paragraph about opposition and corresponding squares in endings.")],
                    prov, GLOSSARY)
    assert any("razão de comprimento" in w for w in run.results[0].warnings)


def test_cached_translation_failing_current_rules_is_resent():
    from app.translation.guard import protect
    from app.translation.prompt import build_request, cache_key
    from app.translation.provider import Segment

    cache = TranslationCache()
    text = "deflection: 2-29, 5-15 diagonal checks: 12-33"
    seg = Segment("i", protect(text).masked)
    system = build_request([], GLOSSARY).system_prompt
    # Entrada gravada antes de a divergência de números passar a bloquear.
    cache.put(cache_key("fake", "fake-1", system, seg, ""), "fake", "fake-1", "desvio: 2-29, 5-15, 2- xeques: 12-33")
    good = FakeProvider(lambda s: s.replace("deflection", "desvio").replace("diagonal checks", "xeques diagonais"))
    run = translate([SourceSegment("i", text)], good, GLOSSARY, cache=cache)
    assert len(good.calls) == 1 and run.results[0].status == SegmentStatus.TRANSLATED
    assert run.results[0].text == "desvio: 2-29, 5-15 xeques diagonais: 12-33"

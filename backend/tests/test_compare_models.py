"""Métricas da comparação de modelos."""

from scripts.compare_models import metrics


def test_metrics_count_states_glossary_and_catalog_cost():
    run = {"summary": {"model": "x/m", "calls": 2, "call_errors": [], "tokens": {"input": 1000, "output": 500}},
           "segments": [
               {"id": "a", "status": "translated", "source": "abcd", "text": "abcde",
                "warnings": ["glossario_evitar: 'deflection' traduzido como 'atração' (preferido: 'desvio')"]},
               {"id": "b", "status": "translated", "source": "ab", "text": "ab",
                "warnings": ["aceito na segunda tentativa", "glossario_ausente: 'move' sem 'lance'"]},
               {"id": "c", "status": "needs_review", "source": "ab", "text": None, "warnings": []},
               {"id": "d", "status": "not_needed", "source": "1.e4", "text": "1.e4", "warnings": []},
           ]}
    prices = {"x/m": {"promptTextTokens": "0.000001", "completionTextTokens": "0.000004"}}
    m = metrics(run, prices)
    assert (m["sent"], m["accepted"], m["needs_review"], m["second_try"]) == (3, 2, 1, 1)
    assert (m["glossary_avoid"], m["glossary_missing"]) == (1, 1)
    assert m["ratio_mean"] == round((5 / 4 + 1) / 2, 2)
    assert m["cost_pollen"] == round(1000 * 0.000001 + 500 * 0.000004, 4)

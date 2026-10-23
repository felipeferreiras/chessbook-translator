"""Instruções e carga de cada chamada de tradução.

O mesmo prompt é usado por todos os provedores, para que a qualidade possa ser
comparada. As instruções fixas (regras + glossário completo) ficam no início e
não mudam entre chamadas, o que favorece o cache de prompt dos provedores.
"""

from __future__ import annotations

import hashlib
import json

from .glossary import Glossary
from .provider import Segment, TranslationRequest

PROMPT_VERSION = "2026-10-23.2"

_RULES = """\
Você é tradutor técnico especializado em literatura de xadrez. Traduza do inglês
para o português brasileiro, com linguagem natural e tecnicamente precisa.

Regras obrigatórias:
1. Traduza o sentido completo do autor: argumentos, avaliações, relações de
   causa, condições e nuances. Não resuma, não omita, não acrescente explicações.
2. Os marcadores ⟦1⟧, ⟦2⟧... substituem lances e sequências de lances. Copie
   cada marcador exatamente uma vez, sem alterá-lo, traduzi-lo ou separá-lo.
   Você pode mudá-lo de lugar dentro da frase quando a sintaxe do português pedir.
3. Não altere casas do tabuleiro (e4, d6, h8), números de lance, números de
   diagrama (1-21), números de exercício (1/6), datas e anos.
4. Preserve símbolos de avaliação e anotação (+−, −+, ±, ∓, ⩲, ⩱, =, ∞, ⊙, △, □,
   ⇆, !, ?, !!, ??, !?, ?!) exatamente como aparecem.
5. Não traduza nomes de jogadores nem títulos de obras ("Dvoretsky's Endgame
   Manual" permanece como está). Para cidades, países e competições, use a
   forma portuguesa consagrada quando existir (Hamburg → Hamburgo, Moscow →
   Moscou, Czechoslovakia → Tchecoslováquia, USSR → URSS); sem forma
   consagrada, mantenha o original. Abreviações de competição: "ol" →
   "ol." (Olimpíada), "ch" → "camp." (campeonato), "chsf" → "semif. camp.",
   "zt" → "torneio zonal", "izt" → "interzonal".
6. "White"/"Black" como lados são "as brancas"/"as pretas" (concordância no
   plural). "diagram" é "diagrama".
7. Use o glossário como preferência, considerando o contexto de cada ocorrência;
   não é substituição cega.
8. O campo "context_before" é só contexto: não o traduza nem o inclua na saída.
9. Quebras de linha ("\n") dentro de um segmento separam itens de lista,
   entradas de índice ou de sumário: preserve-as nos mesmos pontos.
10. <b>…</b> marca negrito e <i>…</i> marca itálico do original. Coloque cada
   par em volta das palavras correspondentes da tradução, na mesma linha; não
   acrescente, remova nem use outras marcas.
11. Responda apenas com o JSON pedido: {"translations": [{"id": ..., "text": ...}]},
   uma entrada por segmento, com o mesmo "id".
"""


def system_prompt(glossary: Glossary) -> str:
    return _RULES + "\nGlossário (termo → tradução preferencial):\n" + "\n".join(glossary.as_prompt_lines()) + "\n"


def build_request(segments: list[Segment], glossary: Glossary, section: str = "") -> TranslationRequest:
    payload = {
        "section": section,
        "segments": [
            {"id": s.id, "kind": s.kind, "text": s.text, **({"context_before": s.context_before} if s.context_before else {})}
            for s in segments
        ],
    }
    return TranslationRequest(
        segments=segments,
        system_prompt=system_prompt(glossary),
        user_payload=json.dumps(payload, ensure_ascii=False, indent=1),
    )


def cache_key(provider: str, model: str, system: str, segment: Segment, section: str) -> str:
    h = hashlib.sha256()
    for part in (PROMPT_VERSION, provider, model, system, section, segment.kind, segment.context_before, segment.text):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()

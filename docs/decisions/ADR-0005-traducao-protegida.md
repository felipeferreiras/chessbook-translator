# ADR-0005 — Tradução com notação protegida e provedores intercambiáveis

**Estado:** aceito; `guard` implementado, provedores na Fase 4 · **Data:** 2026-10-22

## Decisão
* Antes da tradução, cada trecho de notação é trocado por um marcador opaco
  (`⟦n⟧`). Na volta, exige-se cada marcador exatamente uma vez e o mesmo
  multiconjunto de casas citadas na prosa; caso contrário, o segmento é
  rejeitado para revisão (`app/translation/guard.py`).
* Interface `TranslationProvider.translate(segment, context, glossary,
  instructions) -> TranslationResult` com adaptadores: Claude API (SDK oficial
  `anthropic`), llama.cpp (servidor local) e `FakeProvider` (testes).
* Contexto controlado: segmento atual, até N segmentos anteriores já
  traduzidos, título do capítulo/seção, termos do glossário que ocorrem no
  segmento, instruções editoriais fixas (no prefixo, para aproveitar cache).
* Lotes por capítulo; livro inteiro nunca numa chamada só. Para lotes grandes,
  Message Batches API (assíncrona, metade do custo) quando o provedor for a
  Claude API.
* Cada chamada grava provedor, modelo, hash do prompt e uso de tokens. Sem
  dados de preço confiáveis, o custo fica "não estimado", nunca inventado.

## Consequências
O tradutor nunca altera um lance; em troca, a frase traduzida precisa acomodar
marcadores, o que será medido no conjunto de avaliação da Fase 4.

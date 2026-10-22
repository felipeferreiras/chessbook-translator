# ADR-0005 — Tradução com notação protegida e provedores intercambiáveis

**Estado:** aceito e implementado (guard, provedores Claude/ChatGPT/Gemini, cache) · **Data:** 2026-10-22

## Decisão
* Antes da tradução, cada trecho de notação é trocado por um marcador opaco
  (`⟦n⟧`). Na volta, exige-se cada marcador exatamente uma vez e o mesmo
  multiconjunto de casas citadas na prosa; caso contrário, o segmento é
  rejeitado para revisão (`app/translation/guard.py`).
* Interface `TranslationProvider.translate_batch(request) -> BatchResult` com
  adaptadores para Claude (`anthropic`), ChatGPT (`openai`, Responses API) e
  Gemini (`google-genai`), todos com saída em JSON Schema e o mesmo prompt,
  além de `FakeProvider` (testes). llama.cpp continua previsto.
* Escolha do provedor por variável de ambiente; provedores remotos exigem
  `CHESSBOOK_PRIVACY_MODE=remote_allowed`. Para OpenAI e Gemini o modelo é
  obrigatório na configuração (nenhum nome fixado no código).
* Decisão do usuário (2026-10-22): serviço externo, com suporte a Claude,
  ChatGPT e Gemini. Detalhes em `docs/architecture/02-traducao.md`.
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

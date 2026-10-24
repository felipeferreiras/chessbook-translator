# Motores de tradução e previsão de custo

Data: 2026-10-24. Pedido do usuário: configurar todos os motores testados e
deixar o usuário escolher, com previsão de custo de cada um, antes de iniciar
a tradução.

## Motores (todos pela Pollinations, uma chave)

| Motor | Modelo | Situação |
|---|---|---|
| Claude Sonnet 5.5 | `anthropic/claude-sonnet-5.5` | recomendado (comparação da Fase 4) |
| Claude Opus 5.5 | `anthropic/claude-opus-5.5` | disponível |
| Gemini 3.8 Flash | `google/gemini-3.8-flash` | disponível (escolha da Fase 2) |
| GPT-5.5 | `openai/gpt-5.5` | disponível |
| GPT-5.4 Nano | `openai/gpt-5.4-nano` | disponível |
| Qwen 3.8 27B | `qwen/qwen3.8-27b` | experimental (pesos abertos; lento e instável em lotes grandes) |

Preços: catálogo da Pollinations (`GET /text/models`), lido na hora e guardado
por um dia; sem rede, vale a tabela gravada em 2026-10-24, e a interface diz
qual fonte foi usada.

## Como a previsão é feita

1. Monta exatamente os lotes que a tradução enviaria: mesma preparação dos
   segmentos (`prepare_segments`), mesmas seções, mesmo agrupamento e o mesmo
   pedido (`build_request`). Segmentos só de notação e os já em cache não
   entram.
2. Conta caracteres de entrada (instruções + carga) e da saída esperada
   (texto mascarado × 1,05 + formato JSON), a 3,6 caracteres por token.
3. Corrige pelo fator medido de cada modelo (tokens reais / estimados):

| Motor | Entrada | Saída | Faixa | Base |
|---|---|---|---|---|
| Sonnet 5.5 | 1,89 | 3,04 | ±25 % | rodada das p. 21 e 438 com o prompt atual |
| Opus 5.5 | 1,89 | 2,43 | ±25 % | idem |
| Gemini 3.8 Flash | 1,76 | 5,3 | ±45 % | três rodadas; a saída variou de 4,1× a 7,2× (raciocínio) |
| GPT-5.5 | 1,8 | 2,33 | ±35 % | rodada da Fase 2 |
| GPT-5.4 Nano | 1,8 | 1,30 | ±35 % | amostra de 16 páginas da Fase 2 |
| Qwen 3.8 27B | 1,4 | 14,1 | ±60 % | uma rodada (com falhas) |

A diferença grande entre caracteres e tokens vem do tokenizador (português
com acentos, figurinas) e do formato de resposta; o raciocínio cobrado como
saída explica os fatores altos do Gemini e do Qwen.

## Conferência

* Gemini, 16 páginas: previsto 0,25 (0,14–0,36); medido em outubro 0,20.
* Sonnet, p. 13 traduzida pela interface: previsto **0,037**, gasto real
  **0,035** pollen (13/13 segmentos).

## Livro inteiro (441 páginas, 5.561 segmentos a enviar, 530 chamadas)

| Motor | Previsão (pollen) | Tempo estimado |
|---|---|---|
| Sonnet 5.5 | 8,3 (6,3–10,4) | 2,5 h |
| Opus 5.5 | 14,4 (10,8–18,0) | 2,6 h |
| Gemini 3.8 Flash | 6,2 (3,4–9,0) | 5,9 h |
| GPT-5.5 | 19,4 (12,6–26,2) | 5,9 h |
| GPT-5.4 Nano | 0,56 (0,36–0,75) | 1,9 h |
| Qwen 3.8 27B | 4,7 (1,9–7,6) + novas tentativas | 20 h |

Correção em relação ao relatório da Fase 4: lá, a estimativa para o livro
com Sonnet foi dada como 5–6 pollen pela proporção da amostra; a previsão
calibrada é 8,3.

## Tarefas de tradução

Iniciadas pela aba **Traduzir**: o usuário escolhe as páginas, vê a tabela com
todos os motores, marca um, define um **teto de gasto** (sugerido: topo da
faixa + 20 %) e confirma. A tarefa traduz seção por seção, grava cada seção
no projeto ao terminar, soma o custo real e **para se passar do teto**. Pode
ser cancelada entre seções. Uma edição humana nunca é sobrescrita por uma
tradução automática.

Ids estáveis: os segmentos passaram a ser `p{página}-{posição na página}`,
iguais em qualquer seleção de páginas (antes dependiam das páginas pedidas).
Resultados antigos de `translate_pages` não são compatíveis com a montagem
atual e precisam ser gerados de novo.

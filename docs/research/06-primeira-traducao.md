# Primeira tradução real: GPT-5.4 Nano pela Pollinations

Data: 2026-10-23. Modelo `openai/gpt-5.4-nano` via `gen.pollinations.ai`
(Chat Completions, saída em JSON Schema). Livro de amostra: as 16 páginas
definidas em `05-amostra-dvoretsky.md`. Os textos traduzidos ficam fora do
repositório; aqui só há métricas e a descrição dos problemas.

## Números

| Métrica | Valor |
|---|---|
| Segmentos | 295 (208 com prosa, 87 só notação, não enviados) |
| Traduzidos e aceitos | 208 de 208 |
| Rejeitados pela proteção de notação | 0 após nova tentativa (1 segmento precisou de uma) |
| Falhas do provedor | 0 |
| Chamadas | 14 lotes, cerca de 3 min |
| Tokens (todas as rodadas) | 44.935 de entrada, 14.555 de saída |
| Custo pelo preço do catálogo | ≈ 0,02 pollen no total; ≈ 0,0012 pollen por página |
| Estimativa grosseira para 441 páginas | ≈ 0,5 pollen (páginas variam; não medido) |

Preços lidos em `GET /text/models` em 2026-10-23: entrada 0,15, entrada em
cache 0,015 e saída 0,9375 pollen por milhão de tokens.

## O que a revisão encontrou

Verificações automáticas: nenhum inglês residual detectado por lista de
palavras; os 34 segmentos devolvidos idênticos ao original são cabeçalhos de
partida (nomes de jogadores, cidades, anos), o que está correto.

Leitura humana (página 21 inteira e casos sinalizados):

* **Notação:** 100 % restaurada, inclusive figurinas, ⊙, △, +− e variantes.
* **Qualidade geral:** prosa natural e fiel; termos como "casas minadas",
  "zugzwang recíproco", "casas correspondentes" e "final de peões" corretos.
* **Problemas pequenos:** nome de cidade traduzido ("Hamburgo"), contra a
  regra; "movimento de espera" em vez de "lance de espera" (corrigido no
  glossário); uma nuance acrescentada ("e ainda assim"); um singular virou
  plural; pontuação dupla após anotação ("!.").
* **Problema grave (corrigido na regra):** no índice (p. 438) o modelo inseriu
  um número a mais entre as referências de diagrama. A divergência de números
  era só um aviso e o segmento tinha sido aceito; agora **bloqueia** a
  aceitação, e traduções em cache que não passam na regra atual são reenviadas.
* **Problema não detectável automaticamente:** no mesmo índice, ao reenviar,
  o modelo trocou "deflection" (desvio) por "atração", que é o termo de outra
  técnica (*decoy*), e deixou o termo inglês entre parênteses. Em listas densas
  de terminologia o modelo pequeno não seguiu o glossário.
* **Sumário (p. 5):** o conteúdo foi traduzido, mas as tabulações viraram
  espaços simples; a reconstrução do layout terá de tratar sumários como tabela.

## Conclusões

1. O fluxo funciona de ponta a ponta com um provedor real, e a proteção da
   notação se comportou como projetado.
2. O GPT-5.4 Nano é barato e bom para prosa, mas erra terminologia em listas e
   índices. Vale comparar um modelo maior nas páginas 21 e 438 antes de
   traduzir o livro inteiro.
3. A revisão humana continua necessária para terminologia: nenhuma regra
   automática distingue "desvio" de "atração".

## Comparação de modelos (páginas 21 e 438)

Mesmo prompt, glossário e regras; 25 segmentos com prosa. Pedido do usuário:
comparar GPT-5.4 Nano, GPT-5.5 e Gemini 3.8 Flash (ids oficiais da
Pollinations, não as cópias `community/`).

| | GPT-5.4 Nano | GPT-5.5 | Gemini 3.8 Flash |
|---|---|---|---|
| Segmentos aceitos | 25/25 | 25/25 | 25/25 (após recarga do saldo) |
| Notação e números | intactos | intactos | intactos |
| "deflection" (desvio) | "atração" ✗ | "desvio" ✓ | "desvio" ✓ |
| "desperado" | "desgraçado" ✗ | "desperado" ✓ | "desperado" ✓ |
| Nome de cidade | traduzido ✗ | mantido ✓ | mantido ✓ |
| "barrier", "bad bishop" | "bloqueio", "mau bispo" | "barreira", "bispo ruim" | "barreira", "bispo mau" |
| Pontuação dupla "!." | não | sim ✗ | não |
| Razão de comprimento PT/EN | 1,01 | 1,01 | 1,01 |
| Preço (entrada / saída por milhão, pollen) | 0,15 / 0,94 | 3,75 / 22,5 | 0,75 / 3,75 (catálogo) |
| Custo das 2 páginas | ≈ 0,003 (estimado; p. 438 rodou em lote maior) | ≈ 0,13 (medido) | ≈ 0,036 (medido) |
| Estimativa para 441 páginas | ≈ 0,5 | ≈ 28 | ≈ 8 |

Observações:

* O GPT-5.5 acertou todos os termos em que o Nano errou nessas duas páginas.
  Ainda tem defeitos de estilo ("As pretas, a jogar, jogam…", pontuação dupla
  "!.") que a revisão deve corrigir.
* As duas rodadas mostraram um problema da extração, não da tradução:
  referências partidas em fim de linha ("1- 186") chegam assim ao tradutor.
  O Nano às vezes as junta, o GPT-5.5 as preserva. A junção deve ser feita na
  extração, de forma controlada.
* O Gemini 3.8 Flash teve a mesma qualidade terminológica do GPT-5.5 nessas
  páginas, sem a pontuação dupla, por cerca de 1/4 do custo. Gerou mais tokens
  de saída que o GPT-5.5 (7.677 contra 4.398), provavelmente por raciocínio
  contabilizado como saída.
* Com duas páginas, a comparação é indicativa, não estatística.

## Amostra completa com Gemini 3.8 Flash (modelo escolhido)

Rodada em 2026-10-23, já com a junção de linhas corrigida na extração (ver
abaixo). Mesmas 16 páginas.

| Métrica | GPT-5.4 Nano | Gemini 3.8 Flash |
|---|---|---|
| Segmentos com prosa aceitos | 208/208 | 208/208 |
| Falhas / revisões | 0 / 0 | 0 / 0 |
| Avisos | 3 | 0 |
| Inglês residual (lista de palavras) | 0 | 0 |
| "deflection" → "atração" | sim ✗ | não |
| Nomes e locais mantidos | parcial | todos |
| Razão de comprimento PT/EN (média) | ~1,0 | 1,02 (0,89–1,16) |
| Chamadas / tempo | 14 / ~3 min | 12 / ~7,5 min |
| Tokens entrada / saída | 40.504 / 13.101 | 41.287 / 46.291 |
| Custo pelo catálogo | ≈ 0,018 pollen | ≈ 0,20 pollen |

Leitura humana de parágrafos das páginas 13, 22, 201, 380 e 405: tradução fiel
e natural, terminologia correta ("ruptura c5-c6", "casas correspondentes",
"lance de espera"). Ajustes de estilo encontrados: "peão passado de f" (melhor
"peão f passado"); "estão em correspondência" (melhor "são correspondentes").

Os 40 segmentos devolvidos idênticos são nomes de jogadores, locais e anos e o
índice onomástico. Decisão editorial do usuário (2026-10-23): usar a forma
portuguesa consagrada de cidades, países e competições ("Hamburgo", "Moscou",
"Tchecoslováquia") e abreviações portuguesas ("ol." , "camp."); a regra 5 do
prompt foi alterada e a amostra traduzida de novo (208/208 aceitos, 12
chamadas, 43.793 tokens de entrada e 40.666 de saída).

O Gemini gera mais tokens de saída que de entrada (raciocínio cobrado como
saída); a estimativa para o livro inteiro passa a ser ≈ 0,20 / 16 × 441 ≈
5–6 pollen, com a ressalva de que a amostra tem páginas de índice menos densas.

## Correção da extração: hífen no fim da linha

Medido no livro inteiro antes e depois de `app/extraction/lines.py`:

| | Antes | Depois |
|---|---|---|
| Referências partidas ("9- 158") | 92 | 0 |
| Palavras partidas pela hifenização ("posi- tion") | 333 | 3 (dentro da própria linha do PDF; 1 é hífen suspenso correto) |
| Lances validados | 24.581 | 24.590 |
| Ilegais | 115 | 116 (o novo é "play c2-c3", um plano antes invisível por estar partido; agora é notação protegida e vai para revisão) |

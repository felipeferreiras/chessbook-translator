# Fase 7 — o livro completo: integridade, desempenho, custo e retomada

Data: 2026-10-25. Livro: *Dvoretsky's Endgame Manual* (441 páginas), traduzido
de verdade com Claude Sonnet 5.5 pela Pollinations, com autorização do usuário
(teto de 11 pollen).

## Resultado

| | |
|---|---|
| Parágrafos traduzidos | 5527 (+ 3279 só de notação ou rótulos de diagrama, copiados sem tradução) |
| Para trabalho humano | 6: 1 recusado pela proteção (o modelo acrescentou um ano, "1990", que o original não tem) e 5 com lances desenhados como vetor |
| Custo real total | **7,06 pollen** (previsão inicial 8,33; faixa 6,25–10,42) |
| Tempo de tradução | 34 min (6,4 min sequencial até a interrupção proposital + 27,5 min em paralelo) |
| Montagem | 440/440 páginas, 5527/5527 blocos, 5,5–6 min |
| Páginas sem pendência | **428/440**; as 12 restantes têm um bloco com fonte entre 72 e 84 % (cabeçalhos de partida) |
| Notação | auditoria: em todas as 5527 traduções, cada trecho de notação está idêntico ao original; nenhum lance ausente no PDF |
| Diagramas | 1220 conferidos, nenhum alterado |
| Original | sha256 idêntico antes, durante e depois |

Amostras lidas lado a lado (prosa longa, notas com variantes, índice
remissivo, prefácio): tradução fiel, natural, sem omissões; termos técnicos
corretos ("zugzwang recíproco", "casas correspondentes", "fortaleza
inexpugnável", "ala da dama"). Duas escolhas de terminologia para o revisor:
"Undermining" → "Minagem" e "Outflanking" → "Rodeio".

## Integridade

* **Sincronização do projeto** (`scripts.project sync`, `ProjectStore.sync_segments`).
  O projeto real fora criado antes das correções da Fase 5 (8793 segmentos,
  contra 8812 da extração atual): traduzi-lo assim faria a montagem recusar o
  resultado. A sincronização casa cada segmento novo com um antigo **pelo
  texto de origem** (mesmo id, senão mesma página), renomeia levando versões,
  histórico e tarefas, e só descarta a tradução se o texto protegido mudou.
  No projeto real: 8774 mantidos, 188 renomeados, 38 novos, 19 removidos (sem
  tradução). Uma recusa ou falha anterior continua marcada (bug achado e
  corrigido durante a fase).
* **Auditoria** (`scripts.project audit`, aba Qualidade → "Auditar
  integridade", 15 s no livro inteiro): original pelo sha256; segmentos ×
  extração atual; estado final de cada segmento; **notação de toda versão
  atual** conferida com `mask_edit` (inclusive edições humanas); marcadores
  sobrando; montagem cobrindo o texto atual (impressão digital do conteúdo,
  não horário — a comparação por horário perdia uma edição no mesmo segundo),
  mesmo número de páginas e sem pendências.

### Defeitos que só o livro real mostrou

| Defeito | Correção |
|---|---|
| Rótulos de diagrama ("W? Play") traduzidos de forma inconsistente — "As brancas?", "Lance das brancas?" e até "B?", que **muda o sentido** | marcas do diagrama (`W`, `B`, `W?`, `Play`…) não vão mais ao motor; 41 traduções descartadas na sincronização |
| O rótulo ao lado do tabuleiro não era apagado (a área de redação era cortada só na vertical e ficava vazia) e a conferência não percebia (olhava só a área apagada) | corte pela lateral quando a faixa vertical some; a sobra do original é conferida na área inteira de cada trecho, fora dos tabuleiros |
| Um ponto final na borda da caixa escapava da redação quando um tabuleiro invadia o canto | corte vertical preferido (continua tocando todas as letras da linha); folga lateral de 0,6 pt |
| Cabeçalhos de partida com abreviações expandidas ("USSR ch tt" → "camp. da URSS por equipes") reduziam a fonte | regra do prompt (versão 2026-10-25.1): abreviações curtas, cabeçalho com no máximo o tamanho do original; 62 cabeçalhos retraduzidos (0,146 pollen) |
| 63 parágrafos (1,2 %) falharam porque o modelo devolveu JSON seguido de texto, ou texto antes do JSON; o disjuntor marcava o resto da seção | leitura de vários objetos JSON em sequência e pulo de preâmbulo (a proteção confere cada tradução de qualquer jeito); retraduzidos no modo "com problemas" (0,109 pollen) |

Evolução das páginas sem pendência: 378/440 na primeira montagem → 425 depois
dos rótulos e cabeçalhos → 428 depois da redação ao lado dos tabuleiros.

## Desempenho

* **Tradução em paralelo**: até `CHESSBOOK_TRANSLATION_WORKERS` seções ao
  mesmo tempo (padrão 3). Medido: 44 parágrafos/min sequencial → **192/min**
  com 3 seções (4,4×; algumas seções têm muitas chamadas curtas). A previsão
  de tempo na interface divide pelo número de seções simultâneas.
* **Teto seguro em paralelo**: o custo previsto de cada seção é **reservado**
  antes do envio; uma seção só vai se gasto real + reservas + previsto couber
  no teto. As seções já enviadas terminam (e são gravadas) mesmo depois de um
  cancelamento ou de o gasto passar do teto, então o excesso possível é de no
  máximo as seções em andamento.
* Outras etapas no livro inteiro: extração 12 s, validação de lances 11,5 s,
  auditoria 15 s, montagem 5,5–6 min (pico ~400 MB, em partes de 20 páginas).

## Custo

| Tarefa | Segmentos | Custo real | Previsto |
|---|---|---|---|
| 1 — pendentes (interrompida de propósito) | 278 | 0,491 | 8,329 (livro inteiro) |
| 2 — retomada, 3 seções em paralelo | 5291 | 6,305 | — |
| 3 — com problemas | 70 | 0,109 | 0,118 |
| 4 — cabeçalhos com a regra nova | 62 | 0,146 | 0,132 |
| 5 — p12-3, nova tentativa | 1 | 0,009 | 0,007 |
| **Total** | | **7,06** | |

No livro inteiro, o gasto real foi 0,81 × a previsão (tokens de entrada 0,82×,
de saída 0,80×). Os fatores do Sonnet foram recalibrados (entrada 1,89 → 1,56,
saída 3,04 → 2,43, incerteza ±25 % → ±20 %, 15 s por chamada).

## Retomada real

A tarefa 1 foi interrompida com `kill -9` no meio de uma seção, com 278
parágrafos gravados. Na consulta seguinte ela apareceu como `interrupted` (o
processo dela não existia mais). A retomada criou a tarefa 2 com o mesmo motor
e seleção, pulou os 278 já tratados, aproveitou do cache os lotes já pagos da
seção interrompida e terminou os 5291 restantes — já com o paralelismo novo.

## Limitações e o que fica para o revisor

* 6 parágrafos para tradução manual (lista na auditoria e no filtro "só o que
  pede atenção").
* 12 cabeçalhos de partida com fonte entre 72 e 84 %: cabem numa linha ao
  lado do diagrama só reduzidos; a revisão pode abreviar à mão.
* Os rótulos de diagrama ficam em inglês ("W?", "Play"); traduzi-los com
  segurança exige uma convenção editorial (em português, "B" seria ambíguo
  entre brancas e o "B" de *Black*).
* A aprovação humana de cada parágrafo continua por fazer (0/8812 aprovados).

# Fase 5 — layout do livro inteiro, tipografia e relatórios de qualidade

Data: 2026-10-24.

## Como foi medido

Sem gastar tradução: o provedor `pseudo` devolve a prosa alongada (≈ +25 %,
com acentos e cedilha) e mantém a notação, o que é o pior caso realista para
o layout. O livro inteiro (441 páginas) foi traduzido assim e montado com
`scripts/assemble_pdf.py`; o relatório (`relatorio.json`, também na aba
**Qualidade** da interface) foi conferido relendo o PDF gerado.

| Medida | Resultado |
|---|---|
| Blocos colocados | 5569 / 5569 |
| Páginas sem pendência | 441 / 441 |
| Texto ausente, cortado ou sobrando do original | 0 / 0 / 0 |
| Notação ausente no PDF | 0 |
| Sobreposições entre blocos | 0 |
| Diagramas conferidos / alterados | 1220 / 0 |
| Blocos para revisão de layout | 0 |
| Segmentos bloqueados (tradução manual) | 5 |
| Escala da fonte | 100 %: 3118 · 94–99 %: 1840 · 88–93 %: 593 · 85–87 %: 18 |
| Fontes substituídas | Broadway → Urbanist, Century Gothic → Urbanist (serifada e sem serifa: Liberation, métricas iguais) |
| Tempo / pico de memória / tamanho | 208 s / 402 MB / 8,0 MB |

O modo adaptativo por página (B) não foi necessário: nenhuma página precisou
de menos de 85 % da fonte nem ficou com pendência.

## O que mudou

### Memória

A primeira montagem do livro inteiro foi encerrada pelo sistema (falta de
memória): cada bloco embutia a fonte de novo, e a FreeSerif (figurinas e
símbolos do Informator) tem 3,7 MB. Agora:

* as fontes entram como subconjuntos (fontTools) com só os caracteres usados
  no texto e nas figurinas;
* o livro é montado em blocos de 20 páginas salvos em arquivos temporários e
  depois juntados, com `subset_fonts` e `garbage=4` no fim.

### Diagramas e texto na mesma caixa

* Alguns blocos do PDF continham a legenda acima e o parágrafo abaixo de um
  tabuleiro; a tradução cobria o tabuleiro. Esses blocos agora são divididos
  em volta do diagrama antes da tradução.
* Faixas da moldura extraídas à parte são reunidas ao tabuleiro, e dois
  tabuleiros empilhados no mesmo bloco são separados pelas linhas de fileira.
  Os eventos (texto e diagramas) passam a ser ordenados pelo centro
  vertical; com isso a contagem de lances validados voltou a 27.257 (a
  junção das faixas tinha reduzido para 27.006).
* Lances desenhados como vetor (glifos em curvas, sem texto) não podem ser
  reescritos com segurança: o parágrafo vira **bloqueado** e fica intacto,
  para tradução manual. São os 5 segmentos bloqueados do livro.

### Tipografia e casos de borda

* Century Gothic e Broadway substituídas por Urbanist (licença OFL, arquivo
  da licença junto às fontes); as fontes originais não foram reaproveitadas
  porque os subconjuntos do PDF não têm letras acentuadas.
* Títulos lado a lado: cada um cresce só até o ponto médio entre os dois.
* Rótulo estreito que o medidor aceitava mas a escrita recusava: volta para
  a colocação no lugar original, menor, em vez de sumir.
* Apóstrofo lido como sinal de minuto (Urbanist usa o mesmo glifo): U+2032 e
  U+2033 saem dos subconjuntos de texto.
* Fundos sombreados retirados (autorizado pelo usuário), sem tocar em texto
  nem tabuleiros: 18/18 retângulos na página de teste.

### Detecção de cortes e sobreposições

* A conferência do texto procura o começo **e** o fim de cada bloco no PDF
  gerado: um bloco cortado no final aparece como `cut_text`.
* Sobreposição medida entre todas as caixas escritas na página; um bloco
  vizinho que começa dentro do espaço entre linhas agora conta como
  obstáculo.
* O relatório traz, por página, sobreposições, cortes, fundos retirados,
  notação ausente, sobra do original, diagramas alterados e escalas.

### Interface

* Aba **Traduzir**: todos os motores numa tabela para escolher, com a
  previsão de custo de cada um (faixa de incerteza e tempo), teto de gasto,
  confirmação antes de começar, andamento e cancelamento
  (`docs/research/11-motores-custo.md`).
* Aba **Qualidade**: resumo e páginas com pendências do último relatório de
  montagem.

## Limitações conhecidas

* 5 parágrafos com lances em vetor precisam de tradução manual (aparecem como
  bloqueados na revisão).
* Validação: 89 lances ilegais contra 88 antes das mudanças de ordenação;
  o lance a mais ainda não foi investigado (ele pede revisão, não é
  convertido).
* O probe ainda confunde peão e bispo em algumas fontes; o mapa confirmado
  pelo usuário é que vale no livro de amostra.
* O teste de estresse usa tradução simulada; a montagem com a tradução real
  do livro inteiro só será medida depois que o usuário escolher o motor e
  iniciar a tradução.

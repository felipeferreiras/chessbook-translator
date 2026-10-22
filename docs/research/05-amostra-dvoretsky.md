# Livro de amostra: diagnóstico e primeira passagem de notação

Livro fornecido pelo usuário em 2026-10-22: *Dvoretsky's Endgame Manual*
(Mark Dvoretsky, 5ª ed., Russell Enterprises, 2020). O arquivo fica **fora do
repositório** (`/root/chessbook-samples/` no contêiner) e os relatórios
detalhados, que contêm trechos do livro, também. Este documento registra apenas
métricas e fatos sobre a codificação.

Reprodução:

```bash
cd backend
.venv/bin/python -m scripts.diagnose_book LIVRO.pdf /fora/do/repo/saida
```

## Diagnóstico do arquivo

| Item | Valor |
|---|---|
| Páginas | 441 (440 de 521×737 pt; capa de 215×307 pt) |
| Produtor | Calibre 5.22.1: PDF gerado a partir de um e-book, não do arquivo de gráfica |
| Texto selecionável | 440 páginas; só a capa não tem texto |
| Imagens | 3, nas páginas 1–3; **nenhuma página precisa de OCR** |
| Fontes do corpo | Times New Roman (regular, negrito, itálico), Arial, Century Gothic, Broadway (títulos de seção "Tragicomedies") |
| Fontes de xadrez | **LinaresFigurine**, **LinaresFigurineBold** (notação) e **LinaresDiagram** (tabuleiros) |
| Layout | duas colunas, caixas sombreadas, cabeçalho e número de página |

## Como o livro codifica o xadrez

### Notação: fontes figurinas que reaproveitam ASCII

Na camada de texto, `♔d6+−` aparece como `Kd6i`. A fonte LinaresFigurine
desenha `K Q R B N` como figurinas e usa letras e sinais ASCII para os símbolos
do Informator: `i`=+−, `o`=−+, `y`=±, `u`=∓, `r`=⩲, `t`=⩱, `q`=∞, `m`=⇆,
`*`=⊙ (zugzwang), `$`=△ (com a ideia), `~`=□ (lance único), `x`=×. Sem o perfil
de fonte, uma tradução trataria `i` e `o` como letras.

O mapa está em `backend/app/extraction/font_profiles.py`. Ele saiu da leitura
de cada glifo renderizado isoladamente a partir da fonte incorporada e foi
**confirmado pelo usuário em 2026-10-22** com a folha de confirmação gerada a
partir do próprio PDF.

### Diagramas: tabuleiro composto como texto

Cada diagrama tem 10 linhas na fonte LinaresDiagram: moldura, 8 fileiras e
moldura. Cada caractere é uma casa, já com a cor: `K` é rei branco em casa
clara, `I` é rei branco em casa escura, `w` e `d` são casas vazias. Isso
permite ler a posição sem visão computacional, e a cor embutida no glifo
fornece uma verificação independente.

Consequências para o layout: os diagramas são **texto**. Um bloco de diagrama
pode conter também o cabeçalho da partida ("Jogador – Jogador / Cidade ano"),
então a exclusão do diagrama no momento de apagar e reescrever texto tem de ser
feita **por trecho de fonte**, não por bloco.

### Convenções tipográficas encontradas

| Convenção | Exemplo (construído) | Tratamento |
|---|---|---|
| Número de lance sem ponto | `2 ♔e4 ♔c4` | `LexStyle.numbers_without_dot`, detectado no livro inteiro (21.813 ocorrências × 23 com ponto) |
| Captura abreviada de peão | `hg`, `fe` | `LexStyle.abbreviated_pawn_captures` (1.228 ocorrências); só colunas vizinhas e dentro de notação |
| Linha principal em negrito | variantes em fonte normal | `main_mask`: variantes partem da linha principal e não a alteram |
| Casa de destino alternativa | `♕b5(c2)?` = ♕b5 ou ♕c2 | átomo `ALT_DEST`, validado como alternativa |
| Ideia após △ | `△ ♖b8+, ♖b7+` | lances marcados como ideia, sem contexto |
| Rota de peça | `♔d6-c7` | reconhecida como algébrica longa; quando é rota, a validação falha e o lance vai para revisão |
| Parênteses de prosa com lances | `(but not 2 ♔f6? …)` | ao fechar, volta à linha anterior |
| Rótulos do diagrama | `1-21`, `W`, `B?`, `1/6` | número, vez de jogar, exercício e número do exercício |

### Defeitos encontrados no próprio livro

A verificação de cor das casas encontrou peças compostas com o glifo de fundo
errado: o rei preto em d7 no diagrama 1-1 e em e6 no 1-13 usam o glifo de
"casa escura" numa casa clara. Visualmente, o original mostra a casa hachurada
indevidamente. A peça é inequívoca, então isso é registrado como defeito
tipográfico, não como erro de leitura. Casas vazias com cor trocada, ou mais de
duas divergências, reprovam a leitura.

## Identificação automática de glifos: resultado

| Método | Resultado neste livro |
|---|---|
| Recorte da página renderizada | **Falhou**: as caixas de caractere invadem os vizinhos e o fundo sombreado; pontuações entre 0,2 e 0,3 |
| Glifo isolado da fonte incorporada (cmap reconstruído do `ToUnicode`) | Funciona e gera imagens limpas para a confirmação humana |
| Classificação automática dos glifos isolados contra fontes livres | **Não confiável**: acerta ♘, ♖ e ♕ com margem, mas confunde ♔ branco com preto e toma dígitos por peças |

Conclusão: para fontes de editoras, o mapa precisa de confirmação humana. Uma
vez confirmado, vale para todos os livros com a mesma fonte, o que é comum em
editoras que usam as mesmas famílias.

## Passagem de notação no livro inteiro

Resultado final, após as correções descritas abaixo (2026-10-22):

| Métrica | Valor |
|---|---|
| Regiões de texto | 9.656 |
| Diagramas | 1.199 |
| Diagramas lidos sem erro | 1.171 (97,7 %) |
| Diagramas com vez de jogar identificada | 1.156 |
| Lances reconhecidos | 45.447 |
| Validados contra uma posição | 24.581 (54,1 %) |
| Sem contexto (preservados, não validados) | 20.751 |
| Ilegais (vão para revisão) | 115 (0,25 %) |
| Ambíguos aceitos | 0 |
| Glifos sem mapa | 0 |
| Tempo | cerca de 9 s para o livro inteiro |

Todos os lances validados dependem de **FEN proposta** (lida do diagrama, ainda
não confirmada). O perfil de fonte foi confirmado depois desta medição. Os
lances continuam marcados para revisão até a confirmação das posições.

Taxa de validação por faixa de páginas: 64 %, 65 %, 58 %, 60 %, 54 %, 71 %, 73 %,
31 % e 24 % (blocos de 50 páginas). A queda no final ocorre na seção de
**soluções dos exercícios**, que cita a posição pelo número do exercício
("9/21.") sem repetir o diagrama.

### Correções feitas a partir de evidência do livro

| Rodada | Problema encontrado | Correção | Efeito |
|---|---|---|---|
| 1 | — | primeira passagem (pp. 15–40) | 46,6 % validados, 8 ilegais |
| 2 | `(c2)` lido como lance de peão; variante aberta no fim de um segmento contaminava a linha principal; refutação ligada à linha errada | `ALT_DEST`, pilha de parênteses por profundidade, parênteses de prosa | 56,0 %, 4 ilegais |
| 3 | rótulos "W" lidos como parte do diagrama (caixa do bloco incluía o cabeçalho) | caixa só do tabuleiro | 60,6 % |
| 4 | ramo ambíguo entre a variante anterior e a linha principal | simulação nas duas linhas; escolha só se uma for inteiramente legal | 60,8 % |
| 5 | (livro inteiro) numeração do diagrama perdida após parágrafo só de prosa | propagação do estado "posição fresca, numeração desconhecida" | 30,1 % → 54,0 % |
| 6 | lances após △ tratados como sequência; empate entre ramos decidido cedo demais | modo ideia; alternativa mantida até um segmento posterior desempatar | 159 → 115 ilegais |

### Os ilegais

Amostra aleatória de 16 dos ilegais, classificada manualmente:

* **10 legítimos**: o autor descreve uma posição modificada ("com o rei ainda
  em g3…", "se o rei estivesse em a7…"), lances impossíveis ("as Black cannot
  play…"), planos ou rotas (`g2-g3`, `♔d6-c7`) e configurações-alvo
  (`♘f4, ♗d5, ♔g2`).
* **6 não classificados** sem análise mais profunda; podem ser hipóteses do
  autor ou limites das heurísticas de ramificação.

Nenhum ilegal foi corrigido ou aceito: todos vão para revisão.

## Páginas da amostra da POC

16 páginas (numeração do PDF), escolhidas para cobrir os casos do livro:

| Página | Por quê |
|---|---|
| 1 | capa: página só de imagem |
| 5 | sumário: colunas alinhadas com tabulação |
| 13 | prefácio: prosa contínua sem notação |
| 15 | início do capítulo 1; diagrama esquemático com marcas × e defeito tipográfico |
| 21 | página típica: duas colunas, caixa sombreada, linha principal em negrito, cabeçalhos de partida, título "Tragicomedies" |
| 22 | exercícios (`W?`, `B?`, `1/6`), diagrama sem reis, rótulos de casa no diagrama |
| 62 | análise densa com ramificação decidida por legalidade |
| 117 | ideias e rotas (`△ ♔d6-c7`) |
| 201 | fragmento de partida com numeração real (5...♖a6 6 ♖d7+) |
| 209 | página com fontes incomuns (Cambria/Calibri) |
| 256 | início de capítulo no meio do livro |
| 355 | página com muitos diagramas |
| 380 | análise longa com baixa taxa de validação (teste de estresse) |
| 405 | seção de soluções (referência a exercícios pelo número) |
| 430 | índice de jogadores (lista em várias colunas) |
| 438 | índice de técnicas |

O livro não tem páginas digitalizadas; o OCR não é exercitado por esta amostra.
Se for necessário, uma página pode ser rasterizada para simular esse caso.

## Implicações para as próximas etapas

* **Fonte de saída:** o corpo usa Times New Roman, que não pode ser
  redistribuída. Candidatas instaladas e livres: **Liberation Serif** (OFL,
  métricas compatíveis com Times New Roman) para o texto e **FreeSerif**
  (GPL-3+ com exceção para fontes) para figurinas e símbolos. A DejaVu Sans não
  tem `⩲`/`⩱`.
* **Diagramas:** na estratégia A, os diagramas ficam intocados porque são texto
  numa fonte própria e a redação exclui esses trechos. Defeitos tipográficos do
  original são preservados, não corrigidos.
* **Soluções dos exercícios:** ligar "9/21." ao diagrama com o rótulo de
  exercício 9/21 recuperaria o contexto de boa parte das últimas 50 páginas.
* **Referências cruzadas:** "Return to diagram 1-1" pode reabrir a posição
  daquele diagrama.

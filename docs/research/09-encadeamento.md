# Fase 3 — notação: encadeamento, figurinas de peão, PGN, probe e fontes

Data: 2026-10-23. Medido no livro inteiro (*Dvoretsky's Endgame Manual*,
441 páginas, 45.448 lances), antes e depois.

## Por que um lance fica sem posição

Cada lance `no_context` agora diz o motivo num aviso informativo
(`no_position:…`). Antes desta etapa:

| Motivo | Lances |
|---|---|
| número de lance que não está na linha atual (`after_move_number_gap`) | 9.472 |
| parágrafo que já começa sem posição (`region_start`) | 7.756 |
| lance citado na prosa sem número (`detached`, por desenho) | 2.612 |
| depois de um lance ilegal | 554 |
| ideia depois de △ (por desenho) | 223 |
| outros | 125 |

A maior parte dos "números fora da linha" era um parágrafo novo voltando a um
lance anterior da mesma partida: cada parágrafo partia só da posição final do
anterior, sem a linha que levou até ela.

## O que mudou

1. **A linha principal viaja entre parágrafos** (`Context.line`): desde o
   último diagrama, todas as posições da linha principal ficam disponíveis
   para quem vier depois.
2. **Voltar a um parágrafo anterior exige prova**: a posição encontrada pelo
   número só vale se todo o segmento seguinte for legal a partir dela; senão
   é tratada como lacuna, como antes (outra partida citada no texto, por
   exemplo).
3. **Texto antes do próprio diagrama**: se o próximo diagrama da mesma
   página e coluna explica melhor os lances do parágrafo (mais validados e
   não mais ilegais), a posição dele é usada, com o aviso
   `context_from_following_diagram`.

## Resultado

| | Antes | Depois |
|---|---|---|
| Validados | 24.590 | 27.256 (+2.666) |
| Sem posição | 20.742 | 18.103 |
| Ilegais | 116 | 88 |
| Ambíguos | 0 | 1 |

Transições: 2.629 de sem posição → validado; 37 de ilegal → validado; 9 de
sem posição → ilegal; 1 → ambíguo.

**114 lances validados antes e depois mudaram de interpretação** (outra
posição de partida). Destes, 27 agora têm aviso de revisão (`branch_ambiguous`:
com mais linhas visíveis, o validador passa a enxergar duas leituras possíveis
e pede revisão em vez de escolher em silêncio). Num caso inspecionado lance a
lance (p. 54), a leitura nova é a coerente: o parágrafo volta à linha anterior
para discutir uma alternativa, e a leitura antiga validava um lance seguinte
na linha principal por coincidência.

Na amostra traduzida, o P3 continua atendido com mais lances confirmados:
515/515 (eram 482).

## Figurinas de peão e PGN

* **Figurina de peão** ("♙e4", "♟d×c6") passou a ser lida como lance de peão;
  antes era descartada e, colada a um número, confundida com erro de OCR.
  Na conversão para letras ela some ("e4"); em figurinas vira a branca, como
  as demais peças. O livro de amostra não usa figurina de peão no texto
  (contagens inalteradas); a cobertura vem dos testes.
* **PGN por diagrama** (`app/chess/pgn_export.py`, `scripts/export_pgn.py`):
  uma partida por diagrama, com a posição do diagrama (FEN, ainda proposta),
  página e rótulo no cabeçalho e **só os lances da linha principal
  validados**. Quando a validação perde a posição, a partida termina com um
  comentário dizendo isso. No livro inteiro: 1.136 diagramas com posição, 790
  com lances, 9.371 meios-lances, 242 interrompidos por perda de posição;
  o arquivo é relido pelo python-chess sem erros. A saída fica fora do
  repositório.

## Probe de glifos com mais referências

Medido nos 12 glifos de peça das duas fontes figurinas do livro, usando como
gabarito o mapa confirmado pelo usuário:

| Variante | Acertos |
|---|---|
| 2 fontes de referência, contorno (antes) | 10/12 |
| 2 fontes, contorno + silhueta | 11/12 |
| todas as instaladas com as 12 figurinas (13), contorno | 11/12 |
| todas as instaladas, contorno + silhueta (adotada) | 11/12 |

A silhueta (desenho com o interior preenchido) varia menos entre editoras que
o contorno. Como ela torna ♗ e ♝ quase iguais, a margem de segurança da
proposta passou a ser medida contra **outra peça**, não contra a mesma peça
na outra cor. Erro restante: peão lido como bispo (silhuetas parecidas). A
amostra é pequena; o resultado continua sendo proposta que o usuário confirma.

## Sinais de fonte e fontes Type 3

`app/extraction/font_signals.py` examina cada fonte (nome, tipo, presença de
`ToUnicode`, caracteres na Área de Uso Privado, letras de peça em trechos
curtos, linhas de 8+ caracteres típicas de tabuleiro) e diz **quais pedem
mapa** e **como sondar**: `embedded` (TrueType/CFF incorporada com
`ToUnicode`: glifo desenhado isolado) ou `page` (Type 3 ou sem `ToUnicode`:
recorte da página). `scripts/diagnose_book.py` passou a listar essas fontes.
No livro de amostra: as três Linares aparecem como perfis já confirmados; as
dez de texto não pedem nada.

Caracterização com uma fonte Type 3 sintética (`tests/fixtures/type3.py`,
glifos desenhados por procedimento):

| Caso | Texto extraído | Sinal | Probe |
|---|---|---|---|
| sem `ToUnicode` | letras da codificação ("Nf3") | `unknown_symbols` | página |
| `ToUnicode` → figurinas | "♘f3", valida direto | texto (nenhum mapa) | — |
| `ToUnicode` → letras | "Nf3" | `likely_figurine` | página |

Para Type 3 não há arquivo de fonte a redesenhar (`embedded_glyph_font`
devolve nada); só o recorte da página serve. Os desenhos toscos do teste
recebem notas altas contra figurinas de referência (um triângulo parece um
peão), o que reforça a regra: o probe propõe, o usuário confirma.

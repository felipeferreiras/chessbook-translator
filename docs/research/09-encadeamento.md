# Fase 3 — encadeamento de posições entre parágrafos e diagramas

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

# Prova de conceito (Fase 2)

## Amostra

10 a 20 páginas, escolhidas pelo usuário de um livro que ele tenha direito de
traduzir, ou páginas sintéticas equivalentes se nenhum livro puder ser usado.
A amostra deve cobrir, no mínimo:

| Tipo de página | Qtd. mínima |
|---|---|
| Prosa contínua com lances intercalados | 3 |
| Página com 1–2 diagramas e legendas | 3 |
| Análise com variantes entre parênteses e recuos | 2 |
| Página com nota de rodapé | 1 |
| Início de capítulo (títulos, cabeçalho diferente) | 1 |
| Página digitalizada (se o livro tiver) | 2 |
| Tabela, índice ou lista de partidas | 1 |

Se o livro usar fonte figurina, ao menos 3 páginas devem contê-la.

## Escopo do que a POC executa

1. Importar o PDF da amostra (cópia imutável + hash).
2. Diagnóstico por página (digital/digitalizada, fontes, candidatos a diagrama).
3. Extração em IR; OCR nas páginas digitalizadas.
4. Probe de glifos e confirmação manual do mapa por fonte.
5. Detecção de convenção e validação dos lances, com FEN confirmada dos
   diagramas quando o usuário a informar.
6. Tradução por provedor escolhido (ou `FakeProvider`), com `guard`.
7. Layout A com fallback para B por página; diagramas reaproveitados.
8. PDF preliminar + relatório com os critérios P1–P11.
9. Comparação lado a lado no navegador (versão mínima).

## Fora do escopo da POC

Interface completa de revisão, glossário editável na interface, retomada após
falha, controle de custo além da contagem de tokens, modo adaptativo completo.

## Decisão ao final

Avançar para a Fase 3 somente se P1–P5 e P7 forem atendidos e se o usuário
considerar a tradução e o layout da amostra aceitáveis (P9). Caso contrário,
registrar as falhas e corrigir antes.

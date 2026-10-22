# ADR-0002 — Estratégia híbrida de preservação de PDF

**Estado:** aceito (Fase 1), a confirmar com a amostra da Fase 2 · **Data:** 2026-10-22

## Contexto
Duas estratégias foram medidas no spike (`docs/research/03-spike-pdf.md`):
A — editar o PDF original (redação seletiva + reescrita nas regiões);
B — reconstruir a página a partir da representação intermediária (HTML/CSS →
WeasyPrint, diagrama recortado como vetor).

Evidências: A preserva o diagrama de forma exata (0 % de pixels alterados), mas
perde blocos silenciosamente quando o texto não cabe (4 de 6 com a caixa
estrita; 1 de 6 com expansão). B não perde blocos e não exige redução de fonte,
mas reflui a página (diagrama deslocado 50 pt) e se afasta do original.

## Decisão
Uma única representação intermediária e dois motores de layout, escolhidos
**por página**:

| Situação | Motor |
|---|---|
| PDF digital, modo fidelidade | A com calibração, expansão no espaço livre, redução máxima de 10–15 % |
| Bloco que não cabe em A | página marcada para revisão; oferta de recomposição em B só daquela página |
| Página digitalizada | B (nunca sobrepor tradução à imagem que contém o texto) |
| Modo adaptativo | B em todas as páginas |

Regras obrigatórias para os dois motores:
1. Verificar o retorno de cada operação de composição; nenhum bloco pode ser
   descartado sem registro.
2. Depois de renderizar, procurar o texto de cada bloco na página gerada.
3. Diagramas e imagens são reutilizados do original; nunca recriados sem
   pedido e confirmação.
4. Toda redução tipográfica, expansão de caixa ou troca de fonte é registrada
   no relatório.

## Consequências
* Dois motores para manter, mas ambos pequenos e sobre a mesma IR.
* O modo fidelidade depende de espaço livre; livros muito densos terão mais
  páginas para revisar ou recompor em B.
* A comparação visual precisa de alinhamento antes de usar métricas de pixel.

# Critérios de aceitação

Cada critério tem uma forma de verificação. "Objetiva" = medida automática;
"heurística" = indicador automático que não substitui inspeção; "humana" =
inspeção do usuário.

## Fase 1 — investigação e arquitetura

| # | Critério | Verificação | Estado |
|---|---|---|---|
| 1.1 | Ambiente inspecionado e registrado | `docs/research/01-ambiente.md` | ✅ |
| 1.2 | Licenças dos componentes recomendados conferidas no arquivo do repositório e no pacote | `docs/research/02-repositorios-e-licencas.md` | ✅ (pesos do Docling e de modelos locais: **não verificados**) |
| 1.3 | Duas estratégias de PDF comparadas com medição | `docs/research/03-spike-pdf.md` + script reproduzível | ✅ (1 página sintética) |
| 1.4 | Estratégia de FAN para Unicode, fontes especiais e OCR | `docs/research/04-estrategia-fan.md` + fixtures + testes | ✅ (protótipo) |
| 1.5 | Arquitetura, modelo de dados e pipeline | `docs/architecture/01-arquitetura.md`, ADRs | ✅ |
| 1.6 | POC de 10–20 páginas definida | `docs/quality/poc.md` | ✅ |
| 1.7 | Testes iniciais executados | `pytest`: 89 testes passando na Fase 1 (285 agora) | ✅ |
| 1.8 | Plano por prioridade | `docs/plano-execucao.md` | ✅ |

## Prova de conceito (Fase 2) — critérios de saída

Medidos sobre a amostra definida em `poc.md`. Resultado de 2026-10-23 em
`docs/research/08-relatorio-poc.md`: P1–P8, P10 e P11 atendidos; P9 aprovado pelo usuário em 2026-10-23.

| # | Critério | Métrica | Meta | Tipo |
|---|---|---|---|---|
| P1 | Original intacto | sha256 do original antes = depois | 100 % | objetiva |
| P2 | Nenhum bloco perdido | blocos da IR encontrados na página gerada | 100 %, ou bloco listado como pendente | objetiva |
| P3 | Notação nunca corrompida | lances `validated` cujo UCI, relido do PDF final, é igual ao do original | 100 % | objetiva |
| P4 | Nenhuma conversão silenciosa | lances não validados que mudaram de grafia sem registro | 0 | objetiva |
| P5 | Diagramas preservados | diagramas da origem presentes na saída, mesmo tamanho (±1 pt), sem corte | 100 % | objetiva + humana |
| P6 | Legenda junto do diagrama | legenda na mesma página e adjacente | 100 % ou sinalizado | objetiva |
| P7 | Marcadores de tradução íntegros | segmentos com `GuardViolation` | registrados; 0 aceitos | objetiva |
| P8 | Tradução sem omissão | segmentos com razão de comprimento PT/EN fora de 0,8–1,6 | listados para revisão | heurística |
| P9 | Qualidade da tradução | revisão do usuário em todos os parágrafos da amostra | aceito pelo usuário | humana |
| P10 | Layout | sobreposições, texto fora da página, redução > 15 % | 0 não sinalizados | objetiva |
| P11 | Relatório | todos os itens acima no relatório, separando objetivo de heurístico | gerado | objetiva |

## Primeira versão utilizável

Os 20 critérios da seção 22 do enunciado, com estas verificações adicionais:

* Retomada: matar o processo no meio da tradução e reiniciar não duplica
  blocos nem retraduz blocos concluídos (teste de integração).
* Reprocessamento seletivo de uma página não altera ids nem revisões de outras
  páginas.
* Exportação: falha na geração mostra erro e não marca a exportação como
  concluída.
* Nenhuma porcentagem geral de "precisão" é exibida sem metodologia; o
  relatório mostra contagens.

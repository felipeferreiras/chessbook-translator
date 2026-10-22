# Plano de execução por prioridade

A ordem segue a prioridade do projeto: **não corromper lances → preservar
diagramas → não perder conteúdo no layout → qualidade da tradução →
conforto de uso**.

| Prioridade | Fase | Entrega | Depende de |
|---|---|---|---|
| ✅ | 1 | Investigação, licenças, spike de PDF, estratégia FAN, arquitetura, ADRs, critérios, 89 testes; núcleo de notação e `guard` (antecipados por serem o maior risco) | — |
| 1 | 2a | Importação segura + diagnóstico + extração para IR (PyMuPDF atrás de `PdfReader`), com testes nos fixtures | — |
| 2 | 2b | Detecção de regiões de diagrama (vetor, imagem, fonte de diagrama) e associação com legendas | 2a |
| 3 | 2c | Layout A com calibração, expansão e verificação de presença; fallback B por página | 2a, 2b |
| 4 | 2d | `TranslationProvider` + `FakeProvider` + adaptador Claude API; tradução da amostra com `guard` | 2a |
| 5 | 2e | Relatório P1–P11 e comparação lado a lado mínima; **avaliação da POC com o usuário** | 2a–2d |
| 6 | 3 | Notação: probe de glifos com mais referências, sinais de fonte/`ToUnicode`, figurinas pretas, encadeamento entre parágrafos e diagramas, PGN por partida, testes com fontes Type 3 | 2e aprovada |
| 7 | 4 | Glossário (modelo, editor, aplicação contextual), contexto por capítulo, editor de revisão com histórico, avaliação de modelos (Opus 5.5 × Sonnet 5.5 × local) | 3 |
| 8 | 5 | Modos de layout completos, tipografia, detecção de cortes/sobreposições, relatórios de qualidade | 4 |
| 9 | 6 | OCR melhorado (figurinas em imagem), retomada, reprocessamento seletivo, limites e custos, Docling para digitalizados | 5 |
| 10 | 7 | Livros completos: integridade, desempenho, custo, retomada | 6 |
| 11 | 8 | Interface final, instalação, backup, revisão de segurança, limitações conhecidas | 7 |

## O que o usuário precisa decidir para a Fase 2

1. Qual livro (ou quais páginas) usar na amostra, mantido fora do repositório.
2. Se a tradução da POC pode usar um provedor remoto (e qual) ou se deve ser
   apenas local/`FakeProvider`.
3. Se o projeto deve ser movido para um repositório próprio.

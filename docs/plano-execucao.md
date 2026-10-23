# Plano de execução por prioridade

A ordem segue a prioridade do projeto: **não corromper lances → preservar
diagramas → não perder conteúdo no layout → qualidade da tradução →
conforto de uso**.

| Prioridade | Fase | Entrega | Depende de |
|---|---|---|---|
| ✅ | 1 | Investigação, licenças, spike de PDF, estratégia FAN, arquitetura, ADRs, critérios, 89 testes; núcleo de notação e `guard` (antecipados por serem o maior risco) | — |
| ◐ | 2a | Diagnóstico + extração para regiões em ordem de leitura + perfis de fonte + passagem de notação no livro de amostra (feito: `notation_pass`, `diagnose_book`); falta importação com cópia imutável e a IR persistida | — |
| ◐ | 2b | Diagramas em fonte lidos e associados a rótulos (feito); falta diagramas vetoriais/imagem e ligação com soluções ("9/21") e referências ("diagram 1-1") | 2a |
| ✅ | 2b' | Mapa de glifos Linares confirmado pelo usuário (2026-10-22) | 2a |
| ✅ | 2d | Provedores, glossário, cache e revisão; primeira tradução real da amostra com GPT-5.4 Nano (208/208 aceitos) | 2a |
| **agora** | 2d' | Comparar um modelo maior nas páginas 21 e 438 (terminologia em índices) e decidir o modelo do livro | 2d |
| 3 | 2c | Layout A com calibração, expansão e verificação de presença; fallback B por página | 2a, 2b |
| 5 | 2e | Relatório P1–P11 e comparação lado a lado mínima; **avaliação da POC com o usuário** | 2a–2d |
| 6 | 3 | Notação: probe de glifos com mais referências, sinais de fonte/`ToUnicode`, figurinas pretas, encadeamento entre parágrafos e diagramas, PGN por partida, testes com fontes Type 3 | 2e aprovada |
| 7 | 4 | Glossário (modelo, editor, aplicação contextual), contexto por capítulo, editor de revisão com histórico, avaliação de modelos (Opus 5.5 × Sonnet 5.5 × local) | 3 |
| 8 | 5 | Modos de layout completos, tipografia, detecção de cortes/sobreposições, relatórios de qualidade | 4 |
| 9 | 6 | OCR melhorado (figurinas em imagem), retomada, reprocessamento seletivo, limites e custos, Docling para digitalizados | 5 |
| 10 | 7 | Livros completos: integridade, desempenho, custo, retomada | 6 |
| 11 | 8 | Interface final, instalação, backup, revisão de segurança, limitações conhecidas | 7 |

## Decisões do usuário

1. Livro de amostra: *Dvoretsky's Endgame Manual* (2020), mantido fora do
   repositório; 16 páginas escolhidas em `docs/research/05-amostra-dvoretsky.md`.
2. Provedor de tradução: **serviço externo**, com suporte a Claude, ChatGPT e
   Gemini; em 2026-10-23, **Pollinations** como ponto único.
3. Repositório próprio: **feito** (`felipeferreiras/chessbook-translator`).

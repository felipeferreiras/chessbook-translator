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
| ✅ | 2d' | Comparação Nano × GPT-5.5 × Gemini; **modelo escolhido: Gemini 3.8 Flash**; amostra de 16 páginas traduzida (208/208) | 2d |
| ✅ | 2a' | Junção de linhas com hífen no fim (referências e hifenização) | 2a |
| ◐ | 2c | Layout A: redação fora dos tabuleiros, fontes métricas, fluxo por coluna, linha única, sumário em tabela, verificações (texto, notação, sobra, sobreposição, diagramas) — amostra montada, 208/208 blocos (`docs/research/07-montagem-pdf.md`); negrito/itálico da prosa preservados; falta fallback B por página | 2a, 2b |
| ✅ | 2e | Relatório P1–P11 (`scripts/poc_report.py`, `docs/research/08-relatorio-poc.md`): P1–P8, P10, P11 atendidos; página de revisão lado a lado gerada; P9 **aprovado pelo usuário em 2026-10-23** | 2a–2d |
| ✅ | 3 | Notação (encadeamento entre parágrafos e diagramas, figurinas de peão, PGN por diagrama, probe com mais referências, sinais de fonte/ToUnicode, Type 3 — `docs/research/09-encadeamento.md`): probe de glifos com mais referências, sinais de fonte/`ToUnicode`, figurinas pretas, encadeamento entre parágrafos e diagramas, PGN por partida, testes com fontes Type 3 | 2e aprovada |
| ✅ | 4 | Glossário (modelo, editor, aplicação contextual), contexto por capítulo, editor de revisão com histórico, avaliação de modelos (Opus 5.5 × Sonnet 5.5 × Gemini × Qwen aberto) — `docs/research/10-fase4.md` | 3 |
| ✅ | 5 | Layout do livro inteiro (5569/5569 blocos, 441/441 páginas sem pendência na tradução simulada), memória (subconjuntos de fonte, montagem em blocos), tipografia (Urbanist/Liberation), detecção de cortes e sobreposições, aba Qualidade, seleção de motor com previsão de custo — `docs/research/12-fase5-layout.md`; modo B não foi necessário | 4 |
| ✅ | 6 | Retomada (tarefas órfãs e montagem em partes reaproveitadas: 216 s → 24 s depois de uma edição), reprocessamento seletivo (5 modos, "Retraduzir…" por parágrafo), teto de gasto do projeto e conferência antes de cada seção, OCR com figurinas pelos protótipos do livro (71–84 % dos lances com peça certos, diagramas 111/111, conferência obrigatória) — `docs/research/13-fase6.md`, ADR-0007; Docling avaliado e não adotado (empata na prosa, não lê figurinas, +6 GB) | 5 |
| ✅ | 7 | Livro completo traduzido de verdade (Sonnet 5.5, 7,06 pollen, 34 min): 428/440 páginas sem pendência, notação idêntica em todas as traduções, diagramas intactos; sincronização do projeto, auditoria de integridade, tradução em paralelo com reserva no teto (4,4×), retomada real após `kill -9`, recalibração de custo — `docs/research/14-fase7.md` | 6 |
| 11 | 8 | Interface final, instalação, backup, revisão de segurança, limitações conhecidas | 7 |

## Decisões do usuário

1. Livro de amostra: *Dvoretsky's Endgame Manual* (2020), mantido fora do
   repositório; 16 páginas escolhidas em `docs/research/05-amostra-dvoretsky.md`.
2. Provedor de tradução: **serviço externo**, com suporte a Claude, ChatGPT e
   Gemini; em 2026-10-23, **Pollinations** como ponto único.
3. Repositório próprio: **feito** (`felipeferreiras/chessbook-translator`).

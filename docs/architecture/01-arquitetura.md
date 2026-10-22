# Arquitetura inicial

Estado: proposta da Fase 1. Os módulos marcados como **implementado** existem
em `backend/app/` e têm testes; os demais são desenho.

## Visão geral

Monólito modular local: um processo Python (FastAPI) com um executor de tarefas
em segundo plano, SQLite e um diretório de armazenamento por projeto; um
frontend React/TypeScript (Vite) servido em `localhost`. Nenhum serviço externo
é obrigatório: o provedor remoto de tradução é opcional e explícito.

```
┌──────────────────────── navegador (localhost) ────────────────────────┐
│ React + TS (Vite) · pdf.js (visualização) · chess.js (revisão)         │
│ Painel · Importação/diagnóstico · Configuração · Revisão · Comparação  │
└───────────────▲────────────────────────────────────────────────────────┘
                │ HTTP/JSON (API local, sem CORS público)
┌───────────────┴──────────────── backend (Python) ──────────────────────┐
│ api/        rotas FastAPI, validação de entrada (pydantic)             │
│ jobs/       fila em SQLite, executor com limite de concorrência,       │
│             estados por etapa, cancelamento, retomada                  │
│ documents/  importação, hash, cópia imutável do original, limites      │
│ extraction/ PdfReader (PyMuPDF): blocos, spans, fontes, imagens,       │
│             vetores; glyph_probe (implementado, protótipo)             │
│ ocr/        OcrEngine (Tesseract); OCR seletivo por página/região      │
│ structure/  ordem de leitura, papéis (título, nota, legenda, diagrama) │
│ chess/      notation/ (implementado): lexer, convention, validate,     │
│             render · diagrams/: detecção, associação, FEN confirmada   │
│ translation/ guard (implementado) · TranslationProvider (adaptadores:  │
│             Claude API, llama.cpp, fake para testes) · glossário       │
│ layout/     modo A (edição do original) e modo B (reconstrução),       │
│             medição, calibração, detecção de sobreposição/corte        │
│ export/     PDF final, texto estruturado, relatório de qualidade       │
│ quality/    verificações técnicas e visuais por página                 │
└───────────────┬────────────────────────────────────────────────────────┘
                │
     storage/<projeto>/{original/, intermediate/, renders/, output/} + app.db (SQLite)
```

## Decisões principais (detalhes nos ADRs)

| Tema | Decisão | ADR |
|---|---|---|
| Estilo | Monólito modular, um processo, sem filas externas | 0001 |
| PDF | Estratégia híbrida por página sobre a mesma representação intermediária | 0002 |
| Notação | Três camadas (original, normalizada, saída); resolução própria + python-chess | 0003 |
| Licenças | GPL/AGPL aceitas para uso privado, isoladas atrás de adaptadores | 0004 |
| Tradução | Marcadores protegem a notação; provedores intercambiáveis; contexto controlado | 0005 |
| OCR | Tesseract só para prosa; notação OCR sempre validada ou revisada | 0006 |

### Alternativas descartadas

* **Next.js**: acrescentaria um segundo servidor (Node) sem ganho, porque não
  há SEO nem renderização no servidor; o FastAPI já é o backend. Vite gera
  arquivos estáticos que o próprio FastAPI pode servir.
* **Celery/Redis ou RQ**: dependências de infraestrutura para um usuário e uma
  máquina. Uma tabela de tarefas em SQLite com um executor em thread/processo
  cobre retomada, cancelamento e progresso. Revisar se houver multiusuário.
* **PostgreSQL**: só se houver concorrência real ou implantação multiusuário.
* **Tratar o PDF como texto corrido** (extrair tudo, traduzir, gerar novo
  documento): perde diagramas, coordenadas e o vínculo entre trecho e página.
* **Deixar o LLM converter a notação** junto com a prosa: impossível validar
  e auditar; rejeitado pelo requisito de integridade.

## Representação intermediária (IR)

Toda extração produz a mesma estrutura, persistida em SQLite (metadados) e
JSON por página (conteúdo); as duas estratégias de layout leem dela.

```
Document ── Page ── Block ── Span (texto, fonte, tamanho, flags, bbox, origem)
                     │        └─ glifos resolvidos (mapa por fonte, confirmado ou proposto)
                     ├─ role: title | heading | paragraph | caption | footnote |
                     │        header | footer | page_number | table | diagram | image
                     ├─ reading_order (+ confiança)
                     ├─ source: pdf_text | ocr (+ confiança por palavra)
                     ├─ notation: [Atom] + [MoveAnalysis] (camadas original/normalizada)
                     └─ translation: machine | reviewed | current (+ histórico)
Diagram ── região, imagem original (recorte vetorial ou raster), legenda,
           número, FEN (somente se confirmada), vínculos com lances, estado
```

Identificadores estáveis: `doc:<sha256-curto>/p<nº>/b<ordem>-<hash do conteúdo
original>`. Reprocessar uma página com o mesmo conteúdo gera o mesmo id
(idempotência); conteúdo diferente gera id novo, e o anterior fica no
histórico.

## Modelo de dados (SQLite, primeira versão)

| Tabela | Campos principais |
|---|---|
| `project` | id, nome, idioma_origem (`en`), idioma_destino (`pt-BR`), notação_saída (`preserve` padrão), política_conversão (`strict`), modo_layout (`fidelity`/`adaptive`), provedor_tradução, privacidade (`local_only`/`remote_allowed`), estado, criado_em, atualizado_em |
| `document` | id, project_id, nome_original, caminho_original (somente leitura), sha256, tamanho, nº_páginas, metadados_json, convenção_detectada, convenção_confirmada, estado |
| `page` | id, document_id, número, largura, altura, rotação, tipo_extração (`digital`/`scanned`/`hybrid`), estado, alertas_json |
| `block` | id estável, page_id, papel, bbox, ordem_leitura, confiança_ordem, texto_original, origem, estilos_json, alertas_json |
| `glyph_map` | document_id, fonte, caractere, figurina, pontuação, estado (`proposed`/`confirmed`/`rejected`) |
| `notation_atom` | id, block_id, início, fim, texto_original, tipo |
| `move` | id, atom_id, status, contexto, fen_antes, uci, san_canônico, interpretações_json, avisos_json |
| `diagram` | id, page_id, bbox, caminho_imagem, legenda_block_id, número, fen, estado_fen (`none`/`proposed`/`confirmed`), vínculos_json |
| `translation` | block_id, versão, texto_máquina, texto_revisado, texto_atual, provedor, modelo, prompt_hash, criado_em |
| `revision` | id, entidade, entidade_id, valor_anterior, valor_novo, tipo, autor, data |
| `job` / `job_step` | id, projeto, etapa, escopo (documento/página/bloco), estado (`pending`/`running`/`done`/`done_with_warnings`/`failed`/`awaiting_review`), progresso, erro, tentativas, iniciado_em, terminado_em |
| `usage` | job_id, provedor, modelo, tokens_entrada, tokens_saída, tokens_cache, custo_estimado (nulo se desconhecido) |

O original nunca é alterado: é copiado para `original/` com permissão somente
leitura e verificado pelo hash antes de cada etapa.

## Pipeline

Cada etapa é idempotente, grava sua saída antes de marcar `done` e pode ser
reexecutada por escopo (documento, página, bloco, sequência, diagrama).

| # | Etapa | Saída | Pode exigir revisão quando |
|---|---|---|---|
| 1 | Importação e validação | cópia imutável, hash, limites verificados | arquivo protegido, corrompido, acima do limite |
| 2 | Diagnóstico | páginas digitais/digitalizadas, fontes, candidatos a diagrama | — |
| 3 | Extração | blocos, spans, imagens, vetores | texto ilegível, fontes sem `ToUnicode` |
| 4 | OCR seletivo | blocos OCR com confiança | baixa confiança |
| 5 | Glifos | mapa proposto por fonte | sempre que houver proposta nova |
| 6 | Estrutura | papéis e ordem de leitura | ordem incerta |
| 7 | Notação | átomos, convenção, validação | ambíguo, ilegal, suspeito, sem contexto |
| 8 | Diagramas | regiões, legendas, vínculos, FEN proposta | associação ou posição incerta |
| 9 | Tradução | texto traduzido com marcadores verificados | `GuardViolation`, glossário violado |
| 10 | Saída de notação | texto final com notação escolhida | lances não convertidos |
| 11 | Layout | páginas compostas (A ou B) | bloco não coube, sobreposição |
| 12 | Verificação | presença de blocos, cortes, diagramas, contagem de páginas | qualquer falha |
| 13 | Revisão humana | edições registradas | — |
| 14 | Exportação | PDF, texto estruturado, relatório | falha de geração |

## Privacidade

* Padrão `local_only`: nenhuma etapa envia conteúdo para fora; a tradução
  remota fica desabilitada até o usuário escolher um provedor.
* Ao habilitar um provedor remoto, a tela mostra o provedor, o modelo e o que é
  enviado: apenas o texto mascarado do segmento, o contexto delimitado e os
  termos de glossário relevantes. Nunca o PDF, nunca imagens, nunca o livro
  inteiro numa chamada.
* Logs registram ids, contagens e erros, não o conteúdo do livro.
* Credenciais apenas por variável de ambiente (`.env` fora do controle de
  versão).
* Exclusão de projeto remove registros e todo o diretório de armazenamento.

## Segurança de arquivos

* Verificação do tipo pelo conteúdo (`%PDF-`), não pela extensão.
* Limites configuráveis: tamanho do arquivo, nº de páginas, pixels por
  renderização, tempo por página.
* Abertura de PDFs em processo filho com limites de memória/tempo, para que um
  arquivo malformado não derrube o servidor.
* PDFs com senha: erro explícito com ação ("remova a proteção com a senha e
  importe novamente"); nenhuma tentativa de quebra.
* API escuta apenas em `127.0.0.1` por padrão.

## Riscos técnicos principais

| Risco | Impacto | Mitigação |
|---|---|---|
| Fontes figurinas sem mapeamento | lances ilegíveis ou trocados | probe visual + confirmação por fonte; validação |
| OCR corrompe notação | lance errado aceito | átomos suspeitos; perda de contexto; revisão obrigatória |
| Posição inicial desconhecida | nada é validável | FEN de diagrama confirmada; hipótese explícita; revisão em lote por partida |
| Tradução mais longa que o original | perda ou espremimento de texto | calibração, expansão controlada, limite de redução, fallback B, verificação de presença |
| Ordem de leitura em duas colunas | texto embaralhado | heurística por colunas + revisão; Docling na Fase 2 para digitalizados |
| Diagrama associado ao parágrafo errado | posição errada | associação por legenda/número; nunca recriar sem confirmação |
| Licenças GPL/AGPL | restrição para distribuir | uso privado; adaptadores; alternativas permissivas mapeadas |
| Custo de tradução em livros longos | gasto inesperado | estimativa antes, limites, cache, lotes, amostra primeiro |

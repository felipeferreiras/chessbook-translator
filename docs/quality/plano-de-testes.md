# Plano de testes

## Como executar

```bash
cd chessbook-translator/backend
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev,spike]"
.venv/bin/python -m pytest -q
```

Requisitos do sistema: fonte DejaVu Sans (`fonts-dejavu-core`); Tesseract é
opcional (o teste de OCR é pulado se não estiver instalado).

## Suíte atual — 199 testes, todos passando em 2026-10-23

| Arquivo | Cobre |
|---|---|
| `test_notation_lexer.py` | formas de lance (EN, PT, FAN, longa, promoções, e.p., roques com O/0), números de lance, reticências, casas na prosa, parênteses de prosa × variantes, padrões de OCR, descritiva, preservação de posições |
| `test_notation_validate.py` | posição inicial não presumida, hipótese explícita, mesma linha nas três notações, capturas, xeque-mate, roque × `Kg1`, promoções, promoção sem peça (ambígua), SAN subespecificado (ambíguo), desambiguação por coluna/linha/casa, `R` torre × rei, ilegal com perda de contexto, FEN não padrão, números incompatíveis, variantes simples e aninhadas, variante ilegal sem quebrar a principal, ramificação implícita, lances sem número após prosa, marcadores incoerentes, en passant, OCR suspeito, encadeamento de regiões, descritiva |
| `test_notation_render_convention.py` | preservação byte a byte, FAN→EN/PT, ida e volta EN→PT→FAN→EN, promoção, desambiguação e sinais mantidos, política `strict` × `symbol_only`, letra ambígua nunca convertida, lance ambíguo nunca convertido, detecção de convenção (6 casos) |
| `test_translation_guard.py` | marcadores, restauração, marcador ausente/duplicado/inventado, casa alterada na prosa, reordenação, números, quebra de linha perdida e marcador mudado de linha (bloqueiam), negrito/itálico da prosa como `<b>`/`<i>` (marcação, restauração, estilo do bloco inteiro não marcado, marcas malformadas bloqueiam, marcas perdidas avisam), parêntese com notação que perde a prosa ou muda de marcadores (bloqueia) |
| `test_book_conventions.py` | captura abreviada só depois de notação ("de" em português não é lance), parêntese de prosa com "de", números sem ponto, capturas abreviadas, símbolos do Informator colados, casa alternativa `(c2)`, parênteses de prosa, negrito como linha principal, ramificação decidida por um segmento posterior, ideias após △, numeração vinda do texto, leitura de diagramas em fonte (ida e volta, roque não inventado, defeito tipográfico, fileira deslocada, diagrama sem reis), rótulos, resolução de glifos com origem, glifo sem mapa, probe da fonte incorporada |
| `test_translation_providers.py` | prompt e glossário; para Pollinations, Claude, ChatGPT e Gemini: argumentos do pedido e leitura de respostas construídas com as classes reais de cada SDK, recusas, bloqueios, cortes por limite, JSON inválido; configuração (privacidade, chave, modelo obrigatório, `.env`) |
| `test_translation_service.py` | fluxo completo com notação restaurada byte a byte, segmentos só de notação não enviados, contexto mascarado, marcador perdido → nova tentativa → revisão, casa ou símbolo alterado rejeitado, cache, lotes, disjuntor após falhas, recusa, id ausente, razão de comprimento |
| `test_line_joining.py` | hífen no fim da linha: referências, casas e lances partidos, hífen suspenso, nomes compostos, hifenização desfeita só com evidência do vocabulário, alinhamento do negrito |
| `test_layout_compose.py` | montagem em página sintética: original removido e tabuleiro intacto, fluxo empurra o bloco seguinte, tabuleiro encerra o fluxo, bloco que não cabe vai para revisão, redação recortada fora do tabuleiro, moldura do diagrama, linha única centralizada sem invadir vizinhos, HTML (negrito, itálico, símbolos, sumário em tabela com estilo por célula), substituição de fontes, notação ausente, fundo sombreado retirado sem afetar texto e tabuleiro |
| `test_pdf_fixtures.py` | extração de FAN Unicode, fonte figurina por letras, fonte de uso privado; proposta de mapa de glifos; letras comuns não confundidas; validação após mapeamento; caracterização do `insert_htmlbox`; caracterização do Tesseract com FAN |

Casos ambíguos cujo resultado correto é **pedir revisão**: SAN subespecificado,
promoção sem peça, `R` com convenção indeterminada, letra resolvida só por
legalidade, marcador de xeque sem xeque, números de lance incompatíveis,
posição presumida.

## Não coberto por testes automáticos

* Chamadas reais: feitas manualmente com a Pollinations (GPT-5.4 Nano) em
  2026-10-23; Claude, ChatGPT e Gemini diretos ainda não. Testes com rede não
  entram na suíte automática (custo e chave). Os
  testes verificam montagem do pedido e leitura da resposta com os tipos dos
  SDKs, mas só uma chamada real confirma que cada API aceita o pedido (por
  exemplo, saída estruturada combinada com `fallbacks` na Claude).

## Próximas camadas

| Camada | Fase | Conteúdo |
|---|---|---|
| Unitários de extração | 2 | spans, fontes, ordem de leitura em 1 e 2 colunas |
| Integração | 2 | importação → extração → tradução (FakeProvider) → layout → exportação na página sintética e na amostra |
| Regressão | 2+ | documentos de referência sintéticos versionados com saída esperada (IR em JSON + hashes de texto por bloco) |
| Visual | 2+ | renderização antes/depois, alinhamento por correlação, diferença por região; nunca critério único |
| Notação | 3 | PDFs com fontes Type 3, `ToUnicode` ausente, figurinas pretas, sequências longas, partidas inteiras em PGN |
| Retomada | 6 | interrupção forçada em cada etapa |
| Casos extremos | 6–7 | duas colunas, notas longas, baixa resolução, páginas inclinadas, texto PT muito maior |

Livros reais do usuário **não** entram no repositório. Testes com livros reais
rodam localmente apontando para um diretório fora do controle de versão
(`CHESSBOOK_SAMPLES_DIR`) e só registram métricas.

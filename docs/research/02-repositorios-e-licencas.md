# Repositórios investigados e licenças

Método: o arquivo de licença de cada repositório foi baixado do branch padrão em
`raw.githubusercontent.com` em 2026-10-22, e a licença declarada no pacote
publicado (PyPI/npm) foi conferida na versão indicada. **Isto não é parecer
jurídico.** Antes de qualquer distribuição, as licenças devem ser revisadas
novamente na versão exata em uso.

## Resumo

| Projeto | Licença verificada | Versão conferida | Papel proposto | Decisão |
|---|---|---|---|---|
| python-chess | GPL-3.0 (LICENSE.txt); pacote: GPL-3.0+ | 1.11.2 | validação de lances, FEN, PGN, SVG de diagramas | **Adotado** |
| chess.js | BSD-2-Clause | 1.4.0 (npm) | validação no navegador (editor de revisão) | Adotar na Fase 4 |
| Lichess (lila) | AGPL-3.0 | master | referência de organização | Só referência; nenhum código copiado |
| PyMuPDF | AGPL-3.0 ou comercial (Artifex) | 2.0 | extração com fontes/coordenadas, redação, reescrita, renderização | **Adotado**, isolado atrás de adaptador |
| Docling | MIT (código) | 2.141.0 | análise de layout por modelo | Adiado (ver abaixo) |
| OCRmyPDF | MPL-2.0 | 17.13.0 | camada de OCR em PDFs digitalizados | Opcional, Fase 6 |
| Tesseract | Apache-2.0 | 5.3.4 (binário) | OCR | **Adotado** (prosa) |
| pypdf | BSD-3-Clause | 6.21.2 | manipulação estrutural simples | Não necessário agora |
| WeasyPrint | BSD-3-Clause | 70.0 | HTML/CSS → PDF (modo adaptativo) | **Adotado** para o modo B |
| Chessprint | **CC BY-NC-SA 4.0** | master | gerador de fichas de exercícios | **Descartado** |
| llama.cpp | MIT (código) | master | inferência local | Avaliar na Fase 6 |
| pdf.js (pdfjs-dist) | Apache-2.0 | 6.4.299 | visualizador no navegador | Adotar na Fase 4 |
| fontTools | MIT | 4.67.0 | inspeção de fontes, fixtures | **Adotado** |
| Noto Sans Symbols 2 | SIL OFL 1.1 | main | fonte de saída com figurinas | Candidata para saída |
| DejaVu Sans | licença Bitstream Vera + domínio público | pacote do sistema | fonte de saída, referência de glifos | **Adotada** nos testes |
| SDK `anthropic` (Python) | Apache-2.0 | 2.1.0 | adaptador do provedor de tradução | Fase 4 |

## Observações por componente

### python-chess (GPL-3.0+)

Cobre exatamente o que a validação precisa: geração de lances legais, roque,
en passant, promoção, xeque/mate, FEN, PGN e renderização SVG de tabuleiros. Não
reconhece figurinas nem notação portuguesa: o `parse_san` aceita apenas SAN
inglês. Por isso o projeto tem seu próprio analisador léxico e resolve cada
lance comparando seus componentes com `board.legal_moves`, usando o
python-chess só como motor de regras.

**Consequência de licença:** uma aplicação que importa python-chess e for
*distribuída* precisa ser distribuída sob GPL-3.0 (ou compatível). O uso privado
não gera essa obrigação.

### PyMuPDF (AGPL-3.0 ou comercial)

Foi a única opção avaliada que, em uma única biblioteca, entrega: texto com
fonte, tamanho, flags e caixa por caractere (`rawdict`); extração de fontes
incorporadas; redação seletiva (remove texto sem remover imagens ou vetores);
inserção de HTML em caixas com retorno de medição (`insert_htmlbox`);
recorte vetorial de regiões (`show_pdf_page` com `clip`) e renderização.

**Consequência de licença:** AGPL obriga a oferecer o código-fonte a quem usar
o software *pela rede*. Para uso privado em `localhost`, sem terceiros, não há
obrigação prática. Se a aplicação for aberta a outras pessoas, será preciso
publicar o código sob AGPL ou adquirir a licença comercial.

**Mitigação:** todo acesso a PDF fica atrás de interfaces (`PdfReader`,
`PageRenderer`, `PdfEditor`). Alternativas permissivas identificadas:
`pypdfium2` (BSD/Apache, renderização e texto), `pdfminer.six` (MIT, texto com
fontes) e `reportlab`/WeasyPrint (BSD, geração). A troca custaria a reescrita
dos adaptadores, mas não do domínio.

### Docling (MIT)

O código é MIT, mas o pacote completo depende de `docling-ibm-models`, que
puxa `torch`, `torchvision` e `transformers`, e baixa pesos de modelos do
Hugging Face. **As licenças dos pesos não puderam ser verificadas nesta
sessão** (Hugging Face bloqueado pelo proxy). Também não foi possível avaliar a
qualidade em páginas de xadrez sem baixar os modelos. Docling continua sendo o
candidato mais forte para a análise de layout de páginas digitalizadas
complexas (duas colunas, notas), a ser avaliado na Fase 2 em uma máquina com
acesso ao Hugging Face. Não é necessário para PDFs digitais, em que a
estrutura vem do próprio PDF.

### Tesseract (Apache-2.0)

Funciona bem para prosa, mas o spike confirmou que **ele corrompe FAN**:
`2.♘f3 ♘c6 3.♗b5` virou `2.\f3 \c6 3.865` (ver `03-spike-pdf.md`). O caso
`3.865` é o mais perigoso: o lance de bispo vira um número plausível. O OCR é
usado apenas para prosa, e toda região de notação reconhecida por OCR passa
pelo detector de padrões suspeitos e pelo validador.

### Chessprint (descartado)

A licença atual é CC BY-NC-SA 4.0 (inclui o conjunto de peças "caliente"),
com cláusula não comercial e compartilhamento pela mesma licença. Além disso,
o projeto é um gerador de fichas infantis 100 % frontend, sem relação com
reconstrução de diagramas de livros. O python-chess já gera diagramas SVG a
partir de FEN com o conjunto de peças embutido na própria biblioteca (coberto
pela GPL-3.0 do pacote; a procedência dos desenhos ainda deve ser conferida no
repositório antes de qualquer distribuição). Outros conjuntos de peças só
devem entrar após verificação da licença de cada um.

### llama.cpp (MIT)

O código é MIT; **cada modelo tem licença própria** (Llama, Gemma, Qwen,
Mistral etc. diferem e algumas restringem usos). A qualidade de tradução
técnica EN→PT-BR com preservação de marcadores precisa ser medida com o
conjunto de avaliação da Fase 4. O contêiner atual (4 vCPU, sem GPU) não é
representativo; a avaliação deve rodar no hardware do usuário. O adaptador de
tradução já foi desenhado para aceitar um provedor local
(`TranslationProvider`).

### Provedor remoto de tradução (Claude API)

Fatos consultados na referência oficial da API em 2026-10-22 (tabela com
cache de 2026-10-06); **conferir na página de preços antes de usar**:

| Modelo | ID | Contexto | Entrada / saída por 1M tokens |
|---|---|---|---|
| Claude Opus 5.5 | `claude-opus-5-5` | 1M | US$ 4 / US$ 20 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 1M | US$ 2 / US$ 10 |
| Claude Haiku 5.5 | `claude-haiku-5-5` | 1M | US$ 0,10 / US$ 0,50 (até 100K tokens de prompt) |

Recursos relevantes para custo: *prompt caching* (glossário e instruções
editoriais fixas no prefixo; leituras de cache custam uma fração do preço de
entrada) e *Message Batches API* (processamento assíncrono com 50 % do custo,
adequado para traduzir um livro inteiro fora do horário de uso). Contagem
prévia de tokens: `messages.count_tokens`.

Retenção de dados: depende do contrato e da configuração da organização na
Anthropic. Existe modalidade de retenção zero (ZDR) para organizações
autorizadas; alguns modelos (por exemplo, Claude Fable 5.1) exigem retenção de
30 dias e não estão disponíveis em ZDR sem autorização. **O projeto não deve
afirmar nada sobre retenção além do que constar nos termos vigentes da conta
do usuário**; a tela de configuração mostrará o provedor, o modelo e o
link para os termos.

A escolha do modelo é do usuário. Proposta para a Fase 4: medir Opus 5.5 e
Sonnet 5.5 no mesmo conjunto de avaliação e escolher pela qualidade medida,
não pelo preço por token.

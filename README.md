# Chessbook Translator

Aplicação web **privada** para traduzir livros de xadrez em PDF do inglês para o
português brasileiro, preservando notação, diagramas e organização editorial.

> **Estado: Fase 1 concluída; Fase 2 (prova de conceito) em andamento.** Ainda
> não há interface nem tradução/exportação de ponta a ponta. Existe um núcleo
> testado de notação, a proteção de lances para a tradução, perfis de fontes
> de xadrez, leitura de diagramas compostos em fonte e uma passagem de notação
> que roda num livro real inteiro (ver `docs/research/05-amostra-dvoretsky.md`).

## O que já funciona (com testes)

| Módulo | Caminho | O que faz |
|---|---|---|
| Análise léxica da notação | `backend/app/chess/notation/lexer.py` | separa lances (EN, PT, FAN, longa) da prosa sem alterar o texto; marca padrões de OCR suspeitos e notação descritiva |
| Convenção | `.../convention.py` | detecta EN / PT / FAN / descritiva / indeterminada, com evidências |
| Validação | `.../validate.py` | valida com python-chess; estados `validated`, `ambiguous`, `illegal`, `no_context`; nunca presume posição nem escolhe entre interpretações |
| Saída | `.../render.py` | preserva ou converte para EN, PT ou FAN só nos lances validados |
| Proteção na tradução | `backend/app/translation/guard.py` | troca a notação por marcadores e rejeita traduções que percam, dupliquem ou alterem lances e casas |
| Probe de glifos | `backend/app/extraction/glyph_probe.py` | propõe mapas por fonte quando o PDF desenha ♘ mas o texto diz `N` ou `` (protótipo; exige confirmação humana) |

## Como executar os testes

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/), fonte DejaVu Sans
(`fonts-dejavu-core` no Debian/Ubuntu). Tesseract é opcional.

```bash
cd backend
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev,spike]"   # inclui os SDKs de Claude, OpenAI e Gemini
.venv/bin/python -m pytest -q        # 285 testes
.venv/bin/ruff check app tests scripts ../spikes
```

Spike de estratégias de PDF (gera PDFs, PNGs e `results.json`):

```bash
.venv/bin/python ../spikes/pdf_strategies/run_spike.py /tmp/spike-out
```

## Tradução

Configure `.env` a partir de `.env.example` (provedor, chave, modelo e
`CHESSBOOK_PRIVACY_MODE=remote_allowed`) e veja `docs/architecture/02-traducao.md`.
Modelo escolhido: Gemini 3.8 Flash pela Pollinations
(ver `docs/research/06-primeira-traducao.md`).

```bash
cd backend
# 1. tradução das páginas (saída fora do repositório)
.venv/bin/python -m scripts.translate_pages LIVRO.pdf SAÍDA_TRAD --pages 13,21 --env-file ../.env
# 2. montagem do PDF traduzido + relatório + imagens lado a lado
.venv/bin/python -m scripts.assemble_pdf LIVRO.pdf SAÍDA_TRAD SAÍDA_PDF
# 3. critérios P1–P11 (relê o PDF traduzido) + página de revisão poc.html
.venv/bin/python -m scripts.poc_report LIVRO.pdf SAÍDA_TRAD SAÍDA_PDF
```

Como a montagem funciona e o que ela verifica: `docs/research/07-montagem-pdf.md`.

## Revisão (projeto + interface)

```bash
cd backend
export CHESSBOOK_STORAGE=/fora/do/repositorio/projetos   # contém o livro e a tradução
.venv/bin/python -m scripts.project create meu-livro "Meu livro" LIVRO.pdf
.venv/bin/python -m scripts.project import meu-livro SAÍDA_TRAD
.venv/bin/python -m scripts.project assemble meu-livro      # ou pela interface (aba Qualidade)
.venv/bin/python -m scripts.project audit meu-livro         # integridade do livro inteiro
.venv/bin/python -m scripts.project sync meu-livro          # depois de atualizar o código: alinha sem perder traduções
(cd ../frontend && npm install && npm run build)
.venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8000   # abrir http://127.0.0.1:8000
```

Na aba **Traduzir**: escolha as páginas e o que traduzir (pendentes, com problemas, afetados pelo glossário, toda tradução automática ou parágrafos escolhidos), veja a previsão de custo e tempo de cada motor (Sonnet 5.5, Opus 5.5, Gemini 3.8 Flash, GPT-5.5, GPT-5.4 Nano, Qwen 3.8 27B), marque um, defina o teto de gasto e inicie (`docs/research/11-motores-custo.md`). Há um teto opcional para o projeto inteiro; tarefas interrompidas (servidor encerrado, cancelamento, teto) têm o botão "Retomar…". Na aba **Qualidade**: "Montar PDF traduzido" (só as partes de 20 páginas com texto alterado são refeitas) e as pendências de cada página. Na aba **Páginas**: cada parágrafo com o original e a tradução editável; salvar
cria uma versão nova (a edição é recusada se algum lance, casa, número ou
símbolo mudar); aprovar; histórico com volta a qualquer versão; "Retraduzir…"
com previsão de custo; glossário do projeto.

Tradução em paralelo: `CHESSBOOK_TRANSLATION_WORKERS` (padrão 3) seções ao
mesmo tempo, com o custo previsto de cada uma reservado no teto antes do envio.
O livro de amostra inteiro foi traduzido assim em 34 min por 7,06 pollen
(`docs/research/14-fase7.md`).

**Livros digitalizados**: `scripts.project create` passa pelo OCR (Tesseract)
as páginas que só têm imagem quando a maioria do livro é digitalizada (`--ocr
on` força), com as figurinas reconhecidas pelo desenho, e guarda o resultado no
projeto. Todo parágrafo vindo do OCR pede conferência
com a página original antes da aprovação (`docs/research/13-fase6.md`).

## Documentação

* `docs/research/` — ambiente, repositórios e licenças, spike de PDF, estratégia FAN, amostra, tradução, montagem do PDF, relatório da POC
* `docs/architecture/01-arquitetura.md` — módulos, IR, modelo de dados, pipeline, privacidade, riscos
* `docs/architecture/02-traducao.md` — provedores, o que é enviado, garantias, custo
* `docs/decisions/` — ADRs 0001–0007
* `docs/quality/` — critérios de aceitação, plano de testes, definição da POC
* `docs/plano-execucao.md` — próximas fases por prioridade
* `LICENSES.md` — licenças de terceiros e implicações

## Privacidade

Nenhum livro real, credencial ou arquivo do usuário deve entrar neste
repositório. Os testes usam apenas PDFs sintéticos gerados em tempo de
execução. Credenciais futuras vão em `.env` (ver `.env.example`).

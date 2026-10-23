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
.venv/bin/python -m pytest -q        # 157 testes
.venv/bin/ruff check app tests scripts ../spikes
```

Spike de estratégias de PDF (gera PDFs, PNGs e `results.json`):

```bash
.venv/bin/python ../spikes/pdf_strategies/run_spike.py /tmp/spike-out
```

## Tradução

Configure `.env` a partir de `.env.example` (provedor, chave, modelo e
`CHESSBOOK_PRIVACY_MODE=remote_allowed`) e veja `docs/architecture/02-traducao.md`.
Primeira tradução real feita com GPT-5.4 Nano pela Pollinations
(ver `docs/research/06-primeira-traducao.md`).

## Documentação

* `docs/research/` — ambiente, repositórios e licenças, spike de PDF, estratégia FAN
* `docs/architecture/01-arquitetura.md` — módulos, IR, modelo de dados, pipeline, privacidade, riscos
* `docs/architecture/02-traducao.md` — provedores, o que é enviado, garantias, custo
* `docs/decisions/` — ADRs 0001–0006
* `docs/quality/` — critérios de aceitação, plano de testes, definição da POC
* `docs/plano-execucao.md` — próximas fases por prioridade
* `LICENSES.md` — licenças de terceiros e implicações

## Privacidade

Nenhum livro real, credencial ou arquivo do usuário deve entrar neste
repositório. Os testes usam apenas PDFs sintéticos gerados em tempo de
execução. Credenciais futuras vão em `.env` (ver `.env.example`).

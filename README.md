# Chessbook Translator

Aplicativo **privado** para traduzir livros de xadrez em PDF do inglês para o
português brasileiro, preservando lances, diagramas e a organização das
páginas. Roda no seu computador; só a prosa (com os lances trocados por
marcadores) sai para o serviço de tradução, e só quando você permite.

> **Estado: as 8 fases do plano estão concluídas.** O livro de amostra
> (*Dvoretsky's Endgame Manual*, 441 páginas) foi traduzido inteiro com Claude
> Sonnet 5.5 por 7,06 pollen em 34 minutos: 428/440 páginas montadas sem
> pendência, notação idêntica ao original em todas as traduções, 1220
> diagramas intactos (`docs/research/14-fase7.md`). Falta a revisão humana
> parágrafo a parágrafo, como em qualquer tradução.

## Instalar e usar

```bash
# Debian/Ubuntu (o Tesseract é opcional: só para livros digitalizados)
sudo apt install fonts-liberation fonts-freefont-ttf fonts-dejavu-core tesseract-ocr tesseract-ocr-eng
./instalar.sh      # Python 3.12+, uv e Node.js 20.19+ precisam estar instalados
./iniciar.sh       # http://127.0.0.1:8000
```

Para traduzir, edite o `.env`: `CHESSBOOK_PRIVACY_MODE=remote_allowed` e
`POLLINATIONS_API_KEY=sk_...`. O passo a passo completo está no
**[manual](docs/manual.md)**.

## O que ele faz

* **Projeto**: envio do PDF; o original é copiado e conferido pelo sha256 em
  toda operação. Livros digitalizados passam por OCR com as figurinas
  reconhecidas pelo desenho (protótipos aprendidos no próprio livro).
* **Notação**: lances em inglês, português e figurinas (FAN), inclusive fontes
  de figurinas com letras trocadas; validação com python-chess, encadeada
  entre parágrafos e diagramas; nada é presumido.
* **Tradução**: seis motores pela Pollinations com previsão de custo e tempo
  antes de começar, teto por tarefa e por projeto, seções em paralelo,
  retomada, retradução seletiva (problemas, glossário alterado, troca de
  motor, parágrafos escolhidos). Os lances viram marcadores e voltam
  idênticos; tradução que altere lance, casa, número ou símbolo é recusada.
* **Revisão**: original e tradução lado a lado, com as páginas; edição
  versionada (recusada se mudar a notação), aprovação, histórico, glossário,
  próxima pendência.
* **Montagem**: PDF traduzido com os diagramas intocados, em partes de 20
  páginas reaproveitadas; relatório por página (fonte reduzida, cortes,
  sobreposições, sobra do original, lances ausentes, diagramas alterados) e
  auditoria de integridade do livro inteiro.
* **Backup**: pacote com manifesto e sha256; restauração conferida.
* **Segurança**: só `127.0.0.1`, proteção contra DNS rebinding e CSRF, chave
  só no `.env`, dependências sem vulnerabilidades conhecidas
  (`docs/quality/seguranca.md`).

## Linha de comando

```bash
cd backend
.venv/bin/python -m scripts.doctor --rede                      # confere o ambiente
.venv/bin/python -m scripts.project create ID "Nome" LIVRO.pdf [--ocr auto|on|off]
.venv/bin/python -m scripts.project assemble ID                # PDF traduzido em <projeto>/output/
.venv/bin/python -m scripts.project audit ID                   # integridade do livro inteiro
.venv/bin/python -m scripts.project sync ID                    # depois de atualizar o programa
.venv/bin/python -m scripts.project backup ID                  # .zip com manifesto e sha256
.venv/bin/python -m scripts.project restore ARQUIVO.zip [--como NOVO_ID]
.venv/bin/python -m scripts.evaluate_ocr LIVRO.pdf --pages 21-30  # mede o OCR contra um PDF digital
```

Os projetos ficam em `CHESSBOOK_STORAGE` (padrão `./storage`, fora do
controle de versão). Tradução em paralelo: `CHESSBOOK_TRANSLATION_WORKERS`
(padrão 3).

## Desenvolvimento

```bash
cd backend
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest -q        # 308 testes
.venv/bin/ruff check app tests scripts
cd ../frontend && npm run build      # tsc + vite
```

Os testes usam só PDFs sintéticos gerados em tempo de execução; nenhum livro
real entra no repositório.

## Documentação

* [Manual](docs/manual.md) · [Limitações conhecidas](docs/limitacoes.md) · [Segurança](docs/quality/seguranca.md)
* `docs/plano-execucao.md`: as fases e o que cada uma entregou
* `docs/research/`: investigação e relatórios de cada fase (01–14)
* `docs/architecture/`: arquitetura e tradução
* `docs/decisions/`: ADRs 0001–0007
* `docs/quality/`: critérios de aceitação, plano de testes, definição da POC
* `LICENSES.md`: licenças de terceiros (o projeto é GPL-3.0+ por causa do
  python-chess; o PyMuPDF é AGPL-3.0)

## Privacidade

Nenhum livro real, credencial ou arquivo do usuário entra neste repositório.
O texto enviado para tradução é só a prosa, com os lances trocados por
marcadores; nada sai sem `CHESSBOOK_PRIVACY_MODE=remote_allowed`.

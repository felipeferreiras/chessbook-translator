# Verificação do ambiente de desenvolvimento

Data: 2026-10-22. Executado no contêiner de desenvolvimento desta sessão.

## Repositório encontrado

O repositório `norma-digital-ufc-25` já continha um site Vite/React/Tailwind
("Norma Digital", gerado pelo Lovable) e um tema WordPress. **Nenhum código do
tradutor existia.** Para não interferir no projeto existente, o tradutor foi
criado em uma pasta isolada, `chessbook-translator/`, em um branch próprio
(`claude/chessbook-translator-fase1`). Nenhum arquivo preexistente foi alterado.

> Recomendação: mover `chessbook-translator/` para um repositório próprio
> antes da Fase 2. Os dois projetos não compartilham código, dependências nem
> ciclo de vida.

## Ferramentas disponíveis (verificadas por comando)

| Ferramenta | Versão | Observação |
|---|---|---|
| Python | 3.13.16 | ambiente virtual criado com `uv` |
| Node.js / npm | 22.22.0 / 10.9.4 | para o frontend nas próximas fases |
| uv, poetry, docker | instalados | docker não foi usado |
| Tesseract | 5.3.4 (leptonica 1.82) | instalado nesta sessão via apt; idiomas `eng`, `por`, `osd` |
| pdftoppm (poppler) | instalado | não utilizado |
| Fontes | DejaVu Sans/Serif, FreeSerif | DejaVu Sans contém U+2654–U+265F (peças) |
| Rede | PyPI, npm e `raw.githubusercontent.com` acessíveis | `api.github.com` e Hugging Face bloqueados pelo proxy |

Hardware do contêiner: 4 vCPU, 15 GiB de RAM, sem GPU. Isso basta para
extração, OCR e testes, mas **não** para avaliar modelos locais de tradução
com qualidade útil (ver `02-repositorios-e-licencas.md`, llama.cpp).

## Bibliotecas Python instaladas no ambiente virtual

Versões efetivamente instaladas (`importlib.metadata`):

| Pacote | Versão | Licença declarada no pacote |
|---|---|---|
| pymupdf | 2.0 | AGPL-3.0 ou licença comercial Artifex |
| chess (python-chess) | 1.11.2 | GPL-3.0-or-later |
| pypdf | 6.21.2 | BSD-3-Clause |
| weasyprint | 70.0 | BSD |
| fonttools | 4.67.0 | MIT |
| pillow | 13.0.0 | MIT-CMU |
| numpy | 2.5.4 | BSD-3-Clause e outras permissivas |
| pypdfium2 | 5.14.0 | BSD-3-Clause / Apache-2.0 |
| pdfminer.six | 20260107 | MIT |
| pytest | 9.1.1 | MIT |

`pypdf`, `pypdfium2` e `pdfminer.six` foram instalados apenas para avaliação
de alternativas; não são dependências do núcleo atual.

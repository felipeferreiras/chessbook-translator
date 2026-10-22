# Licenças

O código deste projeto é licenciado sob **GPL-3.0-or-later**, por compatibilidade
com as dependências abaixo. Ver `docs/decisions/ADR-0004-licencas.md`.

Verificação feita em 2026-10-22 no arquivo de licença do repositório e nos
metadados do pacote publicado. Não constitui parecer jurídico.

## Dependências em uso

| Componente | Versão | Licença | Implicação |
|---|---|---|---|
| python-chess (`chess`) | 1.11.2 | GPL-3.0-or-later | distribuição do conjunto exige GPL |
| PyMuPDF | 2.0 | AGPL-3.0 ou comercial (Artifex) | oferecer o código-fonte a usuários pela rede, se houver; uso privado local sem obrigação prática |
| fontTools | 4.67.0 | MIT | — |
| NumPy | 2.5.4 | BSD-3-Clause e outras permissivas | — |
| Pillow | 13.0.0 | MIT-CMU | — |
| WeasyPrint (spike/modo B) | 70.0 | BSD-3-Clause | — |
| pytest, ruff (desenvolvimento) | 9.1.1 / atual | MIT | — |
| Tesseract (binário do sistema, opcional) | 5.3.4 | Apache-2.0 | — |
| DejaVu Sans (fonte do sistema) | — | Bitstream Vera + domínio público | incorporação permitida |

## Planejadas (verificadas, ainda não usadas)

chess.js 1.4.0 (BSD-2-Clause), pdfjs-dist 6.4.299 (Apache-2.0), SDK `anthropic`
2.1.0 (Apache-2.0), OCRmyPDF 17.13.0 (MPL-2.0), Noto Sans Symbols 2 (OFL-1.1),
llama.cpp (MIT; pesos de modelos com licenças próprias), Docling 2.141.0 (MIT;
licenças dos pesos **não verificadas**).

## Descartadas

Chessprint — CC BY-NC-SA 4.0 (não comercial, compartilhamento pela mesma
licença), finalidade incompatível. Lichess (AGPL-3.0) — usado só como
referência, sem código copiado.

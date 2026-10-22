# ADR-0004 — Uso de componentes GPL/AGPL em aplicação privada

**Estado:** aceito · **Data:** 2026-10-22

## Contexto
python-chess é GPL-3.0+; PyMuPDF é AGPL-3.0 (ou comercial). São os componentes
tecnicamente mais adequados (ver `docs/research/02-repositorios-e-licencas.md`).

## Decisão
* Usar ambos, porque a aplicação é privada e não será distribuída nem oferecida
  a terceiros pela rede.
* O código do projeto é declarado GPL-3.0-or-later, compatível com os dois,
  para que um compartilhamento futuro não exija relicenciamento.
* PyMuPDF fica isolado atrás de adaptadores; alternativas permissivas mapeadas:
  pypdfium2, pdfminer.six, WeasyPrint/reportlab.
* Fontes: somente fontes livres com incorporação permitida (DejaVu, Noto/OFL).
  Fontes extraídas dos livros não são redistribuídas.
* Modelos locais: licença dos pesos verificada caso a caso, separada da licença
  do llama.cpp.

## Consequências
Se a aplicação for aberta a outras pessoas pela rede, a AGPL exige oferecer o
código-fonte (ou licença comercial do PyMuPDF). Revisar este ADR antes disso.

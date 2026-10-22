# ADR-0006 — OCR seletivo e desconfiado

**Estado:** aceito · **Data:** 2026-10-22

## Decisão
* Tesseract (Apache-2.0) para prosa, apenas em páginas/regiões sem texto
  utilizável; imagem original sempre preservada.
* Regiões de notação vindas de OCR passam pelo analisador léxico (átomos
  `SUSPICIOUS` para padrões como `3.865` e `\f3`) e pela validação; nada de
  substituições globais de caracteres.
* Reconhecimento especializado de figurinas em imagem (comparação de glifos,
  como no probe de fontes) é trabalho da Fase 6.
* OCRmyPDF (MPL-2.0) é opcional para gerar camada de texto pesquisável no
  original de trabalho, nunca no arquivo original.

## Evidência
No spike, `2.♘f3 ♘c6 3.♗b5` foi lido como `2.\f3 \c6 3.865`. O teste
`test_characterization_tesseract_corrupts_fan` garante que, nesse caso, apenas
`e4` e `e5` são dados como validados e a região vai para revisão.

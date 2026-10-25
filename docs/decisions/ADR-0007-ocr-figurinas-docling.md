# ADR-0007: figurinas em imagem pelos protótipos do livro; Docling avaliado e não adotado

**Estado:** aceito · **Data:** 2026-10-24 · Complementa a ADR-0006.

## Contexto

O Tesseract lê figurinas como símbolos ou letras. Às vezes lê uma letra
válida de outra peça: o rei vira `B`. E a figurina estraga a leitura da casa
ao lado. As referências das fontes livres instaladas diferem do desenho das
editoras: o rei do Dvoretsky tem nota 0,3–0,5 contra elas.

## Decisão

* **A peça vem do desenho.** Ela é decidida pela imagem recortada, nunca pelo
  caractere que o OCR leu.
* **Protótipos do próprio livro.** As figurinas do livro são aprendidas por
  agrupamento: desenhos iguais recebem a mesma peça. Só grupos grandes, com
  margem segura contra outra peça, viram protótipos.
* **Segunda passada.** Cada figurina reconhecida é pintada como a letra da
  peça e o OCR é refeito. A letra volta a ser figurina pela posição.
* **Conferência obrigatória.** Todo segmento vindo de OCR pede conferência com
  a imagem antes da aprovação. Os avisos específicos apenas apontam onde olhar.
* **Docling avaliado e não adotado (2026-10-25).**
  * Nas mesmas páginas, o Docling com Tesseract empata ou perde na prosa
    (94,7–96,6 % contra 96,4–98,1 %) e não lê lances com peça (cerca de 1 %
    contra 71–84 %).
  * O híbrido (layout do Docling com o nosso OCR) varia de −5,5 a +0,6 ponto
    na prosa e custa o dobro do tempo.
  * Ele traria 6 GB de dependências. Fica a avaliação
    (`scripts/evaluate_docling.py`) para livros de layout mais complexo, onde
    a ordem de leitura dele pode compensar.

## Consequências

* **Custo:** cerca de 5 s por página digitalizada (duas leituras), uma vez por
  livro, com o resultado guardado em `ocr.json`.
* **Erros sem aviso:** 1–2 % dos lances com peça saem errados sem aviso
  específico, medidos contra o texto digital. A conferência humana cobre esse
  resto.
* **Diagramas digitalizados:** são preservados e protegidos, mas não lidos
  (sem FEN). Por isso não há validação por legalidade nessas páginas.

# Estratégia para reconhecer e preservar FAN

## O problema, demonstrado

O mesmo parágrafo, visualmente idêntico (`2.♘f3 ♘c6 3.♗b5`), produz três
camadas de texto diferentes conforme a fonte usada pelo editor. Os três casos
estão nos fixtures e nos testes (`tests/test_pdf_fixtures.py`):

| Cenário | O que a página mostra | O que a extração devolve |
|---|---|---|
| Unicode | ♘f3 | `♘f3` (U+2658) |
| Fonte figurina por letras (comum em fontes de editoras) | ♘f3 | `Nf3` |
| Fonte com Área de Uso Privado | ♘f3 | `f3` |
| Página digitalizada + Tesseract | ♘f3 | `\f3` (e `♗b5` → `865`) |

Uma substituição global ("troque ♘ por N", ou "troque N por C") falharia em
todos os casos: no segundo, `N` já é a figurina; no terceiro, o caractere não
tem significado padrão; no quarto, o símbolo se perdeu.

## Princípio: separar quatro perguntas

1. **Qual glifo está desenhado?** — camada de glifos, por (fonte, caractere).
2. **Isto é notação?** — análise léxica sobre o texto resolvido.
3. **Qual lance é este?** — validação contra a posição, quando conhecida.
4. **Como escrever na saída?** — renderização, a partir das camadas acima.

Cada pergunta tem um módulo e um estado de confiança próprios. Nenhuma camada
"conserta" a anterior.

## Camada 1 — resolução de glifos (por fonte)

Implementado em `app/extraction/glyph_probe.py` (protótipo).

1. A extração (`rawdict`) fornece, para cada caractere, a fonte e a caixa.
2. Caracteres candidatos: letras de peça (K Q R B N D T C P), símbolos U+2654–
   U+265F e qualquer ponto de código de uso privado (categoria `Co`).
3. Para cada par (fonte, caractere), o glifo é recortado da **página
   renderizada**, normalizado (32×32) e comparado por correlação com desenhos
   de referência de figurinas e de letras.
4. O resultado é uma **proposta** de mapa `{fonte: {caractere: figurina}}`,
   exigindo pontuação mínima e margem sobre o segundo candidato.
5. A interface mostra os glifos recortados lado a lado e pede confirmação. O
   mapa confirmado vale apenas para aquela fonte naquele documento.
6. Regiões de diagrama são excluídas (peças sobre casas coloridas não são
   notação e pontuam mal — observado no protótipo).

Resultado nos fixtures: `N→♘` e `B→♗` na fonte figurina por letras, `→♘`
e `→♗` na fonte de uso privado; nenhuma letra da prosa foi confundida
com figurina.

Sinais adicionais previstos (Fase 3): nome da fonte (Figurine, Chess, Merida,
Diagram etc.), tabela `ToUnicode` ausente ou inconsistente, tabela `cmap` da
fonte incorporada (extraível com PyMuPDF + fontTools) e consistência
estatística (uma "letra N" que só aparece antes de casas é suspeita).

**Limitação reconhecida:** as referências usam a DejaVu Sans. Desenhos de
editoras diferem; será necessário um conjunto de referências com várias
fontes livres e, sobretudo, a confirmação humana. Glifos Type 3 sem
mapeamento continuam dependendo da comparação visual.

## Camada 2 — análise léxica

Implementado em `app/chess/notation/lexer.py`. Opera sobre o texto já
resolvido e devolve átomos com posições exatas, sem alterar a string:

* números de lance (`12.`, `12...`, `12…`), lances SAN e algébrica longa,
  roques com `O` ou `0`, promoções (`=Q`, `Q`, `(Q)`, `/Q`), `e.p.`, xeque,
  mate, sinais `!`, `?`, `!?`, `?!`, `!!`, `??`, avaliações (`±`, `∓`, `+-`,
  `=`, `∞`…), resultados e parênteses de variante;
* referências a casas na prosa ("o cavalo em f3") não são lances;
* parênteses de prosa não abrem variante, mas sua profundidade é rastreada;
* notação descritiva (`P-K4`, `N-KB3`) é detectada e marcada como não
  suportada;
* padrões típicos de OCR (`3.865`, `\f3`, `&f6`) viram átomos `SUSPICIOUS`.

## Camada 3 — convenção e validação

* `convention.py` detecta a convenção por estatística explicável: letras
  exclusivas do inglês (K, Q, N), exclusivas do português (R=rei, D, T, C),
  figurinas e descritiva. Só `R` e `B` não decidem nada.
* `validate.py` resolve cada lance contra `board.legal_moves` do python-chess,
  com o alfabeto da convenção. `R` numa convenção indeterminada é testado como
  torre **e** como rei.
* Estados possíveis: `validated`, `ambiguous`, `illegal`, `no_context`,
  `unrecognized_piece`. Avisos distinguem o que exige revisão (marcador de
  xeque sem xeque, captura sem `x`, letra resolvida só pela legalidade,
  número de lance incompatível) do que é informativo.
* Regras conservadoras: nenhuma posição inicial é presumida por padrão;
  depois de um lance ambíguo, ilegal ou suspeito a posição deixa de ser
  conhecida; um trecho que começa sem número depois de prosa não herda a
  posição (exceto de um diagrama com FEN confirmada); variantes entre
  parênteses voltam à linha principal; números de lance menores que o atual
  (padrão "após 4.♗a4..., a troca 4.♗xc6...") são tratados como ramificação
  implícita e registrados.

## Três representações por lance

| Camada | Onde fica | Exemplo |
|---|---|---|
| Original | `Atom.text` + posições + fonte/página (na persistência) | `♘f3` (ou `N` na fonte figurina) |
| Normalizada | `MoveAnalysis.uci` + `fen_before`, só se `validated` | `g1f3` em `rnbqkbnr/.../RNBQKBNR w KQkq - 0 1` |
| Saída | `render_region` conforme a preferência | `Cf3`, `Nf3`, `♘f3` ou o original |

A conversão troca apenas o caractere de peça (e de promoção) dentro dos limites
exatos do lance; desambiguação, roque, xeque e sinais do autor são mantidos.
Política padrão `strict`: lance não validado não é convertido e fica listado.

## Tradução sem tocar nos lances

`app/translation/guard.py` substitui cada trecho de notação por um marcador
opaco (`⟦1⟧`) antes da tradução e exige, na volta, todos os marcadores
exatamente uma vez e o mesmo multiconjunto de casas na prosa. Qualquer
divergência rejeita o segmento para revisão. O tradutor de prosa nunca vê um
lance, e a conversão de notação é feita depois, pelo módulo de notação.

## Saída: fontes

Fontes incorporadas costumam ser subconjuntos e não podem ser reaproveitadas
para texto novo. A saída usa fontes livres com figurinas e acentos do
português (DejaVu Sans; candidata: Noto Sans Symbols 2 combinada com uma serifa
livre). A substituição da fonte das figurinas é registrada no relatório como
alteração visual.

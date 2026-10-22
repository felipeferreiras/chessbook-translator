# Spike: duas estratégias de preservação de PDF

Script: `spikes/pdf_strategies/run_spike.py`. Página sintética A5 gerada por
`backend/tests/fixtures/synthetic.py`, com título, parágrafo com FAN, diagrama
vetorial (casas desenhadas, peças como **texto** numa fonte — o pior caso),
legenda, segundo parágrafo, nota de rodapé e número de página. A tradução
usada é uma tradução humana de referência (não saída de máquina), cerca de
10–25 % mais longa que o original.

Reprodução:

```bash
cd chessbook-translator/backend
.venv/bin/python ../spikes/pdf_strategies/run_spike.py /caminho/de/saida
```

## Estratégias comparadas

**A — Edição do original.** Remove por redação apenas os blocos de prosa
(`apply_redactions` com `images=NONE`, `graphics=NONE`), mantendo diagramas,
imagens e vetores, e escreve a tradução nas mesmas regiões com
`insert_htmlbox`, com redução tipográfica limitada a 15 %. Variantes:
*A-estrita* (caixa exata do bloco extraído) e *A-expandida* (o bloco pode
ocupar o espaço livre abaixo dele até o próximo elemento).

**B — Reconstrução a partir de estrutura intermediária.** Gera HTML/CSS a partir
dos blocos e renderiza com WeasyPrint. O diagrama é recortado do original como
PDF vetorial e convertido para SVG com o texto transformado em curvas.

## Resultados medidos (2026-10-22)

Idênticos nos cenários `fan_unicode` e `fan_letter_font`:

| Métrica | A-estrita | A-expandida | B |
|---|---|---|---|
| Páginas na saída | 1 | 1 | 1 |
| Diagrama: posição/tamanho | idênticos | idênticos | mesmo tamanho, deslocado 50 pt (reflow) |
| Diagrama: pixels alterados (> 32 níveis de cinza) | 0 % | 0 % | 7,3 % (2,2 % após média 4×4 px) |
| Lances esperados ausentes na saída | 0 de 16 | 0 de 16 | 0 de 16 |
| **Blocos ausentes na saída** | **4 de 6** (título, legenda, nota, nº da página) | 1 de 6 (nº da página) | 0 de 6 |
| Resíduo do texto em inglês | nenhum | nenhum | nenhum |
| Redução tipográfica aplicada | 4,5–6 % nos parágrafos | 8–10 % na legenda e na nota | nenhuma (texto reflui) |

OCR (Tesseract 5.3.4, `eng`, página rasterizada a 300 dpi):

```
esperado: 1.e4 e5 2.♘f3 ♘c6 3.♗b5 a6 This is the main line of the Ruy Lopez.
OCR:      1.e4 e5 2.\f3 \c6 3.865 a6 This is the main line of the Ruy Lopez.
```

## Conclusões

1. **Perda silenciosa na estratégia A.** Quando o texto não cabe,
   `insert_htmlbox` devolve um valor negativo e *não escreve nada*. Sem
   verificação, título, legenda, nota e número da página desaparecem sem erro.
   Isso virou um teste de caracterização
   (`test_characterization_insert_htmlbox_writes_nothing_when_text_does_not_fit`)
   e uma regra obrigatória: todo bloco renderizado é procurado na página gerada.
2. **A caixa extraída não é a caixa de composição.** Até o número "47", que não
   muda na tradução, não coube na caixa exata do bloco: a caixa extraída mede
   os glifos, não a entrelinha. O módulo de layout precisa calibrar cada bloco
   recompondo o texto original antes de compor a tradução, e expandir a caixa
   no espaço livre com regras de margem (rodapés e números de página exigem
   regra própria).
3. **A preserva diagramas de forma exata; B preserva o conteúdo.** Em A, o
   diagrama não é tocado (0 pixel alterado). Em B, o diagrama é vetorial e
   visualmente idêntico, mas a página reflui. A diferença de 7,3 % em B vem de
   suavização e deslocamento subpixel do SVG com texto em curvas; a métrica de
   pixels sozinha não serve como critério de aprovação sem alinhamento prévio.
4. **A não depende da fonte figurina original.** A tradução é escrita com uma
   fonte nova (DejaVu, com figurinas Unicode). Fontes incorporadas costumam ser
   subconjuntos e não podem ser reutilizadas para texto novo; a troca da fonte
   das figurinas precisa ser registrada como alteração visual.
5. **OCR genérico é inaceitável para notação.** O padrão `3.865` mostra que um
   erro de OCR pode parecer texto válido. Daí o detector de átomos suspeitos e
   a regra de perder a posição após qualquer trecho suspeito.

## Decisão resultante

Estratégia **híbrida por página**, com a mesma representação intermediária
(ver ADR-0002):

* PDF digital, modo fidelidade: **A-expandida** com calibração, redução de até
  10–15 %, verificação de presença de cada bloco e, se algum bloco não couber,
  marcação da página para revisão e oferta de recomposição em B só daquela
  página.
* PDF digitalizado: nunca sobrepor tradução à imagem com texto; usar B com o
  diagrama recortado da imagem original (raster em resolução nativa).
* Modo adaptativo: B para todas as páginas.

## Limitações do spike

* Uma única página sintética, com layout simples e de uma coluna.
* Tradução humana de referência; a variação de comprimento real será medida na
  Fase 2.
* Não testa imagens rasterizadas de diagramas, duas colunas, notas extensas,
  hifenização em português, nem PDFs com fontes Type 3.

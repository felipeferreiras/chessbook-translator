# Montagem do PDF traduzido (estratégia A)

Data: 2026-10-23. Amostra de 16 páginas, tradução do Gemini 3.8 Flash com as
formas portuguesas de lugares e abreviações de competição (regra 5 do prompt).
Código: `app/layout/compose.py`, `scripts/assemble_pdf.py`. O PDF gerado, as
imagens lado a lado e o relatório ficam fora do repositório.

## Como a página é montada

1. **Redação só do texto traduzido.** Imagens, vetores, fundos e diagramas em
   fonte ficam intactos. A área apagada é recortada para fora de cada
   tabuleiro (`away_from`): a caixa do glifo de uma legenda chegava a invadir
   a moldura em 3,7 pt e a redação apagava a borda inferior do diagrama.
2. **Fonte substituta com as mesmas métricas.** Times New Roman → Liberation
   Serif, Arial → Liberation Sans (OFL); figurinas e símbolos do Informator na
   FreeSerif. Century Gothic e Broadway (títulos) não têm equivalente métrico
   e a troca é registrada no relatório.
3. **Fluxo por coluna.** Blocos traduzidos consecutivos da mesma coluna, sem
   nada fixo entre eles (tabuleiro, notação não traduzida, rótulos), formam
   uma sequência. Na sequência, cada bloco mantém o espaçamento original para
   o anterior e pode empurrar os seguintes para baixo até o próximo obstáculo
   ou a margem inferior. Se a sequência não couber, a fonte de toda a
   sequência é reduzida por igual (97 %, 94 %, 91 %, 88 %, 85 %). Só depois
   disso cada bloco é ajustado no próprio lugar, com qualquer redução; abaixo
   de 85 % o bloco vai para revisão.
4. **Linha única** (títulos, nomes de jogadores, local e ano): se estava
   centralizada na coluna ou na página, ocupa a largura toda, centralizada;
   senão pode crescer para a direita até o fim da coluna, nunca sobre outro
   bloco ou tabuleiro.
5. **Sumário** (tabulações no texto extraído): tabela com o número da página
   alinhado à direita.

## Verificações por página

| Verificação | Como |
|---|---|
| Texto presente | início de cada bloco encontrado no texto da página gerada |
| Notação | cada trecho protegido encontrado na página gerada |
| Original removido | nenhum texto sob as áreas apagadas |
| Sobreposição | áreas escritas (sem a meia entrelinha) não se cruzam |
| Diagramas | diferença de pixels dentro da moldura do tabuleiro, original × gerado |

A moldura é encontrada pelas linhas e colunas com mais de 60 % de tinta. Com
o limite inicial de 80 % nenhuma linha era detectada (máximo medido: 82–84 %
em uma linha só), a comparação usava a caixa do glifo inteira e acusava como
"diagrama alterado" a legenda traduzida que cai na sobra da caixa.

## Resultado na amostra

| Métrica | Valor |
|---|---|
| Blocos traduzidos | 208 |
| Escritos | 208 |
| Texto ou notação ausente | 0 / 0 |
| Texto original remanescente | 0 |
| Sobreposições | 0 |
| Diagramas verificados / alterados | 32 / 0 |
| Blocos em tamanho original | 166 |
| Reduzidos | 42 (13 a 97 %, 18 a 94 %, 8 a 91 %, 3 a 87–88 %) |
| Para revisão | 0 |
| Páginas sem pendências | 16 de 16 |
| Trechos de prosa em negrito / itálico | 49 / 6, todos devolvidos pelo tradutor e reaplicados |

Números da segunda rodada (2026-10-23), com negrito e itálico da prosa
enviados como `<b>`/`<i>`: 208/208 segmentos aceitos sem nenhum aviso, 13
chamadas, 46.078 tokens de entrada e 46.108 de saída. A tradução mudou um
pouco de comprimento e o bloco que antes ficava a 81 % passou a caber.

## Defeitos encontrados na inspeção visual e corrigidos

* **Bloco escrito sobre o seguinte** (p. 21): o bloco seguinte começava 1,3 pt
  dentro da folga de entrelinha do anterior e não era visto como obstáculo; a
  expansão o cobriu. Corrigido na detecção e coberto pela verificação de
  sobreposição.
* **Sentido trocado pela tradução** (p. 21): um lance da partida em linha
  própria e a correção na linha seguinte ("1...♔g6! was necessary") estavam
  no mesmo marcador. O tradutor não tinha como saber a qual dos dois a prosa
  se referia e escreveu "Era necessário" antes do lance errado. Agora um
  marcador nunca atravessa uma quebra de linha. Perda de quebra ou tabulação
  e marcador mudado de linha passaram a **bloquear** a aceitação. O aviso de
  quebras que existia antes era falso: comparava com o texto original, que
  tinha a quebra dentro do marcador.
* **Títulos e assinatura quebrados** ("Capítulo / 10"): linha única
  centralizada na página não era reconhecida, e espaços soltos à esquerda
  criavam um recuo falso de 18 pt.
* **Parágrafos reduzidos com espaço livre na página** (p. 13): resolvido pelo
  fluxo por coluna.
* **Negrito e itálico da prosa perdidos** (verbetes do índice, capítulos no
  sumário, título de obra no prefácio): agora vão ao tradutor como marcas e
  voltam aplicados; marcas malformadas bloqueiam a aceitação.

## Limitações conhecidas

* Fundos sombreados ficam na posição original; quando o fluxo desloca o texto,
  o sombreado pode não acompanhar exatamente.
* Blocos só de notação não são deslocados (mantêm a fonte figurina original);
  eles encerram uma sequência de fluxo.
* Títulos em Century Gothic e Broadway aparecem em Liberation Sans.
* O índice traduzido mantém a ordem alfabética do original.

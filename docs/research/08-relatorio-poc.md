# Relatório da POC (critérios P1–P11)

Data: 2026-10-23. Amostra de 16 páginas; tradução Gemini 3.8 Flash pela
Pollinations; montagem pela estratégia A. Gerado por
`scripts/poc_report.py`, que relê o PDF traduzido **do zero** (extração,
leitura de diagramas e validação de lances) e compara com o original nas
mesmas páginas. Saídas (`poc.json`, `poc.html`) ficam fora do repositório.

## Resultado

| # | Critério | Tipo | Resultado |
|---|---|---|---|
| P1 | Original intacto | objetiva | ✅ sha256 igual antes, durante e depois |
| P2 | Nenhum bloco perdido | objetiva | ✅ 208/208 blocos escritos, nenhum pendente |
| P3 | Notação nunca corrompida | objetiva | ✅ 482/482 lances confirmados relidos com a mesma posição e o mesmo UCI |
| P4 | Nenhuma conversão silenciosa | objetiva | ✅ todos os trechos de notação encontrados byte a byte; nenhuma conversão |
| P5 | Diagramas preservados | objetiva + humana | ✅ 32/32 com a mesma caixa (±1 pt), as mesmas peças e 0 pixel alterado na moldura |
| P6 | Legenda junto do diagrama | objetiva | ✅ 49 legendas, nenhuma afastada mais de 10 pt |
| P7 | Marcadores íntegros | objetiva | ✅ 0 traduções aceitas com violação |
| P8 | Sem omissão (heurística) | heurística | 1 segmento com razão 0,79 (limite 0,8), listado para revisão |
| P9 | Qualidade da tradução | humana | ✅ aprovado pelo usuário em 2026-10-23 |
| P10 | Layout | objetiva | ✅ 0 sobreposições, 0 fora da página, nenhuma redução > 15 % sem sinal |
| P11 | Relatório | objetiva | ✅ este documento e `poc.json` |

Notas de P3: 8 lances validados **com aviso de revisão** no original são
contados à parte (7 iguais; 1 é a menção de um plano na prosa que só valia
por acaso na posição suposta). 14 lances da p. 201 só têm leitura confirmada
na versão traduzida (ver abaixo); não há como terem sido corrompidos e são
listados, sem reprovar.

## O que a releitura encontrou e foi corrigido

A primeira execução deu **413/490**. Cada diferença foi investigada:

1. **"de" lido como lance.** No estilo do livro, captura de peão pode ser
   escrita só com as colunas ("hg"). Em português, "de" é a palavra mais
   comum e virava "d×e" sem posição, quebrando a cadeia de lances seguinte.
   Agora a captura abreviada só é lance logo depois de número de lance,
   reticências, outro lance ou "(". No livro inteiro em inglês as contagens
   não mudaram (24.590 validados, 841 capturas abreviadas).
2. **Variantes em negrito.** O negrito da linha principal era aplicado por
   maioria a cada marcador; um marcador com lance principal e variante entre
   parênteses saía todo em negrito, apagando a distinção que o livro faz.
   Agora o negrito é copiado caractere a caractere do original.
3. **Prosa tirada de dentro de um parêntese** (p. 201). "(5 ♖d7+! is
   threatened)" virou um aviso de ameaça no início do parágrafo, mudando o
   sentido. Os parênteses estavam escondidos dentro de dois marcadores
   diferentes. Agora um marcador nunca contém parêntese de variante sem o
   par, e um parêntese com notação precisa manter os mesmos marcadores e a
   presença de prosa — senão a tradução é recusada e reenviada.
4. **`missing_check_marker` passou a pedir revisão**, como seu espelho
   `check_marker_without_check`: o livro sempre marca o xeque; um lance que
   dá xeque sem "+" indica posição suposta errada (14 lances no livro todo).

Também nesta etapa, por decisão do usuário, os **fundos sombreados são
retirados** da versão traduzida (476 retângulos na amostra), sem tocar em
texto, imagens nem tabuleiros; a verificação de diagramas continua em 0.

## Limitações que continuam

* A leitura do original trata "(5 ♖d7+! is threatened)" como variante e perde
  a posição; o português, que começa o parêntese com prosa, não. Reclassificar
  parênteses que começam com lance e terminam em prosa melhoraria a validação
  do livro em inglês; não foi feito para não mudar a análise sem medir.
* Títulos em Century Gothic e Broadway saem em Liberation Sans.
* O índice mantém a ordem alfabética do original.
* Motor B (recomposição por página) ainda não existe; nenhuma página da
  amostra precisou dele.

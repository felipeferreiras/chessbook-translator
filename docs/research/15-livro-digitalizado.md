# Livro digitalizado de verdade: *Grandmaster Preparation – Calculation*

Data: 2026-10-27. Livro do usuário (Jacob Aagaard, Quality Chess, 2012), 306
páginas, todas imagens (digitalização a 4122×5900). O usuário traduziu o
livro com o Gemini e relatou três problemas: os 4736 segmentos marcados como
"pedem atenção", diagramas que não apareciam no livro final, e a dama lida
como "W". Os testes abaixo usam a tradução de mentira (`PseudoProvider`):
nenhum crédito gasto, nenhum texto do livro no repositório.

## O que estava errado

| Sintoma | Causa |
|---|---|
| Diagramas ausentes no PDF final | o PDF traduzido só levava páginas com algum texto para traduzir: página só com diagramas, foto ou em branco sumia, e a numeração deslocava (299 de 306 páginas). Também: coordenadas e marcas em volta do tabuleiro eram apagadas e reescritas |
| Tabuleiros não achados | a digitalização é levemente torta: a moldura chega aos pedaços e não fechava o quadrado; a hachura fina e clara, com peças por cima, não passava no teste de casas alternadas. Num trecho de 20 páginas, 1 de 6 tabuleiros achados na p. 21 |
| Texto de diagrama como parágrafo | do tabuleiro não achado, o OCR "lia" casas e peças como letras: 126 de 296 segmentos do trecho eram lixo |
| Dama como "W" | o grupo de desenhos da dama ficou mais parecido com o rei da referência (margem 0,02): sem protótipo, o lance saiu com a letra lida |
| Tudo pedindo atenção | o aviso geral de OCR ("confira com a imagem") estava em todo parágrafo e contava como pendência |
| Montagem lenta | a imagem de 24 MP era renderizada a cada bloco: mais de 10 min para 20 páginas |
| Coordenadas sob o texto | o Tesseract juntou a fileira "a b c … h" com a linha de baixo; uma palavra mal lida ocupava as duas e o bloco traduzido subia sobre as coordenadas (7 diagramas "alterados" no livro). A fileira também saiu lida junta ("bede", 4 letras) e passava por palavra |
| Legenda sobre o tabuleiro | o número do exercício "(3)", encostado na faixa protegida, e a legenda abaixo do tabuleiro viraram um bloco só, que cobria o tabuleiro: a tradução foi escrita por cima dele (p. 58) |
| Palavras curtas perdidas | na faixa em volta do diagrama, toda palavra de até 3 letras saía, inclusive o fim de linha da coluna vizinha ("can", "As") |

## Correções

* **Tabuleiros**: pedaços de traço juntados (horizontal e vertical, com
  tolerância à inclinação) e casas alternadas por duas medidas (tom médio;
  fração de pixels escuros pela mediana de cada cor de casa). Todos os 618
  tabuleiros emoldurados do livro passam; uma caixa de texto emoldurada não.
* **Diagrama inteiro protegido**: tabuleiro, coordenadas, vez de jogar e número
  do exercício (`diagram_area`); linhas e palavras de texto nunca entram nessa
  área. Na faixa, sai só o trecho feito inteiro de marcas e coordenadas; um
  trecho com palavra de verdade fica inteiro. Um bloco que atravessa um
  diagrama é partido acima e abaixo dele.
* **Livro inteiro no PDF**: páginas sem texto vão como no original; a
  auditoria confere que o PDF tem todas as páginas do livro.
* **Figurinas do livro**: os grupos de desenhos achados no começo dos lances
  aparecem com imagem, quantidade e o que o OCR leu; o usuário escolhe a peça e
  o livro é relido com elas (a decisão fica no projeto, vale num OCR refeito e
  vai no backup). Grupo confirmado vale mesmo com 2 ocorrências.
* **Leitura única corrigida e anotada**: "♖el" → "♖e1", "4l." → "41.", "t" no
  fim do lance → "†".
* **Atenção só no que importa**: o aviso geral não conta; avisos sobre prosa
  ("Morales," lido sem confiança) também não; a confiança de um lance é a das
  letras da casa (a da palavra cai por causa da figurina). Trechos ilegíveis
  curtos ficam como na imagem sem pedir nada. "Aprovar página".
* **Sincronizar e reler em segundo plano**, com andamento; montar e auditar
  com o OCR desatualizado pedem a sincronização em vez de refazer o OCR
  escondido.

## Resultado no livro inteiro

| | antes | depois |
|---|---|---|
| Páginas no PDF traduzido | 299 de 306 | 306 de 306 |
| Tabuleiros achados | — | 617 |
| Diagramas alterados na montagem | 7 (coordenadas e legenda reescritas) | **0 de 617** |
| Páginas sem pendência na montagem | — | 274 de 306 (as outras: 30 sobreposições, 3 textos que não couberam, 1 corte, 26 blocos com fonte reduzida demais) |
| Lances com ♕ | 0 | 3829 |
| Lances começando por "W" | ~1800 | 79 (com aviso) |
| Segmentos que pedem atenção | 100 % | 32 % (789 de 2469) |
| Trechos ilegíveis que ficam como na imagem | 126 de 296 no trecho de 20 páginas | 82 no livro inteiro |
| Montagem de 20 páginas | > 10 min | 35 s |
| Montagem do livro | — | 8 min (refazer depois de uma mudança: as partes iguais são reaproveitadas) |
| OCR do livro (4 núcleos) | — | 17–18 min; reler com figurinas: 8 min |
| Auditoria | — | original intacto; notação idêntica em todas as traduções; PDF com todas as páginas |

Sincronizar depois de atualizar o programa (OCR refeito, figurinas confirmadas
mantidas pelo desenho): 18 min; das 2469 traduções, só os parágrafos cujo texto
mudou voltaram a pendentes (de 4 a 97, conforme a mudança).

A confirmação das figurinas, feita olhando as imagens dos 40 grupos: 14 damas,
reis, torres, cavalos e bispos claros; 9 grupos marcados "não é peça" (o "x"
da captura sozinho, ou peça colada no "x", que pintada como letra apagaria o
"x").

Os 32 % que ainda pedem atenção são, na maioria, lances que o OCR estragou de
verdade ("35.♖xaG", "26.♕65!", "♘FB") ou casas lidas com pouca confiança: é
trabalho de revisão, que agora aparece separado do resto.

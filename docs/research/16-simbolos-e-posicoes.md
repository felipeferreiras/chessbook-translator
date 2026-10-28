# Símbolos, primeira linha, original corrigível e posições dos diagramas

Data: 2026-10-28. Livro: *Grandmaster Preparation – Calculation* (306 páginas
digitalizadas), a partir do relato do usuário depois de criar um projeto novo:
"?!" lido como "2!", "c1=♕" lido como "cl=", ± e ⩲ ilegíveis, "♕c4†" lido sem
o xeque, a primeira linha das páginas fora da tradução, nenhuma forma de
corrigir o texto lido antes de traduzir, e as posições dos diagramas não lidas
nem mostradas na revisão. Testes com a tradução de mentira; nenhum crédito
gasto, nenhum texto do livro no repositório.

## O que estava errado

| Relato | Causa |
|---|---|
| Primeira linha das páginas fora | "Cabeçalho" era tudo que começava a menos de 55 pt do alto (medida do livro digital de amostra). Aqui a primeira linha do texto fica a 44 pt: o título da partida no alto de cada página ("1. Golod – Gerzhoy…" e o lance seguinte) sumia |
| "?!" como "2!", "!?" como "!2" | o Tesseract não conhece esses desenhos nesta fonte |
| xeque e vantagem iguais | o xeque do livro é "†"; o Tesseract lê "†" e "±" os dois como "+" (às vezes "t", "¢", "}") |
| "c1=♕" como "cl=" ou "e1=WtF" | a figurina da promoção não estava no começo da palavra, onde as figurinas eram procuradas; o "1" vira "l" |
| "♕c4†" como "♕c4" | o Tesseract deixa o símbolo fora da palavra |
| casas trocadas sem aviso | "♕g4" lido "♕e4", "26.♕g7" lido "26.♕e7" (modelo rápido do Tesseract) |

## Correções

* **Cabeçalho e rodapé só quando se repetem** (título corrente em várias
  páginas, com ou sem o número da página, ou o número sozinho). O título
  corrente passa a ser traduzido.
* **Símbolos pelo desenho**: o que vem depois da casa de cada lance é
  recortado e partido em desenhos (o "!!" são dois); os desenhos iguais do
  livro formam grupos; cada grupo recebe um símbolo pela referência (FreeSerif
  tem ⩲ e ⩱) quando o desenho é claro e não contradiz a leitura do OCR, ou pela
  confirmação na tela "Símbolos do livro". O fim do lance é reescrito; desenho
  sem símbolo decidido deixa o lance como o OCR leu, com aviso. A confirmação
  não refaz o OCR (segundos) e vale num OCR futuro. A tinta colada depois da
  palavra também conta. "Não é símbolo" mantém o que o OCR leu ali.
* Leituras únicas: "d52!" → "d5?!", "e5!2" → "e5!?", "♕£3" → "♕f3", "¢4" →
  "g4".
* **Corrigir o original** antes de traduzir: o texto lido fica guardado, a
  sincronização casa por ele, a montagem e a auditoria usam o corrigido.
* **Posições dos diagramas**: cada casa vira o contorno da peça (miolo branco
  fechado — os vãos da hachura chegam todos à borda da casa — ou corpo preto que
  resiste à erosão); forma e cor numa imagem de três níveis (branco 0, fundo ½,
  preto 1: com branco ½ e preto 1, a correlação não separava o peão branco do
  preto); contornos agrupados no livro; o usuário confirma a peça de cada
  grupo ("Peças dos diagramas"); grupo pequeno herda do mais parecido. Vez de
  jogar pela marca ▼/△. Cada diagrama aparece na aba Páginas com a imagem, o
  tabuleiro lido, a FEN editável e "Confirmar posição".
* **Conferência dos lances pela posição**, só no texto logo abaixo do
  diagrama: lance que não confere ou sinal de xeque que não confere vira aviso.

## Medidas no livro inteiro

| | |
|---|---|
| Segmentos | 3504 (2469 antes: títulos de partida do alto da página e títulos correntes) |
| Grupos de símbolos | 116; 30 com mais de 5 desenhos cobrem quase todos; confirmados em ~2 min |
| Lances com símbolo decidido pelo desenho | 5911; 48 sem decisão (aviso) |
| "⩲" e "±" | a sugestão automática confundiu os dois (mais/um traço × mais/dois traços) em 3 grupos: a confirmação é necessária |
| Grupos de peças | 86; 53 com mais de 5 casas cobrem 13 216 de 13 266 peças |
| Diagramas com posição completa e possível | 579 de 617 (94 %); faltam 14 sem a marca de vez de jogar e ~20 com uma casa da borda sem peça decidida |
| Posições conferidas à mão (sorteio + uma transcrita) | 7 de 7 idênticas à imagem, casa a casa, com a vez de jogar |
| Conferência dos lances abaixo dos diagramas | 356 lances conferem; 29 avisos (cerca de metade é leitura errada; o resto, ameaça ou outra variante citada) |

## O que não funcionou e foi retirado

* **Ligar solução a exercício pela ordem** ("N. Fulano – Beltrano" ↔ o N-ésimo
  dos K diagramas antes da sequência de soluções): 28 primeiros lances
  conferiam contra 149 que não; nenhum deslocamento da janela melhorou. Os
  exercícios do livro não ficam todos juntos antes das soluções.
* **Agrupar as casas pelo recorte reduzido** (hachura virando cinza): 8733
  grupos para 39 488 casas; o contorno resolveu (86 grupos).
* **Modelo "best" do Tesseract**: melhor nas letras e casas ("♕g4", "c6"), pior
  no xeque e nas figurinas pintadas; não adotado (ver limitações).

# Limitações conhecidas

Medidas no livro de amostra (*Dvoretsky's Endgame Manual*, 441 páginas,
traduzido inteiro na Fase 7) e nos testes. Cada item diz o que acontece e o
que o aplicativo faz para não esconder o problema.

## Notação e diagramas

* **Lances desenhados como imagem** dentro do texto (5 parágrafos no livro):
  não há como reescrevê-los com segurança; o parágrafo fica no original,
  "bloqueado", para tradução manual.
* **Lances ilegais ou ambíguos** na origem (89 no livro, erros do próprio
  livro ou leitura duvidosa) são marcados e nunca convertidos; a tradução copia
  o que está lá.
* **Probe de glifos**: em fontes de figurinas desconhecidas, peão e bispo
  ainda se confundem; o mapa precisa de confirmação humana (o do livro de
  amostra foi confirmado).
* **Notação descritiva** (P-K4) é reconhecida, mas não convertida.
* **Rótulos de diagrama** ("W?", "B", "Play") ficam em inglês: traduzi-los
  pede uma convenção editorial ("B" de *Black* × "B" de brancas).

## Layout

* O texto traduzido é acomodado **dentro da página**: não passa de uma página
  para outra. Quando não cabe, a fonte é reduzida; abaixo de 85 % a página vai
  para revisão. No livro: 428/440 páginas sem pendência; as 12 restantes têm um
  cabeçalho de partida entre 72 e 84 %.
* Fontes originais são substituídas por equivalentes livres (Liberation com
  as mesmas métricas; Urbanist para Century Gothic e Broadway). As figurinas
  saem na FreeSerif, um pouco mais leves que as originais em negrito.
* Fundos sombreados são retirados nas páginas traduzidas (decisão do usuário).

## Tradução

* Depende de um serviço externo (Pollinations); sem
  `CHESSBOOK_PRIVACY_MODE=remote_allowed`, só a revisão funciona.
* O modelo pode acrescentar ou omitir algo na prosa. Números, lances, casas e
  símbolos são conferidos (no livro: 1 tradução recusada por acrescentar um
  ano); a razão de comprimento avisa sobre omissões possíveis, mas o sentido
  da prosa só a revisão humana garante.
* Previsão de custo com ±20 % para o Sonnet (recalibrada no livro inteiro);
  modelos com raciocínio variam mais.
* O aviso de glossário compara palavras com flexão portuguesa e tem falsos
  positivos ("jogo de finais" foi tomado por "jogo final").
* Só inglês → português brasileiro.

## Livros digitalizados (OCR)

* 71–84 % dos lances com peça lidos certos no livro de amostra; 1–2 % errados
  **sem** aviso específico. Por isso todo parágrafo de OCR leva o aviso geral
  "confira com a imagem", mas só pede atenção quando há um aviso específico
  sobre lance, casa ou número (no *Grandmaster Preparation*: 32 % dos
  parágrafos). Confira os demais pela página inteira e use "Aprovar página".
* As figurinas de cada livro precisam de confirmação na tela "Figurinas do
  livro": sem ela, um desenho que se parece com outra peça (a dama do
  *Grandmaster Preparation* com o rei) fica sem leitura e o lance sai com a
  letra que o OCR viu ("We4"), com aviso.
* Lances que o OCR estragou além da correção de leitura única ("♕65!",
  "♘FB") ficam como lidos, com aviso: a correção é manual, na revisão.
* A posição dos diagramas digitalizados é lida pelo contorno das peças, com
  as peças confirmadas pelo usuário ("Peças dos diagramas"); um diagrama sem a
  marca ▼/△ fica sem vez de jogar até a revisão. Tabuleiro virado (pretas
  embaixo) não é reconhecido.
* Os lances de um livro digitalizado só são conferidos pelas regras onde a
  posição é certa: logo abaixo do diagrama, na mesma página e coluna, e nas
  soluções numeradas ("N. Fulano – Beltrano") ligadas ao exercício N. Texto
  que continua na página seguinte ou partida que começa do zero sem diagrama
  ficam sem essa conferência.
* Casas lidas erradas sem aviso continuam possíveis onde não há posição (ex.:
  "♕e4" no lugar de "♕g4" no meio de uma partida comentada); por isso a
  revisão com a imagem continua necessária.
* Itálico e fonte original se perdem; títulos saem em serifa normal.
* ~5 s por página, uma vez por livro (refeito quando o OCR do programa muda);
  reler com figurinas confirmadas: ~3 s por página. As figurinas precisam
  aparecer ao menos 3 vezes iguais para virar protótipo sozinhas; um grupo
  menor só vale se confirmado.
* Diagramas são achados pela moldura quadrada com casas alternadas. Um
  diagrama sem moldura não é achado: o texto lido dele sai como trecho
  ilegível que "fica como na imagem" (nada é apagado).
* Negrito dos lances não é recuperado: a tradução sai sem o destaque.
* A conferência dos diagramas compara a área do diagrama com uma folga em
  volta; texto traduzido da coluna vizinha que entra nessa folga aparece como
  "diagrama alterado" sem que o tabuleiro tenha mudado (confira pela imagem).
* Docling avaliado e não adotado (ADR-0007); RapidOCR não testado (modelos em
  `www.modelscope.cn`, bloqueado no ambiente de desenvolvimento).

## Aplicativo

* Um usuário, no próprio computador, sem senha (ver `docs/quality/seguranca.md`).
* Instalação testada em Linux; macOS deve funcionar com os mesmos requisitos,
  mas não foi testado; Windows não é suportado pelos scripts (usar WSL).
* Exportação de PGN só pela linha de comando (`scripts.export_pgn`).

# ADR-0003 — Notação em três camadas, validada por regras

**Estado:** aceito e implementado (núcleo) · **Data:** 2026-10-22

## Contexto
Os lances podem estar em inglês, português, FAN Unicode, fontes figurinas que
reutilizam letras, fontes com pontos de uso privado ou vir de OCR. Um símbolo
errado muda a análise. O python-chess valida regras, mas só interpreta SAN
inglês.

## Decisão
* Cada lance guarda: **original** (texto e posição exatos), **normalizada**
  (UCI + FEN anterior, somente se validado) e **saída** (gerada sob demanda
  conforme a preferência; padrão: preservar).
* Análise léxica própria, sem alterar o texto (`app/chess/notation/lexer.py`).
* Resolução própria dos componentes do lance contra `board.legal_moves`, com o
  alfabeto da convenção; o python-chess é o motor de regras.
* Validação conservadora: sem posição presumida, ambiguidade nunca resolvida
  por palpite, perda de contexto após erro, avisos de revisão para marcadores
  incoerentes.
* Conversão de saída troca só o caractere da peça (e da promoção), mantendo
  desambiguação, roque e sinais do autor. Política `strict` por padrão.
* A conversão é feita pelo módulo de notação, nunca pelo tradutor.

## Consequências
* Lances sem contexto permanecem na grafia original em modos de conversão
  (política `strict`), o que pode deixar notação mista; o relatório lista cada
  caso e o usuário pode optar por `symbol_only`.
* Notação descritiva fica preservada e sinalizada; conversão é trabalho
  futuro.

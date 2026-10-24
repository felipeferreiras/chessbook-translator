# Fase 4 — glossário, contexto, revisão e comparação de modelos

Data: 2026-10-24.

## Glossário aplicado por contexto

* Cada lote recebe só os termos que aparecem nos seus segmentos (com flexão
  inglesa: "outposts", "drawn"); o glossário saiu das instruções fixas.
* O cache depende dos termos do segmento: mudar um termo retraduz só quem o
  usa.
* Conferência depois da tradução: `glossario_evitar` (tradução marcada como
  errada, pede revisão) e `glossario_ausente` (informativo). A comparação
  aceita plural, gênero e derivação no português ("peões passados",
  "rei branco", "empatada") e ignora artigos.
* Entradas novas: `avoid` (nunca usar), `case_sensitive` ("White" lado ×
  "white pawn") e `check` (desliga só o aviso de ausência em termos ambíguos
  como "move" verbo e "the square").

## Contexto por capítulo

Títulos reconhecidos pelo tamanho relativo ao corpo do texto (capítulo
1,35×, subseção 1,15× em negrito, curtos e sem lances). No livro: 50
capítulos e 254 seções. Cada lote vai com "Capítulo › Subseção" e nunca
mistura seções.

## Projeto e revisão

Projeto em SQLite com o original somente leitura (sha256), versões de cada
segmento (máquina, edição, reversão), registro de revisões e glossário do
projeto. Edição manual recusada se qualquer lance, casa, número ou símbolo
mudar. API local (FastAPI, só `127.0.0.1`) e interface (Vite + React + TS).
Ciclo completo na amostra (criar, importar, exportar, montar): 208/208
blocos, sem sobreposições, diagramas intactos. Teste no navegador: recusa de
edição com motivo, edição válida, histórico, volta de versão, aprovação,
glossário; sem rolagem horizontal no celular.

## Comparação de modelos (p. 21 e 438, 25 segmentos com prosa)

Mesmo prompt (2026-10-24.1, glossário por lote e contexto de seção), todos
pela Pollinations.

| | Gemini 3.8 Flash | Claude Sonnet 5.5 | Claude Opus 5.5 | Qwen 3.8 27B |
|---|---|---|---|---|
| Aceitos | 25/25 | 25/25 | 25/25 | 24/25 |
| Erros do provedor | 0 | 0 | 0 | 3 (resposta cortada por limite de tokens) |
| Avisos de glossário (após a correção abaixo) | 0 | 0 | 0 | 0 |
| Razão de comprimento PT/EN | 1,03 | 1,02 | 1,02 | 1,03 |
| Tokens entrada / saída | 9.853 / 13.576 | 10.616 / 5.734 | 10.616 / 4.582 | 7.862 / 26.578 |
| Tempo | 121 s | 51 s | 54 s | 686 s |
| Custo pelo catálogo (pollen) | 0,058 | 0,059 | 0,101 | 0,035 |

Leitura dos parágrafos que mais divergem entre os modelos:

* Os três primeiros são fiéis e mantêm toda a notação; as diferenças são de
  estilo.
* **Opus 5.5**: o português mais natural.
* **Sonnet 5.5**: tão bom quanto, às vezes com pequenas liberdades de
  interpretação.
* **Gemini 3.8 Flash**: um pouco mais literal em alguns pontos. Gasta mais
  tokens de saída (raciocínio cobrado como saída), o que iguala o custo ao
  do Sonnet.
* **Qwen 3.8 27B** (pesos abertos, candidato a rodar localmente): lento e
  instável com lotes grandes; um segmento falhou por resposta cortada. Para
  uso local precisaria de lotes menores e de uma nova avaliação.

A rodada revelou dois alarmes falsos na conferência do glossário, iguais em
todos os modelos: "White's king" → "o rei branco" (correto; a conferência só
aceitava "brancas") e "Black to move" (não é "lance"). Corrigidos: o radical
agora ignora plural e gênero, e "move" deixou de gerar aviso de ausência.

Com duas páginas, a comparação é indicativa. Estimativa para o livro inteiro,
pela proporção da amostra de 16 páginas: Gemini ou Sonnet ≈ 5–6 pollen; Opus
≈ 10.

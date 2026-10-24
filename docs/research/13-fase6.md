# Fase 6: OCR com figurinas, retomada, reprocessamento seletivo e custos

Data: 2026-10-24.

## Retomada

**Tradução.** Uma tarefa grava o resultado de cada seção assim que ela termina.
Os lotes já respondidos de uma seção interrompida ficam no cache, então a
retomada não paga por eles de novo. O que mudou nesta fase:

* **Tarefa órfã.** É uma tarefa ativa cujo processo morreu (servidor encerrado,
  queda de energia). Agora ela aparece como `interrupted` e deixa de bloquear o
  projeto.
  * A tarefa é considerada viva em dois casos:
    * a thread dela existe neste processo;
    * ou, se roda em outro processo, ela deu sinal nos últimos 30 minutos
      (`heartbeat_at`, gravado a cada seção) **e** o processo existe.
  * O número de um processo morto pode ser reaproveitado. Por isso só o pid
    não basta.
* **Retomar.** O botão "Retomar…" (ou `POST /jobs/{id}/resume`) cria uma tarefa
  nova com o mesmo motor, as mesmas páginas e o mesmo modo.
  * Os segmentos que a anterior já tratou são pulados (tabela `job_segment`,
    seguindo a cadeia de retomadas).
  * O teto da nova tarefa é o que sobrou da anterior, ou um teto novo.
* **Corrida corrigida.** Entre gravar a tarefa e marcar a thread como viva,
  outra consulta podia tomá-la por órfã. Agora a trava do projeto cobre esse
  instante.

**Montagem.** A montagem agora roda pela interface, na aba Qualidade, em outro
processo (`app/store/assembly.py`), com andamento e cancelamento.

* As partes de 20 páginas ficam guardadas em `output/partes`.
* A chave de cada parte junta:
  * o sha256 do original;
  * as páginas da parte;
  * o texto atual de cada segmento dessas páginas;
  * a versão do código de layout.
* Uma montagem interrompida recomeça pelas partes que faltam.
* As saídas são gravadas em arquivo temporário e trocadas no fim: nunca fica
  um PDF pela metade.

Medido no livro inteiro, com tradução simulada (`PseudoProvider`) numa cópia
de teste do projeto:

| Montagem | Partes reaproveitadas | Tempo |
|---|---|---|
| primeira | 0 de 23 | 216 s |
| de novo, sem mudanças | 23 de 23 | 12 s |
| depois de editar um parágrafo da p. 200 | 22 de 23 | 24 s |

Os números de qualidade são os mesmos da Fase 5:

* 5569/5569 blocos colocados;
* 440/440 páginas com texto sem pendência;
* 1220 diagramas intactos;
* zero cortes, sobreposições e sobras do original.

## Reprocessamento seletivo

Na aba Traduzir, "O que traduzir" oferece cinco modos (`ProjectStore.select_sources`):

| Modo | Seleciona |
|---|---|
| pendentes | sem tradução ainda (o comportamento anterior) |
| com problemas | recusados pela proteção, falhas do provedor, glossário contrariado |
| glossário | traduzidos com termos do glossário que mudaram depois (cada versão guarda a impressão digital dos termos que valiam para ela) |
| toda tradução automática | para trocar de motor |
| escolhidos | botão "Retraduzir…" em cada parágrafo da revisão |

Regras:

* **Versão humana:** nunca é selecionada nem substituída.
* **Nova tentativa que falha:** a tradução anterior continua valendo
  (`retry_failed`), e todas as versões ficam no histórico.
* **Opção "pedir tradução nova (ignorar o cache)":** sem ela, o mesmo motor
  devolveria a mesma tradução, de graça. A previsão de custo leva a opção em
  conta.
* **Traduções de antes do registro do glossário:** a importação da amostra da
  Fase 2, por exemplo, não tem a impressão digital dos termos. Essas traduções
  ficam fora do modo glossário, e a previsão diz quantas são.

## Limites e custos

* **Teto do projeto inteiro (opcional).** O teto de cada tarefa nunca passa do
  que sobra dele, e a interface mostra o gasto acumulado. Mudar o teto fica
  registrado no histórico de revisões.
* **Conferência antes de cada seção.** Se o custo previsto da seção não couber
  no que sobra do teto, a tarefa para **antes** de enviar
  (`stopped_budget`, "nada dele foi enviado"). Antes, ela só parava depois de
  passar do teto.
* **Respostas inúteis também são cobradas.** Uma resposta cortada pelo limite de
  tokens ou com JSON inválido ainda custa. Os tokens dela agora entram no custo
  da tarefa (`ProviderError.usage`, no adaptador da Pollinations). Antes eram
  ignorados.
* **Limite de taxa (429) e erros do servidor:** o SDK da OpenAI, usado para a
  Pollinations, já repete com espera (2 tentativas). O disjuntor de falhas
  seguidas continua valendo.

## OCR de páginas digitalizadas

Uma página sem texto utilizável, mas com imagem cobrindo boa parte dela, passa
pelo OCR em `scripts.project create`. O resultado fica guardado em
`<projeto>/ocr.json`. A montagem relê exatamente o mesmo texto, e a segunda
leitura não chama o Tesseract.

No modo automático (padrão), só livros **majoritariamente** digitalizados são
lidos. Num livro digital, uma página só de imagem é capa ou foto (no
Dvoretsky, só a capa) e fica como está; `--ocr on` força a leitura. Projetos
criados sem OCR continuam montando sem ele, porque a decisão fica gravada no
projeto: os projetos existentes não mudam.

**Leitura.** Tesseract 5.3.4, em hOCR com a caixa de cada caractere, a 300 dpi.
Sempre com **uma thread** (`OMP_THREAD_LIMIT=1`): com várias e a CPU ocupada,
uma página levou mais de 5 minutos, contra 2 s com uma só.

**Diagramas.** O tabuleiro é achado pela moldura: dois traços horizontais e dois
verticais longos que fecham um quadrado, com tom alternado nas 64 casas
(hachuradas, cinza ou cor).

* O texto que o OCR "lê" dentro do tabuleiro é descartado.
* A área fica protegida na montagem e é conferida pixel a pixel.
* A posição não é lida: o diagrama fica sem FEN.

**Figurinas.** O Tesseract não conhece figurinas: leu `♔e6` como `@e6`, `8e6`,
`Se6` e até `Be6`, uma letra válida de outra peça. Pior, a figurina atrapalha a
leitura da casa: `Ke6` virou `Seb`. A solução tem duas passadas:

1. **Aprender as figurinas do próprio livro.**
   * O primeiro desenho largo de cada palavra que parece lance é recortado da
     imagem.
   * Desenhos iguais formam grupos (semelhança ≥ 0,85), e cada grupo recebe a
     peça da referência mais parecida (figurinas e letras das fontes
     instaladas, como no probe).
   * Só grupos com 3 ou mais recortes e margem segura contra outra peça viram
     protótipos.
   * Medido: o rei do Dvoretsky, com cruz num quadrado, tem nota baixa contra
     as referências (0,3–0,5), mas a margem sobre a dama separa bem. Os grupos
     grandes saíram todos com a peça certa; os recortes isolados erravam com
     frequência.
2. **Trocar as figurinas por letras e ler de novo.**
   * Cada figurina reconhecida pelos protótipos é pintada na imagem como a
     letra da peça, alinhada pela direita para manter a distância até a casa.
   * O OCR é refeito e lê `Ke6` sem tropeçar.
   * A letra volta a ser figurina pela posição.

Primeiro tentei apagar a figurina e juntar as palavras depois, mas o Tesseract
corta as palavras de outro jeito na segunda leitura, e a junção colava trechos
que não deviam ficar juntos.

**Nada presumido.** Todo segmento de página lida por OCR pede conferência com a
imagem antes da aprovação (`source_flags`; o parágrafo fica "pede atenção" até
ser aprovado). Além disso, avisos específicos apontam o trecho:

| Aviso | Quando |
|---|---|
| peça incerta | sem margem contra outra peça, ou sem protótipo |
| lance incompleto | figurina sem casa válida depois |
| lance ilegível | padrões que nenhum lance produz: `2...8c4`, `c62`, `Afl+` |
| desenho não lido | tinta na linha que nenhum caractere lido cobre, ou pontuação larga demais (o ponto de `1...` às vezes vinha com 40 px, cobrindo a figurina pulada) |
| baixa confiança | palavra com confiança abaixo de 60 |

**Layout.**

* O Tesseract juntava linhas das duas colunas. Uma linha agora é partida onde o
  espaço entre palavras passa de 1,2 vez o corpo da fonte.
* O corpo da fonte é o `x_size` vezes 1,07 (medido: 9,4 pt lidos para corpo 10).
* Rótulos curtos lidos sem confiança (`1-38` lido como `SS`) ficam como na
  imagem.
* Na montagem, a redação pinta os pixels com a cor do papel em volta (o quadro
  sombreado continua cinza). O texto que sobrar é medido pela tinta restante.

### Avaliação contra o texto digital

`scripts/evaluate_ocr.py` transforma páginas do PDF digital em imagem, passa
pelo OCR e compara com o texto original, com o mapa de glifos já resolvido.
Ruído gaussiano é opcional.

| Conjunto | Palavras certas | Lances com peça certos | Errados **sem aviso** | Diagramas achados / falsos | s/página |
|---|---|---|---|---|---|
| 18 páginas usadas para ajustar (21–26, 101–104, 181–184, 301–304) | 91,0 % | 84,0 % | 16 de 1339 (1,2 %) | 53/53 / 0 | 4,8 |
| 20 páginas novas (50–53, 150–153, 250–253, 350–353, 420–423) | 85,9 % | 70,7 % | 20 de 1333 (1,5 %) | 58/58 / 0 | 4,7 |
| as mesmas 20, com ruído (σ = 12) | 86,1 % | 71,2 % | 28 de 1333 (2,1 %) | 58/58 / 0 | 6,3 |

Partindo da primeira versão (só o Tesseract com a peça decidida pela imagem),
nas 18 páginas de ajuste:

* lances certos: 3 % → 84 %;
* palavras certas: 78 % → 91 %.

**Os erros sem aviso existem**, quase sempre uma casa mal lida pelo próprio
Tesseract: `g`→`e`, `1`→`5`, `c`→`e`. Por isso a conferência com a imagem é
obrigatória em todo parágrafo vindo do OCR, e não só nos que têm aviso.

**Livro digitalizado de teste**: 6 páginas como imagem, com ruído.

* Criação com OCR: 50 s.
* Montagem: 100/100 blocos colocados, 19 diagramas intactos, nenhuma sobra do
  original.
* 4 de 6 páginas sem pendência. As outras duas mostram, honestamente, uma
  sobreposição e um texto ausente que vêm de linhas mal agrupadas pelo OCR.

## Docling

O Docling 2.142.1 (MIT) foi instalado num ambiente separado, com 5,9 GB por
causa do PyTorch, para não pesar no projeto. A avaliação está pronta em
`scripts/evaluate_docling.py`, com as mesmas páginas e o mesmo gabarito do
nosso OCR. Ela mede quatro coisas: palavras na ordem de leitura, lances com
peça, diagramas detectados como imagem e tempo por página.

Os modelos ainda não baixam. `huggingface.co` foi liberado em 2026-10-24, mas
os pesos são servidos por outros endereços, que continuam bloqueados:

* com o Xet: `cas-server.xethub.hf.co`, que leva a `cas-bridge.xethub.hf.co`
  e `transfer.xethub.hf.co`;
* sem o Xet (`HF_HUB_DISABLE_XET=1`): `us.aws.cdn.hf.co`, `cdn-lfs.huggingface.co`
  e `cdn-lfs-us-1.hf.co`.

Liberar `*.hf.co` (que inclui `*.xethub.hf.co`) e `cdn-lfs.huggingface.co`
resolve. O OCR atual não depende do Docling.

## Limitações conhecidas

* **Posição dos diagramas digitalizados não é lida:** sem FEN, os lances dessas
  páginas não são validados pela legalidade. Reconhecer as peças do tabuleiro
  com os mesmos protótipos é o passo natural.
* **Estilos perdidos no OCR:** negrito, itálico e fonte original (títulos saem
  em serifa normal, e a linha principal em negrito não é distinguida).
* **OCR caro e todo de uma vez:** cerca de 5 s por página, com as duas passadas.
  As figurinas são aprendidas no conjunto, então o OCR lê todas as páginas
  digitalizadas do livro na criação do projeto: cerca de 35 minutos para 440
  páginas. Isso acontece uma vez só, e o resultado fica guardado.
* **Erros silenciosos:** 1,2–2,1 % dos lances com peça saem errados sem aviso
  específico. Ficam cobertos pela conferência obrigatória com a imagem.
* **Teste de retomada no livro inteiro:** a retomada foi testada com tarefas
  simuladas, não com uma tradução real interrompida no livro inteiro, porque
  isso exigiria gastar com tradução.

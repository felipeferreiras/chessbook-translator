# Manual do chessbook-translator

Traduz livros de xadrez em PDF do inglês para o português brasileiro sem
alterar lances, diagramas ou a organização das páginas. Roda no seu
computador; só o texto em prosa (com os lances trocados por marcadores) sai
para o serviço de tradução, e só quando você permite.

## 1. Instalar

Requisitos: Linux ou macOS, Python 3.12+, [uv](https://docs.astral.sh/uv/),
Node.js 20.19+ (só para compilar a interface). No Debian/Ubuntu:

```bash
sudo apt install fonts-liberation fonts-freefont-ttf fonts-dejavu-core tesseract-ocr tesseract-ocr-eng
./instalar.sh      # cria backend/.venv, compila a interface, cria o .env e confere tudo
./iniciar.sh       # abre http://127.0.0.1:8000
```

O Tesseract é opcional: só é usado em livros digitalizados (páginas que são
imagens). Para conferir o ambiente a qualquer momento:
`cd backend && .venv/bin/python -m scripts.doctor --rede`.

### Configurar a tradução

Edite o `.env` (fica só no seu computador, fora do controle de versão):

```
CHESSBOOK_PRIVACY_MODE=remote_allowed     # sem isto, nada é enviado para fora
POLLINATIONS_API_KEY=sk_...               # a chave da Pollinations
CHESSBOOK_STORAGE=/caminho/dos/projetos   # opcional; padrão ./storage
```

A aba **Projeto** mostra se a tradução externa está permitida e se a chave
existe (a chave nunca aparece na tela).

## 2. Criar um projeto

Aba **Projeto → Novo projeto**: escolha o PDF, dê um nome e crie. O original é
copiado para o projeto e nunca mais é alterado (o sha256 é conferido sempre).
Num livro digital, a leitura leva segundos; num livro digitalizado, o OCR leva
cerca de 5 s por página e acontece uma vez só.

**Páginas digitalizadas**: no modo automático, só livros majoritariamente
digitalizados passam pelo OCR (a capa de um livro digital fica como imagem).
Os diagramas são achados pela moldura e pelas casas alternadas e ficam
intactos, com coordenadas, números e marcas ao redor.

### Figurinas do livro (livros digitalizados)

Cada livro desenha as peças do seu jeito, e o OCR não as conhece (a dama do
*Grandmaster Preparation* sai como "W"). Depois de criar o projeto, abra
**Projeto → Figurinas do livro**: cada grupo mostra um desenho achado no começo
dos lances, quantas vezes aparece e o que o OCR leu. Escolha a peça de cada
grupo (ou "não é peça") e clique **Confirmar e reler o livro**. O livro é
relido com essas figurinas (cerca de 1 min a cada 20 páginas) e só os
parágrafos cujo texto mudou voltam a pendentes; traduções feitas ficam
guardadas no histórico. Grupos com a borda laranja são sugestões incertas:
confira com mais atenção. A escolha vale também quando o OCR for refeito
depois de atualizar o programa.

Faça isso **antes de traduzir**: parágrafos traduzidos com a peça errada
precisam ser traduzidos de novo.

## 3. Traduzir

Aba **Traduzir**:

1. Escolha as páginas e o que traduzir: pendentes; com problemas; afetados por
   mudança no glossário; toda tradução automática (para trocar de motor); ou os
   parágrafos escolhidos com "Retraduzir…" na revisão.
2. **Calcular previsão**: cada motor mostra custo previsto (com faixa), tempo e
   observações. Sonnet 5.5 é o recomendado (o livro de amostra inteiro custou
   7,06 pollen e levou 34 min).
3. Defina o **teto desta tarefa**; opcionalmente, um **teto do projeto**.
   Antes de cada seção, a tarefa confere se o custo previsto cabe no que sobra;
   se não couber, para sem enviar.
4. Acompanhe o andamento. Uma tarefa interrompida (servidor desligado,
   cancelamento, teto) pode ser **retomada**: o que já foi traduzido é pulado e
   o que já foi pago vem do cache.

Garantias: os lances viram marcadores antes do envio e voltam idênticos; uma
tradução que perca, troque ou acrescente lance, casa, número ou símbolo é
recusada e fica para revisão. Edições humanas nunca são substituídas por uma
retradução.

## 4. Revisar

Aba **Páginas**: a página original e a montada lado a lado; cada parágrafo com
o original e a tradução editável.

* **Salvar** cria uma versão nova; a edição é recusada se algum lance, casa,
  número ou símbolo mudar (o motivo aparece).
* **Aprovar** marca o parágrafo como conferido; qualquer mudança depois retira
  a aprovação.
* **Histórico**: todas as versões, com quem e quando; "Voltar a esta versão".
* **Retraduzir…**: outra tentativa automática, com previsão de custo.
* **Aprovar página**: aprova de uma vez os parágrafos traduzidos da página,
  depois de conferi-los com a página original. Recusas da proteção, falhas e
  parágrafos sem tradução ficam de fora.
* **Próxima pendência** e o filtro "só o que pede atenção" levam ao que falta:
  recusas da proteção, falhas, glossário contrariado, parágrafos bloqueados
  (lances desenhados como imagem) e, nos livros digitalizados, parágrafos com
  um aviso do OCR sobre um lance, casa ou número (peça incerta, lance
  incompleto, desenho não lido, leitura sem confiança) ainda não aprovados.
  O aviso geral "texto lido da imagem" aparece em todo parágrafo de OCR, mas
  não pede atenção sozinho; uma palavra comum mal lida também não.
* Trechos ilegíveis do OCR (rótulos, marcas, restos de desenho) **ficam como na
  imagem**, nunca são apagados. Os curtos não pedem nada; os longos pedem uma
  olhada e saem da lista com **Manter como na imagem**.
* Trocas do OCR com uma leitura só são corrigidas e ficam anotadas no
  parágrafo: "♖el" → "♖e1", "4l." → "41.", "t" no fim do lance → "†".

Aba **Glossário**: termos com tradução preferida, alternativas e traduções a
evitar. Mudou um termo? "O que traduzir → afetados pelo glossário" retraduz só
quem o usa.

## 5. Montar e conferir

Aba **Qualidade**:

* **Montar PDF traduzido**: em partes de 20 páginas; depois de uma revisão, só
  as partes alteradas são refeitas (o livro inteiro leva ~6 min; depois de
  editar um parágrafo, ~25 s).
* A lista de páginas com pendência: fonte reduzida abaixo de 85 %, texto
  ausente ou cortado, sobreposição, sobra do original, lance ausente, diagrama
  alterado.
* **Auditar integridade**: original intacto, projeto alinhado com a versão do
  programa, notação idêntica em todas as traduções (inclusive edições), nada
  sobrando, PDF cobrindo o texto atual.

Aba **Projeto → Baixar PDF traduzido**.

## 6. Backup

Aba **Projeto → Baixar backup**: um `.chessbook.zip` com o banco (todas as
versões e revisões), o original, o glossário, o OCR, o cache de traduções já
pagas e o PDF montado, com sha256 de cada arquivo. **Restaurar backup** confere
tudo antes e nunca sobrescreve um projeto existente (restaure com outro
identificador para ter uma cópia). Pela linha de comando:
`scripts.project backup ID` e `scripts.project restore ARQUIVO.zip`.

## 7. Depois de atualizar o programa

Aba **Projeto → Sincronizar com a versão atual**: uma versão nova pode ler o
livro de forma um pouco diferente (por exemplo, dividir um parágrafo). A
sincronização alinha os parágrafos pelo texto, sem perder traduções; só o
parágrafo cujo texto mudou volta a pendente (a tradução antiga fica guardada
como obsoleta). Num livro digitalizado, se o OCR mudou, ele é refeito (cerca
de 5 s por página): a sincronização roda em segundo plano, com o andamento na
tela, e pode-se continuar usando o resto do programa. Depois, confira as
**Figurinas do livro** e traduza os pendentes (Traduzir → pendentes).

Pela linha de comando: `scripts.project sync ID` e
`scripts.project figurines ID` (mostra os grupos) ou
`scripts.project figurines ID --labels '{"2": "♕", "4": ""}'` (confirma e relê).

## 8. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "motor não configurado" | `.env`: `CHESSBOOK_PRIVACY_MODE=remote_allowed` e `POLLINATIONS_API_KEY`; reinicie |
| "host não autorizado" ao abrir por outro nome | use `http://127.0.0.1:8000` ou acrescente o nome em `CHESSBOOK_ALLOWED_HOSTS` |
| Montagem recusa: "não corresponde ao texto extraído" | Projeto → Sincronizar |
| Página com fonte muito reduzida | edite o parágrafo para ficar mais curto (cabeçalhos de partida) e monte de novo |
| Parágrafo "bloqueado" | os lances estão desenhados como imagem no PDF: traduza à mão na revisão |
| Livro digitalizado: peça lida como letra ("We4") | Projeto → Figurinas do livro: escolha a peça do grupo e releia |
| Quase todos os parágrafos pedem atenção | Projeto → Sincronizar (versão nova do OCR), depois Figurinas do livro |
| Tarefa "interrompida" | Traduzir → Retomar… |

Limitações conhecidas: `docs/limitacoes.md`. Segurança: `docs/quality/seguranca.md`.

# Revisão de segurança (Fase 8, 2026-10-26)

## O que protegemos

O livro (material com direitos autorais do usuário), as traduções e a chave
da Pollinations (que gasta créditos). O aplicativo é de um usuário só, no
próprio computador.

## Superfície

* API FastAPI e interface servidas em `127.0.0.1` (nunca em `0.0.0.0`).
* Entradas não confiáveis: PDFs enviados, backups `.zip` restaurados, respostas
  dos modelos de tradução, e qualquer página da web aberta no mesmo navegador.
* Saída para a rede: só a Pollinations, com `CHESSBOOK_PRIVACY_MODE=remote_allowed`.

## Achados e correções

| # | Achado | Gravidade | Correção | Teste |
|---|---|---|---|---|
| 1 | **DNS rebinding**: a API aceitava qualquer `Host`. Uma página maliciosa cujo domínio passa a apontar para 127.0.0.1 leria o livro e a tradução e poderia iniciar tarefas que gastam créditos | alta | só nomes locais (`localhost`, `127.0.0.1`, `[::1]`) ou os de `CHESSBOOK_ALLOWED_HOSTS`, inclusive para leitura | `test_security.py` |
| 2 | **CSRF**: rotas POST sem corpo (cancelar tarefa, cancelar montagem) aceitavam um formulário de outro site. As rotas com corpo JSON já recusavam (422) | média | pedidos que alteram algo com `Origin` de outro site, `Origin: null` ou `Sec-Fetch-Site: cross-site` são recusados | `test_security.py` |
| 3 | Dependências com vulnerabilidades conhecidas (pip-audit): starlette 0.48.0 (12 avisos), brotli 1.2.0 (2) | alta | FastAPI 0.162.0 / starlette ≥ 1.3.1; brotli ≥ 1.2.1; **pip-audit: nenhuma vulnerabilidade conhecida** | suíte inteira com as versões novas |
| 4 | npm audit: vite 5.4 / esbuild (só o servidor de desenvolvimento, não a interface compilada) | baixa | vite 7.3.7, plugin-react 5.1.4; **npm audit: 0** | build |
| 5 | Envio de PDF pela interface (novo) | — | limite de tamanho verificado durante o envio (413), assinatura `%PDF-`, abre sem senha, 1–3000 páginas; o nome enviado nunca vira caminho (arquivo renomeado); extração em outro processo | `test_project_lifecycle.py` |
| 6 | Restauração de backup (novo): zip slip, links, bombas de descompressão | — | só nomes esperados (sem `..`, absolutos ou links), limite de 8 GB descompactado, sha256 de cada parte contra o manifesto, `PRAGMA integrity_check`, original contra o sha256 do banco; montado numa pasta temporária e movido de uma vez; nunca sobrescreve | `test_backup.py` |
| 7 | Cabeçalhos | baixa | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`; `--no-server-header` no `iniciar.sh` | `test_security.py` |

## Conferido sem mudança

* **Chave**: só no `.env` (fora do git; `instalar.sh` cria com `chmod 600`; o
  `doctor` avisa se outros usuários podem lê-lo). A API diz apenas se ela
  existe; nenhuma mensagem de erro a repete. Commits conferidos sem a chave.
* **Caminhos**: projetos e segmentos são identificados por id validado por
  expressão regular; nenhum caminho vem do cliente.
* **XSS**: a interface usa só a renderização do React (nenhum `innerHTML`); o
  texto do livro e das traduções nunca é interpretado como HTML.
* **Saída dos modelos**: tratada como dado não confiável. A proteção de
  notação recusa traduções que alterem lances, casas, números ou símbolos; as
  marcas `<b>`/`<i>` aceitas são só essas duas, convertidas pelo próprio
  aplicativo. O JSON é lido por `json.JSONDecoder` (sem `eval`).
* **SQL**: só consultas parametrizadas; os nomes de coluna dinâmicos vêm do
  próprio código.
* **Processos**: OCR e montagem rodam como subprocessos com lista de
  argumentos (sem shell).

## Riscos que permanecem

* **Outros usuários do mesmo computador** alcançam `127.0.0.1` e, portanto, a
  API (sem senha). Em computador compartilhado, use uma conta própria do
  sistema e não deixe o servidor ligado sem necessidade.
* **PDFs maliciosos** são abertos pelo PyMuPDF (MuPDF, em C). O limite de
  tamanho e a extração em processo separado reduzem o impacto, mas não o
  eliminam: abra só livros de fonte conhecida.
* **Privacidade da tradução**: o texto em prosa passa pela Pollinations e pelo
  fornecedor do modelo; a política de retenção deles não está documentada.
* **A chave usada nos testes do projeto foi colada no chat**: troque-a.

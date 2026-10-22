# Camada de tradução

Estado: implementada e testada com provedor de teste e com respostas simuladas
pelos tipos reais de cada SDK. **Ainda não foi feita nenhuma chamada real** a
Claude, ChatGPT ou Gemini: esta sessão não tem chaves de API. O primeiro uso
com chave deve começar por poucas páginas (ver "Primeiro uso").

## Provedores

| Provedor | SDK (licença) | API usada | Modelo | Saída estruturada |
|---|---|---|---|---|
| `anthropic` (Claude) | `anthropic` 2.1.0 (Apache-2.0) | Messages (beta, por causa de `fallbacks`) | padrão `claude-opus-5-5`; configurável | `output_config.format` JSON Schema |
| `openai` (ChatGPT) | `openai` 3.36.1 (Apache-2.0) | Responses | **obrigatório configurar** | `text.format` JSON Schema estrito |
| `gemini` (Google) | `google-genai` 2.32.0 (Apache-2.0) | `models.generate_content` | **obrigatório configurar** | `response_json_schema` |
| `fake` | — | local | — | — (só marca o texto com `[PT-TESTE]`) |

Para OpenAI e Gemini o código não fixa um nome de modelo: os catálogos mudam
com frequência e um nome errado falharia só na hora do uso. A configuração
recusa iniciar sem `CHESSBOOK_OPENAI_MODEL` / `CHESSBOOK_GEMINI_MODEL`.

Detalhes por provedor:

* **Claude:** esforço `high` por padrão (`CHESSBOOK_ANTHROPIC_EFFORT`);
  `fallbacks: "default"` reexecuta o pedido em outro modelo da Anthropic se
  houver recusa por política (o modelo que respondeu fica registrado; desligue
  com `CHESSBOOK_ANTHROPIC_FALLBACKS=off`); cache de prompt automático no
  prefixo fixo (regras + glossário).
* **ChatGPT:** `store=False`; esforço de raciocínio opcional
  (`CHESSBOOK_OPENAI_REASONING_EFFORT`), só para modelos que o aceitam.
* **Gemini:** chave em `GEMINI_API_KEY` (ou `GOOGLE_API_KEY`).
* Os três: recusa, bloqueio de segurança, resposta incompleta ou cortada por
  limite de tokens viram erro explícito, nunca texto parcial aceito.

## O que é enviado

Para cada lote (até 20 segmentos ou cerca de 6.000 caracteres):

* as instruções de tradução e o glossário inteiro (fixos, iguais para todos);
* o título do livro como "seção";
* cada segmento **com a notação substituída por marcadores** `⟦n⟧`;
* o parágrafo anterior, também mascarado, como contexto.

Não são enviados: o PDF, imagens, diagramas, lances, nomes de arquivo ou
metadados do projeto. Segmentos que só contêm notação, números e pontuação
não são enviados.

Os provedores remotos só funcionam com `CHESSBOOK_PRIVACY_MODE=remote_allowed`.
A retenção dos dados segue os termos da conta de cada provedor.

## Garantias na volta

Cada tradução só é aceita se:

1. todos os marcadores voltarem exatamente uma vez, sem marcadores inventados;
2. as casas citadas na prosa ("o cavalo em f3") forem as mesmas do original;
3. os símbolos de avaliação fora da notação (△, ⊙, +−, ±…) forem os mesmos.

Se falhar, o segmento é reenviado sozinho uma vez; persistindo, fica
`needs_review` com a saída bruta guardada. Avisos não bloqueantes: números da
prosa diferentes, ordem dos marcadores alterada e razão de comprimento PT/EN
fora de 0,7–1,8.

Parênteses de prosa ("(but not …)") ficam fora dos marcadores, visíveis para o
tradutor; a notação é restaurada byte a byte, inclusive figurinas e símbolos.

## Custo e falhas

* Os tokens de entrada, saída e cache são registrados por chamada. O custo em
  moeda **não é estimado** pelo código: os preços mudam e variam por conta.
* Cache local (SQLite) por provedor + modelo + versão do prompt + texto: repetir
  uma tradução não gera nova chamada.
* Duas falhas seguidas do provedor (por exemplo, chave inválida) interrompem o
  envio; os segmentos restantes ficam `failed` com a mensagem do erro.
* Os SDKs já repetem automaticamente erros 429/5xx.

## Primeiro uso

```bash
cp .env.example .env     # preencha a chave e, para OpenAI/Gemini, o modelo
# CHESSBOOK_PRIVACY_MODE=remote_allowed
cd backend
.venv/bin/python -m scripts.translate_pages LIVRO.pdf /fora/do/repo/saida --pages 21 --provider anthropic
```

Comece por uma página, confira `comparativo.html` e só depois rode a amostra
inteira. Para comparar provedores, rode as mesmas páginas com
`--provider openai` e `--provider gemini` em diretórios de saída diferentes.

## Ainda não implementado

* Aplicar a preferência de notação de saída (EN/PT/FAN) às partes restauradas:
  hoje a notação volta exatamente como no original (padrão "preservar").
* Contexto por capítulo (título da seção real), em vez do título do livro.
* Message Batches API (Claude) e equivalentes, para traduzir o livro inteiro
  com custo menor.
* Interface para editar o glossário e revisar segmentos.

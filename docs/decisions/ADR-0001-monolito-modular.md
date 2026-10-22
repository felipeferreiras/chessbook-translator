# ADR-0001 — Monólito modular local

**Estado:** aceito (Fase 1) · **Data:** 2026-10-22

## Contexto
Um único usuário, uso privado, livros com centenas de páginas, tarefas longas
que precisam ser retomadas. Privacidade é requisito central.

## Decisão
* Backend Python 3.12+ com FastAPI, um processo, escutando em `127.0.0.1`.
* Tarefas longas num executor interno com fila persistida em SQLite (estados
  por etapa, progresso, cancelamento, retomada). Sem Redis/Celery.
* SQLite para metadados; arquivos por projeto em `storage/<projeto>/`.
* Frontend React + TypeScript com Vite, servido como estático pelo backend.
* Cada módulo do pipeline expõe funções puras ou interfaces (`PdfReader`,
  `OcrEngine`, `TranslationProvider`, `LayoutEngine`) e não importa detalhes de
  outro módulo.

## Consequências
* Instalação simples (um `venv` e um `npm build`), sem serviços externos.
* Concorrência limitada a uma máquina, suficiente para o caso de uso.
* Se surgir uso multiusuário, migram-se a fila e o banco (PostgreSQL), sem
  mexer no domínio.

## Alternativas consideradas
Next.js (segundo servidor sem ganho), microserviços (complexidade sem
necessidade), aplicação desktop (Electron/Tauri: possível no futuro, mas o
navegador local já resolve).

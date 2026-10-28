#!/usr/bin/env bash
# Inicia o chessbook-translator: a interface fica em http://127.0.0.1:8000 (só neste computador).
#
#   ./iniciar.sh [PORTA]
#
# Os projetos ficam em CHESSBOOK_STORAGE (definido no .env; padrão: ./storage).
set -euo pipefail
cd "$(dirname "$0")"
PORTA="${1:-8000}"
[ -x backend/.venv/bin/uvicorn ] || { echo "Rode ./instalar.sh primeiro."; exit 1; }
[ -f frontend/dist/index.html ] || { echo "Interface não compilada: rode ./instalar.sh."; exit 1; }
URL="http://127.0.0.1:${PORTA}"
echo "chessbook-translator em ${URL}  (Ctrl+C para encerrar)"
if [ -z "${SEM_NAVEGADOR:-}" ]; then
  (sleep 2; command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 || command -v open >/dev/null && open "$URL") &
fi
cd backend
# Só 127.0.0.1: o livro e a tradução nunca ficam expostos na rede.
exec .venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port "$PORTA" --no-server-header

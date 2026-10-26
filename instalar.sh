#!/usr/bin/env bash
# Instala o chessbook-translator neste computador (Linux ou macOS).
#
#   ./instalar.sh
#
# Requisitos que o script não instala sozinho (pacotes do sistema):
#   Python 3.12+, Node.js 20.19+ (ou 22.12+), uv (https://docs.astral.sh/uv/)
#   Debian/Ubuntu: sudo apt install fonts-liberation fonts-freefont-ttf fonts-dejavu-core \
#                                   tesseract-ocr tesseract-ocr-eng
# Tesseract é opcional: só é usado em livros digitalizados.
set -euo pipefail
cd "$(dirname "$0")"

falta() { echo "✗ $1"; exit 1; }
command -v python3 >/dev/null || falta "Python 3.12+ não encontrado"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' || falta "Python 3.12+ é necessário ($(python3 --version))"
command -v uv >/dev/null || falta "uv não encontrado: https://docs.astral.sh/uv/getting-started/installation/"
command -v node >/dev/null || falta "Node.js 20.19+ não encontrado (só para compilar a interface)"
node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit((a===20&&b>=19)||(a===22&&b>=12)||a>22?0:1)' \
  || falta "Node.js 20.19+ ou 22.12+ é necessário ($(node --version))"

echo "→ backend (ambiente Python em backend/.venv)"
(cd backend && uv venv --quiet .venv && uv pip install --quiet --python .venv/bin/python -e .)

echo "→ interface (compilada em frontend/dist)"
(cd frontend && npm ci --silent --no-audit --no-fund && npm run --silent build >/dev/null)

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "→ .env criado a partir de .env.example (tradução externa bloqueada até você permitir)"
fi

echo
(cd backend && .venv/bin/python -m scripts.doctor) || true
echo
echo "Para usar: ./iniciar.sh  (abre em http://127.0.0.1:8000)"

"""Proteções da API local contra páginas da web abertas no mesmo navegador.

A API só escuta em ``127.0.0.1``, mas o navegador do usuário também visita
outros sites, e dois ataques chegam a um servidor local assim:

* **DNS rebinding**: o domínio do atacante passa a apontar para 127.0.0.1; a
  página dele vira "mesma origem" da API e pode ler o livro e a tradução, ou
  iniciar tarefas que gastam. Defesa: só aceitar pedidos cujo ``Host`` seja
  um nome local (``localhost``, ``127.0.0.1``, ``[::1]``) ou um nome
  autorizado em ``CHESSBOOK_ALLOWED_HOSTS``.
* **CSRF**: um formulário de outro site faz um POST "simples" (sem preflight).
  Defesa: pedidos que alteram algo (POST, PUT, DELETE) com ``Origin`` ou
  ``Sec-Fetch-Site`` de outro site são recusados.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}  # testserver: cliente de testes do Starlette
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in os.environ.get("CHESSBOOK_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return LOCAL_HOSTS | extra


def _hostname(value: str) -> str:
    """Nome sem porta: "127.0.0.1:8000" → "127.0.0.1"; "[::1]:8000" → "::1"."""
    return (urlsplit(f"//{value}").hostname or "").lower()


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        hosts = allowed_hosts()
        if _hostname(request.headers.get("host", "")) not in hosts:
            return JSONResponse({"detail": "host não autorizado"}, status_code=403)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin != "null" and _hostname(urlsplit(origin).netloc) not in hosts:
                return JSONResponse({"detail": "pedido de outra origem recusado"}, status_code=403)
            if origin == "null" or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "pedido de outra origem recusado"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

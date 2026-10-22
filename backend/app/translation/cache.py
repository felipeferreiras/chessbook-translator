"""Cache local de traduções (SQLite), para não pagar duas vezes pelo mesmo trecho.

A chave inclui versão do prompt, provedor, modelo, instruções, seção, contexto
e texto mascarado: qualquer mudança gera nova tradução.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class TranslationCache:
    def __init__(self, path: Path | str = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS translation_cache ("
            " key TEXT PRIMARY KEY, provider TEXT, model TEXT, text TEXT,"
            " created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )

    def get(self, key: str) -> str | None:
        row = self.db.execute("SELECT text FROM translation_cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, provider: str, model: str, text: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO translation_cache (key, provider, model, text) VALUES (?, ?, ?, ?)",
            (key, provider, model, text),
        )
        self.db.commit()

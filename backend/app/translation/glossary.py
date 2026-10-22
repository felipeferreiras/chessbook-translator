"""Glossário técnico editável.

As entradas orientam o tradutor; não são substituição cega. O prompt informa
a tradução preferencial, as alternativas e o contexto de uso, e a decisão em
cada ocorrência continua sendo do tradutor (e da revisão humana).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "data" / "glossary_default.json"


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    preferred: str
    alternatives: list[str] = field(default_factory=list)
    context: str = ""
    notes: str = ""
    category: str = "geral"
    priority: int = 1  # 1 = alta
    examples: list[str] = field(default_factory=list)


@dataclass
class Glossary:
    entries: list[GlossaryEntry]

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> Glossary:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([GlossaryEntry(**e) for e in data["entries"]])

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps({"entries": [asdict(e) for e in self.entries]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def relevant(self, text: str) -> list[GlossaryEntry]:
        """Entradas cujo termo aparece no texto (palavra inteira, sem caixa)."""
        found = []
        for e in self.entries:
            if re.search(rf"(?<![\w-]){re.escape(e.term)}(?![\w-])", text, re.IGNORECASE):
                found.append(e)
        return sorted(found, key=lambda e: (e.priority, e.term.lower()))

    def as_prompt_lines(self) -> list[str]:
        lines = []
        for e in sorted(self.entries, key=lambda e: (e.priority, e.term.lower())):
            alt = f" (alternativas: {', '.join(e.alternatives)})" if e.alternatives else ""
            ctx = f" — {e.context}" if e.context else ""
            lines.append(f"- {e.term} → {e.preferred}{alt}{ctx}")
        return lines

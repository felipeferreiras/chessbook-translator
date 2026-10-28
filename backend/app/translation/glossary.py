"""Glossário técnico editável, aplicado por contexto.

As entradas orientam o tradutor; não são substituição cega. Cada lote recebe
só as entradas cujo termo aparece nos seus segmentos, e a decisão em cada
ocorrência continua sendo do tradutor (e da revisão humana).

Depois da tradução, ``check`` confere o resultado:

* ``glossario_evitar``: apareceu uma tradução marcada como errada para o termo
  ("deflection" → "atração", que é *decoy*). Pede revisão.
* ``glossario_ausente``: o termo está no original e nenhuma das traduções
  aceitas aparece. Só informa: o contexto pode justificar outra escolha.

A comparação tolera flexão: plural e tempos no inglês ("outposts", "drawn"),
plural e gênero no português ("finais", "peões", "branco"/"brancas"), e
ignora artigos e preposições ("as brancas" casa com "das brancas").
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "data" / "glossary_default.json"

_PT_STOPWORDS = {
    "o", "a", "os", "as", "do", "da", "dos", "das", "de", "ao", "à", "aos", "às", "no", "na", "nos", "nas",
    "pelo", "pela", "pelos", "pelas", "um", "uma", "e", "com",
}


def _en_word(word: str) -> str:
    w = re.escape(word)
    if word.endswith("y"):
        return w[:-1] + r"(?:y|ies)"
    return w + r"(?:s|es|n|ed|ing)?"


def _pt_word(word: str) -> str:
    """Um padrão que aceita plural e gênero: "peão"/"peões", "final"/"finais", "empate"/"empatada"."""
    low = word.lower()
    if len(low) > 4 and low.endswith(("as", "os", "es")):
        low = low[:-1]  # "brancas" → "branca": o radical abaixo aceita "branco" também
    if low.endswith("ão"):
        return re.escape(low[:-2]) + r"(?:ão|ões|ães|ãos)"
    if low.endswith("l"):
        return re.escape(low[:-1]) + r"(?:l|is)"
    if len(low) > 4:
        # Radical: "empate" também casa "empata", "empatada"; "branco", "brancas".
        return re.escape(low[:-1]) + r"\w*"
    return re.escape(low) + r"(?:s|es)?"


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
    avoid: list[str] = field(default_factory=list)  # traduções erradas para este termo
    case_sensitive: bool = False  # "White" (as brancas) não é "white pawn" (peão branco)
    check: bool = True  # False: não avisar ausência (termo ambíguo: "the square", "move" verbo); "avoid" vale sempre

    def source_pattern(self) -> re.Pattern[str]:
        words = self.term.split()
        body = r"\s+".join(re.escape(w) for w in words[:-1]) + (r"\s+" if len(words) > 1 else "") + _en_word(words[-1])
        flags = 0 if self.case_sensitive else re.IGNORECASE
        return re.compile(rf"(?<![\w-]){body}(?![\w-])", flags)

    @property
    def accepted(self) -> list[str]:
        return [self.preferred, *self.alternatives]


@functools.cache
def _phrase(text: str) -> re.Pattern[str] | None:
    """Palavras de conteúdo da expressão, em ordem, com até quatro palavras entre elas."""
    words = [w for w in re.findall(r"[\w-]+", text.lower()) if w not in _PT_STOPWORDS]
    if not words:
        return None
    gap = r"(?:\W+\w+){0,4}?\W+"
    return re.compile(r"(?<!\w)" + gap.join(_pt_word(w) for w in words) + r"(?!\w)", re.IGNORECASE)


def _present(phrase: str, text: str) -> bool:
    pattern = _phrase(phrase)
    return pattern is not None and pattern.search(text) is not None


@dataclass
class Glossary:
    entries: list[GlossaryEntry]

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH, overrides: Path | None = None) -> Glossary:
        """Glossário padrão; ``overrides`` (do projeto) substitui ou acrescenta entradas pelo termo."""
        entries = {e["term"]: GlossaryEntry(**e) for e in json.loads(path.read_text(encoding="utf-8"))["entries"]}
        if overrides is not None and overrides.exists():
            for e in json.loads(overrides.read_text(encoding="utf-8"))["entries"]:
                entries[e["term"]] = GlossaryEntry(**e)
        return cls(list(entries.values()))

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps({"entries": [asdict(e) for e in self.entries]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def relevant(self, text: str) -> list[GlossaryEntry]:
        """Entradas cujo termo aparece no texto (palavra inteira, com flexão)."""
        found = [e for e in self.entries if e.source_pattern().search(text)]
        return sorted(found, key=lambda e: (e.priority, e.term.lower()))

    @staticmethod
    def prompt_lines(entries: list[GlossaryEntry]) -> list[str]:
        lines = []
        for e in entries:
            alt = f" (alternativas: {', '.join(e.alternatives)})" if e.alternatives else ""
            avoid = f" (nunca: {', '.join(e.avoid)})" if e.avoid else ""
            ctx = f" — {e.context}" if e.context else ""
            lines.append(f"- {e.term} → {e.preferred}{alt}{avoid}{ctx}")
        return lines

    def as_prompt_lines(self) -> list[str]:
        return self.prompt_lines(sorted(self.entries, key=lambda e: (e.priority, e.term.lower())))

    def check(self, source: str, translation: str) -> list[str]:
        """Avisos de uso do glossário numa tradução (ver o início do módulo)."""
        warnings = []
        for e in self.relevant(source):
            wrong = [a for a in e.avoid if _present(a, translation)]
            if wrong:
                warnings.append(f"glossario_evitar: '{e.term}' traduzido como '{wrong[0]}' (preferido: '{e.preferred}')")
            elif e.check and not any(_present(a, translation) for a in e.accepted):
                warnings.append(f"glossario_ausente: '{e.term}' sem '{e.preferred}'")
        return warnings


GLOSSARY_REVIEW_PREFIX = "glossario_evitar:"

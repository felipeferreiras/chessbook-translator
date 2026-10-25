"""Contrato comum dos provedores de tradução.

Cada provedor recebe um lote de segmentos já mascarados (a notação foi
trocada por marcadores ``⟦n⟧`` pelo ``guard``) e devolve as traduções por id.
Nenhum provedor vê o PDF, imagens ou lances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ProviderError(RuntimeError):
    """Falha do provedor (rede, autenticação, cota, resposta inválida).

    ``usage``: tokens de uma resposta que chegou mas não serviu (cortada, JSON
    inválido). Foram cobrados e entram no custo da tarefa.
    """

    def __init__(self, message: str, usage: Usage | None = None):
        super().__init__(message)
        self.usage = usage


class ProviderRefusal(ProviderError):
    """O modelo recusou ou bloqueou a resposta; não é um erro de rede."""


class ConfigurationError(RuntimeError):
    """Configuração ausente ou inválida (chave, modelo, privacidade)."""


@dataclass(frozen=True)
class Segment:
    id: str
    text: str  # texto mascarado: notação substituída por ⟦n⟧
    context_before: str = ""  # parágrafo anterior (fonte), só para contexto
    kind: str = "paragraph"  # paragraph | heading | caption | header | footnote


@dataclass(frozen=True)
class TranslationRequest:
    segments: list[Segment]
    system_prompt: str
    user_payload: str  # JSON com seção e segmentos


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None


@dataclass
class BatchResult:
    translations: dict[str, str]
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    raw_text: str = ""
    notes: list[str] = field(default_factory=list)


class TranslationProvider(Protocol):
    name: str
    model: str
    remote: bool  # envia conteúdo para fora da máquina?

    def translate_batch(self, request: TranslationRequest) -> BatchResult: ...


# Esquema JSON da resposta, igual para todos os provedores.
OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


def parse_output(raw: str, expected_ids: list[str]) -> dict[str, str]:
    """Converte a resposta JSON em {id: texto}; ids desconhecidos são descartados."""
    import json
    import re

    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:  # modelos sem modo JSON costumam cercar a resposta com ```json
        text = fenced.group(1)
    # Alguns modelos devolvem o objeto e mais texto, ou dois objetos seguidos: lê todos em sequência.
    # Cada tradução ainda passa pela proteção, então aceitar o que veio a mais não arrisca a notação.
    decoder = json.JSONDecoder()
    objects, pos = [], 0
    if text and text[0] != "{" and "{" in text:  # "Aqui está a tradução: {...}": pula o preâmbulo
        pos = text.index("{")
    while pos < len(text):
        try:
            data, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError as exc:
            if not objects:
                raise ProviderError(f"resposta não é JSON válido: {exc}") from exc
            break  # texto solto depois do JSON
        objects.append(data)
        pos = end
        while pos < len(text) and text[pos].isspace():
            pos += 1
    items = [it for d in objects if isinstance(d, dict) and isinstance(d.get("translations"), list)
             for it in d["translations"]]
    if not items and not any(isinstance(d, dict) and isinstance(d.get("translations"), list) for d in objects):
        raise ProviderError("resposta sem a lista 'translations'")
    out: dict[str, str] = {}
    wanted = set(expected_ids)
    for item in items:
        if isinstance(item, dict) and item.get("id") in wanted and isinstance(item.get("text"), str):
            out.setdefault(item["id"], item["text"])  # repetido: vale a primeira
    return out

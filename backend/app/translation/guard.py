"""Proteção da notação durante a tradução automática.

Antes de enviar um texto ao tradutor, cada trecho de notação é substituído por
um marcador opaco (``⟦1⟧``, ``⟦2⟧``...). O tradutor de prosa nunca vê os
lances. Na volta, a restauração exige que todos os marcadores estejam presentes
exatamente uma vez e que as referências a casas fora da notação ("o cavalo em
f3") sejam as mesmas do original. Qualquer divergência gera ``GuardViolation``:
o segmento vai para revisão em vez de ser aceito.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.chess.notation.lexer import DEFAULT_STYLE, AtomKind, LexStyle, lex

PLACEHOLDER_RE = re.compile(r"⟦(\d+)⟧")
# Negrito e itálico da prosa vão ao tradutor como <b>…</b> e <i>…</i>.
TAG_RE = re.compile(r"</?([bi])>")
_ANY_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*\s*/?>")
_TOKEN_RE = re.compile(r"⟦(\d+)⟧|</?([bi])>")
_LETTERS_RE = re.compile(r"[^\W\d_]{2}")
TAG_NAMES = {"b": "negrito", "i": "itálico"}
SQUARE_RE = re.compile(r"(?<![\w])[a-h][1-8](?![\w])")
NUMBER_RE = re.compile(r"(?<![\w⟦])\d+(?![\w⟧])")
# Símbolos de avaliação e anotação fora da notação ("△ ...", "+−" isolado).
SYMBOL_RE = re.compile(r"\+−|−\+|[⊙△□⇆∞±∓⩲⩱]")


class GuardViolation(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Protected:
    original: str
    masked: str
    slots: dict[str, str]
    squares: Counter[str]
    numbers: Counter[str]
    symbols: Counter[str] = field(default_factory=Counter)
    slot_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)  # posição no original
    tags: Counter[str] = field(default_factory=Counter)  # trechos de prosa marcados com <b>/<i>


@dataclass
class Restored:
    text: str
    warnings: list[str] = field(default_factory=list)
    pieces: list[tuple[int, int, str]] = field(default_factory=list)  # (início, fim, marcador) no texto final
    styles: list[tuple[int, int, str]] = field(default_factory=list)  # (início, fim, "b"|"i") no texto final


_NOTATION_KINDS = (AtomKind.MOVE, AtomKind.SUSPICIOUS, AtomKind.DESCRIPTIVE, AtomKind.ROUTE)


def _groups(span, text: str) -> list[list]:
    """Divide um trecho nos parênteses de prosa e nas quebras de linha.

    Os dois devem ficar visíveis ao tradutor. Uma quebra separa, por exemplo, o
    lance da partida em linha própria ("1 Bd1+!? Kh4??") da correção que vem
    na linha seguinte ("1...Kg6! was necessary"); num marcador único, o
    tradutor não teria como saber a qual dos dois a prosa se refere.
    """
    groups: list[list] = [[]]
    for atom in span.atoms:
        if atom.kind in (AtomKind.PAREN_OPEN, AtomKind.PAREN_CLOSE):
            groups.append([])
            continue
        if groups[-1] and "\n" in text[groups[-1][-1].end:atom.start]:
            groups.append([])
        groups[-1].append(atom)
    out: list[list] = []
    for group in groups:
        out.extend(_split_unpaired(group))
    return [g for g in out if g and any(a.kind in _NOTATION_KINDS for a in g)]


def _split_unpaired(group: list) -> list[list]:
    """Tira de um trecho os parênteses de variante sem par dentro dele.

    Em "4 fe (5 Rd7+! is threatened) 4...Ke7" a prosa fica dentro do parêntese;
    se "(" e ")" fossem para marcadores diferentes, o tradutor não veria o
    parêntese e poderia levar a prosa para fora dele.
    """
    stack: list[int] = []
    unpaired: set[int] = set()
    for i, atom in enumerate(group):
        if atom.kind == AtomKind.VAR_OPEN:
            stack.append(i)
        elif atom.kind == AtomKind.VAR_CLOSE:
            if stack:
                stack.pop()
            else:
                unpaired.add(i)
    unpaired.update(stack)
    parts: list[list] = [[]]
    for i, atom in enumerate(group):
        if i in unpaired:
            parts.append([])
        else:
            parts[-1].append(atom)
    return parts


def _styled_prose(chunk: str, flags: list[tuple[bool, bool]], use: tuple[bool, bool], tags: Counter[str]) -> str:
    """Marca com <b>/<i> os trechos de prosa (sem quebra, tabulação nem notação) com estilo."""
    out: list[str] = []
    i = 0
    while i < len(chunk):
        j = i
        while j < len(chunk) and flags[j] == flags[i] and chunk[j] not in "\n\t":
            j += 1
        if j == i:  # quebra ou tabulação
            out.append(chunk[i])
            i += 1
            continue
        piece = chunk[i:j]
        bold, italic = flags[i][0] and use[0], flags[i][1] and use[1]
        core = piece.strip()
        if (bold or italic) and _LETTERS_RE.search(core):
            lead = piece[:len(piece) - len(piece.lstrip())]
            trail = piece[len(piece.rstrip()):]
            opened = ("<b>" if bold else "") + ("<i>" if italic else "")
            closed = ("</i>" if italic else "") + ("</b>" if bold else "")
            tags.update(["b"] * bold + ["i"] * italic)
            piece = lead + opened + core + closed + trail
        out.append(piece)
        i = j
    return "".join(out)


def protect(text: str, style: LexStyle = DEFAULT_STYLE, bold: list[bool] | tuple[bool, ...] = (),
            italic: list[bool] | tuple[bool, ...] = ()) -> Protected:
    """Mascara a notação; ``bold``/``italic`` (por caractere) marcam a prosa com <b>/<i>.

    Estilo que cobre toda a prosa do bloco não é marcado: vem do próprio bloco.
    """
    lexed = lex(text, style)
    slots: dict[str, str] = {}
    ranges: dict[str, tuple[int, int]] = {}
    for span in lexed.spans:
        for group in _groups(span, text):
            start, end = group[0].start, group[-1].end
            key = str(len(slots) + 1)
            slots[key] = text[start:end]
            ranges[key] = (start, end)
    flags = [(i < len(bold) and bool(bold[i]), i < len(italic) and bool(italic[i])) for i in range(len(text))]
    in_slot = [False] * len(text)
    for start, end in ranges.values():
        for i in range(start, end):
            in_slot[i] = True
    visible = [i for i, ch in enumerate(text) if not in_slot[i] and not ch.isspace()]
    use = (not all(flags[i][0] for i in visible) if visible else False,
           not all(flags[i][1] for i in visible) if visible else False)
    tags: Counter[str] = Counter()
    parts: list[str] = []
    cursor = 0
    for key, (start, end) in ranges.items():
        parts.append(_styled_prose(text[cursor:start], flags[cursor:start], use, tags))
        parts.append(f"⟦{key}⟧")
        cursor = end
    parts.append(_styled_prose(text[cursor:], flags[cursor:], use, tags))
    masked = "".join(parts)
    prose = TAG_RE.sub("", PLACEHOLDER_RE.sub(" ", masked))
    return Protected(
        original=text, masked=masked, slots=slots,
        squares=Counter(SQUARE_RE.findall(prose)), numbers=Counter(NUMBER_RE.findall(prose)),
        symbols=Counter(SYMBOL_RE.findall(prose)), slot_ranges=ranges, tags=tags,
    )


def restore(translated: str, protected: Protected) -> Restored:
    problems: list[str] = []
    found = Counter(PLACEHOLDER_RE.findall(translated))
    for key in protected.slots:
        if found[key] == 0:
            problems.append(f"marcador ⟦{key}⟧ ausente ({protected.slots[key]!r})")
        elif found[key] > 1:
            problems.append(f"marcador ⟦{key}⟧ duplicado")
    for key in found:
        if key not in protected.slots:
            problems.append(f"marcador desconhecido ⟦{key}⟧")
    unknown = [t for t in _ANY_TAG_RE.findall(translated) if not TAG_RE.fullmatch(t)
               and t not in protected.original]
    if unknown:
        problems.append(f"marcação desconhecida na tradução: {sorted(set(unknown))}")
    problems.extend(_tag_problems(translated))
    prose = TAG_RE.sub("", PLACEHOLDER_RE.sub(" ", translated))
    squares = Counter(SQUARE_RE.findall(prose))
    if squares != protected.squares:
        problems.append(
            f"casas na prosa divergem: original={dict(protected.squares)} tradução={dict(squares)}"
        )
    symbols = Counter(SYMBOL_RE.findall(prose))
    if symbols != protected.symbols:
        problems.append(
            f"símbolos de avaliação divergem: original={dict(protected.symbols)} tradução={dict(symbols)}"
        )
    # Números da prosa são dados (diagramas 1-21, exercícios 1/6, páginas, anos):
    # qualquer número a mais ou a menos bloqueia a aceitação.
    numbers = Counter(NUMBER_RE.findall(prose))
    if numbers != protected.numbers:
        diff = {k: (protected.numbers.get(k, 0), numbers.get(k, 0))
                for k in sorted(set(numbers) | set(protected.numbers), key=int)
                if protected.numbers.get(k, 0) != numbers.get(k, 0)}
        problems.append(
            "números na prosa divergem (número: original → tradução): "
            + ", ".join(f"{k}: {a} → {b}" for k, (a, b) in diff.items())
        )
    # Quebras e tabulações são estrutura (itens de índice, sumário, lance
    # destacado em linha própria). Perdê-las desloca palavras para o lance errado.
    for ch, name in (("\n", "quebras de linha"), ("\t", "tabulações")):
        if translated.count(ch) != protected.masked.count(ch):
            problems.append(f"{name} divergem: original={protected.masked.count(ch)} tradução={translated.count(ch)}")
    if not problems and _paren_groups(translated) != _paren_groups(protected.masked):
        problems.append("parênteses com notação mudaram: prosa ou lances entraram ou saíram deles")
    if not problems and "\n" in protected.masked:
        lines_src = [sorted(PLACEHOLDER_RE.findall(line)) for line in protected.masked.split("\n")]
        lines_out = [sorted(PLACEHOLDER_RE.findall(line)) for line in translated.split("\n")]
        if lines_src != lines_out:
            problems.append("trechos de notação mudaram de linha na tradução")
    if problems:
        raise GuardViolation(problems)
    warnings: list[str] = []
    order = [int(k) for k in PLACEHOLDER_RE.findall(translated)]
    if order != sorted(order):
        warnings.append("ordem dos trechos de notação foi alterada pela tradução")
    found_tags = Counter(m.group(1) for m in TAG_RE.finditer(translated) if not m.group(0).startswith("</"))
    for tag, name in TAG_NAMES.items():
        if found_tags[tag] != protected.tags[tag]:
            warnings.append(f"trechos em {name} divergem: original={protected.tags[tag]} tradução={found_tags[tag]}")
    out: list[str] = []
    pieces: list[tuple[int, int, str]] = []
    styles: list[tuple[int, int, str]] = []
    opened: dict[str, int] = {}
    cursor = length = 0
    for m in _TOKEN_RE.finditer(translated):
        out.append(translated[cursor:m.start()])
        length += m.start() - cursor
        cursor = m.end()
        if m.group(1):
            slot = protected.slots[m.group(1)]
            pieces.append((length, length + len(slot), m.group(1)))
            out.append(slot)
            length += len(slot)
        elif m.group(0).startswith("</"):
            start = opened.pop(m.group(2))
            if length > start:
                styles.append((start, length, m.group(2)))
        else:
            opened[m.group(2)] = length
    out.append(translated[cursor:])
    return Restored(text="".join(out), warnings=warnings, pieces=pieces, styles=sorted(styles))


def _paren_groups(masked: str) -> Counter[tuple[tuple[str, ...], bool]]:
    """Parênteses de prosa que contêm marcadores: (marcadores, tem prosa).

    "(⟦2⟧ is threatened)" diz que o lance é uma ameaça; se a tradução levar a
    prosa para fora ("Ameaça-se ⟦1⟧ (⟦2⟧)"), o sentido muda.
    """
    groups: Counter[tuple[tuple[str, ...], bool]] = Counter()
    stack: list[int] = []
    for i, ch in enumerate(masked):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            inner = masked[stack.pop() + 1:i]
            keys = tuple(sorted(PLACEHOLDER_RE.findall(inner)))
            if keys:
                prose = TAG_RE.sub("", PLACEHOLDER_RE.sub(" ", inner))
                groups[(keys, bool(re.search(r"[^\W\d_]", prose)))] += 1  # "e" também é prosa
    return groups


def _tag_problems(translated: str) -> list[str]:
    """<b>/<i> precisam estar abertos e fechados em ordem, sem atravessar linhas."""
    stack: list[str] = []
    for line in translated.split("\n"):
        for m in TAG_RE.finditer(line):
            tag = m.group(1)
            if not m.group(0).startswith("</"):
                if tag in stack:
                    return [f"marca <{tag}> aberta duas vezes"]
                stack.append(tag)
            elif not stack or stack[-1] != tag:
                return [f"marca </{tag}> sem abertura correspondente"]
            else:
                stack.pop()
        if stack:
            return [f"marca <{stack[-1]}> não fechada na mesma linha"]
    return []


def mask_edit(text: str, protected: Protected) -> str:
    """Remascara um texto editado à mão: cada trecho de notação volta a ser marcador.

    A revisão edita o texto final, com os lances visíveis. Para aceitar a
    edição, cada trecho de notação do original precisa continuar lá, byte a
    byte; os mais longos são procurados primeiro (um lance curto pode estar
    contido num trecho maior). Depois disso, ``restore`` aplica as mesmas
    regras da tradução automática (casas, números, símbolos, linhas,
    parênteses). Levanta ``GuardViolation`` se algum trecho sumiu ou mudou.
    """
    out = text
    problems = []
    for key, slot in sorted(protected.slots.items(), key=lambda kv: -len(kv[1])):
        if slot not in out:
            problems.append(f"trecho de notação ⟦{key}⟧ alterado ou removido: {slot!r}")
            continue
        out = out.replace(slot, f"⟦{key}⟧", 1)
    if problems:
        raise GuardViolation(problems)
    restore(out, protected)
    return out

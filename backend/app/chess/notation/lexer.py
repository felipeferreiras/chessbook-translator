"""Análise léxica de notação enxadrística misturada com prosa.

O analisador não altera o texto. Ele devolve átomos com posições exatas
(``start``/``end``) sobre a string original, para que qualquer etapa posterior
possa reconstruir o texto byte a byte, trocando apenas o que foi validado.

Regras conservadoras adotadas:

* Uma casa isolada (``e4``) só é considerada lance de peão quando está num trecho
  de notação com número de lance, reticências ou outro lance de peça. Caso
  contrário, é uma referência a casa (``SQUARE_REF``), como em "o cavalo em f3".
* Parênteses só abrem variante quando o conteúdo começa com notação; parênteses
  de prosa são ignorados, mas a profundidade é rastreada para fechar a variante
  correta.
* Padrões como ``3.865`` dentro de um trecho de notação são marcados como
  ``SUSPICIOUS``: é o tipo de erro que o OCR produz ao ler ``3.♗b5``.
* Convenções próprias de cada livro (números sem ponto, capturas abreviadas
  de peão) só são aceitas quando o estilo do documento as declara
  (``LexStyle``), porque aumentam o risco de confundir prosa com notação.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from enum import StrEnum

from .alphabets import ALL_PIECE_CHARS


class AtomKind(StrEnum):
    MOVE_NUMBER = "move_number"
    ELLIPSIS = "ellipsis"
    MOVE = "move"
    SQUARE_REF = "square_ref"
    EVAL = "eval"
    RESULT = "result"
    VAR_OPEN = "var_open"
    VAR_CLOSE = "var_close"
    SUSPICIOUS = "suspicious"
    DESCRIPTIVE = "descriptive"
    ALT_DEST = "alt_dest"  # "♕b5(c2)": mesma peça, casa de destino alternativa
    PAREN_OPEN = "paren_open"  # parêntese de prosa que contém notação
    PAREN_CLOSE = "paren_close"


@dataclass(frozen=True)
class LexStyle:
    """Convenções tipográficas de notação de um documento.

    ``numbers_without_dot``: "2 ♔e4" em vez de "2.♔e4" (comum em livros de
    origem russa). ``abbreviated_pawn_captures``: "hg" para uma captura de
    peão da coluna h para a coluna g, sem casa de destino.
    """

    numbers_without_dot: bool = False
    abbreviated_pawn_captures: bool = False


DEFAULT_STYLE = LexStyle()


@dataclass(frozen=True)
class MoveSyntax:
    """Componentes sintáticos de um lance, sem interpretação de peça."""

    piece_char: str | None  # caractere original da peça; None para peão
    from_file: str | None
    from_rank: str | None
    separator: str | None  # "x", ":", "×", "-" ou None
    to_square: str | None
    promotion_char: str | None
    castle: str | None  # "K" (pequeno), "Q" (grande) ou None
    castle_text: str | None  # grafia original: "O-O", "0-0-0"...
    check: str  # "", "+", "++", "#", "†", "‡"
    annotation: str  # "", "!", "?", "!!", "??", "!?", "?!"
    en_passant: bool
    to_file: str | None = None  # captura abreviada "hg": só a coluna de destino
    info: str = ""  # símbolos do Informator colados ao lance: "⊙", "△", "+−"...

    @property
    def is_pawn(self) -> bool:
        return self.piece_char is None and self.castle is None

    @property
    def is_bare_square(self) -> bool:
        return self.is_pawn and self.separator is None and self.to_file is None

    @property
    def claims_capture(self) -> bool | None:
        if self.to_file:
            return True
        if self.separator is None:
            return None if self.castle else False
        return self.separator in "x:×"


@dataclass(frozen=True)
class Atom:
    kind: AtomKind
    start: int
    end: int
    text: str
    move: MoveSyntax | None = None
    number: int | None = None
    black: bool = False  # número de lance com reticências (lance das pretas)
    ellipsis_prefix: bool = False  # lance precedido de "..." sem número


@dataclass
class Span:
    """Trecho contínuo de notação (separado de outros apenas por espaços)."""

    atoms: list[Atom] = field(default_factory=list)

    @property
    def start(self) -> int:
        return self.atoms[0].start

    @property
    def end(self) -> int:
        return self.atoms[-1].end

    def has_moves(self) -> bool:
        return any(a.kind == AtomKind.MOVE for a in self.atoms)


@dataclass
class LexResult:
    text: str
    atoms: list[Atom]
    spans: list[Span]

    @property
    def moves(self) -> list[Atom]:
        return [a for a in self.atoms if a.kind == AtomKind.MOVE]


_P = re.escape(ALL_PIECE_CHARS)
_PROMO = re.escape("QRBNDTC♕♖♗♘♛♜♝♞")
_SEP = r"[-x:×]"
# Símbolos do Informator que podem vir colados ao lance ou isolados.
_INFO_SINGLE = "⊙△□⇆∞±∓⩲⩱"
_INFO = rf"(?:[{_INFO_SINGLE}]|\+−|−\+|\+-|-\+|=(?![{_PROMO}]))"

_MOVE_BODY = rf"""
(?P<castle>O-O-O|0-0-0|O-O|0-0)
|
(?P<piece>[{_P}])(?P<ff>[a-h])?(?P<fr>[1-8])?(?P<sep>{_SEP})?(?P<to>[a-h][1-8])
|
(?P<pff>[a-h])(?P<pfr>[1-8])?(?P<psep>{_SEP})(?P<pto>[a-h][1-8])
|
(?P<bare>[a-h][1-8])
"""
_ABBREVIATED = r"""
|
(?P<abff>[a-h])(?P<abtf>[a-h])
"""

_SUFFIX = rf"""
(?P<promo>=[{_PROMO}]|\([{_PROMO}]\)|/[{_PROMO}]|[{_PROMO}](?![\w]))?
(?P<ep>\s?e\.p\.)?
(?P<check>\+\+|\+(?![−\-])|[#†‡])?
(?P<ann>!!|\?\?|!\?|\?!|[!?])?
(?P<info>{_INFO}*)
"""


@functools.cache
def _move_regexes(style: LexStyle) -> tuple[re.Pattern[str], re.Pattern[str]]:
    body = _MOVE_BODY + (_ABBREVIATED if style.abbreviated_pawn_captures else "")
    free = re.compile(rf"(?<![\w\-./{_P}])(?:{body}){_SUFFIX}(?![\w\-])", re.VERBOSE)
    after_number = re.compile(rf"(?:{body}){_SUFFIX}(?![\w\-])", re.VERBOSE)
    return free, after_number


# Número de lance: "12." (brancas) ou "12..." / "12…" (pretas). Não aceita
# "3.5" (número decimal), exceto "5.0-0" (roque logo após o número).
_NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3})(\.\.\.|…|\.)(?=\s*(?:0-0|[^\d\s]|\s))")
# Número sem ponto ("2 ♔e4"): só vale se um lance vier logo depois.
_NUMBER_NODOT_RE = re.compile(r"(?<![\w.\-/])(\d{1,3})(?=\s+\S)")
_ELLIPSIS_RE = re.compile(r"(?<![\w.])(\.\.\.|…)(?=\S)")
_RESULT_RE = re.compile(r"(?<![\w\-])(1-0|0-1|½-½|1/2-1/2)(?![\w\-])")
_EVAL_RE = re.compile(
    rf"(?<![^\s(])(\+/-|-/\+|\+/=|=/\+|\+−|−\+|\+-|-\+|[{_INFO_SINGLE}]|=)(?![^\s).,;])"
)
_SUSPICIOUS_RE = re.compile(
    # "3.865": número de lance seguido de dígitos (OCR de "3.♗b5").
    r"(?<![\w.])\d{1,3}\.(?!0-0)\d[\w]*"
    # "\f3", "&c6": símbolo desconhecido colado a uma casa (OCR de "♘f3").
    rf"|(?<=[\s.])[^\s\w.,;:()\[\]\"'“”‘’«»…\-+=#!?{_P}{_INFO_SINGLE}]{{1,2}}[a-h]?[1-8]?x?[a-h][1-8](?![\w\-])"
)
# Casa alternativa logo após um lance: "♕b5(c2)?", "4...♔f4 (g4)".
_ALT_DEST_RE = re.compile(
    r"(?:(?<=[1-8!?+#⊙△])|(?<=[1-8!?+#⊙△] ))\((?P<sq>[a-h][1-8])\)"
    r"(?P<check>\+(?![−\-])|#)?(?P<ann>!!|\?\?|!\?|\?!|[!?])?(?![\w\-])"
)
# Notação descritiva inglesa: P-K4, N-KB3, PxP, Q-R5ch, B-QN5.
_DESCRIPTIVE_RE = re.compile(
    r"(?<![\w\-])[KQRBNP](?:\((?:[KQ]?[RBN]?)?\d?\))?(?:-(?:[KQ]?[RBN]?[1-8])|x(?:[KQ]?[RBN]?P|[KQRBN]))(?:ch|\+)?(?![\w\-])"
)


def _move_syntax(m: re.Match[str]) -> MoveSyntax:
    g = m.groupdict()
    common = {
        "check": g["check"] or "",
        "annotation": g["ann"] or "",
        "info": g["info"] or "",
    }
    if g["castle"]:
        castle_text = g["castle"]
        return MoveSyntax(
            piece_char=None, from_file=None, from_rank=None, separator=None, to_square=None,
            promotion_char=None, castle="Q" if castle_text.count("-") == 2 else "K",
            castle_text=castle_text, en_passant=False, **common,
        )
    promo = g["promo"]
    if promo:
        promo = promo.strip("=()/")
    rest = {"promotion_char": promo, "castle": None, "castle_text": None, "en_passant": bool(g["ep"]), **common}
    if g["piece"]:
        return MoveSyntax(piece_char=g["piece"], from_file=g["ff"], from_rank=g["fr"], separator=g["sep"],
                          to_square=g["to"], **rest)
    if g["pto"]:
        return MoveSyntax(piece_char=None, from_file=g["pff"], from_rank=g["pfr"], separator=g["psep"],
                          to_square=g["pto"], **rest)
    if g.get("abff"):
        return MoveSyntax(piece_char=None, from_file=g["abff"], from_rank=None, separator=None,
                          to_square=None, to_file=g["abtf"], **rest)
    return MoveSyntax(piece_char=None, from_file=None, from_rank=None, separator=None, to_square=g["bare"],
                      **rest)


def _valid_abbreviation(m: re.Match[str]) -> bool:
    """Captura abreviada só entre colunas vizinhas ("hg"; nunca "he")."""
    g = m.groupdict()
    if not g.get("abff"):
        return True
    return abs(ord(g["abff"]) - ord(g["abtf"])) == 1


def _raw_atoms(text: str, style: LexStyle) -> list[Atom]:
    found: list[Atom] = []
    taken = [False] * (len(text) + 1)
    move_re, _ = _move_regexes(style)

    def claim(start: int, end: int) -> bool:
        if any(taken[start:end]):
            return False
        for i in range(start, end):
            taken[i] = True
        return True

    for m in _DESCRIPTIVE_RE.finditer(text):
        # "PxP", "P-K4": só existem em notação descritiva. "N-KB3" não é SAN.
        if claim(m.start(), m.end()):
            found.append(Atom(AtomKind.DESCRIPTIVE, m.start(), m.end(), m.group()))
    for m in _RESULT_RE.finditer(text):
        if claim(m.start(), m.end()):
            found.append(Atom(AtomKind.RESULT, m.start(), m.end(), m.group()))
    for m in _NUMBER_RE.finditer(text):
        if claim(m.start(), m.end()):
            found.append(
                Atom(AtomKind.MOVE_NUMBER, m.start(), m.end(), m.group(),
                     number=int(m.group(1)), black=m.group(2) != ".")
            )
    for m in _ALT_DEST_RE.finditer(text):
        if claim(m.start(), m.end()):
            alt = MoveSyntax(
                piece_char=None, from_file=None, from_rank=None, separator=None, to_square=m.group("sq"),
                promotion_char=None, castle=None, castle_text=None, check=m.group("check") or "",
                annotation=m.group("ann") or "", en_passant=False,
            )
            found.append(Atom(AtomKind.ALT_DEST, m.start(), m.end(), m.group(), move=alt))
    for m in _SUSPICIOUS_RE.finditer(text):
        if claim(m.start(), m.end()):
            found.append(Atom(AtomKind.SUSPICIOUS, m.start(), m.end(), m.group()))
    # Lances podem vir logo após "12." ou "...": esses são tratados em
    # _attach_after_number, pois o caractere anterior é um ponto.
    for m in move_re.finditer(text):
        if _valid_abbreviation(m) and claim(m.start(), m.end()):
            found.append(Atom(AtomKind.MOVE, m.start(), m.end(), m.group(), move=_move_syntax(m)))
    if style.numbers_without_dot:
        for m in _NUMBER_NODOT_RE.finditer(text):
            if claim(m.start(), m.end()):
                found.append(Atom(AtomKind.MOVE_NUMBER, m.start(), m.end(), m.group(), number=int(m.group(1))))
    for m in _ELLIPSIS_RE.finditer(text):
        if claim(m.start(), m.end()):
            found.append(Atom(AtomKind.ELLIPSIS, m.start(), m.end(), m.group()))
    for m in _EVAL_RE.finditer(text):
        if claim(m.start(), m.end()):
            found.append(Atom(AtomKind.EVAL, m.start(), m.end(), m.group()))
    found.sort(key=lambda a: a.start)
    return found


def _attach_after_number(text: str, atoms: list[Atom], style: LexStyle) -> list[Atom]:
    """Reconhece lances colados ao número ("1.e4", "12...♘f6", "...d6", "2 ♔e4").

    Um número sem ponto que não seja seguido de lance é descartado: era prosa.
    """
    _, after_number = _move_regexes(style)
    by_start = {a.start: a for a in atoms}
    extra: list[Atom] = []
    dropped: set[int] = set()
    for atom in atoms:
        if atom.kind not in (AtomKind.MOVE_NUMBER, AtomKind.ELLIPSIS):
            continue
        pos = atom.end
        while pos < len(text) and text[pos].isspace():
            pos += 1
        nodot = atom.kind == AtomKind.MOVE_NUMBER and not atom.text.endswith((".", "…"))
        existing = by_start.get(pos)
        if existing is not None:
            if nodot and existing.kind not in (AtomKind.MOVE, AtomKind.ELLIPSIS):
                dropped.add(atom.start)
            continue
        m = after_number.match(text, pos)
        if m and _valid_abbreviation(m):
            extra.append(Atom(AtomKind.MOVE, m.start(), m.end(), m.group(), move=_move_syntax(m)))
        elif nodot:
            dropped.add(atom.start)
    kept = [
        a for a in atoms
        if a.start not in dropped and not any(e.start <= a.start and a.end <= e.end for e in extra)
    ]
    return sorted(kept + extra, key=lambda a: a.start)


def _variation_parens(text: str, atoms: list[Atom]) -> list[Atom]:
    """Marca parênteses de variante e parênteses de prosa que contêm notação.

    "(13.♗xe5 ♖xe5)" é variante: alternativa ao último lance. "(but not 2 ♔f6?
    ...)" é prosa com notação: ao fechar, volta-se à linha anterior ao parêntese.
    Parênteses dentro de um átomo ("♕b5(c2)") são ignorados.
    """
    starts = {a.start: a for a in atoms}
    covered = {i for a in atoms for i in range(a.start, a.end)}
    notation_starts = sorted(a.start for a in atoms if a.kind in (AtomKind.MOVE, AtomKind.MOVE_NUMBER))
    result = list(atoms)
    stack: list[tuple[int, bool]] = []
    for i, ch in enumerate(text):
        if i in covered:
            continue
        if ch == "(":
            j = i + 1
            while j < len(text) and text[j] == " ":
                j += 1
            nxt = starts.get(j)
            is_var = nxt is not None and nxt.kind in (
                AtomKind.MOVE_NUMBER, AtomKind.ELLIPSIS, AtomKind.MOVE
            )
            stack.append((i, is_var))
        elif ch == ")" and stack:
            start, is_var = stack.pop()
            if is_var:
                result.append(Atom(AtomKind.VAR_OPEN, start, start + 1, "("))
                result.append(Atom(AtomKind.VAR_CLOSE, i, i + 1, ")"))
            elif any(start < s < i for s in notation_starts):
                result.append(Atom(AtomKind.PAREN_OPEN, start, start + 1, "("))
                result.append(Atom(AtomKind.PAREN_CLOSE, i, i + 1, ")"))
    for start, is_var in stack:  # sem fechamento: a variante continua aberta
        if is_var:
            result.append(Atom(AtomKind.VAR_OPEN, start, start + 1, "("))
    result.sort(key=lambda a: a.start)
    return result


def _group_spans(text: str, atoms: list[Atom]) -> list[Span]:
    spans: list[Span] = []
    current = Span()
    for atom in atoms:
        if current.atoms:
            gap = text[current.end : atom.start]
            if gap.strip() != "":
                spans.append(current)
                current = Span()
        current.atoms.append(atom)
    if current.atoms:
        spans.append(current)
    return spans


def lex(text: str, style: LexStyle = DEFAULT_STYLE) -> LexResult:
    """Separa a notação da prosa, preservando as posições originais."""
    atoms = _attach_after_number(text, _raw_atoms(text, style), style)
    atoms = _variation_parens(text, atoms)
    spans = _group_spans(text, atoms)

    final_spans: list[Span] = []
    for span in spans:
        has_anchor = any(
            a.kind in (AtomKind.MOVE_NUMBER, AtomKind.ELLIPSIS, AtomKind.SUSPICIOUS)
            or (a.kind == AtomKind.MOVE and a.move and not a.move.is_bare_square and a.move.to_file is None)
            for a in span.atoms
        )
        new_atoms: list[Atom] = []
        prev: Atom | None = None
        for atom in span.atoms:
            if atom.kind == AtomKind.MOVE and atom.move and not has_anchor:
                if atom.move.is_bare_square:
                    atom = Atom(AtomKind.SQUARE_REF, atom.start, atom.end, atom.text)
                elif atom.move.to_file is not None:
                    continue  # "hg" sem número nem lance ao lado não é notação
            if atom.kind == AtomKind.MOVE and prev is not None and prev.kind == AtomKind.ELLIPSIS:
                atom = Atom(atom.kind, atom.start, atom.end, atom.text, move=atom.move, ellipsis_prefix=True)
            new_atoms.append(atom)
            prev = atom
        span.atoms = new_atoms
        # Avaliações e "suspeitos" só significam algo ao lado de lances ou de
        # números de lance ("Capítulo 3." sozinho não é notação).
        kinds = {a.kind for a in span.atoms}
        if not span.has_moves() and not (
            AtomKind.MOVE_NUMBER in kinds and AtomKind.SUSPICIOUS in kinds
        ):
            span.atoms = [
                a for a in span.atoms
                if a.kind in (AtomKind.SQUARE_REF, AtomKind.DESCRIPTIVE, AtomKind.PAREN_OPEN, AtomKind.PAREN_CLOSE)
            ]
            if not span.atoms:
                continue
        final_spans.append(span)
    flat = [a for s in final_spans for a in s.atoms]
    return LexResult(text=text, atoms=flat, spans=final_spans)

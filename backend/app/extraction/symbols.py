"""Símbolos depois da casa do lance, reconhecidos pelo desenho: xeque, avaliação, anotação, promoção.

O Tesseract não conhece "†", "±", "⩲" nem "⩱" e troca um pelo outro (no
*Grandmaster Preparation*, o xeque "†" e a vantagem "±" saíam os dois como "+";
"?!" saía como "2!"; a dama da promoção sumia). Como nas figurinas, o desenho
decide: cada símbolo depois da casa é recortado e comparado com os outros do
mesmo livro; desenhos iguais formam um grupo, e o grupo recebe um símbolo (pela
referência mais parecida e pelo que o Tesseract leu, ou pela confirmação do
usuário na tela "Símbolos do livro"). O fim de cada lance é reescrito com os
símbolos dos seus desenhos; se algum desenho não tem símbolo decidido, fica o
que o OCR leu, com aviso.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# o que um desenho pode ser: símbolo de xeque, mate, anotação ou avaliação, ou a peça da promoção
SYMBOLS = "†+#!?±∓⩲⩱=∞−"
PIECES = "♔♕♖♗♘"
SYMBOL_NAMES = {"†": "xeque (†)", "+": "xeque (+)", "#": "mate", "!": "!", "?": "?", "±": "± brancas melhor",
                "∓": "∓ pretas melhor", "⩲": "⩲ brancas um pouco melhor", "⩱": "⩱ pretas um pouco melhor",
                "=": "= igualdade / promoção", "∞": "∞ pouco claro", "−": "− (de +− e −+)"}
GROUP_SIMILARITY = 0.85
SHAPE_TOLERANCE = 0.25  # diferença de altura e posição (em corpos de letra) dentro de um grupo
REF_FONTS = ("/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
             "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

# o lance até o fim da casa, como o OCR o devolve ("l" e "I" no lugar do 1)
_HEAD_RE = re.compile(r"^(?:\(?\d{1,3}\.{0,3}|\(?\.\.\.)?(?:[♔♕♖♗♘KQRBN]?[a-h]?[1-8]?[x:×]?[a-h][1-8lI]"
                      r"|[O0]-[O0](?:-[O0])?)")
_TAIL = set(".,;:)")


@dataclass
class Glyph:
    vec: np.ndarray  # desenho normalizado (32×32)
    height: float  # em corpos de letra
    top: float  # do alto da linha até o alto do desenho, em corpos de letra
    read: str  # o que o Tesseract leu nesse trecho
    group: int = -1


@dataclass
class Suffix:
    """O fim de um lance: o que vem depois da casa, desenho por desenho."""

    block: int
    line: int
    span: int
    head: str  # o lance até a casa, já corrigido ("c1" de "cl")
    tail: str  # pontuação do fim (".", ",", ")")
    read: str  # o que o OCR leu entre a casa e a pontuação
    glyphs: list[int] = field(default_factory=list)  # índices em ``Page.glyphs``


def _head_fixed(head: str) -> str:
    return head[:-1] + "1" if head[-1:] in "lI" and not head.startswith(("O", "0")) else head


def word_suffix(gray: np.ndarray, line, word, text: str, size_px: float,
                next_x0: int | None = None) -> tuple[str, str, str, list] | None:
    """(lance até a casa, pontuação final, sufixo lido, desenhos) de uma palavra de lance, ou None.

    ``word`` é a palavra do hOCR (caixas por caractere); ``text`` é o texto
    dela depois das figurinas (mesmo comprimento que os caracteres). Tinta logo
    depois da palavra, antes da próxima (``next_x0``), também conta: o Tesseract
    às vezes deixa o símbolo de fora ("♕c4" de "♕c4†").
    """
    from app.extraction.glyph_probe import _normalize

    chars = word.chars
    if not chars or len(chars) != len(text):
        return None
    m = _HEAD_RE.match(text)
    if not m:
        return None
    k = m.end()
    head = text[:k]
    # só lance de verdade: com peça, número ou captura; o lance de peão sozinho ("c4!?") só com sufixo
    # sem letras (senão é palavra: "also" não é "a1" + "so")
    if re.search(r"[a-z]{2}", text[k:]):
        return None
    if not (re.search(r"[♔♕♖♗♘KQRBN]|\d\.|x|\.\.\.", head) or re.fullmatch(r"[!?†+#=±∓⩲⩱∞2t()\]}\-—–.,;:]+",
                                                                         text[k:])):
        return None
    end = len(text)
    while end > k and text[end - 1] in _TAIL:
        end -= 1
    size = max(1.0, size_px)
    # do começo do algarismo da casa: o primeiro trecho de tinta é ele e sai (a caixa do Tesseract às
    # vezes acaba antes da tinta do algarismo, e a sobra parecia um símbolo)
    x0 = chars[k - 1].bbox[0]
    if end < len(text):  # a pontuação do fim, pela caixa do Tesseract
        x1 = chars[end].bbox[0]
    else:  # até o fim da palavra e, colada nela, a tinta que o Tesseract não leu
        x1 = word.bbox[2] + 1
        limit = min(next_x0 - 1 if next_x0 is not None else gray.shape[1], word.bbox[2] + int(1.2 * size))
        y0, y1 = line.bbox[1], line.bbox[3]
        col = x1
        while col < limit and (gray[y0:y1, col] < 128).any():
            col += 1
        gap = col
        while gap < limit and gap - col < int(0.15 * size) and not (gray[y0:y1, gap] < 128).any():
            gap += 1
        if gap - col < int(0.15 * size) and gap < limit:  # outro desenho logo adiante (o símbolo solto)
            col = gap
            while col < limit and (gray[y0:y1, col] < 128).any():
                col += 1
        x1 = max(x1, col)
    y0, y1 = line.bbox[1], line.bbox[3]
    if x1 - x0 < 2:
        return None
    crop = gray[y0:y1, x0:x1]
    ink = crop < 128
    cols = np.flatnonzero(ink.any(axis=0))
    if cols.size == 0:
        return None
    glyphs = []
    start = prev = cols[0]
    runs = []
    for c in cols[1:]:
        if c > prev + 1:
            runs.append((start, prev))
            start = c
        prev = c
    runs.append((start, prev))
    runs = runs[1:]  # o algarismo da casa
    for a, b in runs:
        piece = crop[:, a:b + 1]
        rows = np.flatnonzero((piece < 128).any(axis=1))
        if rows.size == 0 or (b - a + 1) * rows.size < 4:  # sujeira
            continue
        vec = _normalize(piece[rows[0]:rows[-1] + 1])
        if vec is None:
            continue
        read = "".join(c.text for c in chars[k:end] if c.bbox[0] <= x0 + b and c.bbox[2] >= x0 + a)
        glyphs.append(Glyph(vec, (rows[-1] - rows[0] + 1) / size, rows[0] / size, read))
    # a caixa do Tesseract às vezes vem deslocada de um caractere: o algarismo da casa entra no recorte
    while glyphs and _looks_like_digit(glyphs[0].vec):
        glyphs.pop(0)
    if not glyphs:
        return None
    return _head_fixed(text[:k]), text[end:], text[k:end], glyphs


def _looks_like_digit(vec: np.ndarray) -> bool:
    digit = max((_sim(vec, r) for ch, r in _references(DIGITS)), default=0.0)
    symbol = max((_sim(vec, r) for ch, r in _references()), default=0.0)
    return digit >= 0.6 and digit > symbol + 0.05


# --- grupos ------------------------------------------------------------------------
@dataclass
class SymbolGroup:
    id: int
    count: int
    vec: np.ndarray
    height: float
    top: float
    read: list[str]  # o que o Tesseract mais leu
    auto: str  # sugestão
    score: float
    margin: float


def group_glyphs(glyphs: list[Glyph], figurines=None) -> list[SymbolGroup]:
    """Agrupa os desenhos iguais do livro; cada grupo recebe uma sugestão."""
    clusters: list[dict] = []
    for g in glyphs:
        for i, cl in enumerate(clusters):
            if (abs(cl["h"] - g.height) <= SHAPE_TOLERANCE and abs(cl["t"] - g.top) <= SHAPE_TOLERANCE
                    and _sim(cl["rep"], g.vec) >= GROUP_SIMILARITY):
                n = len(cl["members"])
                cl["members"].append(g)
                cl["sum"] += g.vec
                cl["rep"] = cl["sum"] / (n + 1)
                cl["h"] = (cl["h"] * n + g.height) / (n + 1)
                cl["t"] = (cl["t"] * n + g.top) / (n + 1)
                g.group = i
                break
        else:
            g.group = len(clusters)
            clusters.append({"rep": g.vec.copy(), "sum": g.vec.copy(), "members": [g], "h": g.height, "t": g.top})
    out = []
    for i, cl in enumerate(clusters):
        read = [r for r, _ in Counter(m.read for m in cl["members"]).most_common(3)]
        auto, score, margin = suggest(cl["rep"], cl["h"], read, figurines)
        out.append(SymbolGroup(i, len(cl["members"]), cl["rep"], round(cl["h"], 3), round(cl["t"], 3), read, auto,
                               round(score, 3), round(margin, 3)))
    return out


def _sim(a: np.ndarray, b: np.ndarray) -> float:
    from app.extraction.glyph_probe import _similarity

    return _similarity(a, b)


DIGITS = "12345678"
_refs_cache: dict[str, list[tuple[str, np.ndarray]]] = {}


def _references(chars: str = SYMBOLS) -> list[tuple[str, np.ndarray]]:
    """Desenhos de referência (FreeSerif tem ⩲ e ⩱)."""
    if chars not in _refs_cache:
        from app.extraction.glyph_probe import _render_text

        out = []
        for font in REF_FONTS:
            if not Path(font).exists():
                continue
            for ch in chars:
                vec = _render_text(ch, fontfile=font)
                if vec is not None:
                    out.append((ch, vec))
        _refs_cache[chars] = out
    return _refs_cache[chars]


# o que o Tesseract costuma ler no lugar de cada símbolo, quando a leitura confirma a referência
_READ_HINTS = {"−": {"-", "—", "–", "−"}, "†": {"†", "t", "+", "¢", "1", "}"}, "+": {"+"}, "#": {"#"}, "!": {"!", "l", "1", "I"},
               "?": {"?", "2"}, "±": {"±", "+"}, "∓": {"∓", "F"}, "⩲": {"+", "F", "£"}, "⩱": {"F", "="},
               "=": {"="}, "∞": {"∞", "oo", "co", "~"}}


def suggest(vec: np.ndarray, height: float, read: list[str], figurines=None) -> tuple[str, float, float]:
    """(símbolo, nota, margem) mais provável: a peça da promoção pelos protótipos do livro; o resto
    pelas referências. Sem nota e margem suficientes, ou contra a leitura do OCR, não sugere nada."""
    if figurines and height >= 0.75:
        from app.extraction.ocr import match_prototype

        char, score, margin = match_prototype(vec, figurines)
        if score >= 0.75 and margin >= 0.05:
            return char, score, margin
    scored: dict[str, float] = {}
    for ch, ref in _references():
        scored[ch] = max(scored.get(ch, -1.0), _sim(vec, ref))
    ranked = sorted(scored.items(), key=lambda kv: -kv[1])
    if not ranked:
        return "", 0.0, 0.0
    (best, score), runner = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0.0)
    agrees = any(r and set(r) <= _READ_HINTS.get(best, set()) | {best} for r in read[:1])
    # sem confirmação, só o que é claro pelo desenho e não contradiz o OCR, ou o que os dois dizem
    if (score >= 0.75 and score - runner >= 0.1 and (agrees or not read or not read[0])) or (score >= 0.6 and agrees):
        return best, score, score - runner
    return "", score, score - runner


VALID_LABEL = re.compile(f"^[{re.escape(SYMBOLS + PIECES)}]*$")


# --- livro inteiro: grupos guardados no ocr.json, decisões do usuário em ocr-simbolos.json ---------
def _vec_b64(vec: np.ndarray) -> str:
    import base64

    return base64.b64encode(np.clip(vec * 255, 0, 255).astype(np.uint8).tobytes()).decode()


def _vec_from_b64(text: str) -> np.ndarray:
    import base64

    raw = base64.b64decode(text)
    side = round(len(raw) ** 0.5)
    return np.frombuffer(raw, dtype=np.uint8).astype(np.float32).reshape(side, side) / 255


def group_json(g: SymbolGroup) -> dict:
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray((255 - g.vec * 255).clip(0, 255).astype(np.uint8)).resize((64, 64)).save(buf, "PNG")
    return {"id": g.id, "count": g.count, "auto": g.auto, "score": g.score, "margin": g.margin, "read": g.read,
            "height": g.height, "top": g.top, "vec": _vec_b64(g.vec),
            "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}


def inherit(groups: list[dict], confirmed: list[dict]) -> dict[str, str]:
    """Os grupos novos (OCR refeito) herdam a decisão do usuário pelo desenho."""
    out: dict[str, str] = {}
    items = [(c, _vec_from_b64(c["vec"])) for c in confirmed]
    for g in groups:
        vec = _vec_from_b64(g["vec"])
        best = max(((_sim(vec, v), c) for c, v in items
                    if abs(c["height"] - g["height"]) <= SHAPE_TOLERANCE and abs(c["top"] - g["top"]) <= SHAPE_TOLERANCE),
                   default=(0.0, None), key=lambda t: t[0])
        if best[1] is not None and best[0] >= GROUP_SIMILARITY:
            out[str(g["id"])] = best[1]["label"]
    return out


def resolved(groups: list[dict], confirmed: dict[str, str]) -> dict[str, str]:
    """Símbolo de cada grupo: o confirmado; senão, a sugestão, quando há."""
    out = {str(g["id"]): g["auto"] for g in groups if g["auto"]}
    out.update(confirmed)
    return out


_STALE = ("ocr_lance_incompleto", "ocr_lance_ilegivel", "ocr_corrigido", "ocr_simbolo_incerto")


def apply_to_pages(pages: dict, labels: dict[str, str]) -> dict[str, int]:
    """Reescreve o fim de cada lance com os símbolos dos desenhos (no formato do ``ocr.json``).

    Idempotente: parte sempre do que o OCR leu (``head + read + tail``). Avisos
    sobre o lance como o OCR o leu saem quando os símbolos foram decididos.
    """
    done = uncertain = 0
    for page in pages.values():
        cleaned: set[int] = set()
        for b, ln, sp, head, tail, read, gids in page.get("suffixes", []):
            block = page["blocks"][b]
            span = block["lines"][ln]["spans"][sp]
            original = head + read + tail
            chosen = [labels.get(str(g)) for g in gids]
            ok = all(c is not None for c in chosen)
            text = head + "".join(chosen) + tail if ok else original
            span["text"] = text + (" " if span["text"].endswith(" ") else "")
            warnings = block.setdefault("ocr_warnings", [])
            if b not in cleaned:
                block["ocr_warnings"] = warnings = [w for w in warnings if not w.startswith("ocr_simbolo_incerto")]
                cleaned.add(b)
            if ok:
                done += 1
                if text != original:
                    block["ocr_warnings"] = [w for w in warnings
                                             if not (w.startswith(_STALE) and f"'{original}'" in w)]
            else:
                uncertain += 1
                warnings.append(f"ocr_simbolo_incerto: '{text}'")
    return {"moves": done, "uncertain": uncertain}


def page_entries(suffixes: list[Suffix], glyphs: list[Glyph]) -> list[list]:
    return [[s.block, s.line, s.span, s.head, s.tail, s.read, [glyphs[i].group for i in s.glyphs]] for s in suffixes]

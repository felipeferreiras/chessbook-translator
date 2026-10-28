"""Posições dos diagramas digitalizados: as peças de cada casa, reconhecidas pelo desenho.

As casas escuras são hachuradas com traços tão escuros quanto as peças, então
o recorte da casa não basta. O contorno da peça sai assim: o miolo de uma peça
branca é branco e fechado pelo contorno (os vãos entre os traços da hachura
chegam todos à borda da casa, o miolo não); uma peça preta é um corpo preto
cheio, que sobrevive a uma erosão que apaga os traços finos. Os contornos do
livro inteiro são agrupados (o mesmo desenho, a mesma peça); cada grupo recebe
uma peça pela referência mais parecida ou pela confirmação do usuário, e um
grupo pequeno herda a peça do grupo confirmado mais parecido. Casa sem peça
decidida deixa a posição incompleta, para revisão: nada é presumido.
"""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass

import numpy as np
import pymupdf
from PIL import Image

SIZE = 24  # lado do contorno normalizado
EMPTY_AREA = 0.04  # menos que isso do quadrado preenchido: casa vazia
GROUP_SIMILARITY = 0.85
NEAREST_SIMILARITY = 0.80  # grupo pequeno herda a peça do grupo decidido mais parecido
SMALL_GROUP = 5
PIECE_CHARS = "KQRBNPkqrbnp"  # FEN
FIGURINE = dict(zip(PIECE_CHARS, "♔♕♖♗♘♙♚♛♜♝♞♟", strict=True))
REF_FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
             "/usr/share/fonts/truetype/freefont/FreeSans.ttf")


def _grow(m: np.ndarray) -> np.ndarray:
    o = m.copy()
    o[:, 1:] |= m[:, :-1]
    o[:, :-1] |= m[:, 1:]
    o[:, :, 1:] |= m[:, :, :-1]
    o[:, :, :-1] |= m[:, :, 1:]
    return o


def _shrink(m: np.ndarray) -> np.ndarray:
    o = m.copy()
    o[:, 1:] &= m[:, :-1]
    o[:, :-1] &= m[:, 1:]
    o[:, :, 1:] &= m[:, :, :-1]
    o[:, :, :-1] &= m[:, :, 1:]
    o[:, 0] = o[:, -1] = False
    o[:, :, 0] = o[:, :, -1] = False
    return o


def board_cells(gray: np.ndarray, board: tuple[float, float, float, float], scale: float) -> np.ndarray:
    """As 64 casas (a8, b8, …, h1), quadradas, sem a moldura."""
    x0, y0, x1, y1 = (round(v * scale) for v in board)
    img = gray[max(0, y0):y1, max(0, x0):x1]
    h, w = img.shape
    # só a moldura sai (as linhas escuras da borda): uma margem fixa maior encolhia o tabuleiro e as
    # casas de baixo saíam deslocadas, com a base das peças cortada (o cavalo aberto embaixo sumia)
    top, bottom = _frame(img < 128, 1), _frame((img < 128)[::-1], 1)
    left, right = _frame(img < 128, 0), _frame((img < 128)[:, ::-1], 0)
    inner = img[top:h - bottom, left:w - right]
    ih, iw = inner.shape
    s = min(ih // 8, iw // 8)
    pad = max(1, s // 40)  # um fio da casa vizinha ou da moldura não entra
    return np.stack([inner[r * ih // 8 + pad:r * ih // 8 + s - pad, c * iw // 8 + pad:c * iw // 8 + s - pad]
                     for r in range(8) for c in range(8)])


def _frame(ink: np.ndarray, axis: int) -> int:
    """Espessura da moldura do lado de ``ink[0]`` (linhas, ``axis=1``) ou de ``ink[:, 0]`` (colunas)."""
    fill = ink.mean(axis=axis)
    limit = max(2, len(fill) // 25)
    # a linha da moldura pode estar uns pixels para dentro (digitalização torta) ou já fora do recorte
    hits = [i for i in range(limit) if fill[i] > 0.5]
    if not hits:
        return 0
    n = hits[0]
    while n < limit and fill[n] > 0.5:
        n += 1
    while n < limit and fill[n] > 0.2:  # a borda borrada da linha
        n += 1
    return n


def silhouettes(cells: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(miolo branco fechado, corpo preto) de cada casa."""
    ink = cells < 128
    white = ~ink
    reach = np.zeros_like(white)  # o branco que chega à borda da casa (fundo e vãos da hachura)
    reach[:, 0, :], reach[:, -1, :] = white[:, 0, :], white[:, -1, :]
    reach[:, :, 0], reach[:, :, -1] = white[:, :, 0], white[:, :, -1]
    while True:
        new = _grow(reach) & white
        if (new == reach).all():
            break
        reach = new
    solid = _shrink(_shrink(ink))
    solid = _grow(_grow(solid)) & ink
    return white & ~reach, solid


def _normalize(mask: np.ndarray, ink: np.ndarray | None = None) -> np.ndarray:
    """O contorno centrado num quadrado de ``SIZE``: parte branca da peça 0, fora ½, parte preta 1.

    Os três níveis guardam forma e cor juntas, em lados opostos do fundo (a correlação não vê
    escala: com branco ½ e preto 1, o peão branco e o preto ficavam iguais). A dama branca listrada
    e a dama preta têm o mesmo contorno, mas não a mesma imagem.
    """
    ys, xs = np.nonzero(mask)
    sl = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    if ink is None:
        level = mask[sl].astype(np.float32)
        background = 0
    else:
        level = np.where(mask[sl], np.where(ink[sl], 1.0, 0.0), 0.5).astype(np.float32)
        background = 127
    h, w = level.shape
    side = max(h, w)
    canvas = np.full((side, side), background, np.uint8)
    canvas[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = (level * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(canvas).resize((SIZE, SIZE), Image.Resampling.BILINEAR), np.float32) / 255


@dataclass
class Shape:
    """O contorno da peça de uma casa."""

    vec: np.ndarray
    black: bool
    sample: np.ndarray  # recorte da casa (para mostrar o grupo)
    group: int = -1


def board_shapes(cells: np.ndarray) -> list[Shape | None]:
    """Contorno de cada casa; None na casa vazia."""
    interior, solid = silhouettes(cells)
    sil = interior | solid
    core = sil
    for _ in range(3):
        core = _shrink(core)
    ink = cells < 128
    out: list[Shape | None] = []
    for i in range(64):
        if sil[i].mean() < EMPTY_AREA:
            out.append(None)
            continue
        # Cor por duas medidas, porque cada uma falha num desenho: o miolo da peça (contorno encolhido) é
        # escuro na preta (medido: 0,76 ou mais), mas também na dama branca listrada do livro (0,81–0,90);
        # o miolo branco fechado é menos da metade do contorno na preta (até 0,43, rei com detalhes
        # brancos), mas também no peão branco de base grossa da DejaVu. A preta passa nas duas.
        dark = (ink[i] & core[i]).sum() / max(1, core[i].sum())
        black = dark >= 0.6 and interior[i].sum() < 0.5 * sil[i].sum()
        out.append(Shape(_normalize(sil[i], ink[i]), bool(black), cells[i]))
    return out


def side_to_move(gray: np.ndarray, board: tuple[float, float, float, float], scale: float) -> str | None:
    """Vez de jogar pela marca ao lado do tabuleiro: ▼ cheio = pretas, △ vazado = brancas."""
    x0, y0, x1, y1 = (v * scale for v in board)
    w, h = x1 - x0, y1 - y0
    area = gray[int(y1 - 0.2 * h):int(y1 + 0.03 * h), int(x1 + 0.01 * w):int(x1 + 0.15 * w)]
    if area.size == 0:
        return None
    ink = area < 128
    rows, cols = np.flatnonzero(ink.any(axis=1)), np.flatnonzero(ink.any(axis=0))
    if rows.size < 0.03 * h or cols.size < 0.03 * w:
        return None
    blob = ink[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    if not 0.6 <= blob.shape[0] / max(1, blob.shape[1]) <= 1.5:
        return None
    fill = blob.mean()
    return "b" if fill > 0.4 else "w" if fill < 0.3 else None


# --- grupos -----------------------------------------------------------------------
@dataclass
class PieceGroup:
    id: int
    count: int
    vec: np.ndarray
    black: bool
    sample: np.ndarray
    auto: str  # letra FEN sugerida ("" sem sugestão)
    score: float
    margin: float


def _norm(v: np.ndarray) -> np.ndarray:
    v = v - v.mean(axis=-1, keepdims=True)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6)


def group_shapes(shapes: list[Shape]) -> list[PieceGroup]:
    reps: list[np.ndarray] = []
    sums: list[np.ndarray] = []
    members: list[list[Shape]] = []
    for s in shapes:
        flat = s.vec.ravel()
        if reps:
            sims = np.stack(reps) @ _norm(flat)
            j = int(np.argmax(sims))
            if sims[j] >= GROUP_SIMILARITY:
                members[j].append(s)
                sums[j] += flat
                reps[j] = _norm(sums[j] / len(members[j]))
                s.group = j
                continue
        s.group = len(reps)
        reps.append(_norm(flat))
        sums.append(flat.copy())
        members.append([s])
    out = []
    for j, ms in enumerate(members):
        vec = (sums[j] / len(ms)).reshape(SIZE, SIZE)
        black = sum(m.black for m in ms) * 2 > len(ms)  # a cor da maioria
        auto, score, margin = suggest(vec, black)
        out.append(PieceGroup(j, len(ms), vec, black, ms[0].sample, auto, round(score, 3), round(margin, 3)))
    return out


_refs: list[tuple[str, np.ndarray]] | None = None


def _references() -> list[tuple[str, np.ndarray]]:
    """Contornos das figurinas das fontes instaladas, tirados do mesmo jeito que os do livro."""
    global _refs
    if _refs is None:
        from pathlib import Path

        _refs = []
        for font in REF_FONTS:
            if not Path(font).exists():
                continue
            for fen, glyph in FIGURINE.items():
                doc = pymupdf.open()
                page = doc.new_page(width=80, height=80)
                page.insert_font(fontname="f", fontfile=font)
                page.insert_text((8, 64), glyph, fontsize=60, fontname="f")
                pix = page.get_pixmap(dpi=90, colorspace=pymupdf.csGRAY)
                gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w)
                interior, solid = silhouettes(gray[None])
                sil = interior[0] | solid[0]
                if sil.any():
                    _refs.append((fen, _norm(_normalize(sil, gray < 128).ravel())))
    return _refs


def suggest(vec: np.ndarray, black: bool) -> tuple[str, float, float]:
    """Peça mais parecida entre as referências da mesma cor; só com nota e margem altas."""
    flat = _norm(vec.ravel())
    scored: dict[str, float] = {}
    for fen, ref in _references():
        if fen.islower() == black:
            scored[fen] = max(scored.get(fen, -1.0), float(ref @ flat))
    ranked = sorted(scored.items(), key=lambda kv: -kv[1])
    if not ranked:
        return "", 0.0, 0.0
    (best, score), runner = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0.0)
    if score >= 0.85 and score - runner >= 0.1:
        return best, score, score - runner
    return "", score, score - runner


def _png(img: np.ndarray, size: int = 48) -> str:
    buf = io.BytesIO()
    Image.fromarray(img).resize((size, size)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def group_json(g: PieceGroup) -> dict:
    return {"id": g.id, "count": g.count, "black": g.black, "auto": g.auto, "score": g.score, "margin": g.margin,
            "vec": base64.b64encode((g.vec * 255).clip(0, 255).astype(np.uint8).tobytes()).decode(),
            "image": _png(g.sample)}


def _vec(g: dict) -> np.ndarray:
    return np.frombuffer(base64.b64decode(g["vec"]), np.uint8).astype(np.float32) / 255


def inherit(groups: list[dict], confirmed: list[dict]) -> dict[str, str]:
    """Os grupos novos (OCR refeito) herdam a peça confirmada pelo desenho."""
    out: dict[str, str] = {}
    items = [(c, _norm(_vec(c))) for c in confirmed]
    for g in groups:
        v = _norm(_vec(g))
        best = max(((float(r @ v), c) for c, r in items), default=(0.0, None),
                   key=lambda t: t[0])
        if best[1] is not None and best[0] >= GROUP_SIMILARITY:
            out[str(g["id"])] = best[1]["label"]
    return out


def resolved(groups: list[dict], confirmed: dict[str, str]) -> dict[str, str]:
    """Peça de cada grupo: a confirmada; senão a sugestão; um grupo pequeno sem nenhuma das duas
    herda a do grupo decidido mais parecido (da mesma cor)."""
    out = {str(g["id"]): g["auto"] for g in groups if g["auto"]}
    out.update(confirmed)
    decided = [(g, _norm(_vec(g))) for g in groups if out.get(str(g["id"]))]
    for g in groups:
        gid = str(g["id"])
        if gid in out or g["count"] > SMALL_GROUP:
            continue
        v = _norm(_vec(g))
        best = max(((float(r @ v), d) for d, r in decided), default=(0.0, None),
                   key=lambda t: t[0])
        if best[1] is not None and best[0] >= NEAREST_SIMILARITY:
            out[gid] = out[str(best[1]["id"])]
    return out


FEN_RE = re.compile(r"^[KQRBNPkqrbnp1-8]+(/[KQRBNPkqrbnp1-8]+){7}$")


def placement(squares: list[int], labels: dict[str, str]) -> tuple[str | None, list[str]]:
    """Campo de posição da FEN a partir das casas (grupo ou -1 vazia), com os problemas achados."""
    rows, unknown = [], []
    for r in range(8):
        row, empty = "", 0
        for c in range(8):
            g = squares[r * 8 + c]
            piece = "" if g < 0 else labels.get(str(g), "?")
            if piece == "":
                empty += 1
                continue
            if piece == "?":
                unknown.append("abcdefgh"[c] + str(8 - r))
            row += (str(empty) if empty else "") + piece
            empty = 0
        rows.append(row + (str(empty) if empty else ""))
    if unknown:
        return None, [f"peça não reconhecida em {', '.join(unknown)}: confirme as peças dos diagramas"]
    fen = "/".join(rows)
    return fen, check_placement(fen)


def check_placement(fen: str) -> list[str]:
    """Problemas que tornam a posição impossível (leitura errada ou diagrama incompleto)."""
    if not FEN_RE.match(fen):
        return ["posição mal formada"]
    issues = []
    board = "".join(ch for ch in fen if ch.isalpha() or ch == "/")
    if fen.count("K") != 1 or fen.count("k") != 1:
        issues.append(f"reis: {fen.count('K')} branco(s), {fen.count('k')} preto(s)")
    first, last = fen.split("/")[0], fen.split("/")[-1]
    if any(ch in "Pp" for ch in first + last):
        issues.append("peão na primeira ou na última fileira")
    for color, chars in (("brancas", "KQRBNP"), ("pretas", "kqrbnp")):
        if sum(board.count(c) for c in chars) > 16 or board.count(chars[-1]) > 8:
            issues.append(f"peças demais das {color}")
    rows = fen.split("/")
    if any(sum(int(ch) if ch.isdigit() else 1 for ch in row) != 8 for row in rows):
        issues.append("fileira com mais ou menos de 8 casas")
    return issues


# --- livro inteiro --------------------------------------------------------------------
def page_entries(diagrams: list[tuple[list[Shape | None], str | None]],
                 boards: list) -> list[dict]:
    return [{"board": list(b), "squares": [-1 if sh is None else sh.group for sh in shapes], "side": side}
            for b, (shapes, side) in zip(boards, diagrams, strict=True)]


def apply_to_pages(pages: dict, labels: dict[str, str], overrides: dict[str, dict]) -> dict[str, int]:
    """Posição de cada diagrama (``placement``, ``side``, ``issues``, ``confirmed``), no formato do ``ocr.json``.

    ``overrides`` (do usuário, por diagrama "página-índice"): posição e vez de jogar corrigidas ou
    confirmadas. Idempotente: parte sempre das casas lidas.
    """
    stats = {"diagrams": 0, "complete": 0, "confirmed": 0}
    for p, page in pages.items():
        for i, d in enumerate(page.get("diagrams", [])):
            stats["diagrams"] += 1
            fen, issues = placement(d["squares"], labels)
            side = d["side"]
            o = overrides.get(f"{p}-{i}")
            d["read"] = fen
            if o:
                fen, side = o.get("placement") or fen, o.get("side") or side
                issues = check_placement(fen) if fen else issues
            if side is None and not issues:
                issues = ["vez de jogar não identificada (▼ ou △ ao lado do tabuleiro)"]
            d.update(placement=fen, side_to_move=side, issues=issues, confirmed=bool(o and o.get("confirmed")))
            stats["complete"] += fen is not None and not issues
            stats["confirmed"] += d["confirmed"]
    return stats

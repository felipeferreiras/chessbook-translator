"""OCR de páginas digitalizadas, com figurinas reconhecidas pela imagem.

Uma página sem texto utilizável (só imagem) passa pelo Tesseract (hOCR com a
caixa de cada caractere). O resultado vira blocos no mesmo formato de
``page.get_text("dict")``, para seguir o caminho das páginas digitais.

O Tesseract não conhece figurinas: lê ``♔e6`` como ``@e6``, ``8e6`` ou até
``Be6`` (uma letra válida, de outra peça). Por isso a peça de todo lance é
decidida pela **imagem**, nunca pelo caractere lido: o glifo é recortado da
página e comparado com desenhos de figurinas e de letras das fontes livres
instaladas (``glyph_probe``). Glifos iguais no livro inteiro recebem a mesma
peça (agrupamento por semelhança), o que corrige leituras isoladas.

Nada é presumido: palavra de baixa confiança, figurina sem margem segura ou
lance que não fecha com o padrão de notação geram um aviso no bloco, e o
segmento pede conferência com a imagem antes da aprovação.

Diagramas: o tabuleiro é achado pela moldura (linhas longas que fecham um
quadrado); o texto que o OCR inventa dentro dele é descartado e a área fica
protegida na montagem. A posição não é lida (fica sem FEN).
"""

from __future__ import annotations

import html.parser
import os
import re
import subprocess
from dataclasses import dataclass, field

import numpy as np
import pymupdf

from app.extraction.glyph_probe import FIGURINE_REFS, _normalize

OCR_DPI = 300
OCR_FONT = "OCR-Tesseract"  # nome de fonte dos blocos lidos por OCR (ver ``font_profiles``)
MIN_WORD_CONF = 60  # abaixo disso a palavra pede conferência
FIGURINE_MIN_SCORE = 0.55
FIGURINE_MIN_MARGIN = 0.04
WHITE_FIGURINES = "♔♕♖♗♘"
# Lance com peça: [número][peça][desambiguação][captura]casa[promoção][sinais]. A "peça" é qualquer
# caractere que não seja coluna, dígito ou espaço: o Tesseract troca figurinas por símbolos e letras.
MOVE_RE = re.compile(
    r"^(?P<num>\d{1,3}\s?\.{0,3}\s?(?:\.\.\.)?)?(?P<piece>[^\sa-h0-9()\[\],;:.!?+#=\-–—])"
    r"(?P<rest>[a-h]?[1-8]?[x:×]?[a-h][1-8](?:=?[QRBN♕♖♗♘])?[+#‡†]?[!?]{0,2}[,;.)]?)$")


@dataclass
class OcrChar:
    text: str
    bbox: tuple[int, int, int, int]  # pixels na imagem do OCR
    conf: float


@dataclass
class OcrWord:
    text: str
    bbox: tuple[int, int, int, int]
    conf: float
    chars: list[OcrChar] = field(default_factory=list)


@dataclass
class OcrLine:
    bbox: tuple[int, int, int, int]
    size_px: float  # tamanho da fonte estimado pelo Tesseract (x_size)
    words: list[OcrWord] = field(default_factory=list)


@dataclass
class OcrBlock:
    bbox: tuple[int, int, int, int]
    lines: list[OcrLine] = field(default_factory=list)


def _title(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    title = dict(attrs).get("title") or ""
    out = {}
    for part in title.split(";"):
        key, _, value = part.strip().partition(" ")
        if key:
            out[key] = value
    return out


def _bbox(value: str) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = (int(v) for v in value.split()[:4])
    return x0, y0, x1, y1


class _HocrParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[OcrBlock] = []
        self._stack: list[str] = []
        self._char: OcrChar | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = dict(attrs).get("class") or ""
        self._stack.append(cls)
        t = _title(attrs)
        if cls == "ocr_par":
            self.blocks.append(OcrBlock(_bbox(t["bbox"])))
        elif cls in ("ocr_line", "ocr_caption", "ocr_textfloat", "ocr_header") and self.blocks:
            self.blocks[-1].lines.append(OcrLine(_bbox(t["bbox"]), float(t.get("x_size", "0") or 0)))
        elif cls == "ocrx_word" and self.blocks and self.blocks[-1].lines:
            self.blocks[-1].lines[-1].words.append(OcrWord("", _bbox(t["bbox"]), float(t.get("x_wconf", "0"))))
        elif cls == "ocrx_cinfo" and self.blocks and self.blocks[-1].lines and self.blocks[-1].lines[-1].words:
            self._char = OcrChar("", _bbox(t["x_bboxes"]), float(t.get("x_conf", "0")))

    def handle_endtag(self, tag: str) -> None:
        cls = self._stack.pop() if self._stack else ""
        if cls == "ocrx_cinfo" and self._char is not None:
            word = self.blocks[-1].lines[-1].words[-1]
            word.chars.append(self._char)
            word.text += self._char.text
            self._char = None

    def handle_data(self, data: str) -> None:
        if self._char is not None:
            self._char.text += data


def parse_hocr(text: str) -> list[OcrBlock]:
    parser = _HocrParser()
    parser.feed(text)
    for block in parser.blocks:
        for line in block.lines:
            line.words = [w for w in line.words if w.text.strip()]
        block.lines = [ln for ln in block.lines if ln.words]
    return [b for b in parser.blocks if b.lines]


def run_tesseract(png: bytes, lang: str = "eng", dpi: int = OCR_DPI, timeout: float = 300) -> str:
    """hOCR da imagem. Uma thread só: com várias, o Tesseract disputa a CPU e fica dezenas de vezes mais lento."""
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    proc = subprocess.run(["tesseract", "stdin", "stdout", "-l", lang, "--dpi", str(dpi), "-c", "hocr_char_boxes=1",
                           "hocr"], input=png, capture_output=True, timeout=timeout, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract falhou: {proc.stderr.decode(errors='replace')[-500:]}")
    return proc.stdout.decode("utf-8")


def needs_ocr(page: pymupdf.Page) -> bool:
    """Página sem texto utilizável mas com imagem cobrindo boa parte dela (digitalizada)."""
    if len(page.get_text("text").strip()) >= 20:
        return False
    area = abs(page.rect)
    covered = sum(abs(pymupdf.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    return area > 0 and covered / area > 0.3


# --- diagramas ----------------------------------------------------------------------
def _runs(mask: np.ndarray, min_len: int) -> list[tuple[int, int, int]]:
    """(linha, início, fim) das sequências de tinta com pelo menos ``min_len`` pixels em cada linha."""
    out = []
    padded = np.pad(mask.astype(np.int8), ((0, 0), (1, 1)))
    diff = np.diff(padded, axis=1)
    for row in np.where((diff != 0).any(axis=1))[0]:
        starts = np.where(diff[row] == 1)[0]
        ends = np.where(diff[row] == -1)[0]
        out.extend((int(row), int(s), int(e)) for s, e in zip(starts, ends, strict=True) if e - s >= min_len)
    return out


def _segments(runs: list[tuple[int, int, int]], tol: int = 6) -> list[tuple[int, int, int, int]]:
    """Junta sequências de linhas vizinhas com as mesmas pontas: (início, fim, linha0, linha1)."""
    segs: list[list[int]] = []
    for row, s, e in sorted(runs):
        for seg in segs:
            if row - seg[3] <= 2 and abs(seg[0] - s) <= tol and abs(seg[1] - e) <= tol:
                seg[3] = row
                break
        else:
            segs.append([s, e, row, row])
    return [tuple(x) for x in segs]  # type: ignore[misc]


def detect_boards(gray: np.ndarray, px_per_pt: float, min_side_pt: float = 90) -> list[tuple[float, float, float, float]]:
    """Tabuleiros pela moldura: dois traços horizontais e dois verticais longos que fecham um quadrado.

    Linhas de texto não formam traços contínuos (há espaço entre as letras), e
    fios de tabela raramente fecham um quadrado com ~8 casas alternadas dentro.
    Devolve retângulos em pontos da página.
    """
    ink = gray < 128
    min_len = int(min_side_pt * px_per_pt)
    horiz = _segments(_runs(ink, min_len))
    vert = _segments(_runs(ink.T, min_len))  # na transposta: (y0, y1, coluna0, coluna1)
    boards = []
    for i, (x0, x1, ya, _) in enumerate(horiz):
        for xb0, xb1, yb, _yb1 in horiz[i + 1:]:
            if abs(xb0 - x0) > 8 or abs(xb1 - x1) > 8:
                continue
            side_w, side_h = x1 - x0, yb - ya
            if not 0.85 <= side_h / max(1, side_w) <= 1.15:
                continue
            # traços verticais ligando as duas pontas (as colunas x0 e x1)
            if not any(abs(c0 - x0) <= 8 and v0 <= ya + 8 and v1 >= yb - 8 for v0, v1, c0, _c1 in vert):
                continue
            if not any(abs(c1 - x1) <= 8 and v0 <= ya + 8 and v1 >= yb - 8 for v0, v1, _c0, c1 in vert):
                continue
            if not _checkered(gray[ya:yb, x0:x1]):
                continue
            rect = (x0 / px_per_pt, ya / px_per_pt, x1 / px_per_pt, yb / px_per_pt)
            if not any(_contains(b, rect) or _contains(rect, b) for b in boards):
                boards.append(rect)
    return boards


def _contains(a: tuple, b: tuple) -> bool:
    return a[0] <= b[0] + 2 and a[1] <= b[1] + 2 and a[2] >= b[2] - 2 and a[3] >= b[3] - 2


def _checkered(gray: np.ndarray) -> bool:
    """Casas escuras alternadas: o tom médio das 64 casas oscila em xadrez (hachuradas, cinza ou cor)."""
    h, w = gray.shape
    if h < 16 or w < 16:
        return False
    m = max(2, min(h, w) // 40)  # ignora a moldura
    inner = gray[m:h - m, m:w - m].astype(np.float32)
    ih, iw = inner.shape
    tone = np.array([[inner[r * ih // 8:(r + 1) * ih // 8, c * iw // 8:(c + 1) * iw // 8].mean() for c in range(8)]
                     for r in range(8)])
    parity = (np.add.outer(np.arange(8), np.arange(8)) % 2).astype(bool)
    return abs(tone[parity].mean() - tone[~parity].mean()) > 10  # níveis de cinza (0–255)


# --- figurinas ------------------------------------------------------------------------
PIECE_REFS = {"♔": "K", "♚": "K", "♕": "Q", "♛": "Q", "♖": "R", "♜": "R", "♗": "B", "♝": "B", "♘": "N", "♞": "N",
              "K": "K", "Q": "Q", "R": "R", "B": "B", "N": "N", "D": "Q", "T": "R", "C": "N", "S": "N", "L": "B"}
CLUSTER_SIMILARITY = 0.85


@dataclass
class PieceCandidate:
    """Um lance com peça lido pelo OCR: a peça será decidida pelo desenho recortado."""

    page: int
    key: tuple[int, int, int]  # (bloco, linha, palavra) no hOCR da página
    prefix: str  # número do lance ("7...")
    rest: str  # o que vem depois da peça ("xe5+")
    raw: str
    vec: np.ndarray
    char: str = ""  # figurina branca ou letra decidida
    score: float = 0.0
    margin: float = 0.0
    confident: bool = False
    cluster: int = -1


def _piece_crop(gray: np.ndarray, word: OcrWord, line: OcrLine, k: int) -> tuple[np.ndarray, int] | None:
    """O primeiro desenho largo depois do número do lance (colunas de tinta contíguas) e onde ele termina.

    Pontos e parênteses (desenhos estreitos) são pulados. A caixa do último
    caractere do número não é confiável: o Tesseract às vezes estica o ponto
    final por cima da figurina que não conseguiu ler.
    """
    size = max(1.0, line.size_px)
    x0 = word.bbox[0]
    for i in range(min(k, len(word.chars)) - 1, -1, -1):
        if word.chars[i].bbox[2] - word.chars[i].bbox[0] < 0.5 * size:
            x0 = word.chars[i].bbox[2] + 1
            break
    y0, y1 = line.bbox[1], line.bbox[3]
    cols = (gray[y0:y1, x0:word.bbox[2]] < 128).any(axis=0)
    i = 0
    while i < cols.size:
        if not cols[i]:
            i += 1
            continue
        start = i
        while i + 1 < cols.size and cols[i + 1]:
            i += 1
        if i + 1 - start >= 0.3 * size:
            return gray[y0:y1, x0 + start:x0 + i + 1], x0 + i + 1
        i += 1
    return None


def _rest_after(word: OcrWord, x: int, fallback: str) -> str:
    """Caracteres cujo centro fica depois do desenho da peça (o OCR às vezes parte a figurina em dois)."""
    if not word.chars:
        return fallback
    rest = "".join(c.text for c in word.chars if (c.bbox[0] + c.bbox[2]) / 2 > x)
    return rest or fallback


def _scores(vec: np.ndarray) -> list[tuple[float, str]]:
    """Semelhança com cada referência de peça (figurina ou letra), da maior para a menor."""
    from app.extraction.glyph_probe import _references, _silhouette, _similarity

    sil = _silhouette(vec)
    out = []
    for ch, pairs in _references().items():
        if ch in PIECE_REFS:
            out.append((max(0.5 * _similarity(vec, r) + 0.5 * _similarity(sil, rs) for r, rs in pairs), ch))
    return sorted(out, reverse=True)


def label_pieces(cands: list[PieceCandidate]) -> None:
    """Agrupa os desenhos iguais do documento e decide a peça de cada grupo pela média deles.

    A média de vários recortes do mesmo glifo é mais limpa que cada um; e o
    mesmo desenho recebe sempre a mesma peça. A confiança exige nota mínima e
    margem contra a melhor referência de **outra** peça (figurina e letra da
    mesma peça não competem).
    """
    from app.extraction.glyph_probe import _similarity

    clusters: list[dict] = []
    for c in cands:
        for i, cl in enumerate(clusters):
            if _similarity(c.vec, cl["rep"]) >= CLUSTER_SIMILARITY:
                cl["members"].append(c)
                cl["sum"] += c.vec
                cl["rep"] = cl["sum"] / len(cl["members"])
                c.cluster = i
                break
        else:
            c.cluster = len(clusters)
            clusters.append({"rep": c.vec.copy(), "sum": c.vec.copy(), "members": [c]})
    for cl in clusters:
        scored = _scores(cl["rep"])
        if not scored:
            continue
        best_score, best = scored[0]
        piece = PIECE_REFS[best]
        runner = next((sc for sc, ch in scored if PIECE_REFS[ch] != piece), 0.0)
        char = WHITE_FIGURINES["KQRBN".index(piece)] if best in FIGURINE_REFS else piece
        for c in cl["members"]:
            c.char, c.score, c.margin = char, best_score, best_score - runner
            c.confident = best_score >= FIGURINE_MIN_SCORE and c.margin >= FIGURINE_MIN_MARGIN


@dataclass
class Prototype:
    """Desenho de uma figurina aprendido no próprio documento (média de um grupo grande e bem classificado)."""

    vec: np.ndarray
    char: str  # figurina branca
    members: int


PROTOTYPE_MIN_MEMBERS = 3
PROTOTYPE_MIN_MARGIN = 0.05
MATCH_SIMILARITY = 0.80  # recorte × protótipo: abaixo disso não é figurina
MATCH_MARGIN = 0.05  # contra o melhor protótipo de outra peça


def prototypes(cands: list[PieceCandidate]) -> list[Prototype]:
    """Figurinas do documento: grupos com vários recortes e margem segura contra outra peça."""
    groups: dict[int, list[PieceCandidate]] = {}
    for c in cands:
        groups.setdefault(c.cluster, []).append(c)
    out = []
    for members in groups.values():
        first = members[0]
        if (len(members) >= PROTOTYPE_MIN_MEMBERS and first.margin >= PROTOTYPE_MIN_MARGIN
                and first.char in WHITE_FIGURINES):
            out.append(Prototype(np.mean([m.vec for m in members], axis=0), first.char, len(members)))
    return out


def match_prototype(vec: np.ndarray, protos: list[Prototype]) -> tuple[str, float, float]:
    """(figurina, semelhança, margem contra outra peça) do protótipo mais parecido."""
    from app.extraction.glyph_probe import _similarity

    scored = sorted(((_similarity(vec, pr.vec), pr.char) for pr in protos), reverse=True)
    best, char = scored[0]
    runner = next((sc for sc, ch in scored if ch != char), 0.0)
    return char, best, best - runner


@dataclass
class PageScan:
    """Primeira passada de uma página: OCR, tabuleiros e lances com peça para aprender as figurinas."""

    page: int
    hocr: str
    boards: list[tuple[float, float, float, float]]
    scale: float
    candidates: list[PieceCandidate]


def _render(page: pymupdf.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)


def _png(gray: np.ndarray) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csGRAY, gray.shape[1], gray.shape[0], np.ascontiguousarray(gray).tobytes(), False)
    return pix.tobytes("png")


def _split_columns(blocks: list[OcrBlock]) -> list[OcrBlock]:
    """Separa o que o Tesseract juntou por cima do vão entre colunas.

    Em páginas de duas colunas, linhas na mesma altura viram uma linha só
    ("Exercises    move, the pawn..."). Um espaço entre palavras maior que
    1,2 vez o tamanho da fonte parte a linha; depois, as linhas se agrupam em
    blocos pela sobreposição horizontal.
    """
    out = []
    for block in blocks:
        lines: list[OcrLine] = []
        for ln in block.lines:
            current = [ln.words[0]]
            for w in ln.words[1:]:
                if w.bbox[0] - current[-1].bbox[2] > 1.2 * max(1.0, ln.size_px):
                    lines.append(_line_of(current, ln))
                    current = [w]
                else:
                    current.append(w)
            lines.append(_line_of(current, ln))
        groups: list[list[OcrLine]] = []
        for ln in lines:
            for g in groups:
                gx0, gx1 = min(x.bbox[0] for x in g), max(x.bbox[2] for x in g)
                width = min(ln.bbox[2] - ln.bbox[0], gx1 - gx0)
                if min(gx1, ln.bbox[2]) - max(gx0, ln.bbox[0]) > 0.3 * width:
                    g.append(ln)
                    break
            else:
                groups.append([ln])
        for g in groups:
            out.append(OcrBlock((min(x.bbox[0] for x in g), min(x.bbox[1] for x in g), max(x.bbox[2] for x in g),
                                 max(x.bbox[3] for x in g)), g))
    return out


def _line_of(words: list[OcrWord], line: OcrLine) -> OcrLine:
    return OcrLine((words[0].bbox[0], line.bbox[1], words[-1].bbox[2], line.bbox[3]), line.size_px, words)


def _text_blocks(hocr: str, boards: list[tuple[float, float, float, float]], scale: float) -> list[OcrBlock]:
    """Blocos do hOCR sem as palavras que o OCR "lê" dentro dos diagramas (casas e peças não são texto)."""
    board_px = [pymupdf.Rect(*(v * scale for v in b)) for b in boards]
    blocks = parse_hocr(hocr)
    for block in blocks:
        for line in block.lines:
            line.words = [w for w in line.words if not any(
                r.contains(pymupdf.Point((w.bbox[0] + w.bbox[2]) / 2, (w.bbox[1] + w.bbox[3]) / 2)) for r in board_px)]
        block.lines = [ln for ln in block.lines if ln.words]
    return _split_columns([b for b in blocks if b.lines])


_PREFIX_RE = re.compile(r"^[(\[]?\d{1,3}\s?\.{0,3}")
_WORDLIKE_RE = re.compile(r"[a-z]{3,}")
# Restos que nenhum lance produz: o OCR perdeu ou trocou a peça ("2...8c4", "c62", "4..4d6").
_IMPOSSIBLE_RE = re.compile(r"^[(\[]?(?:\d{1,3}\.{2,3}\d|[a-h][1-8]\d|\d{1,3}\.\.\d|\S?x?[a-h][lI|][+#!?,;.)]*$)")
_PUNCT = set(".,;:!?'’")


def scan_page(page: pymupdf.Page, lang: str = "eng", dpi: int = OCR_DPI, hocr: str | None = None) -> PageScan:
    gray = _render(page, dpi)
    scale = dpi / 72
    hocr = hocr if hocr is not None else run_tesseract(_png(gray), lang, dpi)
    boards = detect_boards(gray, scale)
    cands = []
    for bi, block in enumerate(_text_blocks(hocr, boards, scale)):
        for li, line in enumerate(block.lines):
            for wi, w in enumerate(line.words):
                m = MOVE_RE.match(w.text)
                if not m:
                    continue
                k = len(m.group("num") or "")
                found = _piece_crop(gray, w, line, k)
                vec = _normalize(found[0]) if found else None
                if vec is None:
                    continue
                rest = _rest_after(w, found[1], w.text[k + 1:])
                cands.append(PieceCandidate(page.number + 1, (bi, li, wi), w.text[:k], rest, w.text, vec))
    return PageScan(page.number + 1, hocr, boards, scale, cands)


@dataclass
class OcrPage:
    blocks: list[dict]  # formato de ``page.get_text("dict")["blocks"]``
    boards: list[tuple[float, float, float, float]]
    warnings: dict[int, list[str]]  # índice do bloco → avisos
    words: int
    low_confidence: int
    pieces: int
    pieces_uncertain: int
    second_pass: bool = False  # figurinas trocadas por letras e OCR de novo
    move_confidence: dict[int, float] = field(default_factory=dict)  # posição da palavra → menor confiança da casa


_REST_RE = re.compile(r"^[a-h]?[1-8]?[x:×]?[a-h][1-8]")
_PIECE_MOVE_RE = re.compile(r"^(?:\d{1,3}\.{0,3})?[♔♕♖♗♘KQRBN][a-h]?[1-8]?[x:×]?[a-h][1-8]")


@dataclass
class _Figurine:
    char: str
    sim: float
    margin: float
    blob: tuple[int, int, int, int]  # pixels
    word: tuple[int, int, int, int]  # palavra da primeira passada que continha a figurina
    prefix: str  # número do lance lido na primeira passada


def _find_figurines(gray: np.ndarray, blocks: list[OcrBlock], protos: list[Prototype]) -> list[_Figurine]:
    """Figurinas no começo das palavras (ou logo depois do número do lance), pelos protótipos do documento."""
    found = []
    for block in blocks:
        for line in block.lines:
            for w in line.words:
                m = _PREFIX_RE.match(w.text)
                k = len(m.group()) if m else 0
                if k >= len(w.text):
                    continue
                crop = _piece_crop(gray, w, line, k)
                if crop is None:
                    continue
                img, end = crop
                vec = _normalize(img)
                if vec is None:
                    continue
                tail = "".join(c.text for c in w.chars if (c.bbox[0] + c.bbox[2]) / 2 > end) if w.chars else ""
                if _WORDLIKE_RE.search(tail):  # "Tragicomedies": letra inicial de palavra comum, não peça
                    continue
                char, sim, margin = match_prototype(vec, protos)
                if sim >= MATCH_SIMILARITY:
                    x0 = end - img.shape[1]
                    found.append(_Figurine(char, sim, margin, (x0, line.bbox[1], end, line.bbox[3]), w.bbox,
                                           w.text[:k]))
    return found


def _letter_font(size: int):
    from PIL import ImageFont

    from app.extraction.glyph_probe import REFERENCE_FONT

    return ImageFont.truetype(str(REFERENCE_FONT), max(8, size))


def _paint_letters(gray: np.ndarray, figs: list[_Figurine]) -> np.ndarray:
    """Troca cada figurina, na imagem, pela letra da peça: o OCR lê "Ke6" sem tropeçar na casa."""
    from PIL import Image, ImageDraw

    img = Image.fromarray(gray.copy())
    draw = ImageDraw.Draw(img)
    for f in figs:
        x0, y0, x1, y1 = f.blob
        draw.rectangle((x0 - 1, y0, x1 + 1, y1), fill=255)
        ink = np.flatnonzero((gray[y0:y1, x0:x1] < 128).any(axis=1))
        top, bottom = (y0 + int(ink[0]), y0 + int(ink[-1])) if ink.size else (y0, y1)
        font = _letter_font(int((bottom - top + 1) / 0.73))
        letter = "KQRBN"[WHITE_FIGURINES.index(f.char)]
        width = draw.textlength(letter, font=font)
        # alinhada pela direita: a distância até a casa fica a do original, e o OCR não separa as palavras
        draw.text((max(x0, x1 - width), bottom + 1), letter, font=font, fill=0, anchor="ls")
    return np.asarray(img)


def _restore_figurines(blocks: list[OcrBlock], figs: list[_Figurine]) -> list[str]:
    """Volta a letra desenhada para a figurina, pela posição. Devolve avisos do que não achou lugar."""
    notes = []
    for f in figs:
        cx = (f.blob[0] + f.blob[2]) / 2
        cy = (f.blob[1] + f.blob[3]) / 2
        letter = "KQRBN"[WHITE_FIGURINES.index(f.char)]
        done = False
        for block in blocks:
            for line in block.lines:
                for w in line.words:
                    if not (w.bbox[0] - 2 <= cx <= w.bbox[2] + 2 and w.bbox[1] - 2 <= cy <= w.bbox[3] + 2):
                        continue
                    i = next((i for i, c in enumerate(w.chars) if c.bbox[0] - 2 <= cx <= c.bbox[2] + 2), None)
                    if i is None or w.chars[i].text != letter:
                        m = _PREFIX_RE.match(w.text)
                        k = len(m.group()) if m else 0
                        i = k if k < len(w.text) and w.text[k] == letter else None
                    if i is not None:
                        w.text = w.text[:i] + f.char + w.text[i + 1:]
                        if i < len(w.chars):
                            w.chars[i].text = f.char
                        done = True
                    break
                if done:
                    break
            if done:
                break
        if not done:
            notes.append(f"ocr_figurina_sem_lugar: {f.char} ({f.prefix or 'sem número'})")
    for block in blocks:  # figurina que o OCR separou da casa: junta se estavam coladas
        for line in block.lines:
            merged: list[OcrWord] = []
            for w in line.words:
                prev = merged[-1] if merged else None
                gap = w.bbox[0] - prev.bbox[2] if prev is not None else 1e9
                size = max(1.0, line.size_px)
                glued = prev is not None and (
                    (prev.text[-1:] in WHITE_FIGURINES and _REST_RE.match(w.text) and gap < 0.25 * size)
                    # "7..." e "♔a4": a letra desenhada é mais estreita que a figurina e abre um espaço
                    or (re.fullmatch(r"[(\[]?\d{1,3}\.\.\.", prev.text) and w.text[:1] in WHITE_FIGURINES
                        and gap < size))
                if glued:
                    merged[-1] = OcrWord(prev.text + w.text, (prev.bbox[0], min(prev.bbox[1], w.bbox[1]), w.bbox[2],
                                                              max(prev.bbox[3], w.bbox[3])),
                                         min(prev.conf, w.conf), prev.chars + w.chars)
                else:
                    merged.append(w)
            line.words = merged
    return notes


def unread_ink(gray: np.ndarray, line: OcrLine, min_width: float) -> list[tuple[int, int]]:
    """Trechos de tinta da linha que nenhum caractere lido cobre: o OCR pulou um desenho (uma figurina, por exemplo)."""
    y0, y1 = line.bbox[1], line.bbox[3]
    x0, x1 = line.bbox[0], line.bbox[2]
    cols = (gray[y0:y1, x0:x1] < 128).sum(axis=0) >= 2
    for w in line.words:
        boxes = [c.bbox for c in w.chars] or [w.bbox]
        for b in boxes:
            cols[max(0, b[0] - x0 - 1):max(0, b[2] - x0 + 1)] = False
    out, start = [], None
    for i, on in enumerate(np.append(cols, False)):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= min_width:
                out.append((x0 + start, x0 + i))
            start = None
    return out


def read_page(page: pymupdf.Page, scan: PageScan, protos: list[Prototype], lang: str = "eng",
              dpi: int = OCR_DPI) -> OcrPage:
    """Segunda passada: figurinas reconhecidas pelos protótipos, trocadas pela letra na imagem e o OCR refeito.

    Sem protótipos (livro com letras, ou figurinas raras demais para aprender),
    vale a primeira passada com a peça de cada lance decidida pelo grupo.
    """
    blocks = _text_blocks(scan.hocr, scan.boards, scan.scale)
    figs: list[_Figurine] = []
    extra_notes: list[str] = []
    if protos:
        gray = _render(page, dpi)
        figs = _find_figurines(gray, blocks, protos)
        if figs:
            painted = _paint_letters(gray, figs)
            blocks = _text_blocks(run_tesseract(_png(painted), lang, dpi), scan.boards, scan.scale)
            extra_notes = _restore_figurines(blocks, figs)
    weak = {f.word for f in figs if f.margin < MATCH_MARGIN}
    # a imagem que o OCR leu por último, para conferir se alguma tinta ficou sem leitura
    second_gray = painted if figs else gray if protos else _render(page, dpi)
    by_key = {} if protos else {c.key: c for c in scan.candidates}
    out_blocks: list[dict] = []
    warnings: dict[int, list[str]] = {}
    stats = {"words": 0, "low": 0, "pieces": 0, "uncertain": 0}
    move_conf: dict[int, float] = {}
    for bi, block in enumerate(blocks):
        lines, notes = [], []
        for li, line in enumerate(block.lines):
            words = []
            skipped = unread_ink(second_gray, line, 0.35 * max(1.0, line.size_px))
            for wi, w in enumerate(line.words):
                text = w.text
                gap_before = [g for g in skipped if g[1] <= w.bbox[2] and g[0] >= (line.words[wi - 1].bbox[2] if wi else
                                                                                   line.bbox[0]) - 1]
                if gap_before:
                    notes.append(f"ocr_desenho_nao_lido: antes de/em '{text}'")
                    stats["uncertain"] += 1
                elif any(c.text in _PUNCT and c.bbox[2] - c.bbox[0] > 0.4 * max(1.0, line.size_px) for c in w.chars):
                    # pontuação larga demais: costuma esconder um desenho que o OCR não leu
                    notes.append(f"ocr_desenho_nao_lido: em '{text}'")
                    stats["uncertain"] += 1
                cand = by_key.get((bi, li, wi))
                if cand is not None:  # sem protótipos: peça do grupo, sobre a leitura da primeira passada
                    text = cand.prefix + (cand.char or "?") + cand.rest
                    if not cand.confident:
                        notes.append(f"ocr_peca_incerta: '{text}' (lido '{w.text}')")
                        stats["uncertain"] += 1
                if any(ch in WHITE_FIGURINES for ch in text) or cand is not None:
                    stats["pieces"] += 1
                    square_conf = min((c.conf for c in w.chars if c.text not in WHITE_FIGURINES), default=w.conf)
                    move_conf[stats["words"]] = square_conf
                    if not _PIECE_MOVE_RE.match(text) and any(ch in WHITE_FIGURINES for ch in text[:5]):
                        notes.append(f"ocr_lance_incompleto: '{text}'")
                        stats["uncertain"] += 1
                    elif any(f.word[0] <= w.bbox[0] + 3 and w.bbox[2] <= f.word[2] + 3 for f in figs
                             if f.word in weak):
                        notes.append(f"ocr_peca_incerta: '{text}'")
                        stats["uncertain"] += 1
                elif MOVE_RE.match(text):  # parece lance, mas a peça não bate com nenhuma figurina conhecida
                    stats["pieces"] += 1
                    stats["uncertain"] += 1
                    notes.append(f"ocr_peca_incerta: '{text}'")
                elif _IMPOSSIBLE_RE.match(text):
                    stats["uncertain"] += 1
                    notes.append(f"ocr_lance_ilegivel: '{text}'")
                stats["words"] += 1
                if w.conf < MIN_WORD_CONF:
                    stats["low"] += 1
                    notes.append(f"ocr_baixa_confianca: '{text}' ({w.conf:.0f})")
                words.append((text, pymupdf.Rect(*(v / scan.scale for v in w.bbox))))
            # x_size do Tesseract × 1,07 = corpo da fonte (medido: 9,4 pt lidos para corpo 10 no livro de amostra)
            size = max(4.0, (line.size_px or (line.bbox[3] - line.bbox[1])) / scan.scale * 1.07)
            lrect = pymupdf.Rect(*(v / scan.scale for v in line.bbox))
            spans = [{"text": text + (" " if i < len(words) - 1 else ""), "font": OCR_FONT, "size": size,
                      "flags": 0, "color": 0, "bbox": tuple(rect), "origin": (rect.x0, lrect.y1),
                      "ascender": 0.9, "descender": -0.25, "alpha": 255, "char_flags": 0}
                     for i, (text, rect) in enumerate(words)]
            lines.append({"bbox": tuple(lrect), "spans": spans, "wmode": 0, "dir": (1.0, 0.0)})
        bbox = pymupdf.Rect()
        for ln in lines:
            bbox |= pymupdf.Rect(ln["bbox"])
        if bi == 0 and extra_notes:
            notes.extend(extra_notes)
        if notes:
            warnings[len(out_blocks)] = notes
        out_blocks.append({"type": 0, "bbox": tuple(bbox), "lines": lines, "number": len(out_blocks)})
    return OcrPage(out_blocks, scan.boards, warnings, stats["words"], stats["low"], stats["pieces"],
                   stats["uncertain"], bool(figs), move_conf)


def version(lang: str = "eng") -> str:
    """Muda com o código do OCR, as referências de peças e o Tesseract: invalida o OCR guardado."""
    import hashlib
    from pathlib import Path

    h = hashlib.sha256(lang.encode())
    here = Path(__file__).resolve().parent
    for name in ("ocr.py", "glyph_probe.py"):
        h.update((here / name).read_bytes())
    try:
        h.update(subprocess.run(["tesseract", "--version"], check=False, capture_output=True,
                                timeout=30).stdout[:200])
    except (OSError, subprocess.SubprocessError):
        h.update(b"sem-tesseract")
    return h.hexdigest()[:16]


def scanned_pages(doc: pymupdf.Document) -> list[int]:
    """Páginas (1-based) só com imagem."""
    return [p + 1 for p in range(doc.page_count) if needs_ocr(doc[p])]


def document_ocr(doc: pymupdf.Document, cache: object = None, lang: str = "eng", progress=None,
                 mode: str = "auto") -> dict[int, dict]:
    """OCR de todas as páginas digitalizadas do documento, guardado em ``cache`` (JSON) se informado.

    ``mode``: ``auto`` lê por OCR só livros majoritariamente digitalizados (num
    livro digital, uma página só de imagem é capa ou foto, não texto); ``on``
    lê toda página só de imagem; ``off`` não lê. Um ``cache`` existente vale
    sobre o modo: é a decisão gravada no projeto.

    Todas de uma vez, porque as figurinas são aprendidas no conjunto: ler só
    parte do livro daria protótipos diferentes, e páginas lidas em momentos
    diferentes poderiam discordar. Devolve {página: {"blocks", "boards", "stats"}};
    os avisos de cada bloco vão em ``block["ocr_warnings"]``.
    """
    import json
    from pathlib import Path

    path = Path(cache) if cache else None
    if path is not None and path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if stored.get("version") == version(lang):
            return {int(k): v for k, v in stored["pages"].items()}
        mode = "on"  # o projeto foi lido por OCR: com código novo, lê de novo
    if mode == "off":
        return {}
    pages = scanned_pages(doc)
    if not pages or (mode == "auto" and len(pages) < doc.page_count / 2):
        return {}
    key = version(lang)
    out = {}
    for p, res in ocr_document(doc, pages, lang, progress=progress).items():
        blocks = []
        for i, b in enumerate(res.blocks):
            blocks.append({**b, "ocr_warnings": res.warnings.get(i, [])})
        out[p] = {"blocks": blocks, "boards": res.boards,
                  "stats": {"words": res.words, "low_confidence": res.low_confidence, "pieces": res.pieces,
                            "pieces_uncertain": res.pieces_uncertain, "second_pass": res.second_pass}}
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"version": key, "pages": out}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    # mesmo formato vindo do cache ou da leitura (listas no lugar de tuplas; páginas como inteiros)
    return {int(k): v for k, v in json.loads(json.dumps(out)).items()}


def ocr_document(doc: pymupdf.Document, pages: list[int], lang: str = "eng", dpi: int = OCR_DPI,
                 progress=None) -> dict[int, OcrPage]:
    """OCR das páginas (1-based). As figurinas são aprendidas no conjunto: glifos iguais, mesma peça."""
    scans = []
    for i, p in enumerate(pages):
        scans.append(scan_page(doc[p - 1], lang, dpi))
        if progress:
            progress("ocr", i + 1, len(pages))
    cands = [c for s in scans for c in s.candidates]
    label_pieces(cands)
    protos = prototypes(cands)
    out = {}
    for i, s in enumerate(scans):
        out[s.page] = read_page(doc[s.page - 1], s, protos, lang, dpi)
        if progress:
            progress("figurinas", i + 1, len(scans))
    return out


def ocr_page(page: pymupdf.Page, lang: str = "eng", dpi: int = OCR_DPI, hocr: str | None = None) -> OcrPage:
    scan = scan_page(page, lang, dpi, hocr)
    label_pieces(scan.candidates)
    return read_page(page, scan, prototypes(scan.candidates), lang, dpi)

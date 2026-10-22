"""Geradores de PDFs sintéticos que imitam páginas de livros de xadrez.

Nenhum livro real é usado nos testes. Os documentos são gerados de forma
determinística a partir de texto conhecido, o que permite verificar com
exatidão o que a extração, a tradução e a reconstrução preservaram.

Cenários cobertos:

* ``fan_unicode``: notação figurativa com símbolos Unicode reais (U+2654..U+265F).
* ``fan_letter_font``: fonte "figurina" cujo mapa de caracteres associa a letra
  ``N`` ao desenho do cavalo, como fazem várias fontes comerciais de editores
  de xadrez. A extração devolve ``N``, mas a página mostra ``♘``.
* ``fan_pua_font``: fonte cujos símbolos ficam na Área de Uso Privado (U+E000+),
  sem equivalência Unicode padrão.
* ``scanned``: a página inteira rasterizada, sem camada de texto.
"""

from __future__ import annotations

import functools
import io
from dataclasses import dataclass
from pathlib import Path

import chess
import pymupdf
from fontTools import subset
from fontTools.ttLib import TTFont

DEJAVU = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
DEJAVU_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

FIGURINES = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘"}
PUA_BASE = 0xE000
PUA_FOR = {letter: PUA_BASE + i for i, letter in enumerate("KQRBN")}

# Posição do diagrama: Ruy López após 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6.
DIAGRAM_MOVES_SAN = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]

TITLE_EN = "Chapter 3: The Ruy Lopez"
PARA1_EN = (
    "1.e4 e5 2.{N}f3 {N}c6 3.{B}b5 a6 This is the main line of the Ruy Lopez. "
    "After 4.{B}a4 {N}f6 5.0-0 White keeps the tension; the exchange 4.{B}xc6 dxc6 "
    "gives Black the bishop pair but a weakened pawn structure on the queenside."
)
CAPTION_EN = "Diagram 7. White to move"
PARA2_EN = (
    "The knight on f3 controls e5 and prepares castling. Black must decide "
    "whether to defend the e5-pawn with ...d6 or to counterattack with ...{N}f6."
)
FOOTNOTE_EN = "1 See also the analysis in Chapter 5."

# Tradução humana de referência (não é saída de máquina). Usada pelo spike para
# medir o comportamento das estratégias de reconstrução com texto mais longo.
TITLE_PT = "Capítulo 3: A Abertura Ruy López"
PARA1_PT = (
    "1.e4 e5 2.{N}f3 {N}c6 3.{B}b5 a6 Esta é a linha principal da Ruy López. "
    "Após 4.{B}a4 {N}f6 5.0-0, as brancas mantêm a tensão; a troca 4.{B}xc6 dxc6 "
    "dá às pretas o par de bispos, mas deixa uma estrutura de peões enfraquecida "
    "na ala da dama."
)
CAPTION_PT = "Diagrama 7. As brancas jogam"
PARA2_PT = (
    "O cavalo em f3 controla e5 e prepara o roque. As pretas precisam decidir "
    "se defendem o peão de e5 com ...d6 ou se contra-atacam com ...{N}f6."
)
FOOTNOTE_PT = "1 Veja também a análise no Capítulo 5."


@dataclass(frozen=True)
class Region:
    """Retângulo de referência de um elemento na página sintética."""

    name: str
    rect: tuple[float, float, float, float]


@dataclass(frozen=True)
class SyntheticPage:
    pdf_bytes: bytes
    regions: dict[str, Region]
    figurine_mode: str


def fill(template: str, mode: str) -> str:
    """Substitui ``{N}``, ``{B}`` etc. pelo que a fonte do cenário espera."""
    out = template
    for letter in "KQRBN":
        if mode == "fan_unicode":
            repl = FIGURINES[letter]
        elif mode == "fan_letter_font":
            repl = letter
        elif mode == "fan_pua_font":
            repl = chr(PUA_FOR[letter])
        elif mode == "english":
            repl = letter
        else:
            raise ValueError(mode)
        out = out.replace("{" + letter + "}", repl)
    return out


@functools.cache
def build_figurine_font(mode: str) -> bytes:
    """Cria uma fonte mínima com os desenhos das peças da DejaVu Sans.

    ``fan_letter_font``: os desenhos só são alcançáveis pelas letras K, Q, R, B, N
    (como em fontes figurinas de editoras de xadrez). ``fan_pua_font``: só são
    alcançáveis por pontos de código privados (U+E000..). Os glifos recebem nomes
    sem significado Unicode, para que o leitor de PDF não consiga deduzir o
    caractere a partir do nome. A página mostra figuras corretas, mas a extração
    textual não devolve os caracteres Unicode de xadrez.
    """
    font = TTFont(str(DEJAVU))
    subsetter = subset.Subsetter(subset.Options(glyph_names=True, notdef_outline=True, drop_tables=["FFTM"]))
    subsetter.populate(unicodes=[ord(s) for s in FIGURINES.values()])
    subsetter.subset(font)
    for tag in ("GSUB", "GPOS", "GDEF", "kern", "FFTM"):
        if tag in font:
            del font[tag]
    cmap = font.getBestCmap()
    rename = {cmap[ord(sym)]: f"fig{letter}" for letter, sym in FIGURINES.items()}
    font.setGlyphOrder([rename.get(g, g) for g in font.getGlyphOrder()])
    for table_name in ("glyf", "hmtx"):
        table = font[table_name]
        store = table.glyphs if table_name == "glyf" else table.metrics
        for old, new in rename.items():
            store[new] = store.pop(old)
    font["post"].formatType = 3.0  # sem nomes de glifos no arquivo final
    codes = {
        letter: ord(letter) if mode == "fan_letter_font" else PUA_FOR[letter] for letter in FIGURINES
    }
    if mode not in ("fan_letter_font", "fan_pua_font"):
        raise ValueError(mode)
    for table in font["cmap"].tables:
        table.cmap = {codes[letter]: f"fig{letter}" for letter in FIGURINES}
    font["name"].setName("ChessFigurineTest", 1, 3, 1, 0x409)
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def _draw_diagram(page: pymupdf.Page, rect: pymupdf.Rect, board: chess.Board) -> None:
    """Desenha um tabuleiro vetorial com peças como glifos de texto.

    Muitos livros compõem diagramas com fontes de diagrama (peças como texto).
    Isso é o pior caso para estratégias que apagam texto: o diagrama também é
    texto e não pode ser removido junto com a prosa.
    """
    sq = rect.width / 8
    for rank in range(8):
        for file in range(8):
            r = pymupdf.Rect(
                rect.x0 + file * sq,
                rect.y0 + (7 - rank) * sq,
                rect.x0 + (file + 1) * sq,
                rect.y0 + (8 - rank) * sq,
            )
            dark = (rank + file) % 2 == 0
            page.draw_rect(r, color=None, fill=(0.62, 0.55, 0.45) if dark else (0.93, 0.9, 0.82))
            piece = board.piece_at(chess.square(file, rank))
            if piece:
                page.insert_text(
                    (r.x0 + sq * 0.12, r.y1 - sq * 0.2),
                    piece.unicode_symbol(),
                    fontsize=sq * 0.8,
                    fontname="diag",
                    fontfile=str(DEJAVU),
                )
    page.draw_rect(rect, color=(0, 0, 0), width=1)


def _markup(template: str, mode: str) -> str:
    """Converte o template em HTML, com os marcadores de peça na fonte do cenário."""
    parts = []
    i = 0
    while i < len(template):
        if template[i] == "{" and template[i + 2 : i + 3] == "}":
            letter = template[i + 1]
            if mode == "fan_unicode":
                parts.append(FIGURINES[letter])
            elif mode == "english":
                parts.append(letter)
            elif mode == "fan_letter_font":
                parts.append(f'<span style="font-family:figu">{letter}</span>')
            elif mode == "fan_pua_font":
                parts.append(f'<span style="font-family:figu">{chr(PUA_FOR[letter])}</span>')
            else:
                raise ValueError(mode)
            i += 3
        else:
            parts.append({"<": "&lt;", ">": "&gt;", "&": "&amp;"}.get(template[i], template[i]))
            i += 1
    return "".join(parts)


def build_page(mode: str = "fan_unicode") -> SyntheticPage:
    """Monta uma página A5 com título, parágrafos, diagrama, legenda e nota."""
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=595)  # A5 em pontos
    archive = pymupdf.Archive()
    archive.add(DEJAVU.read_bytes(), DEJAVU.name)
    archive.add(DEJAVU_BOLD.read_bytes(), DEJAVU_BOLD.name)
    if mode in ("fan_letter_font", "fan_pua_font"):
        archive.add(build_figurine_font(mode), "figu.ttf")
    regions: dict[str, Region] = {}

    def text_block(name: str, rect: pymupdf.Rect, template: str, size: float, bold: bool = False) -> None:
        css = (
            f"@font-face {{font-family: body; src: url({DEJAVU.name});}}"
            f"@font-face {{font-family: bold; src: url({DEJAVU_BOLD.name});}}"
            "@font-face {font-family: figu; src: url(figu.ttf);}"
            f"body {{font-family: {'bold' if bold else 'body'}; font-size: {size}pt; line-height: 1.3;}}"
        )
        spare, _scale = page.insert_htmlbox(rect, _markup(template, mode), css=css, archive=archive)
        if spare < 0:
            raise RuntimeError(f"texto do bloco {name} não coube na área de referência")
        regions[name] = Region(name, tuple(rect))

    text_block("title", pymupdf.Rect(40, 40, 380, 70), TITLE_EN, 14, bold=True)
    text_block("para1", pymupdf.Rect(40, 80, 380, 170), PARA1_EN, 10)

    board = chess.Board()
    for san in DIAGRAM_MOVES_SAN:
        board.push_san(san)
    diag_rect = pymupdf.Rect(110, 180, 310, 380)
    _draw_diagram(page, diag_rect, board)
    regions["diagram"] = Region("diagram", tuple(diag_rect))

    text_block("caption", pymupdf.Rect(110, 386, 310, 402), CAPTION_EN, 9)
    text_block("para2", pymupdf.Rect(40, 412, 380, 470), PARA2_EN, 10)
    text_block("footnote", pymupdf.Rect(40, 540, 380, 556), FOOTNOTE_EN, 8)
    text_block("pageno", pymupdf.Rect(195, 565, 225, 580), "47", 9)
    doc.set_metadata({"title": "Synthetic chess book page", "producer": "chessbook-translator tests"})
    doc.subset_fonts()
    data = doc.tobytes(garbage=3, deflate=True)
    return SyntheticPage(pdf_bytes=data, regions=regions, figurine_mode=mode)


def build_scanned(page: SyntheticPage, dpi: int = 200) -> bytes:
    """Rasteriza a página e devolve um PDF somente-imagem (sem camada de texto)."""
    src = pymupdf.open(stream=page.pdf_bytes, filetype="pdf")
    pix = src[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    out = pymupdf.open()
    p = out.new_page(width=src[0].rect.width, height=src[0].rect.height)
    p.insert_image(p.rect, stream=pix.tobytes("png"))
    return out.tobytes(garbage=3, deflate=True)

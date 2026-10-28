"""OCR de páginas digitalizadas: hOCR, diagramas pela moldura, figurinas pela imagem, avisos e montagem."""

import shutil

import numpy as np
import pymupdf
import pytest

from app.extraction import ocr
from app.layout import assemble as asm
from app.pipeline.notation_pass import OCR_FLAG, collect
from app.pipeline.segments import book_segments
from app.store.jobs import _run
from app.store.project_store import ProjectStore
from app.translation.engines import ENGINES, Prices
from app.translation.providers.fake import PseudoProvider
from scripts.evaluate_ocr import rasterize
from tests.fixtures import synthetic as syn

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract não instalado")

HOCR = """<html><body><div class='ocr_page'>
<div class='ocr_carea' title="bbox 0 0 900 100"><p class='ocr_par' title="bbox 10 10 900 60">
<span class='ocr_line' title="bbox 10 10 300 50; baseline 0 -5; x_size 40; x_descenders 8">
 <span class='ocrx_word' title='bbox 10 10 120 50; x_wconf 91'>
  <span class='ocrx_cinfo' title='x_bboxes 10 10 40 50; x_conf 99'>1</span><span
   class='ocrx_cinfo' title='x_bboxes 42 10 60 50; x_conf 98'>.</span><span
   class='ocrx_cinfo' title='x_bboxes 62 10 90 50; x_conf 70'>@</span><span
   class='ocrx_cinfo' title='x_bboxes 92 10 120 50; x_conf 95'>e</span></span>
 <span class='ocrx_word' title='bbox 700 10 900 50; x_wconf 40'>
  <span class='ocrx_cinfo' title='x_bboxes 700 10 900 50; x_conf 40'>far</span></span>
</span></p></div></div></body></html>"""


def test_hocr_keeps_words_chars_confidence_and_splits_columns():
    blocks = ocr.parse_hocr(HOCR)
    word = blocks[0].lines[0].words[0]
    assert (word.text, word.conf, word.chars[2].bbox) == ("1.@e", 91.0, (62, 10, 90, 50))
    # o vão de 580 px entre as palavras (> 1,2 × corpo 40) é o espaço entre colunas
    split = ocr._split_columns(blocks)
    assert [[w.text for ln in b.lines for w in ln.words] for b in split] == [["1.@e"], ["far"]]


@pytest.mark.parametrize("text, impossible", [
    ("2...8c4", True), ("c62", True), ("4..4d6", True), ("Afl+", True), ("♔el", True),
    ("2...♔c4", False), ("e4", False), ("1...b5", False),
])
def test_patterns_no_move_can_produce_are_flagged(text, impossible):
    assert bool(ocr._IMPOSSIBLE_RE.match(text)) is impossible


def _scanned(page: pymupdf.Page, noise: float = 0) -> pymupdf.Document:
    return rasterize(page, 300, noise, np.random.default_rng(1))


def test_scanned_page_detection():
    digital = pymupdf.open(stream=syn.build_page("fan_unicode").pdf_bytes, filetype="pdf")
    assert not ocr.needs_ocr(digital[0])
    assert ocr.needs_ocr(_scanned(digital[0])[0])


def test_board_found_by_its_frame_and_checkered_squares():
    page = syn.build_page("fan_unicode")
    scan = _scanned(pymupdf.open(stream=page.pdf_bytes, filetype="pdf")[0])
    pix = scan[0].get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    boards = ocr.detect_boards(gray, 300 / 72)
    assert len(boards) == 1
    assert all(abs(a - b) < 3 for a, b in zip(boards[0], (110, 180, 310, 380), strict=True))
    # sem tabuleiro, nada é inventado: a mesma página com o diagrama coberto
    gray = gray.copy()
    x0, y0, x1, y1 = (int(v * 300 / 72) for v in (100, 170, 320, 390))
    gray[y0:y1, x0:x1] = 255
    assert ocr.detect_boards(gray, 300 / 72) == []


def _hatched_board(side: int = 300, line: int = 3) -> np.ndarray:
    """Tabuleiro como nos livros digitalizados: casas escuras com hachura fina e clara, moldura fina."""
    img = np.full((side, side), 255, np.uint8)
    sq = side // 8
    yy, xx = np.mgrid[0:sq, 0:sq]
    hatch = np.where((xx + yy) % 6 == 0, 150, 255).astype(np.uint8)  # traço diagonal claro
    for r in range(8):
        for c in range(8):
            if (r + c) % 2:
                img[r * sq:(r + 1) * sq, c * sq:(c + 1) * sq] = hatch
    img[(np.arange(side) % 50 == 7)[:, None] & (np.arange(side) % 37 < 20)[None, :]] = 0  # peças
    img[:line], img[-line:], img[:, :line], img[:, -line:] = 0, 0, 0, 0
    return img


def test_board_found_on_a_crooked_scan_with_light_hatching():
    """Página digitalizada um pouco torta: a moldura chega aos pedaços e a hachura é clara."""
    page = np.full((1300, 800), 255, np.uint8)
    board = _hatched_board(480)  # ~115 pt a 300 dpi
    for x in range(480):  # inclinação de 6 px ao longo do tabuleiro
        dy = x * 6 // 480
        page[100 + dy:580 + dy, 100 + x] = board[:, x]
    # caixa de texto emoldurada do mesmo tamanho: não é tabuleiro
    page[700:703, 100:580] = page[1177:1180, 100:580] = 0
    page[700:1180, 100:103] = page[700:1180, 577:580] = 0
    page[720:1160:20, 120:560] = 0
    boards = ocr.detect_boards(page, 300 / 72)
    assert len(boards) == 1
    assert abs(boards[0][1] * 300 / 72 - 100) < 8


def test_piece_drawn_as_letter_is_classified_as_that_letter():
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=60)
    page.insert_text((20, 40), "Nf3", fontsize=28, fontfile=str(syn.DEJAVU), fontname="dj")
    pix = page.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    cols = np.flatnonzero((gray < 128).any(axis=0))
    first_gap = next(i for i in range(len(cols) - 1) if cols[i + 1] - cols[i] > 1)
    vec = ocr._normalize(gray[:, cols[0]:cols[first_gap] + 1])
    _score, best = ocr._scores(vec)[0]
    assert ocr.PIECE_REFS[best] == "N" and best not in ocr.WHITE_FIGURINES


@needs_tesseract
def test_ocr_of_synthetic_fan_page_never_leaves_a_wrong_move_unflagged():
    """Na página sintética (FAN da DejaVu), todo lance mal lido sai com aviso de conferência."""
    page = pymupdf.open(stream=syn.build_page("fan_unicode").pdf_bytes, filetype="pdf")[0]
    res = ocr.ocr_page(_scanned(page)[0])
    assert len(res.boards) == 1
    words = [(s["text"].strip(), b["number"]) for b in res.blocks for ln in b["lines"] for s in ln["spans"]]
    assert any("♘f3" in w for w, _ in words)  # figurina reconhecida pelo desenho
    expected = {"2.♘f3", "♘c6", "3.♗b5", "4.♗a4", "♘f6", "4.♗xc6", "...♘f6."}
    for text, block in words:
        looks_like_move = any(ch in "♔♕♖♗♘" for ch in text) or ocr._IMPOSSIBLE_RE.match(text) or ocr.MOVE_RE.match(text)
        if looks_like_move and text not in expected:
            assert any(f"'{text}'" in n for n in res.warnings.get(block, [])), text
    # o lance cuja figurina o OCR pulou ("...f6" no lugar de "...♘f6") pede conferência
    para2 = next(b for b, ws in res.warnings.items() if any("f6" in n for n in ws))
    assert any(n.startswith(("ocr_desenho_nao_lido", "ocr_baixa_confianca", "ocr_peca")) for n in res.warnings[para2])


@needs_tesseract
def test_scanned_book_goes_through_extraction_review_and_assembly(tmp_path, monkeypatch):
    monkeypatch.setattr(asm, "CHUNK_PAGES", 1)
    page = pymupdf.open(stream=syn.build_page("fan_unicode").pdf_bytes, filetype="pdf")[0]
    pdf = tmp_path / "digitalizado.pdf"
    _scanned(page, noise=4).save(pdf)
    doc = pymupdf.open(pdf)
    cache = tmp_path / "ocr.json"
    notation = collect(doc, ocr_cache=cache)
    assert cache.exists() and len(notation.diagrams) == 1 and notation.diagrams[0].fen is None
    segs = book_segments(notation, "Livro")
    assert segs and all(OCR_FLAG in s.flags for s in segs)
    # a segunda leitura vem do cache: mesmo texto, sem chamar o Tesseract
    monkeypatch.setattr(ocr, "run_tesseract", lambda *a, **k: pytest.fail("OCR repetido"))
    again = collect(doc, ocr_cache=cache)
    assert [r.resolved.text for r in again.regions] == [r.resolved.text for r in notation.regions]

    store = ProjectStore.create(tmp_path / "storage", "scan", "Digitalizado", pdf, 1, notation.style)
    store.add_book_segments([{"id": b.id, "page": b.page, "section": b.section.label, "source": b.region.resolved.text,
                              "kind": b.kind, "bold": b.region.main_mask, "italic": b.region.italic_mask,
                              "blocked": b.blocked, "flags": b.flags} for b in segs])
    seg = next(s for s in store.segments() if s.status == "pending")
    # só o aviso geral não pede atenção; um aviso sobre lance, casa ou número pede, até a aprovação
    assert OCR_FLAG in seg.source_flags
    assert seg.needs_attention == any(f != OCR_FLAG and any(c.isdigit() for c in f) for f in seg.source_flags)
    with store._db() as db:
        db.execute("INSERT INTO job (engine, model, pages, state, budget, author, created_at)"
                   " VALUES ('pseudo','pseudo','1','queued',1,'t','t')")
    _run(store, 1, store.sources({1}), ENGINES[0], PseudoProvider(), Prices({}, "teste"))
    store.approve(seg.id, "revisor")
    assert not store.segment(seg.id).needs_attention  # conferido com a imagem e aprovado
    # o original corrigido à mão é o que se traduz e se monta
    other = next(s for s in store.segments() if s.id != seg.id and s.current is not None)
    store.edit_source(other.id, other.source + " Corrected.", "revisor")
    with store._db() as db:
        db.execute("INSERT INTO job (engine, model, pages, state, budget, author, created_at)"
                   " VALUES ('pseudo','pseudo','1','queued',1,'t','t')")
    _run(store, 2, store.sources({1}), ENGINES[0], PseudoProvider(), Prices({}, "teste"))
    assert "Corrected" in store.segment(other.id).current.text
    summary = asm.assemble(store.original_path, store.export_result(), store.dir / "output", ocr_cache=cache)
    assert summary["blocks_placed"] == summary["blocks"] > 0
    assert summary["leftover_original"] == [] and summary["diagrams_changed"] == []
    assert summary["diagrams_checked"] == 1
    out = pymupdf.open(store.dir / "output" / "traduzido.pdf")
    assert out[0].get_text().strip()  # a tradução é texto de verdade (pesquisável), sobre a imagem limpa


def test_digital_book_with_an_image_page_is_not_read_by_ocr(monkeypatch):
    """Num livro digital, a página só de imagem é capa ou foto: o modo automático não a lê."""
    digital = pymupdf.open(stream=syn.build_page("fan_unicode").pdf_bytes, filetype="pdf")
    book = pymupdf.open()
    book.insert_pdf(digital)
    book.insert_pdf(digital)
    book.insert_pdf(_scanned(digital[0]))
    assert ocr.scanned_pages(book) == [3]
    monkeypatch.setattr(ocr, "run_tesseract", lambda *a, **k: pytest.fail("OCR num livro digital"))
    notation = collect(book)
    assert {r.page for r in notation.regions} == {1, 2}
    assert ocr.document_ocr(book, mode="off") == {}


@needs_tesseract
def test_user_confirmed_figurine_is_read_in_the_whole_book(tmp_path):
    """Uma figurina que aparece pouco não vira protótipo sozinha; confirmada pelo usuário, é lida."""
    import json

    page = pymupdf.open(stream=syn.build_page("fan_unicode").pdf_bytes, filetype="pdf")[0]
    pdf = tmp_path / "digitalizado.pdf"
    _scanned(page, noise=4).save(pdf)
    doc = pymupdf.open(pdf)
    cache = tmp_path / "ocr.json"
    before = " ".join(r.resolved.text for r in collect(doc, ocr_cache=cache).regions)
    assert "2.♘f3" not in before  # o cavalo aparece só duas vezes: sem protótipo
    groups = json.loads(cache.read_text())["figurine_groups"]
    knight = next(g for g in groups if g["auto"] == "♘")
    assert knight["count"] == 2 and knight["image"].startswith("data:image/png;base64,")

    with pytest.raises(ValueError):
        ocr.reread_with_figurines(doc, cache, {knight["id"]: "X"})
    res = ocr.reread_with_figurines(doc, cache, {knight["id"]: "♘"})
    assert res["pages"] == 1
    after = " ".join(r.resolved.text for r in collect(doc, ocr_cache=cache).regions)
    assert "2.♘f3" in after and "♘c6" in after
    saved = json.loads((tmp_path / "ocr-figurinas.json").read_text())
    assert {c["char"] for c in saved} >= {"♘", "♗"}  # o bispo não marcado fica com a sugestão
    assert json.loads(cache.read_text())["labels"][str(knight["id"])] == "♘"

    # um OCR refeito (programa atualizado) herda a decisão pelo desenho
    stored = json.loads(cache.read_text())
    cache.write_text(json.dumps({**stored, "version": "antiga"}))
    redone = " ".join(r.resolved.text for r in collect(doc, ocr_cache=cache).regions)
    assert "2.♘f3" in redone
    labels = json.loads(cache.read_text())["labels"]
    assert "♘" in labels.values()


@pytest.mark.parametrize("read, fixed", [
    ("23.♖el", "23.♖e1"), ("16.♖fd]", "16.♖fd1"), ("27...♕xf4t", "27...♕xf4†"), ("4l.fxg5t", "41.fxg5†"),
    ("18...♕£3!", "18...♕f3!"), ("7.¢4", "7.g4"), ("♘x£7", "♘xf7"), ("£30", "£30"),
    ("31...♔d52!", "31...♔d5?!"), ("27.♖h5!2", "27.♖h5!?"), ("(30.h4!2)", "(30.h4!?)"), ("33.♖ef12?", "33.♖ef1??"),
    ("37.f42!", "37.f4?!"), ("24.♕xe4t!", "24.♕xe4†!"), ("31.e4t", "31.e4†"), ("♖dlt", "♖d1†"), ("c6t", "c6†"), ("exf4t.", "exf4†."),
    # prosa e lances já certos ficam como estão
    ("et", "et"), ("al", "al"), ("at", "at"), ("a1", "a1"), ("Bel", "Bel"), ("8.♖e1+", "8.♖e1+"), ("48.gxh4", "48.gxh4"),
])
def test_ocr_misreads_with_a_single_reading_are_fixed(read, fixed):
    assert ocr.fix_move_glyphs(read) == (fixed, read != fixed)


@needs_tesseract
def test_project_creation_keeps_ocr_files_inside_the_project(tmp_path):
    """O OCR da criação fica no projeto: nada na pasta comum que outro projeto possa herdar."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    page = pymupdf.open(stream=syn.build_page("fan_unicode").pdf_bytes, filetype="pdf")[0]
    pdf = tmp_path / "digitalizado.pdf"
    _scanned(page, noise=4).save(pdf)
    root = tmp_path / "storage"
    subprocess.run([sys.executable, "-m", "scripts.project", "create", "scan", "Digitalizado", str(pdf)], check=True,
                   cwd=Path(__file__).resolve().parents[1], env={**os.environ, "CHESSBOOK_STORAGE": str(root)},
                   capture_output=True)
    assert {p.name for p in (root / "scan").iterdir()} >= {"ocr.json", "ocr-passe1.json.gz"}
    assert sorted(p.name for p in root.iterdir() if p.is_file()) == []


def test_text_line_never_reaches_into_the_diagram_coordinates():
    """O Tesseract juntou a fileira "a b c ... h" com a linha de baixo (uma palavra mal lida pega as duas):
    a caixa da linha fica só com a linha de texto, fora da área do diagrama."""
    area = pymupdf.Rect(600, 430, 1470, 1108)
    words = [(219, 1143, 350, 1177), (805, 1070, 917, 1186), (935, 1156, 1032, 1178), (1749, 1155, 1841, 1186)]
    assert ocr._clear_of(ocr._union(words), [area]) == (219, 1143, 1841, 1186)
    # linha acima do diagrama que desce sobre ele
    assert ocr._clear_of((100, 400, 900, 440), [area])[3] == 429


def _hocr_lines(lines: list[list[tuple[str, tuple[int, int, int, int]]]]) -> str:
    """hOCR mínimo: cada palavra com uma caixa por caractere, como o Tesseract devolve."""
    out = []
    for words in lines:
        x0, y0 = min(b[0] for _, b in words), min(b[1] for _, b in words)
        x1, y1 = max(b[2] for _, b in words), max(b[3] for _, b in words)
        spans = []
        for text, (a, b, c, d) in words:
            step = (c - a) // len(text)
            chars = "".join(f"<span class='ocrx_cinfo' title='x_bboxes {a + k * step} {b} {a + (k + 1) * step} {d};"
                            f" x_conf 95'>{ch}</span>" for k, ch in enumerate(text))
            spans.append(f"<span class='ocrx_word' title='bbox {a} {b} {c} {d}; x_wconf 92'>{chars}</span>")
        out.append(f"<span class='ocr_line' title=\"bbox {x0} {y0} {x1} {y1}; x_size 25\">{' '.join(spans)}</span>")
    return ("<html><body><div class='ocr_page'><div class='ocr_carea' title=\"bbox 0 0 2000 2000\">"
            "<p class='ocr_par' title=\"bbox 0 0 2000 2000\">" + "".join(out) + "</p></div></div></body></html>")


def test_coordinate_row_read_as_one_word_is_not_text():
    """ "b c d e" lido como "bede" abaixo do tabuleiro: é coordenada, não texto; uma linha de verdade fica."""
    hocr = _hocr_lines([[("bede", (1290, 700, 1390, 725)), ("fgih", (1400, 700, 1460, 725)), ("@h", (1465, 700, 1490, 725))],
                        [("Black", (1100, 715, 1250, 740)), ("had", (1270, 715, 1350, 740)),
                         ("bad", (1370, 715, 1450, 740))]])
    board = (1200 * 72 / 300, 190 * 72 / 300, 1700 * 72 / 300, 680 * 72 / 300)
    blocks = ocr._text_blocks(hocr, [board], 300 / 72)
    assert [w.text for b in blocks for ln in b.lines for w in ln.words] == ["Black", "had", "bad"]
    # fim de linha da coluna vizinha dentro da faixa do diagrama fica; a marca "W" isolada, não
    hocr = _hocr_lines([[("White", (800, 300, 950, 325)), ("can", (970, 300, 1060, 325)),
                         ("W", (1110, 300, 1140, 325))]])
    blocks = ocr._text_blocks(hocr, [board], 300 / 72)
    assert [w.text for b in blocks for ln in b.lines for w in ln.words] == ["White", "can"]


def test_block_across_a_board_is_split_and_exercise_number_is_a_mark():
    """O número do exercício "(3)" à esquerda do tabuleiro (encostado na faixa) e a legenda abaixo,
    juntos num bloco pelo Tesseract: o número sai como marca e o bloco nunca cobre o tabuleiro."""
    board = (330 * 72 / 300, 280 * 72 / 300, 940 * 72 / 300, 890 * 72 / 300)
    hocr = _hocr_lines([[("(3)", (160, 280, 245, 390)), ("ag", (280, 350, 360, 420))],
                        [("Macieja", (290, 980, 450, 1020)), ("Stockholm", (470, 980, 700, 1020))],
                        [("White", (290, 140, 420, 180)), ("to", (440, 140, 480, 180)), ("play", (500, 140, 600, 180))]])
    blocks = ocr._text_blocks(hocr, [board], 300 / 72)
    words = sorted([w.text for ln in b.lines for w in ln.words] for b in blocks)
    assert words == [["Macieja", "Stockholm"], ["White", "to", "play"]]
    board_px = pymupdf.Rect(*(v * 300 / 72 for v in board))
    assert not any(pymupdf.Rect(*b.bbox).intersects(board_px) for b in blocks)


@needs_tesseract
def test_symbols_after_moves_are_read_by_their_drawing(tmp_path):
    """†, ±, ?! e !? decididos pelo desenho (o Tesseract lê "+" nos dois primeiros); o ⩲ sem sugestão
    fica com aviso até a confirmação, que reescreve os lances sem refazer o OCR e vale num OCR futuro."""
    import json

    doc = pymupdf.open()
    page = doc.new_page(width=420, height=300)
    page.insert_font(fontname="fs", fontfile="/usr/share/fonts/truetype/freefont/FreeSerif.ttf")
    for i, t in enumerate(["After 1.e4† 2.d4† 3.c4† the game is level.", "But 4.b4± 5.a4± 6.h4± gives White the edge.",
                           "And 7.g4⩲ 8.f4⩲ 9.e5⩲ is less clear; 10.d5?! 11.c5?! 12.b5!? too."]):
        page.insert_text((20, 60 + i * 30), t, fontsize=12, fontname="fs")
    pdf = tmp_path / "s.pdf"
    rasterize(page, 300, 2, np.random.default_rng(1)).save(pdf)
    cache = tmp_path / "ocr.json"
    text = " ".join(r.resolved.text for r in collect(pymupdf.open(pdf), ocr_cache=cache, ocr_mode="on").regions)
    for move in ("1.e4†", "3.c4†", "4.b4±", "6.h4±", "10.d5?!", "12.b5!?"):
        assert move in text
    stored = json.loads(cache.read_text())
    entry = next(e for p in stored["pages"].values() for e in p["suffixes"] if e[3] == "8.f4")
    plus_eq = next(g for g in stored["symbol_groups"] if g["id"] == entry[6][0])
    if not plus_eq["auto"]:  # sem sugestão (o OCR não confirmou o desenho): fica com aviso até a confirmação
        warnings = [w for p in stored["pages"].values() for b in p["blocks"] for w in b["ocr_warnings"]]
        assert any(w.startswith("ocr_simbolo_incerto: '8.f4") for w in warnings)

    with pytest.raises(ValueError):
        ocr.relabel_symbols(cache, {str(plus_eq["id"]): "x"})
    ocr.relabel_symbols(cache, {str(plus_eq["id"]): "⩲"})
    text = " ".join(r.resolved.text for r in collect(pymupdf.open(pdf), ocr_cache=cache, ocr_mode="on").regions)
    assert "8.f4⩲" in text and "9.e5⩲" in text and "1.e4†" in text
    stored = json.loads(cache.read_text())
    assert not any(w.startswith("ocr_simbolo_incerto") for p in stored["pages"].values()
                   for b in p["blocks"] for w in b["ocr_warnings"])
    # OCR refeito (programa atualizado): a decisão vem pelo desenho
    cache.write_text(json.dumps({**stored, "version": "antiga"}))
    text = " ".join(r.resolved.text for r in collect(pymupdf.open(pdf), ocr_cache=cache, ocr_mode="on").regions)
    assert "9.e5⩲" in text


def test_figurine_touching_the_capture_x_is_cut_at_the_figurine():
    """"♕xf6" com a dama encostada no "x": o trecho de tinta leva os dois; o molde da dama (da própria
    página) corta na largura dela (senão o grupo vira "♕xf6" e pintar a letra apagava a captura)."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(syn.DEJAVU), 60)

    def draw(text_after: str, overlap: int) -> tuple[np.ndarray, int]:
        img = Image.new("L", (400, 100), 255)
        d = ImageDraw.Draw(img)
        d.text((10, 10), "♕", font=font, fill=0)
        queen_end = 10 + int(d.textlength("♕", font=font))
        if text_after:
            d.text((queen_end - overlap, 10), text_after, font=font, fill=0)
        return np.asarray(img), queen_end

    alone, _ = draw("", 0)
    cols = np.flatnonzero((alone < 128).any(axis=0))
    template = ocr._normalize(alone[:, cols[0]:cols[-1] + 1])
    queen_ink_end = int(cols[-1]) + 1
    gray, _ = draw("xf6", 10)  # encostado
    cols = np.flatnonzero((gray < 128).any(axis=0))
    line = ocr.OcrLine((0, 0, 400, 100), 60.0, [])
    word = ocr.OcrWord("Wxf6", (int(cols[0]), 0, int(cols[-1]) + 1, 100), 90.0, [])
    strip, _end = ocr._piece_crop(gray, word, line, 0)
    assert ocr.is_wide(strip)
    width, index, sim = ocr.fit_template(strip, [template])
    assert index == 0 and sim > 0.9
    assert abs((int(cols[0]) + width) - queen_ink_end) <= 4


def test_not_a_piece_group_is_never_painted_as_a_king():
    """Grupo marcado "não é peça" serve para recusar o desenho, não como molde nem como figurina: antes, a
    letra pintada era "K" (``"♔♕♖♗♘".index("")`` é 0) e a figurina sumia do lance ("17.♗xh7†" → "17. K7+")."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(syn.DEJAVU), 60)
    img = Image.new("L", (400, 100), 255)
    ImageDraw.Draw(img).text((10, 10), "♕", font=font, fill=0)
    gray = np.asarray(img)
    cols = np.flatnonzero((gray < 128).any(axis=0))
    vec = ocr._normalize(gray[:, cols[0]:cols[-1] + 1])
    line = ocr.OcrLine((0, 0, 400, 100), 60.0, [])
    word = ocr.OcrWord("Wf6", (int(cols[0]), 0, int(cols[-1]) + 60, 100), 90.0, [])
    negative = ocr.confirmed_prototypes([{"char": "", "count": 9, "vec": ocr._vec_b64(vec)}])
    assert negative and negative[0].char == ""
    assert ocr._figurine_in_word(gray, word, line, 0, negative, []) is None
    queen = ocr.confirmed_prototypes([{"char": "♕", "count": 9, "vec": ocr._vec_b64(vec)}])
    fig = ocr._figurine_in_word(gray, word, line, 0, queen, [queen[0].vec])
    assert fig is not None and fig.char == "♕"


def test_lone_digit_before_a_square_is_the_figurine_not_the_move_number():
    assert ocr._move_prefix("2a7!") == 0  # "♗a7!" com o bispo lido como "2"
    assert ocr._move_prefix("17.2xh7+") == 3
    assert ocr._move_prefix("30...♖xf5") == 5
    assert ocr._move_prefix("17") == 2


def test_painted_letter_is_restored_even_when_its_box_misses_the_center():
    """O Tesseract às vezes dá à letra pintada uma caixa estreita, à direita do centro do desenho."""
    n = ocr.OcrChar("N", (1762, 1121, 1774, 1162), 90.0)
    rest = [ocr.OcrChar(c, (1780 + 20 * i, 1121, 1798 + 20 * i, 1162), 90.0) for i, c in enumerate("h6t")]
    word = ocr.OcrWord("Nh6t", (1762, 1121, 1844, 1162), 90.0, [n, *rest])
    number = ocr.OcrWord("30.", (1688, 1129, 1738, 1160), 90.0, [])
    block = ocr.OcrBlock((1688, 1120, 1844, 1170), [ocr.OcrLine((1688, 1120, 1844, 1170), 42.0, [number, word])])
    fig = ocr._Figurine("♘", 0.94, 0.7, (1742, 1120, 1774, 1170), (1684, 1120, 1844, 1163), "30.")
    assert ocr._restore_figurines([block], [fig]) == []
    assert any(w.text.startswith("♘h6") for w in block.lines[0].words)


def test_rank_and_file_read_as_letters_after_a_figurine():
    assert ocr.fix_move_glyphs("♔gs")[0] == "♔g8"
    assert ocr.fix_move_glyphs("24.♘F7+?")[0] == "24.♘f7+?"
    assert ocr.fix_move_glyphs("♖bGt")[0] == "♖b6†"
    assert ocr.fix_move_glyphs("Gs")[0] == "Gs" and ocr.fix_move_glyphs("fs")[0] == "fs"


def test_discarded_symbol_disappears_and_not_a_symbol_keeps_the_ocr_reading():
    from app.extraction import symbols

    assert symbols.VALID_LABEL.match(symbols.DISCARD) and symbols.VALID_LABEL.match("?")
    page = {"blocks": [{"lines": [{"spans": [{"text": "36.♖e5!? "}]}], "ocr_warnings": []}],
            "suffixes": [[0, 0, 0, "36.♖e5", "", "5!?", [1, 2, 3], ["", "!", "?"]]]}
    symbols.apply_to_pages({"1": page}, {"1": symbols.DISCARD, "2": "!", "3": "?"})
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "36.♖e5!? "
    symbols.apply_to_pages({"1": page}, {"1": "", "2": "!", "3": ""})  # "" = fica o que o OCR leu
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "36.♖e5!? "

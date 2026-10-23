"""Extração de PDFs sintéticos com FAN em três codificações, e OCR.

Também registra, como testes de caracterização, comportamentos de bibliotecas
que o sistema precisa compensar (ver docs/research/03-spike-pdf.md).
"""

import shutil
import subprocess

import pymupdf
import pytest

from app.chess.notation import Context, Convention, MoveStatus, analyze_region
from app.extraction.glyph_probe import probe_page, propose_glyph_map
from tests.fixtures import synthetic as syn


def page_text(mode: str) -> tuple[pymupdf.Document, str]:
    doc = pymupdf.open(stream=syn.build_page(mode).pdf_bytes, filetype="pdf")
    return doc, doc[0].get_text()


def test_unicode_fan_extracts_as_figurines():
    _, text = page_text("fan_unicode")
    assert "2.♘f3 ♘c6 3.♗b5" in text


def test_letter_figurine_font_extracts_as_letters():
    """A página mostra ♘, mas a camada de texto diz N."""
    _, text = page_text("fan_letter_font")
    assert "2.Nf3 Nc6 3.Bb5" in text and "♘f3" not in text


def test_pua_figurine_font_extracts_private_codepoints():
    _, text = page_text("fan_pua_font")
    assert "2.\ue004f3" in text


@pytest.mark.parametrize("mode", ["fan_letter_font", "fan_pua_font"])
def test_glyph_probe_proposes_mapping_for_figurine_fonts(mode):
    doc, _ = page_text(mode)
    page = syn.build_page(mode)
    obs = probe_page(doc[0], exclude=[pymupdf.Rect(page.regions["diagram"].rect)])
    proposal = propose_glyph_map(obs)
    fonts = [f for f in proposal if "ChessFigurineTest" in f]
    assert len(fonts) == 1
    expected = {"N": "♘", "B": "♗"} if mode == "fan_letter_font" else {"\ue004": "♘", "\ue003": "♗"}
    assert proposal[fonts[0]] == expected


def test_glyph_probe_does_not_flag_ordinary_letters():
    doc, _ = page_text("fan_letter_font")
    obs = probe_page(doc[0], exclude=[pymupdf.Rect(syn.build_page("fan_letter_font").regions["diagram"].rect)])
    body = [o for o in obs if "DejaVu" in o.font]
    assert body and all(not o.looks_like_figurine for o in body)


def test_extracted_paragraph_validates_after_glyph_mapping():
    doc, _ = page_text("fan_pua_font")
    block = next(b for b in doc[0].get_text("blocks") if b[4].startswith("1.e4"))[4]
    mapping = {"\ue004": "♘", "\ue003": "♗"}  # proposta confirmada pelo usuário
    text = "".join(mapping.get(c, c) for c in block).replace("\n", " ")
    r = analyze_region(text, context=Context.standard(), convention=Convention.FIGURINE)
    assert [m.status for m in r.moves][:6] == [MoveStatus.VALIDATED] * 6


def test_characterization_insert_htmlbox_writes_nothing_when_text_does_not_fit():
    """PyMuPDF não escreve o texto se ele não couber: a perda é silenciosa.

    O módulo de layout deve sempre verificar o valor de retorno e, depois de
    renderizar, procurar o texto de cada bloco na página gerada.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    spare, _ = page.insert_htmlbox(pymupdf.Rect(50, 50, 120, 60), "texto longo demais " * 10, scale_low=1)
    assert spare < 0
    assert page.get_text().strip() == ""


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract não instalado")
def test_characterization_tesseract_corrupts_fan(tmp_path):
    """O OCR genérico não reconhece figurinas e pode transformar lances em números."""
    scanned = syn.build_scanned(syn.build_page("fan_unicode"), dpi=300)
    img = tmp_path / "p.png"
    pymupdf.open(stream=scanned, filetype="pdf")[0].get_pixmap(dpi=300).save(img)
    out = subprocess.run(["tesseract", str(img), "-", "-l", "eng", "--psm", "4"],
                         capture_output=True, text=True, check=True, timeout=120).stdout
    line = next(ln for ln in out.splitlines() if ln.startswith("1."))
    assert "♘" not in line
    r = analyze_region(line, context=Context.standard(), convention=Convention.FIGURINE)
    # O que importa: nenhum lance após o trecho corrompido é dado como validado.
    validated = [m.atom.text for m in r.moves if m.status == MoveStatus.VALIDATED]
    assert validated == ["e4", "e5"]
    assert r.needs_review


def test_glyph_probe_uses_every_installed_font_with_figurines():
    from app.extraction.glyph_probe import reference_fonts

    fonts = reference_fonts()
    assert len(fonts) >= 2 and any("DejaVuSans" in f.name for f in fonts)


def test_glyph_probe_margin_is_against_another_piece():
    """♗ e ♝ têm a mesma silhueta: o segundo colocado tem de ser outra peça."""
    from app.extraction.glyph_probe import _classify, _piece_of, _render_text

    vec = _render_text("♗", fontfile="/usr/share/fonts/truetype/freefont/FreeSerif.ttf")
    (s1, best), (s2, runner) = _classify(vec)
    assert _piece_of(best) == "B" and _piece_of(runner) != "B" and s1 - s2 > 0.1

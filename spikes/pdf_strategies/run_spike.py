"""Spike da Fase 1: compara duas estratégias de reconstrução de PDF.

Estratégia A — edição do PDF original: remove (redação) apenas os blocos de
prosa e escreve a tradução nas mesmas regiões; diagramas, imagens e vetores
permanecem intactos.

Estratégia B — reconstrução a partir de uma representação intermediária:
gera HTML/CSS a partir dos blocos extraídos e renderiza com WeasyPrint; o
diagrama é reaproveitado como SVG vetorial recortado do original.

Também executa OCR (Tesseract) sobre a versão digitalizada da página para
observar o que acontece com os símbolos figurativos.

Uso (a partir de chessbook-translator/backend):
    .venv/bin/python ../spikes/pdf_strategies/run_spike.py <diretório-de-saída>

Usa somente páginas sintéticas geradas por tests/fixtures/synthetic.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pymupdf

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

from tests.fixtures import synthetic as syn

MOVE_RE = re.compile(r"(?:\d+\.(?:\.\.)?)?(?:[♔♕♖♗♘KQRBN]?[a-h]?x?[a-h][1-8]|0-0(?:-0)?|O-O(?:-O)?)")
ENGLISH_MARKERS = ["main line", "keeps the tension", "knight on", "Diagram 7", "See also"]


def pixels(page: pymupdf.Page, clip: pymupdf.Rect, dpi: int = 100) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(int)


def diagram_bbox(page: pymupdf.Page) -> pymupdf.Rect | None:
    """Localiza o tabuleiro pela cor das casas escuras (usado na estratégia B)."""
    rect = pymupdf.Rect()
    for d in page.get_drawings():
        fill = d.get("fill")
        if fill and all(abs(a - b) < 0.02 for a, b in zip(fill, (0.62, 0.55, 0.45))):
            rect |= d["rect"]
    return None if rect.is_empty else rect


def moves_in(text: str) -> list[str]:
    return MOVE_RE.findall(text.replace("\n", " "))


def expected_pt_text(mode: str) -> dict[str, str]:
    # Na saída, a notação figurativa é sempre escrita com Unicode (DejaVu Sans),
    # mesmo quando o original usava uma fonte figurina proprietária.
    m = "fan_unicode"
    return {
        "title": syn.fill(syn.TITLE_PT, m),
        "para1": syn.fill(syn.PARA1_PT, m),
        "caption": syn.fill(syn.CAPTION_PT, m),
        "para2": syn.fill(syn.PARA2_PT, m),
        "footnote": syn.fill(syn.FOOTNOTE_PT, m),
        "pageno": "47",
    }


def block_role(block_rect: pymupdf.Rect, regions: dict[str, syn.Region]) -> str:
    """Associa um bloco extraído à região conhecida de maior interseção."""
    best, best_area = "unknown", 0.0
    for name, reg in regions.items():
        inter = pymupdf.Rect(block_rect) & pymupdf.Rect(reg.rect)
        if not inter.is_empty and inter.get_area() > best_area:
            best, best_area = name, inter.get_area()
    return best


CSS_BODY = (
    f"@font-face {{font-family: body; src: url({syn.DEJAVU.name});}}"
    f"@font-face {{font-family: bold; src: url({syn.DEJAVU_BOLD.name});}}"
)


def free_space_rect(rect: pymupdf.Rect, others: list[pymupdf.Rect], page_rect: pymupdf.Rect, gap: float = 4) -> pymupdf.Rect:
    """Expande o bloco para baixo até o próximo elemento que se sobreponha horizontalmente."""
    limit = page_rect.y1 - 36  # margem inferior mínima
    for o in others:
        if o.y0 >= rect.y1 - 0.5 and o.x0 < rect.x1 and o.x1 > rect.x0:
            limit = min(limit, o.y0 - gap)
    return pymupdf.Rect(rect.x0, rect.y0, rect.x1, max(rect.y1, limit))


def strategy_a(
    original: bytes, regions: dict[str, syn.Region], pt: dict[str, str], expand: bool
) -> tuple[bytes, dict]:
    """Edição do original. ``expand=False`` usa a caixa exata do bloco extraído;
    ``expand=True`` permite ocupar o espaço livre abaixo do bloco."""
    doc = pymupdf.open(stream=original, filetype="pdf")
    page = doc[0]
    diag = pymupdf.Rect(regions["diagram"].rect)
    report: dict = {"blocks": {}}
    blocks = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
    targets: dict[str, pymupdf.Rect] = {}
    for b in blocks:
        r = pymupdf.Rect(b["bbox"])
        if diag.contains(r) or (r & diag).get_area() > 0.5 * r.get_area():
            continue  # texto pertence ao diagrama: nunca apagar
        role = block_role(r, regions)
        targets[role] = targets.get(role, pymupdf.Rect()) | r
        page.add_redact_annot(r)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )
    archive = pymupdf.Archive()
    archive.add(syn.DEJAVU.read_bytes(), syn.DEJAVU.name)
    archive.add(syn.DEJAVU_BOLD.read_bytes(), syn.DEJAVU_BOLD.name)
    sizes = {"title": 14, "para1": 10, "caption": 9, "para2": 10, "footnote": 8, "pageno": 9}
    obstacles = list(targets.values()) + [diag]
    for role, rect in targets.items():
        area = rect
        if expand:
            area = free_space_rect(rect, [o for o in obstacles if o != rect], page.rect)
        # Redução tipográfica limitada a 15 %. Acima disso o bloco é marcado
        # como "não coube": nada é cortado nem espremido silenciosamente.
        css = CSS_BODY + (
            f"body {{font-family: {'bold' if role == 'title' else 'body'}; "
            f"font-size: {sizes.get(role, 10)}pt; line-height: 1.3;}}"
        )
        spare, scale = page.insert_htmlbox(area, pt[role], css=css, archive=archive, scale_low=0.85)
        report["blocks"][role] = {
            "fits": spare >= 0,
            "scale": round(scale, 3),
            "box_height_pt": round(area.height, 1),
            "orig_height_pt": round(rect.height, 1),
        }
    doc.subset_fonts()
    return doc.tobytes(garbage=3, deflate=True), report


def strategy_b(original: bytes, regions: dict[str, syn.Region], pt: dict[str, str], workdir: Path) -> tuple[bytes, dict]:
    import weasyprint

    src = pymupdf.open(stream=original, filetype="pdf")
    diag = pymupdf.Rect(regions["diagram"].rect)
    # Recorta o diagrama como PDF vetorial e converte para SVG com texto em curvas.
    one = pymupdf.open()
    p = one.new_page(width=diag.width, height=diag.height)
    p.show_pdf_page(p.rect, src, 0, clip=diag)
    svg = p.get_svg_image(text_as_path=True)
    svg_path = workdir / "diagram.svg"
    svg_path.write_text(svg, encoding="utf-8")
    w, h = src[0].rect.width, src[0].rect.height
    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
      @font-face {{font-family: body; src: url('{syn.DEJAVU.as_uri()}');}}
      @font-face {{font-family: bold; src: url('{syn.DEJAVU_BOLD.as_uri()}');}}
      @page {{ size: {w}pt {h}pt; margin: 40pt 40pt 30pt 40pt;
              @bottom-center {{ content: "{pt['pageno']}"; font: 9pt body; }} }}
      body {{ font-family: body; font-size: 10pt; line-height: 1.3; margin: 0; }}
      h1 {{ font-family: bold; font-size: 14pt; font-weight: normal; margin: 0 0 10pt; }}
      figure {{ margin: 10pt auto; width: {diag.width}pt; break-inside: avoid; }}
      figure img {{ width: {diag.width}pt; height: {diag.height}pt; display: block; }}
      figcaption {{ font-size: 9pt; margin-top: 4pt; }}
      .footnote {{ font-size: 8pt; position: absolute; bottom: 0; }}
    </style></head><body>
      <h1>{pt['title']}</h1>
      <p>{pt['para1']}</p>
      <figure><img src="{svg_path.as_uri()}" alt="Diagrama 7"><figcaption>{pt['caption']}</figcaption></figure>
      <p>{pt['para2']}</p>
      <p class="footnote">{pt['footnote']}</p>
    </body></html>"""
    pdf = weasyprint.HTML(string=html, base_url=str(workdir)).write_pdf()
    out = pymupdf.open(stream=pdf, filetype="pdf")
    return pdf, {"page_count": out.page_count}


def evaluate(name: str, original: bytes, output: bytes, regions, pt: dict[str, str], outdir: Path) -> dict:
    src = pymupdf.open(stream=original, filetype="pdf")[0]
    out_doc = pymupdf.open(stream=output, filetype="pdf")
    out = out_doc[0]
    diag_src = pymupdf.Rect(regions["diagram"].rect)
    diag_out = diagram_bbox(out) or diag_src
    a, b = pixels(src, diag_src), pixels(out, diag_out)
    hh, ww = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    diff = np.abs(a[:hh, :ww] - b[:hh, :ww])
    # Comparação tolerante a deslocamento subpixel: média em blocos de 4x4 px.
    def pool(x: np.ndarray) -> np.ndarray:
        h4, w4 = x.shape[0] // 4 * 4, x.shape[1] // 4 * 4
        return x[:h4, :w4].reshape(h4 // 4, 4, w4 // 4, 4).mean(axis=(1, 3))
    pooled = np.abs(pool(a[:hh, :ww]) - pool(b[:hh, :ww]))
    text_out = "".join(p.get_text() for p in out_doc)
    expected_moves = [m for k in ("para1", "para2") for m in moves_in(pt[k])]
    got_moves = moves_in(text_out)
    missing = [m for m in expected_moves if m not in got_moves]
    pix = out.get_pixmap(dpi=100)
    pix.save(outdir / f"{name}.png")
    return {
        "pages": out_doc.page_count,
        "diagram_bbox_out": [round(v, 1) for v in diag_out],
        "diagram_size_delta_pt": round(abs(diag_out.width - diag_src.width) + abs(diag_out.height - diag_src.height), 2),
        "diagram_mean_abs_pixel_diff": round(float(diff.mean()), 3),
        "diagram_pixels_changed_pct": round(float((diff > 32).mean() * 100), 3),
        "diagram_pooled4_changed_pct": round(float((pooled > 32).mean() * 100), 3),
        "moves_expected": len(expected_moves),
        "moves_missing_in_output_text": missing,
        "english_residue": [m for m in ENGLISH_MARKERS if m in text_out],
        # Bloco ausente = o início do texto traduzido não aparece na página gerada.
        "blocks_missing_in_output": [k for k, v in pt.items() if " ".join(v.split()[:3]) not in " ".join(text_out.split())],
        "diagram_glyphs_remain_as_text": sum(ch in text_out for ch in "♜♞♝♛♚♟") > 0,
    }


def ocr_probe(original: bytes, outdir: Path) -> dict:
    page = syn.SyntheticPage(original, {}, "")
    scanned = syn.build_scanned(page, dpi=300)
    pix = pymupdf.open(stream=scanned, filetype="pdf")[0].get_pixmap(dpi=300)
    img = outdir / "scanned.png"
    pix.save(img)
    try:
        txt = subprocess.run(
            ["tesseract", str(img), "-", "-l", "eng", "--psm", "4"],
            capture_output=True, text=True, timeout=120, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": str(exc)}
    first = next((ln for ln in txt.splitlines() if ln.startswith("1.")), "")
    return {"available": True, "move_line_ocr": first, "expected": syn.fill(syn.PARA1_EN, "fan_unicode")[:60]}


def main(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    results: dict = {}
    for mode in ("fan_unicode", "fan_letter_font"):
        page = syn.build_page(mode)
        (outdir / f"{mode}_original.pdf").write_bytes(page.pdf_bytes)
        pymupdf.open(stream=page.pdf_bytes, filetype="pdf")[0].get_pixmap(dpi=100).save(outdir / f"{mode}_original.png")
        pt = expected_pt_text(mode)
        a_pdf, a_rep = strategy_a(page.pdf_bytes, page.regions, pt, expand=False)
        (outdir / f"{mode}_A_strict.pdf").write_bytes(a_pdf)
        ax_pdf, ax_rep = strategy_a(page.pdf_bytes, page.regions, pt, expand=True)
        (outdir / f"{mode}_A_expand.pdf").write_bytes(ax_pdf)
        b_pdf, b_rep = strategy_b(page.pdf_bytes, page.regions, pt, outdir)
        (outdir / f"{mode}_B.pdf").write_bytes(b_pdf)
        results[mode] = {
            "A_strict_bbox": {**a_rep, **evaluate(f"{mode}_A_strict", page.pdf_bytes, a_pdf, page.regions, pt, outdir)},
            "A_expand_free_space": {**ax_rep, **evaluate(f"{mode}_A_expand", page.pdf_bytes, ax_pdf, page.regions, pt, outdir)},
            "B_rebuild": {**b_rep, **evaluate(f"{mode}_B", page.pdf_bytes, b_pdf, page.regions, pt, outdir)},
        }
    results["ocr_fan_unicode"] = ocr_probe(syn.build_page("fan_unicode").pdf_bytes, outdir)
    (outdir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "spike-out"))

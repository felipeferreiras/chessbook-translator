"""PDF sintético com uma fonte Type 3 de figurinas (glifos desenhados por procedimento).

Livros antigos e alguns gerados por TeX usam Type 3: cada glifo é um pequeno
programa de desenho, sem arquivo de fonte. Aqui os códigos de "N" e "B"
desenham um triângulo e um losango; o texto da página é "1.e4 e5 2.Nf3 Nc6
3.Bb5" com as peças na fonte Type 3 e o resto em Helvetica.
"""

from __future__ import annotations

import pymupdf

TEXT = [("helv", "1.e4 e5 2."), ("T3", "N"), ("helv", "f3 "), ("T3", "N"), ("helv", "c6 3."), ("T3", "B"),
        ("helv", "b5")]

_GLYPHS = {
    "knight": b"700 0 0 0 700 700 d1 50 0 m 650 0 l 350 700 l f",
    "bishop": b"700 0 0 0 700 700 d1 350 0 m 650 350 l 350 700 l 50 350 l f",
}


def _tounicode(mapping: dict[int, str]) -> bytes:
    lines = [f"<{code:02X}> <{ord(ch):04X}>" for code, ch in sorted(mapping.items())]
    return (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "/CMapName /T3Figurines def /CMapType 2 def\n"
        "1 begincodespacerange <00> <FF> endcodespacerange\n"
        f"{len(lines)} beginbfchar\n" + "\n".join(lines) + "\nendbfchar\n"
        "endcmap CMapName currentdict /CMap defineresource pop end end"
    ).encode()


def build(tounicode: dict[int, str] | None = None) -> bytes:
    """``tounicode``: {código: caractere}; ``None`` = sem ToUnicode (o texto sai da codificação)."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=120)
    page.insert_font(fontname="helv")
    procs = {}
    for name, stream in _GLYPHS.items():
        x = doc.get_new_xref()
        doc.update_object(x, "<<>>")
        doc.update_stream(x, stream)
        procs[name] = x
    font = doc.get_new_xref()
    widths = " ".join("700" if code in (66, 78) else "0" for code in range(66, 79))
    extra = ""
    if tounicode is not None:
        tu = doc.get_new_xref()
        doc.update_object(tu, "<<>>")
        doc.update_stream(tu, _tounicode(tounicode))
        extra = f"/ToUnicode {tu} 0 R"
    doc.update_object(font, (
        "<< /Type /Font /Subtype /Type3 /Name /T3 /FontBBox [0 0 700 700] "
        "/FontMatrix [0.001 0 0 0.001 0 0] "
        f"/CharProcs << /knight {procs['knight']} 0 R /bishop {procs['bishop']} 0 R >> "
        "/Encoding << /Type /Encoding /Differences [66 /bishop 78 /knight] >> "
        f"/FirstChar 66 /LastChar 78 /Widths [{widths}] /Resources << >> {extra} >>"
    ))
    _add_font_resource(doc, page.xref, "T3", font)
    ops = ["BT", "1 0 0 1 20 60 Tm"]
    for fontname, text in TEXT:
        ops.append(f"/{fontname} 14 Tf ({text}) Tj")
    ops.append("ET")
    content = doc.get_new_xref()
    doc.update_object(content, "<<>>")
    doc.update_stream(content, "\n".join(ops).encode())
    doc.xref_set_key(page.xref, "Contents", f"{content} 0 R")
    return doc.tobytes()


def _add_font_resource(doc: pymupdf.Document, page_xref: int, name: str, font_xref: int) -> None:
    """Registra a fonte nos recursos da página, seguindo referências indiretas."""
    owner, path = page_xref, "Resources/Font"
    kind, value = doc.xref_get_key(page_xref, "Resources")
    if kind == "xref":
        owner, path = int(value.split()[0]), "Font"
        kind, value = doc.xref_get_key(owner, "Font")
        if kind == "xref":
            owner, path = int(value.split()[0]), ""
    doc.xref_set_key(owner, f"{path}/{name}" if path else name, f"{font_xref} 0 R")

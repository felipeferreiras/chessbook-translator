"""Núcleo de notação: análise léxica, convenção, validação e saída."""

from .alphabets import Convention
from .convention import ConventionReport, detect_convention
from .lexer import Atom, AtomKind, LexResult, lex
from .render import ConversionPolicy, OutputNotation, RenderResult, render_region
from .validate import Context, ContextSource, MoveAnalysis, MoveStatus, RegionAnalysis, analyze_region

__all__ = [
    "Atom", "AtomKind", "Context", "ContextSource", "Convention", "ConventionReport",
    "ConversionPolicy", "LexResult", "MoveAnalysis", "MoveStatus", "OutputNotation",
    "RegionAnalysis", "RenderResult", "analyze_region", "detect_convention", "lex", "render_region",
]

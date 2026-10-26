"""Confere se o ambiente está pronto: programas, fontes, interface, armazenamento e configuração.

Uso (a partir de backend/):
    .venv/bin/python -m scripts.doctor [--rede]

``--rede`` também testa o acesso à Pollinations (sem enviar texto do livro).
Nunca mostra a chave: só diz se ela existe. Sai com código 1 se algo
obrigatório faltar.
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OK, WARN, FAIL = "ok", "aviso", "ERRO"


def checks(network: bool) -> list[tuple[str, str, str]]:
    from app.translation.config import load_env_file

    load_env_file(ROOT / ".env")
    out: list[tuple[str, str, str]] = []

    def add(state: str, what: str, detail: str = "") -> None:
        out.append((state, what, detail))

    v = sys.version_info
    add(OK if v >= (3, 12) else FAIL, "Python 3.12 ou mais novo", f"{v.major}.{v.minor}.{v.micro}")
    for mod in ("pymupdf", "chess", "fontTools", "numpy", "PIL", "fastapi", "uvicorn", "openai", "multipart"):
        try:
            importlib.import_module(mod)
            add(OK, f"pacote {mod}")
        except ImportError as exc:
            add(FAIL, f"pacote {mod}", f"{exc} — rode ./instalar.sh")

    tess = shutil.which("tesseract")
    if tess:
        langs = subprocess.run([tess, "--list-langs"], capture_output=True, text=True, check=False).stdout
        add(OK if "eng" in langs.split() else WARN, "Tesseract (OCR de livros digitalizados)",
            "inglês instalado" if "eng" in langs.split() else "falta o idioma inglês (tesseract-ocr-eng)")
    else:
        add(WARN, "Tesseract (OCR de livros digitalizados)", "ausente: livros digitais funcionam; digitalizados não")

    dejavu = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    add(OK if dejavu.exists() else WARN, "fonte DejaVu Sans (referência de figurinas)",
        "" if dejavu.exists() else "instale fonts-dejavu-core: o probe de glifos e o OCR de figurinas ficam piores")
    from app.layout.compose import _FONT_FILES, FREE

    missing = [str(p) for files in _FONT_FILES.values() for p in files if not Path(p).exists()]
    missing += [str(FREE / n) for n in ("FreeSerif.ttf", "FreeSerifBold.ttf") if not (FREE / n).exists()]
    add(OK if not missing else FAIL, "fontes da montagem (Liberation, FreeSerif, Urbanist)",
        "" if not missing else f"faltam: {', '.join(missing[:3])} (fonts-liberation, fonts-freefont-ttf)")

    dist = ROOT / "frontend" / "dist" / "index.html"
    add(OK if dist.exists() else FAIL, "interface compilada", "" if dist.exists() else "rode ./instalar.sh")

    storage = Path(os.environ.get("CHESSBOOK_STORAGE") or ROOT / "storage")
    try:
        storage.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=storage):
            pass
        add(OK, "armazenamento dos projetos", str(storage))
    except OSError as exc:
        add(FAIL, "armazenamento dos projetos", f"{storage}: {exc}")
    if storage.resolve().is_relative_to(ROOT.resolve()) and not (ROOT / ".gitignore").read_text().count("storage/"):
        add(WARN, "armazenamento fora do controle de versão", "storage/ deveria estar no .gitignore")

    env_file = ROOT / ".env"
    add(OK if env_file.exists() else WARN, "arquivo .env", "" if env_file.exists() else "copie .env.example para .env")
    if env_file.exists() and os.name == "posix" and env_file.stat().st_mode & 0o077:
        add(WARN, "permissões do .env", "outros usuários podem ler a chave: chmod 600 .env")
    privacy = os.environ.get("CHESSBOOK_PRIVACY_MODE", "local_only")
    add(OK if privacy == "remote_allowed" else WARN, "tradução externa",
        "permitida" if privacy == "remote_allowed" else "bloqueada (CHESSBOOK_PRIVACY_MODE=local_only): "
        "só a revisão funciona")
    add(OK if os.environ.get("POLLINATIONS_API_KEY") else WARN, "chave da Pollinations",
        "configurada (não é mostrada)" if os.environ.get("POLLINATIONS_API_KEY") else "ausente")

    if network:
        import urllib.request

        try:
            with urllib.request.urlopen("https://gen.pollinations.ai/v1/models", timeout=20) as resp:
                add(OK, "acesso à Pollinations", f"HTTP {resp.status}")
        except OSError as exc:
            add(FAIL, "acesso à Pollinations", str(exc))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rede", action="store_true", help="testa o acesso à Pollinations")
    args = ap.parse_args()
    results = checks(args.rede)
    width = max(len(w) for _, w, _ in results)
    for state, what, detail in results:
        print(f"[{state:^5}] {what.ljust(width)}  {detail}")
    failed = [w for s, w, _ in results if s == FAIL]
    print("\nTudo pronto." if not failed else f"\nFalta resolver: {', '.join(failed)}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

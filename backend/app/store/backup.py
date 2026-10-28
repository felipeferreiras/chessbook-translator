"""Backup e restauração de projetos: um arquivo ``.zip`` com manifesto e sha256 de cada parte.

O pacote leva tudo o que não se refaz sem custo ou sem trabalho humano:

* ``app.db``: segmentos, todas as versões, revisões, tarefas, gastos (cópia
  consistente pela API de backup do SQLite, mesmo com uma tarefa rodando);
* ``original/``: o PDF original (o sha256 também está no banco);
* ``glossary.json`` e ``ocr.json``, se houver, com as figurinas confirmadas
  (``ocr-figurinas.json``) e a primeira passada do OCR (``ocr-passe1.json.gz``,
  para reler com outras figurinas sem refazer o OCR);
* ``cache.sqlite``: as traduções já pagas (retraduzir sairia de graça);
* opcionalmente ``output/`` (PDF traduzido, relatório, auditoria). As partes e
  as imagens lado a lado ficam de fora: a montagem as refaz.

A restauração não confia no arquivo recebido: aceita só os nomes esperados
(nada de caminhos absolutos, ``..`` ou links), limita o tamanho descompactado,
confere o sha256 de cada parte contra o manifesto, a integridade do banco e o
sha256 do original contra o registrado no banco, e só então move o projeto
para o lugar, de uma vez.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .project_store import ProjectStore, StoreError, _sha256

FORMAT = 1
MAX_UNCOMPRESSED = 8 * 1024**3  # 8 GB: livro, banco e PDF traduzido cabem com folga
_ALLOWED = re.compile(r"^(manifest\.json|app\.db|glossary\.json|ocr\.json|ocr-figurinas\.json|ocr-passe1\.json\.gz|cache\.sqlite|original/[^/]+\.pdf|"
                      r"output/(traduzido\.pdf|relatorio\.json|pages\.txt|auditoria\.json))$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _sqlite_copy(src: Path, dest: Path) -> None:
    with sqlite3.connect(src, timeout=30) as a, sqlite3.connect(dest) as b:
        a.backup(b)
    b.close()
    a.close()


def create_backup(store: ProjectStore, dest_dir: Path, include_output: bool = True) -> Path:
    """Grava ``<id>-<data>.chessbook.zip`` em ``dest_dir`` e devolve o caminho."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = dest_dir / f"{store.id}-{stamp}.chessbook.zip"
    files: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="backup-") as tmp:
        db_copy = Path(tmp) / "app.db"
        _sqlite_copy(store.db_path, db_copy)
        files["app.db"] = db_copy
        if (store.dir / "cache.sqlite").exists():
            cache_copy = Path(tmp) / "cache.sqlite"
            _sqlite_copy(store.dir / "cache.sqlite", cache_copy)
            files["cache.sqlite"] = cache_copy
        files[f"original/{store.original_path.name}"] = store.original_path
        for name in ("glossary.json", "ocr.json", "ocr-figurinas.json", "ocr-passe1.json.gz"):
            if (store.dir / name).exists():
                files[name] = store.dir / name
        if include_output:
            for name in ("traduzido.pdf", "relatorio.json", "pages.txt", "auditoria.json"):
                if (store.dir / "output" / name).exists():
                    files[f"output/{name}"] = store.dir / "output" / name
        manifest = {"format": FORMAT, "project_id": store.id, "name": store.info["name"],
                    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "original_sha256": store.info["sha256"],
                    "files": {k: {"sha256": _sha256(v), "size": v.stat().st_size} for k, v in sorted(files.items())}}
        partial = target.with_name(target.name + ".tmp")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
            for name, path in sorted(files.items()):
                z.write(path, name)
        partial.replace(target)
    return target


def read_manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        try:
            return json.loads(z.read("manifest.json"))
        except KeyError as exc:
            raise StoreError("o arquivo não é um backup do chessbook-translator (sem manifest.json)") from exc


def restore_backup(path: Path, root: Path, project_id: str | None = None) -> ProjectStore:
    """Restaura o pacote em ``root`` como ``project_id`` (padrão: o id original). Nunca sobrescreve."""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise StoreError("arquivo de backup inválido (não é um zip)") from exc
    with zf as z:
        manifest = read_manifest(path)
        if manifest.get("format") != FORMAT:
            raise StoreError(f"formato de backup desconhecido: {manifest.get('format')}")
        new_id = project_id or manifest.get("project_id", "")
        if not _ID.match(new_id or ""):
            raise StoreError("id de projeto inválido")
        if (root / new_id).exists():
            raise StoreError(f"já existe um projeto {new_id}; restaure com outro id")
        infos = z.infolist()
        total = 0
        for info in infos:
            name = info.filename
            pure = PurePosixPath(name)
            if (not _ALLOWED.match(name) or pure.is_absolute() or ".." in pure.parts
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):  # link simbólico
                raise StoreError(f"entrada não permitida no backup: {name!r}")
            total += info.file_size
            if total > MAX_UNCOMPRESSED:
                raise StoreError("backup grande demais depois de descompactado")
        expected = manifest.get("files", {})
        names = {i.filename for i in infos} - {"manifest.json"}
        if names != set(expected):
            raise StoreError("o conteúdo do backup não confere com o manifesto")
        root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".restaurando-{new_id}-", dir=root))
        try:
            for name in sorted(names):
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                with z.open(name) as src, target.open("wb") as dst:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        h.update(chunk)
                        dst.write(chunk)
                if h.hexdigest() != expected[name]["sha256"]:
                    raise StoreError(f"sha256 não confere: {name}")
            with sqlite3.connect(staging / "app.db") as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise StoreError("o banco do backup está corrompido")
                row = db.execute("SELECT id, sha256, original_name FROM project").fetchone()
                if row is None or row[1] != manifest.get("original_sha256"):
                    raise StoreError("o banco do backup não corresponde ao original")
                if _sha256(staging / "original" / row[2]) != row[1]:
                    raise StoreError("o original do backup não confere com o sha256 registrado")
                if new_id != row[0]:
                    db.execute("UPDATE project SET id=?", (new_id,))
            db.close()
            for pdf in (staging / "original").glob("*.pdf"):
                pdf.chmod(0o440)  # o original volta somente leitura, como na criação do projeto
            staging.rename(root / new_id)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    store = ProjectStore(root, new_id)
    with store._db() as db:
        store._log(db, "project", new_id, "restore", manifest.get("project_id"), manifest.get("created_at"),
                   "sistema")
    return store

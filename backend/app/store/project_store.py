"""Projetos de tradução persistidos em SQLite, com histórico de revisões.

Cada projeto fica em ``<raiz>/<id>/``: ``original/`` (cópia somente leitura
do PDF, conferida pelo sha256), ``app.db`` e ``glossary.json`` (termos do
projeto, que substituem ou acrescentam aos do padrão).

Toda mudança de texto cria uma nova versão; nada é apagado. A tabela
``revision`` registra quem mudou o quê e quando (edição, reversão, aprovação,
glossário). Uma edição manual só é aceita se a notação continuar intacta
(``guard.mask_edit``).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.chess.notation.lexer import LexStyle
from app.translation.glossary import Glossary, GlossaryEntry
from app.translation.guard import GuardViolation, mask_edit, protect, restore
from app.translation.service import SourceSegment, _needs_translation

SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, original_name TEXT NOT NULL, sha256 TEXT NOT NULL,
    pages INTEGER NOT NULL, style_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS segment (
    id TEXT PRIMARY KEY, page INTEGER NOT NULL, ordinal INTEGER NOT NULL, section TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL, bold_json TEXT NOT NULL DEFAULT '[]', italic_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL, current_version INTEGER, approved INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'paragraph',
    machine_problems_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS translation (
    segment_id TEXT NOT NULL REFERENCES segment(id), version INTEGER NOT NULL, kind TEXT NOT NULL,
    text TEXT NOT NULL, masked TEXT NOT NULL, warnings_json TEXT NOT NULL DEFAULT '[]',
    provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', author TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (segment_id, version)
);
CREATE TABLE IF NOT EXISTS revision (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, entity_id TEXT NOT NULL, kind TEXT NOT NULL,
    old_value TEXT, new_value TEXT, author TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job (
    id INTEGER PRIMARY KEY AUTOINCREMENT, engine TEXT NOT NULL, model TEXT NOT NULL, pages TEXT NOT NULL,
    state TEXT NOT NULL, total INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
    estimate REAL, budget REAL NOT NULL, counts_json TEXT NOT NULL DEFAULT '{}', error TEXT,
    author TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS segment_page ON segment(page, ordinal);
CREATE INDEX IF NOT EXISTS revision_entity ON revision(entity, entity_id);
"""


class StoreError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Version:
    version: int
    kind: str  # machine | edit | revert
    text: str
    warnings: list[str]
    author: str
    created_at: str
    provider: str = ""
    model: str = ""


@dataclass
class SegmentView:
    id: str
    page: int
    ordinal: int
    section: str
    source: str
    status: str  # estado da tradução automática: translated, cached, not_needed, needs_review, failed
    approved: bool
    current: Version | None
    machine_problems: list[str]

    @property
    def needs_attention(self) -> bool:
        """Precisa de olhos humanos: falhou, a proteção recusou, ou o glossário foi contrariado."""
        if self.status in ("needs_review", "failed"):
            return True
        return bool(self.current and any(w.startswith("glossario_evitar:") for w in self.current.warnings))


class ProjectStore:
    def __init__(self, root: Path, project_id: str):
        self.root = root
        self.id = project_id
        self.dir = root / project_id
        self.db_path = self.dir / "app.db"
        if not self.db_path.exists():
            raise StoreError(f"projeto inexistente: {project_id}")
        with self._db() as db:  # projetos criados antes de colunas/tabelas novas
            db.executescript(SCHEMA)
            columns = {r["name"] for r in db.execute("PRAGMA table_info(segment)")}
            if "kind" not in columns:
                db.execute("ALTER TABLE segment ADD COLUMN kind TEXT NOT NULL DEFAULT 'paragraph'")

    # --- criação ---------------------------------------------------------
    @classmethod
    def create(cls, root: Path, project_id: str, name: str, pdf: Path, pages: int,
               style: LexStyle | None = None) -> ProjectStore:
        if not project_id.replace("-", "").replace("_", "").isalnum():
            raise StoreError("id de projeto: só letras, números, '-' e '_'")
        pdir = root / project_id
        if pdir.exists():
            raise StoreError(f"projeto já existe: {project_id}")
        (pdir / "original").mkdir(parents=True)
        copy = pdir / "original" / pdf.name
        shutil.copyfile(pdf, copy)
        os.chmod(copy, stat.S_IRUSR | stat.S_IRGRP)  # o original nunca é alterado
        digest = _sha256(copy)
        if digest != _sha256(pdf):
            raise StoreError("a cópia do original não confere com o arquivo de origem")
        with sqlite3.connect(pdir / "app.db") as db:
            db.executescript(SCHEMA)
            db.execute("INSERT INTO project VALUES (?,?,?,?,?,?,?)",
                       (project_id, name, pdf.name, digest, pages, json.dumps((style or LexStyle()).__dict__), _now()))
        return cls(root, project_id)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    @property
    def info(self) -> dict:
        with self._db() as db:
            row = dict(db.execute("SELECT * FROM project").fetchone())
        row["style"] = json.loads(row.pop("style_json"))
        return row

    @property
    def style(self) -> LexStyle:
        return LexStyle(**self.info["style"])

    @property
    def original_path(self) -> Path:
        return self.dir / "original" / self.info["original_name"]

    def verify_original(self) -> bool:
        return _sha256(self.original_path) == self.info["sha256"]

    # --- importação da tradução automática -------------------------------
    def add_book_segments(self, segments: list[dict]) -> int:
        """Todos os segmentos do livro, pendentes: {id, page, section, source, kind, bold, italic}."""
        added = 0
        style = self.style
        with self._db() as db:
            for ordinal, seg in enumerate(segments):
                masked = protect(seg["source"], style, list(seg.get("bold", [])), list(seg.get("italic", []))).masked
                status = "pending" if _needs_translation(masked) else "not_needed"  # só notação: nunca vai ao motor
                cur = db.execute(
                    "INSERT OR IGNORE INTO segment (id, page, ordinal, section, source, bold_json, italic_json, status,"
                    " kind) VALUES (?,?,?,?,?,?,?,?,?)",
                    (seg["id"], seg["page"], ordinal, seg.get("section", ""), seg["source"],
                     json.dumps(list(seg.get("bold", []))), json.dumps(list(seg.get("italic", []))), status,
                     seg.get("kind", "paragraph")))
                added += cur.rowcount
        return added

    def record_machine(self, db: sqlite3.Connection, seg: dict, author: str = "sistema") -> str:
        """Registra o resultado da tradução automática de um segmento existente.

        Uma edição humana nunca é sobrescrita: se a versão atual for de pessoa,
        a tradução nova não é gravada. Devolve o que aconteceu.
        """
        row = db.execute("SELECT current_version FROM segment WHERE id=?", (seg["id"],)).fetchone()
        if row is None:
            raise StoreError(f"segmento inexistente: {seg['id']}")
        if row["current_version"]:
            kind = db.execute("SELECT kind FROM translation WHERE segment_id=? AND version=?",
                              (seg["id"], row["current_version"])).fetchone()["kind"]
            if kind != "machine":
                return "kept_human"
        db.execute("UPDATE segment SET status=?, machine_problems_json=? WHERE id=?",
                   (seg["status"], json.dumps(seg.get("problems", [])), seg["id"]))
        if seg["status"] in ("translated", "cached") and seg.get("raw_translation"):
            self._add_version(db, seg["id"], "machine", seg["text"], seg["raw_translation"], seg.get("warnings", []),
                              author, seg.get("provider", ""), seg.get("model", ""))
            return "translated"
        return seg["status"]

    def import_translation(self, result: dict, bold: dict[str, list[bool]] | None = None,
                           italic: dict[str, list[bool]] | None = None, author: str = "sistema") -> int:
        """Importa ``resultado.json`` de ``translate_pages``: cria os segmentos que faltam e grava as traduções."""
        bold, italic = bold or {}, italic or {}
        self.add_book_segments([{**seg, "bold": bold.get(seg["id"], []), "italic": italic.get(seg["id"], [])}
                                for seg in result["segments"]])
        imported = 0
        with self._db() as db:
            for seg in result["segments"]:
                current = db.execute("SELECT current_version, status FROM segment WHERE id=?", (seg["id"],)).fetchone()
                gains_text = seg["status"] in ("translated", "cached") and seg.get("raw_translation")
                if current["current_version"] is None and (current["status"] == "pending" or gains_text):
                    self.record_machine(db, seg, author)
                    imported += 1
        return imported

    def _add_version(self, db: sqlite3.Connection, segment_id: str, kind: str, text: str, masked: str,
                     warnings: list[str], author: str, provider: str = "", model: str = "") -> int:
        row = db.execute("SELECT MAX(version) FROM translation WHERE segment_id=?", (segment_id,)).fetchone()
        version = (row[0] or 0) + 1
        db.execute("INSERT INTO translation VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (segment_id, version, kind, text, masked, json.dumps(warnings), provider, model, author, _now()))
        db.execute("UPDATE segment SET current_version=?, approved=0 WHERE id=?", (version, segment_id))
        return version

    def _log(self, db: sqlite3.Connection, entity: str, entity_id: str, kind: str, old: str | None,
             new: str | None, author: str) -> None:
        db.execute("INSERT INTO revision (entity, entity_id, kind, old_value, new_value, author, created_at)"
                   " VALUES (?,?,?,?,?,?,?)", (entity, entity_id, kind, old, new, author, _now()))

    # --- leitura -----------------------------------------------------------
    def _view(self, db: sqlite3.Connection, row: sqlite3.Row) -> SegmentView:
        current = None
        if row["current_version"]:
            v = db.execute("SELECT * FROM translation WHERE segment_id=? AND version=?",
                           (row["id"], row["current_version"])).fetchone()
            current = Version(v["version"], v["kind"], v["text"], json.loads(v["warnings_json"]), v["author"],
                              v["created_at"], v["provider"], v["model"])
        return SegmentView(row["id"], row["page"], row["ordinal"], row["section"], row["source"], row["status"],
                           bool(row["approved"]), current, json.loads(row["machine_problems_json"]))

    def segments(self, page: int | None = None) -> list[SegmentView]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM segment" + (" WHERE page=?" if page is not None else "")
                              + " ORDER BY ordinal", (() if page is None else (page,))).fetchall()
            return [self._view(db, r) for r in rows]

    def segment(self, segment_id: str) -> SegmentView:
        with self._db() as db:
            row = db.execute("SELECT * FROM segment WHERE id=?", (segment_id,)).fetchone()
            if row is None:
                raise StoreError(f"segmento inexistente: {segment_id}")
            return self._view(db, row)

    def pages(self) -> list[dict]:
        """Páginas com segmentos: total, traduzidos (com alguma versão), aprovados."""
        with self._db() as db:
            rows = db.execute("SELECT page, COUNT(*) n, SUM(approved) ok, SUM(current_version IS NOT NULL) tr,"
                              " SUM(status = 'not_needed') nn FROM segment GROUP BY page ORDER BY page")
            return [{"page": r["page"], "segments": r["n"], "approved": r["ok"] or 0, "translated": r["tr"] or 0,
                     "notation_only": r["nn"] or 0} for r in rows]

    def sources(self, pages: set[int], only_pending: bool = True) -> list[tuple[str, SourceSegment]]:
        """[(seção, segmento)] das páginas, em ordem; ``only_pending`` pula os já traduzidos ou só de notação."""
        with self._db() as db:
            rows = db.execute("SELECT * FROM segment ORDER BY ordinal").fetchall()
        out = []
        for r in rows:
            if r["page"] not in pages:
                continue
            if only_pending and (r["current_version"] is not None or r["status"] == "not_needed"):
                continue
            out.append((r["section"], SourceSegment(r["id"], r["source"], kind=r["kind"],
                                                    bold=tuple(json.loads(r["bold_json"])),
                                                    italic=tuple(json.loads(r["italic_json"])))))
        return out

    def history(self, segment_id: str) -> list[Version]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM translation WHERE segment_id=? ORDER BY version", (segment_id,))
            return [Version(v["version"], v["kind"], v["text"], json.loads(v["warnings_json"]), v["author"],
                            v["created_at"], v["provider"], v["model"]) for v in rows]

    def revisions(self, entity: str | None = None, entity_id: str | None = None) -> list[dict]:
        where, args = [], []
        if entity:
            where.append("entity=?")
            args.append(entity)
        if entity_id:
            where.append("entity_id=?")
            args.append(entity_id)
        with self._db() as db:
            sql = "SELECT * FROM revision" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
            return [dict(r) for r in db.execute(sql, args)]

    # --- revisão -------------------------------------------------------------
    def _protected(self, db: sqlite3.Connection, segment_id: str):
        row = db.execute("SELECT source, bold_json, italic_json FROM segment WHERE id=?", (segment_id,)).fetchone()
        if row is None:
            raise StoreError(f"segmento inexistente: {segment_id}")
        return protect(row["source"], self.style, json.loads(row["bold_json"]), json.loads(row["italic_json"]))

    def edit(self, segment_id: str, text: str, author: str) -> Version:
        """Nova versão revisada. Levanta ``GuardViolation`` se a notação não estiver intacta."""
        with self._db() as db:
            prot = self._protected(db, segment_id)
            masked = mask_edit(text, prot)
            warnings = restore(masked, prot).warnings + self.glossary().check(prot.original, text)
            old = self._view(db, db.execute("SELECT * FROM segment WHERE id=?", (segment_id,)).fetchone()).current
            version = self._add_version(db, segment_id, "edit", text, masked, warnings, author)
            self._log(db, "segment", segment_id, "edit", old.text if old else None, text, author)
        return self.history(segment_id)[version - 1]

    def revert(self, segment_id: str, version: int, author: str) -> Version:
        """Volta a uma versão anterior criando uma nova (o histórico não perde nada)."""
        target = next((v for v in self.history(segment_id) if v.version == version), None)
        if target is None:
            raise StoreError(f"versão inexistente: {segment_id} v{version}")
        with self._db() as db:
            masked = db.execute("SELECT masked FROM translation WHERE segment_id=? AND version=?",
                                (segment_id, version)).fetchone()["masked"]
            current = self._view(db, db.execute("SELECT * FROM segment WHERE id=?", (segment_id,)).fetchone()).current
            new = self._add_version(db, segment_id, "revert", target.text, masked, target.warnings, author)
            self._log(db, "segment", segment_id, f"revert:v{version}", current.text if current else None,
                      target.text, author)
        return self.history(segment_id)[new - 1]

    def approve(self, segment_id: str, author: str, approved: bool = True) -> None:
        with self._db() as db:
            row = db.execute("SELECT current_version FROM segment WHERE id=?", (segment_id,)).fetchone()
            if row is None:
                raise StoreError(f"segmento inexistente: {segment_id}")
            if approved and row["current_version"] is None:
                raise StoreError("não há tradução para aprovar")
            db.execute("UPDATE segment SET approved=? WHERE id=?", (int(approved), segment_id))
            self._log(db, "segment", segment_id, "approve" if approved else "unapprove", None,
                      str(row["current_version"]), author)

    # --- glossário do projeto ---------------------------------------------------
    @property
    def glossary_path(self) -> Path:
        return self.dir / "glossary.json"

    def glossary(self) -> Glossary:
        return Glossary.load(overrides=self.glossary_path)

    def set_glossary_entry(self, entry: GlossaryEntry, author: str) -> None:
        current = Glossary.load(self.glossary_path) if self.glossary_path.exists() else Glossary([])
        old = next((e for e in current.entries if e.term == entry.term), None)
        current.entries = [e for e in current.entries if e.term != entry.term] + [entry]
        current.save(self.glossary_path)
        with self._db() as db:
            self._log(db, "glossary", entry.term, "set", json.dumps(old.__dict__, ensure_ascii=False) if old else None,
                      json.dumps(entry.__dict__, ensure_ascii=False), author)

    # --- exportação ----------------------------------------------------------
    def export_result(self) -> dict:
        """Mesmo formato de ``resultado.json``, com o texto atual de cada segmento (para ``assemble_pdf``)."""
        segments = []
        with self._db() as db:
            for row in db.execute("SELECT * FROM segment ORDER BY ordinal").fetchall():
                v = None
                if row["current_version"]:
                    v = db.execute("SELECT * FROM translation WHERE segment_id=? AND version=?",
                                   (row["id"], row["current_version"])).fetchone()
                if v is not None:
                    status, text = ("translated" if v["kind"] == "machine" else "reviewed"), v["text"]
                else:  # sem tradução: só notação (copiada) ou pendente (o original fica na página)
                    status, text = row["status"], row["source"] if row["status"] == "not_needed" else None
                segments.append({
                    "id": row["id"], "page": row["page"], "section": row["section"], "source": row["source"],
                    "status": status, "text": text,
                    "raw_translation": v["masked"] if v else None,
                    "warnings": json.loads(v["warnings_json"]) if v else [],
                    "approved": bool(row["approved"]),
                })
        pages = sorted({s["page"] for s in segments})
        return {"summary": {"pages": pages, "project": self.id}, "segments": segments}


__all__ = ["GuardViolation", "ProjectStore", "SegmentView", "StoreError", "Version"]

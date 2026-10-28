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
import re
import shutil
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.chess.notation.lexer import LexStyle
from app.pipeline.notation_pass import OCR_FLAG
from app.pipeline.segments import OCR_SHORT_MARK
from app.translation.glossary import Glossary, GlossaryEntry
from app.translation.guard import GuardViolation, mask_edit, protect, restore
from app.translation.prompt import glossary_signature
from app.translation.service import SourceSegment, _needs_translation

SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, original_name TEXT NOT NULL, sha256 TEXT NOT NULL,
    pages INTEGER NOT NULL, style_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
    spend_limit REAL
);
CREATE TABLE IF NOT EXISTS segment (
    id TEXT PRIMARY KEY, page INTEGER NOT NULL, ordinal INTEGER NOT NULL, section TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL, bold_json TEXT NOT NULL DEFAULT '[]', italic_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL, current_version INTEGER, approved INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'paragraph',
    machine_problems_json TEXT NOT NULL DEFAULT '[]',
    source_flags_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS translation (
    segment_id TEXT NOT NULL REFERENCES segment(id), version INTEGER NOT NULL, kind TEXT NOT NULL,
    text TEXT NOT NULL, masked TEXT NOT NULL, warnings_json TEXT NOT NULL DEFAULT '[]',
    provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', author TEXT NOT NULL, created_at TEXT NOT NULL,
    glossary_sig TEXT,
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
    author TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT,
    mode TEXT NOT NULL DEFAULT 'pending', segment_ids_json TEXT NOT NULL DEFAULT '[]', fresh INTEGER NOT NULL DEFAULT 0,
    runner TEXT, heartbeat_at TEXT, resumed_from INTEGER
);
CREATE TABLE IF NOT EXISTS job_segment (
    job_id INTEGER NOT NULL REFERENCES job(id), segment_id TEXT NOT NULL, outcome TEXT NOT NULL,
    PRIMARY KEY (job_id, segment_id)
);
CREATE TABLE IF NOT EXISTS assembly (
    id INTEGER PRIMARY KEY AUTOINCREMENT, state TEXT NOT NULL, pid INTEGER, author TEXT NOT NULL,
    created_at TEXT NOT NULL, finished_at TEXT, error TEXT, summary_json TEXT
);
CREATE INDEX IF NOT EXISTS segment_page ON segment(page, ordinal);
CREATE INDEX IF NOT EXISTS revision_entity ON revision(entity, entity_id);
"""


# Colunas acrescentadas depois da criação de projetos existentes: (tabela, coluna, declaração).
_MIGRATIONS = (
    ("segment", "kind", "TEXT NOT NULL DEFAULT 'paragraph'"),
    ("segment", "source_flags_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("translation", "glossary_sig", "TEXT"),
    ("project", "spend_limit", "REAL"),
    ("job", "mode", "TEXT NOT NULL DEFAULT 'pending'"),
    ("job", "segment_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("job", "fresh", "INTEGER NOT NULL DEFAULT 0"),
    ("job", "runner", "TEXT"),
    ("job", "heartbeat_at", "TEXT"),
    ("job", "resumed_from", "INTEGER"),
    ("segment", "source_extracted", "TEXT"),  # o texto como foi lido, quando o usuário corrigiu o original
    ("segment", "discarded", "INTEGER NOT NULL DEFAULT 0"),  # lixo do OCR descartado pelo revisor
)

# O que retraduzir (``select_sources``). Uma versão humana nunca entra: a tradução nova não a substituiria.
MODES = {
    "pending": "sem tradução ainda",
    "problems": "recusados pela proteção, falhas do provedor ou glossário contrariado",
    "glossary": "traduzidos com termos do glossário que mudaram depois",
    "machine": "toda tradução automática (por exemplo, para trocar de motor)",
    "ids": "segmentos escolhidos",
}


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


_NOTATION_HINT = re.compile(r"[0-9♔♕♖♗♘♚♛♜♝♞]|\b[a-h][1-8]|[+#†]")
# avisos que só nascem de algo com forma de lance: sempre pedem conferência
_MOVE_WARNINGS = ("ocr_peca_incerta", "ocr_lance_incompleto", "ocr_lance_ilegivel", "ocr_figurina_sem_lugar",
                  "ocr_lance_impossivel", "ocr_sinal_de_xeque", "ocr_simbolo_incerto")


def _touches_notation(flag: str) -> bool:
    """O aviso específico do OCR recai sobre algo que pode ser lance, casa, número ou peça.

    Uma palavra comum lida com pouca confiança ("Morales," "White's") é risco
    de prosa, que a tradução e a revisão pegam; não pede conferência de lance.
    """
    if flag == OCR_FLAG or flag.startswith("ocr_corrigido:"):  # troca com uma leitura só (fica registrada)
        return False
    if flag.startswith(_MOVE_WARNINGS):
        return True
    start, end = flag.find("'"), flag.rfind("'")
    if start < 0 or end <= start:
        return True
    return bool(_NOTATION_HINT.search(flag[start + 1:end]))


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
    source_flags: list[str] = field(default_factory=list)  # dúvidas sobre o texto de origem (OCR)
    source_extracted: str | None = None  # o texto lido, se o original foi corrigido pelo usuário
    discarded: bool = False  # lixo do OCR descartado pelo revisor: não é traduzido, a página fica como a imagem

    @property
    def kept_as_image(self) -> bool:
        """Bloco do OCR que fica como na imagem (rótulo, marca, desenho lido como letras, lixo descartado)."""
        return self.discarded or (self.status == "blocked" and any(p.startswith("ocr:") for p in self.machine_problems))

    @property
    def needs_attention(self) -> bool:
        """Precisa de olhos humanos: falhou, a proteção recusou, o glossário foi contrariado, os
        lances estão desenhados como vetor, ou o OCR deixou um aviso específico ainda não conferido.

        O aviso geral de todo texto de OCR (``OCR_FLAG``) não conta: num livro
        digitalizado ele marcaria todos os parágrafos e esconderia os que importam.
        Um rótulo curto ilegível fica como na imagem sem pedir nada; um trecho descartado também.
        """
        if self.discarded:
            return False
        if self.status in ("needs_review", "failed"):
            return True
        if self.status == "blocked":
            if not self.kept_as_image:
                return True
            return not self.approved and not any(p.startswith(OCR_SHORT_MARK) for p in self.machine_problems)
        if not self.approved and any(_touches_notation(f) for f in self.source_flags):
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
            for table, column, decl in _MIGRATIONS:
                if column not in {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

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
            db.execute("INSERT INTO project (id, name, original_name, sha256, pages, style_json, created_at)"
                       " VALUES (?,?,?,?,?,?,?)",
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
        """Todos os segmentos do livro, pendentes: {id, page, section, source, kind, bold, italic, blocked, flags}."""
        added = 0
        style = self.style
        with self._db() as db:
            for ordinal, seg in enumerate(segments):
                masked = protect(seg["source"], style, list(seg.get("bold", [])), list(seg.get("italic", []))).masked
                status = "pending" if _needs_translation(masked) and seg.get("kind") != "label" else "not_needed"
                problems = []
                if seg.get("blocked"):  # lances desenhados como vetor: não traduzir automaticamente
                    status, problems = "blocked", [seg["blocked"]]
                cur = db.execute(
                    "INSERT OR IGNORE INTO segment (id, page, ordinal, section, source, bold_json, italic_json, status,"
                    " kind, machine_problems_json, source_flags_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (seg["id"], seg["page"], ordinal, seg.get("section", ""), seg["source"],
                     json.dumps(list(seg.get("bold", []))), json.dumps(list(seg.get("italic", []))), status,
                     seg.get("kind", "paragraph"), json.dumps(problems), json.dumps(list(seg.get("flags", [])))))
                added += cur.rowcount
        return added

    def sync_segments(self, segments: list[dict], author: str = "sistema") -> dict:
        """Alinha os segmentos do projeto com uma extração nova (código atualizado), sem perder traduções.

        Cada segmento novo é casado com um antigo de mesmo texto de origem
        (mesmo id, senão mesma página, senão qualquer página). Um casamento com
        id diferente renomeia o antigo, com versões, histórico e tarefas. Se o
        texto protegido mudou (negrito, itálico), a tradução antiga não serve
        mais: fica no histórico e o segmento volta a pendente. Segmentos antigos
        sem par são apagados se nunca foram traduzidos; os traduzidos ficam
        como ``obsolete`` (fora da tradução e da montagem), com o histórico.
        """
        style = self.style
        report = {"kept": 0, "renamed": 0, "added": 0, "removed": 0, "obsolete": 0, "retranslate": 0}
        with self._db() as db:
            old = {r["id"]: r for r in db.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM translation t WHERE t.segment_id = s.id) AS versions"
                " FROM segment s WHERE s.status != 'obsolete'")}
            def read(r: sqlite3.Row) -> str:  # o texto como foi lido (o corrigido pelo usuário fica por cima)
                return r["source_extracted"] if r["source_extracted"] is not None else r["source"]

            by_source: dict[str, list[str]] = {}
            for oid, r in old.items():
                by_source.setdefault(read(r), []).append(oid)
            match: dict[str, str] = {}
            used: set[str] = set()
            for seg in segments:  # 1º mesmo id e texto
                if seg["id"] in old and read(old[seg["id"]]) == seg["source"]:
                    match[seg["id"]] = seg["id"]
                    used.add(seg["id"])
            for seg in segments:  # 2º mesmo texto, preferindo a mesma página
                if seg["id"] in match:
                    continue
                options = [o for o in by_source.get(seg["source"], []) if o not in used]
                options.sort(key=lambda o: old[o]["page"] != seg["page"])
                if options:
                    match[seg["id"]] = options[0]
                    used.add(options[0])
            for oid, r in old.items():  # sem par
                if oid in used:
                    continue
                if r["versions"]:
                    db.execute("UPDATE segment SET status='obsolete' WHERE id=?", (oid,))
                    self._rename(db, oid, f"obsoleto-{oid}-{_now()}")
                    report["obsolete"] += 1
                else:
                    db.execute("DELETE FROM segment WHERE id=?", (oid,))
                    db.execute("DELETE FROM job_segment WHERE segment_id=?", (oid,))
                    report["removed"] += 1
            renames = {o: n for n, o in match.items() if o != n}
            for o in renames:  # em duas etapas: os ids novos podem coincidir com antigos ainda não renomeados
                self._rename(db, o, "tmp:" + o)
            for o, n in renames.items():
                self._rename(db, "tmp:" + o, n)
            report["renamed"] = len(renames)
            for ordinal, seg in enumerate(segments):
                bold, italic = list(seg.get("bold", [])), list(seg.get("italic", []))
                masked = protect(seg["source"], style, bold, italic).masked
                # só notação, ou marca do diagrama ("W?"): nunca vai ao motor
                status = "pending" if _needs_translation(masked) and seg.get("kind") != "label" else "not_needed"
                problems = [seg["blocked"]] if seg.get("blocked") else []
                if seg.get("blocked"):
                    status = "blocked"
                fields = (seg["page"], ordinal, seg.get("section", ""), json.dumps(bold), json.dumps(italic),
                          seg.get("kind", "paragraph"), json.dumps(list(seg.get("flags", []))))
                if seg["id"] not in match:
                    db.execute("INSERT INTO segment (id, page, ordinal, section, bold_json, italic_json, kind,"
                               " source_flags_json, source, status, machine_problems_json)"
                               " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (seg["id"], *fields, seg["source"], status, json.dumps(problems)))
                    report["added"] += 1
                    continue
                prev = old[match[seg["id"]]]
                if prev["source_extracted"] is not None:  # original corrigido pelo usuário: só a posição muda
                    db.execute("UPDATE segment SET page=?, ordinal=?, section=?, source_flags_json=? WHERE id=?",
                               (seg["page"], ordinal, seg.get("section", ""), json.dumps(list(seg.get("flags", []))),
                                seg["id"]))
                    report["kept"] += 1
                    continue
                db.execute("UPDATE segment SET page=?, ordinal=?, section=?, bold_json=?, italic_json=?, kind=?,"
                           " source_flags_json=? WHERE id=?", (*fields, seg["id"]))
                old_masked = protect(prev["source"], style, json.loads(prev["bold_json"]),
                                     json.loads(prev["italic_json"])).masked
                if prev["versions"] and old_masked != masked:  # a tradução guardada não casa com a nova proteção
                    db.execute("UPDATE segment SET current_version=NULL, approved=0, status=?,"
                               " machine_problems_json=? WHERE id=?", (status, json.dumps(problems), seg["id"]))
                    self._log(db, "segment", seg["id"], "source_changed", old_masked, masked, author)
                    report["retranslate"] += 1
                elif seg.get("kind") == "label" and prev["current_version"]:  # marca do diagrama: volta ao original
                    db.execute("UPDATE segment SET current_version=NULL, approved=0, status='not_needed',"
                               " machine_problems_json='[]' WHERE id=?", (seg["id"],))
                    self._log(db, "segment", seg["id"], "label_untranslated", None, None, author)
                    report["retranslate"] += 1
                elif not prev["current_version"] and prev["status"] not in ("needs_review", "failed"):
                    # nunca tentado: o estado vem da extração nova (recusa ou falha de uma tentativa ficam)
                    db.execute("UPDATE segment SET status=?, machine_problems_json=? WHERE id=?",
                               (status, json.dumps(problems), seg["id"]))
                report["kept"] += 1
            self._log(db, "project", self.id, "sync", None, json.dumps(report), author)
        return report

    def _rename(self, db: sqlite3.Connection, old: str, new: str) -> None:
        # o nome novo está livre: registro de tarefa com ele é de um segmento já apagado (projetos de
        # versões que não limpavam ao apagar); senão, renomear para ele violava a chave da tarefa
        db.execute("DELETE FROM job_segment WHERE segment_id=?", (new,))
        db.execute("UPDATE segment SET id=? WHERE id=?", (new, old))
        db.execute("UPDATE translation SET segment_id=? WHERE segment_id=?", (new, old))
        db.execute("UPDATE job_segment SET segment_id=? WHERE segment_id=?", (new, old))
        db.execute("UPDATE revision SET entity_id=? WHERE entity='segment' AND entity_id=?", (new, old))

    def record_machine(self, db: sqlite3.Connection, seg: dict, author: str = "sistema") -> str:
        """Registra o resultado da tradução automática de um segmento existente.

        Uma edição humana nunca é sobrescrita: se a versão atual for de pessoa,
        a tradução nova não é gravada. Numa retradução que falha, a tradução
        anterior continua valendo (``retry_failed``). Devolve o que aconteceu.
        """
        row = db.execute("SELECT current_version FROM segment WHERE id=?", (seg["id"],)).fetchone()
        if row is None:
            raise StoreError(f"segmento inexistente: {seg['id']}")
        if row["current_version"]:
            kind = db.execute("SELECT kind FROM translation WHERE segment_id=? AND version=?",
                              (seg["id"], row["current_version"])).fetchone()["kind"]
            if kind != "machine":
                return "kept_human"
            if seg["status"] not in ("translated", "cached"):
                return "retry_failed"
        db.execute("UPDATE segment SET status=?, machine_problems_json=? WHERE id=?",
                   (seg["status"], json.dumps(seg.get("problems", [])), seg["id"]))
        if seg["status"] in ("translated", "cached") and seg.get("raw_translation"):
            self._add_version(db, seg["id"], "machine", seg["text"], seg["raw_translation"], seg.get("warnings", []),
                              author, seg.get("provider", ""), seg.get("model", ""), seg.get("glossary_sig"))
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
                     warnings: list[str], author: str, provider: str = "", model: str = "",
                     glossary_sig: str | None = None) -> int:
        row = db.execute("SELECT MAX(version) FROM translation WHERE segment_id=?", (segment_id,)).fetchone()
        version = (row[0] or 0) + 1
        db.execute("INSERT INTO translation (segment_id, version, kind, text, masked, warnings_json, provider, model,"
                   " author, created_at, glossary_sig) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (segment_id, version, kind, text, masked, json.dumps(warnings), provider, model, author, _now(),
                    glossary_sig))
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
                           bool(row["approved"]), current, json.loads(row["machine_problems_json"]),
                           json.loads(row["source_flags_json"]), row["source_extracted"], bool(row["discarded"]))

    def segments(self, page: int | None = None) -> list[SegmentView]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM segment WHERE status != 'obsolete'" + (" AND page=?" if page is not None else "")
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
                              " SUM(status = 'not_needed') nn FROM segment WHERE status != 'obsolete'"
                              " GROUP BY page ORDER BY page")
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
            if r["status"] == "obsolete" or (only_pending and (
                    r["current_version"] is not None or r["status"] in ("not_needed", "blocked") or r["discarded"])):
                continue
            out.append((r["section"], SourceSegment(r["id"], r["source"], kind=r["kind"],
                                                    bold=tuple(json.loads(r["bold_json"])),
                                                    italic=tuple(json.loads(r["italic_json"])))))
        return out

    def select_sources(self, pages: set[int], mode: str = "pending", ids: frozenset[str] = frozenset(),
                       exclude: frozenset[str] = frozenset()) -> tuple[list[tuple[str, SourceSegment]], dict]:
        """Segmentos a (re)traduzir conforme ``mode`` (ver ``MODES``), em ordem, e o que ficou de fora.

        ``exclude``: já tratados por uma tarefa anterior (retomada). Só de
        notação, bloqueados e versões humanas nunca entram.
        """
        if mode not in MODES:
            raise StoreError(f"modo desconhecido: {mode}")
        if mode == "ids" and not ids:
            raise StoreError("nenhum segmento escolhido")
        if mode == "pending":
            items = [x for x in self.sources(pages) if x[1].id not in exclude]
            return items, {}
        glossary = self.glossary() if mode == "glossary" else None
        style = self.style
        skipped = {"human": 0, "not_needed": 0, "blocked": 0, "discarded": 0, "no_glossary_record": 0}
        out = []
        with self._db() as db:
            rows = db.execute("SELECT s.*, t.kind AS vkind, t.warnings_json, t.glossary_sig FROM segment s"
                              " LEFT JOIN translation t ON t.segment_id = s.id AND t.version = s.current_version"
                              " WHERE s.status != 'obsolete'"
                              " ORDER BY s.ordinal").fetchall()
        for r in rows:
            if (r["page"] not in pages and mode != "ids") or r["id"] in exclude:
                continue
            if mode == "ids" and r["id"] not in ids:
                continue
            if r["discarded"]:
                skipped["discarded"] += 1
                continue
            if r["status"] in ("not_needed", "blocked"):
                skipped[r["status"]] += 1
                continue
            if r["vkind"] not in (None, "machine"):
                skipped["human"] += 1
                continue
            if mode == "problems":
                avoid = r["warnings_json"] and any(w.startswith("glossario_evitar:") for w in json.loads(r["warnings_json"]))
                if r["status"] not in ("needs_review", "failed") and not avoid:
                    continue
            elif mode in ("glossary", "machine"):
                if r["vkind"] != "machine":
                    continue
                if mode == "glossary":
                    if r["glossary_sig"] is None:  # traduzido antes do registro: não dá para saber
                        skipped["no_glossary_record"] += 1
                        continue
                    masked = protect(r["source"], style, json.loads(r["bold_json"]), json.loads(r["italic_json"])).masked
                    if glossary_signature(masked, glossary) == r["glossary_sig"]:
                        continue
            out.append((r["section"], SourceSegment(r["id"], r["source"], kind=r["kind"],
                                                    bold=tuple(json.loads(r["bold_json"])),
                                                    italic=tuple(json.loads(r["italic_json"])))))
        return out, {k: v for k, v in skipped.items() if v}

    # --- gastos ------------------------------------------------------------------
    def spent(self) -> float:
        """Soma do custo real de todas as tarefas do projeto (pollen)."""
        with self._db() as db:
            return round(db.execute("SELECT COALESCE(SUM(cost), 0) FROM job").fetchone()[0], 5)

    @property
    def spend_limit(self) -> float | None:
        return self.info.get("spend_limit")

    def set_spend_limit(self, limit: float | None, author: str) -> None:
        """Teto de gasto do projeto inteiro (None: sem teto). Cada tarefa fica limitada ao que sobra."""
        if limit is not None and limit < 0:
            raise StoreError("o teto não pode ser negativo")
        old = self.spend_limit
        with self._db() as db:
            db.execute("UPDATE project SET spend_limit=?", (limit,))
            self._log(db, "project", self.id, "spend_limit", None if old is None else str(old),
                      None if limit is None else str(limit), author)

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

    def edit_source(self, segment_id: str, text: str, author: str) -> SegmentView:
        """Corrige o texto de origem lido por OCR (ou de um bloco com lances desenhados) antes de traduzir.

        O texto lido fica guardado (``source_extracted``) e a sincronização casa
        por ele, então a correção sobrevive a uma atualização do programa. Uma
        tradução automática feita sobre o texto antigo volta a pendente (fica no
        histórico); uma revisão humana fica, mas pede conferência.
        """
        text = text.strip()
        if not text:
            raise StoreError("o original não pode ficar vazio")
        with self._db() as db:
            row = db.execute("SELECT * FROM segment WHERE id=?", (segment_id,)).fetchone()
            if row is None:
                raise StoreError(f"segmento inexistente: {segment_id}")
            flags = json.loads(row["source_flags_json"])
            if OCR_FLAG not in flags and row["status"] != "blocked":
                raise StoreError("só o texto lido por OCR (ou um bloco bloqueado) pode ser corrigido")
            if text == row["source"]:
                return self._view(db, row)
            extracted = row["source_extracted"] if row["source_extracted"] is not None else row["source"]
            zeros = json.dumps([False] * len(text))
            masked = protect(text, self.style, [False] * len(text), [False] * len(text)).masked
            status = "pending" if _needs_translation(masked) and row["kind"] != "label" else "not_needed"
            problems: list[str] = []
            version = row["current_version"]
            if version:
                kind = db.execute("SELECT kind FROM translation WHERE segment_id=? AND version=?",
                                  (segment_id, version)).fetchone()["kind"]
                if kind == "machine":
                    version = None
                else:
                    status = "needs_review"
                    problems = ["o original foi corrigido depois desta revisão: confira lances e números com ele"]
            db.execute("UPDATE segment SET source=?, source_extracted=?, bold_json=?, italic_json=?, status=?,"
                       " current_version=?, approved=0, machine_problems_json=? WHERE id=?",
                       (text, None if text == extracted else extracted, zeros, zeros, status, version,
                        json.dumps(problems), segment_id))
            self._log(db, "segment", segment_id, "source_edit", row["source"], text, author)
            return self._view(db, db.execute("SELECT * FROM segment WHERE id=?", (segment_id,)).fetchone())

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
        """Marca como conferido. Um bloco do OCR que fica como na imagem pode ser aprovado sem tradução."""
        with self._db() as db:
            row = db.execute("SELECT * FROM segment WHERE id=?", (segment_id,)).fetchone()
            if row is None:
                raise StoreError(f"segmento inexistente: {segment_id}")
            if approved and row["current_version"] is None and not self._view(db, row).kept_as_image:
                raise StoreError("não há tradução para aprovar")
            db.execute("UPDATE segment SET approved=? WHERE id=?", (int(approved), segment_id))
            self._log(db, "segment", segment_id, "approve" if approved else "unapprove", None,
                      str(row["current_version"]), author)

    def discard(self, segment_id: str, author: str, discarded: bool = True) -> SegmentView:
        """Descarta um trecho que o OCR leu onde não há texto (sujeira, borda, mancha): não vai ao
        tradutor e a página fica como a imagem original ali. Vale depois de sincronizar; pode ser desfeito."""
        with self._db() as db:
            row = db.execute("SELECT * FROM segment WHERE id=?", (segment_id,)).fetchone()
            if row is None:
                raise StoreError(f"segmento inexistente: {segment_id}")
            if OCR_FLAG not in json.loads(row["source_flags_json"]):
                raise StoreError("só um trecho lido por OCR pode ser descartado")
            db.execute("UPDATE segment SET discarded=?, approved=? WHERE id=?",
                       (int(discarded), int(discarded), segment_id))
            self._log(db, "segment", segment_id, "discard" if discarded else "undiscard", None, None, author)
            return self._view(db, db.execute("SELECT * FROM segment WHERE id=?", (segment_id,)).fetchone())

    def approve_page(self, page: int, author: str) -> dict:
        """Aprova de uma vez o que a página tem de traduzido (ou mantido como na imagem).

        Não aprova o que a proteção recusou ou o que falhou: isso pede correção, não conferência.
        """
        done, skipped = [], []
        with self._db() as db:
            for row in db.execute("SELECT * FROM segment WHERE page=? AND status != 'obsolete' AND approved=0"
                                  " ORDER BY ordinal", (page,)).fetchall():
                view = self._view(db, row)
                if view.status in ("needs_review", "failed") or (view.current is None and not view.kept_as_image):
                    if view.status != "not_needed":
                        skipped.append(view.id)
                    continue
                db.execute("UPDATE segment SET approved=1 WHERE id=?", (view.id,))
                self._log(db, "segment", view.id, "approve", None, str(row["current_version"]), author)
                done.append(view.id)
        return {"approved": done, "skipped": skipped}

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
            for row in db.execute("SELECT * FROM segment WHERE status != 'obsolete' ORDER BY ordinal").fetchall():
                v = None
                if row["current_version"]:
                    v = db.execute("SELECT * FROM translation WHERE segment_id=? AND version=?",
                                   (row["id"], row["current_version"])).fetchone()
                if row["discarded"]:  # lixo do OCR: a página fica como a imagem ali
                    v = None
                    status, text = "discarded", None
                elif v is not None:
                    status, text = ("translated" if v["kind"] == "machine" else "reviewed"), v["text"]
                else:  # sem tradução: só notação (copiada) ou pendente (o original fica na página)
                    status, text = row["status"], row["source"] if row["status"] == "not_needed" else None
                corrected = row["source_extracted"] is not None
                segments.append({
                    "id": row["id"], "page": row["page"], "section": row["section"],
                    "source": row["source_extracted"] if corrected else row["source"],
                    **({"source_text": row["source"]} if corrected else {}),
                    "status": status, "text": text,
                    "raw_translation": v["masked"] if v else None,
                    "warnings": json.loads(v["warnings_json"]) if v else [],
                    "approved": bool(row["approved"]),
                })
        # o livro inteiro: páginas sem texto (só diagramas, fotos, em branco) vão como no original,
        # senão o PDF traduzido perderia páginas e a numeração deslocaria
        pages = sorted({s["page"] for s in segments} | set(range(1, int(self.info["pages"]) + 1)))
        return {"summary": {"pages": pages, "project": self.id}, "segments": segments}


__all__ = ["GuardViolation", "ProjectStore", "SegmentView", "StoreError", "Version"]

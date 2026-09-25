"""SQLite catalog: datasets, their files, conditions (with 510(k) counts),
and crawl sessions.

One file on disk (``$DATASETS_DATA_DIR/catalog.sqlite3``), WAL mode, a fresh
connection per operation and a process-wide write lock, so the API thread and
the crawl worker threads can share it safely. Search uses an FTS5 index kept
in sync by the write path.
"""
from __future__ import annotations

import hashlib
import json
import zlib
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlsplit, urlunsplit

ACCESS_TYPES = ("open", "registration", "credentialed", "dua", "request", "unknown")

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id                  TEXT PRIMARY KEY,
    canonical_url       TEXT NOT NULL UNIQUE,
    url                 TEXT NOT NULL,
    title               TEXT NOT NULL,
    source              TEXT,
    description         TEXT,
    conditions          TEXT NOT NULL DEFAULT '[]',
    modalities          TEXT NOT NULL DEFAULT '[]',
    labels              TEXT,
    size                TEXT,
    n_subjects          TEXT,
    file_formats        TEXT NOT NULL DEFAULT '[]',
    license             TEXT,
    access_type         TEXT NOT NULL DEFAULT 'unknown',
    access_instructions TEXT,
    download_urls       TEXT NOT NULL DEFAULT '[]',
    citation            TEXT,
    tags                TEXT NOT NULL DEFAULT '[]',
    download_status     TEXT NOT NULL DEFAULT 'pending',
    first_seen          TEXT NOT NULL,
    last_seen           TEXT NOT NULL,
    found_by            TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id   TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    url          TEXT NOT NULL,
    filename     TEXT,
    local_path   TEXT,
    bytes        INTEGER,
    sha256       TEXT,
    content_type TEXT,
    status       TEXT NOT NULL,
    note         TEXT,
    fetched_at   TEXT NOT NULL,
    UNIQUE (dataset_id, url)
);

CREATE TABLE IF NOT EXISTS conditions (
    name            TEXT PRIMARY KEY,
    display         TEXT NOT NULL,
    synonyms        TEXT NOT NULL DEFAULT '[]',
    fda_terms       TEXT NOT NULL DEFAULT '[]',
    fda_510k_count  INTEGER,
    fda_checked_at  TEXT
);

CREATE TABLE IF NOT EXISTS dataset_conditions (
    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    condition  TEXT NOT NULL,
    PRIMARY KEY (dataset_id, condition)
);

CREATE TABLE IF NOT EXISTS crawls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mode        TEXT NOT NULL,
    query       TEXT,
    query_norm  TEXT,
    status      TEXT NOT NULL,
    plan        TEXT,
    log         TEXT NOT NULL DEFAULT '[]',
    error       TEXT,
    minutes     INTEGER NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS crawls_query_norm ON crawls(query_norm);

CREATE TABLE IF NOT EXISTS crawl_hits (
    crawl_id   INTEGER NOT NULL REFERENCES crawls(id) ON DELETE CASCADE,
    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    is_new     INTEGER NOT NULL,
    at         TEXT NOT NULL,
    PRIMARY KEY (crawl_id, dataset_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS datasets_fts USING fts5(
    id UNINDEXED, title, description, conditions, modalities, labels,
    tags, source, tokenize = 'porter unicode61'
);

-- Literature: journal articles that cite a dataset's descriptor paper(s) or
-- mention the dataset by name. One article row per paper, however found.
CREATE TABLE IF NOT EXISTS articles (
    id             TEXT PRIMARY KEY,          -- pmid:… | doi:… | openalex:W… | epmc:SRC:…
    doi            TEXT,
    pmid           TEXT,
    pmcid          TEXT,
    openalex_id    TEXT,
    title          TEXT NOT NULL,
    authors        TEXT,
    venue          TEXT,
    year           INTEGER,
    cited_by_count INTEGER NOT NULL DEFAULT 0,
    url            TEXT,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS articles_doi ON articles(doi);

CREATE TABLE IF NOT EXISTS dataset_articles (
    dataset_id  TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    cites       INTEGER NOT NULL DEFAULT 0,   -- cites a descriptor paper
    mentions    INTEGER NOT NULL DEFAULT 0,   -- names the dataset in text
    is_descriptor INTEGER NOT NULL DEFAULT 0, -- the paper that introduced it
    sources     TEXT NOT NULL DEFAULT '',     -- e.g. "epmc_cites,openalex_mentions"
    matched     TEXT,                         -- alias that matched (mentions)
    first_seen  TEXT NOT NULL,
    PRIMARY KEY (dataset_id, article_id)
);
CREATE INDEX IF NOT EXISTS dataset_articles_article ON dataset_articles(article_id);

-- FDA device submissions (510(k) and De Novo, both from openFDA's 510k
-- endpoint; De Novo numbers start with DEN) matched to conditions.
CREATE TABLE IF NOT EXISTS devices (
    k_number              TEXT PRIMARY KEY,
    submission_type       TEXT NOT NULL,          -- 510k | denovo
    device_name           TEXT,
    applicant             TEXT,
    contact               TEXT,
    address               TEXT,
    country_code          TEXT,
    decision_date         TEXT,
    decision_code         TEXT,
    decision_description  TEXT,
    date_received         TEXT,
    product_code          TEXT,
    generic_name          TEXT,
    device_class          TEXT,
    regulation_number     TEXT,
    medical_specialty     TEXT,
    advisory_committee    TEXT,
    clearance_type        TEXT,
    statement_or_summary  TEXT,
    third_party_flag      TEXT,
    expedited_review_flag TEXT,
    raw                   TEXT,
    updated_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS devices_decision ON devices(decision_date);

CREATE TABLE IF NOT EXISTS condition_devices (
    condition TEXT NOT NULL,
    k_number  TEXT NOT NULL REFERENCES devices(k_number) ON DELETE CASCADE,
    source    TEXT NOT NULL DEFAULT 'name',  -- name (openFDA name match) | llm
    PRIMARY KEY (condition, k_number)
);

-- The public summary / decision-summary PDF of each submission.
CREATE TABLE IF NOT EXISTS device_docs (
    k_number     TEXT PRIMARY KEY REFERENCES devices(k_number) ON DELETE CASCADE,
    status       TEXT NOT NULL,          -- done | failed | none
    requested    INTEGER NOT NULL DEFAULT 0,
    pdf_url      TEXT,
    pages        INTEGER,
    text         BLOB,                   -- zlib-compressed extracted text
    predicates   TEXT NOT NULL DEFAULT '[]',
    extracted    TEXT,                   -- LLM structured summary (JSON)
    extracted_at TEXT,
    error        TEXT,
    fetched_at   TEXT
);

-- Catalog datasets / papers referenced in a submission's summary.
CREATE TABLE IF NOT EXISTS device_links (
    k_number   TEXT NOT NULL REFERENCES devices(k_number) ON DELETE CASCADE,
    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    article_id TEXT NOT NULL DEFAULT '',
    via        TEXT NOT NULL,            -- alias | doi | title
    matched    TEXT,
    snippet    TEXT,
    PRIMARY KEY (k_number, dataset_id, article_id)
);
CREATE INDEX IF NOT EXISTS device_links_dataset ON device_links(dataset_id);
CREATE INDEX IF NOT EXISTS device_links_article ON device_links(article_id);

CREATE TABLE IF NOT EXISTS literature_state (
    dataset_id   TEXT PRIMARY KEY REFERENCES datasets(id) ON DELETE CASCADE,
    status       TEXT NOT NULL,               -- active | retry | complete | unresolved
    descriptors  TEXT NOT NULL DEFAULT '[]',
    aliases      TEXT NOT NULL DEFAULT '[]',
    streams      TEXT NOT NULL DEFAULT '[]',  -- [{kind, ref, cursor, done, fetched, error}]
    note         TEXT,
    last_worked  TEXT,
    completed_at TEXT
);
"""

_JSON_FIELDS = ("conditions", "modalities", "file_formats", "download_urls", "tags")
_STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "with", "in", "on", "to", "or",
    "dataset", "datasets", "data", "images", "image", "scan", "scans",
    "labels", "labeled", "labelled", "annotated", "public", "open",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_url(url: str) -> str:
    """Normalize a landing-page URL for dedup: lowercase host, no scheme
    distinction, no fragment, no trailing slash, no ``www.``."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parts.path) or ""
    return urlunsplit(("", host, path, parts.query, "")).lstrip("/")


def dataset_id_for(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:12]


def normalize_condition(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def normalize_query(q: str) -> str:
    return " ".join(sorted(set(re.findall(r"[a-z0-9]+", q.lower()))))


def fts_query(q: str) -> str | None:
    """User text -> an FTS5 OR-query of prefix terms (stopwords dropped)."""
    terms = [t for t in re.findall(r"[A-Za-z0-9]+", q.lower())
             if t not in _STOPWORDS and len(t) > 1]
    if not terms:
        return None
    return " OR ".join(f'"{t}"*' for t in dict.fromkeys(terms))


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            self._migrate(c)
            # Identity of this catalog file: if catalog_created_at changes
            # across deploys, the file was recreated (storage not persisting).
            c.execute("INSERT OR IGNORE INTO kv VALUES ('catalog_created_at', ?)", (now_iso(),))
            c.execute("INSERT INTO kv VALUES ('opens', '1') ON CONFLICT (k) DO UPDATE"
                      " SET v = CAST(v AS INTEGER) + 1")

    @staticmethod
    def _migrate(c: sqlite3.Connection) -> None:
        """Additive column migrations for catalogs created by older versions."""
        have = {r[1] for r in c.execute("PRAGMA table_info(conditions)")}
        for col, decl in (("fda_denovo_count", "INTEGER"), ("fda_synced_at", "TEXT"),
                          ("fda_devices_capped", "INTEGER NOT NULL DEFAULT 0")):
            if col not in have:
                c.execute(f"ALTER TABLE conditions ADD COLUMN {col} {decl}")
        have = {r[1] for r in c.execute("PRAGMA table_info(devices)")}
        for col, decl in (("is_software", "INTEGER NOT NULL DEFAULT 0"),
                          ("is_ai", "INTEGER NOT NULL DEFAULT 0"), ("ai_source", "TEXT"),
                          ("conditions_mapped_at", "TEXT")):
            if col not in have:
                c.execute(f"ALTER TABLE devices ADD COLUMN {col} {decl}")
        have = {r[1] for r in c.execute("PRAGMA table_info(condition_devices)")}
        if "source" not in have:
            c.execute("ALTER TABLE condition_devices ADD COLUMN source TEXT NOT NULL"
                      " DEFAULT 'name'")
        c.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")

    # ------------------------------------------------------------ plumbing
    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._conn() as c:
            yield c

    @staticmethod
    def _dataset_row(row: sqlite3.Row) -> dict:
        d = dict(row)
        for f in _JSON_FIELDS:
            d[f] = json.loads(d.get(f) or "[]")
        return d

    # ------------------------------------------------------------ datasets
    def upsert_dataset(self, rec: dict, found_by: str | None = None) -> tuple[str, bool]:
        """Insert or merge a dataset record. Returns (id, is_new).

        Merge rule: non-empty incoming scalars overwrite; list fields are
        unioned, so repeated sightings only ever add information.
        """
        url = rec["url"].strip()
        canon = canonical_url(url)
        ts = now_iso()
        access = rec.get("access_type") or "unknown"
        if access not in ACCESS_TYPES:
            access = "unknown"
        with self._write() as c:
            existing = c.execute(
                "SELECT * FROM datasets WHERE canonical_url = ?", (canon,)).fetchone()
            if existing:
                cur = self._dataset_row(existing)
                ds_id, is_new = cur["id"], False
            else:
                cur = {f: [] for f in _JSON_FIELDS}
                ds_id, is_new = dataset_id_for(url), True
            merged: dict[str, Any] = {}
            for f in _JSON_FIELDS:
                incoming = [str(x).strip() for x in rec.get(f) or [] if str(x).strip()]
                if f == "conditions":
                    incoming = [normalize_condition(x) for x in incoming]
                if f == "download_urls":  # rendered as links: http(s) only
                    incoming = [u for u in incoming if u.startswith(("http://", "https://"))]
                merged[f] = json.dumps(list(dict.fromkeys(cur[f] + incoming)))
            scalars = ("title", "source", "description", "labels", "size",
                       "n_subjects", "license", "access_instructions", "citation")
            for f in scalars:
                val = rec.get(f)
                merged[f] = (str(val).strip() if val else None) or (
                    existing[f] if existing else None)
            if existing and access == "unknown":
                access = existing["access_type"]
            merged["title"] = merged["title"] or url
            if existing:
                c.execute(f"""
                    UPDATE datasets SET {", ".join(f"{k} = :{k}" for k in merged)},
                        access_type = :access_type, last_seen = :ts
                    WHERE id = :id""",
                    {**merged, "access_type": access, "ts": ts, "id": ds_id})
            else:
                cols = ["id", "canonical_url", "url", *merged, "access_type",
                        "first_seen", "last_seen", "found_by"]
                vals = {**merged, "id": ds_id, "canonical_url": canon, "url": url,
                        "access_type": access, "first_seen": ts, "last_seen": ts,
                        "found_by": found_by}
                c.execute(f"INSERT INTO datasets ({', '.join(cols)}) VALUES "
                          f"({', '.join(':' + k for k in cols)})", vals)
            conds = json.loads(merged["conditions"])
            c.executemany(
                "INSERT OR IGNORE INTO dataset_conditions VALUES (?, ?)",
                [(ds_id, x) for x in conds])
            for x in conds:
                c.execute("INSERT OR IGNORE INTO conditions (name, display) VALUES (?, ?)",
                          (x, x.title()))
            self._reindex(c, ds_id)
        return ds_id, is_new

    def _reindex(self, c: sqlite3.Connection, ds_id: str) -> None:
        row = c.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
        c.execute("DELETE FROM datasets_fts WHERE id = ?", (ds_id,))
        if row is None:
            return
        d = self._dataset_row(row)
        c.execute(
            "INSERT INTO datasets_fts (id, title, description, conditions, modalities,"
            " labels, tags, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ds_id, d["title"], d["description"] or "", " ".join(d["conditions"]),
             " ".join(d["modalities"]), d["labels"] or "", " ".join(d["tags"]),
             d["source"] or ""))

    def set_download_status(self, ds_id: str, status: str) -> None:
        with self._write() as c:
            c.execute("UPDATE datasets SET download_status = ? WHERE id = ?",
                      (status, ds_id))

    def get_dataset(self, ds_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
            if not row:
                return None
            d = self._dataset_row(row)
            d["n_articles"] = c.execute(
                "SELECT COUNT(*) FROM dataset_articles WHERE dataset_id = ? AND is_descriptor = 0",
                (ds_id,)).fetchone()[0]
            d["devices"] = [dict(r) for r in c.execute(
                "SELECT DISTINCT v.k_number, v.submission_type, v.device_name, v.applicant,"
                " v.decision_date FROM device_links l JOIN devices v ON v.k_number = l.k_number"
                " WHERE l.dataset_id = ? ORDER BY v.decision_date DESC", (ds_id,))]
            d["files"] = [dict(r) for r in c.execute(
                "SELECT id, url, filename, bytes, sha256, content_type, status, note,"
                " fetched_at FROM files WHERE dataset_id = ? ORDER BY id", (ds_id,))]
        return d

    def get_datasets(self, ids: Iterable[str]) -> list[dict]:
        out = []
        for i in ids:
            d = self.get_dataset(i)
            if d:
                out.append(d)
        return out

    def search(self, q: str, limit: int = 100, extra_terms: Iterable[str] = ()) -> list[str]:
        """Ranked dataset ids for a free-text query (FTS5 bm25, title/conditions
        weighted up). ``extra_terms`` widens the match (e.g. synonyms)."""
        expr = fts_query(" ".join([q, *extra_terms]))
        if not expr:
            return []
        with self._conn() as c:
            rows = c.execute(
                "SELECT id FROM datasets_fts WHERE datasets_fts MATCH ?"
                " ORDER BY bm25(datasets_fts, 0, 5.0, 1.0, 4.0, 2.0, 1.5, 1.0, 0.5)"
                " LIMIT ?", (expr, limit)).fetchall()
        return [r["id"] for r in rows]

    def list_dataset_ids(self, condition: str | None = None, limit: int = 500,
                         offset: int = 0) -> list[str]:
        with self._conn() as c:
            if condition:
                rows = c.execute(
                    "SELECT d.id FROM datasets d JOIN dataset_conditions dc"
                    " ON dc.dataset_id = d.id WHERE dc.condition = ?"
                    " ORDER BY d.last_seen DESC LIMIT ? OFFSET ?",
                    (normalize_condition(condition), limit, offset)).fetchall()
            else:
                rows = c.execute("SELECT id FROM datasets ORDER BY last_seen DESC"
                                 " LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [r["id"] for r in rows]

    def known_for_prompt(self, terms: Iterable[str], limit: int = 60) -> list[dict]:
        """Compact (title, url) list the crawl agent uses to skip duplicates."""
        ids = self.search(" ".join(terms), limit=limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT title, url FROM datasets WHERE id IN ({','.join('?' * len(ids))})",
                ids)] if ids else []

    def stats(self) -> dict:
        with self._conn() as c:
            one = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
            return {
                "datasets": one("SELECT COUNT(*) FROM datasets"),
                "open": one("SELECT COUNT(*) FROM datasets WHERE access_type = 'open'"),
                "with_files": one("SELECT COUNT(DISTINCT dataset_id) FROM files"
                                  " WHERE status = 'downloaded'"),
                "files": one("SELECT COUNT(*) FROM files WHERE status = 'downloaded'"),
                "bytes": one("SELECT COALESCE(SUM(bytes), 0) FROM files"
                             " WHERE status = 'downloaded'"),
                "conditions": one("SELECT COUNT(DISTINCT condition) FROM dataset_conditions"),
            }

    # ------------------------------------------------------------ files
    def record_file(self, ds_id: str, url: str, status: str, **kw: Any) -> int:
        fields = {"filename": None, "local_path": None, "bytes": None, "sha256": None,
                  "content_type": None, "note": None, **kw}
        with self._write() as c:
            c.execute(
                "INSERT INTO files (dataset_id, url, status, fetched_at, filename,"
                " local_path, bytes, sha256, content_type, note)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (dataset_id, url) DO UPDATE SET status = excluded.status,"
                " fetched_at = excluded.fetched_at, filename = excluded.filename,"
                " local_path = excluded.local_path, bytes = excluded.bytes,"
                " sha256 = excluded.sha256, content_type = excluded.content_type,"
                " note = excluded.note",
                (ds_id, url, status, now_iso(), fields["filename"], fields["local_path"],
                 fields["bytes"], fields["sha256"], fields["content_type"], fields["note"]))
            return c.execute("SELECT id FROM files WHERE dataset_id = ? AND url = ?",
                             (ds_id, url)).fetchone()[0]

    def get_file(self, file_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return dict(row) if row else None

    def file_urls(self, ds_id: str) -> dict[str, str]:
        with self._conn() as c:
            return {r["url"]: r["status"] for r in c.execute(
                "SELECT url, status FROM files WHERE dataset_id = ?", (ds_id,))}

    # ------------------------------------------------------------ conditions
    def upsert_condition(self, name: str, display: str | None = None,
                         synonyms: Iterable[str] = (), fda_terms: Iterable[str] = ()) -> str:
        key = normalize_condition(name)
        with self._write() as c:
            row = c.execute("SELECT * FROM conditions WHERE name = ?", (key,)).fetchone()
            syn = list(dict.fromkeys(
                (json.loads(row["synonyms"]) if row else []) + [s.lower() for s in synonyms]))
            terms = list(dict.fromkeys(
                (json.loads(row["fda_terms"]) if row else []) + [t.lower() for t in fda_terms]))
            disp = display or (row["display"] if row else name.strip().title())
            c.execute(
                "INSERT INTO conditions (name, display, synonyms, fda_terms) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (name) DO UPDATE SET display = excluded.display,"
                " synonyms = excluded.synonyms, fda_terms = excluded.fda_terms",
                (key, disp, json.dumps(syn), json.dumps(terms)))
        return key

    def set_condition_510k(self, name: str, count: int | None) -> None:
        with self._write() as c:
            c.execute("UPDATE conditions SET fda_510k_count = ?, fda_checked_at = ?"
                      " WHERE name = ?", (count, now_iso(), normalize_condition(name)))

    def get_condition(self, name: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM conditions WHERE name = ?",
                            (normalize_condition(name),)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["synonyms"] = json.loads(d["synonyms"])
        d["fda_terms"] = json.loads(d["fda_terms"])
        return d

    def conditions_ranked(self, only_with_datasets: bool = False) -> list[dict]:
        """Directory view: conditions ranked by FDA 510(k) clearances, then
        by how many datasets we hold for them."""
        having = "HAVING n_datasets > 0" if only_with_datasets else ""
        with self._conn() as c:
            rows = c.execute(f"""
                SELECT c.name, c.display, c.fda_510k_count AS openfda_510k,
                       c.fda_denovo_count AS openfda_denovo, c.fda_checked_at,
                       c.fda_synced_at,
                       (SELECT COUNT(*) FROM condition_devices cd JOIN devices v
                          ON v.k_number = cd.k_number WHERE cd.condition = c.name
                          AND v.submission_type = '510k') AS local_510k,
                       (SELECT COUNT(*) FROM condition_devices cd JOIN devices v
                          ON v.k_number = cd.k_number WHERE cd.condition = c.name
                          AND v.submission_type = 'denovo') AS local_denovo,
                       (SELECT COUNT(*) FROM condition_devices cd WHERE cd.condition = c.name
                          AND cd.source = 'llm') AS n_mapped,
                       (SELECT COUNT(*) FROM condition_devices cd JOIN devices v
                          ON v.k_number = cd.k_number WHERE cd.condition = c.name
                          AND v.is_software = 1 AND v.submission_type = '510k') AS sw_510k,
                       (SELECT COUNT(*) FROM condition_devices cd JOIN devices v
                          ON v.k_number = cd.k_number WHERE cd.condition = c.name
                          AND v.is_software = 1 AND v.submission_type = 'denovo') AS sw_denovo,
                       (SELECT COUNT(*) FROM condition_devices cd JOIN devices v
                          ON v.k_number = cd.k_number WHERE cd.condition = c.name
                          AND v.is_ai = 1) AS n_ai,
                       c.synonyms, COUNT(dc.dataset_id) AS n_datasets,
                       SUM(CASE WHEN d.access_type = 'open' THEN 1 ELSE 0 END) AS n_open,
                       SUM(CASE WHEN d.download_status IN ('downloaded', 'partial')
                           THEN 1 ELSE 0 END) AS n_downloaded
                FROM conditions c
                LEFT JOIN dataset_conditions dc ON dc.condition = c.name
                LEFT JOIN datasets d ON d.id = dc.dataset_id
                GROUP BY c.name {having}
            """).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # Counts = stored submissions for the condition (openFDA name matches
            # plus Claude's AI-list mappings). Before the first sync, fall back to
            # openFDA's own total; if openFDA matched more than we store (capped),
            # keep its larger total.
            known = d["fda_synced_at"] is not None or d["local_510k"] or d["local_denovo"]
            d["fda_510k_count"] = (max(d["local_510k"], d["openfda_510k"] or 0) if known
                                   else d["openfda_510k"])
            d["fda_denovo_count"] = (max(d["local_denovo"], d["openfda_denovo"] or 0)
                                     if known else d["openfda_denovo"])
            d["synonyms"] = json.loads(d["synonyms"])
            d["n_open"] = d["n_open"] or 0
            d["n_downloaded"] = d["n_downloaded"] or 0
            out.append(d)
        out.sort(key=lambda d: (-(d["fda_510k_count"] if d["fda_510k_count"] is not None else -1),
                                -(d["fda_denovo_count"] or 0), -d["n_datasets"], d["name"]))
        return out

    def match_conditions(self, q: str) -> list[str]:
        """Conditions whose name or a synonym appears (as whole words) in q."""
        text_ = " " + " ".join(re.findall(r"[a-z0-9]+", q.lower())) + " "
        hits = []
        with self._conn() as c:
            for r in c.execute("SELECT name, synonyms FROM conditions"):
                names = [r["name"], *json.loads(r["synonyms"])]
                for n in names:
                    n_norm = " ".join(re.findall(r"[a-z0-9]+", n.lower()))
                    if n_norm and f" {n_norm} " in text_:
                        hits.append(r["name"])
                        break
        return hits

    # ------------------------------------------------------------ crawls
    def create_crawl(self, mode: str, query: str | None, minutes: int) -> int:
        with self._write() as c:
            cur = c.execute(
                "INSERT INTO crawls (mode, query, query_norm, status, minutes, started_at)"
                " VALUES (?, ?, ?, 'queued', ?, ?)",
                (mode, query, normalize_query(query) if query else None, minutes, now_iso()))
            return int(cur.lastrowid)

    def update_crawl(self, crawl_id: int, **fields: Any) -> None:
        if "plan" in fields and not isinstance(fields["plan"], (str, type(None))):
            fields["plan"] = json.dumps(fields["plan"])
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        with self._write() as c:
            c.execute(f"UPDATE crawls SET {sets} WHERE id = :id", {**fields, "id": crawl_id})

    def add_usage(self, crawl_id: int, input_tokens: int, output_tokens: int) -> None:
        with self._write() as c:
            c.execute("UPDATE crawls SET input_tokens = input_tokens + ?,"
                      " output_tokens = output_tokens + ? WHERE id = ?",
                      (input_tokens, output_tokens, crawl_id))

    def log_crawl(self, crawl_id: int, message: str, keep: int = 300) -> None:
        with self._write() as c:
            row = c.execute("SELECT log FROM crawls WHERE id = ?", (crawl_id,)).fetchone()
            if not row:
                return
            log = json.loads(row["log"])
            log.append({"at": now_iso(), "msg": message[:500]})
            c.execute("UPDATE crawls SET log = ? WHERE id = ?",
                      (json.dumps(log[-keep:]), crawl_id))

    def add_crawl_hit(self, crawl_id: int, ds_id: str, is_new: bool) -> None:
        with self._write() as c:
            c.execute("INSERT OR IGNORE INTO crawl_hits VALUES (?, ?, ?, ?)",
                      (crawl_id, ds_id, int(is_new), now_iso()))

    def get_crawl(self, crawl_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM crawls WHERE id = ?", (crawl_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["plan"] = json.loads(d["plan"]) if d["plan"] else None
            d["log"] = json.loads(d["log"])
            hits = c.execute("SELECT dataset_id, is_new FROM crawl_hits WHERE crawl_id = ?"
                             " ORDER BY at", (crawl_id,)).fetchall()
            d["hits"] = [r["dataset_id"] for r in hits]
            d["new_hits"] = [r["dataset_id"] for r in hits if r["is_new"]]
        return d

    def list_crawls(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT c.id, c.mode, c.query, c.status, c.minutes, c.started_at,"
                " c.finished_at, c.error, c.input_tokens, c.output_tokens,"
                " (SELECT COUNT(*) FROM crawl_hits h WHERE h.crawl_id = c.id) AS n_hits,"
                " (SELECT COUNT(*) FROM crawl_hits h WHERE h.crawl_id = c.id AND h.is_new)"
                "   AS n_new"
                " FROM crawls c ORDER BY c.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def memo_for_query(self, query: str) -> dict:
        """The memoized side of a search: datasets earlier crawls of the same
        (normalized) query found, the latest crawl, and its plan's expansion
        terms (condition names + synonyms) for widening the local search."""
        qn = normalize_query(query)
        with self._conn() as c:
            crawls = c.execute(
                "SELECT id, status, started_at, finished_at, plan FROM crawls"
                " WHERE query_norm = ? ORDER BY id DESC", (qn,)).fetchall()
            ids = [r["dataset_id"] for r in c.execute(
                "SELECT DISTINCT h.dataset_id FROM crawl_hits h JOIN crawls c"
                " ON c.id = h.crawl_id WHERE c.query_norm = ?", (qn,))]
        terms: list[str] = []
        for r in crawls:
            if r["plan"]:
                plan = json.loads(r["plan"])
                for cond in plan.get("conditions", []):
                    terms += [cond.get("name", ""), *cond.get("synonyms", [])]
                break
        latest = dict(crawls[0]) if crawls else None
        if latest:
            latest.pop("plan", None)
        return {"dataset_ids": ids, "latest_crawl": latest,
                "expansion_terms": [t for t in terms if t]}

    def recent_crawl_for(self, query: str, hours: int) -> dict | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with self._conn() as c:
            row = c.execute(
                "SELECT id, status, started_at FROM crawls WHERE query_norm = ?"
                " AND (status IN ('queued', 'running') OR started_at >= ?)"
                " AND status != 'failed' ORDER BY id DESC LIMIT 1",
                (normalize_query(query), cutoff)).fetchone()
        return dict(row) if row else None

    def mark_stale_crawls(self) -> None:
        """On boot, crawls left 'running' by a dead process are interrupted."""
        with self._write() as c:
            c.execute("UPDATE crawls SET status = 'interrupted', finished_at = ?"
                      " WHERE status IN ('queued', 'running')", (now_iso(),))

    # ------------------------------------------------------------ literature
    def upsert_article(self, art: dict) -> str:
        """Insert/refresh one article. ``art`` needs id + title; other fields
        fill in when present (citation counts always take the latest)."""
        cols = ("doi", "pmid", "pmcid", "openalex_id", "authors", "venue", "year", "url")
        with self._write() as c:
            c.execute(
                "INSERT INTO articles (id, title, cited_by_count, updated_at, "
                + ", ".join(cols) + ") VALUES (?, ?, ?, ?, " + ", ".join("?" * len(cols)) + ")"
                " ON CONFLICT (id) DO UPDATE SET title = excluded.title,"
                " cited_by_count = MAX(articles.cited_by_count, excluded.cited_by_count),"
                " updated_at = excluded.updated_at, "
                + ", ".join(f"{k} = COALESCE(excluded.{k}, articles.{k})" for k in cols),
                (art["id"], art["title"], int(art.get("cited_by_count") or 0), now_iso(),
                 *[art.get(k) for k in cols]))
        return art["id"]

    def find_article_id(self, pmid: str | None = None, doi: str | None = None,
                        openalex_id: str | None = None) -> str | None:
        """Existing article row for any of these identifiers (cross-source dedup)."""
        with self._conn() as c:
            for col, val in (("pmid", pmid), ("doi", doi), ("openalex_id", openalex_id)):
                if val:
                    row = c.execute(f"SELECT id FROM articles WHERE {col} = ?", (val,)).fetchone()
                    if row:
                        return row["id"]
        return None

    def link_article(self, ds_id: str, article_id: str, relation: str, source: str,
                     matched: str | None = None) -> bool:
        """Associate an article with a dataset. relation: cites | mentions |
        descriptor. Returns True if the pair is new."""
        with self._write() as c:
            row = c.execute("SELECT sources FROM dataset_articles WHERE dataset_id = ?"
                            " AND article_id = ?", (ds_id, article_id)).fetchone()
            flags = {"cites": int(relation == "cites"), "mentions": int(relation == "mentions"),
                     "is_descriptor": int(relation == "descriptor")}
            if row is None:
                c.execute("INSERT INTO dataset_articles (dataset_id, article_id, cites, mentions,"
                          " is_descriptor, sources, matched, first_seen)"
                          " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (ds_id, article_id, flags["cites"], flags["mentions"],
                           flags["is_descriptor"], source, matched, now_iso()))
                return True
            sources = ",".join(dict.fromkeys(filter(None, row["sources"].split(",") + [source])))
            c.execute("UPDATE dataset_articles SET cites = MAX(cites, ?), mentions = MAX(mentions, ?),"
                      " is_descriptor = MAX(is_descriptor, ?), sources = ?,"
                      " matched = COALESCE(matched, ?) WHERE dataset_id = ? AND article_id = ?",
                      (flags["cites"], flags["mentions"], flags["is_descriptor"], sources,
                       matched, ds_id, article_id))
            return False

    def dataset_articles(self, ds_id: str, relation: str | None = None, limit: int = 50,
                         offset: int = 0) -> dict:
        """Articles for a dataset: descriptor papers first, then papers that
        cite them, then name mentions; most-cited first within each tier."""
        where = "da.dataset_id = ?"
        if relation == "cites":
            where += " AND da.cites = 1"
        elif relation == "mentions":
            where += " AND da.mentions = 1 AND da.cites = 0"
        with self._conn() as c:
            rows = c.execute(f"""
                SELECT a.*, da.cites, da.mentions, da.is_descriptor, da.sources, da.matched
                FROM dataset_articles da JOIN articles a ON a.id = da.article_id
                WHERE {where}
                ORDER BY da.is_descriptor DESC, da.cites DESC, a.cited_by_count DESC, a.year DESC
                LIMIT ? OFFSET ?""", (ds_id, limit, offset)).fetchall()
            counts = c.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(cites), 0) AS cites,"
                " COALESCE(SUM(CASE WHEN mentions = 1 AND cites = 0 THEN 1 ELSE 0 END), 0)"
                " AS mentions_only FROM dataset_articles WHERE dataset_id = ?"
                " AND is_descriptor = 0", (ds_id,)).fetchone()
        return {**dict(counts), "items": [dict(r) for r in rows],
                "state": self.literature_state(ds_id)}

    def article_counts(self, ds_ids: Iterable[str]) -> dict[str, int]:
        ids = list(ds_ids)
        if not ids:
            return {}
        with self._conn() as c:
            rows = c.execute(
                "SELECT dataset_id, COUNT(*) AS n FROM dataset_articles WHERE is_descriptor = 0"
                f" AND dataset_id IN ({','.join('?' * len(ids))}) GROUP BY dataset_id",
                ids).fetchall()
        return {r["dataset_id"]: r["n"] for r in rows}

    def literature_state(self, ds_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM literature_state WHERE dataset_id = ?",
                            (ds_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for f in ("descriptors", "aliases", "streams"):
            d[f] = json.loads(d[f])
        return d

    def save_literature_state(self, ds_id: str, **fields: Any) -> None:
        for f in ("descriptors", "aliases", "streams"):
            if f in fields and not isinstance(fields[f], str):
                fields[f] = json.dumps(fields[f])
        fields["last_worked"] = now_iso()
        with self._write() as c:
            exists = c.execute("SELECT 1 FROM literature_state WHERE dataset_id = ?",
                               (ds_id,)).fetchone()
            if exists:
                sets = ", ".join(f"{k} = :{k}" for k in fields)
                c.execute(f"UPDATE literature_state SET {sets} WHERE dataset_id = :id",
                          {**fields, "id": ds_id})
            else:
                fields.setdefault("status", "active")
                cols = ["dataset_id", *fields]
                c.execute(f"INSERT INTO literature_state ({', '.join(cols)}) VALUES"
                          f" ({', '.join(':' + k for k in cols)})", {**fields, "dataset_id": ds_id})

    def next_literature_dataset(self, refresh_days: int) -> str | None:
        """What the literature worker should touch next: datasets never
        processed (oldest first), then active ones least-recently worked
        (round-robin, so every dataset gets its most-cited papers early),
        then completed ones due for a refresh."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=refresh_days)).isoformat()
        with self._conn() as c:
            row = c.execute(
                "SELECT d.id FROM datasets d LEFT JOIN literature_state l ON l.dataset_id = d.id"
                " WHERE l.dataset_id IS NULL ORDER BY d.first_seen LIMIT 1").fetchone()
            if row:
                return row["id"]
            row = c.execute("SELECT dataset_id FROM literature_state"
                            " WHERE status IN ('active', 'retry')"
                            " ORDER BY last_worked LIMIT 1").fetchone()
            if row:
                return row["dataset_id"]
            row = c.execute(
                "SELECT dataset_id FROM literature_state WHERE status IN ('complete', 'unresolved')"
                " AND COALESCE(completed_at, last_worked) < ? ORDER BY last_worked LIMIT 1",
                (cutoff,)).fetchone()
        return row["dataset_id"] if row else None

    def reset_literature(self, ds_id: str) -> None:
        """Forget resolution + cursors (articles already linked are kept)."""
        with self._write() as c:
            c.execute("DELETE FROM literature_state WHERE dataset_id = ?", (ds_id,))

    def literature_summary(self) -> dict:
        with self._conn() as c:
            one = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
            by_status = {r["status"]: r["n"] for r in c.execute(
                "SELECT status, COUNT(*) AS n FROM literature_state GROUP BY status")}
            return {
                "articles": one("SELECT COUNT(*) FROM articles"),
                "links": one("SELECT COUNT(*) FROM dataset_articles WHERE is_descriptor = 0"),
                "datasets_pending": one(
                    "SELECT COUNT(*) FROM datasets d LEFT JOIN literature_state l"
                    " ON l.dataset_id = d.id WHERE l.dataset_id IS NULL"),
                "by_status": by_status,
            }

    # ------------------------------------------------------------ FDA devices
    _DEVICE_COLS = ("submission_type", "device_name", "applicant", "contact", "address",
                    "country_code", "decision_date", "decision_code", "decision_description",
                    "date_received", "product_code", "generic_name", "device_class",
                    "regulation_number", "medical_specialty", "advisory_committee",
                    "clearance_type", "statement_or_summary", "third_party_flag",
                    "expedited_review_flag", "raw")

    def upsert_devices(self, devices: list[dict]) -> None:
        """Insert/refresh submissions. ``is_software`` comes from the record;
        ``is_ai`` only ever goes up (it is also set by the FDA AI list and by
        the summary PDF text, which a plain record refresh must not undo)."""
        cols = self._DEVICE_COLS
        ts = now_iso()
        with self._write() as c:
            c.executemany(
                f"INSERT INTO devices (k_number, updated_at, is_software, {', '.join(cols)})"
                f" VALUES (?, ?, ?, {', '.join('?' * len(cols))}) ON CONFLICT (k_number) DO UPDATE"
                " SET updated_at = excluded.updated_at,"
                " is_software = MAX(devices.is_ai, excluded.is_software), "
                + ", ".join(f"{k} = COALESCE(excluded.{k}, devices.{k})" for k in cols),
                [(d["k_number"], ts, int(bool(d.get("is_software"))), *[d.get(k) for k in cols])
                 for d in devices])

    def insert_device_stubs(self, stubs: list[dict]) -> None:
        cols = ("submission_type", "device_name", "applicant", "decision_date",
                "advisory_committee", "product_code")
        with self._write() as c:
            c.executemany(
                f"INSERT OR IGNORE INTO devices (k_number, updated_at, is_software,"
                f" {', '.join(cols)}) VALUES (?, ?, 1, {', '.join('?' * len(cols))})",
                [(d["k_number"], now_iso(), *[d.get(k) for k in cols]) for d in stubs])

    def reclassify_software(self, classify) -> int:
        """Re-run the software heuristic over every stored record (used once
        after upgrading, since older rows predate the flag)."""
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT k_number, device_name, generic_name, regulation_number FROM devices")]
        hits = {r["k_number"] for r in rows if classify(r)}
        with self._write() as c:
            # AI-flagged rows stay software whatever the name says.
            c.executemany("UPDATE devices SET is_software = CASE WHEN is_ai = 1 THEN 1"
                          " ELSE ? END WHERE k_number = ?",
                          [(int(r["k_number"] in hits), r["k_number"]) for r in rows])
        return len(hits)

    def devices_to_map(self, limit: int) -> list[dict]:
        """AI-list devices Claude hasn't assigned to conditions yet, newest first."""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT k_number, submission_type, device_name, applicant, generic_name,"
                " product_code, advisory_committee, medical_specialty, regulation_number"
                " FROM devices WHERE is_ai = 1 AND conditions_mapped_at IS NULL"
                " ORDER BY decision_date DESC LIMIT ?", (limit,))]

    def condition_names(self) -> list[str]:
        with self._conn() as c:
            return [r["name"] for r in c.execute("SELECT name FROM conditions ORDER BY name")]

    def save_device_conditions(self, mapping: dict[str, list[str]]) -> int:
        """Record Claude's device → condition assignments (new conditions are
        created). Every device in ``mapping`` is marked mapped, including
        condition-agnostic ones (empty list). Returns links written."""
        pairs = [(normalize_condition(cn), k) for k, conds in mapping.items()
                 for cn in conds if cn and cn.strip()]
        for cond, _ in pairs:
            self.upsert_condition(cond)
        with self._write() as c:
            c.executemany("DELETE FROM condition_devices WHERE k_number = ? AND source = 'llm'",
                          [(k,) for k in mapping])
            c.executemany("INSERT OR IGNORE INTO condition_devices (condition, k_number, source)"
                          " VALUES (?, ?, 'llm')", pairs)
            c.executemany("UPDATE devices SET conditions_mapped_at = ? WHERE k_number = ?",
                          [(now_iso(), k) for k in mapping])
        return len(pairs)

    def mark_ai(self, k_numbers: list[str], source: str) -> None:
        """Flag submissions as AI-enabled (and therefore software). The FDA
        list outranks a summary-text match as the recorded source."""
        with self._write() as c:
            c.executemany(
                "UPDATE devices SET is_ai = 1, is_software = 1, ai_source = CASE"
                " WHEN ai_source = 'fda_list' THEN ai_source ELSE ? END WHERE k_number = ?",
                [(source, k) for k in k_numbers])

    def kv_get(self, k: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
        return row["v"] if row else None

    def kv_set(self, k: str, v: str) -> None:
        with self._write() as c:
            c.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v",
                      (k, v))

    def missing_devices(self, k_numbers: list[str]) -> list[str]:
        """Numbers with no openFDA-backed record yet (stub rows count as missing)."""
        if not k_numbers:
            return []
        with self._conn() as c:
            have = {r["k_number"] for r in c.execute(
                f"SELECT k_number FROM devices WHERE raw IS NOT NULL AND k_number IN"
                f" ({','.join('?' * len(k_numbers))})", k_numbers)}
        return [k for k in k_numbers if k not in have]

    def set_condition_devices(self, name: str, k_numbers: list[str], n_510k: int,
                              n_denovo: int, capped: bool = False) -> None:
        key = normalize_condition(name)
        with self._write() as c:
            # Only name matches are replaced; Claude's mappings survive a re-sync.
            c.execute("DELETE FROM condition_devices WHERE condition = ? AND source = 'name'",
                      (key,))
            c.executemany("INSERT OR IGNORE INTO condition_devices (condition, k_number, source)"
                          " VALUES (?, ?, 'name')", [(key, k) for k in k_numbers])
            c.execute("UPDATE conditions SET fda_510k_count = ?, fda_denovo_count = ?,"
                      " fda_checked_at = ?, fda_synced_at = ?, fda_devices_capped = ?"
                      " WHERE name = ?",
                      (n_510k, n_denovo, now_iso(), now_iso(), int(capped), key))

    def condition_due_for_device_sync(self, days: int) -> str | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._conn() as c:
            row = c.execute("SELECT name FROM conditions WHERE fda_synced_at IS NULL"
                            " OR fda_synced_at < ? ORDER BY fda_synced_at IS NOT NULL,"
                            " fda_synced_at LIMIT 1", (cutoff,)).fetchone()
        return row["name"] if row else None

    _DEVICE_SORTS = {"decision_date": "d.decision_date", "date_received": "d.date_received",
                     "applicant": "d.applicant COLLATE NOCASE",
                     "device_name": "d.device_name COLLATE NOCASE", "k_number": "d.k_number",
                     "type": "d.submission_type", "product_code": "d.product_code",
                     "links": "n_links"}

    def list_devices(self, condition: str | None = None, submission_type: str | None = None,
                     q: str | None = None, dataset_id: str | None = None,
                     linked_only: bool = False, category: str | None = None,
                     sort: str = "decision_date",
                     direction: str = "desc", limit: int = 50, offset: int = 0) -> dict:
        where, params = ["1=1"], []
        join = ""
        if condition:
            join += " JOIN condition_devices cd ON cd.k_number = d.k_number AND cd.condition = ?"
            params.append(normalize_condition(condition))
        if dataset_id:
            where.append("d.k_number IN (SELECT k_number FROM device_links WHERE dataset_id = ?)")
            params.append(dataset_id)
        if submission_type in ("510k", "denovo", "pma"):
            where.append("d.submission_type = ?")
            params.append(submission_type)
        if q:
            where.append("(d.device_name LIKE ? OR d.applicant LIKE ? OR d.k_number LIKE ?"
                         " OR d.product_code LIKE ? OR d.generic_name LIKE ?)")
            params += [f"%{q}%"] * 5
        if linked_only:
            where.append("d.k_number IN (SELECT k_number FROM device_links)")
        if category == "software":
            where.append("d.is_software = 1")
        elif category == "ai":
            where.append("d.is_ai = 1")
        order = self._DEVICE_SORTS.get(sort, "d.decision_date")
        direction = "ASC" if str(direction).lower() == "asc" else "DESC"
        base = f"FROM devices d{join} WHERE {' AND '.join(where)}"
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
            facets = dict(c.execute(
                f"SELECT COALESCE(SUM(d.is_software), 0) AS software,"
                f" COALESCE(SUM(d.is_ai), 0) AS ai,"
                f" COALESCE(SUM(d.submission_type = '510k'), 0) AS n_510k,"
                f" COALESCE(SUM(d.submission_type = 'denovo'), 0) AS n_denovo,"
                f" COALESCE(SUM(d.submission_type = 'pma'), 0) AS n_pma {base}",
                params).fetchone())
            rows = c.execute(
                f"""SELECT d.k_number, d.submission_type, d.device_name, d.applicant,
                       d.decision_date, d.date_received, d.decision_description,
                       d.product_code, d.generic_name, d.device_class, d.clearance_type,
                       d.country_code, d.is_software, d.is_ai, d.ai_source,
                       (SELECT COUNT(*) FROM device_links l WHERE l.k_number = d.k_number)
                         AS n_links,
                       (SELECT status FROM device_docs x WHERE x.k_number = d.k_number)
                         AS doc_status
                {base} ORDER BY {order} {direction}, d.k_number DESC LIMIT ? OFFSET ?""",
                [*params, limit, offset]).fetchall()
        return {"total": total, "facets": facets, "items": [dict(r) for r in rows]}

    def get_device(self, k: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM devices WHERE k_number = ?", (k,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["raw"] = json.loads(d["raw"]) if d["raw"] else None
            d["conditions"] = [r["condition"] for r in c.execute(
                "SELECT condition FROM condition_devices WHERE k_number = ?", (k,))]
            d["condition_sources"] = {r["condition"]: r["source"] for r in c.execute(
                "SELECT condition, source FROM condition_devices WHERE k_number = ?", (k,))}
            doc = c.execute("SELECT k_number, status, requested, pdf_url, pages, predicates,"
                            " extracted, extracted_at, error, fetched_at FROM device_docs"
                            " WHERE k_number = ?", (k,)).fetchone()
            d["doc"] = None
            if doc:
                d["doc"] = dict(doc)
                d["doc"]["predicates"] = json.loads(doc["predicates"])
                d["doc"]["extracted"] = json.loads(doc["extracted"]) if doc["extracted"] else None
                known = {r["k_number"] for r in c.execute(
                    f"SELECT k_number FROM devices WHERE k_number IN"
                    f" ({','.join('?' * len(d['doc']['predicates']))})",
                    d["doc"]["predicates"])} if d["doc"]["predicates"] else set()
                d["doc"]["predicates"] = [{"k_number": p, "known": p in known}
                                          for p in d["doc"]["predicates"]]
            d["links"] = [dict(r) for r in c.execute(
                """SELECT l.dataset_id, ds.title AS dataset_title, l.article_id,
                          a.title AS article_title, a.url AS article_url, l.via, l.matched,
                          l.snippet
                   FROM device_links l JOIN datasets ds ON ds.id = l.dataset_id
                   LEFT JOIN articles a ON a.id = l.article_id
                   WHERE l.k_number = ? ORDER BY l.article_id = '' DESC, ds.title""", (k,))]
        return d

    def device_text(self, k: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT text FROM device_docs WHERE k_number = ?", (k,)).fetchone()
        return zlib.decompress(row["text"]).decode() if row and row["text"] else None

    def save_device_doc(self, k: str, status: str, pdf_url: str | None = None,
                        pages: int | None = None, text: str | None = None,
                        predicates: list[str] | None = None, error: str | None = None) -> None:
        blob = zlib.compress(text.encode()) if text else None
        with self._write() as c:
            c.execute(
                "INSERT INTO device_docs (k_number, status, pdf_url, pages, text, predicates,"
                " error, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (k_number) DO UPDATE SET status = excluded.status,"
                " pdf_url = excluded.pdf_url, pages = excluded.pages, text = excluded.text,"
                " predicates = excluded.predicates, error = excluded.error,"
                " fetched_at = excluded.fetched_at",
                (k, status, pdf_url, pages, blob, json.dumps(predicates or []), error, now_iso()))

    def save_device_extraction(self, k: str, extracted: dict | None, error: str | None = None) -> None:
        with self._write() as c:
            c.execute("UPDATE device_docs SET extracted = ?, extracted_at = ?, requested = 0,"
                      " error = COALESCE(?, error) WHERE k_number = ?",
                      (json.dumps(extracted) if extracted else None, now_iso(), error, k))

    def request_device_analysis(self, k: str) -> None:
        """Move a submission to the front of the document worker's queue."""
        with self._write() as c:
            c.execute("INSERT INTO device_docs (k_number, status, requested) VALUES (?, 'queued', 1)"
                      " ON CONFLICT (k_number) DO UPDATE SET requested = 1", (k,))

    def next_device_doc(self, want_extraction: bool) -> tuple[str, str] | None:
        """(k_number, job) for the document worker: 'fetch' a summary PDF not
        yet read, or 'extract' (LLM summary) for one a user opened. User
        requests first, then submissions under conditions that have datasets,
        then everything else, newest decisions first."""
        with self._conn() as c:
            reqs = c.execute("SELECT k_number, status, extracted FROM device_docs"
                             " WHERE requested = 1 ORDER BY fetched_at").fetchall()
        stale = []
        for r in reqs:
            if r["status"] == "queued":
                return r["k_number"], "fetch"
            if r["status"] == "done" and want_extraction and not r["extracted"]:
                return r["k_number"], "extract"
            stale.append(r["k_number"])  # nothing left to do for this request
        if stale:
            with self._write() as c:
                c.executemany("UPDATE device_docs SET requested = 0 WHERE k_number = ?",
                              [(k,) for k in stale])
        with self._conn() as c:
            row = c.execute(
                """SELECT d.k_number FROM devices d
                   LEFT JOIN device_docs x ON x.k_number = d.k_number
                   WHERE x.k_number IS NULL OR x.status = 'queued'
                   ORDER BY EXISTS (SELECT 1 FROM condition_devices cd
                                    JOIN dataset_conditions dc ON dc.condition = cd.condition
                                    WHERE cd.k_number = d.k_number) DESC,
                            d.decision_date DESC LIMIT 1""").fetchone()
        return (row["k_number"], "fetch") if row else None

    def link_targets(self) -> dict:
        """What a summary PDF is matched against: per-dataset aliases (from the
        literature linker, else a distinctive title) and descriptor papers."""
        with self._conn() as c:
            ds = c.execute("SELECT d.id, d.title, l.aliases, l.descriptors FROM datasets d"
                           " LEFT JOIN literature_state l ON l.dataset_id = d.id").fetchall()
        aliases: list[tuple[str, str]] = []
        titles: list[tuple[str, str, str]] = []
        for r in ds:
            names = json.loads(r["aliases"]) if r["aliases"] else []
            if not names and len(r["title"].split()) >= 2 and len(r["title"]) >= 10:
                names = [r["title"]]
            aliases += [(r["id"], a) for a in names]
            for dsc in json.loads(r["descriptors"]) if r["descriptors"] else []:
                if dsc.get("title") and len(dsc["title"]) >= 30:
                    titles.append((r["id"], dsc["article_id"], dsc["title"]))
        return {"aliases": aliases, "titles": titles}

    def datasets_for_article(self, article_id: str) -> list[str]:
        with self._conn() as c:
            return [r["dataset_id"] for r in c.execute(
                "SELECT dataset_id FROM dataset_articles WHERE article_id = ?", (article_id,))]

    def replace_device_links(self, k: str, links: list[dict]) -> None:
        with self._write() as c:
            c.execute("DELETE FROM device_links WHERE k_number = ?", (k,))
            c.executemany(
                "INSERT OR IGNORE INTO device_links (k_number, dataset_id, article_id, via,"
                " matched, snippet) VALUES (?, ?, ?, ?, ?, ?)",
                [(k, l["dataset_id"], l.get("article_id") or "", l["via"], l.get("matched"),
                  l.get("snippet")) for l in links])

    def devices_for_articles(self, article_ids: list[str]) -> dict[str, list[str]]:
        if not article_ids:
            return {}
        with self._conn() as c:
            rows = c.execute(
                "SELECT article_id, k_number FROM device_links WHERE article_id IN"
                f" ({','.join('?' * len(article_ids))}) ORDER BY k_number", article_ids).fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["article_id"], []).append(r["k_number"])
        return out

    def device_summary(self) -> dict:
        with self._conn() as c:
            one = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
            return {
                "devices": one("SELECT COUNT(*) FROM devices"),
                "denovo": one("SELECT COUNT(*) FROM devices WHERE submission_type = 'denovo'"),
                "software": one("SELECT COUNT(*) FROM devices WHERE is_software = 1"),
                "ai": one("SELECT COUNT(*) FROM devices WHERE is_ai = 1"),
                "ai_mapped_to_conditions": one("SELECT COUNT(*) FROM devices WHERE is_ai = 1"
                                               " AND conditions_mapped_at IS NOT NULL"),
                "docs_read": one("SELECT COUNT(*) FROM device_docs WHERE status = 'done'"),
                "docs_extracted": one("SELECT COUNT(*) FROM device_docs WHERE extracted IS NOT NULL"),
                "linked": one("SELECT COUNT(DISTINCT k_number) FROM device_links"),
            }

"""Database schema and connection management for PaperDB.

All table definitions, indexes, and initialization logic live here.
SQLite in WAL mode for multi-user concurrent reads.
"""

from __future__ import annotations

import sqlite3
import os
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Schema version — bump when schema changes; used for future migrations
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 3


def _pragmas(conn: sqlite3.Connection) -> None:
    """Enable WAL mode, foreign keys, and sensible defaults."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")


# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,
    role        TEXT NOT NULL DEFAULT 'researcher',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_PAPERS = """
CREATE TABLE IF NOT EXISTS papers (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    title_en            TEXT,
    authors_raw         TEXT,
    institution         TEXT,
    source_type         TEXT NOT NULL,
    source_name         TEXT,
    source_url          TEXT,
    download_url        TEXT,
    github_url          TEXT,
    github_evidence_type TEXT,
    github_evidence_url TEXT,
    publication_date    TEXT,
    market              TEXT,
    frequency           TEXT,
    language            TEXT,
    abstract            TEXT,
    abstract_en         TEXT,
    ai_summary          TEXT,
    file_path           TEXT,
    file_format         TEXT,
    access_status       TEXT NOT NULL DEFAULT 'queued',
    access_notes        TEXT,
    content_hash        TEXT,
    metadata_hash       TEXT,
    priority_score      INTEGER NOT NULL DEFAULT 0,
    quality_flag        TEXT NOT NULL DEFAULT 'ok',
    metadata_quality    TEXT NOT NULL DEFAULT 'partial',
    quality_screening_status TEXT NOT NULL DEFAULT 'metadata_only',
    lifecycle_status    TEXT NOT NULL DEFAULT 'active',
    ingestion_batch     TEXT,
    added_by            TEXT REFERENCES users(id),
    reviewed_by         TEXT REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_PAPER_LABELS = """
CREATE TABLE IF NOT EXISTS paper_labels (
    id          TEXT PRIMARY KEY,
    paper_id    TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    confidence  REAL,
    source      TEXT NOT NULL DEFAULT 'ai_auto',
    added_by    TEXT REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_PAPER_AUTHORS = """
CREATE TABLE IF NOT EXISTS paper_authors (
    id                 TEXT PRIMARY KEY,
    paper_id           TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    author_name        TEXT NOT NULL,
    author_name_en     TEXT,
    institution        TEXT,
    affiliation_source TEXT,
    affiliation_evidence_url TEXT,
    is_corresponding   INTEGER NOT NULL DEFAULT 0,
    author_order       INTEGER NOT NULL
);
"""

CREATE_USER_ANNOTATIONS = """
CREATE TABLE IF NOT EXISTS user_annotations (
    id          TEXT PRIMARY KEY,
    paper_id    TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users(id),
    note_type   TEXT NOT NULL,
    content     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_SEARCH_LOGS = """
CREATE TABLE IF NOT EXISTS search_logs (
    id              TEXT PRIMARY KEY,
    source_name     TEXT,
    query           TEXT,
    query_type      TEXT,
    results_count   INTEGER,
    new_papers      INTEGER,
    inspected_count INTEGER NOT NULL DEFAULT 0,
    accepted_count  INTEGER NOT NULL DEFAULT 0,
    rejected_count  INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER,
    searched_at     TEXT NOT NULL DEFAULT (datetime('now')),
    error           TEXT
);
"""

CREATE_SEARCH_CANDIDATES = """
CREATE TABLE IF NOT EXISTS search_candidates (
    id              TEXT PRIMARY KEY,
    search_log_id   TEXT REFERENCES search_logs(id) ON DELETE CASCADE,
    source_name     TEXT NOT NULL,
    source_id       TEXT,
    title           TEXT NOT NULL,
    source_url      TEXT,
    decision        TEXT NOT NULL,
    rejection_reason TEXT,
    relevance_score REAL,
    evidence        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_PAPER_INSTITUTIONS = """
CREATE TABLE IF NOT EXISTS paper_institutions (
    id              TEXT PRIMARY KEY,
    paper_id        TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    canonical_name  TEXT NOT NULL,
    raw_value       TEXT NOT NULL,
    matched_alias   TEXT NOT NULL,
    priority_rank   INTEGER NOT NULL,
    priority_score  INTEGER NOT NULL,
    match_source    TEXT NOT NULL,
    confidence      REAL NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(paper_id, canonical_name, raw_value)
);
"""

CREATE_DOWNLOAD_LOGS = """
CREATE TABLE IF NOT EXISTS download_logs (
    id            TEXT PRIMARY KEY,
    paper_id      TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    attempt_at    TEXT NOT NULL DEFAULT (datetime('now')),
    status        TEXT NOT NULL,
    http_status   INTEGER,
    error_detail  TEXT,
    file_size     INTEGER,
    finished_at   TEXT,
    retryable     INTEGER
);
"""


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_papers_metadata_hash ON papers(metadata_hash);",
    "CREATE INDEX IF NOT EXISTS idx_papers_access_status ON papers(access_status);",
    "CREATE INDEX IF NOT EXISTS idx_papers_source_type ON papers(source_type);",
    "CREATE INDEX IF NOT EXISTS idx_papers_download_url ON papers(download_url);",
    "CREATE INDEX IF NOT EXISTS idx_papers_priority ON papers(priority_score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_papers_added_by ON papers(added_by);",
    "CREATE INDEX IF NOT EXISTS idx_papers_institution ON papers(institution);",
    "CREATE INDEX IF NOT EXISTS idx_papers_github_url ON papers(github_url);",
    "CREATE INDEX IF NOT EXISTS idx_papers_publication_date ON papers(publication_date);",
    "CREATE INDEX IF NOT EXISTS idx_papers_lifecycle ON papers(lifecycle_status);",
    "CREATE INDEX IF NOT EXISTS idx_papers_screening ON papers(quality_screening_status);",
    "CREATE INDEX IF NOT EXISTS idx_labels_paper ON paper_labels(paper_id);",
    "CREATE INDEX IF NOT EXISTS idx_labels_label ON paper_labels(label);",
    "CREATE INDEX IF NOT EXISTS idx_labels_source ON paper_labels(source);",
    "CREATE INDEX IF NOT EXISTS idx_authors_paper ON paper_authors(paper_id);",
    "CREATE INDEX IF NOT EXISTS idx_authors_name ON paper_authors(author_name);",
    "CREATE INDEX IF NOT EXISTS idx_annotations_paper_user ON user_annotations(paper_id, user_id);",
    "CREATE INDEX IF NOT EXISTS idx_downloads_paper ON download_logs(paper_id);",
    "CREATE INDEX IF NOT EXISTS idx_candidates_search ON search_candidates(search_log_id);",
    "CREATE INDEX IF NOT EXISTS idx_candidates_decision ON search_candidates(decision);",
    "CREATE INDEX IF NOT EXISTS idx_paper_institutions_paper ON paper_institutions(paper_id);",
    "CREATE INDEX IF NOT EXISTS idx_paper_institutions_canonical ON paper_institutions(canonical_name);",
]


ALL_TABLES = [
    CREATE_USERS,
    CREATE_PAPERS,
    CREATE_PAPER_LABELS,
    CREATE_PAPER_AUTHORS,
    CREATE_USER_ANNOTATIONS,
    CREATE_SEARCH_LOGS,
    CREATE_SEARCH_CANDIDATES,
    CREATE_PAPER_INSTITUTIONS,
    CREATE_DOWNLOAD_LOGS,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database with WAL + FK pragmas.

    Args:
        db_path: Path to the SQLite file (e.g. ``paper_database/db/papers.sqlite``).

    Returns:
        A ``sqlite3.Connection`` with WAL mode enabled and ``row_factory`` set
        to ``sqlite3.Row`` for dict-like access.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _pragmas(conn)
    _ensure_schema_compat(conn)
    return conn


def _ensure_schema_compat(conn: sqlite3.Connection) -> None:
    """Apply lightweight compatibility migrations for existing databases."""
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'papers'"
        ).fetchone()
        if not table:
            return
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
    except sqlite3.OperationalError:
        return

    changed = False
    if "download_url" not in cols:
        conn.execute("ALTER TABLE papers ADD COLUMN download_url TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_download_url ON papers(download_url);")
        changed = True
    if "github_url" not in cols:
        conn.execute("ALTER TABLE papers ADD COLUMN github_url TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_github_url ON papers(github_url);")
        changed = True
    paper_columns = {
        "github_evidence_type": "TEXT",
        "github_evidence_url": "TEXT",
        "metadata_quality": "TEXT NOT NULL DEFAULT 'partial'",
        "quality_screening_status": "TEXT NOT NULL DEFAULT 'metadata_only'",
        "lifecycle_status": "TEXT NOT NULL DEFAULT 'active'",
    }
    for name, definition in paper_columns.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {name} {definition}")
            changed = True

    # Tables and additive columns are deliberately migrated in place so old
    # PaperDB roots remain usable without a separate migration command.
    conn.execute(CREATE_SEARCH_LOGS)
    conn.execute(CREATE_SEARCH_CANDIDATES)
    conn.execute(CREATE_PAPER_INSTITUTIONS)
    conn.execute(CREATE_DOWNLOAD_LOGS)
    for table, additions in {
        "search_logs": {
            "inspected_count": "INTEGER NOT NULL DEFAULT 0",
            "accepted_count": "INTEGER NOT NULL DEFAULT 0",
            "rejected_count": "INTEGER NOT NULL DEFAULT 0",
            "duplicate_count": "INTEGER NOT NULL DEFAULT 0",
            "latency_ms": "INTEGER",
        },
        "download_logs": {
            "finished_at": "TEXT",
            "retryable": "INTEGER",
        },
        "paper_authors": {
            "affiliation_source": "TEXT",
            "affiliation_evidence_url": "TEXT",
        },
    }.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                changed = True
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_lifecycle ON papers(lifecycle_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_screening ON papers(quality_screening_status)")
    conn.execute("""UPDATE papers SET quality_screening_status = 'full_text_available'
                    WHERE file_path IS NOT NULL
                      AND quality_screening_status = 'metadata_only'""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_search ON search_candidates(search_log_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_decision ON search_candidates(decision)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_institutions_paper ON paper_institutions(paper_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_institutions_canonical ON paper_institutions(canonical_name)")
    conn.commit()


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Create all tables and indexes if they don't exist.

    Idempotent — safe to call on an already-initialised database.

    Args:
        db_path: Path to the SQLite file.

    Returns:
        An open connection to the initialised database.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = get_db(db_path)

    for ddl in ALL_TABLES:
        conn.execute(ddl)

    for ddl in INDEXES:
        conn.execute(ddl)

    conn.commit()
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version, or 0 if uninitialised."""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


# ---------------------------------------------------------------------------
# Connection context manager for convenience
# ---------------------------------------------------------------------------

class Database:
    """Context manager that wraps a SQLite connection."""

    def __init__(self, db_path: str | Path):
        self._path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> sqlite3.Connection:
        self.conn = get_db(self._path)
        return self.conn

    def __exit__(self, *args) -> None:
        if self.conn:
            self.conn.close()

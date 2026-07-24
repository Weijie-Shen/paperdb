"""Data models for PaperDB — lightweight dataclasses that map to SQLite rows.

No ORM — just typed containers with ``to_dict()`` serialization and
``from_row()`` factory constructors.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def new_id(prefix: str = "p") -> str:
    """Generate a short unique ID with date prefix.

    >>> new_id("p")
    'p_2026_07_08_a1b2c3d4'
    """
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y_%m_%d")
    uid = uuid.uuid4().hex[:8]
    return f"{prefix}_{date_part}_{uid}"


def now_iso() -> str:
    """Current UTC timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class User:
    name: str
    id: str = field(default_factory=lambda: new_id("u"))
    email: Optional[str] = None
    role: str = "researcher"          # admin | researcher | viewer
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "User":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})


@dataclass
class Paper:
    title: str
    source_type: str                  # academic_paper | broker_report | white_paper | blog_article | manual_upload | other
    id: str = field(default_factory=lambda: new_id("p"))
    title_en: Optional[str] = None
    authors_raw: Optional[str] = None   # semicolon-delimited
    institution: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    download_url: Optional[str] = None
    github_url: Optional[str] = None
    github_evidence_type: Optional[str] = None
    github_evidence_url: Optional[str] = None
    publication_date: Optional[str] = None
    market: Optional[str] = None
    frequency: Optional[str] = None
    language: Optional[str] = None
    abstract: Optional[str] = None
    abstract_en: Optional[str] = None
    ai_summary: Optional[str] = None
    file_path: Optional[str] = None
    file_format: Optional[str] = None
    access_status: str = "queued"     # downloaded | manual_required | paywalled | not_available | queued | failed
    access_notes: Optional[str] = None
    content_hash: Optional[str] = None
    metadata_hash: Optional[str] = None
    priority_score: int = 0
    quality_flag: str = "ok"          # ok | needs_review | duplicate_suspected | broken
    metadata_quality: str = "partial" # verified | partial | suspicious
    quality_screening_status: str = "metadata_only"  # metadata_only | full_text_available | quality_screened | insufficient_evidence
    lifecycle_status: str = "active"  # active | rejected_out_of_scope | archived
    ingestion_batch: Optional[str] = None
    added_by: Optional[str] = None
    reviewed_by: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "Paper":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})


@dataclass
class PaperLabel:
    paper_id: str
    label: str
    id: str = field(default_factory=lambda: new_id("l"))
    confidence: Optional[float] = None
    source: str = "ai_auto"           # ai_auto by default; optional audit source for custom workflows
    added_by: Optional[str] = None
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "PaperLabel":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})


@dataclass
class PaperAuthor:
    paper_id: str
    author_name: str
    author_order: int
    id: str = field(default_factory=lambda: new_id("a"))
    author_name_en: Optional[str] = None
    institution: Optional[str] = None
    affiliation_source: Optional[str] = None
    affiliation_evidence_url: Optional[str] = None
    is_corresponding: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_corresponding"] = int(d["is_corresponding"])
        return d

    @classmethod
    def from_row(cls, row) -> "PaperAuthor":
        d = {k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()}
        d["is_corresponding"] = bool(d["is_corresponding"])
        return cls(**d)


@dataclass
class UserAnnotation:
    paper_id: str
    user_id: str
    note_type: str                    # comment | rating | tag | reading_status
    id: str = field(default_factory=lambda: new_id("n"))
    content: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "UserAnnotation":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})


@dataclass
class SearchLog:
    query: str
    id: str = field(default_factory=lambda: new_id("s"))
    source_name: Optional[str] = None
    query_type: Optional[str] = None  # keyword | semantic | author_search | browse | web_exploratory
    results_count: int = 0
    new_papers: int = 0
    inspected_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    duplicate_count: int = 0
    latency_ms: Optional[int] = None
    searched_at: str = field(default_factory=now_iso)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "SearchLog":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})


@dataclass
class DownloadLog:
    paper_id: str
    status: str                       # success | blocked | timeout | paywall | error
    id: str = field(default_factory=lambda: new_id("d"))
    attempt_at: str = field(default_factory=now_iso)
    http_status: Optional[int] = None
    error_detail: Optional[str] = None
    file_size: Optional[int] = None
    finished_at: Optional[str] = None
    retryable: Optional[bool] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        if data["retryable"] is not None:
            data["retryable"] = int(data["retryable"])
        return data

    @classmethod
    def from_row(cls, row) -> "DownloadLog":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})

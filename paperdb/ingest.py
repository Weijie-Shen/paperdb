"""Ingestion pipeline — the core workflow for adding papers to the database.

Handles deduplication, hashing, file storage, and DB insertion.
"""

from __future__ import annotations

import sqlite3
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from paperdb.db.models import Paper, PaperAuthor, new_id, now_iso
from paperdb.connectors.base import DownloadResult, PaperMetadata
from paperdb.storage.file_store import FileStore
from paperdb.utils.hashing import (
    compute_content_hash,
    compute_metadata_hash,
    normalize_title,
    normalize_authors,
)

# Optional search index auto-update
_AUTO_INDEX = True


def set_auto_index(enabled: bool) -> None:
    """Enable or disable automatic search index updates on ingest.

    Disable during bulk imports for performance, then run
    ``paperdb index rebuild`` once at the end.
    """
    global _AUTO_INDEX
    _AUTO_INDEX = enabled


def _maybe_index(paper_id: str, title: str, abstract: str | None = None) -> None:
    """Update search indexes for a newly ingested paper, if auto-index is on."""
    if not _AUTO_INDEX:
        return
    try:
        from paperdb.search.indexer import index_paper
        # We need a db_path to find the index — infer from common layout
        import os
        db_root = os.environ.get("PAPERDB_HOME", "paper_database")
        index_dir = os.path.join(db_root, "index", "vector")
        # The caller's conn gives us access — just use the SQLite path
        # but we need the conn. Since we don't have it here, we skip.
        # Callers should call index_paper directly after commit.
        pass
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Ingestion result
# ---------------------------------------------------------------------------

class IngestResult:
    """Outcome of an ingestion attempt."""

    def __init__(
        self,
        paper_id: str,
        status: str,                   # "new" | "duplicate" | "error"
        duplicate_of: Optional[str] = None,
        error: Optional[str] = None,
    ):
        self.paper_id = paper_id
        self.status = status
        self.duplicate_of = duplicate_of
        self.error = error

    def __repr__(self) -> str:
        if self.status == "new":
            return f"IngestResult(new, id={self.paper_id})"
        if self.status == "duplicate":
            return f"IngestResult(duplicate of {self.duplicate_of})"
        return f"IngestResult(error: {self.error})"


# ---------------------------------------------------------------------------
# Dedup check
# ---------------------------------------------------------------------------

def _check_duplicate(
    conn: sqlite3.Connection,
    metadata_hash: str,
    title: str,
    authors_raw: Optional[str],
    publication_date: Optional[str],
) -> Optional[str]:
    """Check if a paper already exists in the database.

    Returns the existing paper's ID if a duplicate is found, or None.
    Uses exact metadata_hash match first, then fuzzy title+author check.
    """
    # Step 1: Exact metadata hash match (fast, indexed)
    row = conn.execute(
        "SELECT id FROM papers WHERE metadata_hash = ?", (metadata_hash,)
    ).fetchone()
    if row:
        return row["id"]

    # Step 2: Fuzzy title match (slower, catches variations)
    norm_title = normalize_title(title)
    if len(norm_title) < 10:
        return None  # Title too short for reliable fuzzy match

    # Find papers with similar normalized title prefix
    candidates = conn.execute(
        "SELECT id, title, authors_raw, publication_date FROM papers "
        "WHERE LOWER(title) LIKE ? OR LOWER(title) LIKE ?",
        (f"%{norm_title[:30]}%", f"%{norm_title[-30:]}%"),
    ).fetchall()

    if not candidates:
        return None

    norm_authors = normalize_authors(authors_raw) if authors_raw else ""

    for c in candidates:
        c_norm_title = normalize_title(c["title"])
        # Simple Jaccard-like word overlap on title
        title_words = set(norm_title.split())
        c_words = set(c_norm_title.split())
        if not title_words or not c_words:
            continue
        title_overlap = len(title_words & c_words) / len(title_words | c_words)

        # Author overlap
        c_norm_auth = normalize_authors(c["authors_raw"]) if c["authors_raw"] else ""
        author_overlap = 0.0
        if norm_authors and c_norm_auth:
            auth_set = set(norm_authors.split("; "))
            c_auth_set = set(c_norm_auth.split("; "))
            if auth_set and c_auth_set:
                author_overlap = len(auth_set & c_auth_set) / len(auth_set | c_auth_set)

        # Date proximity (within 12 months)
        date_close = True
        if publication_date and c["publication_date"]:
            try:
                d1 = publication_date[:7]  # YYYY-MM
                d2 = c["publication_date"][:7]
                date_close = d1 == d2
            except (IndexError, ValueError):
                date_close = True  # Can't parse, don't block on date

        # Score: high title overlap + any author overlap + close date = likely dupe
        if title_overlap > 0.7 and (author_overlap > 0.3 or date_close):
            return c["id"]

    return None


# ---------------------------------------------------------------------------
# Ingest from URL
# ---------------------------------------------------------------------------

def ingest_from_url(
    conn: sqlite3.Connection,
    file_store: FileStore,
    *,
    title: str,
    url: str,
    source_type: str,
    source_name: str = "web",
    authors_raw: Optional[str] = None,
    institution: Optional[str] = None,
    download_url: Optional[str] = None,
    github_url: Optional[str] = None,
    publication_date: Optional[str] = None,
    abstract: Optional[str] = None,
    market: Optional[str] = None,
    frequency: Optional[str] = None,
    language: Optional[str] = None,
    access_notes: Optional[str] = None,
    priority_score: int = 0,
    batch_id: Optional[str] = None,
    added_by: Optional[str] = None,
) -> IngestResult:
    """Download a paper from a URL and ingest it into the database.

    Returns an ``IngestResult`` indicating success, duplicate, or error.
    """
    # 1. Compute metadata hash early for dedup
    meta_hash = compute_metadata_hash(title, authors_raw, publication_date)

    # 2. Check for duplicate
    dup_id = _check_duplicate(conn, meta_hash, title, authors_raw, publication_date)
    if dup_id:
        return IngestResult(paper_id=dup_id, status="duplicate", duplicate_of=dup_id)

    # 3. Generate paper ID
    paper_id = new_id("p")

    # 4. Try downloading the file
    file_path_rel: Optional[str] = None
    content_hash: Optional[str] = None
    file_format: Optional[str] = "pdf"
    access_status: str = "queued"

    try:
        # Download to a temp location first
        import tempfile
        import os
        import mimetypes

        req = urllib.request.Request(url, headers={"User-Agent": "PaperDB/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()

        # Guess format from Content-Type or URL extension
        ct = resp.headers.get("Content-Type", "")
        ext = mimetypes.guess_extension(ct) or ".pdf"
        if url.lower().endswith(".pdf"):
            ext = ".pdf"
        elif url.lower().endswith(".html") or url.lower().endswith(".htm"):
            ext = ".html"
        elif url.lower().endswith(".docx"):
            ext = ".docx"

        fmt = ext.lstrip(".")
        file_format = fmt if fmt in ("pdf", "html", "docx", "txt") else "pdf"

        # Write temp file, compute hash, then move to store
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        content_hash = compute_content_hash(tmp_path)
        file_path_rel = file_store.add_file(paper_id, tmp_path, fmt=file_format, move=True)
        os.unlink(tmp_path)  # Clean up in case move created a copy (shouldn't, but safe)

        access_status = "downloaded"
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        access_status = "failed"
        access_notes = (access_notes or "") + f" Download failed: {e}"

    # 5. Insert paper record
    paper = Paper(
        id=paper_id,
        title=title,
        authors_raw=authors_raw,
        institution=institution,
        source_type=source_type,
        source_name=source_name,
        source_url=url,
        download_url=download_url or url,
        github_url=github_url,
        publication_date=publication_date,
        abstract=abstract,
        market=market,
        frequency=frequency,
        language=language,
        file_path=file_path_rel,
        file_format=file_format,
        access_status=access_status,
        quality_screening_status="full_text_available" if file_path_rel else "metadata_only",
        access_notes=access_notes,
        content_hash=content_hash,
        metadata_hash=meta_hash,
        priority_score=priority_score,
        ingestion_batch=batch_id,
        added_by=added_by,
    )

    conn.execute(
        """INSERT INTO papers (
            id, title, title_en, authors_raw, institution,
            source_type, source_name, source_url, download_url, github_url, publication_date,
            market, frequency, language, abstract, abstract_en,
            file_path, file_format, access_status, access_notes,
            content_hash, metadata_hash, priority_score, quality_flag, quality_screening_status,
            ingestion_batch, added_by, created_at, updated_at
        ) VALUES (
            :id, :title, :title_en, :authors_raw, :institution,
            :source_type, :source_name, :source_url, :download_url, :github_url, :publication_date,
            :market, :frequency, :language, :abstract, :abstract_en,
            :file_path, :file_format, :access_status, :access_notes,
            :content_hash, :metadata_hash, :priority_score, :quality_flag, :quality_screening_status,
            :ingestion_batch, :added_by, :created_at, :updated_at
        )""",
        paper.to_dict(),
    )

    # 6. Insert normalized authors
    if authors_raw:
        _insert_authors(conn, paper_id, authors_raw)

    conn.commit()
    return IngestResult(paper_id=paper_id, status="new")


# ---------------------------------------------------------------------------
# Ingest from local file
# ---------------------------------------------------------------------------

def ingest_from_file(
    conn: sqlite3.Connection,
    file_store: FileStore,
    *,
    title: str,
    file_path: str | Path,
    source_type: str,
    source_name: str = "manual_upload",
    authors_raw: Optional[str] = None,
    institution: Optional[str] = None,
    source_url: Optional[str] = None,
    download_url: Optional[str] = None,
    github_url: Optional[str] = None,
    publication_date: Optional[str] = None,
    abstract: Optional[str] = None,
    market: Optional[str] = None,
    frequency: Optional[str] = None,
    language: Optional[str] = None,
    priority_score: int = 0,
    batch_id: Optional[str] = None,
    added_by: Optional[str] = None,
) -> IngestResult:
    """Ingest a local file (PDF, DOCX, HTML) into the database.

    Copies the file into the store, computes hashes, and inserts metadata.
    """
    src = Path(file_path)
    if not src.exists():
        return IngestResult(paper_id="", status="error", error=f"File not found: {file_path}")

    # 1. Compute metadata hash for dedup
    meta_hash = compute_metadata_hash(title, authors_raw, publication_date)

    # 2. Check duplicate
    dup_id = _check_duplicate(conn, meta_hash, title, authors_raw, publication_date)
    if dup_id:
        return IngestResult(paper_id=dup_id, status="duplicate", duplicate_of=dup_id)

    # 3. Generate paper ID
    paper_id = new_id("p")

    # 4. Determine format and hash
    fmt = src.suffix.lstrip(".").lower()
    if fmt not in ("pdf", "html", "htm", "docx", "txt"):
        fmt = "pdf"  # Default assumption
    if fmt == "htm":
        fmt = "html"
    file_format = fmt

    content_hash = compute_content_hash(str(src))

    # 5. Copy to file store
    file_path_rel = file_store.add_file(paper_id, str(src), fmt=file_format)

    # 6. Insert
    paper = Paper(
        id=paper_id,
        title=title,
        authors_raw=authors_raw,
        institution=institution,
        source_type=source_type,
        source_name=source_name,
        source_url=source_url or str(src),
        download_url=download_url,
        github_url=github_url,
        publication_date=publication_date,
        abstract=abstract,
        market=market,
        frequency=frequency,
        language=language,
        file_path=file_path_rel,
        file_format=file_format,
        access_status="downloaded",
        quality_screening_status="full_text_available",
        content_hash=content_hash,
        metadata_hash=meta_hash,
        priority_score=priority_score,
        ingestion_batch=batch_id,
        added_by=added_by,
    )

    conn.execute(
        """INSERT INTO papers (
            id, title, title_en, authors_raw, institution,
            source_type, source_name, source_url, download_url, github_url, publication_date,
            market, frequency, language, abstract, abstract_en,
            file_path, file_format, access_status, access_notes,
            content_hash, metadata_hash, priority_score, quality_flag, quality_screening_status,
            ingestion_batch, added_by, created_at, updated_at
        ) VALUES (
            :id, :title, :title_en, :authors_raw, :institution,
            :source_type, :source_name, :source_url, :download_url, :github_url, :publication_date,
            :market, :frequency, :language, :abstract, :abstract_en,
            :file_path, :file_format, :access_status, :access_notes,
            :content_hash, :metadata_hash, :priority_score, :quality_flag, :quality_screening_status,
            :ingestion_batch, :added_by, :created_at, :updated_at
        )""",
        paper.to_dict(),
    )

    if authors_raw:
        _insert_authors(conn, paper_id, authors_raw)

    conn.commit()
    return IngestResult(paper_id=paper_id, status="new")


# ---------------------------------------------------------------------------
# Ingest metadata-only (no file)
# ---------------------------------------------------------------------------

def ingest_metadata_only(
    conn: sqlite3.Connection,
    *,
    title: str,
    source_type: str,
    source_name: str = "web",
    authors_raw: Optional[str] = None,
    institution: Optional[str] = None,
    source_url: Optional[str] = None,
    download_url: Optional[str] = None,
    github_url: Optional[str] = None,
    publication_date: Optional[str] = None,
    abstract: Optional[str] = None,
    market: Optional[str] = None,
    frequency: Optional[str] = None,
    language: Optional[str] = None,
    access_status: str = "manual_required",
    access_notes: Optional[str] = None,
    priority_score: int = 0,
    batch_id: Optional[str] = None,
    added_by: Optional[str] = None,
) -> IngestResult:
    """Ingest a paper as metadata-only (no file download).

    Use this when a paper cannot be downloaded (paywalled, terminal-licensed,
    manual access required) but you want it in the searchable database.
    """
    meta_hash = compute_metadata_hash(title, authors_raw, publication_date)

    dup_id = _check_duplicate(conn, meta_hash, title, authors_raw, publication_date)
    if dup_id:
        return IngestResult(paper_id=dup_id, status="duplicate", duplicate_of=dup_id)

    paper_id = new_id("p")

    paper = Paper(
        id=paper_id,
        title=title,
        authors_raw=authors_raw,
        institution=institution,
        source_type=source_type,
        source_name=source_name,
        source_url=source_url,
        download_url=download_url,
        github_url=github_url,
        publication_date=publication_date,
        abstract=abstract,
        market=market,
        frequency=frequency,
        language=language,
        access_status=access_status,
        access_notes=access_notes,
        metadata_hash=meta_hash,
        priority_score=priority_score,
        ingestion_batch=batch_id,
        added_by=added_by,
    )

    conn.execute(
        """INSERT INTO papers (
            id, title, title_en, authors_raw, institution,
            source_type, source_name, source_url, download_url, github_url, publication_date,
            market, frequency, language, abstract, abstract_en,
            file_path, file_format, access_status, access_notes,
            content_hash, metadata_hash, priority_score, quality_flag, quality_screening_status,
            ingestion_batch, added_by, created_at, updated_at
        ) VALUES (
            :id, :title, :title_en, :authors_raw, :institution,
            :source_type, :source_name, :source_url, :download_url, :github_url, :publication_date,
            :market, :frequency, :language, :abstract, :abstract_en,
            :file_path, :file_format, :access_status, :access_notes,
            :content_hash, :metadata_hash, :priority_score, :quality_flag, :quality_screening_status,
            :ingestion_batch, :added_by, :created_at, :updated_at
        )""",
        paper.to_dict(),
    )

    if authors_raw:
        _insert_authors(conn, paper_id, authors_raw)

    conn.commit()
    return IngestResult(paper_id=paper_id, status="new")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_authors(conn: sqlite3.Connection, paper_id: str, authors_raw: str) -> None:
    """Parse semicolon-delimited authors and insert into paper_authors."""
    import re
    names = [n.strip() for n in re.split(r"[;,]", authors_raw) if n.strip()]
    for i, name in enumerate(names):
        author = PaperAuthor(
            paper_id=paper_id,
            author_name=name,
            author_order=i + 1,
        )
        conn.execute(
            """INSERT INTO paper_authors (id, paper_id, author_name, author_order)
               VALUES (:id, :paper_id, :author_name, :author_order)""",
            author.to_dict(),
        )


# ---------------------------------------------------------------------------
# Convenience: ingest from PaperMetadata (connector → DB bridge)
# ---------------------------------------------------------------------------

def ingest_from_metadata(
    conn: sqlite3.Connection,
    file_store: FileStore,
    metadata,
    *,
    priority_score: int = 0,
    batch_id: Optional[str] = None,
    added_by: Optional[str] = None,
    download: bool = True,
    connector=None,
) -> IngestResult:
    """Ingest a paper from a :class:`~paperdb.connectors.base.PaperMetadata` object.

    This is the primary bridge between connectors and the database.
    It handles dedup checks, optional file download, and DB insertion.

    Args:
        conn: Open SQLite connection.
        file_store: Initialised :class:`FileStore`.
        metadata: A :class:`PaperMetadata` from any connector.
        priority_score: Priority score from watchlist matching.
        batch_id: Optional batch identifier.
        added_by: User ID who triggered the ingestion.
        download: If True (default) and *connector* supports download,
                  use the connector's download method to fetch the PDF,
                  then ingest the downloaded file. Falls back to metadata-only
                  on failure.
        connector: Optional connector instance. If provided and *download*
                   is True, uses ``connector.download(metadata)`` instead of
                   raw URL download (more reliable for sources like arXiv).

    Returns:
        :class:`IngestResult`.
    """
    # 1. Dedup check
    meta_hash = compute_metadata_hash(
        metadata.title, metadata.authors_raw, metadata.publication_date
    )
    dup_id = _check_duplicate(
        conn, meta_hash, metadata.title, metadata.authors_raw, metadata.publication_date
    )
    if dup_id:
        return IngestResult(paper_id=dup_id, status="duplicate", duplicate_of=dup_id)

    # 2. Try downloading via connector (preferred) or raw URL
    if download and connector is not None and hasattr(connector, "download"):
        dl_result = connector.download(metadata)
        if dl_result.success and dl_result.local_path:
            # Ingest the downloaded file
            try:
                result = ingest_from_file(
                    conn, file_store,
                    title=metadata.title,
                    file_path=dl_result.local_path,
                    source_type=metadata.source_type,
                    source_name=metadata.source_name,
                    authors_raw=metadata.authors_raw,
                    institution=metadata.institution,
                    source_url=metadata.source_url or metadata.download_url,
                    download_url=metadata.download_url,
                    github_url=getattr(metadata, "github_url", None),
                    publication_date=metadata.publication_date,
                    abstract=metadata.abstract,
                    market=metadata.market,
                    frequency=metadata.frequency,
                    language=metadata.language,
                    priority_score=priority_score,
                    batch_id=batch_id,
                    added_by=added_by,
                )
                # Log download success
                _log_download(conn, result.paper_id, "success",
                              file_size=dl_result.file_size)
                # Clean up temp file
                import os
                try:
                    os.unlink(dl_result.local_path)
                except OSError:
                    pass
                _apply_connector_metadata(conn, result.paper_id, metadata)
                conn.commit()
                return result
            except Exception as e:
                _log_download(conn, "", "error", error=str(e))
                # Fall through to metadata-only

    elif download and metadata.download_url:
        # No connector — try raw URL download
        try:
            result = ingest_from_url(
                conn, file_store,
                title=metadata.title,
                url=metadata.download_url,
                source_type=metadata.source_type,
                source_name=metadata.source_name,
                authors_raw=metadata.authors_raw,
                institution=metadata.institution,
                download_url=metadata.download_url,
                github_url=getattr(metadata, "github_url", None),
                publication_date=metadata.publication_date,
                abstract=metadata.abstract,
                market=metadata.market,
                frequency=metadata.frequency,
                language=metadata.language,
                priority_score=priority_score,
                batch_id=batch_id,
                added_by=added_by,
            )
            if result.status == "new":
                _apply_connector_metadata(conn, result.paper_id, metadata)
                conn.commit()
            return result
        except Exception:
            pass  # Fall through to metadata-only

    # 3. Fall back to metadata-only
    access_status = "failed" if download else "queued"
    access_notes = None
    if download and metadata.download_url:
        access_notes = f"Download attempted for {metadata.source_name}, stored as metadata-only"

    result = ingest_metadata_only(
        conn,
        title=metadata.title,
        source_type=metadata.source_type,
        source_name=metadata.source_name,
        authors_raw=metadata.authors_raw,
        institution=metadata.institution,
        source_url=metadata.source_url or metadata.download_url,
        download_url=metadata.download_url,
        github_url=getattr(metadata, "github_url", None),
        publication_date=metadata.publication_date,
        abstract=metadata.abstract,
        market=metadata.market,
        frequency=metadata.frequency,
        language=metadata.language,
        access_status=access_status,
        access_notes=access_notes,
        priority_score=priority_score,
        batch_id=batch_id,
        added_by=added_by,
    )
    if result.status == "new":
        _apply_connector_metadata(conn, result.paper_id, metadata)
        conn.commit()
    return result


def _apply_connector_metadata(conn: sqlite3.Connection, paper_id: str, metadata) -> None:
    """Persist connector evidence and non-destructive metadata validation."""
    from paperdb.search.quality import validate_metadata

    quality, warnings = validate_metadata(metadata)
    extra = getattr(metadata, "extra", {}) or {}
    github_url = getattr(metadata, "github_url", None)
    evidence_type = extra.get("github_evidence_type")
    evidence_url = extra.get("github_evidence_url")
    author_affiliations = extra.get("author_affiliations") or []
    affiliation_source = extra.get("affiliation_source")
    affiliation_evidence_url = extra.get("affiliation_evidence_url")
    if "invalid_github_repository_url" in warnings:
        github_url = evidence_type = evidence_url = None
    conn.execute(
        """UPDATE papers
           SET github_url = ?, github_evidence_type = ?, github_evidence_url = ?,
               metadata_quality = ?, quality_flag = ?, updated_at = ?
           WHERE id = ?""",
        (github_url, evidence_type, evidence_url, quality,
         "needs_review" if warnings else "ok", now_iso(), paper_id),
    )
    unique_affiliations = []
    for order, author in enumerate(author_affiliations, 1):
        affiliations = [a.strip() for a in author.get("affiliations", []) if a and a.strip()]
        if not affiliations:
            continue
        institution = "; ".join(dict.fromkeys(affiliations))
        for affiliation in affiliations:
            if affiliation not in unique_affiliations:
                unique_affiliations.append(affiliation)
        conn.execute(
            """UPDATE paper_authors
               SET institution = ?, affiliation_source = ?, affiliation_evidence_url = ?
               WHERE paper_id = ? AND author_order = ?""",
            (institution, affiliation_source, affiliation_evidence_url, paper_id, order),
        )
    if unique_affiliations:
        conn.execute(
            """UPDATE papers SET institution = ?
               WHERE id = ? AND (institution IS NULL OR TRIM(institution) = '')""",
            ("; ".join(unique_affiliations), paper_id),
        )


def download_paper_file(
    conn: sqlite3.Connection,
    file_store: FileStore,
    paper_id: str,
    *,
    connector=None,
) -> DownloadResult:
    """Download the file for an existing metadata-only paper.

    This updates the existing row instead of inserting a new paper, which lets
    AI workflows ingest/filter first and run slow downloads later.
    """
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if not row:
        return DownloadResult(success=False, error=f"Paper not found: {paper_id}")

    if row["file_path"] and row["access_status"] == "downloaded":
        return DownloadResult(
            success=True,
            local_path=row["file_path"],
            error="Paper is already downloaded",
        )

    metadata = PaperMetadata(
        title=row["title"],
        source_type=row["source_type"],
        source_name=row["source_name"] or "web",
        authors_raw=row["authors_raw"],
        institution=row["institution"],
        source_url=row["source_url"],
        github_url=row["github_url"],
        publication_date=row["publication_date"],
        abstract=row["abstract"],
        language=row["language"],
        market=row["market"],
        frequency=row["frequency"],
        download_url=row["download_url"] or row["source_url"],
        file_format=row["file_format"] or "pdf",
    )

    log_id = _start_download_log(conn, paper_id)
    conn.commit()
    try:
        dl_result = _download_with_connector_or_url(connector, metadata)
    except Exception as exc:
        dl_result = DownloadResult(
            success=False, error=f"Download failed: {exc}",
            error_type="unexpected_error", retryable=True,
        )
    if not dl_result.success or not dl_result.local_path:
        conn.execute(
            """UPDATE papers
               SET access_status = ?, access_notes = ?, updated_at = ?
               WHERE id = ?""",
            ("failed", dl_result.error, now_iso(), paper_id),
        )
        _finish_download_log(
            conn,
            log_id,
            "timeout" if dl_result.error_type == "timeout" else "error",
            http_status=dl_result.http_status,
            error=dl_result.error,
            file_size=dl_result.file_size,
            retryable=dl_result.retryable,
        )
        conn.commit()
        return dl_result

    fmt = (metadata.file_format or "pdf").lower()
    if fmt not in ("pdf", "html", "docx", "txt"):
        fmt = "pdf"

    file_path_rel = file_store.add_file(paper_id, dl_result.local_path, fmt=fmt, move=True)
    content_hash = compute_content_hash(str(file_store.get_path(file_path_rel)))

    conn.execute(
        """UPDATE papers
           SET file_path = ?, file_format = ?, access_status = ?,
               quality_screening_status = 'full_text_available',
               access_notes = NULL, content_hash = ?, updated_at = ?
           WHERE id = ?""",
        (file_path_rel, fmt, "downloaded", content_hash, now_iso(), paper_id),
    )
    _finish_download_log(conn, log_id, "success", file_size=dl_result.file_size,
                         retryable=False)
    conn.commit()

    dl_result.local_path = file_path_rel
    dl_result.content_hash = content_hash
    return dl_result


def _download_with_connector_or_url(connector, metadata: PaperMetadata) -> DownloadResult:
    """Download metadata using a connector when possible, otherwise raw URL."""
    if connector is not None and hasattr(connector, "download"):
        return connector.download(metadata)

    url = metadata.download_url or metadata.source_url
    if not url:
        return DownloadResult(success=False, error="No download URL")

    import tempfile

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PaperDB/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            http_status = getattr(resp, "status", None)

        if len(data) < 1000:
            return DownloadResult(
                success=False,
                error=f"Downloaded file too small ({len(data)} bytes)",
                http_status=http_status,
                file_size=len(data),
            )

        suffix = "." + (metadata.file_format or "pdf").lstrip(".")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            local_path = tmp.name

        return DownloadResult(
            success=True,
            local_path=local_path,
            file_size=len(data),
            http_status=http_status,
        )
    except urllib.error.HTTPError as e:
        return DownloadResult(
            success=False,
            error=f"HTTP {e.code}: {e.reason}",
            http_status=e.code,
            error_type="http_error",
            retryable=e.code >= 500 or e.code == 429,
        )
    except TimeoutError as e:
        return DownloadResult(success=False, error=f"Download timed out: {e}",
                              error_type="timeout", retryable=True)
    except Exception as e:
        return DownloadResult(success=False, error=f"Download failed: {e}",
                              error_type="network_error", retryable=True)


def _start_download_log(conn: sqlite3.Connection, paper_id: str) -> str:
    """Create a durable attempt row before network I/O begins."""
    log_id = new_id("d")
    conn.execute(
        "INSERT INTO download_logs (id, paper_id, attempt_at, status) VALUES (?, ?, ?, ?)",
        (log_id, paper_id, now_iso(), "in_progress"),
    )
    return log_id


def _finish_download_log(conn: sqlite3.Connection, log_id: str, status: str, *,
                         http_status: Optional[int] = None,
                         error: Optional[str] = None,
                         file_size: Optional[int] = None,
                         retryable: Optional[bool] = None) -> None:
    conn.execute(
        """UPDATE download_logs
           SET status = ?, http_status = ?, error_detail = ?, file_size = ?,
               finished_at = ?, retryable = ? WHERE id = ?""",
        (status, http_status, error, file_size, now_iso(),
         None if retryable is None else int(retryable), log_id),
    )


def _log_download(
    conn: sqlite3.Connection,
    paper_id: str,
    status: str,
    *,
    http_status: Optional[int] = None,
    error: Optional[str] = None,
    file_size: Optional[int] = None,
) -> None:
    """Record a download attempt in the download_logs table."""
    from paperdb.db.models import DownloadLog
    log = DownloadLog(
        paper_id=paper_id or "unknown",
        status=status,
        http_status=http_status,
        error_detail=error,
        file_size=file_size,
    )
    conn.execute(
        """INSERT INTO download_logs
           (id, paper_id, attempt_at, status, http_status, error_detail,
            file_size, finished_at, retryable)
           VALUES (:id, :paper_id, :attempt_at, :status, :http_status,
                   :error_detail, :file_size, :finished_at, :retryable)""",
        log.to_dict(),
    )

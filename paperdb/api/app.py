"""FastAPI application for PaperDB.

The API is intentionally thin: it exposes the same deterministic operations as
the CLI while leaving AI-directed search/classification decisions outside the
HTTP layer.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from paperdb.config.loader import Config
from paperdb.connectors.arxiv_connector import ArxivConnector
from paperdb.db.models import PaperLabel, now_iso
from paperdb.db.schema import get_db
from paperdb.ingest import (
    download_paper_file,
    ingest_from_metadata,
    ingest_metadata_only,
)
from paperdb.storage.file_store import FileStore
from paperdb.utils.hashing import compute_metadata_hash


DEFAULT_DB_ROOT = "paper_database"


def resolve_root(path: Optional[str] = None) -> Path:
    """Resolve the PaperDB root directory."""
    return Path(path or os.environ.get("PAPERDB_HOME", DEFAULT_DB_ROOT)).resolve()


class ApiContext:
    """Per-request DB/config/file-store context."""

    def __init__(self, root: Path):
        self.root = root
        self.conn = get_db(root / "db" / "papers.sqlite")
        self.config = Config(root)
        self.file_store = FileStore(root / "files")

    def close(self) -> None:
        self.conn.close()


def create_app(db_root: Optional[str | Path] = None) -> FastAPI:
    """Create a FastAPI app bound to a PaperDB root."""
    root = resolve_root(str(db_root) if db_root is not None else None)
    app = FastAPI(
        title="PaperDB API",
        version="0.1.0",
        description="HTTP API for the AI-operated PaperDB research database.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_context():
        ctx = ApiContext(root)
        try:
            yield ctx
        finally:
            ctx.close()

    @app.get("/health")
    def health(ctx: ApiContext = Depends(get_context)) -> dict[str, Any]:
        active = ctx.conn.execute(
            "SELECT COUNT(*) FROM papers WHERE lifecycle_status = 'active'"
        ).fetchone()[0]
        return {"status": "ok", "root": str(root), "papers": active}

    @app.get("/papers/facets")
    def paper_facets(ctx: ApiContext = Depends(get_context)) -> dict[str, Any]:
        """Return filter values and counts for active papers."""
        facets: dict[str, list[dict[str, Any]]] = {}
        for column in (
            "market",
            "frequency",
            "source_type",
            "source_name",
            "access_status",
            "language",
            "metadata_quality",
            "quality_screening_status",
        ):
            rows = ctx.conn.execute(
                f"""SELECT {column} AS value, COUNT(*) AS count
                    FROM papers
                    WHERE lifecycle_status = 'active'
                      AND {column} IS NOT NULL AND {column} != ''
                    GROUP BY {column}
                    ORDER BY count DESC, value"""
            ).fetchall()
            facets[column] = [dict(row) for row in rows]

        labels = ctx.conn.execute(
            """SELECT pl.label AS value, COUNT(DISTINCT pl.paper_id) AS count
               FROM paper_labels pl
               JOIN papers p ON p.id = pl.paper_id
               WHERE p.lifecycle_status = 'active'
               GROUP BY pl.label
               ORDER BY count DESC, value"""
        ).fetchall()
        institutions = ctx.conn.execute(
            """SELECT pi.canonical_name AS value, COUNT(DISTINCT pi.paper_id) AS count
               FROM paper_institutions pi
               JOIN papers p ON p.id = pi.paper_id
               WHERE p.lifecycle_status = 'active'
               GROUP BY pi.canonical_name
               ORDER BY count DESC, value"""
        ).fetchall()
        facets["labels"] = [dict(row) for row in labels]
        facets["institutions"] = [dict(row) for row in institutions]
        return facets

    @app.get("/papers")
    def list_papers(
        label: list[str] = Query(default=[]),
        market: Optional[str] = None,
        frequency: Optional[str] = None,
        source_type: Optional[str] = None,
        source_name: Optional[str] = None,
        access_status: Optional[str] = None,
        language: Optional[str] = None,
        institution: Optional[str] = None,
        search: Optional[str] = None,
        github_only: bool = False,
        has_file: Optional[bool] = None,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        ctx: ApiContext = Depends(get_context),
    ) -> dict[str, Any]:
        where = ["lifecycle_status = 'active'"]
        params: list[Any] = []

        if label:
            placeholders = ",".join("?" for _ in label)
            where.append(f"""id IN (
                SELECT paper_id FROM paper_labels
                WHERE label IN ({placeholders})
                GROUP BY paper_id
                HAVING COUNT(DISTINCT label) = ?
            )""")
            params.extend(label)
            params.append(len(label))

        for col, value in [
            ("market", market),
            ("frequency", frequency),
            ("source_type", source_type),
            ("source_name", source_name),
            ("access_status", access_status),
            ("language", language),
        ]:
            if value is not None:
                where.append(f"{col} = ?")
                params.append(value)

        if search:
            where.append("(title LIKE ? OR abstract LIKE ? OR ai_summary LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        if institution:
            institution = ctx.config.canonicalize_institution_filter(institution)
            where.append("""(institution LIKE ? OR id IN (
                SELECT paper_id FROM paper_institutions
                WHERE canonical_name LIKE ? OR raw_value LIKE ? OR matched_alias LIKE ?
            ))""")
            params.extend([f"%{institution}%"] * 4)

        if github_only:
            where.append("github_url IS NOT NULL AND github_url != ''")

        if has_file is True:
            where.append("file_path IS NOT NULL")
        elif has_file is False:
            where.append("file_path IS NULL")

        where_clause = " AND ".join(where)
        total = ctx.conn.execute(f"SELECT COUNT(*) FROM papers WHERE {where_clause}", params).fetchone()[0]
        rows = ctx.conn.execute(
            f"""SELECT * FROM papers
                WHERE {where_clause}
                ORDER BY priority_score DESC, publication_date DESC, created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [_paper_payload(ctx, row["id"], include_detail=False) for row in rows],
        }

    @app.get("/papers/{paper_id}")
    def get_paper(paper_id: str, ctx: ApiContext = Depends(get_context)) -> dict[str, Any]:
        pid = _resolve_paper_id(ctx, paper_id)
        return _paper_payload(ctx, pid, include_detail=True)

    @app.get("/papers/{paper_id}/file", response_class=FileResponse)
    def get_paper_file(paper_id: str, ctx: ApiContext = Depends(get_context)):
        """Serve a downloaded paper from the local file store."""
        pid = _resolve_paper_id(ctx, paper_id)
        row = ctx.conn.execute(
            "SELECT title, file_path, file_format FROM papers WHERE id = ?", (pid,)
        ).fetchone()
        if not row["file_path"]:
            raise HTTPException(status_code=404, detail="No downloaded file is available")

        store_root = ctx.file_store.root.resolve()
        file_path = ctx.file_store.get_path(row["file_path"]).resolve()
        if store_root not in file_path.parents or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Downloaded file is missing")

        extension = row["file_format"] or file_path.suffix.lstrip(".") or "pdf"
        safe_title = "".join(c if c.isalnum() or c in " -_." else "_" for c in row["title"])
        return FileResponse(file_path, filename=f"{safe_title[:100]}.{extension}")

    @app.post("/papers", status_code=201)
    def create_paper(req: PaperCreate, ctx: ApiContext = Depends(get_context)) -> dict[str, Any]:
        result = ingest_metadata_only(
            ctx.conn,
            title=req.title,
            source_type=req.source_type,
            source_name=req.source_name,
            authors_raw=req.authors_raw,
            institution=req.institution,
            source_url=req.source_url,
            download_url=req.download_url,
            github_url=req.github_url,
            publication_date=req.publication_date,
            abstract=req.abstract,
            market=req.market,
            frequency=req.frequency,
            language=req.language,
            access_status=req.access_status,
            access_notes=req.access_notes,
            priority_score=req.priority_score,
            batch_id=req.batch_id,
            added_by=req.added_by,
        )
        if result.status == "duplicate":
            return {
                "status": "duplicate",
                "paper_id": result.paper_id,
                "duplicate_of": result.duplicate_of,
            }
        if result.status != "new":
            raise HTTPException(status_code=400, detail=result.error or "Paper creation failed")
        return {"status": "new", "paper_id": result.paper_id}

    @app.patch("/papers/{paper_id}")
    def update_paper(
        paper_id: str,
        req: PaperUpdate,
        ctx: ApiContext = Depends(get_context),
    ) -> dict[str, Any]:
        pid = _resolve_paper_id(ctx, paper_id)
        updates = _model_dump(req, exclude_unset=True)
        if not updates:
            return _paper_payload(ctx, pid, include_detail=True)

        updates["updated_at"] = now_iso()
        updates["id"] = pid
        set_clause = ", ".join(f"{k} = :{k}" for k in updates if k != "id")
        ctx.conn.execute(f"UPDATE papers SET {set_clause} WHERE id = :id", updates)
        ctx.conn.commit()
        return _paper_payload(ctx, pid, include_detail=True)

    @app.post("/papers/{paper_id}/labels", status_code=201)
    def add_label(
        paper_id: str,
        req: LabelCreate,
        ctx: ApiContext = Depends(get_context),
    ) -> dict[str, Any]:
        pid = _resolve_paper_id(ctx, paper_id)
        existing = ctx.conn.execute(
            "SELECT id FROM paper_labels WHERE paper_id = ? AND label = ?",
            (pid, req.label),
        ).fetchone()
        if existing:
            return {"status": "exists", "paper_id": pid, "label": req.label}

        label = PaperLabel(
            paper_id=pid,
            label=req.label,
            confidence=req.confidence,
            source=req.source,
            added_by=req.added_by,
        )
        ctx.conn.execute(
            """INSERT INTO paper_labels (id, paper_id, label, confidence, source, added_by, created_at)
               VALUES (:id, :paper_id, :label, :confidence, :source, :added_by, :created_at)""",
            label.to_dict(),
        )
        ctx.conn.commit()
        return {"status": "new", "paper_id": pid, "label": req.label}

    @app.post("/arxiv/search")
    def arxiv_search(req: ArxivSearchRequest, ctx: ApiContext = Depends(get_context)) -> dict[str, Any]:
        connector = ArxivConnector()
        try:
            results = connector.search(req.query, limit=req.limit)
        except Exception as exc:
            from paperdb.connectors.arxiv_connector import ArxivSourceError
            error_type = exc.error_type if isinstance(exc, ArxivSourceError) else "source_error"
            raise HTTPException(status_code=502, detail={
                "source": "arxiv", "error_type": error_type,
                "message": str(exc),
                "retryable": exc.retryable if isinstance(exc, ArxivSourceError) else False,
            }) from exc
        payload = []
        for meta in results:
            metadata_hash = compute_metadata_hash(meta.title, meta.authors_raw, meta.publication_date)
            existing = ctx.conn.execute(
                "SELECT id FROM papers WHERE metadata_hash = ?",
                (metadata_hash,),
            ).fetchone()
            item = _metadata_payload(meta)
            item["in_db"] = bool(existing)
            if existing:
                item["paper_id"] = existing["id"]
            payload.append(item)
        return {"query": req.query, "total": len(payload), "results": payload}

    @app.post("/arxiv/ingest")
    def arxiv_ingest(req: ArxivIngestRequest, ctx: ApiContext = Depends(get_context)) -> dict[str, Any]:
        connector = ArxivConnector()
        try:
            results = connector.search(req.query, limit=req.limit)
        except Exception as exc:
            from paperdb.connectors.arxiv_connector import ArxivSourceError
            error_type = exc.error_type if isinstance(exc, ArxivSourceError) else "source_error"
            raise HTTPException(status_code=502, detail={
                "source": "arxiv", "error_type": error_type,
                "message": str(exc),
                "retryable": exc.retryable if isinstance(exc, ArxivSourceError) else False,
            }) from exc
        outcomes = []
        counts = {"new": 0, "duplicate": 0, "error": 0}
        for meta in results:
            matches = ctx.config.resolve_metadata_institutions(meta)
            priority = max((match.priority_score for match in matches), default=0)

            result = ingest_from_metadata(
                ctx.conn,
                ctx.file_store,
                meta,
                priority_score=priority,
                batch_id=req.batch_id,
                download=req.download,
                connector=connector,
            )
            if result.paper_id:
                from paperdb.config.institutions import persist_institution_matches
                persist_institution_matches(ctx.conn, result.paper_id, matches)
            if result.status in counts:
                counts[result.status] += 1
            else:
                counts["error"] += 1
            outcomes.append({
                "title": meta.title,
                "status": result.status,
                "paper_id": result.paper_id,
                "duplicate_of": result.duplicate_of,
                "error": result.error,
                "arxiv_id": meta.source_id,
            })

        return {
            "query": req.query,
            "total_found": len(results),
            "ingested": counts["new"],
            "duplicates": counts["duplicate"],
            "errors": counts["error"],
            "download": req.download,
            "results": outcomes,
        }

    @app.post("/papers/{paper_id}/download")
    def download_paper(paper_id: str, ctx: ApiContext = Depends(get_context)) -> dict[str, Any]:
        pid = _resolve_paper_id(ctx, paper_id)
        row = ctx.conn.execute("SELECT * FROM papers WHERE id = ?", (pid,)).fetchone()
        result = download_paper_file(
            ctx.conn,
            ctx.file_store,
            pid,
            connector=_connector_for_paper(row),
        )
        return _download_payload(pid, result)

    @app.post("/downloads/missing")
    def download_missing(req: DownloadMissingRequest, ctx: ApiContext = Depends(get_context)) -> dict[str, Any]:
        where = [
            "file_path IS NULL",
            "access_status IN ('queued', 'failed')",
            "(download_url IS NOT NULL OR (source_name = 'arxiv' AND source_url IS NOT NULL))",
        ]
        params: list[Any] = []

        if req.label:
            placeholders = ",".join("?" for _ in req.label)
            where.append(f"""id IN (
                SELECT paper_id FROM paper_labels
                WHERE label IN ({placeholders})
                GROUP BY paper_id
                HAVING COUNT(DISTINCT label) = ?
            )""")
            params.extend(req.label)
            params.append(len(req.label))

        if req.market:
            where.append("market = ?")
            params.append(req.market)
        if req.source_name:
            where.append("source_name = ?")
            params.append(req.source_name)

        rows = ctx.conn.execute(
            f"""SELECT * FROM papers
                WHERE {' AND '.join(where)}
                ORDER BY priority_score DESC, publication_date DESC
                LIMIT ?""",
            params + [req.limit],
        ).fetchall()

        results = []
        for row in rows:
            dl = download_paper_file(
                ctx.conn,
                ctx.file_store,
                row["id"],
                connector=_connector_for_paper(row),
            )
            item = _download_payload(row["id"], dl)
            item["title"] = row["title"]
            results.append(item)

        return {
            "matched": len(rows),
            "downloaded": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"]),
            "results": results,
        }

    @app.get("/downloads/status")
    def download_status(
        limit: int = Query(default=20, ge=1, le=200),
        ctx: ApiContext = Depends(get_context),
    ) -> dict[str, Any]:
        by_access = ctx.conn.execute(
            """SELECT access_status, COUNT(*) AS cnt FROM papers
               WHERE lifecycle_status = 'active'
               GROUP BY access_status ORDER BY cnt DESC"""
        ).fetchall()
        backlog = ctx.conn.execute(
            """SELECT COUNT(*) FROM papers
               WHERE file_path IS NULL
                 AND lifecycle_status = 'active'
                 AND access_status IN ('queued', 'failed')
                 AND (download_url IS NOT NULL OR (source_name = 'arxiv' AND source_url IS NOT NULL))"""
        ).fetchone()[0]
        logs = ctx.conn.execute(
            """SELECT d.*, p.title
               FROM download_logs d
               JOIN papers p ON p.id = d.paper_id AND p.lifecycle_status = 'active'
               ORDER BY d.attempt_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return {
            "by_access_status": {r["access_status"]: r["cnt"] for r in by_access},
            "downloadable_backlog": backlog,
            "recent_logs": [dict(r) for r in logs],
        }

    return app


class PaperCreate(BaseModel):
    title: str
    source_type: str
    source_name: str = "web"
    authors_raw: Optional[str] = None
    institution: Optional[str] = None
    source_url: Optional[str] = None
    download_url: Optional[str] = None
    github_url: Optional[str] = None
    publication_date: Optional[str] = None
    abstract: Optional[str] = None
    market: Optional[str] = None
    frequency: Optional[str] = None
    language: Optional[str] = None
    access_status: str = "manual_required"
    access_notes: Optional[str] = None
    priority_score: int = 0
    batch_id: Optional[str] = None
    added_by: Optional[str] = None


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    title_en: Optional[str] = None
    authors_raw: Optional[str] = None
    institution: Optional[str] = None
    source_url: Optional[str] = None
    download_url: Optional[str] = None
    github_url: Optional[str] = None
    publication_date: Optional[str] = None
    abstract: Optional[str] = None
    abstract_en: Optional[str] = None
    ai_summary: Optional[str] = None
    market: Optional[str] = None
    frequency: Optional[str] = None
    language: Optional[str] = None
    access_status: Optional[str] = None
    access_notes: Optional[str] = None
    priority_score: Optional[int] = None
    quality_flag: Optional[str] = None


class LabelCreate(BaseModel):
    label: str
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    source: str = "ai_auto"
    added_by: Optional[str] = None


class ArxivSearchRequest(BaseModel):
    query: str
    limit: int = Field(default=20, ge=1, le=100)


class ArxivIngestRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=100)
    download: bool = False
    batch_id: Optional[str] = None


class DownloadMissingRequest(BaseModel):
    label: list[str] = Field(default_factory=list)
    market: Optional[str] = None
    source_name: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)


def _paper_payload(ctx: ApiContext, paper_id: str, *, include_detail: bool) -> dict[str, Any]:
    row = ctx.conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id}")
    paper = dict(row)

    labels = ctx.conn.execute(
        "SELECT label, confidence, source, added_by, created_at FROM paper_labels WHERE paper_id = ? ORDER BY label",
        (paper_id,),
    ).fetchall()
    paper["labels"] = [dict(label) for label in labels]
    paper["file"] = _file_status(ctx, paper)
    paper["download_status"] = paper["file"]["status"]

    if include_detail:
        authors = ctx.conn.execute(
            "SELECT author_name, author_name_en, institution, is_corresponding, author_order "
            "FROM paper_authors WHERE paper_id = ? ORDER BY author_order",
            (paper_id,),
        ).fetchall()
        paper["authors"] = [dict(author) for author in authors]
        institutions = ctx.conn.execute(
            """SELECT canonical_name, raw_value, matched_alias, priority_rank,
                      priority_score, match_source, confidence, created_at
               FROM paper_institutions WHERE paper_id = ?
               ORDER BY priority_rank, canonical_name""",
            (paper_id,),
        ).fetchall()
        paper["institutions"] = [dict(institution) for institution in institutions]
        downloads = ctx.conn.execute(
            """SELECT attempt_at, status, http_status, error_detail, file_size,
                      finished_at, retryable
               FROM download_logs WHERE paper_id = ?
               ORDER BY attempt_at DESC LIMIT 20""",
            (paper_id,),
        ).fetchall()
        paper["download_logs"] = [dict(download) for download in downloads]

    return paper


def _file_status(ctx: ApiContext, paper: dict[str, Any]) -> dict[str, Any]:
    relative_path = paper.get("file_path")
    available = bool(relative_path and ctx.file_store.exists(relative_path))
    status = paper.get("access_status") or "not_available"
    if available:
        status = "downloaded"
    elif status == "downloaded":
        status = "missing"
    return {
        "status": status,
        "available": available,
        "format": paper.get("file_format"),
        "path": relative_path,
        "download_url": f"/papers/{paper['id']}/file" if available else None,
    }


def _resolve_paper_id(ctx: ApiContext, paper_id: str) -> str:
    row = ctx.conn.execute(
        "SELECT id FROM papers WHERE id = ? OR id LIKE ?",
        (paper_id, f"{paper_id}%"),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id}")
    return row["id"]


def _metadata_payload(meta) -> dict[str, Any]:
    return {
        "title": meta.title,
        "authors_raw": meta.authors_raw,
        "source_type": meta.source_type,
        "source_name": meta.source_name,
        "source_id": meta.source_id,
        "source_url": meta.source_url,
        "download_url": meta.download_url,
        "github_url": meta.github_url,
        "publication_date": meta.publication_date,
        "abstract": meta.abstract,
        "language": meta.language,
        "market": meta.market,
        "frequency": meta.frequency,
        "extra": meta.extra,
    }


def _connector_for_paper(row):
    if row["source_name"] == "arxiv":
        return ArxivConnector()
    return None


def _download_payload(paper_id: str, result) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "success": result.success,
        "file_path": result.local_path,
        "file_size": result.file_size,
        "content_hash": result.content_hash,
        "http_status": result.http_status,
        "error": result.error,
    }


def _model_dump(model: BaseModel, **kwargs) -> dict[str, Any]:
    """Support both Pydantic v1 and v2."""
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


app = create_app()


def main() -> None:
    """Run the API with uvicorn."""
    import uvicorn

    host = os.environ.get("PAPERDB_API_HOST", "127.0.0.1")
    port = int(os.environ.get("PAPERDB_API_PORT", "8000"))
    uvicorn.run("paperdb.api.app:app", host=host, port=port, reload=False)

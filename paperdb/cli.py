"""PaperDB CLI — manage the paper database from the command line.

Usage::

    paperdb init                     Create database and file structure
    paperdb ingest from-url ...      Download and ingest a paper from a URL
    paperdb ingest from-file ...     Import a local file
    paperdb ingest metadata-only ... Store metadata without downloading
    paperdb query [filters]          Search and filter papers
    paperdb info <id>                Show full details of a paper
    paperdb stats                    Database summary statistics
    paperdb label add <id> <label>   Assign a label to a paper
    paperdb label list [--source]    List labels by frequency
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
import yaml

from paperdb.db.schema import init_db, get_db
from paperdb.storage.file_store import FileStore
from paperdb.config.loader import Config, DEFAULT_WATCHLIST
from paperdb.ingest import (
    ingest_from_url,
    ingest_from_file,
    ingest_metadata_only,
    download_paper_file,
    IngestResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_DB_ROOT = "paper_database"


def _resolve_root(path: Optional[str]) -> Path:
    """Resolve the paper_database root directory."""
    return Path(path or os.environ.get("PAPERDB_HOME", DEFAULT_DB_ROOT)).resolve()


def _get_db(root: Path) -> tuple:
    """Open DB connection and return (conn, config, file_store)."""
    db_path = root / "db" / "papers.sqlite"
    conn = get_db(db_path)
    config = Config(root)
    file_store = FileStore(root / "files")
    return conn, config, file_store


def _format_paper_row(row, labels: str = "") -> str:
    """Format a single paper row for terminal display."""
    fid = row["id"][:20]
    title = row["title"][:60]
    inst = (row["institution"] or "-")[:12]
    date = (row["publication_date"] or "-")[:10]
    stype = row["source_type"][:15]
    access = row["access_status"][:12]

    return f"{fid:<21} {date:<11} {stype:<16} {access:<13} {inst:<13} {title}"


def _resolve_watchlist(config, metadata):
    """Return canonical affiliation matches and their descending sort score."""
    matches = config.resolve_metadata_institutions(metadata)
    score = max((match.priority_score for match in matches), default=0)
    return matches, score


@click.group()
@click.version_option(version="0.1.0", prog_name="paperdb")
def main():
    """PaperDB — AI-driven paper search engine for Chinese A-share quant research."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@main.command()
@click.option("--root", default=None, help="Paper database root directory (default: ./paper_database)")
def init(root):
    """Initialize the paper database and file store structure.

    Creates the SQLite database, file storage directories, and default
    configuration files. Safe to run multiple times (idempotent).
    """
    r = _resolve_root(root)

    # Create directory structure
    r.mkdir(parents=True, exist_ok=True)
    (r / "db").mkdir(exist_ok=True)
    (r / "config").mkdir(exist_ok=True)
    (r / "logs").mkdir(exist_ok=True)
    (r / "index").mkdir(exist_ok=True)

    # Initialize file store
    fs = FileStore(r / "files")
    fs.init()

    # Initialize database
    db_path = r / "db" / "papers.sqlite"
    conn = init_db(db_path)

    # Insert default admin user if not exists
    existing = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if not existing:
        from paperdb.db.models import User
        admin = User(name="admin", role="admin")
        conn.execute(
            "INSERT INTO users (id, name, email, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (admin.id, admin.name, admin.email, admin.role, admin.created_at),
        )
        conn.commit()

    # Write default config files
    config = Config(r)
    config_dir = r / "config"

    _write_yaml(config_dir / "taxonomy.yaml", _default_taxonomy())
    _write_yaml(config_dir / "sources.yaml", {
        "connectors": {
            "arxiv": {"enabled": True, "categories": ["q-fin.ST", "q-fin.PM", "q-fin.RM", "stat.ML", "cs.LG"]},
            "choice": {"enabled": True, "requires_auth": True, "auth_type": "terminal"},
            "semantic_scholar": {"enabled": True},
        },
        "search_defaults": {"max_results": 50},
    })
    _write_yaml(config_dir / "watchlist.yaml", DEFAULT_WATCHLIST)
    _write_yaml(config_dir / "embedding.yaml", {
        "backend": "local",
        "local": {"model": "BAAI/bge-large-zh-v1.5", "device": "auto"},
        "openai": {"model": "text-embedding-3-small"},
    })

    conn.close()
    click.echo(f"✓ PaperDB initialized at {r}")
    click.echo(f"  Database: {db_path}")
    click.echo(f"  Files:    {r / 'files'}")
    click.echo(f"  Config:   {config_dir}")
    click.echo(f"  Default admin user created (admin)")


def _write_yaml(path: Path, data: dict) -> None:
    """Write dict as YAML, skipping if file already exists."""
    if not path.exists():
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# ingest group
# ---------------------------------------------------------------------------

@main.group()
def ingest():
    """Ingest papers into the database."""


@ingest.command("from-url")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--title", required=True, help="Paper title")
@click.option("--url", required=True, help="Download URL")
@click.option("--source-type", required=True, type=click.Choice([
    "academic_paper", "broker_report", "white_paper", "blog_article", "manual_upload", "other"
]), help="Type of source")
@click.option("--source-name", default="web", help="Source name (e.g. 'arxiv', 'choice', 'web')")
@click.option("--authors", default=None, help="Semicolon-delimited author names")
@click.option("--institution", default=None, help="Institution / broker / research org")
@click.option("--download-url", default=None, help="Direct file URL for delayed downloads")
@click.option("--github-url", default=None, help="Related GitHub repository URL")
@click.option("--date", "publication_date", default=None, help="Publication date (YYYY-MM-DD or YYYY-MM)")
@click.option("--abstract", default=None, help="Abstract text")
@click.option("--market", default=None, help="Market (a_share, hk_equity, us_equity, etc.)")
@click.option("--frequency", default=None, help="Frequency (daily, weekly, monthly, etc.)")
@click.option("--language", default=None, help="Language (zh, en, bilingual, other)")
@click.option("--priority", "priority_score", default=0, type=int, help="Priority score")
@click.option("--batch", "batch_id", default=None, help="Batch ID for grouping")
@click.option("--added-by", default=None, help="User ID who added this paper")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def ingest_from_url_cmd(
    root, title, url, source_type, source_name, authors, institution, download_url, github_url,
    publication_date, abstract, market, frequency, language,
    priority_score, batch_id, added_by, output_json,
):
    """Download and ingest a paper from a URL."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        result = ingest_from_url(
            conn, file_store,
            title=title, url=url, source_type=source_type,
            source_name=source_name, authors_raw=authors,
            institution=institution, download_url=download_url, github_url=github_url,
            publication_date=publication_date,
            abstract=abstract, market=market, frequency=frequency,
            language=language, priority_score=priority_score,
            batch_id=batch_id, added_by=added_by,
        )
        _report_result(result, output_json)
    except Exception as e:
        conn.rollback()
        _error(str(e), output_json)
    finally:
        conn.close()


@ingest.command("from-file")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--title", required=True, help="Paper title")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True), help="Path to the file to import")
@click.option("--source-type", required=True, type=click.Choice([
    "academic_paper", "broker_report", "white_paper", "blog_article", "manual_upload", "other"
]), help="Type of source")
@click.option("--source-name", default="manual_upload", help="Source name")
@click.option("--authors", default=None, help="Semicolon-delimited author names")
@click.option("--institution", default=None, help="Institution / broker / research org")
@click.option("--source-url", default=None, help="Original source URL")
@click.option("--download-url", default=None, help="Direct file URL for delayed downloads")
@click.option("--github-url", default=None, help="Related GitHub repository URL")
@click.option("--date", "publication_date", default=None, help="Publication date (YYYY-MM-DD)")
@click.option("--abstract", default=None, help="Abstract text")
@click.option("--market", default=None, help="Market")
@click.option("--frequency", default=None, help="Frequency")
@click.option("--language", default=None, help="Language")
@click.option("--priority", "priority_score", default=0, type=int, help="Priority score")
@click.option("--batch", "batch_id", default=None, help="Batch ID")
@click.option("--added-by", default=None, help="User ID")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def ingest_from_file_cmd(
    root, title, file_path, source_type, source_name, authors, institution,
    source_url, download_url, github_url, publication_date, abstract, market, frequency, language,
    priority_score, batch_id, added_by, output_json,
):
    """Import a local file into the database."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        result = ingest_from_file(
            conn, file_store,
            title=title, file_path=file_path, source_type=source_type,
            source_name=source_name, authors_raw=authors,
            institution=institution, source_url=source_url,
            download_url=download_url,
            github_url=github_url,
            publication_date=publication_date, abstract=abstract,
            market=market, frequency=frequency, language=language,
            priority_score=priority_score, batch_id=batch_id,
            added_by=added_by,
        )
        _report_result(result, output_json)
    except Exception as e:
        conn.rollback()
        _error(str(e), output_json)
    finally:
        conn.close()


@ingest.command("metadata-only")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--title", required=True, help="Paper title")
@click.option("--source-type", required=True, type=click.Choice([
    "academic_paper", "broker_report", "white_paper", "blog_article", "manual_upload", "other"
]), help="Type of source")
@click.option("--source-name", default="web", help="Source name")
@click.option("--authors", default=None, help="Semicolon-delimited author names")
@click.option("--institution", default=None, help="Institution / broker")
@click.option("--source-url", default=None, help="Source URL")
@click.option("--download-url", default=None, help="Direct file URL for delayed downloads")
@click.option("--github-url", default=None, help="Related GitHub repository URL")
@click.option("--date", "publication_date", default=None, help="Publication date")
@click.option("--abstract", default=None, help="Abstract")
@click.option("--market", default=None, help="Market")
@click.option("--frequency", default=None, help="Frequency")
@click.option("--language", default=None, help="Language")
@click.option("--access-status", default="manual_required", help="Access status")
@click.option("--access-notes", default=None, help="Access notes (e.g. terminal name)")
@click.option("--priority", "priority_score", default=0, type=int, help="Priority score")
@click.option("--batch", "batch_id", default=None, help="Batch ID")
@click.option("--added-by", default=None, help="User ID")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def ingest_metadata_cmd(
    root, title, source_type, source_name, authors, institution,
    source_url, download_url, github_url, publication_date, abstract, market, frequency, language,
    access_status, access_notes, priority_score, batch_id, added_by,
    output_json,
):
    """Store paper metadata without downloading the file."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        result = ingest_metadata_only(
            conn,
            title=title, source_type=source_type, source_name=source_name,
            authors_raw=authors, institution=institution,
            source_url=source_url, download_url=download_url, github_url=github_url,
            publication_date=publication_date,
            abstract=abstract, market=market, frequency=frequency,
            language=language, access_status=access_status,
            access_notes=access_notes, priority_score=priority_score,
            batch_id=batch_id, added_by=added_by,
        )
        _report_result(result, output_json)
    except Exception as e:
        conn.rollback()
        _error(str(e), output_json)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

@main.command()
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--label", multiple=True, help="Filter by label (repeatable)")
@click.option("--market", "market_filter", default=None, help="Filter by market")
@click.option("--source-type", "source_type_filter", default=None, help="Filter by source type")
@click.option("--institution", "inst_filter", default=None, help="Filter by institution (LIKE match)")
@click.option("--date-from", default=None, help="Publication date from (YYYY-MM-DD)")
@click.option("--date-to", default=None, help="Publication date to (YYYY-MM-DD)")
@click.option("--search", default=None, help="Keyword search in title and abstract")
@click.option("--access-status", "access_filter", default=None, help="Filter by access status")
@click.option("--language", "lang_filter", default=None, help="Filter by language")
@click.option("--lifecycle-status", default="active", help="Filter lifecycle status (default: active)")
@click.option("--include-rejected", is_flag=True, help="Include rejected/archived records")
@click.option("--limit", default=50, type=int, help="Max results (default: 50)")
@click.option("--offset", default=0, type=int, help="Offset for pagination")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def query(
    root, label, market_filter, source_type_filter, inst_filter,
    date_from, date_to, search, access_filter, lang_filter, lifecycle_status, include_rejected,
    limit, offset, output_json,
):
    """Search and filter papers in the database."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        # Build query
        where = ["1=1"]
        params = []
        if not include_rejected:
            where.append("lifecycle_status = ?")
            params.append(lifecycle_status)

        if label:
            # Papers that have ALL specified labels
            placeholders = ",".join("?" for _ in label)
            where.append(f"""id IN (
                SELECT paper_id FROM paper_labels
                WHERE label IN ({placeholders})
                GROUP BY paper_id
                HAVING COUNT(DISTINCT label) = ?
            )""")
            params.extend(label)
            params.append(len(label))

        if market_filter:
            where.append("market = ?")
            params.append(market_filter)

        if source_type_filter:
            where.append("source_type = ?")
            params.append(source_type_filter)

        if inst_filter:
            inst_filter = config.canonicalize_institution_filter(inst_filter)
            where.append("""(institution LIKE ? OR id IN (
                SELECT paper_id FROM paper_institutions
                WHERE canonical_name LIKE ? OR raw_value LIKE ? OR matched_alias LIKE ?
            ))""")
            params.extend([f"%{inst_filter}%"] * 4)

        if date_from:
            where.append("publication_date >= ?")
            params.append(date_from)

        if date_to:
            where.append("publication_date <= ?")
            params.append(date_to)

        if search:
            where.append("(title LIKE ? OR abstract LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        if access_filter:
            where.append("access_status = ?")
            params.append(access_filter)

        if lang_filter:
            where.append("language = ?")
            params.append(lang_filter)

        where_clause = " AND ".join(where)
        count_sql = f"SELECT COUNT(*) FROM papers WHERE {where_clause}"
        total = conn.execute(count_sql, params).fetchone()[0]

        sql = f"""SELECT * FROM papers WHERE {where_clause}
                  ORDER BY priority_score DESC, publication_date DESC
                  LIMIT ? OFFSET ?"""
        rows = conn.execute(sql, params + [limit, offset]).fetchall()

        if output_json:
            results = []
            for row in rows:
                paper = dict(row)
                # Attach labels
                labels = conn.execute(
                    "SELECT label FROM paper_labels WHERE paper_id = ?", (paper["id"],)
                ).fetchall()
                paper["labels"] = [l["label"] for l in labels]
                results.append(paper)
            click.echo(json.dumps({"total": total, "limit": limit, "offset": offset, "results": results}, ensure_ascii=False, indent=2))
        else:
            click.echo(f"\n{'ID':<21} {'Date':<11} {'Type':<16} {'Access':<13} {'Inst':<13} Title")
            click.echo("-" * 90)
            for row in rows:
                click.echo(_format_paper_row(row))
            click.echo(f"\nShowing {len(rows)} of {total} papers" + (f" (offset {offset})" if offset else ""))

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

@main.command()
@click.argument("paper_id")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def info(paper_id, root, output_json):
    """Show full details of a paper by ID."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not row:
            # Try partial match
            row = conn.execute("SELECT * FROM papers WHERE id LIKE ?", (f"{paper_id}%",)).fetchone()
        if not row:
            _error(f"Paper not found: {paper_id}", output_json)
            return

        labels = conn.execute(
            "SELECT label, confidence, source FROM paper_labels WHERE paper_id = ? ORDER BY label",
            (row["id"],),
        ).fetchall()

        authors = conn.execute(
            "SELECT author_name, institution FROM paper_authors WHERE paper_id = ? ORDER BY author_order",
            (row["id"],),
        ).fetchall()
        institution_matches = conn.execute(
            """SELECT canonical_name, raw_value, matched_alias, priority_rank,
                      priority_score, match_source, confidence
               FROM paper_institutions WHERE paper_id = ?
               ORDER BY priority_score DESC, canonical_name""",
            (row["id"],),
        ).fetchall()

        if output_json:
            paper = dict(row)
            paper["labels"] = [{"label": l["label"], "confidence": l["confidence"], "source": l["source"]} for l in labels]
            paper["authors"] = [{"name": a["author_name"], "institution": a["institution"]} for a in authors]
            paper["institution_matches"] = [dict(match) for match in institution_matches]
            click.echo(json.dumps(paper, ensure_ascii=False, indent=2))
        else:
            click.echo(f"\n{'='*70}")
            click.echo(f"ID:          {row['id']}")
            click.echo(f"Title:       {row['title']}")
            if row["title_en"]:
                click.echo(f"Title (EN):  {row['title_en']}")
            click.echo(f"Authors:     {row['authors_raw'] or '-'}")
            if authors:
                for a in authors:
                    inst_str = f" ({a['institution']})" if a["institution"] else ""
                    click.echo(f"             {a['author_name']}{inst_str}")
            click.echo(f"Institution: {row['institution'] or '-'}")
            for match in institution_matches:
                click.echo(
                    f"Institution ID: {match['canonical_name']} "
                    f"(rank {match['priority_rank']}, via {match['match_source']}, "
                    f"confidence {match['confidence']:.2f})"
                )
            click.echo(f"Source:      {row['source_name']} ({row['source_type']})")
            if row["source_url"]:
                click.echo(f"URL:         {row['source_url']}")
            if row["download_url"]:
                click.echo(f"Download:    {row['download_url']}")
            if row["github_url"]:
                click.echo(f"GitHub:      {row['github_url']}")
                if row["github_evidence_type"]:
                    click.echo(f"GitHub via:  {row['github_evidence_type']} ({row['github_evidence_url'] or '-'})")
            click.echo(f"Date:        {row['publication_date'] or '-'}")
            click.echo(f"Market:      {row['market'] or '-'}")
            click.echo(f"Frequency:   {row['frequency'] or '-'}")
            click.echo(f"Language:    {row['language'] or '-'}")
            click.echo(f"Access:      {row['access_status']}")
            click.echo(f"Lifecycle:   {row['lifecycle_status']}")
            click.echo(f"Metadata:    {row['metadata_quality']}")
            click.echo(f"Screening:   {row['quality_screening_status']}")
            if row["access_notes"]:
                click.echo(f"Access note: {row['access_notes']}")
            if row["file_path"]:
                click.echo(f"File:        {row['file_path']} ({row['file_format']})")
            if labels:
                click.echo(f"Labels:")
                for l in labels:
                    conf = f" ({l['confidence']:.2f})" if l["confidence"] else ""
                    src = f" [{l['source']}]"
                    click.echo(f"             {l['label']}{conf}{src}")
            if row["abstract"]:
                click.echo(f"\nAbstract:\n{row['abstract'][:500]}")
            if row["ai_summary"]:
                click.echo(f"\nAI Summary:\n{row['ai_summary'][:500]}")
            click.echo(f"{'='*70}\n")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

@main.command()
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def stats(root, output_json):
    """Show database summary statistics."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

        by_type = conn.execute(
            "SELECT source_type, COUNT(*) as cnt FROM papers GROUP BY source_type ORDER BY cnt DESC"
        ).fetchall()

        by_market = conn.execute(
            "SELECT market, COUNT(*) as cnt FROM papers WHERE market IS NOT NULL GROUP BY market ORDER BY cnt DESC"
        ).fetchall()

        by_access = conn.execute(
            "SELECT access_status, COUNT(*) as cnt FROM papers GROUP BY access_status ORDER BY cnt DESC"
        ).fetchall()

        by_label = conn.execute(
            "SELECT label, COUNT(*) as cnt FROM paper_labels GROUP BY label ORDER BY cnt DESC LIMIT 20"
        ).fetchall()

        by_institution = conn.execute(
            "SELECT institution, COUNT(*) as cnt FROM papers WHERE institution IS NOT NULL GROUP BY institution ORDER BY cnt DESC LIMIT 10"
        ).fetchall()

        by_language = conn.execute(
            "SELECT language, COUNT(*) as cnt FROM papers WHERE language IS NOT NULL GROUP BY language ORDER BY cnt DESC"
        ).fetchall()

        if output_json:
            click.echo(json.dumps({
                "total_papers": total,
                "by_source_type": {r["source_type"]: r["cnt"] for r in by_type},
                "by_market": {r["market"]: r["cnt"] for r in by_market},
                "by_access_status": {r["access_status"]: r["cnt"] for r in by_access},
                "by_label": {r["label"]: r["cnt"] for r in by_label},
                "by_institution": {r["institution"]: r["cnt"] for r in by_institution},
                "by_language": {r["language"]: r["cnt"] for r in by_language},
            }, ensure_ascii=False, indent=2))
        else:
            click.echo(f"\n  Total papers: {total}\n")

            if by_type:
                click.echo("  By source type:")
                for r in by_type:
                    click.echo(f"    {r['source_type']:<20} {r['cnt']:>5}")
                click.echo()

            if by_market:
                click.echo("  By market:")
                for r in by_market:
                    click.echo(f"    {r['market']:<20} {r['cnt']:>5}")
                click.echo()

            if by_access:
                click.echo("  By access status:")
                for r in by_access:
                    click.echo(f"    {r['access_status']:<20} {r['cnt']:>5}")
                click.echo()

            if by_label:
                click.echo("  Top labels:")
                for r in by_label:
                    click.echo(f"    {r['label']:<30} {r['cnt']:>5}")

            if by_institution:
                click.echo(f"\n  Top institutions:")
                for r in by_institution:
                    click.echo(f"    {r['institution']:<25} {r['cnt']:>5}")

            if by_language:
                click.echo(f"\n  By language:")
                for r in by_language:
                    click.echo(f"    {r['language']:<20} {r['cnt']:>5}")

            click.echo()

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# label group
# ---------------------------------------------------------------------------

@main.group()
def label():
    """Manage paper labels."""


@label.command("add")
@click.argument("paper_id")
@click.argument("label_name")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--confidence", type=float, default=None, help="Confidence score (0-1)")
@click.option("--source", "label_source", default="ai_auto", help="Label source")
@click.option("--added-by", default=None, help="User ID")
def label_add(paper_id, label_name, root, confidence, label_source, added_by):
    """Add a label to a paper."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        # Verify paper exists
        paper = conn.execute("SELECT id FROM papers WHERE id = ? OR id LIKE ?",
                             (paper_id, f"{paper_id}%")).fetchone()
        if not paper:
            _error(f"Paper not found: {paper_id}", False)
            return

        pid = paper["id"]

        # Check for existing label
        existing = conn.execute(
            "SELECT id FROM paper_labels WHERE paper_id = ? AND label = ?",
            (pid, label_name),
        ).fetchone()

        if existing:
            click.echo(f"Label '{label_name}' already exists on {pid}")
            return

        from paperdb.db.models import PaperLabel
        lbl = PaperLabel(
            paper_id=pid,
            label=label_name,
            confidence=confidence,
            source=label_source,
            added_by=added_by,
        )
        conn.execute(
            """INSERT INTO paper_labels (id, paper_id, label, confidence, source, added_by, created_at)
               VALUES (:id, :paper_id, :label, :confidence, :source, :added_by, :created_at)""",
            lbl.to_dict(),
        )
        conn.commit()
        click.echo(f"✓ Added label '{label_name}' to {pid}")
    finally:
        conn.close()


@label.command("list")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--source", "source_filter", default=None, help="Filter by label source")
def label_list(root, source_filter):
    """List all labels by frequency."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        if source_filter:
            rows = conn.execute(
                "SELECT label, source, COUNT(*) as cnt FROM paper_labels "
                "WHERE source = ? GROUP BY label, source ORDER BY cnt DESC",
                (source_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT label, COUNT(*) as cnt FROM paper_labels "
                "GROUP BY label ORDER BY cnt DESC"
            ).fetchall()

        if not rows:
            click.echo("No labels found.")
            return

        click.echo(f"\n{'Label':<35} Count")
        click.echo("-" * 50)
        for r in rows:
            src_str = f" [{r['source']}]" if source_filter and "source" in r.keys() else ""
            click.echo(f"{r['label']:<35} {r['cnt']:>5}{src_str}")
        click.echo()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# update command (modify paper fields)
# ---------------------------------------------------------------------------

@main.command("update")
@click.argument("paper_id")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--ai-summary", default=None, help="Set AI-generated summary")
@click.option("--abstract", default=None, help="Set abstract")
@click.option("--market", "market_val", default=None, help="Set market")
@click.option("--frequency", "freq_val", default=None, help="Set frequency")
@click.option("--language", "lang_val", default=None, help="Set language")
@click.option("--download-url", default=None, help="Set direct file URL for delayed downloads")
@click.option("--github-url", default=None, help="Set related GitHub repository URL")
@click.option("--access-status", default=None, help="Set access status")
@click.option("--access-notes", default=None, help="Set access notes")
@click.option("--lifecycle-status", type=click.Choice(["active", "rejected_out_of_scope", "archived"]), default=None)
@click.option("--metadata-quality", type=click.Choice(["verified", "partial", "suspicious"]), default=None)
@click.option("--quality-screening-status", type=click.Choice([
    "metadata_only", "full_text_available", "quality_screened", "insufficient_evidence"
]), default=None)
@click.option("--github-evidence-type", default=None, help="Evidence type for GitHub URL")
@click.option("--github-evidence-url", default=None, help="Page containing the GitHub evidence")
def update_paper(paper_id, root, ai_summary, abstract, market_val, freq_val,
                 lang_val, download_url, github_url, access_status, access_notes,
                 lifecycle_status, metadata_quality, github_evidence_type,
                 github_evidence_url, quality_screening_status):
    """Update metadata fields on a paper."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        row = conn.execute(
            "SELECT id FROM papers WHERE id = ? OR id LIKE ?",
            (paper_id, f"{paper_id}%"),
        ).fetchone()
        if not row:
            _error(f"Paper not found: {paper_id}", False)
            return

        pid = row["id"]
        from paperdb.db.models import now_iso

        updates = {"updated_at": now_iso()}
        if ai_summary is not None:
            updates["ai_summary"] = ai_summary
        if abstract is not None:
            updates["abstract"] = abstract
        if market_val is not None:
            updates["market"] = market_val
        if freq_val is not None:
            updates["frequency"] = freq_val
        if lang_val is not None:
            updates["language"] = lang_val
        if download_url is not None:
            updates["download_url"] = download_url
        if github_url is not None:
            updates["github_url"] = github_url
        if access_status is not None:
            updates["access_status"] = access_status
        if access_notes is not None:
            updates["access_notes"] = access_notes
        if lifecycle_status is not None:
            updates["lifecycle_status"] = lifecycle_status
        if metadata_quality is not None:
            updates["metadata_quality"] = metadata_quality
        if quality_screening_status is not None:
            updates["quality_screening_status"] = quality_screening_status
        if github_evidence_type is not None:
            updates["github_evidence_type"] = github_evidence_type
        if github_evidence_url is not None:
            updates["github_evidence_url"] = github_evidence_url

        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = pid
        conn.execute(f"UPDATE papers SET {set_clause} WHERE id = :id", updates)
        conn.commit()

        if ai_summary is not None:
            paper = conn.execute("SELECT title, abstract FROM papers WHERE id = ?", (pid,)).fetchone()
            if paper:
                try:
                    from paperdb.search.indexer import index_paper
                    index_paper(conn, r / "index" / "vector", pid, paper["title"], paper["abstract"])
                except Exception:
                    pass

        click.echo(f"✓ Updated {pid}")
    finally:
        conn.close()


@main.command("reject")
@click.argument("paper_id")
@click.option("--reason", required=True, help="Auditable out-of-scope reason")
@click.option("--root", default=None, help="Paper database root directory")
def reject_paper(paper_id, reason, root):
    """Mark a paper out of scope without inventing a research label."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)
    try:
        row = conn.execute("SELECT id FROM papers WHERE id = ? OR id LIKE ?",
                           (paper_id, f"{paper_id}%")).fetchone()
        if not row:
            raise click.ClickException(f"Paper not found: {paper_id}")
        from paperdb.db.models import now_iso
        conn.execute(
            """UPDATE papers SET lifecycle_status = 'rejected_out_of_scope',
               quality_flag = 'needs_review', access_notes = ?, updated_at = ?
               WHERE id = ?""",
            (reason, now_iso(), row["id"]),
        )
        conn.commit()
        click.echo(f"✓ Rejected {row['id']}: {reason}")
    finally:
        conn.close()


@main.command("search-metrics")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--limit", default=20, type=int)
@click.option("--json", "output_json", is_flag=True)
def search_metrics(root, limit, output_json):
    """Report search precision, inspection yield, and novelty metrics."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)
    try:
        rows = conn.execute(
            "SELECT * FROM search_logs ORDER BY searched_at DESC LIMIT ?", (limit,)
        ).fetchall()
        data = []
        for row in rows:
            item = dict(row)
            inspected = item.get("inspected_count") or 0
            accepted = item.get("accepted_count") or 0
            new = item.get("new_papers") or 0
            item["inspection_yield"] = accepted / inspected if inspected else 0
            item["novelty_rate"] = new / accepted if accepted else 0
            data.append(item)
        if output_json:
            click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            for item in data:
                click.echo(
                    f"{item['searched_at'][:19]} {item['source_name'] or '-':<10} "
                    f"returned={item['results_count'] or 0} inspected={item['inspected_count']} "
                    f"accepted={item['accepted_count']} rejected={item['rejected_count']} "
                    f"yield={item['inspection_yield']:.0%}"
                )
    finally:
        conn.close()


@main.command("institution-refresh")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--json", "output_json", is_flag=True)
def institution_refresh(root, output_json):
    """Recompute canonical watchlist matches and correctly ordered priorities."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)
    try:
        from paperdb.config.institutions import refresh_institution_matches
        result = refresh_institution_matches(conn, config.watchlist.get("institutions", []))
        if output_json:
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(
                f"Scanned {result['papers_scanned']} papers; matched "
                f"{result['papers_matched']} papers ({result['matches_stored']} evidence rows)."
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# delayed download commands
# ---------------------------------------------------------------------------

def _connector_for_paper(row):
    """Return the best connector for a paper row, if one is available."""
    if row["source_name"] == "arxiv":
        from paperdb.connectors.arxiv_connector import ArxivConnector
        return ArxivConnector()
    return None


@main.command("download")
@click.argument("paper_id")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def download_paper(paper_id, root, output_json):
    """Download the file for an existing metadata-only paper."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        row = conn.execute(
            "SELECT * FROM papers WHERE id = ? OR id LIKE ?",
            (paper_id, f"{paper_id}%"),
        ).fetchone()
        if not row:
            _error(f"Paper not found: {paper_id}", output_json)
            return

        result = download_paper_file(
            conn,
            file_store,
            row["id"],
            connector=_connector_for_paper(row),
        )

        payload = {
            "paper_id": row["id"],
            "success": result.success,
            "file_path": result.local_path,
            "file_size": result.file_size,
            "error": result.error,
            "error_type": result.error_type,
            "retryable": result.retryable,
        }
        if output_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        elif result.success:
            click.echo(f"Downloaded {row['id'][:20]} -> {result.local_path}")
        else:
            click.echo(f"Download failed for {row['id'][:20]}: {result.error}")
    finally:
        conn.close()


@main.command("download-missing")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--label", multiple=True, help="Filter by label (repeatable)")
@click.option("--market", "market_filter", default=None, help="Filter by market")
@click.option("--source-name", default=None, help="Filter by source name, e.g. arxiv")
@click.option("--limit", default=10, type=int, help="Max papers to download")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def download_missing(root, label, market_filter, source_name, limit, output_json):
    """Download queued/failed papers that have a known download URL."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        where = [
            "file_path IS NULL",
            "access_status IN ('queued', 'failed')",
            "(download_url IS NOT NULL OR (source_name = 'arxiv' AND source_url IS NOT NULL))",
        ]
        params = []

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

        if market_filter:
            where.append("market = ?")
            params.append(market_filter)

        if source_name:
            where.append("source_name = ?")
            params.append(source_name)

        sql = f"""SELECT * FROM papers
                  WHERE {' AND '.join(where)}
                  ORDER BY priority_score DESC, publication_date DESC
                  LIMIT ?"""
        rows = conn.execute(sql, params + [limit]).fetchall()

        outcomes = []
        for row in rows:
            result = download_paper_file(
                conn,
                file_store,
                row["id"],
                connector=_connector_for_paper(row),
            )
            outcomes.append({
                "paper_id": row["id"],
                "title": row["title"],
                "success": result.success,
                "file_path": result.local_path,
                "file_size": result.file_size,
                "error": result.error,
            })
            if not output_json:
                if result.success:
                    click.echo(f"  ✓ {row['id'][:20]}  {row['title'][:60]}")
                else:
                    click.echo(f"  ✗ {row['id'][:20]}  {result.error}")

        downloaded = sum(1 for r in outcomes if r["success"])
        failed = sum(1 for r in outcomes if not r["success"])
        if output_json:
            click.echo(json.dumps({
                "matched": len(rows),
                "downloaded": downloaded,
                "failed": failed,
                "results": outcomes,
            }, ensure_ascii=False, indent=2))
        else:
            click.echo(f"\nDone. {downloaded} downloaded, {failed} failed.")
    finally:
        conn.close()


@main.command("download-status")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--limit", default=20, type=int, help="Recent log rows to show")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def download_status(root, limit, output_json):
    """Show current download backlog and recent attempts."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        by_access = conn.execute(
            "SELECT access_status, COUNT(*) AS cnt FROM papers GROUP BY access_status ORDER BY cnt DESC"
        ).fetchall()
        backlog = conn.execute(
            """SELECT COUNT(*) FROM papers
               WHERE file_path IS NULL
                 AND access_status IN ('queued', 'failed')
                 AND (download_url IS NOT NULL OR (source_name = 'arxiv' AND source_url IS NOT NULL))"""
        ).fetchone()[0]
        logs = conn.execute(
            """SELECT d.*, p.title
               FROM download_logs d
               LEFT JOIN papers p ON p.id = d.paper_id
               ORDER BY d.attempt_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        if output_json:
            click.echo(json.dumps({
                "by_access_status": {r["access_status"]: r["cnt"] for r in by_access},
                "downloadable_backlog": backlog,
                "recent_logs": [dict(r) for r in logs],
            }, ensure_ascii=False, indent=2))
        else:
            click.echo("\nAccess status:")
            for row in by_access:
                click.echo(f"  {row['access_status']:<14} {row['cnt']:>5}")
            click.echo(f"\nDownloadable backlog: {backlog}")
            if logs:
                click.echo("\nRecent download attempts:")
                for row in logs:
                    title = (row["title"] or "-")[:50]
                    err = f" ({row['error_detail']})" if row["error_detail"] else ""
                    click.echo(f"  {row['attempt_at'][:19]}  {row['status']:<8} {title}{err}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# summary command group
# ---------------------------------------------------------------------------

@main.group()
def summary():
    """Manage AI-generated paper summaries."""


@summary.command("set")
@click.argument("paper_id")
@click.argument("text")
@click.option("--root", default=None, help="Paper database root directory")
def summary_set(paper_id, text, root):
    """Set the AI summary for a paper."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        row = conn.execute(
            "SELECT id FROM papers WHERE id = ? OR id LIKE ?",
            (paper_id, f"{paper_id}%"),
        ).fetchone()
        if not row:
            _error(f"Paper not found: {paper_id}", False)
            return

        pid = row["id"]
        conn.execute(
            "UPDATE papers SET ai_summary = ?, updated_at = datetime('now') WHERE id = ?",
            (text, pid),
        )
        conn.commit()
        click.echo(f"✓ Summary set for {pid}")
    finally:
        conn.close()


@summary.command("list")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--missing", is_flag=True, help="Show only papers WITHOUT summaries")
def summary_list(root, missing):
    """List papers and their summary status."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        if missing:
            rows = conn.execute(
                "SELECT id, title FROM papers WHERE ai_summary IS NULL OR ai_summary = '' ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, ai_summary FROM papers ORDER BY created_at DESC LIMIT 20"
            ).fetchall()

        if not rows:
            click.echo("No papers found.")
            return

        for row in rows:
            has = "✓" if ("ai_summary" in row.keys() and row["ai_summary"]) else "✗"
            click.echo(f"  {has} {row['id'][:20]}  {row['title'][:60]}")
        click.echo(f"\n{len(rows)} papers.")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# search command (hybrid: keyword + vector)
# ---------------------------------------------------------------------------

@main.command("search")
@click.argument("query")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--mode", type=click.Choice(["hybrid", "keyword", "vector"]), default="hybrid",
              help="Search mode (default: hybrid)")
@click.option("--label", multiple=True, help="Filter by label (repeatable)")
@click.option("--market", default=None, help="Filter by market")
@click.option("--source-type", "source_type_filter", default=None, help="Filter by source type")
@click.option("--institution", "inst_filter", default=None, help="Filter by institution")
@click.option("--date-from", default=None, help="Publication date from")
@click.option("--date-to", default=None, help="Publication date to")
@click.option("--limit", default=20, type=int, help="Max results (default: 20)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def search_cmd(query, root, mode, label, market, source_type_filter, inst_filter,
               date_from, date_to, limit, output_json):
    """Hybrid search across papers (keyword + semantic).

    Searches paper titles and abstracts using a combination of FTS5
    keyword matching and (if available) BGE vector similarity.
    """
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)
    index_dir = r / "index" / "vector"

    try:
        from paperdb.search.hybrid import HybridSearcher

        searcher = HybridSearcher(conn, index_dir)

        # Build filters
        filters = {}
        if market:
            filters["market"] = market
        if source_type_filter:
            filters["source_type"] = source_type_filter
        if inst_filter:
            filters["institution"] = config.canonicalize_institution_filter(inst_filter)
        if date_from:
            filters["date_from"] = date_from
        if date_to:
            filters["date_to"] = date_to

        results = searcher.search(query, limit=limit, filters=filters, mode=mode)

        if not results:
            if output_json:
                click.echo(json.dumps({"total": 0, "results": []}, ensure_ascii=False))
            else:
                click.echo("No results found. Try rebuilding the index: paperdb index rebuild")
            return

        # Fetch full paper rows for display
        paper_ids = [pid for pid, _ in results]
        placeholders = ",".join("?" for _ in paper_ids)
        rows = conn.execute(
            f"SELECT * FROM papers WHERE id IN ({placeholders})",
            paper_ids,
        ).fetchall()

        # Maintain RRF order
        id_to_row = {r["id"]: r for r in rows}
        ordered = []
        seen = set()
        for pid, score in results:
            if pid in id_to_row and pid not in seen:
                ordered.append((id_to_row[pid], score))
                seen.add(pid)

        if label:
            # Filter by labels (post-filter)
            ordered = _filter_by_labels(conn, ordered, label)

        if output_json:
            out = []
            for paper, score in ordered:
                labels = conn.execute(
                    "SELECT label FROM paper_labels WHERE paper_id = ?", (paper["id"],)
                ).fetchall()
                out.append({
                    "paper_id": paper["id"],
                    "title": paper["title"],
                    "authors": paper["authors_raw"],
                    "institution": paper["institution"],
                    "source_type": paper["source_type"],
                    "publication_date": paper["publication_date"],
                    "abstract": (paper["abstract"] or "")[:300],
                    "github_url": paper["github_url"],
                    "access_status": paper["access_status"],
                    "labels": [l["label"] for l in labels],
                    "score": round(score, 4),
                })
            click.echo(json.dumps({"total": len(out), "results": out}, ensure_ascii=False, indent=2))
        else:
            click.echo(f"\n  Query: {query}  |  Mode: {mode}  |  Results: {len(ordered)}")
            if not searcher.vector_available:
                click.echo("  (vector search unavailable — install sentence-transformers)")
            click.echo(f"  {'ID':<21} {'Score':<8} {'Date':<11} {'Type':<16} Title")
            click.echo("  " + "-" * 85)
            for paper, score in ordered[:limit]:
                fid = paper["id"][:20]
                date = (paper["publication_date"] or "-")[:10]
                stype = paper["source_type"][:15]
                title = paper["title"][:55]
                click.echo(f"  {fid:<21} {score:<8.4f} {date:<11} {stype:<16} {title}")
            click.echo()

    finally:
        conn.close()


def _filter_by_labels(conn, ordered, labels):
    """Post-filter results to only include papers with all specified labels."""
    result = []
    for paper, score in ordered:
        paper_labels = conn.execute(
            "SELECT label FROM paper_labels WHERE paper_id = ?", (paper["id"],)
        ).fetchall()
        paper_label_set = {l["label"] for l in paper_labels}
        if all(lbl in paper_label_set for lbl in labels):
            result.append((paper, score))
    return result


# ---------------------------------------------------------------------------
# index command group
# ---------------------------------------------------------------------------

@main.group()
def index():
    """Manage search indexes (FTS5 keyword + vector)."""


@index.command("rebuild")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--fts-only", is_flag=True, help="Rebuild only FTS5 index (skip vector)")
@click.option("--vector-only", is_flag=True, help="Rebuild only vector index (skip FTS5)")
def index_rebuild(root, fts_only, vector_only):
    """Rebuild search indexes from the papers table.

    Rebuilds the FTS5 keyword index (always) and the BGE vector index
    (if sentence-transformers is installed). Safe to run at any time.
    """
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)
    index_dir = r / "index" / "vector"

    try:
        from paperdb.search.indexer import build_index
        from paperdb.search.vector import has_vector_support

        rebuild_fts = not vector_only
        rebuild_vector = not fts_only

        click.echo("Rebuilding search indexes...")
        result = build_index(
            conn, index_dir,
            rebuild_fts=rebuild_fts,
            rebuild_vector=rebuild_vector,
            verbose=True,
        )

        click.echo(f"\n  FTS5 keyword index: {result['fts_count']} papers")
        if has_vector_support():
            click.echo(f"  Vector index:       {result['vector_count']} papers")
        else:
            click.echo("  Vector index:       skipped (pip install sentence-transformers)")
        click.echo()

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _report_result(result: IngestResult, json_output: bool) -> None:
    """Print ingestion result to stdout."""
    if json_output:
        click.echo(json.dumps({
            "status": result.status,
            "paper_id": result.paper_id,
            "duplicate_of": result.duplicate_of,
            "error": result.error,
        }, ensure_ascii=False))
    else:
        if result.status == "new":
            click.echo(f"✓ Ingested: {result.paper_id}")
        elif result.status == "duplicate":
            click.echo(f"⚠ Duplicate of existing paper: {result.duplicate_of}")
        else:
            click.echo(f"✗ Error: {result.error}")


def _error(msg: str, json_output: bool) -> None:
    """Print error message."""
    if json_output:
        click.echo(json.dumps({"status": "error", "error": msg}, ensure_ascii=False))
    else:
        click.echo(f"✗ {msg}", err=True)


# ---------------------------------------------------------------------------
# Default taxonomy (used when creating config files)
# ---------------------------------------------------------------------------

def _default_taxonomy() -> dict:
    return {
        "labels": {
            "factor_research": "因子研究 — factor construction, testing, IC analysis, decay",
            "strategy_research": "策略研究 — investment strategies, signal generation",
            "asset_pricing": "资产定价 — factor models, CAPM, APT, SDF",
            "portfolio_construction": "组合构建 — optimization, constraints, risk budgeting",
            "risk_model": "风险模型 — covariance estimation, Barra-style",
            "market_microstructure": "市场微观结构 — order book, bid-ask spread, market impact",
            "trading_cost_execution": "交易成本/执行 — TCA, VWAP/TWAP, optimal execution",
            "technical_factor": "技术因子 — indicators, technical signals, momentum/reversal patterns",
            "value_factor": "价值因子 — valuation, profitability, quality, growth, fundamental value signals",
            "price_and_volume_factor": "价量因子 — price/volume behavior, turnover, liquidity, volatility, order-flow signals",
        }
    }


# ---------------------------------------------------------------------------
# arxiv command group
# ---------------------------------------------------------------------------

@main.group()
def arxiv():
    """Search and ingest papers from arXiv.org."""


@arxiv.command("search")
@click.argument("query")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--limit", default=20, type=int, help="Max results (default: 20)")
@click.option("--finance-only", is_flag=True, help="Constrain results to finance/economics categories")
@click.option("--topic-term", multiple=True, help="Expected topic term for relevance scoring")
@click.option("--market-term", multiple=True, help="Expected market term for relevance scoring")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def arxiv_search(query, root, limit, finance_only, topic_term, market_term, output_json):
    """Search arXiv for papers matching QUERY.

    Displays results with an indicator of whether each paper is already
    in the database (✓ = already ingested, ✗ = new).
    """
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        from paperdb.connectors.arxiv_connector import ArxivConnector
        from paperdb.db.models import SearchLog
        from paperdb.search.quality import assess_candidate, record_candidate
        import time
        connector = ArxivConnector()

        if not output_json:
            click.echo(f"Searching arXiv for: {query}\n")
        started = time.monotonic()
        try:
            results = connector.search(query, limit=limit, finance_only=finance_only)
        except Exception as exc:
            from paperdb.connectors.arxiv_connector import ArxivSourceError
            elapsed = int((time.monotonic() - started) * 1000)
            error_type = exc.error_type if isinstance(exc, ArxivSourceError) else "source_error"
            retryable = exc.retryable if isinstance(exc, ArxivSourceError) else False
            failed_log = SearchLog(
                query=query, source_name="arxiv", query_type="preview",
                latency_ms=elapsed, error=f"{error_type}: {exc}",
            )
            conn.execute(
                """INSERT INTO search_logs
                   (id,source_name,query,query_type,results_count,new_papers,
                    inspected_count,accepted_count,rejected_count,duplicate_count,
                    latency_ms,searched_at,error)
                   VALUES (:id,:source_name,:query,:query_type,:results_count,:new_papers,
                    :inspected_count,:accepted_count,:rejected_count,:duplicate_count,
                    :latency_ms,:searched_at,:error)""",
                failed_log.to_dict(),
            )
            conn.commit()
            payload = {"success": False, "query": query, "error_type": error_type,
                       "error": str(exc), "retryable": retryable, "elapsed_ms": elapsed}
            if output_json:
                click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
                raise click.exceptions.Exit(2)
            raise click.ClickException(
                f"arXiv {error_type}: {exc} (retryable: {'yes' if retryable else 'no'})"
            ) from exc
        assessments = [assess_candidate(m, topic_term, market_term) for m in results]
        search_log = SearchLog(
            query=query, source_name="arxiv", query_type="preview",
            results_count=len(results), inspected_count=len(results),
            accepted_count=sum(a.decision == "accepted" for a in assessments),
            rejected_count=sum(a.decision == "rejected" for a in assessments),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        conn.execute(
            """INSERT INTO search_logs
               (id, source_name, query, query_type, results_count, new_papers,
                inspected_count, accepted_count, rejected_count, duplicate_count,
                latency_ms, searched_at, error)
               VALUES (:id, :source_name, :query, :query_type, :results_count,
                :new_papers, :inspected_count, :accepted_count, :rejected_count,
                :duplicate_count, :latency_ms, :searched_at, :error)""",
            search_log.to_dict(),
        )
        for meta, assessment in zip(results, assessments):
            record_candidate(
                conn, search_log_id=search_log.id, metadata=meta,
                decision=assessment.decision,
                rejection_reason=",".join(assessment.reasons) if assessment.decision == "rejected" else None,
                relevance_score=assessment.score,
                evidence={"categories": meta.extra.get("categories", [])},
            )
        conn.commit()

        if not results:
            click.echo("No results found.")
            return

        if output_json:
            out = []
            for meta, assessment in zip(results, assessments):
                paper = {
                    "title": meta.title,
                    "authors": meta.authors_raw,
                    "arxiv_id": meta.source_id,
                    "published": meta.publication_date,
                    "abstract": meta.abstract[:300] if meta.abstract else None,
                    "pdf_url": meta.download_url,
                    "language": meta.language,
                    "relevance_score": assessment.score,
                    "suggested_decision": assessment.decision,
                    "decision_reasons": assessment.reasons,
                }
                # Check if already in DB
                from paperdb.utils.hashing import compute_metadata_hash
                mh = compute_metadata_hash(meta.title, meta.authors_raw, meta.publication_date)
                existing = conn.execute(
                    "SELECT id FROM papers WHERE metadata_hash = ?", (mh,)
                ).fetchone()
                paper["in_db"] = bool(existing)
                if existing:
                    paper["paper_id"] = existing["id"]
                out.append(paper)
            click.echo(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            for i, (meta, assessment) in enumerate(zip(results, assessments), 1):
                # Check if already ingested
                from paperdb.utils.hashing import compute_metadata_hash
                mh = compute_metadata_hash(meta.title, meta.authors_raw, meta.publication_date)
                existing = conn.execute(
                    "SELECT id FROM papers WHERE metadata_hash = ?", (mh,)
                ).fetchone()
                status = "✓" if existing else "✗"
                pid = f" [{existing['id'][:20]}]" if existing else ""

                click.echo(f"{i:>3}. {status} {meta.title[:80]}")
                if meta.authors_raw:
                    click.echo(f"     Authors: {meta.authors_raw[:70]}")
                click.echo(f"     Date: {meta.publication_date or '?'}  |  ID: {meta.source_id}  |  Lang: {meta.language}{pid}")
                click.echo(f"     Relevance: {assessment.score:.2f} ({assessment.decision})")
                if meta.abstract:
                    click.echo(f"     {meta.abstract[:150]}...")
                click.echo()
    finally:
        conn.close()


@arxiv.command("queries")
@click.argument("topic")
@click.option("--market", default="China OR Chinese OR A-share",
              help="Market terms to include")
@click.option("--json", "output_json", is_flag=True)
def arxiv_queries(topic, market, output_json):
    """Generate three complementary constrained queries for a topic."""
    from paperdb.search.quality import generate_query_variants
    variants = generate_query_variants(topic, market)
    if output_json:
        click.echo(json.dumps(variants, ensure_ascii=False, indent=2))
    else:
        for index, query_text in enumerate(variants, 1):
            click.echo(f"{index}. {query_text}")


@arxiv.command("ingest")
@click.argument("query")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--limit", default=10, type=int, help="Max papers to ingest (default: 10)")
@click.option("--dry-run", is_flag=True, help="Search only, do not ingest")
@click.option("--confirm", is_flag=True, help="Confirm ingestion of search-ranked results")
@click.option("--download/--no-download", default=False, help="Attempt to download PDFs during ingest (default: false)")
@click.option("--batch", "batch_id", default=None, help="Batch ID for grouping")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def arxiv_ingest(query, root, limit, dry_run, confirm, download, batch_id, output_json):
    """Search arXiv and ingest new papers into the database.

    Searches arXiv for QUERY, checks for duplicates, and stores metadata.
    Use --download to fetch PDFs immediately, or run download/download-missing later.
    """
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        from paperdb.connectors.arxiv_connector import ArxivConnector
        from paperdb.ingest import ingest_from_metadata

        connector = ArxivConnector()

        click.echo(f"Searching arXiv for: {query}")
        try:
            results = connector.search(query, limit=limit)
        except Exception as exc:
            raise click.ClickException(f"arXiv search failed: {exc}") from exc
        click.echo(f"Found {len(results)} results.\n")

        if dry_run or not confirm:
            for i, meta in enumerate(results, 1):
                click.echo(f"  {i}. [{meta.source_id}] {meta.title[:80]}")
            if not dry_run:
                click.echo("\nPreview only. Re-run with --confirm, or use 'arxiv ingest-id <id>'.")
            return

        ingested = 0
        duplicates = 0
        errors = 0
        outcomes = []

        for meta in results:
            matches, priority = _resolve_watchlist(config, meta)

            result = ingest_from_metadata(
                conn, file_store, meta,
                priority_score=priority,
                batch_id=batch_id,
                download=download,
                connector=connector,
            )
            if result.paper_id:
                from paperdb.config.institutions import persist_institution_matches
                persist_institution_matches(conn, result.paper_id, matches)

            if result.status == "new":
                ingested += 1
                click.echo(f"  ✓ {result.paper_id[:20]}  {meta.title[:60]}")
            elif result.status == "duplicate":
                duplicates += 1
                click.echo(f"  ⚠ dup        {meta.title[:60]}")
            else:
                errors += 1
                click.echo(f"  ✗ error      {meta.title[:60]}  ({result.error})")

            outcomes.append({
                "title": meta.title,
                "status": result.status,
                "paper_id": result.paper_id,
                "arxiv_id": meta.source_id,
            })

        conn.commit()

        if output_json:
            click.echo(json.dumps({
                "query": query,
                "total_found": len(results),
                "ingested": ingested,
                "duplicates": duplicates,
                "errors": errors,
                "results": outcomes,
            }, ensure_ascii=False, indent=2))
        else:
            mode = "with immediate PDF downloads" if download else "metadata-only; run download-missing later"
            click.echo(f"\nDone. {ingested} new, {duplicates} duplicates, {errors} errors ({mode}).")

    finally:
        conn.close()


@arxiv.command("ingest-id")
@click.argument("arxiv_id")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--download/--no-download", default=False,
              help="Download immediately (default: metadata-only)")
@click.option("--batch", "batch_id", default=None)
@click.option("--json", "output_json", is_flag=True)
def arxiv_ingest_id(arxiv_id, root, download, batch_id, output_json):
    """Ingest one exact arXiv ID, avoiding relevance-ranked title matching."""
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)
    try:
        from paperdb.connectors.arxiv_connector import ArxivConnector
        from paperdb.ingest import ingest_from_metadata
        connector = ArxivConnector()
        try:
            metadata = connector.get_by_id(arxiv_id)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        except Exception as exc:
            raise click.ClickException(f"arXiv ID lookup failed: {exc}") from exc
        if metadata is None:
            raise click.ClickException(f"No arXiv record found for {arxiv_id}")
        matches, priority = _resolve_watchlist(config, metadata)
        result = ingest_from_metadata(
            conn, file_store, metadata, batch_id=batch_id, priority_score=priority,
            download=download, connector=connector,
        )
        if result.paper_id:
            from paperdb.config.institutions import persist_institution_matches
            persist_institution_matches(conn, result.paper_id, matches)
        payload = {
            "arxiv_id": metadata.source_id, "title": metadata.title,
            "status": result.status, "paper_id": result.paper_id,
            "metadata_only": not download,
        }
        if output_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            click.echo(f"{result.status}: {result.paper_id} [{metadata.source_id}] {metadata.title}")
    finally:
        conn.close()


@arxiv.command("harvest")
@click.option("--root", default=None, help="Paper database root directory")
@click.option("--since", default="last_week", type=click.Choice(["last_week", "last_month"]),
              help="Time range (default: last_week)")
@click.option("--limit", default=20, type=int, help="Max papers per category (default: 20)")
@click.option("--dry-run", is_flag=True, help="List only, do not ingest")
@click.option("--download/--no-download", default=False, help="Download PDFs during harvest (default: false)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def arxiv_harvest(root, since, limit, dry_run, download, output_json):
    """Harvest recently published papers from configured arXiv categories.

    Scans categories like q-fin.ST, q-fin.PM, stat.ML for new papers
    and ingests them into the database.
    """
    r = _resolve_root(root)
    conn, config, file_store = _get_db(r)

    try:
        from paperdb.connectors.arxiv_connector import ArxivConnector
        from paperdb.ingest import ingest_from_metadata

        connector = ArxivConnector()
        click.echo(f"Harvesting arXiv ({since}) from categories: {', '.join(connector.categories[:5])}...")

        try:
            results = connector.harvest(since=since, limit=limit)
        except Exception as exc:
            raise click.ClickException(f"arXiv harvest failed: {exc}") from exc
        click.echo(f"Found {len(results)} recent papers.\n")

        if dry_run:
            for i, meta in enumerate(results, 1):
                cats = meta.extra.get("categories", [])
                click.echo(f"  {i}. [{', '.join(cats[:2])}] {meta.title[:80]}")
            return

        ingested = 0
        duplicates = 0
        for meta in results:
            matches, priority = _resolve_watchlist(config, meta)
            result = ingest_from_metadata(
                conn, file_store, meta,
                priority_score=priority,
                download=download,
                connector=connector,
            )
            if result.paper_id:
                from paperdb.config.institutions import persist_institution_matches
                persist_institution_matches(conn, result.paper_id, matches)

            if result.status == "new":
                ingested += 1
                click.echo(f"  ✓ {result.paper_id[:20]}  {meta.title[:60]}")
            elif result.status == "duplicate":
                duplicates += 1

        conn.commit()

        if output_json:
            click.echo(json.dumps({
                "since": since,
                "total_found": len(results),
                "ingested": ingested,
                "duplicates": duplicates,
            }, ensure_ascii=False, indent=2))
        else:
            mode = "with immediate PDF downloads" if download else "metadata-only; run download-missing later"
            click.echo(f"\nDone. {ingested} new, {duplicates} duplicates ({mode}).")

    finally:
        conn.close()

"""Explicit bridge from a local ingestion record to remote Supabase.

Existing local records are never copied automatically. The caller selects a
paper ID after local discovery, parsing, deduplication, and assessment finish.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paperdb.search.keyword import segment_text
from paperdb.storage.file_store import FileStore

from .client import SupabaseClient, SupabaseError


BOOLEAN_COLUMNS = {
    "paper_authors": {"is_corresponding"},
    "download_logs": {"retryable"},
    "paper_assessments": {
        "long_only", "transaction_costs_included", "leverage_used", "intraday",
        "a_share_rules_compliant", "out_of_sample",
    },
}
JSON_COLUMNS = {
    "search_candidates": {"evidence"},
    "paper_assessments": {"rejection_reasons", "quality_breakdown", "evidence_json"},
}


def _record(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _normalize(table: str, record: dict[str, Any]) -> dict[str, Any]:
    for column in BOOLEAN_COLUMNS.get(table, set()):
        if record.get(column) is not None:
            record[column] = bool(record[column])
    for column in JSON_COLUMNS.get(table, set()):
        value = record.get(column)
        if isinstance(value, str):
            try:
                record[column] = json.loads(value)
            except json.JSONDecodeError:
                record[column] = {} if column != "rejection_reasons" else []
    return record


def sync_paper(client: SupabaseClient, conn: Any, file_store: FileStore, paper_id: str) -> dict:
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if not row:
        raise SupabaseError(f"Paper {paper_id!r} does not exist locally")

    paper = _record(row)
    paper["added_by"] = None
    paper["reviewed_by"] = None
    paper["search_text"] = segment_text(" ".join(filter(None, (
        paper.get("title"), paper.get("abstract"), paper.get("ai_summary")
    ))))

    local_relative_path = paper.get("file_path")
    if local_relative_path:
        local_path = file_store.get_path(local_relative_path)
        if local_path.is_file():
            extension = paper.get("file_format") or local_path.suffix.lstrip(".") or "pdf"
            object_path = f"papers/{paper_id}/{paper_id}.{extension}"
            client.upload_file(local_path, object_path)
            paper["file_path"] = object_path

    client.upsert("papers", paper, on_conflict="id")
    synced = {"paper_id": paper_id, "tables": {"papers": 1}, "file_path": paper.get("file_path")}
    for table in ("paper_labels", "paper_authors", "paper_institutions", "download_logs"):
        records = [_normalize(table, _record(item)) for item in conn.execute(
            f"SELECT * FROM {table} WHERE paper_id = ?", (paper_id,)
        ).fetchall()]
        for record in records:
            if "added_by" in record:
                record["added_by"] = None
        client.delete(table, paper_id=paper_id)
        if records:
            client.upsert(table, records, on_conflict="id")
        synced["tables"][table] = len(records)

    assessment = conn.execute(
        "SELECT * FROM paper_assessments WHERE paper_id = ?", (paper_id,)
    ).fetchone()
    if assessment:
        client.upsert(
            "paper_assessments",
            _normalize("paper_assessments", _record(assessment)),
            on_conflict="paper_id",
        )
        synced["tables"]["paper_assessments"] = 1
    return synced

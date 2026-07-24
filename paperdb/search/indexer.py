"""Index builder — rebuild FTS5 and vector indexes from the papers table."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from paperdb.search.keyword import KeywordSearcher
from paperdb.search.vector import VectorSearcher, has_vector_support


def build_index(
    conn: sqlite3.Connection,
    index_dir: str | Path,
    *,
    rebuild_fts: bool = True,
    rebuild_vector: bool = True,
    verbose: bool = False,
) -> dict:
    """Rebuild search indexes from the papers table.

    Args:
        conn: Open SQLite connection.
        index_dir: Directory for vector index storage.
        rebuild_fts: Rebuild the FTS5 index (default True).
        rebuild_vector: Rebuild the vector index (default True).
        verbose: Print progress messages.

    Returns:
        Dict with counts: ``{"fts_count": int, "vector_count": int}``.
    """
    result = {"fts_count": 0, "vector_count": 0}

    # FTS5 rebuild
    if rebuild_fts:
        if verbose:
            print("Building FTS5 keyword index...", end=" ", flush=True)
        kw = KeywordSearcher(conn)
        result["fts_count"] = kw.rebuild()
        if verbose:
            print(f"done ({result['fts_count']} papers)")

    # Vector rebuild
    if rebuild_vector:
        if verbose:
            print("Building vector index...", end=" ", flush=True)
        if has_vector_support():
            vec = VectorSearcher(conn, index_dir)
            result["vector_count"] = vec.rebuild()
            if verbose:
                print(f"done ({result['vector_count']} papers)")
        else:
            if verbose:
                print("skipped (sentence-transformers not installed)")

    return result


def index_paper(
    conn: sqlite3.Connection,
    index_dir: str | Path,
    paper_id: str,
    title: str,
    abstract: Optional[str] = None,
) -> None:
    """Add or update a single paper in both indexes.

    Call this after ingesting a new paper to keep indexes current.
    """
    kw = KeywordSearcher(conn)
    kw.index_paper(paper_id, title, abstract)

    if has_vector_support():
        vec = VectorSearcher(conn, index_dir)
        vec.index_paper(paper_id, title, abstract)

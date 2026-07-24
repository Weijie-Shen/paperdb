"""Hybrid search combining keyword (FTS5) and vector (BGE) results.

Uses Reciprocal Rank Fusion (RRF) to merge ranked lists from both
search strategies into a single relevance-ordered result set.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from paperdb.search.keyword import KeywordSearcher, segment_text
from paperdb.search.vector import VectorSearcher, has_vector_support


def reciprocal_rank_fusion(
    keyword_results: list[tuple[str, float]],
    vector_results: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Merge two ranked lists using Reciprocal Rank Fusion.

    Args:
        keyword_results: List of ``(paper_id, score)`` from keyword search.
        vector_results: List of ``(paper_id, score)`` from vector search.
        k: RRF constant (default 60, per Cormack et al.).

    Returns:
        Merged list of ``(paper_id, fused_score)``, sorted descending.
    """
    scores: dict[str, float] = {}

    for rank, (pid, _) in enumerate(keyword_results):
        scores[pid] = scores.get(pid, 0) + 1.0 / (k + rank + 1)

    for rank, (pid, _) in enumerate(vector_results):
        scores[pid] = scores.get(pid, 0) + 1.0 / (k + rank + 1)

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return ranked


class HybridSearcher:
    """Combined keyword + vector search with RRF fusion.

    Falls back gracefully to keyword-only search when vector support
    is unavailable.

    Usage::

        searcher = HybridSearcher(conn, index_dir)
        results = searcher.search("因子选股 A股", limit=20)
        # → list of Paper rows with relevance scores
    """

    def __init__(self, conn: sqlite3.Connection, index_dir: str | Path):
        self.conn = conn
        self.index_dir = Path(index_dir)
        self.keyword = KeywordSearcher(conn)
        self.vector = VectorSearcher(conn, index_dir)
        self._vector_available = has_vector_support()

    @property
    def vector_available(self) -> bool:
        return self._vector_available

    def search(
        self,
        query: str,
        limit: int = 20,
        filters: Optional[dict] = None,
        mode: str = "hybrid",
    ) -> list[tuple[str, float]]:
        """Search papers using keyword, vector, or hybrid mode.

        Args:
            query: Search query.
            limit: Maximum results.
            filters: Optional column→value filters.
            mode: ``"keyword"``, ``"vector"``, or ``"hybrid"`` (default).

        Returns:
            List of ``(paper_id, fused_score)`` tuples.
        """
        if mode == "keyword" or not self._vector_available:
            return self._strategy_rerank(
                self._keyword_search(query, limit * 2, filters)
            )[:limit]

        if mode == "vector":
            return self._strategy_rerank(
                self._vector_search(query, limit * 2, filters)
            )[:limit]

        # Hybrid: RRF fusion
        kw_results = self._keyword_search(query, limit * 2, filters)
        vec_results = self._vector_search(query, limit * 2, filters)

        fused = reciprocal_rank_fusion(kw_results, vec_results)
        return self._strategy_rerank(fused)[:limit]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _keyword_search(self, query, limit, filters):
        """Run keyword search, falling back to LIKE if FTS5 unavailable."""
        results = self.keyword.search(query, limit=limit, filters=filters)
        if results:
            return results

        # FTS5 fallback: match useful concepts independently. Requiring the
        # entire natural-language query as one substring causes compound
        # Chinese/English queries to return false empty results.
        tokens = []
        for token in segment_text(query).split():
            normalized = token.strip().casefold()
            if len(normalized) > 1 and normalized not in tokens:
                tokens.append(normalized)
        if not tokens:
            return []
        term_conditions = []
        params = []
        for token in tokens:
            term_conditions.append("(title LIKE ? OR abstract LIKE ? OR ai_summary LIKE ?)")
            params.extend([f"%{token}%"] * 3)
        where = ["lifecycle_status = 'active'", f"({' OR '.join(term_conditions)})"]

        if filters:
            for col, val in filters.items():
                if col == "institution":
                    where.append("""(institution LIKE ? OR id IN (
                        SELECT paper_id FROM paper_institutions
                        WHERE canonical_name LIKE ? OR raw_value LIKE ? OR matched_alias LIKE ?
                    ))""")
                    params.extend([f"%{val}%"] * 4)
                elif col in ("market", "source_type", "access_status", "language", "frequency"):
                    where.append(f"{col} = ?")
                    params.append(val)
                elif col == "date_from":
                    where.append("publication_date >= ?")
                    params.append(val)
                elif col == "date_to":
                    where.append("publication_date <= ?")
                    params.append(val)
                elif col in ("research_type", "decision"):
                    where.append(
                        f"id IN (SELECT paper_id FROM paper_assessments WHERE {col} = ?)"
                    )
                    params.append(val)

        where_clause = " AND ".join(where)
        rows = self.conn.execute(
            f"SELECT id, title, abstract, ai_summary FROM papers WHERE {where_clause}",
            params,
        ).fetchall()
        ranked = []
        for row in rows:
            text = " ".join((row["title"] or "", row["abstract"] or "", row["ai_summary"] or "")).casefold()
            hits = sum(token in text for token in tokens)
            ranked.append((row["id"], hits / len(tokens)))
        return sorted(ranked, key=lambda item: (-item[1], item[0]))[:limit]

    def _vector_search(self, query, limit, filters):
        """Run vector search, returning empty if unavailable."""
        if not self._vector_available:
            return []
        return self.vector.search(query, limit=limit, filters=filters)

    def _strategy_rerank(self, results):
        """Prefer verified strategies, then factor reports, without hiding candidates."""
        if not results:
            return []
        ids = [paper_id for paper_id, _ in results]
        placeholders = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"""SELECT paper_id, research_type, decision, quality_score
                FROM paper_assessments WHERE paper_id IN ({placeholders})""",
            ids,
        ).fetchall()
        assessments = {row["paper_id"]: row for row in rows}
        reranked = []
        for paper_id, score in results:
            row = assessments.get(paper_id)
            boost = 0.0
            if row:
                if row["decision"] == "qualified" and row["research_type"] == "strategy":
                    boost = 0.20 + (row["quality_score"] or 0) / 1000
                elif row["decision"] == "qualified":
                    boost = 0.08
                elif row["decision"] == "unverified":
                    boost = 0.02
            reranked.append((paper_id, score + boost))
        return sorted(reranked, key=lambda item: (-item[1], item[0]))

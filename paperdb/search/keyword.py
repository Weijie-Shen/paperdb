"""Keyword search using SQLite FTS5 with jieba Chinese tokenization.

Strategy: pre-segment Chinese text with jieba (producing space-separated
tokens), then use FTS5's default tokenizer. This avoids needing a custom
C tokenizer while still getting proper CJK word segmentation.
"""

from __future__ import annotations

import sqlite3
from typing import Optional


# ---------------------------------------------------------------------------
# FTS5 table DDL (added to schema)
# ---------------------------------------------------------------------------

FTS5_CREATE = """
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    paper_id UNINDEXED,
    title_seg,
    abstract_seg
);
"""

FTS5_TRIGGERS = """
-- Keep FTS5 in sync with papers table
CREATE TRIGGER IF NOT EXISTS papers_ai_fts AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(paper_id, title_seg, abstract_seg)
    VALUES (new.id, '', '');
END;

CREATE TRIGGER IF NOT EXISTS papers_ad_fts AFTER DELETE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, paper_id, title_seg, abstract_seg)
    VALUES('delete', old.id, '', '');
END;
"""


# ---------------------------------------------------------------------------
# jieba segmentation
# ---------------------------------------------------------------------------

def segment_text(text: str) -> str:
    """Segment Chinese text with jieba, preserving English words.

    >>> segment_text("A股多因子选股模型研究")
    'A股 多因子 选股 模型 研究'

    >>> segment_text("Portfolio optimization with factor timing")
    'Portfolio optimization with factor timing'
    """
    try:
        import jieba
    except ImportError:
        return text  # No jieba — return as-is

    # Detect if text contains Chinese characters
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in text)
    if not has_cjk:
        return text

    # Use jieba for Chinese text
    tokens = jieba.cut(text.strip())
    return " ".join(t for t in tokens if t.strip())


# ---------------------------------------------------------------------------
# KeywordSearcher
# ---------------------------------------------------------------------------

class KeywordSearcher:
    """FTS5-based keyword search with jieba Chinese segmentation.

    Usage::

        searcher = KeywordSearcher(conn)
        results = searcher.search("因子 选股", limit=20)
        # → list of (paper_id, rank) tuples
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def search(
        self,
        query: str,
        limit: int = 20,
        filters: Optional[dict] = None,
    ) -> list[tuple[str, float]]:
        """Search papers by keyword with optional filters.

        Args:
            query: Search query (Chinese or English).
            limit: Maximum results.
            filters: Optional dict of column→value filters (e.g. {"market": "a_share"}).

        Returns:
            List of ``(paper_id, score)`` tuples ordered by relevance.
        """
        segmented = segment_text(query)

        # Build FTS5 query — wrap each token for prefix matching
        tokens = segmented.split()
        if not tokens:
            return []

        fts_query = " OR ".join(
            f'("{t}" OR {t}*)' for t in tokens if len(t) > 1
        )
        if not fts_query:
            fts_query = segmented

        # Build filter clause
        filter_clause = " AND p.lifecycle_status = 'active'"
        filter_params: list = []
        if filters:
            conditions = []
            for col, val in filters.items():
                if col in ("market", "source_type", "access_status", "language", "frequency"):
                    conditions.append(f"p.{col} = ?")
                    filter_params.append(val)
                elif col == "institution":
                    conditions.append("""(p.institution LIKE ? OR p.id IN (
                        SELECT paper_id FROM paper_institutions
                        WHERE canonical_name LIKE ? OR raw_value LIKE ? OR matched_alias LIKE ?
                    ))""")
                    filter_params.extend([f"%{val}%"] * 4)
                elif col == "date_from":
                    conditions.append("p.publication_date >= ?")
                    filter_params.append(val)
                elif col == "date_to":
                    conditions.append("p.publication_date <= ?")
                    filter_params.append(val)
            if conditions:
                filter_clause += " AND " + " AND ".join(conditions)

        try:
            rows = self.conn.execute(
                f"""SELECT f.paper_id, f.rank
                    FROM papers_fts f
                    JOIN papers p ON p.id = f.paper_id
                    WHERE papers_fts MATCH ?{filter_clause}
                    ORDER BY rank
                    LIMIT ?""",
                [fts_query] + filter_params + [limit],
            ).fetchall()

            # Normalize scores: inverse rank (lower rank = better in FTS5)
            if not rows:
                return []

            max_rank = max(abs(r["rank"]) for r in rows) if rows else 1
            results = []
            for i, row in enumerate(rows):
                # FTS5 rank is negative (more negative = better)
                # Convert to positive score in [0, 1]
                score = 1.0 - (abs(row["rank"]) / (max_rank + 1))
                results.append((row["paper_id"], score))

            return results

        except sqlite3.OperationalError:
            # FTS5 table may not exist or be empty
            return []

    def index_paper(self, paper_id: str, title: str, abstract: Optional[str] = None) -> None:
        """Add or update a single paper in the FTS5 index."""
        title_seg = segment_text(title)
        abstract_seg = segment_text(abstract) if abstract else ""

        # Delete existing entry if present
        self.conn.execute(
            "DELETE FROM papers_fts WHERE paper_id = ?", (paper_id,)
        )

        # Insert segmented content
        self.conn.execute(
            "INSERT INTO papers_fts(paper_id, title_seg, abstract_seg) VALUES (?, ?, ?)",
            (paper_id, title_seg, abstract_seg),
        )

    def rebuild(self) -> int:
        """Rebuild the entire FTS5 index from the papers table.

        Drops and recreates the FTS5 table, then inserts all papers.

        Returns:
            Number of papers indexed.
        """
        # Drop and recreate
        self.conn.execute("DROP TABLE IF EXISTS papers_fts")
        self.conn.execute(FTS5_CREATE)

        # Index all papers
        rows = self.conn.execute(
            "SELECT id, title, abstract FROM papers"
        ).fetchall()

        count = 0
        for row in rows:
            title_seg = segment_text(row["title"])
            abstract_seg = segment_text(row["abstract"]) if row["abstract"] else ""
            self.conn.execute(
                "INSERT INTO papers_fts(paper_id, title_seg, abstract_seg) VALUES (?, ?, ?)",
                (row["id"], title_seg, abstract_seg),
            )
            count += 1

        self.conn.commit()
        return count

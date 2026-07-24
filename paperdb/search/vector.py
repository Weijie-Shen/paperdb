"""Vector / semantic search using BGE embeddings (optional).

Requires ``sentence-transformers`` to be installed. Falls back gracefully
if the dependency is missing — vector search simply returns empty results.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional


def has_vector_support() -> bool:
    """Check if sentence-transformers is available."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


class VectorSearcher:
    """Semantic search using BGE embeddings.

    Embeddings are stored in a simple JSON file alongside the SQLite DB.
    This avoids the complexity of ChromaDB/FAISS while being sufficient
    for ~5,000 papers.

    Usage::

        searcher = VectorSearcher(conn, index_dir)
        results = searcher.search("因子选股", limit=20)
        # → list of (paper_id, score) tuples
    """

    def __init__(self, conn: sqlite3.Connection, index_dir: str | Path):
        self.conn = conn
        self.index_dir = Path(index_dir)
        self._model = None

    # ------------------------------------------------------------------
    # Model loading (lazy)
    # ------------------------------------------------------------------

    @property
    def model(self):
        """Lazy-load the BGE model."""
        if self._model is None:
            if not has_vector_support():
                return None
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer("BAAI/bge-large-zh-v1.5")
            except Exception:
                return None
        return self._model

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 20,
        filters: Optional[dict] = None,
    ) -> list[tuple[str, float]]:
        """Semantic search over indexed papers.

        Args:
            query: Natural language query.
            limit: Maximum results.
            filters: Optional column→value filters.

        Returns:
            List of ``(paper_id, score)`` tuples, sorted by similarity.
            Empty list if vector support is unavailable.
        """
        if self.model is None:
            return []

        # Load embeddings
        embeddings = self._load_embeddings()
        if not embeddings:
            return []

        # Encode query
        import numpy as np
        query_vec = self.model.encode([query], normalize_embeddings=True)[0]

        # Compute cosine similarity (vectors are normalized, so dot product)
        paper_ids = list(embeddings.keys())
        vectors = np.array([embeddings[pid] for pid in paper_ids])
        scores = np.dot(vectors, query_vec)

        # Sort by score descending
        ranked = sorted(
            zip(paper_ids, scores),
            key=lambda x: -x[1],
        )

        # Apply filters if needed
        ranked = self._apply_filters(ranked, filters or {})

        return [(pid, float(score)) for pid, score in ranked[:limit]]

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def rebuild(self) -> int:
        """Build embeddings for all papers in the database.

        Returns:
            Number of papers indexed, or 0 if vector support is unavailable.
        """
        if self.model is None:
            return 0

        import numpy as np

        rows = self.conn.execute(
            "SELECT id, title, abstract FROM papers"
        ).fetchall()

        if not rows:
            self._save_embeddings({})
            return 0

        # Build text for embedding (title + abstract)
        texts = []
        paper_ids = []
        for row in rows:
            text = row["title"]
            if row["abstract"]:
                text += " " + row["abstract"]
            texts.append(text)
            paper_ids.append(row["id"])

        # Encode in batches
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )

        # Store as dict
        emb_dict = {
            pid: emb.tolist()
            for pid, emb in zip(paper_ids, embeddings)
        }

        self._save_embeddings(emb_dict)
        return len(emb_dict)

    def index_paper(self, paper_id: str, title: str, abstract: Optional[str] = None) -> None:
        """Add or update a single paper's embedding."""
        if self.model is None:
            return

        text = title
        if abstract:
            text += " " + abstract

        embedding = self.model.encode(
            [text], normalize_embeddings=True
        )[0].tolist()

        emb_dict = self._load_embeddings()
        emb_dict[paper_id] = embedding
        self._save_embeddings(emb_dict)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _embeddings_path(self) -> Path:
        return self.index_dir / "embeddings.json"

    def _load_embeddings(self) -> dict:
        path = self._embeddings_path()
        if not path.exists():
            return {}
        with open(path, "r") as f:
            return json.load(f)

    def _save_embeddings(self, emb_dict: dict) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        with open(self._embeddings_path(), "w") as f:
            json.dump(emb_dict, f)

    def _apply_filters(
        self,
        ranked: list[tuple[str, float]],
        filters: dict,
    ) -> list[tuple[str, float]]:
        """Filter ranked results by column constraints."""
        # Build set of eligible paper IDs
        conditions = ["lifecycle_status = 'active'"]
        params = []
        for col, val in filters.items():
            if col in ("market", "source_type", "access_status", "language", "frequency"):
                conditions.append(f"{col} = ?")
                params.append(val)
            elif col == "institution":
                conditions.append("""(institution LIKE ? OR id IN (
                    SELECT paper_id FROM paper_institutions
                    WHERE canonical_name LIKE ? OR raw_value LIKE ? OR matched_alias LIKE ?
                ))""")
                params.extend([f"%{val}%"] * 4)
            elif col == "date_from":
                conditions.append("publication_date >= ?")
                params.append(val)
            elif col == "date_to":
                conditions.append("publication_date <= ?")
                params.append(val)

        if conditions:
            where = " AND ".join(conditions)
            rows = self.conn.execute(
                f"SELECT id FROM papers WHERE {where}", params
            ).fetchall()
            eligible = {r["id"] for r in rows}
            return [(pid, s) for pid, s in ranked if pid in eligible]

        return ranked

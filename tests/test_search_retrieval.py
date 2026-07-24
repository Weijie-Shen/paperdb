"""Regression tests for compound queries and lifecycle-safe retrieval."""

from paperdb.db.models import Paper
from paperdb.db.schema import init_db
from paperdb.search.hybrid import HybridSearcher
from paperdb.search.keyword import KeywordSearcher


def _insert(conn, paper):
    conn.execute(
        """INSERT INTO papers
           (id, title, abstract, source_type, access_status, quality_flag,
            lifecycle_status, created_at, updated_at)
           VALUES (:id, :title, :abstract, :source_type, :access_status,
                   :quality_flag, :lifecycle_status, :created_at, :updated_at)""",
        paper.to_dict(),
    )


def test_compound_query_fallback_matches_individual_concepts(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    relevant = Paper(
        title="A股量价技术因子研究",
        abstract="使用动量与反转指标开展回测。",
        source_type="academic_paper",
    )
    _insert(conn, relevant)
    conn.commit()
    # Leave FTS empty to exercise the LIKE fallback directly.
    results = HybridSearcher(conn, tmp_path / "index")._keyword_search(
        "A股 量价 技术指标 动量 反转 回测", 10, None
    )
    assert results[0][0] == relevant.id
    assert results[0][1] >= 0.5


def test_keyword_search_excludes_rejected_records(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    active = Paper(title="Equity factor model", source_type="academic_paper")
    rejected = Paper(
        title="Galaxy factor model", source_type="academic_paper",
        lifecycle_status="rejected_out_of_scope",
    )
    _insert(conn, active)
    _insert(conn, rejected)
    searcher = KeywordSearcher(conn)
    searcher.rebuild()
    ids = [paper_id for paper_id, _ in searcher.search("factor")]
    assert active.id in ids
    assert rejected.id not in ids

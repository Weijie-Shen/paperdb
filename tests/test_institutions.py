"""Tests for canonical institution identity and priority resolution."""

from paperdb.config.institutions import (
    match_institutions, normalize_institution, persist_institution_matches,
    refresh_institution_matches,
)
from paperdb.config.loader import Config
from paperdb.connectors.base import PaperMetadata
from paperdb.db.models import Paper
from paperdb.db.schema import init_db


ENTRIES = [
    {"name": "中金公司", "priority": 1,
     "aliases": ["中国国际金融股份有限公司", "China International Capital Corporation", "CICC"]},
    {"name": "中信证券", "priority": 2,
     "aliases": ["中信证券股份有限公司", "CITIC Securities"]},
    {"name": "示例研究所", "priority": 3, "aliases": ["Example Institute"]},
]


def test_normalization_handles_width_case_and_punctuation():
    assert normalize_institution("  CICC（北京） ") == "cicc 北京"
    assert normalize_institution("CITIC-Securities") == "citic securities"


def test_alias_and_department_qualified_affiliation_match():
    matches = match_institutions(
        ENTRIES,
        [("Quantitative Research, China International Capital Corporation", "author_affiliation")],
    )
    assert matches[0].canonical_name == "中金公司"
    assert matches[0].matched_alias == "China International Capital Corporation"
    assert matches[0].priority_rank == 1
    assert matches[0].priority_score == 3
    assert matches[0].source == "author_affiliation"


def test_short_english_alias_uses_token_boundaries():
    assert match_institutions(ENTRIES, [("CICC Research", "paper_institution")])
    assert not match_institutions(ENTRIES, [("piccdata laboratory", "paper_institution")])


def test_metadata_resolution_uses_affiliations_not_author_names(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = Config(tmp_path)
    metadata = PaperMetadata(
        title="Test", source_type="academic_paper", source_name="arxiv",
        authors_raw="CICC; Some Author",
        extra={"author_affiliations": [
            {"name": "CICC", "affiliations": ["Unrelated University"]}
        ]},
    )
    assert config.resolve_metadata_institutions(metadata) == []


def test_query_filter_alias_is_canonicalized(tmp_path):
    assert Config(tmp_path).canonicalize_institution_filter("CICC") == "中金公司"
    assert Config(tmp_path).canonicalize_institution_filter("Unknown University") == "Unknown University"


def test_persisted_match_updates_score_and_audit_table(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    paper = Paper(title="Test", source_type="academic_paper")
    conn.execute(
        """INSERT INTO papers
           (id,title,source_type,access_status,quality_flag,priority_score,created_at,updated_at)
           VALUES (:id,:title,:source_type,:access_status,:quality_flag,:priority_score,:created_at,:updated_at)""",
        paper.to_dict(),
    )
    matches = match_institutions(ENTRIES, [("CICC", "author_affiliation")])
    persist_institution_matches(conn, paper.id, matches)
    row = conn.execute("SELECT * FROM paper_institutions WHERE paper_id = ?", (paper.id,)).fetchone()
    stored = conn.execute("SELECT priority_score FROM papers WHERE id = ?", (paper.id,)).fetchone()
    assert row["canonical_name"] == "中金公司"
    assert row["raw_value"] == "CICC"
    assert row["confidence"] == 0.99
    assert stored["priority_score"] == 3


def test_refresh_recomputes_reversed_existing_priority(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    high = Paper(title="High", source_type="broker_report",
                 institution="中国国际金融股份有限公司", priority_score=1)
    low = Paper(title="Low", source_type="broker_report",
                institution="Example Institute", priority_score=3)
    for paper in (high, low):
        conn.execute(
            """INSERT INTO papers
               (id,title,institution,source_type,access_status,quality_flag,
                priority_score,created_at,updated_at)
               VALUES (:id,:title,:institution,:source_type,:access_status,:quality_flag,
                :priority_score,:created_at,:updated_at)""",
            paper.to_dict(),
        )
    result = refresh_institution_matches(conn, ENTRIES)
    scores = {row["title"]: row["priority_score"] for row in conn.execute(
        "SELECT title, priority_score FROM papers"
    )}
    assert result["papers_matched"] == 2
    assert scores["High"] > scores["Low"]

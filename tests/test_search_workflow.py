"""Regression tests for the safe search/classification workflow."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from paperdb.cli import main
from paperdb.connectors.arxiv_connector import ArxivConnector, ArxivSourceError
from paperdb.connectors.base import DownloadResult, PaperMetadata
from paperdb.db.schema import init_db
from paperdb.ingest import download_paper_file, ingest_from_metadata
from paperdb.search.quality import (
    assess_candidate, extract_performance_claims, generate_query_variants,
    record_candidate, validate_metadata,
)
from paperdb.storage.file_store import FileStore


def metadata(title="Chinese A-share Factor Pricing"):
    return PaperMetadata(
        title=title, source_type="academic_paper", source_name="arxiv",
        source_id="2501.12345", source_url="https://arxiv.org/abs/2501.12345",
        download_url="https://arxiv.org/pdf/2501.12345", authors_raw="A. Author",
        abstract="We study stock factor returns and asset pricing in China.",
        extra={"categories": ["q-fin.ST"]},
    )


def test_finance_assessment_accepts_finance_and_rejects_noise():
    assert assess_candidate(metadata(), ["factor"], ["china"]).decision == "accepted"
    noise = metadata("Host Galaxy and Black Hole Alpha Factors")
    noise.abstract = "An astrophysics study of a galaxy and black hole."
    assert assess_candidate(noise).decision == "rejected"


def test_discovery_rejects_intraday_and_non_a_share_candidates():
    intraday = metadata("Intraday A-share factor trading strategy")
    intraday.abstract = "A high-frequency intraday backtest on Chinese A-shares."
    assert assess_candidate(intraday).decision == "rejected"

    us = metadata("S&P 500 momentum strategy")
    us.abstract = "A daily backtest for US equities and the S&P 500."
    assert assess_candidate(us).decision == "rejected"


def test_abstract_performance_claims_are_only_extracted_as_evidence():
    claims = extract_performance_claims(
        "The annualized return is 35.2% and maximum drawdown is -8.4%."
    )
    assert claims == {"annualized_return": 35.2, "max_drawdown": 8.4}


def test_query_variants_are_complementary_and_market_constrained():
    variants = generate_query_variants("momentum reversal")
    assert len(variants) == 3
    assert len(set(variants)) == 3
    assert all("China" in query for query in variants)
    assert any("cat:q-fin" in query for query in variants)
    assert all('all:"momentum reversal"' not in query for query in variants)
    assert any("momentum OR reversal" in query for query in variants)


def test_metadata_validation_and_github_provenance(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    store = FileStore(tmp_path / "files")
    store.init()
    item = metadata()
    item.github_url = "https://github.com/example/repo"
    item.extra.update({
        "github_evidence_type": "arxiv_abstract",
        "github_evidence_url": item.source_url,
    })
    quality, warnings = validate_metadata(item)
    assert quality == "verified"
    assert warnings == []
    result = ingest_from_metadata(conn, store, item, download=False)
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (result.paper_id,)).fetchone()
    assert row["github_evidence_type"] == "arxiv_abstract"
    assert row["github_evidence_url"] == item.source_url
    assert row["metadata_quality"] == "verified"


def test_candidate_log_and_lifecycle_columns(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    candidate_id = record_candidate(
        conn, search_log_id=None, metadata=metadata(), decision="rejected",
        rejection_reason="wrong_market", relevance_score=0.2,
    )
    row = conn.execute("SELECT * FROM search_candidates WHERE id = ?", (candidate_id,)).fetchone()
    assert row["decision"] == "rejected"
    paper_cols = {r["name"] for r in conn.execute("PRAGMA table_info(papers)")}
    assert {"lifecycle_status", "metadata_quality", "github_evidence_type",
            "quality_screening_status"} <= paper_cols


def test_exact_id_lookup_uses_id_list_and_verifies_id():
    connector = ArxivConnector()
    result = MagicMock()
    result.entry_id = "http://arxiv.org/abs/2501.12345v2"
    result.pdf_url = "https://arxiv.org/pdf/2501.12345v2"
    result.title = "Test"
    result.authors = []
    result.published.strftime.return_value = "2025-01-01"
    result.summary = "Finance portfolio study"
    result.categories = ["q-fin.PM"]
    result.comment = None
    client = MagicMock()
    client.results.return_value = iter([result])
    fake_arxiv = MagicMock()
    fake_arxiv.Client.return_value = client
    with patch.dict("sys.modules", {"arxiv": fake_arxiv}):
        meta = connector.get_by_id("2501.12345")
    assert meta.source_id == "2501.12345"
    search_arg = client.results.call_args.args[0]
    assert search_arg is fake_arxiv.Search.return_value


def test_failed_download_is_always_logged(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    store = FileStore(tmp_path / "files")
    store.init()
    item = metadata()
    result = ingest_from_metadata(conn, store, item, download=False)
    connector = MagicMock()
    connector.download.return_value = DownloadResult(
        success=False, error="timed out", error_type="timeout", retryable=True,
    )
    outcome = download_paper_file(conn, store, result.paper_id, connector=connector)
    assert not outcome.success
    log = conn.execute("SELECT * FROM download_logs WHERE paper_id = ?", (result.paper_id,)).fetchone()
    assert log["status"] == "timeout"
    assert log["finished_at"] is not None
    assert log["retryable"] == 1


def test_arxiv_ingest_requires_confirmation(tmp_path):
    root = tmp_path / "paper_database"
    runner = CliRunner()
    assert runner.invoke(main, ["init", "--root", str(root)]).exit_code == 0
    with patch("paperdb.connectors.arxiv_connector.ArxivConnector.search", return_value=[metadata()]):
        output = runner.invoke(main, ["arxiv", "ingest", "factor", "--root", str(root)])
    assert output.exit_code == 0
    assert "Preview only" in output.output
    conn = init_db(root / "db" / "papers.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0


def test_arxiv_search_cli_surfaces_and_logs_source_failure(tmp_path):
    root = tmp_path / "paper_database"
    runner = CliRunner()
    assert runner.invoke(main, ["init", "--root", str(root)]).exit_code == 0
    failure = ArxivSourceError("source timed out", error_type="timeout", retryable=True)
    with patch("paperdb.connectors.arxiv_connector.ArxivConnector.search", side_effect=failure):
        output = runner.invoke(main, [
            "arxiv", "search", "factor", "--root", str(root), "--json"
        ])
    assert output.exit_code == 2
    assert '"success": false' in output.output
    assert '"error_type": "timeout"' in output.output
    conn = init_db(root / "db" / "papers.sqlite")
    log = conn.execute("SELECT * FROM search_logs ORDER BY searched_at DESC LIMIT 1").fetchone()
    assert log["error"] == "timeout: source timed out"

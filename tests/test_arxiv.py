"""Unit tests for the arXiv connector and connector→DB bridge."""

import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from paperdb.connectors.arxiv_connector import ArxivConnector, ArxivSourceError
from paperdb.connectors.base import PaperMetadata, DownloadResult
from paperdb.ingest import ingest_from_metadata
from paperdb.db.schema import init_db
from paperdb.storage.file_store import FileStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def connector():
    return ArxivConnector()


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def db(tmpdir):
    conn = init_db(tmpdir / "test.sqlite")
    yield conn
    conn.close()


@pytest.fixture
def file_store(tmpdir):
    fs = FileStore(tmpdir / "files")
    fs.init()
    return fs


@pytest.fixture
def sample_metadata():
    return PaperMetadata(
        title="Optimal Portfolio with Factor Timing",
        source_type="academic_paper",
        source_name="arxiv",
        source_id="2501.12345",
        source_url="https://arxiv.org/abs/2501.12345",
        github_url="https://github.com/example/factor-timing",
        download_url="https://arxiv.org/pdf/2501.12345.pdf",
        authors_raw="Zhang Wei; Li Ming",
        publication_date="2025-01-15",
        abstract="We study portfolio optimization with factor timing...",
        language="en",
        file_format="pdf",
    )


# ---------------------------------------------------------------------------
# Connector tests
# ---------------------------------------------------------------------------

class TestArxivConnector:
    """Test connector properties and metadata conversion."""

    def test_default_properties(self, connector):
        assert connector.name == "arxiv"
        assert connector.source_type == "academic_paper"
        assert connector.can_search is True
        assert connector.can_download is True
        assert connector.can_harvest is True
        assert connector.requires_auth is False

    def test_default_categories(self, connector):
        cats = connector.categories
        assert "q-fin.ST" in cats
        assert "q-fin.PM" in cats
        assert "stat.ML" in cats

    def test_custom_categories(self):
        conn = ArxivConnector(categories=["q-fin.ST", "cs.LG"])
        assert conn.categories == ["q-fin.ST", "cs.LG"]

    def test_search_timeout_is_not_reported_as_empty(self):
        client = MagicMock()
        client.results.side_effect = TimeoutError("source timed out")
        fake_arxiv = MagicMock()
        fake_arxiv.Client.return_value = client
        with patch.dict("sys.modules", {"arxiv": fake_arxiv}):
            with pytest.raises(ArxivSourceError) as error:
                ArxivConnector().search("factor")
        assert error.value.error_type == "timeout"
        assert error.value.retryable is True

    def test_to_metadata(self, connector):
        """Test conversion of a mock arXiv result to PaperMetadata."""
        mock_result = MagicMock()
        mock_result.title = "Test Factor Paper"
        mock_result.entry_id = "http://arxiv.org/abs/2501.12345v1"
        mock_result.pdf_url = "https://arxiv.org/pdf/2501.12345v1"
        mock_result.authors = [MagicMock(__str__=lambda s: "Zhang Wei")]
        mock_result.published = MagicMock()
        mock_result.published.strftime.return_value = "2025-01-15"
        mock_result.summary = "Test abstract."
        mock_result.categories = ["q-fin.ST", "stat.ML"]

        meta = connector._to_metadata(mock_result)

        assert meta.title == "Test Factor Paper"
        assert meta.source_id == "2501.12345"  # v stripped
        assert meta.source_type == "academic_paper"
        assert meta.source_name == "arxiv"
        assert meta.language == "en"  # No CJK in title
        assert meta.source_url == "http://arxiv.org/abs/2501.12345v1"
        assert meta.download_url == "https://arxiv.org/pdf/2501.12345v1"
        assert meta.extra["arxiv_id"] == "2501.12345"
        assert "q-fin.ST" in meta.extra["categories"]

    def test_to_metadata_extracts_github_url(self, connector):
        """GitHub URLs mentioned in arXiv metadata should be captured."""
        mock_result = MagicMock()
        mock_result.title = "Test Factor Paper"
        mock_result.entry_id = "http://arxiv.org/abs/2501.12345v1"
        mock_result.pdf_url = "https://arxiv.org/pdf/2501.12345v1"
        mock_result.authors = []
        mock_result.published = MagicMock()
        mock_result.published.strftime.return_value = "2025-01-15"
        mock_result.summary = "Code is available at https://github.com/example/factor-paper."
        mock_result.categories = []
        mock_result.comment = None

        meta = connector._to_metadata(mock_result)

        assert meta.github_url == "https://github.com/example/factor-paper"

    def test_to_metadata_preserves_author_affiliations(self, connector):
        """Optional arXiv affiliations should populate paper and author metadata."""
        mock_result = MagicMock()
        mock_result.title = "Institutional Factor Research"
        mock_result.entry_id = "http://arxiv.org/abs/2501.12345v1"
        mock_result.pdf_url = "https://arxiv.org/pdf/2501.12345v1"
        alice = MagicMock(name="alice")
        alice.name = "Alice Zhang"
        alice.affiliation = ["Tsinghua University"]
        bob = MagicMock(name="bob")
        bob.name = "Bob Smith"
        bob.affiliation = ["University of Chicago", "NBER"]
        mock_result.authors = [alice, bob]
        mock_result.published.strftime.return_value = "2025-01-15"
        mock_result.summary = "Portfolio research."
        mock_result.categories = ["q-fin.PM"]
        mock_result.comment = None

        meta = connector._to_metadata(mock_result)

        assert meta.institution == "Tsinghua University; University of Chicago; NBER"
        assert meta.extra["author_affiliations"][0] == {
            "name": "Alice Zhang", "affiliations": ["Tsinghua University"]
        }
        assert meta.extra["affiliation_source"] == "arxiv_api"

    def test_to_metadata_chinese(self, connector):
        """Chinese titles should be detected."""
        mock_result = MagicMock()
        mock_result.title = "A股市场因子研究"  # Contains CJK
        mock_result.entry_id = "http://arxiv.org/abs/2501.12345v1"
        mock_result.pdf_url = "https://arxiv.org/pdf/2501.12345"
        mock_result.authors = []
        mock_result.published = MagicMock()
        mock_result.published.strftime.return_value = "2025-01-15"
        mock_result.summary = "摘要"
        mock_result.categories = []

        meta = connector._to_metadata(mock_result)
        assert meta.language == "zh"


# ---------------------------------------------------------------------------
# ingest_from_metadata bridge tests
# ---------------------------------------------------------------------------

class TestIngestFromMetadata:
    """Test the connector→DB bridge function."""

    def test_metadata_only_no_download(self, db, file_store, sample_metadata):
        """Ingesting with download=False should store metadata-only."""
        result = ingest_from_metadata(
            db, file_store, sample_metadata, download=False,
        )
        assert result.status == "new"

        paper = db.execute(
            "SELECT * FROM papers WHERE id = ?", (result.paper_id,)
        ).fetchone()
        assert paper["title"] == sample_metadata.title
        assert paper["access_status"] == "queued"
        assert paper["download_url"] == sample_metadata.download_url
        assert paper["github_url"] == sample_metadata.github_url
        assert paper["file_path"] is None
        assert paper["quality_screening_status"] == "metadata_only"

    def test_metadata_only_persists_author_affiliations(self, db, file_store, sample_metadata):
        sample_metadata.institution = None
        sample_metadata.extra.update({
            "author_affiliations": [
                {"name": "Zhang Wei", "affiliations": ["Tsinghua University"]},
                {"name": "Li Ming", "affiliations": ["Peking University"]},
            ],
            "affiliation_source": "arxiv_api",
            "affiliation_evidence_url": sample_metadata.source_url,
        })
        result = ingest_from_metadata(db, file_store, sample_metadata, download=False)
        paper = db.execute("SELECT * FROM papers WHERE id = ?", (result.paper_id,)).fetchone()
        authors = db.execute(
            "SELECT * FROM paper_authors WHERE paper_id = ? ORDER BY author_order",
            (result.paper_id,),
        ).fetchall()
        assert paper["institution"] == "Tsinghua University; Peking University"
        assert authors[0]["institution"] == "Tsinghua University"
        assert authors[1]["institution"] == "Peking University"
        assert authors[0]["affiliation_source"] == "arxiv_api"

    def test_with_connector_download_success(self, db, file_store, sample_metadata, tmpdir):
        """When connector download succeeds, file should be stored."""
        # Create a mock connector
        mock_conn = MagicMock()
        pdf_path = tmpdir / "test.pdf"
        pdf_path.write_text("PDF content" * 100)
        mock_conn.download.return_value = DownloadResult(
            success=True,
            local_path=str(pdf_path),
            file_size=len("PDF content" * 100),
        )

        result = ingest_from_metadata(
            db, file_store, sample_metadata,
            download=True,
            connector=mock_conn,
        )
        assert result.status == "new"

        paper = db.execute(
            "SELECT * FROM papers WHERE id = ?", (result.paper_id,)
        ).fetchone()
        assert paper["access_status"] == "downloaded"
        assert paper["file_path"] is not None
        assert paper["quality_screening_status"] == "full_text_available"
        assert file_store.exists(paper["file_path"])

    def test_with_connector_download_failure(self, db, file_store, sample_metadata):
        """When connector download fails, fall back to metadata-only."""
        mock_conn = MagicMock()
        mock_conn.download.return_value = DownloadResult(
            success=False, error="Network timeout",
        )

        result = ingest_from_metadata(
            db, file_store, sample_metadata,
            download=True,
            connector=mock_conn,
        )
        assert result.status == "new"

        paper = db.execute(
            "SELECT * FROM papers WHERE id = ?", (result.paper_id,)
        ).fetchone()
        assert paper["access_status"] == "failed"
        assert paper["file_path"] is None

    def test_deduplication(self, db, file_store, sample_metadata):
        """Ingesting the same metadata twice should detect duplicate."""
        r1 = ingest_from_metadata(
            db, file_store, sample_metadata, download=False,
        )
        assert r1.status == "new"

        r2 = ingest_from_metadata(
            db, file_store, sample_metadata, download=False,
        )
        assert r2.status == "duplicate"
        assert r2.duplicate_of == r1.paper_id

    def test_different_metadata_no_duplicate(self, db, file_store):
        """Different titles should not trigger duplicate."""
        m1 = PaperMetadata(
            title="Paper About Factor A",
            source_type="academic_paper",
            source_name="arxiv",
            authors_raw="Author One",
            publication_date="2025-01",
        )
        m2 = PaperMetadata(
            title="Completely Different Research on Strategy B",
            source_type="academic_paper",
            source_name="arxiv",
            authors_raw="Author Two",
            publication_date="2025-06",
        )

        r1 = ingest_from_metadata(db, file_store, m1, download=False)
        r2 = ingest_from_metadata(db, file_store, m2, download=False)

        assert r1.status == "new"
        assert r2.status == "new"
        assert r1.paper_id != r2.paper_id

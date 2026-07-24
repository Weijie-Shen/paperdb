"""Unit tests for PaperDB core — schema, hashing, file store, and ingestion."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from paperdb.db.schema import init_db, get_db
from paperdb.db.models import Paper, PaperLabel, PaperAuthor, User, new_id
from paperdb.storage.file_store import FileStore
from paperdb.utils.hashing import (
    normalize_title,
    normalize_authors,
    compute_metadata_hash,
    compute_content_hash,
)
from paperdb.ingest import (
    ingest_from_file,
    ingest_metadata_only,
    download_paper_file,
    _check_duplicate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmpdir():
    """Create a temporary directory, cleaned up after the test."""
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def db(tmpdir):
    """Initialise a fresh in-memory-like DB in a temp dir."""
    db_path = tmpdir / "test.sqlite"
    conn = init_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def file_store(tmpdir):
    """Create a FileStore with initialised directory tree."""
    fs = FileStore(tmpdir / "files")
    fs.init()
    return fs


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchema:
    """Verify table creation and WAL mode."""

    def test_all_tables_exist(self, db):
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {t["name"] for t in tables}
        expected = {"papers", "paper_labels", "paper_authors", "users",
                    "user_annotations", "search_logs", "download_logs"}
        assert expected <= names

    def test_papers_have_download_and_github_url_columns(self, db):
        cols = db.execute("PRAGMA table_info(papers)").fetchall()
        names = {c["name"] for c in cols}
        assert "download_url" in names
        assert "github_url" in names

    def test_wal_mode(self, db):
        row = db.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_foreign_keys_enabled(self, db):
        row = db.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_indexes_exist(self, db):
        indexes = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ).fetchall()
        names = {i["name"] for i in indexes}
        # At minimum these should be present:
        assert "idx_papers_metadata_hash" in names
        assert "idx_labels_paper" in names
        assert "idx_authors_paper" in names


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    """Verify model creation and serialization."""

    def test_paper_defaults(self):
        p = Paper(title="Test", source_type="academic_paper")
        assert p.id.startswith("p_")
        assert p.access_status == "queued"
        assert p.quality_flag == "ok"
        assert p.priority_score == 0

    def test_paper_to_dict_roundtrip(self, db):
        p = Paper(
            title="因子研究",
            source_type="broker_report",
            institution="华泰证券",
            authors_raw="张三; 李四",
            download_url="https://example.com/paper.pdf",
            github_url="https://github.com/example/paper-code",
            market="a_share",
            priority_score=1,
        )
        db.execute(
            """INSERT INTO papers (
                id, title, authors_raw, institution, source_type, download_url, github_url,
                market, priority_score, access_status, quality_flag,
                created_at, updated_at
            ) VALUES (
                :id, :title, :authors_raw, :institution, :source_type, :download_url, :github_url,
                :market, :priority_score, :access_status, :quality_flag,
                :created_at, :updated_at
            )""",
            p.to_dict(),
        )
        db.commit()
        row = db.execute("SELECT * FROM papers WHERE id = ?", (p.id,)).fetchone()
        assert row["title"] == "因子研究"
        assert row["institution"] == "华泰证券"
        assert row["download_url"] == "https://example.com/paper.pdf"
        assert row["github_url"] == "https://github.com/example/paper-code"

    def test_label_to_dict(self):
        lbl = PaperLabel(paper_id="p_test", label="factor_research", confidence=0.92)
        d = lbl.to_dict()
        assert d["label"] == "factor_research"
        assert d["confidence"] == 0.92
        assert d["source"] == "ai_auto"

    def test_author_to_dict(self):
        a = PaperAuthor(paper_id="p_test", author_name="张三", author_order=1)
        d = a.to_dict()
        assert d["author_name"] == "张三"
        assert d["author_order"] == 1
        assert d["is_corresponding"] == 0

    def test_new_id_uniqueness(self):
        ids = {new_id("p") for _ in range(100)}
        assert len(ids) == 100

    def test_user_defaults(self):
        u = User(name="testuser")
        assert u.role == "researcher"
        assert u.id.startswith("u_")


# ---------------------------------------------------------------------------
# Hashing tests
# ---------------------------------------------------------------------------

class TestHashing:
    """Verify title normalization and hash stability."""

    def test_normalize_title_basic(self):
        assert normalize_title("Size and Value in the Chinese A-Share Market") == \
            "size value chinese share market"

    def test_normalize_title_noise_removal(self):
        # "the", "in", "a", "new", "novel", "evidence", etc. are noise
        t = normalize_title("The New Evidence on A Novel Factor in China")
        # noise words stripped
        assert "the" not in t
        assert "new" not in t
        assert "novel" not in t
        assert "evidence" not in t
        assert "factor" in t
        assert "china" in t

    def test_normalize_title_punctuation(self):
        assert normalize_title("Factor Timing: When & How?") == \
            "factor timing when how"

    def test_normalize_authors_sorting(self):
        # Order-independent
        result = normalize_authors("Zhang, Wei; Li, Ming")
        assert "li ming" in result
        assert "zhang wei" in result
        assert result == "li ming; zhang wei"

    def test_metadata_hash_stable(self):
        h1 = compute_metadata_hash("Test Paper", "张三; 李四", "2025-01")
        h2 = compute_metadata_hash("Test Paper", "张三; 李四", "2025-01")
        assert h1 == h2

    def test_metadata_hash_differs(self):
        h1 = compute_metadata_hash("Paper A", "张三", "2025-01")
        h2 = compute_metadata_hash("Paper B", "张三", "2025-01")
        assert h1 != h2

    def test_metadata_hash_normalized(self):
        # Different author formatting should produce same hash
        h1 = compute_metadata_hash("Test", "Zhang Wei; Li Ming", "2025")
        h2 = compute_metadata_hash("Test", "li ming; zhang wei", "2025")
        assert h1 == h2

    def test_content_hash(self, tmpdir):
        f = tmpdir / "test.txt"
        f.write_text("hello world")
        h1 = compute_content_hash(str(f))
        h2 = compute_content_hash(str(f))
        assert h1 == h2
        assert len(h1) == 64  # SHA-256


# ---------------------------------------------------------------------------
# File store tests
# ---------------------------------------------------------------------------

class TestFileStore:
    """Verify file storage operations."""

    def test_init_creates_dirs(self, tmpdir):
        fs = FileStore(tmpdir / "files")
        fs.init()
        assert (tmpdir / "files" / "raw_pdf").is_dir()
        assert (tmpdir / "files" / "_inbox").is_dir()
        assert (tmpdir / "files" / "parsed" / "text").is_dir()

    def test_add_file_copy(self, file_store, tmpdir):
        src = tmpdir / "source.pdf"
        src.write_text("pdf content")
        rel = file_store.add_file("p_test", str(src), fmt="pdf")
        assert rel == "raw_pdf/p_test.pdf"
        assert file_store.exists(rel)

    def test_add_file_move(self, file_store, tmpdir):
        src = tmpdir / "source.pdf"
        src.write_text("pdf content")
        file_store.add_file("p_test2", str(src), fmt="pdf", move=True)
        assert not src.exists()  # Moved away

    def test_write_parsed_text(self, file_store):
        rel = file_store.write_parsed_text("p_test", "extracted text content")
        assert rel == "parsed/text/p_test.txt"
        text = file_store.read_text(rel)
        assert text == "extracted text content"

    def test_write_summary(self, file_store):
        rel = file_store.write_summary("p_test", "# Summary\nThis is a summary.")
        content = file_store.read_text(rel)
        assert "# Summary" in content

    def test_list_inbox(self, file_store, tmpdir):
        inbox = tmpdir / "files" / "_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "report1.pdf").write_text("a")
        (inbox / "report2.pdf").write_text("b")
        files = file_store.list_inbox()
        assert len(files) == 2

    def test_remove_file(self, file_store, tmpdir):
        src = tmpdir / "source.pdf"
        src.write_text("pdf content")
        rel = file_store.add_file("p_del", str(src), fmt="pdf")
        assert file_store.exists(rel)
        file_store.remove_file(rel)
        assert not file_store.exists(rel)


# ---------------------------------------------------------------------------
# Ingest / dedup tests
# ---------------------------------------------------------------------------

class TestIngest:
    """Verify the ingestion pipeline end-to-end."""

    def test_ingest_from_file(self, db, file_store, tmpdir):
        src = tmpdir / "report.pdf"
        src.write_text("broker report content")

        result = ingest_from_file(
            db, file_store,
            title="A股多因子选股研究",
            file_path=str(src),
            source_type="broker_report",
            source_name="华泰证券",
            authors_raw="张三; 李四",
            institution="华泰证券",
            publication_date="2025-03",
            market="a_share",
            language="zh",
        )
        assert result.status == "new"
        assert result.paper_id.startswith("p_")

        # Verify DB record
        paper = db.execute(
            "SELECT * FROM papers WHERE id = ?", (result.paper_id,)
        ).fetchone()
        assert paper["title"] == "A股多因子选股研究"
        assert paper["institution"] == "华泰证券"
        assert paper["access_status"] == "downloaded"
        assert paper["file_path"] is not None
        assert paper["file_format"] == "pdf"
        assert paper["content_hash"] is not None
        assert paper["metadata_hash"] is not None

        # Verify authors
        authors = db.execute(
            "SELECT author_name FROM paper_authors WHERE paper_id = ? ORDER BY author_order",
            (result.paper_id,),
        ).fetchall()
        assert [a["author_name"] for a in authors] == ["张三", "李四"]

        # Verify file exists on disk
        assert file_store.exists(paper["file_path"])

    def test_ingest_metadata_only(self, db):
        result = ingest_metadata_only(
            db,
            title="深度学习因子挖掘",
            source_type="academic_paper",
            source_name="arxiv",
            source_url="https://arxiv.org/abs/2501.12345",
            download_url="https://arxiv.org/pdf/2501.12345.pdf",
            authors_raw="王五",
            institution="清华大学",
            github_url="https://github.com/example/repo",
            publication_date="2025-06",
            market="a_share",
            language="zh",
            access_status="manual_required",
            access_notes="ArXiv preprint, pending download",
        )
        assert result.status == "new"

        paper = db.execute(
            "SELECT * FROM papers WHERE id = ?", (result.paper_id,)
        ).fetchone()
        assert paper["access_status"] == "manual_required"
        assert paper["access_notes"] == "ArXiv preprint, pending download"
        assert paper["download_url"] == "https://arxiv.org/pdf/2501.12345.pdf"
        assert paper["github_url"] == "https://github.com/example/repo"
        assert paper["file_path"] is None

    def test_download_paper_file_updates_existing_row(self, db, file_store, tmpdir):
        result = ingest_metadata_only(
            db,
            title="Delayed Download Paper",
            source_type="academic_paper",
            source_name="arxiv",
            source_url="https://arxiv.org/abs/2501.12345",
            download_url="https://arxiv.org/pdf/2501.12345.pdf",
            access_status="queued",
        )
        src = tmpdir / "downloaded.pdf"
        src.write_text("PDF content" * 200)

        class MockConnector:
            def download(self, metadata):
                from paperdb.connectors.base import DownloadResult
                return DownloadResult(
                    success=True,
                    local_path=str(src),
                    file_size=src.stat().st_size,
                )

        dl_result = download_paper_file(
            db, file_store, result.paper_id, connector=MockConnector()
        )

        assert dl_result.success is True
        paper = db.execute(
            "SELECT * FROM papers WHERE id = ?", (result.paper_id,)
        ).fetchone()
        assert paper["access_status"] == "downloaded"
        assert paper["file_path"] is not None
        assert paper["content_hash"] is not None
        assert file_store.exists(paper["file_path"])

    def test_detect_duplicate_exact(self, db, file_store, tmpdir):
        """Ingesting the same paper twice should detect duplicate."""
        src = tmpdir / "dup.pdf"
        src.write_text("content")

        # First ingest
        r1 = ingest_from_file(
            db, file_store,
            title="重复测试论文",
            file_path=str(src),
            source_type="academic_paper",
            source_name="test",
            authors_raw="测试作者",
            publication_date="2025-01",
        )
        assert r1.status == "new"

        # Second ingest — same metadata
        r2 = ingest_from_file(
            db, file_store,
            title="重复测试论文",
            file_path=str(src),
            source_type="academic_paper",
            source_name="test",
            authors_raw="测试作者",
            publication_date="2025-01",
        )
        assert r2.status == "duplicate"
        assert r2.duplicate_of == r1.paper_id

    def test_detect_duplicate_metadata_only(self, db, file_store, tmpdir):
        """File ingest → metadata-only with same title should catch dup."""
        src = tmpdir / "meta_dup.pdf"
        src.write_text("content")

        r1 = ingest_from_file(
            db, file_store,
            title="元数据去重测试",
            file_path=str(src),
            source_type="broker_report",
            source_name="test",
            authors_raw="测试; 作者",
            publication_date="2025-03",
        )
        assert r1.status == "new"

        r2 = ingest_metadata_only(
            db,
            title="元数据去重测试",
            source_type="broker_report",
            source_name="test",
            authors_raw="测试; 作者",
            publication_date="2025-03",
        )
        assert r2.status == "duplicate"
        assert r2.duplicate_of == r1.paper_id

    def test_no_duplicate_different_title(self, db, file_store, tmpdir):
        """Different titles should not trigger duplicate."""
        src = tmpdir / "diff1.pdf"
        src.write_text("a")
        r1 = ingest_from_file(
            db, file_store,
            title="完全不同的论文标题A",
            file_path=str(src),
            source_type="academic_paper",
            source_name="test",
            authors_raw="张三",
            publication_date="2025-01",
        )
        assert r1.status == "new"

        r2 = ingest_from_file(
            db, file_store,
            title="完全不同的论文标题B",
            file_path=str(src),
            source_type="academic_paper",
            source_name="test",
            authors_raw="张三",
            publication_date="2025-01",
        )
        assert r2.status == "new"  # Different title, should NOT be dup
        assert r1.paper_id != r2.paper_id

"""Tests for the optional FastAPI layer."""

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
try:
    from fastapi.testclient import TestClient
except RuntimeError as exc:
    pytest.skip(str(exc), allow_module_level=True)

from paperdb.api.app import create_app
from paperdb.db.schema import init_db
from paperdb.storage.file_store import FileStore


@pytest.fixture
def api_root(tmp_path: Path) -> Path:
    root = tmp_path / "paper_database"
    (root / "db").mkdir(parents=True)
    fs = FileStore(root / "files")
    fs.init()
    init_db(root / "db" / "papers.sqlite").close()
    return root


@pytest.fixture
def client(api_root: Path):
    return TestClient(create_app(api_root))


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_list_and_get_paper(client):
    create = client.post(
        "/papers",
        json={
            "title": "API Test Paper",
            "source_type": "academic_paper",
            "source_name": "test",
            "download_url": "https://example.com/test.pdf",
            "access_status": "queued",
        },
    )
    assert create.status_code == 201
    paper_id = create.json()["paper_id"]

    label = client.post(
        f"/papers/{paper_id}/labels",
        json={"label": "factor_research", "confidence": 0.93},
    )
    assert label.status_code == 201

    listed = client.get("/papers", params={"label": "factor_research"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    detail = client.get(f"/papers/{paper_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["title"] == "API Test Paper"
    assert body["download_url"] == "https://example.com/test.pdf"
    assert body["labels"][0]["label"] == "factor_research"
    assert body["file"]["available"] is False
    assert body["download_status"] == "queued"
    assert body["institutions"] == []
    assert body["download_logs"] == []


def test_facets_and_health_only_include_active_papers(client, api_root):
    active = client.post(
        "/papers",
        json={"title": "Active", "source_type": "academic_paper", "market": "a_share"},
    ).json()["paper_id"]
    rejected = client.post(
        "/papers",
        json={"title": "Rejected", "source_type": "blog_article", "market": "us"},
    ).json()["paper_id"]
    conn = init_db(api_root / "db" / "papers.sqlite")
    conn.execute("UPDATE papers SET lifecycle_status = 'rejected_out_of_scope' WHERE id = ?", (rejected,))
    conn.commit()
    conn.close()

    assert client.get("/health").json()["papers"] == 1
    facets = client.get("/papers/facets").json()
    assert facets["market"] == [{"value": "a_share", "count": 1}]
    assert facets["source_type"] == [{"value": "academic_paper", "count": 1}]
    assert client.get("/papers").json()["results"][0]["id"] == active


def test_local_paper_file(client, api_root):
    paper_id = client.post(
        "/papers",
        json={"title": "A / Demo Paper", "source_type": "academic_paper"},
    ).json()["paper_id"]
    relative_path = f"raw_pdf/{paper_id}.pdf"
    stored = api_root / "files" / relative_path
    stored.write_bytes(b"%PDF-1.4 demo")
    conn = init_db(api_root / "db" / "papers.sqlite")
    conn.execute(
        "UPDATE papers SET file_path = ?, file_format = 'pdf', access_status = 'downloaded' WHERE id = ?",
        (relative_path, paper_id),
    )
    conn.commit()
    conn.close()

    detail = client.get(f"/papers/{paper_id}").json()
    assert detail["file"]["available"] is True
    assert detail["file"]["download_url"] == f"/papers/{paper_id}/file"
    response = client.get(f"/papers/{paper_id}/file")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 demo"
    assert "A%20_%20Demo%20Paper.pdf" in response.headers["content-disposition"]

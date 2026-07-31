import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from paperdb.supabase.client import SupabaseClient, SupabaseError


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_rpc_sends_key_and_json(monkeypatch):
    captured = {}

    def fake_open(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response(b'{"total":0,"results":[]}')

    monkeypatch.setattr("paperdb.supabase.client.urlopen", fake_open)
    client = SupabaseClient("https://example.supabase.co/", "publishable", timeout=12)

    result = client.rpc("search_papers", query_text="momentum")

    assert result == {"total": 0, "results": []}
    assert captured["request"].full_url.endswith("/rest/v1/rpc/search_papers")
    assert captured["request"].get_header("Apikey") == "publishable"
    assert json.loads(captured["request"].data) == {"query_text": "momentum"}
    assert captured["timeout"] == 12


def test_http_error_does_not_expose_key(monkeypatch):
    def fake_open(request, timeout):
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, BytesIO(b'{"message":"denied"}'))

    monkeypatch.setattr("paperdb.supabase.client.urlopen", fake_open)
    client = SupabaseClient("https://example.supabase.co", "secret-value")

    with pytest.raises(SupabaseError) as error:
        client.select("papers")

    assert "401" in str(error.value)
    assert "secret-value" not in str(error.value)


def test_upload_encodes_object_path(tmp_path, monkeypatch):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    captured = {}

    def fake_open(request, timeout):
        captured["request"] = request
        return Response(b'{}')

    monkeypatch.setattr("paperdb.supabase.client.urlopen", fake_open)
    client = SupabaseClient("https://example.supabase.co", "secret")

    client.upload_file(source, "papers/p 1/paper.pdf")

    assert captured["request"].full_url.endswith("/paper-files/papers/p%201/paper.pdf")
    assert captured["request"].get_header("X-upsert") == "true"


def test_remove_files_uses_storage_delete(monkeypatch):
    captured = {}

    def fake_open(request, timeout):
        captured["request"] = request
        return Response(b'[]')

    monkeypatch.setattr("paperdb.supabase.client.urlopen", fake_open)
    client = SupabaseClient("https://example.supabase.co", "secret")
    client.remove_files(["checks/test.pdf"])

    assert captured["request"].method == "DELETE"
    assert captured["request"].full_url.endswith("/storage/v1/object/paper-files")
    assert json.loads(captured["request"].data) == {"prefixes": ["checks/test.pdf"]}

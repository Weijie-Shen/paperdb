"""Small dependency-free client for Supabase Data API and Storage.

This client is intended for the trusted local ingestion agent. Browser reads
use the publishable key; local writes require a secret/service-role key.
"""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class SupabaseError(RuntimeError):
    """A failed Supabase HTTP operation."""


class SupabaseClient:
    def __init__(self, url: str, key: str, *, timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.key = key
        self.timeout = timeout

    @classmethod
    def from_env(cls, *, write: bool = False) -> "SupabaseClient":
        url = os.environ.get("SUPABASE_URL", "").strip()
        key_name = "SUPABASE_SECRET_KEY" if write else "SUPABASE_PUBLISHABLE_KEY"
        key = (
            os.environ.get("SUPABASE_SECRET_KEY", "")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        ).strip() if write else os.environ.get(key_name, "").strip()
        if not url or not key:
            legacy = " (or SUPABASE_SERVICE_ROLE_KEY)" if write else ""
            raise SupabaseError(f"SUPABASE_URL and {key_name}{legacy} must be configured")
        return cls(url, key)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        raw: bool = False,
    ) -> Any:
        request_headers = {"apikey": self.key, **(headers or {})}
        # Legacy anon/service-role keys are JWTs. Modern sb_publishable/sb_secret
        # keys belong in the apikey header and must not be presented as JWTs.
        if self.key.startswith("eyJ"):
            request_headers["Authorization"] = f"Bearer {self.key}"
        data: Optional[bytes]
        if body is None:
            data = None
        elif isinstance(body, bytes):
            data = body
        else:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(f"{self.url}{path}", data=data, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                if raw:
                    return payload
                return json.loads(payload) if payload else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SupabaseError(f"Supabase returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise SupabaseError(f"Could not reach Supabase: {exc.reason}") from exc

    def select(self, table: str, *, params: Optional[Mapping[str, Any]] = None) -> list[dict]:
        query = urlencode({"select": "*", **(params or {})}, doseq=True)
        return self._request("GET", f"/rest/v1/{quote(table)}?{query}") or []

    def upsert(
        self,
        table: str,
        rows: Mapping[str, Any] | Iterable[Mapping[str, Any]],
        *,
        on_conflict: Optional[str] = None,
    ) -> list[dict]:
        suffix = f"?on_conflict={quote(on_conflict)}" if on_conflict else ""
        return self._request(
            "POST",
            f"/rest/v1/{quote(table)}{suffix}",
            body=rows,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        ) or []

    def delete(self, table: str, **equals: Any) -> None:
        query = urlencode({key: f"eq.{value}" for key, value in equals.items()})
        self._request("DELETE", f"/rest/v1/{quote(table)}?{query}")

    def rpc(self, function: str, **arguments: Any) -> Any:
        return self._request("POST", f"/rest/v1/rpc/{quote(function)}", body=arguments)

    def upload_file(
        self,
        source: str | Path,
        object_path: str,
        *,
        bucket: str = "paper-files",
        content_type: Optional[str] = None,
    ) -> str:
        source_path = Path(source)
        mime = content_type or mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        encoded_path = "/".join(quote(part, safe="") for part in object_path.split("/"))
        self._request(
            "POST",
            f"/storage/v1/object/{quote(bucket)}/{encoded_path}",
            body=source_path.read_bytes(),
            headers={"Content-Type": mime, "x-upsert": "true"},
        )
        return object_path

    def download_file(self, object_path: str, *, bucket: str = "paper-files") -> bytes:
        encoded_path = "/".join(quote(part, safe="") for part in object_path.split("/"))
        return self._request("GET", f"/storage/v1/object/{quote(bucket)}/{encoded_path}", raw=True)

    def remove_files(self, object_paths: Iterable[str], *, bucket: str = "paper-files") -> None:
        prefixes = list(object_paths)
        if prefixes:
            self._request(
                "DELETE",
                f"/storage/v1/object/{quote(bucket)}",
                body={"prefixes": prefixes},
            )

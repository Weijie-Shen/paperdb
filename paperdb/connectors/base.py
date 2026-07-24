"""Base connector interface and shared types for source connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class PaperMetadata:
    """Lightweight struct representing a paper/report found by a connector.

    This is the interchange format between connectors and the ingestion
    pipeline. Every connector returns a list of these.
    """

    title: str
    source_type: str                    # academic_paper | broker_report | white_paper | blog_article | other
    source_name: str                    # e.g. "arxiv", "choice", "semantic_scholar", "web"

    # Authors (raw string, semicolon-delimited)
    authors_raw: Optional[str] = None

    # Institution / broker / research org
    institution: Optional[str] = None

    # Identifiers
    source_url: Optional[str] = None
    github_url: Optional[str] = None
    source_id: Optional[str] = None     # Connector-specific ID (arxiv ID, Choice report ID, etc.)

    # Publication info
    publication_date: Optional[str] = None
    abstract: Optional[str] = None
    language: Optional[str] = None

    # Classification hints (optional; may be filled by connector or left for AI)
    market: Optional[str] = None
    frequency: Optional[str] = None

    # Access info
    download_url: Optional[str] = None
    file_format: Optional[str] = "pdf"

    # Extra data (connector-specific fields)
    extra: dict = field(default_factory=dict)


@dataclass
class DownloadResult:
    """Result of a download attempt."""

    success: bool
    local_path: Optional[str] = None        # Absolute path to downloaded file
    file_size: Optional[int] = None
    content_hash: Optional[str] = None
    error: Optional[str] = None
    http_status: Optional[int] = None
    error_type: Optional[str] = None
    retryable: Optional[bool] = None


class BaseConnector(Protocol):
    """Protocol that all source connectors must satisfy.

    A connector is an **optional accelerator** — the AI can always fall back
    to ``web_search`` + ``web_extract`` for sources without a connector.
    """

    name: str
    source_type: str
    can_search: bool
    can_download: bool
    can_harvest: bool
    rate_limit_rps: float
    requires_auth: bool
    auth_type: Optional[str]           # api_key | cookie | terminal | institutional | None

    def search(self, query: str, limit: int = 50) -> list[PaperMetadata]:
        """Search this source for papers matching *query*.

        Raises ``NotImplementedError`` if ``can_search`` is False.
        """
        ...

    def harvest(self, since: str, limit: int = 50) -> list[PaperMetadata]:
        """Retrieve recently published papers (e.g. last 7 days).

        Raises ``NotImplementedError`` if ``can_harvest`` is False.
        """
        ...

    def download(self, metadata: PaperMetadata) -> DownloadResult:
        """Download the full-text file for a paper.

        Raises ``NotImplementedError`` if ``can_download`` is False.
        """
        ...

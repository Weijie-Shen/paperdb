"""arXiv connector — search and download papers from arXiv.org.

Uses the ``arxiv`` Python package (v4.x) for API access.
"""

from __future__ import annotations

import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

from paperdb.connectors.base import BaseConnector, PaperMetadata, DownloadResult

logger = logging.getLogger(__name__)

GITHUB_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", re.IGNORECASE)

# arXiv categories relevant to quant finance
DEFAULT_CATEGORIES = [
    "q-fin.ST",   # Statistical Finance
    "q-fin.PM",   # Portfolio Management
    "q-fin.RM",   # Risk Management
    "q-fin.TR",   # Trading and Market Microstructure
    "q-fin.CP",   # Computational Finance
    "q-fin.EC",   # Economics
    "econ.EM",    # Econometrics
    "stat.ML",    # Machine Learning (statistics)
    "cs.LG",      # Machine Learning (cs)
]
ARXIV_ID_RE = re.compile(
    r"^(?:arXiv:)?([a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?$",
    re.IGNORECASE,
)


class ArxivSourceError(RuntimeError):
    """Observable arXiv source failure, distinct from a valid empty result."""

    def __init__(self, message: str, *, error_type: str = "source_error",
                 retryable: bool = True):
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


class ArxivConnector:
    """Search and download papers from arXiv.

    Implements :class:`BaseConnector` for the arXiv API.

    Usage::

        conn = ArxivConnector()
        results = conn.search("factor timing China A-share", limit=20)
        for paper in results:
            if not conn.exists_in_db(paper):
                conn.download(paper)
    """

    name = "arxiv"
    source_type = "academic_paper"
    can_search = True
    can_download = True
    can_harvest = True
    rate_limit_rps = 1.0         # arXiv asks for ~1 req/s with bursts
    requires_auth = False
    auth_type = None

    def __init__(self, categories: Optional[list[str]] = None, timeout_seconds: int = 20):
        self.categories = categories or DEFAULT_CATEGORIES
        self.timeout_seconds = timeout_seconds
        self._last_request = 0.0

    def _client(self):
        """Build a single-attempt client with a bounded HTTP request."""
        import arxiv
        client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=0)
        session = getattr(client, "_session", None)
        if session is not None:
            original_get = session.get
            session.get = lambda *args, **kwargs: original_get(
                *args, timeout=kwargs.pop("timeout", self.timeout_seconds), **kwargs
            )
        return client

    def _source_error(self, exc: Exception) -> ArxivSourceError:
        name = type(exc).__name__.lower()
        message = str(exc)
        if "timeout" in name or "timed out" in message.lower():
            return ArxivSourceError(message or "arXiv request timed out",
                                    error_type="timeout", retryable=True)
        if "429" in message or "rate" in message.lower():
            return ArxivSourceError(message, error_type="rate_limit", retryable=True)
        if isinstance(exc, ValueError):
            return ArxivSourceError(message, error_type="invalid_response", retryable=False)
        return ArxivSourceError(message or repr(exc), error_type="network_error", retryable=True)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 50, *, finance_only: bool = False) -> list[PaperMetadata]:
        """Search arXiv for papers matching *query*.

        Args:
            query: Search query (supports arXiv API syntax: AND, OR, parentheses).
            limit: Maximum number of results (default 50, max 1000).

        Returns:
            List of :class:`PaperMetadata` objects.
        """
        import arxiv

        self._rate_limit()

        client = self._client()
        effective_query = query
        if finance_only and not re.search(r"\bcat:", query):
            cats = [cat for cat in self.categories if cat.startswith(("q-fin", "econ"))]
            effective_query = f"({query}) AND ({' OR '.join(f'cat:{cat}' for cat in cats)})"
        search = arxiv.Search(
            query=effective_query,
            max_results=min(limit, 1000),
            sort_by=arxiv.SortCriterion.Relevance,
        )

        results = []
        try:
            for result in client.results(search):
                results.append(self._to_metadata(result))
                if len(results) >= limit:
                    break
        except Exception as exc:
            error = self._source_error(exc)
            logger.warning("arXiv search error (%s): %s", error.error_type, error)
            raise error from exc

        return results

    def get_by_id(self, arxiv_id: str) -> Optional[PaperMetadata]:
        """Fetch exactly one arXiv record and verify the returned base ID."""
        import arxiv

        match = ARXIV_ID_RE.fullmatch(arxiv_id.strip())
        if not match:
            raise ValueError(f"Invalid arXiv ID: {arxiv_id}")
        requested = match.group(1)
        self._rate_limit()
        try:
            result = next(iter(self._client().results(
                arxiv.Search(id_list=[requested], max_results=1)
            )), None)
        except Exception as exc:
            raise self._source_error(exc) from exc
        if result is None:
            return None
        metadata = self._to_metadata(result)
        if metadata.source_id != requested:
            raise ValueError(
                f"arXiv returned {metadata.source_id!r} for requested ID {requested!r}"
            )
        return metadata

    # ------------------------------------------------------------------
    # Harvest (recent papers)
    # ------------------------------------------------------------------

    def harvest(self, since: str = "last_week", limit: int = 50) -> list[PaperMetadata]:
        """Retrieve recently published papers from configured categories.

        Args:
            since: Time filter — ``"last_week"``, ``"last_month"``, or an ISO date.
            limit: Maximum results per category.

        Returns:
            List of :class:`PaperMetadata` objects.
        """
        import arxiv

        # Build date filter
        if since == "last_week":
            days = 7
        elif since == "last_month":
            days = 30
        else:
            days = 30  # default

        import datetime
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

        all_results = []
        for cat in self.categories:
            self._rate_limit()
            query = f"cat:{cat}"
            client = self._client()
            search = arxiv.Search(
                query=query,
                max_results=min(limit, 100),
                sort_by=arxiv.SortCriterion.SubmittedDate,
            )

            try:
                for result in client.results(search):
                    if result.published.replace(tzinfo=datetime.timezone.utc) < cutoff:
                        break
                    all_results.append(self._to_metadata(result))
                    if len(all_results) >= limit * len(self.categories):
                        break
            except Exception as exc:
                error = self._source_error(exc)
                logger.warning("arXiv harvest error for %s (%s): %s", cat, error.error_type, error)
                raise error from exc

        return all_results

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(self, metadata: PaperMetadata) -> DownloadResult:
        """Download the PDF for a paper.

        Args:
            metadata: Paper metadata (must have ``download_url`` with PDF link).

        Returns:
            :class:`DownloadResult` with local path to the downloaded PDF.
        """
        import urllib.request
        import tempfile

        pdf_url = metadata.download_url or metadata.source_url
        if not pdf_url:
            return DownloadResult(success=False, error="No PDF URL in metadata")

        # Ensure it's a PDF URL (arXiv sometimes gives abstract page)
        if "arxiv.org/abs/" in pdf_url:
            pdf_url = pdf_url.replace("/abs/", "/pdf/") + ".pdf"
        if not pdf_url.endswith(".pdf"):
            pdf_url = pdf_url.rstrip("/") + ".pdf"

        self._rate_limit()

        try:
            req = urllib.request.Request(pdf_url, headers={"User-Agent": "PaperDB/0.1"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()

            if len(data) < 1000:
                return DownloadResult(
                    success=False,
                    error=f"Downloaded file too small ({len(data)} bytes), likely not a PDF",
                    error_type="invalid_content",
                    retryable=False,
                )

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(data)
                local_path = tmp.name

            file_size = len(data)
            return DownloadResult(
                success=True,
                local_path=local_path,
                file_size=file_size,
            )
        except urllib.error.HTTPError as e:
            return DownloadResult(
                success=False,
                error=f"HTTP {e.code}: {e.reason}",
                http_status=e.code,
                error_type="http_error",
                retryable=e.code >= 500 or e.code == 429,
            )
        except (TimeoutError, urllib.error.URLError) as e:
            error_type = "timeout" if isinstance(e, TimeoutError) else "network_error"
            return DownloadResult(success=False, error=f"Download timed out: {e}",
                                  error_type=error_type, retryable=True)
        except Exception as e:
            return DownloadResult(
                success=False,
                error=f"Download failed: {e}",
                error_type="network_error",
                retryable=True,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_metadata(self, result) -> PaperMetadata:
        """Convert an arxiv.Result to PaperMetadata."""
        # Extract arXiv ID from entry_id (e.g. "http://arxiv.org/abs/2501.12345v1")
        arxiv_id = result.entry_id.split("/")[-1] if result.entry_id else ""
        # Strip version suffix for clean ID
        if "v" in arxiv_id:
            arxiv_id = arxiv_id.rsplit("v", 1)[0]

        def author_name(author) -> str:
            name = getattr(author, "name", None)
            return name if isinstance(name, str) else str(author)

        authors = "; ".join(author_name(a) for a in result.authors) if result.authors else None
        author_affiliations = [
            {
                "name": author_name(author),
                "affiliations": list(
                    getattr(author, "affiliation", [])
                    if isinstance(getattr(author, "affiliation", []), list) else []
                ),
            }
            for author in (result.authors or [])
        ]
        unique_affiliations = []
        for author in author_affiliations:
            for affiliation in author["affiliations"]:
                cleaned = affiliation.strip()
                if cleaned and cleaned not in unique_affiliations:
                    unique_affiliations.append(cleaned)

        # Guess language from title (simple heuristic)
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in result.title)
        language = "zh" if has_cjk else "en"
        comment = result.comment if hasattr(result, "comment") and isinstance(result.comment, str) else None
        metadata_text = " ".join(t for t in [result.summary, comment] if isinstance(t, str) and t)
        github_url = self._extract_github_url(metadata_text)

        return PaperMetadata(
            title=result.title,
            source_type=self.source_type,
            source_name=self.name,
            source_id=arxiv_id,
            source_url=result.entry_id,
            github_url=github_url,
            institution="; ".join(unique_affiliations) or None,
            authors_raw=authors,
            publication_date=result.published.strftime("%Y-%m-%d") if result.published else None,
            abstract=result.summary,
            language=language,
            market=None,  # AI will classify later
            frequency=None,
            download_url=result.pdf_url,
            file_format="pdf",
            extra={
                "arxiv_id": arxiv_id,
                "arxiv_url": result.entry_id,
                "categories": list(result.categories) if result.categories else [],
                "comment": comment,
                "author_affiliations": author_affiliations,
                "affiliation_source": "arxiv_api" if unique_affiliations else None,
                "affiliation_evidence_url": result.entry_id if unique_affiliations else None,
                "github_evidence_type": "arxiv_abstract" if github_url else None,
                "github_evidence_url": result.entry_id if github_url else None,
            },
        )

    def _extract_github_url(self, text: str) -> Optional[str]:
        """Return the first GitHub repository URL mentioned in metadata text."""
        match = GITHUB_RE.search(text or "")
        return match.group(0).rstrip(".,);]") if match else None

    def _rate_limit(self) -> None:
        """Enforce rate limiting between API calls."""
        elapsed = time.time() - self._last_request
        if elapsed < 1.0 / self.rate_limit_rps:
            time.sleep(1.0 / self.rate_limit_rps - elapsed)
        self._last_request = time.time()

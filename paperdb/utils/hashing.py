"""Hashing and text-normalization utilities for deduplication."""

from __future__ import annotations

import hashlib
import re
from typing import Optional


def normalize_title(title: str) -> str:
    """Normalize a title for fuzzy matching.

    Lowercases, strips punctuation / extra whitespace, and removes common
    noise words that vary between preprint / published versions.

    >>> normalize_title("Size and Value in the Chinese A-Share Market")
    'size value chinese share market'
    """
    t = title.lower().strip()
    # Remove punctuation except CJK characters and alphanumerics
    t = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Strip common noise words for fuzzy matching
    noise = {
        "a", "an", "the", "in", "of", "and", "or", "for", "on", "to",
        "is", "are", "was", "were", "be", "been", "being",
        "with", "from", "by", "at", "as", "into", "through",
        "its", "it", "this", "that", "these", "those",
        "new", "novel", "improved", "evidence", "empirical",
    }
    words = [w for w in t.split() if w not in noise]
    return " ".join(words)


def normalize_authors(authors_raw: str) -> str:
    """Normalize an author string for comparison.

    Lowercases, strips whitespace, sorts individual names (order-agnostic
    comparison), and removes punctuation.

    Authors are separated by semicolons. Commas within names (e.g.
    "Zhang, Wei") are preserved as part of the name, not treated as
    delimiters.

    >>> normalize_authors("Zhang, Wei; Li, Ming")
    'li ming; zhang wei'
    """
    # Split on semicolons only — commas are part of name format
    names = [n.strip().lower() for n in authors_raw.split(";") if n.strip()]
    names = sorted(re.sub(r"[^\w\s]", "", n).strip() for n in names)
    return "; ".join(names)


def compute_metadata_hash(
    title: str,
    authors: Optional[str] = None,
    publication_date: Optional[str] = None,
) -> str:
    """Compute a stable hash from title + authors + date for deduplication.

    Normalizes inputs before hashing so that minor formatting differences
    (capitalization, author order, whitespace) don't break matching.

    Returns a SHA-256 hex digest.
    """
    parts = [normalize_title(title)]
    if authors:
        parts.append(normalize_authors(authors))
    if publication_date:
        parts.append(publication_date.strip())

    joined = "||".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def compute_content_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file's contents.

    Reads the file in chunks to handle large PDFs without memory issues.
    """
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()

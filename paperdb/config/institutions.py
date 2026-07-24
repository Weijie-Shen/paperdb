"""Canonical institution identity matching for watchlist affiliations."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from paperdb.db.models import new_id, now_iso


@dataclass(frozen=True)
class InstitutionMatch:
    canonical_name: str
    raw_value: str
    matched_alias: str
    priority_rank: int
    priority_score: int
    source: str
    confidence: float


def normalize_institution(value: str) -> str:
    """Normalize typography while retaining words needed for identity matching."""
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"[\s,.;:()（）\[\]{}·'\"/\\_-]+", " ", text)
    return " ".join(text.split())


def _contains_alias(raw: str, alias: str) -> bool:
    raw_norm = normalize_institution(raw)
    alias_norm = normalize_institution(alias)
    if not alias_norm:
        return False
    # CJK organization names are conventionally embedded in department strings.
    if any("\u4e00" <= char <= "\u9fff" for char in alias_norm):
        return alias_norm in raw_norm
    # Avoid matching short English aliases inside unrelated words.
    return re.search(rf"(?<![a-z0-9]){re.escape(alias_norm)}(?![a-z0-9])", raw_norm) is not None


def match_institutions(entries: Iterable[dict], values: Iterable[tuple[str, str]]) -> list[InstitutionMatch]:
    """Match raw `(value, source)` pairs to canonical watchlist entries."""
    configured = list(entries)
    max_rank = max((int(item.get("priority", 0)) for item in configured), default=0)
    matches: list[InstitutionMatch] = []
    seen: set[tuple[str, str]] = set()
    for raw_value, source in values:
        if not raw_value:
            continue
        for entry in configured:
            canonical = entry["name"]
            aliases = [canonical, *(entry.get("aliases") or [])]
            matching = [alias for alias in aliases if _contains_alias(raw_value, alias)]
            if not matching:
                continue
            # Prefer the longest alias: it is normally the least ambiguous evidence.
            alias = max(matching, key=lambda value: len(normalize_institution(value)))
            key = (canonical, raw_value)
            if key in seen:
                continue
            seen.add(key)
            rank = int(entry.get("priority", max_rank + 1))
            score = max_rank - rank + 1 if rank <= max_rank else 0
            exact = normalize_institution(raw_value) == normalize_institution(alias)
            matches.append(InstitutionMatch(
                canonical_name=canonical,
                raw_value=raw_value,
                matched_alias=alias,
                priority_rank=rank,
                priority_score=score,
                source=source,
                confidence=0.99 if exact else 0.95,
            ))
    return sorted(matches, key=lambda item: (-item.priority_score, item.canonical_name))


def persist_institution_matches(conn, paper_id: str, matches: Iterable[InstitutionMatch]) -> None:
    """Store auditable canonical matches and refresh the paper's sort score."""
    matches = list(matches)
    for match in matches:
        conn.execute(
            """INSERT INTO paper_institutions
               (id, paper_id, canonical_name, raw_value, matched_alias,
                priority_rank, priority_score, match_source, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(paper_id, canonical_name, raw_value) DO UPDATE SET
                 matched_alias=excluded.matched_alias,
                 priority_rank=excluded.priority_rank,
                 priority_score=excluded.priority_score,
                 match_source=excluded.match_source,
                 confidence=excluded.confidence""",
            (new_id("pi"), paper_id, match.canonical_name, match.raw_value,
             match.matched_alias, match.priority_rank, match.priority_score,
             match.source, match.confidence, now_iso()),
        )
    if matches:
        score = max(match.priority_score for match in matches)
        conn.execute(
            "UPDATE papers SET priority_score = MAX(priority_score, ?), updated_at = ? WHERE id = ?",
            (score, now_iso(), paper_id),
        )
    conn.commit()


def refresh_institution_matches(conn, entries: Iterable[dict]) -> dict[str, int]:
    """Recompute canonical identities and priority scores for the whole database."""
    conn.execute("DELETE FROM paper_institutions")
    conn.execute("UPDATE papers SET priority_score = 0")
    papers = conn.execute("SELECT id, institution FROM papers").fetchall()
    matched_papers = 0
    match_count = 0
    for paper in papers:
        values = []
        if paper["institution"]:
            values.append((paper["institution"], "paper_institution"))
        authors = conn.execute(
            """SELECT institution, affiliation_source FROM paper_authors
               WHERE paper_id = ? AND institution IS NOT NULL AND TRIM(institution) != ''""",
            (paper["id"],),
        ).fetchall()
        values.extend(
            (author["institution"], author["affiliation_source"] or "author_affiliation")
            for author in authors
        )
        matches = match_institutions(entries, values)
        if matches:
            matched_papers += 1
            match_count += len(matches)
            persist_institution_matches(conn, paper["id"], matches)
    conn.commit()
    return {"papers_scanned": len(papers), "papers_matched": matched_papers,
            "matches_stored": match_count}

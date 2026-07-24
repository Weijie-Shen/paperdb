"""Search-candidate scoring, validation, and auditable decision logging."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional
from urllib.parse import urlparse

from paperdb.db.models import new_id, now_iso

FINANCE_CATEGORIES = {
    "q-fin.CP", "q-fin.EC", "q-fin.GN", "q-fin.MF", "q-fin.PM",
    "q-fin.PR", "q-fin.RM", "q-fin.ST", "q-fin.TR", "econ.EM",
}
FINANCE_TERMS = {
    "asset pricing", "portfolio", "stock", "equity", "factor", "alpha",
    "trading", "market microstructure", "liquidity", "volatility", "return",
    "risk model", "covariance", "momentum", "reversal", "a-share", "finance",
}
NOISE_TERMS = {
    "galaxy", "black hole", "antihydrogen", "particle physics", "radiance field",
    "human mesh", "medical imaging", "protein", "solar field", "astrophysics",
}
GITHUB_RE = re.compile(r"^https://github\.com/[^/\s]+/[^/\s#?]+/?$", re.I)


def generate_query_variants(topic: str, market: str = "China OR Chinese OR A-share") -> list[str]:
    """Generate complementary arXiv queries without literal whole-topic matching."""
    concepts = list(dict.fromkeys(
        token.casefold() for token in re.findall(r"[\w-]+", topic, re.UNICODE)
        if len(token) > 1
    ))
    if not concepts:
        return []
    clean_market = " ".join(market.split())
    quoted = [f'"{concept}"' if "-" in concept else concept for concept in concepts]
    topic_group = " OR ".join(quoted)

    technical_terms = [
        term for term in ("technical indicator", "momentum", "reversal", "trend")
        if any(part in concepts for part in term.split())
    ]
    price_volume_terms = [
        term for term in ("price", "volume", "turnover", "liquidity", "volatility", "order flow")
        if any(part in concepts for part in term.split())
    ]
    focused = list(dict.fromkeys(technical_terms + price_volume_terms))
    focus_group = " OR ".join(f'"{term}"' if " " in term else term for term in focused) or topic_group
    return [
        f'({topic_group}) AND ({clean_market}) AND (cat:q-fin.ST OR cat:q-fin.PM)',
        f'({focus_group}) AND ({clean_market}) AND (stock OR equity OR "asset pricing")',
        f'({topic_group}) AND ({clean_market}) AND (factor OR alpha OR portfolio OR risk)',
    ]


@dataclass
class CandidateAssessment:
    score: float
    decision: str
    reasons: list[str] = field(default_factory=list)


def assess_candidate(metadata, topic_terms: Optional[Iterable[str]] = None,
                     market_terms: Optional[Iterable[str]] = None,
                     threshold: float = 0.55) -> CandidateAssessment:
    """Return a transparent heuristic assessment; the agent remains final arbiter."""
    text = f"{metadata.title} {metadata.abstract or ''}".lower()
    categories = set((metadata.extra or {}).get("categories", []))
    finance_hits = sum(term in text for term in FINANCE_TERMS)
    topic = [t.lower() for t in (topic_terms or [])]
    market = [t.lower() for t in (market_terms or [])]
    noise = [term for term in NOISE_TERMS if term in text]

    finance_score = 1.0 if categories & FINANCE_CATEGORIES else min(finance_hits / 3, 1.0)
    topic_score = 1.0 if not topic else sum(t in text for t in topic) / len(topic)
    market_score = 0.5 if not market else sum(t in text for t in market) / len(market)
    metadata_score = sum(bool(v) for v in (metadata.title, metadata.authors_raw,
                                             metadata.abstract, metadata.source_url)) / 4
    score = 0.4 * finance_score + 0.3 * topic_score + 0.2 * market_score + 0.1 * metadata_score
    reasons = []
    if categories & FINANCE_CATEGORIES:
        reasons.append("finance_category")
    if noise:
        score = min(score, 0.15)
        reasons.append(f"noise:{noise[0]}")
    if finance_score == 0:
        reasons.append("no_finance_evidence")
    return CandidateAssessment(round(score, 3), "accepted" if score >= threshold else "rejected", reasons)


def validate_metadata(metadata) -> tuple[str, list[str]]:
    """Classify metadata quality without inventing missing values."""
    warnings = []
    if not metadata.authors_raw and metadata.source_type == "academic_paper":
        warnings.append("missing_authors")
    if not metadata.abstract:
        warnings.append("missing_abstract")
    if metadata.source_url:
        parsed = urlparse(metadata.source_url)
        if parsed.scheme not in {"http", "https"}:
            warnings.append("non_public_source_url")
    if metadata.github_url and not GITHUB_RE.match(metadata.github_url):
        warnings.append("invalid_github_repository_url")
    if any(x in (metadata.authors_raw or "").lower() for x in ("john doe", "张三", "李四")):
        warnings.append("placeholder_author")
    if any(x in warnings for x in ("invalid_github_repository_url", "placeholder_author")):
        return "suspicious", warnings
    return ("verified" if not warnings else "partial"), warnings


def record_candidate(conn, *, search_log_id: Optional[str], metadata, decision: str,
                     rejection_reason: Optional[str] = None,
                     relevance_score: Optional[float] = None,
                     evidence: Optional[dict] = None) -> str:
    candidate_id = new_id("c")
    conn.execute(
        """INSERT INTO search_candidates
           (id, search_log_id, source_name, source_id, title, source_url,
            decision, rejection_reason, relevance_score, evidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (candidate_id, search_log_id, metadata.source_name, metadata.source_id,
         metadata.title, metadata.source_url, decision, rejection_reason,
         relevance_score, json.dumps(evidence or {}, ensure_ascii=False), now_iso()),
    )
    return candidate_id

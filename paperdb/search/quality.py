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
STRATEGY_TERMS = {
    "strategy", "trading rule", "portfolio", "backtest", "back-test",
    "timing", "selection", "momentum", "reversal", "trend", "择时", "选股",
    "策略", "回测", "组合",
}
FACTOR_TERMS = {
    "factor", "signal", "anomaly", "alpha", "因子", "信号", "异象",
}
A_SHARE_TERMS = {
    "a-share", "a share", "a股", "china stock", "chinese stock",
    "china equity", "chinese equity", "csi 300", "csi300", "沪深300",
    "csi 500", "csi500", "中证500", "csi 1000", "中证1000",
    "上证", "深证",
}
INTRADAY_TERMS = {
    "intraday", "high-frequency", "high frequency", "tick data",
    "minute-level", "分钟", "日内", "高频",
}
OTHER_MARKET_TERMS = {
    "s&p 500", "nasdaq", "nyse", "cryptocurrency", "bitcoin", "forex",
    "hong kong stock", "h-share", "港股", "美股",
}
NOISE_TERMS = {
    "galaxy", "black hole", "antihydrogen", "particle physics", "radiance field",
    "human mesh", "medical imaging", "protein", "solar field", "astrophysics",
}
GITHUB_RE = re.compile(r"^https://github\.com/[^/\s]+/[^/\s#?]+/?$", re.I)


def generate_query_variants(topic: str, market: str = "China OR Chinese OR A-share") -> list[str]:
    """Generate A-share strategy-first queries, with a lower-priority factor lane."""
    concepts = list(dict.fromkeys(
        token.casefold() for token in re.findall(r"[\w-]+", topic, re.UNICODE)
        if len(token) > 1
    ))
    if not concepts:
        return []
    clean_market = " ".join(market.split())
    quoted = [f'"{concept}"' if "-" in concept else concept for concept in concepts]
    topic_group = " OR ".join(quoted)

    return [
        f'({topic_group}) AND ({clean_market}) AND '
        f'(strategy OR backtest OR portfolio OR timing) AND (cat:q-fin.ST OR cat:q-fin.PM)',
        f'({topic_group}) AND ({clean_market}) AND '
        f'("annualized return" OR "Sharpe ratio" OR "transaction cost")',
        f'({topic_group}) AND ({clean_market}) AND '
        f'(factor OR signal OR anomaly) AND (formula OR construction OR backtest)',
    ]


@dataclass
class CandidateAssessment:
    score: float
    decision: str
    reasons: list[str] = field(default_factory=list)
    abstract_metrics: dict = field(default_factory=dict)


def extract_performance_claims(text: str) -> dict:
    """Extract explicit abstract-level claims for prioritization, never qualification."""
    patterns = {
        "annualized_return": (
            r"(?:annuali[sz]ed return|annual return|年化收益率?|年化回报率?)"
            r"\s*(?:of|is|为|达到|达|:|：|=)?\s*(-?\d+(?:\.\d+)?)\s*%"
        ),
        "max_drawdown": (
            r"(?:maximum drawdown|max(?:imum)?\.?\s*drawdown|最大回撤)"
            r"\s*(?:of|is|为|达到|达|:|：|=)?\s*(-?\d+(?:\.\d+)?)\s*%"
        ),
        "sharpe_ratio": (
            r"(?:Sharpe(?:\s+ratio)?|夏普(?:比率|值)?)"
            r"\s*(?:of|is|为|达到|达|:|：|=)?\s*(-?\d+(?:\.\d+)?)"
        ),
    }
    claims = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            value = float(match.group(1))
            claims[name] = abs(value) if name == "max_drawdown" else value
    return claims


def assess_candidate(metadata, topic_terms: Optional[Iterable[str]] = None,
                     market_terms: Optional[Iterable[str]] = None,
                     threshold: float = 0.55) -> CandidateAssessment:
    """Return a transparent heuristic assessment; the agent remains final arbiter."""
    text = f"{metadata.title} {metadata.abstract or ''}".lower()
    categories = set((metadata.extra or {}).get("categories", []))
    topic = [t.lower() for t in (topic_terms or [])]
    requested_market = [t.lower() for t in (market_terms or [])]
    noise = [term for term in NOISE_TERMS if term in text]
    strategy_hits = [term for term in STRATEGY_TERMS if term in text]
    factor_hits = [term for term in FACTOR_TERMS if term in text]
    a_share_hits = [term for term in A_SHARE_TERMS if term in text]
    intraday_hits = [term for term in INTRADAY_TERMS if term in text]
    other_market_hits = [term for term in OTHER_MARKET_TERMS if term in text]
    metadata_market = (getattr(metadata, "market", None) or "").casefold()

    finance_score = 1.0 if categories & FINANCE_CATEGORIES else min(
        (len(strategy_hits) + len(factor_hits)) / 3, 1.0
    )
    topic_score = 1.0 if not topic else sum(t in text for t in topic) / len(topic)
    market_score = 1.0 if a_share_hits or metadata_market == "a_share" else 0.0
    if requested_market:
        market_score = max(
            market_score,
            sum(t in text for t in requested_market) / len(requested_market),
        )
    research_score = 1.0 if strategy_hits else (0.65 if factor_hits else 0.0)
    metadata_score = sum(bool(v) for v in (metadata.title, metadata.authors_raw,
                                             metadata.abstract, metadata.source_url)) / 4
    source_type = (getattr(metadata, "source_type", None) or "").casefold()
    source_score = 1.0 if source_type in {"academic_paper", "broker_report"} else 0.25
    performance_evidence = any(term in text for term in (
        "annualized return", "annual return", "sharpe ratio", "sharpe",
        "年化收益", "夏普比率", "夏普值", "transaction cost", "交易成本",
    ))
    abstract_metrics = extract_performance_claims(text)
    score = (
        0.25 * finance_score
        + 0.20 * topic_score
        + 0.30 * market_score
        + 0.20 * research_score
        + 0.03 * metadata_score
        + 0.07 * source_score
        + (0.05 if performance_evidence else 0.0)
    )
    reasons = []
    if categories & FINANCE_CATEGORIES:
        reasons.append("finance_category")
    if noise:
        score = min(score, 0.15)
        reasons.append(f"noise:{noise[0]}")
    if not a_share_hits and metadata_market != "a_share":
        reasons.append("no_a_share_evidence")
    if other_market_hits and not a_share_hits and metadata_market != "a_share":
        reasons.append(f"other_market:{other_market_hits[0]}")
    if intraday_hits:
        reasons.append(f"intraday:{intraday_hits[0]}")
    if not strategy_hits and not factor_hits:
        reasons.append("no_strategy_or_factor_evidence")
    if strategy_hits:
        reasons.append("strategy_candidate")
    elif factor_hits:
        reasons.append("factor_candidate_lower_priority")
    if performance_evidence:
        reasons.append("abstract_performance_evidence")

    hard_reject = (
        bool(noise)
        or bool(intraday_hits)
        or (not a_share_hits and metadata_market != "a_share")
        or (not strategy_hits and not factor_hits)
    )
    decision = "rejected" if hard_reject or score < threshold else "accepted"
    return CandidateAssessment(
        round(min(score, 1.0), 3), decision, reasons, abstract_metrics
    )


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

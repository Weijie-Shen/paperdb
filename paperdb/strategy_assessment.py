"""Deterministic qualification and quality scoring for A-share research.

The search stage may use metadata to discover candidates, but every decision
made here is based on evidence verified from the full text.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

from paperdb.db.models import now_iso


STRATEGY_MIN_ANNUAL_RETURN = 30.0
STRATEGY_MAX_DRAWDOWN = 10.0
STRATEGY_MIN_TEST_MONTHS = 60
ALLOWED_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "lower_frequency"}
STRATEGY_EVIDENCE_KEYS = {
    "main_strategy", "universe", "test_period", "annualized_return",
    "max_drawdown", "transaction_costs", "leverage", "frequency",
    "market_rules",
}

QUALITY_MAX_POINTS = {
    "backtest_design": 25,
    "transaction_cost_realism": 15,
    "out_of_sample_robustness": 20,
    "test_length_recency": 15,
    "clarity_reproducibility": 15,
    "source_credibility": 10,
}


@dataclass
class QualityBreakdown:
    """The six visible components of the 100-point strategy quality score."""

    backtest_design: int
    transaction_cost_realism: int
    out_of_sample_robustness: int
    test_length_recency: int
    clarity_reproducibility: int
    source_credibility: int

    def validate(self) -> None:
        for name, maximum in QUALITY_MAX_POINTS.items():
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
            if value < 0 or value > maximum:
                raise ValueError(f"{name} must be between 0 and {maximum}")

    @property
    def total(self) -> int:
        self.validate()
        return sum(asdict(self).values())


@dataclass
class StrategyEvidence:
    """Full-text facts required to qualify a strategy paper."""

    full_text_verified: bool
    a_share_scope: Optional[bool] = None
    permitted_in_a_share: Optional[bool] = None
    main_strategy: Optional[str] = None
    strategy_family: Optional[str] = None
    signal_family: Optional[str] = None
    universe: Optional[str] = None
    benchmark: Optional[str] = None
    holding_period: Optional[str] = None
    rebalance_frequency: Optional[str] = None
    long_only: Optional[bool] = None
    test_start: Optional[str] = None
    test_end: Optional[str] = None
    test_months: Optional[int] = None
    annualized_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    transaction_costs_included: Optional[bool] = None
    transaction_cost_details: Optional[str] = None
    leverage_used: Optional[bool] = None
    intraday: Optional[bool] = None
    out_of_sample: Optional[bool] = None
    turnover: Optional[str] = None
    evidence: dict = field(default_factory=dict)


@dataclass
class FactorEvidence:
    """Full-text facts required to qualify an A-share factor report."""

    full_text_verified: bool
    a_share_scope: Optional[bool] = None
    factor_formula_complete: Optional[bool] = None
    backtest_method_complete: Optional[bool] = None
    backtest_results_complete: Optional[bool] = None
    factor_formula: Optional[str] = None
    backtest_method: Optional[str] = None
    backtest_results: Optional[str] = None
    strategy_family: Optional[str] = None
    signal_family: Optional[str] = None
    universe: Optional[str] = None
    evidence: dict = field(default_factory=dict)


@dataclass
class AssessmentResult:
    research_type: str
    decision: str
    rejection_reasons: list[str]
    quality: Optional[QualityBreakdown] = None

    @property
    def quality_score(self) -> Optional[int]:
        return self.quality.total if self.quality else None


def assess_strategy(
    evidence: StrategyEvidence,
    quality: Optional[QualityBreakdown] = None,
) -> AssessmentResult:
    """Apply the agreed hard gates to a full-text strategy assessment."""
    if not evidence.full_text_verified:
        return AssessmentResult("strategy", "unverified", ["full_text_unavailable"])

    reasons: list[str] = []
    required = {
        "a_share_scope": evidence.a_share_scope,
        "permitted_in_a_share": evidence.permitted_in_a_share,
        "main_strategy": evidence.main_strategy,
        "universe": evidence.universe,
        "rebalance_frequency": evidence.rebalance_frequency,
        "test_start": evidence.test_start,
        "test_end": evidence.test_end,
        "test_months": evidence.test_months,
        "annualized_return": evidence.annualized_return,
        "max_drawdown": evidence.max_drawdown,
        "transaction_costs_included": evidence.transaction_costs_included,
        "leverage_used": evidence.leverage_used,
        "intraday": evidence.intraday,
    }
    for name, value in required.items():
        if value is None or value == "":
            reasons.append(f"missing_{name}")
    for key in sorted(STRATEGY_EVIDENCE_KEYS - set(evidence.evidence)):
        reasons.append(f"missing_evidence_{key}")

    if evidence.a_share_scope is False:
        reasons.append("not_a_share")
    if evidence.permitted_in_a_share is False:
        reasons.append("violates_a_share_rules")
    if evidence.intraday is True:
        reasons.append("intraday_strategy")
    if (
        evidence.rebalance_frequency is not None
        and evidence.rebalance_frequency not in ALLOWED_FREQUENCIES
    ):
        reasons.append("unsupported_frequency")
    if evidence.test_months is not None and evidence.test_months < STRATEGY_MIN_TEST_MONTHS:
        reasons.append("test_period_under_60_months")
    if (
        evidence.annualized_return is not None
        and evidence.annualized_return < STRATEGY_MIN_ANNUAL_RETURN
    ):
        reasons.append("annualized_return_below_30_percent")
    if (
        evidence.max_drawdown is not None
        and abs(evidence.max_drawdown) > STRATEGY_MAX_DRAWDOWN
    ):
        reasons.append("max_drawdown_above_10_percent")
    if evidence.transaction_costs_included is False:
        reasons.append("transaction_costs_not_included")
    if evidence.leverage_used is True:
        reasons.append("leverage_used")

    reasons = list(dict.fromkeys(reasons))
    if reasons:
        return AssessmentResult("strategy", "rejected", reasons)
    if quality is None:
        raise ValueError("A qualified strategy requires a quality score breakdown")
    quality.validate()
    return AssessmentResult("strategy", "qualified", [], quality)


def assess_factor_report(evidence: FactorEvidence) -> AssessmentResult:
    """Qualify factor reports on formula and backtest completeness only."""
    if not evidence.full_text_verified:
        return AssessmentResult("factor_report", "unverified", ["full_text_unavailable"])

    reasons: list[str] = []
    checks = (
        (evidence.a_share_scope, "not_a_share", "missing_a_share_scope"),
        (
            evidence.factor_formula_complete,
            "incomplete_factor_formula",
            "missing_factor_formula_evidence",
        ),
        (
            evidence.backtest_method_complete,
            "incomplete_backtest_method",
            "missing_backtest_method_evidence",
        ),
        (
            evidence.backtest_results_complete,
            "missing_backtest_results",
            "missing_backtest_results_evidence",
        ),
    )
    for value, false_reason, missing_reason in checks:
        if value is False:
            reasons.append(false_reason)
        elif value is None:
            reasons.append(missing_reason)
    for name, value in (
        ("factor_formula", evidence.factor_formula),
        ("backtest_method", evidence.backtest_method),
        ("backtest_results", evidence.backtest_results),
    ):
        if not value:
            reasons.append(f"missing_{name}_location")
    return AssessmentResult(
        "factor_report",
        "rejected" if reasons else "qualified",
        reasons,
    )


def recency_points(test_end: Optional[str], today: Optional[date] = None) -> int:
    """Return the recency portion (0/2/4) of the test-length score."""
    if not test_end:
        return 0
    try:
        end_year = int(test_end[:4])
    except (TypeError, ValueError):
        return 0
    age = (today or date.today()).year - end_year
    if age <= 3:
        return 4
    if age <= 7:
        return 2
    return 0


def save_assessment(conn, paper_id: str, evidence, result: AssessmentResult) -> None:
    """Upsert the structured assessment and synchronize paper lifecycle state."""
    evidence_dict = asdict(evidence)
    quality_dict = asdict(result.quality) if result.quality else {}
    common = {
        "paper_id": paper_id,
        "research_type": result.research_type,
        "decision": result.decision,
        "rejection_reasons": json.dumps(result.rejection_reasons, ensure_ascii=False),
        "quality_score": result.quality_score,
        "quality_breakdown": json.dumps(quality_dict, ensure_ascii=False),
        "evidence_json": json.dumps(evidence_dict.get("evidence", {}), ensure_ascii=False),
        "strategy_family": evidence_dict.get("strategy_family"),
        "signal_family": evidence_dict.get("signal_family"),
        "universe": evidence_dict.get("universe"),
        "benchmark": evidence_dict.get("benchmark"),
        "holding_period": evidence_dict.get("holding_period"),
        "rebalance_frequency": evidence_dict.get("rebalance_frequency"),
        "long_only": _sql_bool(evidence_dict.get("long_only")),
        "test_start": evidence_dict.get("test_start"),
        "test_end": evidence_dict.get("test_end"),
        "test_months": evidence_dict.get("test_months"),
        "annualized_return": evidence_dict.get("annualized_return"),
        "max_drawdown": (
            abs(evidence_dict["max_drawdown"])
            if evidence_dict.get("max_drawdown") is not None else None
        ),
        "transaction_costs_included": _sql_bool(
            evidence_dict.get("transaction_costs_included")
        ),
        "transaction_cost_details": evidence_dict.get("transaction_cost_details"),
        "leverage_used": _sql_bool(evidence_dict.get("leverage_used")),
        "intraday": _sql_bool(evidence_dict.get("intraday")),
        "a_share_rules_compliant": _sql_bool(evidence_dict.get("permitted_in_a_share")),
        "out_of_sample": _sql_bool(evidence_dict.get("out_of_sample")),
        "turnover": evidence_dict.get("turnover"),
        "factor_formula": evidence_dict.get("factor_formula"),
        "backtest_method": evidence_dict.get("backtest_method"),
        "backtest_results": evidence_dict.get("backtest_results"),
        "updated_at": now_iso(),
    }
    columns = ", ".join(common)
    values = ", ".join(f":{name}" for name in common)
    updates = ", ".join(
        f"{name}=excluded.{name}" for name in common if name != "paper_id"
    )
    conn.execute(
        f"""INSERT INTO paper_assessments ({columns}) VALUES ({values})
            ON CONFLICT(paper_id) DO UPDATE SET {updates}""",
        common,
    )
    lifecycle = "rejected_out_of_scope" if result.decision == "rejected" else "active"
    screening = "unverified" if result.decision == "unverified" else "quality_screened"
    conn.execute(
        """UPDATE papers
           SET lifecycle_status = ?, quality_screening_status = ?, updated_at = ?
           WHERE id = ?""",
        (lifecycle, screening, now_iso(), paper_id),
    )
    conn.commit()


def _sql_bool(value: Optional[bool]) -> Optional[int]:
    return None if value is None else int(value)

"""Tests for strict A-share strategy and factor-report screening."""

import json

import pytest
from click.testing import CliRunner

from paperdb.cli import main
from paperdb.db.models import Paper
from paperdb.db.schema import init_db
from paperdb.strategy_assessment import (
    FactorEvidence,
    QualityBreakdown,
    StrategyEvidence,
    assess_factor_report,
    assess_strategy,
    save_assessment,
)


def quality():
    return QualityBreakdown(
        backtest_design=20,
        transaction_cost_realism=12,
        out_of_sample_robustness=15,
        test_length_recency=13,
        clarity_reproducibility=12,
        source_credibility=8,
    )


def qualifying_strategy(**overrides):
    values = {
        "full_text_verified": True,
        "a_share_scope": True,
        "permitted_in_a_share": True,
        "main_strategy": "Author-designated baseline",
        "universe": "All A-shares",
        "rebalance_frequency": "daily",
        "test_start": "2015-01",
        "test_end": "2015-12",
        "test_months": 12,
        "annualized_return": 30.0,
        "sharpe_ratio": 1.0,
        "max_drawdown": -25.0,
        "transaction_costs_included": True,
        "leverage_used": False,
        "intraday": False,
        "evidence": {
            "main_strategy": "Section 3",
            "universe": "Section 2",
            "test_period": "Table 1",
            "annualized_return": "Table 4",
            "sharpe_ratio": "Table 4",
            "transaction_costs": "Section 3.4",
            "leverage": "Section 3.2",
            "frequency": "Section 3.3",
            "market_rules": "Section 3.4",
        },
    }
    values.update(overrides)
    return StrategyEvidence(**values)


def test_strategy_thresholds_are_inclusive_and_drawdown_is_not_a_gate():
    result = assess_strategy(qualifying_strategy(), quality())
    assert result.decision == "qualified"
    assert result.quality_score == 80


def test_strategy_requires_sharpe_value_and_evidence():
    missing_value = assess_strategy(qualifying_strategy(sharpe_ratio=None), quality())
    assert missing_value.decision == "rejected"
    assert "missing_sharpe_ratio" in missing_value.rejection_reasons

    without_location = qualifying_strategy()
    without_location.evidence.pop("sharpe_ratio")
    missing_location = assess_strategy(without_location, quality())
    assert missing_location.decision == "rejected"
    assert "missing_evidence_sharpe_ratio" in missing_location.rejection_reasons


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"a_share_scope": False}, "not_a_share"),
        ({"permitted_in_a_share": False}, "violates_a_share_rules"),
        ({"intraday": True}, "intraday_strategy"),
        ({"test_months": 11}, "test_period_under_12_months"),
        ({"annualized_return": 29.99}, "annualized_return_below_30_percent"),
        ({"sharpe_ratio": 0.99}, "sharpe_ratio_below_1"),
        ({"transaction_costs_included": False}, "transaction_costs_not_included"),
        ({"leverage_used": True}, "leverage_used"),
    ],
)
def test_strategy_hard_rejections(change, reason):
    result = assess_strategy(qualifying_strategy(**change), quality())
    assert result.decision == "rejected"
    assert reason in result.rejection_reasons
    assert result.quality_score is None


def test_strategy_records_every_applicable_rejection_reason():
    result = assess_strategy(
        qualifying_strategy(
            test_months=11,
            annualized_return=29.0,
            sharpe_ratio=0.9,
            transaction_costs_included=False,
            leverage_used=True,
        ),
        quality(),
    )
    assert result.rejection_reasons == [
        "test_period_under_12_months",
        "annualized_return_below_30_percent",
        "sharpe_ratio_below_1",
        "transaction_costs_not_included",
        "leverage_used",
    ]


def test_missing_full_text_is_unverified_not_rejected():
    result = assess_strategy(StrategyEvidence(full_text_verified=False))
    assert result.decision == "unverified"
    assert result.rejection_reasons == ["full_text_unavailable"]


def test_factor_report_uses_separate_completeness_rules():
    evidence = FactorEvidence(
        full_text_verified=True,
        a_share_scope=True,
        factor_formula_complete=True,
        backtest_method_complete=True,
        backtest_results_complete=True,
        factor_formula="Equation 2, page 7",
        backtest_method="Section 4, pages 9-11",
        backtest_results="Tables 3-5, pages 12-15",
    )
    result = assess_factor_report(evidence)
    assert result.decision == "qualified"
    assert result.quality_score is None

    result = assess_factor_report(FactorEvidence(
        full_text_verified=True,
        a_share_scope=True,
        factor_formula_complete=False,
        backtest_method_complete=True,
        backtest_results_complete=True,
        factor_formula="Equation 2, page 7",
        backtest_method="Section 4, pages 9-11",
        backtest_results="Tables 3-5, pages 12-15",
    ))
    assert result.decision == "rejected"
    assert "incomplete_factor_formula" in result.rejection_reasons


def test_assessment_is_persisted_and_rejection_updates_lifecycle(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    paper = Paper(title="A-share strategy", source_type="academic_paper")
    conn.execute(
        """INSERT INTO papers
           (id, title, source_type, access_status, quality_flag, lifecycle_status,
            created_at, updated_at)
           VALUES (:id, :title, :source_type, :access_status, :quality_flag,
                   :lifecycle_status, :created_at, :updated_at)""",
        paper.to_dict(),
    )
    result = assess_strategy(
        qualifying_strategy(annualized_return=20.0),
        quality(),
    )
    save_assessment(conn, paper.id, qualifying_strategy(annualized_return=20.0), result)
    row = conn.execute(
        "SELECT * FROM paper_assessments WHERE paper_id = ?", (paper.id,)
    ).fetchone()
    assert row["decision"] == "rejected"
    assert row["quality_score"] is None
    stored = conn.execute("SELECT * FROM papers WHERE id = ?", (paper.id,)).fetchone()
    assert stored["lifecycle_status"] == "rejected_out_of_scope"


def test_cli_refuses_full_text_qualification_without_downloaded_file(tmp_path):
    root = tmp_path / "paper_database"
    runner = CliRunner()
    assert runner.invoke(main, ["init", "--root", str(root)]).exit_code == 0
    ingest = runner.invoke(main, [
        "ingest", "metadata-only", "--root", str(root),
        "--title", "A-share strategy", "--source-type", "academic_paper",
    ])
    assert ingest.exit_code == 0
    paper_id = ingest.output.strip().split()[-1]
    payload = {
        "research_type": "strategy",
        "evidence": {
            **qualifying_strategy().__dict__,
        },
        "quality": quality().__dict__,
    }
    assessment_file = tmp_path / "assessment.json"
    assessment_file.write_text(json.dumps(payload), encoding="utf-8")
    output = runner.invoke(main, [
        "assessment", "apply", paper_id, "--file", str(assessment_file),
        "--root", str(root), "--json",
    ])
    assert output.exit_code == 0, output.output
    assert json.loads(output.output)["decision"] == "unverified"


def test_quality_component_limits_are_enforced():
    invalid = quality()
    invalid.backtest_design = 26
    with pytest.raises(ValueError, match="backtest_design"):
        invalid.validate()

---
name: paper-classify
description: Perform full-text qualification, labeling, complete rejection auditing, and strategy quality scoring for A-share strategy papers and factor reports in PaperDB.
---

# Paper Classify — Full-text Screening

Classification requires locally retained full text. If unavailable, record
`unverified`; never infer a final decision from an abstract. Read
`docs/strategy-screening.md` and `paperdb/strategy_assessment.py` before
assessing. The executable code is authoritative.

## Choose the research type

- `strategy`: a complete investment strategy or factor portfolio presented as
  the paper's primary strategy.
- `factor_report`: a factor study without a qualifying complete strategy.

For ambiguous strategies, use the authors' designated primary strategy,
otherwise the baseline/default principal specification. Never substitute the
best optimized parameter combination.

## Strategy hard gates

Verify every gate from full text:

- A-share stocks, A-share index, or corresponding index ETF.
- Trading permitted in the A-share market.
- Daily or lower frequency; no intraday trading.
- At least 12 months of testing.
- Paper-reported annualized return at least 30%.
- Paper-reported Sharpe ratio at least 1.0.
- Reported performance includes transaction costs.
- No leverage.

Thresholds are inclusive. Maximum drawdown is descriptive only and has no
qualification threshold. Out-of-sample evidence affects the quality score but
is not mandatory.

Explicit violations of T+1, price limits, suspensions, or tradability rules are
rejections. Missing friction modelling reduces quality unless unrealistic
execution materially creates the return, in which case reject.

Store every applicable rejection reason; do not use a generic catch-all.
Rejected strategies receive no quality score.

## Factor-report gates

A factor report requires A-share scope, a complete implementable formula with
variable definitions, a complete backtest method, and reported results.

Do not require IC or apply strategy duration, return, Sharpe, cost, leverage,
drawdown, or quality-score gates to factor reports.

## Evidence and labels

Record page, table, figure, or section locations for every required evidence
field. Also capture strategy/signal family, benchmark, holding and rebalance
period, turnover, out-of-sample evidence, and institution when available.

Use `references/taxonomy-quickref.md` for labels. Market, frequency, language,
and source type are columns, not labels.

Apply and inspect the assessment:

```bash
paperdb assessment apply <paper-id> --file <assessment.json>
paperdb assessment show <paper-id> --json
```

Validate the batch audit:

```bash
python skills/paper-classify/scripts/validate_audit.py <audit.json>
```

Only qualified strategies receive the visible 100-point score defined in
`docs/strategy-screening.md`.

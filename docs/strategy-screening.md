# A-share Strategy Search and Screening

PaperDB is specialized for medium- and low-frequency A-share strategy research.
It uses metadata for broad discovery, but it never treats an abstract claim as
a final qualification decision.

## Discovery

Search candidates must show evidence of:

- an A-share stock universe, A-share index, or corresponding index ETF; and
- either an investable strategy or a factor formula/backtest.

Explicit intraday research and explicit non-A-share research are rejected
during discovery. Missing performance figures in an abstract are not a reason
to reject a candidate; those figures are checked from the downloaded full text.
Strategy candidates rank above factor reports. Academic papers and broker
reports are the preferred sources.

## Full-text decisions

Every paper receives one of these decisions:

- `qualified`: all rules were verified from a locally retained full text.
- `rejected`: full text was checked and at least one mandatory rule failed.
- `unverified`: no locally retained full text was available.

### Strategy rules

The authors' primary/default strategy must satisfy every rule:

- A-share stocks, an A-share index, or the corresponding index ETF.
- Instruments and trading behaviour permitted in the A-share market.
- Daily or lower frequency; no intraday signals or repeated same-day trading.
- At least 12 months of testing.
- Paper-reported annualized return of at least 30%.
- Paper-reported Sharpe ratio of at least 1.0.
- Reported performance includes transaction costs.
- No leverage.

The primary strategy is the strategy designated by the authors, otherwise the
baseline/default principal specification. The best optimized parameter set is
not substituted for the main strategy.

Maximum drawdown may still be recorded as descriptive risk evidence, but it is
optional and has no qualification threshold.

An explicit violation of T+1, price-limit, suspension, or tradability rules is
a rejection. Missing modelling of a market friction reduces quality, unless
the unrealistic execution assumption materially creates the return, in which
case the strategy is rejected.

### Factor-report rules

A factor report does not need to satisfy strategy return, Sharpe, duration,
transaction-cost, or quality-score requirements. It must:

- use an A-share universe or index;
- give a complete, implementable factor formula;
- explain the backtest method; and
- report backtest results.

IC is not required.

## Strategy quality score

Only qualified strategies receive a score. Every component is visible:

| Component | Maximum |
|---|---:|
| Backtest design and bias control | 25 |
| Transaction-cost realism | 15 |
| Out-of-sample and robustness evidence | 20 |
| Test length and recency | 15 |
| Strategy clarity and reproducibility | 15 |
| Source and institutional credibility | 10 |
| **Total** | **100** |

Use the following anchors consistently:

- **Backtest design (25):** point-in-time inputs, survivorship and look-ahead
  controls, realistic execution, and appropriate benchmarks.
- **Transaction costs (15):** explicit cost rate, commissions and stamp duty,
  plus slippage/market impact appropriate to turnover.
- **Out-of-sample/robustness (20):** out-of-sample evidence, parameter
  sensitivity, subperiod tests, and alternative-universe/benchmark checks.
- **Length/recency (15):** longer tests score better; a test ending within
  three years receives the highest recency credit, four-to-seven years receives
  partial credit, and older tests receive none. Multiple regimes add credit.
- **Clarity/reproducibility (15):** complete signals, portfolio construction,
  data description, and fixed parameters.
- **Source credibility (10):** peer-reviewed academic work and established
  broker research receive the strongest credit, while unverifiable provenance
  receives little or none.

Out-of-sample evidence improves the score but is not mandatory.

## Rejection audit requirements

For every rejected paper, store `rejection_reasons` as a list containing every
failed hard gate found during full-text review. Do not replace specific reasons
with a generic catch-all such as `failed_strategy_gates`. A paper that fails
duration, Sharpe, and transaction-cost requirements must retain all three
reasons. Keep evidence locations for each evaluated gate whenever the report
provides them.

## Recording an assessment

Strategy example:

```json
{
  "research_type": "strategy",
  "evidence": {
    "full_text_verified": true,
    "a_share_scope": true,
    "permitted_in_a_share": true,
    "main_strategy": "Monthly multi-factor portfolio",
    "strategy_family": "multi_factor_selection",
    "signal_family": "composite",
    "universe": "CSI 500 constituents",
    "benchmark": "CSI 500",
    "holding_period": "1 month",
    "rebalance_frequency": "monthly",
    "long_only": true,
    "test_start": "2015-01",
    "test_end": "2025-12",
    "test_months": 132,
    "annualized_return": 32.4,
    "sharpe_ratio": 1.24,
    "max_drawdown": -8.7,
    "transaction_costs_included": true,
    "transaction_cost_details": "Commission, stamp duty, and 10 bps slippage",
    "leverage_used": false,
    "intraday": false,
    "out_of_sample": true,
    "turnover": "38% monthly",
    "evidence": {
      "main_strategy": "Section 3.1, page 9",
      "universe": "Section 2.2, page 6",
      "test_period": "Table 1, page 8",
      "annualized_return": "Table 6, page 18",
      "sharpe_ratio": "Table 6, page 18",
      "transaction_costs": "Section 4.2, page 14",
      "leverage": "Portfolio weights in Section 3.2, page 10",
      "frequency": "Section 3.3, page 11",
      "market_rules": "Execution assumptions in Section 4.2, page 14"
    }
  },
  "quality": {
    "backtest_design": 22,
    "transaction_cost_realism": 13,
    "out_of_sample_robustness": 16,
    "test_length_recency": 14,
    "clarity_reproducibility": 13,
    "source_credibility": 8
  }
}
```

Apply and inspect it with:

```bash
paperdb assessment apply <paper-id> --file assessment.json
paperdb assessment show <paper-id>
paperdb assessment rubric
```

Factor-report example:

```json
{
  "research_type": "factor_report",
  "evidence": {
    "full_text_verified": true,
    "a_share_scope": true,
    "factor_formula_complete": true,
    "backtest_method_complete": true,
    "backtest_results_complete": true,
    "factor_formula": "Formula and variable definitions, page 7",
    "backtest_method": "Universe, sorting, rebalance, and benchmark, pages 9-11",
    "backtest_results": "Portfolio return tables, pages 12-15",
    "signal_family": "price_volume",
    "universe": "All non-ST A-shares"
  }
}
```

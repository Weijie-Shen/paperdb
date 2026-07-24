# Agent Evaluation Run

## Metadata

- Case ID: `portfolio_risk_models`
- Date: 2026-07-15
- Agent/model: Codex / GPT-5
- Database notes: Existing classified corpus used; summaries and source metadata inspected. No download.

## Prompt Used

```text
Find papers relevant to portfolio construction or risk models for Chinese or emerging equity markets. Classify and summarize them.
```

## Queries Generated

- arXiv: `(portfolio optimization OR covariance estimation OR factor risk model) AND (China OR Chinese OR emerging equity)`
- Database: `portfolio_construction`, `risk_model`, and China-market abstract terms.

## Papers Found

| Paper ID | Title | Labels | Market | Summary/evidence | Relevant? |
|---|---|---|---|---|---|
| `p_2026_07_09_50a037f6` | Adjust factor with volatility model...China A share market | factor_research, portfolio_construction, technical_factor | a_share | Volatility adjustment plus portfolio construction | Yes |
| `p_2026_07_09_772ea595` | Empirical Study on Factors Influencing Stock Market Volatility in China | risk_model | global (should likely be a_share/China) | ARDL/PCA volatility drivers for Shanghai Composite | Yes, risk forecasting adjacent |
| `p_2026_07_09_6771cbe0` | Optimal portfolio under ratio-type periodic evaluation... | portfolio_construction, asset_pricing | global | Convex constraints and stochastic factor models | Yes, but not China-specific |
| `p_2026_07_09_e2ed6b4f` | Optimal Portfolio with Power Utility of Absolute and Relative Wealth | portfolio_construction, asset_pricing, risk_model | global | Benchmark-relative optimization | Yes, but global |

## GitHub URLs / Downloads

- GitHub URLs: none stored or claimed.
- Downloads attempted: none in this case. Existing access statuses were preserved.

## Errors And False Positives

- No obvious topic false positives.
- The China-volatility paper's `market=global` is weak metadata and should be corrected in a future cleanup.
- Only two results were directly China-related; query breadth drifted toward global optimization.

## Scoring

| Dimension | Available | Awarded | Notes |
|---|---:|---:|---|
| Relevance | 25 | 21 | All topical; only half China/emerging-specific |
| Search strategy | 15 | 12 | Correct concepts, limited live source search |
| Metadata quality | 15 | 12 | One incorrect/weak market value |
| Classification quality | 20 | 18 | Labels defensible and no old labels |
| Workflow correctness | 15 | 15 | No unnecessary ingestion/download |
| Reporting quality | 10 | 10 | Scope drift stated clearly |

Final score: **88/100**

Pass/fail: **Pass**

## Notes For Skill Improvement

- Add explicit examples for volatility forecasting versus covariance/factor risk models; the current `risk_model` boundary is underspecified.

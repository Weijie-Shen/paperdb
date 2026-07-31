# PaperDB Taxonomy Quick Reference

Assign at least one research-area label. Add factor-family labels only when the
paper studies or uses that family. Use the repository taxonomy configuration as
the authoritative list.

## Common research-area labels

| Label | Meaning |
|---|---|
| `factor_research` | Factor construction, testing, IC, or decay |
| `strategy_research` | Investment strategy or signal generation |
| `asset_pricing` | Factor models and asset-pricing theory |
| `portfolio_construction` | Optimization, constraints, or risk budgeting |
| `risk_model` | Covariance and Barra-style risk models |
| `risk_management` | VaR, stress testing, and risk controls |
| `market_microstructure` | Order books, spreads, and market impact |
| `trading_cost_execution` | TCA and execution methods |

## Common factor-family labels

Examples include `fundamental_factor`, `technical_factor`,
`sentiment_factor`, `macro_factor`, `industry_factor`, `style_factor`, and
`alternative_data_factor`. Use only labels present in the configured taxonomy.

## Rules

1. Usually assign one to three high-confidence content labels.
2. Store AI labels with their actual confidence and provenance.
3. Do not invent a label to encode a rejection.
4. Market, frequency, language, and source type belong in paper columns.
5. Classification as `strategy` or `factor_report` belongs in the assessment,
   not solely in labels.

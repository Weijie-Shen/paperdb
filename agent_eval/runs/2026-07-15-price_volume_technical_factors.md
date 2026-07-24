# Agent Evaluation Run

## Metadata

- Case ID: `price_volume_technical_factors`
- Date: 2026-07-15
- Agent/model: Codex / GPT-5
- Database notes: Evaluated existing results and added the simplified `price_and_volume_factor` label to six clearly supported papers. No download.

## Prompt Used

```text
Find papers or reports about price-volume factors, technical indicators, momentum, reversal, liquidity, turnover, or volatility signals in China equities. Classify with the simplified taxonomy.
```

## Queries Generated

- arXiv: `(technical indicator OR momentum OR reversal OR liquidity OR turnover OR volatility) AND (China OR Chinese OR A-share) AND (stock OR equity)`
- Web: `A股 量价 因子 动量 反转 流动性 换手率 波动率 研报`
- Database: labels and title/abstract inspection.

## Commands Or API Calls Used

```bash
venv/bin/paperdb query --limit 100 --json
venv/bin/paperdb label add <id> price_and_volume_factor --confidence <n> --source ai_auto
```

## Papers Found And Labels

| Paper ID | Title | Labels after run | Confidence added | Evidence | Relevant? |
|---|---|---|---:|---|---|
| `p_2026_07_09_f7b5e0be` | 日内动量脉冲与股价过度反应的精细刻画 | factor_research, technical_factor, market_microstructure, trading_cost_execution, price_and_volume_factor | 0.98 | Intraday returns, volume-surge volatility | Yes |
| `p_2026_07_09_c62b8470` | Predicting intraday jumps...using liquidity measures and technical indicators | technical_factor, market_microstructure, price_and_volume_factor | 0.98 | Shenzhen L2 liquidity/technical inputs | Yes |
| `p_2026_07_10_a7b079a9` | 信息分布均匀度，基于高频波动率的选股因子 | factor_research, technical_factor, price_and_volume_factor | 0.99 | Title explicitly says high-frequency volatility factor | Yes |
| `p_2026_07_10_b500447c` | 高频价量相关性选股因子 | factor_research, technical_factor, price_and_volume_factor | 0.99 | Title explicitly says price-volume correlation | Yes |
| `p_2026_07_10_23d00e45` | 基于高频快照数据的行为追踪因子 | factor_research, technical_factor, price_and_volume_factor | 0.96 | Snapshot/order-book factor | Yes |
| `p_2026_07_10_a30f1881` | 基于分钟线的高频选股因子 | factor_research, technical_factor, price_and_volume_factor | 0.98 | Minute-bar factor | Yes |

All additions used source `ai_auto`; market is `a_share`, frequency `intraday`, and language is consistent with source metadata for the six selected records.

## GitHub URLs / Downloads

- GitHub URLs stored: none.
- Downloads attempted: none.

## Errors And False Positives

- No obvious false positives among the six selected records.
- Existing taxonomy usage had overused `technical_factor` while omitting `price_and_volume_factor`; this run corrected that gap.
- No removed labels were used.

## Scoring

| Dimension | Available | Awarded | Notes |
|---|---:|---:|---|
| Relevance | 25 | 25 | Six direct matches |
| Search strategy | 15 | 13 | Source-appropriate terms, mainly DB reuse |
| Metadata quality | 15 | 12 | Several broker records lack authors/source URLs |
| Classification quality | 20 | 20 | Simplified taxonomy and stored confidence |
| Workflow correctness | 15 | 14 | No downloads; direct audited updates |
| Reporting quality | 10 | 8 | Clear evidence, limited external provenance |

Final score: **92/100**

Pass/fail: **Pass**

## Notes For Skill Improvement

- The classification examples should explicitly distinguish chart-rule `technical_factor` from generic price/volume `price_and_volume_factor`; many records need both, but not always.

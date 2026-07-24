# Agent Evaluation Run

## Metadata

- Case ID: `a_share_factor_search`
- Date: 2026-07-15
- Agent/model: Codex / GPT-5
- Operator: Codex
- Database snapshot or notes: Baseline 25 papers. This case used metadata previews and existing deduplicated records; no PDF was downloaded.

## Prompt Used

```text
Find 5 papers about Chinese A-share factor research. Prefer medium- or low-frequency studies. Use metadata-first ingestion and classify all new papers.
```

## Queries Generated

- arXiv: `Chinese stock asset pricing factors`
- Planned variants: `(China OR Chinese OR A-share) AND (factor OR anomaly OR alpha) AND stock`; `Chinese A-share factor model asset pricing`
- Web: `A股 因子 量化 研报`; `中国股票 异象 资产定价 因子`

## Commands Or API Calls Used

```bash
venv/bin/paperdb arxiv search 'Chinese stock asset pricing factors' --limit 10
venv/bin/paperdb query --limit 100 --json
venv/bin/paperdb download-status
```

## Papers Ingested / Found

| Paper ID | Title | Source / evidence | Relevant? | Notes |
|---|---|---|---|---|
| `p_2026_07_09_1f02ee23` | An Empirical Study of CAPM based on Chinese A-share Trading Data | arXiv 2305.04838 | Yes | A-share asset pricing |
| `p_2026_07_09_3b67d7d6` | A revised comparison between FF five-factor model and three-factor model, based on China's A-share market | arXiv | Yes | Direct factor-model comparison |
| `p_2026_07_09_50a037f6` | Adjust factor with volatility model...in China A share market | arXiv 2304.04676 | Yes | Factor construction and portfolio application |
| `p_2026_07_09_e94cf0a4` | 动量效应在A股的实证检验与改进 | BigQuant source page | Yes | Monthly momentum/reversal evidence |
| `p_2026_07_09_d46a8ca0` | A股多因子选股模型研究 | Existing local fixture | Yes | Monthly multi-factor selection; metadata provenance is weak |

## Labels Assigned / Verified

| Paper ID | Labels | Confidence | Market | Frequency | Language | Correct? |
|---|---|---:|---|---|---|---|
| `p_2026_07_09_1f02ee23` | `asset_pricing` | pre-existing | a_share | unclear | en | Yes |
| `p_2026_07_09_3b67d7d6` | `asset_pricing`, `factor_research` | pre-existing | a_share | unclear | en | Yes |
| `p_2026_07_09_50a037f6` | `factor_research`, `technical_factor`, `portfolio_construction` | pre-existing | a_share | unclear | en | Mostly; technical label is defensible from filtering method |
| `p_2026_07_09_e94cf0a4` | `factor_research`, `technical_factor` | pre-existing | a_share | monthly | zh | Yes |
| `p_2026_07_09_d46a8ca0` | `factor_research`, `value_factor` | pre-existing | a_share | monthly | zh | Yes |

## GitHub URLs / Downloads

- GitHub URLs stored: none claimed.
- Downloads attempted: none. arXiv candidates remained metadata-first/queued.

## Errors And False Positives

- Search false positives rejected: commodity pricing, defaultable-stock options, generic CAPM, and generic correlations papers.
- The database fixture record `A股多因子选股模型研究` has placeholder-looking authors and a `/tmp` source URL; it was not newly fabricated, but lowers metadata-quality confidence.
- No invalid removed labels observed in the selected set.

## Scoring

| Dimension | Available | Awarded | Notes |
|---|---:|---:|---|
| Relevance | 25 | 23 | Five relevant records; one weak fixture |
| Search strategy | 15 | 12 | Focused English query; fewer live variants than ideal |
| Metadata quality | 15 | 11 | arXiv strong; local fixture weak |
| Classification quality | 20 | 17 | Valid labels; several frequencies unclear |
| Workflow correctness | 15 | 15 | Preview/dedup, no discovery downloads |
| Reporting quality | 10 | 9 | Evidence and uncertainty explicit |

Final score: **87/100**

Pass/fail: **Pass**

## Notes For Skill Improvement

- Prefer arXiv ID or category-constrained queries; title-like free-text queries can return unrelated top hits.
- Add a fixture-quality flag so synthetic records do not silently count as high-quality discoveries.

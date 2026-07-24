# PaperDB Search Regression Evaluation

## Metadata

- Date: 2026-07-17
- Agent/model: Codex / GPT-5
- Baseline: 31 papers; 21 arXiv, 8 broker reports, 2 blog articles
- Purpose: Evaluate the improved preview, relevance, institution, and local retrieval paths without adding or downloading papers.

## Test Request

Find high-quality Chinese-equity technical/price-volume factor research using constrained arXiv discovery and the existing PaperDB corpus. Verify relevance, duplicates, institution matching, and workflow safety.

## Queries And Commands

```bash
paperdb arxiv queries 'technical price volume factors momentum reversal liquidity' --json
paperdb arxiv search '(momentum OR reversal OR liquidity OR turnover) AND (China OR Chinese OR A-share) AND (stock OR equity)' --finance-only --limit 10 --json
paperdb arxiv search 'Chinese stock momentum reversal liquidity' --limit 10 --json
paperdb arxiv search 'Chinese stock asset pricing factors' --limit 5 --json
paperdb arxiv ingest-id 2304.04676 --json
paperdb search 'A股 技术 量价 动量 反转 流动性 波动率 因子' --mode keyword --limit 20 --json
paperdb search '动量' --mode keyword --limit 20 --json
paperdb search '高频' --mode keyword --limit 20 --json
paperdb search 'factor' --mode keyword --limit 20 --json
paperdb query --label factor_research --label price_and_volume_factor --market a_share --limit 20 --json
paperdb query --institution 中金公司 --limit 10 --json
paperdb query --institution CICC --limit 10 --json
```

## Results

### Query generation

The generator returned three constrained variants, but inserted the entire six-term topic as one phrase/group. This is too literal and likely harms recall. Manual narrower variants were required.

### Live arXiv discovery

| Test | Result | Assessment |
|---|---|---|
| Finance-only technical-factor query | 0 results after 84.5s | Fail; no error recorded |
| Simplified Chinese-stock query | 0 results after 35.2s | Fail; no error recorded |
| Previously successful control query | No payload | Fail; regression/source failure |
| Exact-ID duplicate lookup | No payload | Fail; ID path also affected |

The search logs recorded `results_count=0` and `error=null`, so a source failure is indistinguishable from a valid empty result.

### Local keyword retrieval

| Query | Results | Relevant | Precision | Notes |
|---|---:|---:|---:|---|
| `动量` | 4 | 4 | 100% | Strong Chinese retrieval; all directly related to momentum/reversal/factors |
| `高频` | 5 | 5 | 100% | Strong broker-report retrieval; all high-frequency factor/microstructure reports |
| `factor` top 10 | 10 | 8 | 80% | Two pre-existing out-of-scope records ranked first: black-hole astrophysics and confirmatory factor analysis |
| Compound Chinese topic query | 0 | 0 | n/a | Poor multi-term behavior despite relevant component matches |

### Structured taxonomy retrieval

`factor_research + price_and_volume_factor + a_share` returned six records, all relevant. Precision: 100%.

The strongest records included:

- Machine Learning Enhanced Multi-Factor Quantitative Trading — A-share factors, IC contamination, explicit testing results and GitHub code.
- 日内动量脉冲与股价过度反应的精细刻画 — explicit IC and long-short results.
- 高频价量相关性选股因子 — direct price-volume factor report.
- 信息分布均匀度，基于高频波动率的选股因子 — direct volatility factor report.
- 基于分钟线的高频选股因子 — direct high-frequency stock-selection factor report.
- 基于高频快照数据的行为追踪因子 — snapshot/order-flow factor report.

### Institution identity retrieval

| Filter | Expected | Actual | Assessment |
|---|---:|---:|---|
| `中金公司` | 1 | 1 | Pass |
| `CICC` alias | 1 | 0 | Fail |

Canonical identification is stored correctly, but query-time alias input is not first resolved to its canonical identity unless that alias was the evidence originally matched.

### Workflow invariants

- Papers added: 0
- PDFs downloaded: 0
- Invalid labels added: 0
- GitHub URLs fabricated: 0
- Existing database records changed: none, except search-log evidence
- Metadata-first behavior: preserved

## False Positives And Misses

- False positives: two out-of-scope records in the top two positions for broad English `factor` search.
- Misses: compound query returned no results despite nine strong results across its component terms.
- Live-source miss: all arXiv discovery and ID controls returned no usable payload.
- Institution miss: `CICC` did not retrieve the canonical `中金公司` record.

## Scoring

| Dimension | Available | Awarded | Notes |
|---|---:|---:|---|
| Relevance | 25 | 19 | Focused/local structured precision is strong; broad ranking starts with noise |
| Search strategy | 15 | 8 | Manual variants sensible; generated variants too literal; live source failed |
| Metadata quality | 15 | 10 | Existing records usable, but many broker reports lack full metadata |
| Classification quality | 20 | 18 | Structured labels produced 6/6 relevant results |
| Workflow correctness | 15 | 7 | No contamination/downloads, but silent external failures are severe |
| Reporting quality | 10 | 10 | Queries, latency, failures, false positives, and misses recorded |

Final score: **72/100**

Pass/fail: **Fail** (below 75; primary live-source path unavailable)

## Required Improvements

1. Propagate arXiv exceptions/timeouts into `search_logs.error` and JSON/CLI output.
2. Add bounded connector timeouts and non-zero CLI exit status for source failures.
3. Split long topic input into OR-based concept groups instead of quoting it as one phrase.
4. Resolve institution filter input through the alias registry before SQL filtering.
5. Exclude or mark the known out-of-scope records so active keyword search cannot rank them.
6. Improve multi-term keyword semantics and add regression tests for component-term recall.

## Remediation Verification (2026-07-17)

All six required improvements were implemented and checked against the same live database.

| Previous failure | Verification after fix | Result |
|---|---|---|
| arXiv failure looked like zero results | Network failure returned exit code 2 with `success=false`, `error_type=network_error`, `retryable=true`, and `elapsed_ms=45` | Pass |
| Generated query quoted the entire topic | Three variants now use OR-based concept groups; the focused variant groups `technical indicator`, momentum, reversal, price, and volume | Pass |
| Compound Chinese query returned zero | `A股 量价 技术指标 动量 反转 回测` returned 5 records | Pass |
| `CICC` returned zero | Alias filter returned the canonical `中金公司` record | Pass |
| Known noise ranked in broad search | Four confirmed out-of-scope records were set to `rejected_out_of_scope`; `factor` returned 8 active results and none of those records | Pass |
| No later document-screening state | Added `quality_screening_status`; live database reports 27 `metadata_only` and 4 `full_text_available` records | Pass |

The FTS regression test also exposed and fixed an external-content schema mismatch (`paper_id/title_seg/abstract_seg` did not map to `papers.id/title/abstract`). The FTS table is now a standalone index maintained by the existing index/rebuild methods. The live FTS index was rebuilt for all 31 records.

Automated verification: **63 passed, 1 skipped**. The skip is the optional FastAPI test dependency; the two warnings are from jieba's deprecated `pkg_resources` import and do not affect retrieval behavior.

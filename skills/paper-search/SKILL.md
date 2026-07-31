---
name: paper-search
description: Discover and prioritize medium- and low-frequency A-share strategy papers and complete factor reports for PaperDB. Use for web, arXiv, broker-report, or folder-based paper searches before full-text classification.
---

# Paper Search — A-share Strategy Discovery

Use this skill for medium- or low-frequency A-share strategy research and
A-share factor reports. Prefer academic papers and established broker reports.
Read `references/search-queries.md` when constructing discovery queries.

## Discovery workflow

1. Generate several source-appropriate queries. Include A-share/Chinese-stock
   terms and strategy/backtest terms. Include annualized return, Sharpe, and
   transaction-cost terms in at least one variant. Use a separate,
   lower-priority formula/backtest query for factor reports.
2. Search structured academic sources and Chinese broker-report sources.
3. Inspect title and abstract before ingestion. Reject explicit non-A-share and
   explicit intraday results. Avoid unrelated finance and generic ML papers.
4. Use abstract metrics only to prioritize candidates; never qualify from an
   abstract. Preserve claims as unverified evidence.
5. Record exact source and download links. Never invent metadata, metrics,
   GitHub links, or PDF links.
6. Download only promising candidates. Without locally retained full text, keep
   the decision `unverified`.
7. Hand downloaded papers to `$paper-classify`.

Useful commands:

```bash
paperdb arxiv queries "<strategy topic>"
paperdb arxiv search "<query>" --finance-only --json
paperdb arxiv ingest-id <id>
paperdb download <paper-id>
paperdb assessment show <paper-id>
```

## Priority and scope

Rank strategy candidates first, then complete factor reports. Within a tier,
prefer longer and more recent tests, robustness evidence, credible provenance,
and explicit costs. Out-of-sample evidence is helpful but not required.

Accept A-share stocks, A-share indices, and corresponding index ETFs. Reject
convertible bonds, futures, options, B-shares, Hong Kong stocks, US stocks,
crypto, and mixed-market results unless a separately reported A-share result
can be assessed independently.

Accept daily, weekly, monthly, quarterly, and lower-frequency strategies.
Reject intraday bars, ticks, repeated same-day trading, and results dependent on
unavailable same-day execution.

## Reporting

Report every inspected candidate with source, source/download link, abstract
claims, download status, and current decision. Distinguish `unverified`,
`qualified`, and `rejected`.

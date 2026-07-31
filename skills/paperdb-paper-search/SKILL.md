---
name: paperdb-paper-search
description: Search, acquire, classify, fully screen, audit, ingest, label, and explicitly sync A-share strategy papers and factor reports for the PaperDB repository. Use when reviewing a folder of reports, discovering research candidates, deciding strategy or factor-report qualification, recording every rejection reason, importing qualified papers into the local PaperDB database, or uploading selected records and PDFs to Supabase.
---

# PaperDB Paper Search

Use PaperDB's deterministic assessment code for final decisions. Keep discovery,
PDF processing, deduplication, classification, and semantic search local. Sync
only explicitly selected, qualified papers to Supabase.

## Establish the project context

Work from the PaperDB repository root. Before screening, read:

- `docs/strategy-screening.md` for the complete current policy and evidence
  schema.
- `paperdb/strategy_assessment.py` for the executable qualification rules.
- `README.md` for current ingestion, assessment, label, and remote-sync commands.
- `agent_eval/cases.yaml` when changing or evaluating the policy.

Treat the code and tests as authoritative if prose has drifted. Do not design or
implement agent-search orchestration as part of this workflow.

## Search and acquire candidates

1. Inventory the supplied folder or search source without modifying source
   files.
2. Use metadata only for broad discovery and prioritization. Prefer strategy
   candidates, then factor reports; prefer academic and established broker
   research.
3. Reject explicit non-A-share and intraday material during discovery. Do not
   reject a candidate merely because its abstract omits performance metrics.
4. Retain PDFs locally and extract full text into an ignored temporary
   directory. A final `qualified` or `rejected` decision requires locally
   retained full text; otherwise use `unverified`.
5. Deduplicate before ingestion using PaperDB's normal ingestion path.

When PDF layout determines the evidence, inspect the relevant rendered pages,
tables, footnotes, and surrounding text. Do not rely only on extracted text for
ambiguous table values or execution assumptions.

## Classify before applying gates

Classify each candidate as exactly one of:

- `strategy`: an investable strategy with portfolio or trading rules and
  performance.
- `factor_report`: an implementable factor formula with a described backtest
  and results.

Do not apply strategy performance gates to factor reports.

## Apply strategy qualification

Assess the authors' primary/default strategy, not the best optimized variant.
Every hard gate must pass:

- A-share stocks, A-share index, or corresponding index ETF.
- Instruments and trading behavior permitted in the A-share market.
- Daily or lower frequency; no intraday strategy.
- Testing period of at least 12 months.
- Paper-reported annualized return of at least 30%.
- Paper-reported Sharpe ratio of at least 1.0.
- Transaction costs included in reported performance.
- No leverage.

Maximum drawdown is descriptive only and has no qualification threshold.
Out-of-sample evidence affects the quality score but is not a hard gate.

For a qualified strategy, provide all evidence fields required by
`StrategyEvidence` and a complete `QualityBreakdown`. Cite page, section, or
table locations for every required evidence key.

## Apply factor-report qualification

A factor report qualifies when full text verifies:

- an A-share universe or index;
- a complete, implementable factor formula;
- a complete backtest method; and
- reported backtest results.

IC is not mandatory. Strategy annual-return, Sharpe, duration,
transaction-cost, leverage, and quality-score gates do not apply.

## Record a complete audit

For every candidate, record its filename or source, classification, decision,
evidence locations, and notes. For every rejected paper, record
`rejection_reasons` as a list containing every failed hard gate found during
review. Never replace specific reasons with a generic catch-all.

Run the included audit validator before handoff:

```bash
python skills/paperdb-paper-search/scripts/validate_audit.py <audit.json>
```

The validator accepts either a top-level list or an object containing a
`decisions`, `results`, `papers`, or `assessments` list.

## Ingest, label, and sync

Only ingest papers selected by the user or the task's stated qualification
rule. Use `paperdb ingest from-file` for local PDFs, add labels through the
PaperDB CLI, and apply the structured assessment:

```bash
paperdb assessment apply <paper-id> --file <assessment.json>
paperdb assessment show <paper-id> --json
```

After verifying the local record, labels, assessment, and file, sync each
qualified paper explicitly:

```bash
paperdb remote sync <paper-id>
```

Local records are never bulk-copied automatically. The trusted local agent may
write using `SUPABASE_SECRET_KEY` or the legacy
`SUPABASE_SERVICE_ROLE_KEY`. Browser users use only the publishable key and
remain read-only under the project's Supabase policies.

Never print, copy into reports, or commit secret values. Do not commit `.env`,
frontend environment files, database files, downloaded PDFs, extracted text,
logs, or temporary audit artifacts.

## Verify the result

Confirm:

- every qualified paper has retained full text and specific evidence;
- every rejection contains all observed reasons;
- factor reports were not subjected to strategy gates;
- labels and assessment data are present locally;
- each intended remote paper, assessment, and PDF is anonymously readable;
- no unintended paper was uploaded; and
- the Git diff contains no credentials or generated research artifacts.

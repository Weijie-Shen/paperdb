# Agent Evaluation Run

## Metadata

- Case ID: `delayed_download_workflow`
- Date: 2026-07-15
- Agent/model: Codex / GPT-5
- Database notes: Three exact arXiv IDs ingested metadata-first, all classified and summarized before any download command.

## Prompt Used

```text
Find 3 relevant arXiv papers, ingest metadata first, classify them, and then download only the papers that are clearly relevant.
```

## Queries / Commands

```bash
venv/bin/paperdb arxiv ingest '2507.04176' --limit 1
venv/bin/paperdb arxiv ingest '2607.00581' --limit 1
venv/bin/paperdb arxiv ingest '2309.12627' --limit 1
venv/bin/paperdb info <id>
venv/bin/paperdb label add ... --confidence ... --source ai_auto
venv/bin/paperdb update ...
venv/bin/paperdb summary set ...
venv/bin/paperdb download p_2026_07_15_9fd2c0f0
venv/bin/paperdb download p_2026_07_15_8ef55e80
venv/bin/paperdb download-status
```

## Papers And Classifications

| Paper ID | Title | Labels / confidence | Market | Frequency | Access outcome |
|---|---|---|---|---|---|
| `p_2026_07_15_9fd2c0f0` | skfolio: Portfolio Optimization in Python | portfolio_construction 0.99; risk_model 0.90 | global | low_freq | downloaded; 800,224 bytes |
| `p_2026_07_15_8ef55e80` | Decision-focused Sparse Tangent Portfolio Optimization | portfolio_construction 0.99 | global | low_freq | download attempted after classification; remained queued with no log/output |
| `p_2026_07_15_757145c4` | A Quantum Computing-based System for Portfolio Optimization... | portfolio_construction 0.98 | global | low_freq | queued; not selected for a second retry |

All labels used source `ai_auto`; all three have English language metadata and stored summaries. The decision-focused paper also preserved the explicit GitHub URL `https://github.com/feuerwerksh/Diffble-card-SR`.

## Download Timing Evidence

- Each `arxiv ingest` reported `metadata-only` and queued status.
- Classification/update/summary commands completed before either `download` command.
- `download_logs` contains a success for skfolio at `2026-07-15T07:21:02+00:00`.
- The second command ran for roughly 40 seconds, returned no message, created no log entry, and left the record queued. This is a CLI observability/reliability bug, not a relevance-filter failure.

## Errors And False Positives

- Obvious false positives: 0.
- Invalid/removed labels: 0.
- One silent download no-op/failure.

## Scoring

| Dimension | Available | Awarded | Notes |
|---|---:|---:|---|
| Relevance | 25 | 25 | Three clear portfolio papers |
| Search strategy | 15 | 14 | Exact IDs avoided discovery noise |
| Metadata quality | 15 | 15 | Source and download URLs retained |
| Classification quality | 20 | 20 | Valid labels, confidence, metadata, summaries |
| Workflow correctness | 15 | 11 | Correct ordering; one silent download failure |
| Reporting quality | 10 | 10 | Timing and outcome auditable |

Final score: **95/100**

Pass/fail: **Pass** (2+ relevant ingested; at least one downloaded after classification)

## Notes For Skill Improvement

- `paperdb download` must always emit a result and create a failed log entry on timeout/no-op; silent queued state makes automation ambiguous.

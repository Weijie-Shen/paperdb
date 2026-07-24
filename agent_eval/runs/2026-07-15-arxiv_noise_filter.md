# Agent Evaluation Run

## Metadata

- Case ID: `arxiv_noise_filter`
- Date: 2026-07-15
- Agent/model: Codex / GPT-5
- Database notes: Search-only negative control. No records ingested and no PDFs downloaded.

## Prompt Used

```text
Search arXiv for factor, alpha, neural, and China-related terms, but only ingest papers relevant to quantitative finance, economics, asset pricing, or statistical methods applicable to finance.
```

## Query And Evidence

- arXiv: `factor alpha neural China` (10 results previewed)
- Accepted: `Adjust factor with volatility model using MAXFLAT low-pass filter and construct portfolio in China A share market` (already in DB, arXiv 2304.04676).
- Skipped noise examples:
  - Deep Arbitrary Polynomial Chaos Neural Network — physical/mathematical modeling, no finance link.
  - Nonlinear Force-free Field Reconstruction — solar physics; “Alpha” was an author token.
  - ALPHA antihydrogen papers — particle physics experiment.
  - Alpha Invariance in neural radiance fields — computer vision.
  - China SKA Regional Centre — radio astronomy; China was geographic only.
  - Hierarchical Attentional Hybrid Neural Networks — generic document classification.

## Commands Used

```bash
venv/bin/paperdb arxiv search 'factor alpha neural China' --limit 10
```

## Results

- Relevant new papers ingested: 0 (the only finance result was a duplicate).
- Obvious false positives ingested: 0.
- Skipped noise categories reported: physics, astronomy, computer vision, generic ML/statistics.
- Downloads attempted: 0.

## Scoring

| Dimension | Available | Awarded | Notes |
|---|---:|---:|---|
| Relevance | 25 | 25 | No noise ingested |
| Search strategy | 15 | 12 | Intentionally broad negative-control query |
| Metadata quality | 15 | 13 | Abstract snippets inspected |
| Classification quality | 20 | 18 | Duplicate already validly classified |
| Workflow correctness | 15 | 15 | Preview-only; no PDF |
| Reporting quality | 10 | 10 | Multiple skip categories documented |

Final score: **93/100**

Pass/fail: **Pass**

## Notes For Skill Improvement

- Add category filters (`q-fin`, `econ`, `stat.AP`) before broad keyword expansion to reduce obvious “alpha/factor/China” collisions.

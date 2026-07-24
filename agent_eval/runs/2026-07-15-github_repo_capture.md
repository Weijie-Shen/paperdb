# Agent Evaluation Run

## Metadata

- Case ID: `github_repo_capture`
- Date: 2026-07-15
- Agent/model: Codex / GPT-5
- Database notes: Baseline 25 papers. Three records were ingested during this case: two relevant and one arXiv search false positive.

## Prompt Used

```text
Find papers in quantitative finance, factor research, portfolio construction, or asset pricing that explicitly provide related GitHub repositories. Ingest metadata and preserve the GitHub links.
```

## Queries Generated

- Web: `site:arxiv.org quantitative finance portfolio optimization GitHub code`
- Web: `site:arxiv.org factor investing GitHub repository`
- Web: `site:arxiv.org/abs FinRL GitHub quantitative finance paper`
- arXiv IDs: `2507.07107`, `2011.09607`

## Commands Or API Calls Used

```bash
venv/bin/paperdb arxiv ingest 'Machine Learning Enhanced Multi-Factor Quantitative Trading' --limit 1
venv/bin/paperdb arxiv ingest '2507.07107' --limit 1
venv/bin/paperdb arxiv ingest '2011.09607' --limit 1
venv/bin/paperdb info <id>
venv/bin/paperdb label add ... --confidence ... --source ai_auto
venv/bin/paperdb update ...
venv/bin/paperdb summary set ...
```

## Papers Ingested

| Paper ID | Title | Source | Relevant? | Notes |
|---|---|---|---|---|
| `p_2026_07_15_b2db4424` | Machine Learning Enhanced Multi-Factor Quantitative Trading... | [arXiv 2507.07107](https://arxiv.org/abs/2507.07107) | Yes | A-share factor engineering and portfolio optimization |
| `p_2026_07_15_acffcc78` | FinRL: A Deep Reinforcement Learning Library... | [arXiv 2011.09607](https://arxiv.org/abs/2011.09607) | Yes | Quant trading and allocation framework |
| `p_2026_07_15_4adf0b50` | Changing Data Sources in the Age of Machine Learning for Official Statistics | arXiv 2306.04338 | No | Incorrect result from title-like ingest query; left unlabeled for auditability |

## Labels Assigned

| Paper ID | Labels | Confidence | Market | Frequency | Language | Correct? |
|---|---|---|---|---|---|---|
| `p_2026_07_15_b2db4424` | factor_research; portfolio_construction; price_and_volume_factor | 0.97; 0.94; 0.91 | a_share | daily | en | Yes |
| `p_2026_07_15_acffcc78` | strategy_research; portfolio_construction | 0.96; 0.88 | global | unclear | en | Yes |

## GitHub URLs Stored

| Paper ID | GitHub URL | Evidence Location | Correct? |
|---|---|---|---|
| `p_2026_07_15_b2db4424` | https://github.com/initial-d/ml-quant-trading | arXiv abstract text explicitly says code is available there | Yes |
| `p_2026_07_15_acffcc78` | https://github.com/AI4Finance-LLC/FinRL-Library | arXiv abstract explicitly provides repository | Yes |

## Downloads

- None attempted; both relevant records remained queued with arXiv `download_url` retained.

## Errors And False Positives

- One obvious false positive was ingested by the free-text title query. ArXiv ID queries worked correctly.
- Fabricated GitHub URLs: 0.
- Papers without explicit GitHub evidence were not assigned a URL.
- The irrelevant new record remains unclassified, so the overall case violates the global completion invariant even though GitHub-link acceptance passes.

## Scoring

| Dimension | Available | Awarded | Notes |
|---|---:|---:|---|
| Relevance | 25 | 17 | 2/3 relevant; one obvious false positive |
| Search strategy | 15 | 13 | Strong web discovery and ID fallback |
| Metadata quality | 15 | 15 | Two links automatically and explicitly captured |
| Classification quality | 20 | 16 | Relevant papers strong; false positive intentionally unlabeled |
| Workflow correctness | 15 | 11 | Metadata-first, but unsafe title-query ingest |
| Reporting quality | 10 | 10 | Error and provenance fully reported |

Final score: **82/100**

Pass/fail: **Pass on case minimum; global invariant warning**

## Notes For Skill Improvement

- The skill should require `arxiv search`/dry-run followed by ID-based ingest, because `arxiv ingest <title>` can store an unrelated relevance-ranked result.

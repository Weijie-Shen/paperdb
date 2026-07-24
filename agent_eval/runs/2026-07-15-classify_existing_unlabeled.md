# Agent Evaluation Run

## Metadata

- Case ID: `classify_existing_unlabeled`
- Date: 2026-07-15
- Agent/model: Codex / GPT-5
- Database notes: Queried once in JSON. Exactly four unlabeled records existed; all were outside the finance taxonomy.

## Prompt Used

```text
Classify up to 10 existing unlabeled papers in the database. Use the current research-area labels and optional factor-family labels only. Preserve confidence scores.
```

## Commands Or API Calls Used

```bash
venv/bin/paperdb query --limit 100 --json
venv/bin/paperdb info <each-unlabeled-id>
```

## Unlabeled Papers Inspected

| Paper ID | Title | Classification decision | Evidence |
|---|---|---|---|
| `p_2026_07_09_bf7f7de6` | Fast SAM 3D Body... | Skip; no valid label | Computer vision / human mesh recovery |
| `p_2026_07_09_07e265a3` | Host Galaxy Demographics...Black-hole Binaries... | Skip; no valid label | Astrophysics / gravitational waves |
| `p_2026_07_09_663a8798` | Constraints for non-zero secondary loadings in confirmatory factor analysis | Skip; no valid label | General psychometrics/statistics, not financially applicable from metadata |
| `p_2026_07_15_4adf0b50` | Changing Data Sources...Official Statistics | Skip; no valid label | Official statistics / ML data-source drift |

## Labels Assigned

- Classified count: **0**.
- Invalid labels: **0**.
- No manual review queue was created.
- No finance label was fabricated merely to satisfy the count target.

## Errors And False Positives

- The fixture cannot meet `classified_count: 5`: only four unlabeled records exist, and none defensibly fits the allowed taxonomy.
- This reveals a test-design conflict between “classify existing unlabeled” and “every ingested paper needs a finance research-area label.” Noise records need a rejection/archive state outside the research taxonomy.

## Scoring

| Dimension | Available | Awarded | Notes |
|---|---:|---:|---|
| Relevance | 25 | 10 | Correctly rejected all noise, but no target papers available |
| Search strategy | 15 | 15 | Single JSON query as required |
| Metadata quality | 15 | 15 | Inspected full title/abstract evidence |
| Classification quality | 20 | 5 | No invalid assignments, but minimum count unmet |
| Workflow correctness | 15 | 15 | No review queue or fabricated labels |
| Reporting quality | 10 | 10 | Fixture limitation explicit |

Final score: **70/100**

Pass/fail: **Fail** (minimum classified count 5 not met)

## Notes For Skill Improvement

- Add a supported `rejected_out_of_scope` lifecycle state, or ensure this test begins with at least five unlabeled finance papers.

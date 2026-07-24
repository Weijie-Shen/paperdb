# PaperDB Agent Evaluation

This directory defines manual/semiautomated tests for Hermes or an AgentMatrix
agent using the PaperDB skills.

These are not normal unit tests. They evaluate whether the AI workflow can
search, filter, ingest, classify, summarize, and preserve links correctly.

## How To Run

1. Start from a known PaperDB database state.
2. Give the agent one case prompt from `cases.yaml`.
3. Let the agent use the PaperDB skills and CLI/API tools.
4. Record the run in `runs/<date>-<case-id>.md`.
5. Score the output using the rubric in `cases.yaml`.

## Minimum Acceptance Criteria

- At least 70% of ingested papers are relevant to the case.
- 100% of ingested papers receive at least one valid research-area label.
- 0 invalid old/removed labels are used.
- arXiv workflows are metadata-first unless the case explicitly asks to download.
- GitHub URLs are stored only when explicitly specified by the paper, abstract page, PDF, or project page.
- Label confidence values are preserved.
- No manual label-review queue is created or required.

## Useful Verification Commands

```bash
paperdb query --limit 100 --json
paperdb label list
paperdb download-status
paperdb search "A-share factor" --json
```


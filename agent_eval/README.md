# PaperDB Agent Evaluation

This directory defines manual/semiautomated tests for Hermes or an AgentMatrix
agent using the PaperDB skills.

These are not normal unit tests. They evaluate whether the AI workflow finds
A-share strategy/factor research, downloads promising candidates, verifies
full-text evidence, applies hard gates correctly, and preserves an audit trail.

## How To Run

1. Start from a known PaperDB database state.
2. Give the agent one case prompt from `cases.yaml`.
3. Let the agent use the PaperDB skills and CLI tools.
4. Record the run in `runs/<date>-<case-id>.md`.
5. Score the output using the rubric in `cases.yaml`.

## Minimum Acceptance Criteria

- No paper is qualified without downloaded full text.
- Every strategy hard gate is supported by page/table/section evidence.
- Thresholds are inclusive: annualized return >=30%, drawdown magnitude <=10%.
- Rejected papers have reasons and no score.
- Qualified strategies show all six score components.
- Factor reports use their separate completeness rules.

## Useful Verification Commands

```bash
paperdb query --limit 100 --json
paperdb query --research-type strategy --decision qualified --json
paperdb query --research-type factor_report --decision qualified --json
paperdb assessment show <paper-id> --json
```

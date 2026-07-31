---
name: paper-summarize
description: Generate concise, evidence-faithful summaries for PaperDB papers without copying abstracts or inventing findings.
---

# Paper Summarize

Find missing summaries with:

```bash
paperdb summary list --missing
```

Read the retained paper when available. Write three to five sentences covering
the research question, method, principal findings, and relevance to A-share
quant research. Use the paper's language and aim for 80–200 words.

Do not copy the abstract verbatim. Do not infer unstated findings. When only
metadata is available, state that limitation and summarize only verified
scope. Skip clearly irrelevant material.

Store and verify:

```bash
paperdb summary set <paper-id> "<summary>"
paperdb info <paper-id>
```

A summary is descriptive and never substitutes for `$paper-classify` evidence.

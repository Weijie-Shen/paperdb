---
name: paper-review
description: Handle PaperDB label and assessment review checks. The former label-review queue is deprecated; use confidence-scored labels and paper-classify.
---

# Paper Review — Deprecated Queue

PaperDB no longer uses a separate label-review queue. Use `$paper-classify` for
full-text decisions and assign labels directly with honest confidence and
provenance. Do not turn uncertainty into a fake categorical label.

Useful checks:

```bash
paperdb label list
paperdb query --json --limit 100
paperdb info <paper-id>
paperdb assessment show <paper-id> --json
```

Review remote publication separately: anonymous users may read active papers
and stored PDFs, while only the trusted local agent may write.

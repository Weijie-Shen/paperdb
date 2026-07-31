---
name: paper-import
description: Bulk-import local PDFs into PaperDB with verified metadata, deduplication, labels, summaries, full-text assessment, and optional explicit Supabase sync.
---

# Paper Import — Local Bulk Import

Use for PDFs supplied in a folder or placed in
`paper_database/files/_inbox/`. Do not modify or delete source files.

## Workflow

1. Inventory PDFs and detect obvious duplicates.
2. Extract text locally. Inspect the cover and relevant rendered pages when
   layout matters or extraction is ambiguous.
3. Determine title, authors, institution, date, source type, language, market,
   abstract, and only links explicitly present in the paper.
4. Present proposed metadata when the task has not already authorized importing
   all papers meeting a stated rule.
5. Import through `paperdb ingest from-file`; rely on PaperDB's dedup checks.
6. Add confidence-scored labels, write a faithful summary, and invoke
   `$paper-classify`.
7. Sync only papers explicitly selected for remote publication.

Example:

```bash
paperdb ingest from-file \
  --title "<verified title>" \
  --authors "<author one>; <author two>" \
  --institution "<institution>" \
  --source-type broker_report \
  --date "YYYY-MM-DD" \
  --market a_share \
  --language zh \
  --file "<source.pdf>"
```

Use semicolons between authors. Never invent metadata or repository links.
Scanned or garbled PDFs require OCR or manual verification; do not fabricate
missing fields. Use the full returned paper ID for subsequent operations.

After local verification:

```bash
paperdb info <paper-id>
paperdb assessment show <paper-id> --json
paperdb remote sync <paper-id>
```

The remote command requires local trusted credentials. Never expose or commit
them. Original PDFs, local database files, parsed text, logs, and temporary
assessment JSON remain untracked.

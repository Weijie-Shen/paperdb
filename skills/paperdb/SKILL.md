---
name: paperdb
description: Operate the PaperDB repository, including local search and ingestion, deterministic paper assessment, Supabase publication, and the anonymous paper-browser frontend.
---

# PaperDB

PaperDB discovers, downloads, classifies, and organizes Chinese A-share
quantitative research.

## Current boundary

- Local SQLite and files support discovery, PDF parsing, deduplication,
  scheduled searches, semantic search, classification, and ingestion.
- Supabase Postgres and Storage provide the remotely browsable paper library.
- The frontend reads active metadata and PDFs anonymously with the publishable
  key.
- Only the trusted local agent writes remotely, using a secret key and an
  explicit `paperdb remote sync <paper-id>` operation.
- Agent-search orchestration remains out of scope.

Never commit `.env`, keys, databases, PDFs, parsed content, logs, or temporary
audit files.

## Common commands

| Command | Purpose |
|---|---|
| `paperdb init` | Initialize local database and file store |
| `paperdb ingest from-file ...` | Import a local paper |
| `paperdb arxiv search "<query>" --finance-only` | Preview arXiv candidates |
| `paperdb download <paper-id>` | Download a selected paper |
| `paperdb search "<query>"` | Local hybrid search |
| `paperdb query ...` | Structured local filtering |
| `paperdb label add <paper-id> <label>` | Add a label |
| `paperdb assessment apply <paper-id> --file <json>` | Apply screening |
| `paperdb remote status` | Verify Supabase Data API access |
| `paperdb remote sync <paper-id>` | Explicitly publish one local paper |

Use `$paper-search`, `$paper-import`, `$paper-classify`, and
`$paper-summarize` for their specialized workflows.

## Architecture

Read `references/search-architecture.md` for local keyword/vector search,
`README.md` for the current remote workflow, and
`supabase/migrations/*.sql` for the remote schema, policies, RPCs, and Storage
setup. Treat repository code and tests as authoritative when older design notes
differ.

PaperDB uses metadata and content hashes plus fuzzy detection for deduplication.
Fuzzy matches are reviewed and never auto-merged. Content labels carry
confidence and provenance; market, language, frequency, and source type remain
metadata columns.

# PaperDB — AI-Driven Paper Search Engine for Quant Research

PaperDB is an AI-operated research intake system that discovers, downloads, classifies, and organizes papers and broker reports for quantitative finance research, with a primary focus on **Chinese A-share markets** (medium- to low-frequency trading).

It has two operation modes:
- **CLI mode**: direct commands for `init`, `ingest`, `search`, `query`, `stats`
- **AI mode**: Hermes skills that orchestrate full discovery → classification → summarization workflows

## Installation

```bash
cd paperdb
pip install -e ".[dev]"

# For arXiv connector:
pip install arxiv

# For Chinese search (FTS5 + jieba):
pip install jieba

# For vector/semantic search (optional):
pip install sentence-transformers
```

## Quick Start

```bash
# 1. Initialize the database and file store
paperdb init
# Creates: paper_database/{db/, files/, config/, index/, logs/}

# 2. Import a paper from a local file
paperdb ingest from-file \
  --title "A股多因子选股模型研究" \
  --authors "张三; 李四" \
  --institution "华泰证券" \
  --source-type broker_report \
  --date "2025-03" \
  --market a_share \
  --language zh \
  --github-url "https://github.com/example/a-share-factor-model" \
  --file ~/Downloads/report.pdf

# 3. Import a paper as metadata-only (no file)
paperdb ingest metadata-only \
  --title "深度学习在A股因子挖掘中的应用" \
  --authors "王五" \
  --institution "中金公司" \
  --source-type broker_report \
  --date "2025-06" \
  --market a_share \
  --language zh \
  --access-status manual_required \
  --access-notes "Choice终端可获取"

# 4. Preview arXiv, inspect abstracts, then ingest selected IDs
paperdb arxiv search "factor timing China A-share" --finance-only --limit 10
paperdb arxiv ingest-id 2501.12345

# 5. Download selected/missing PDFs after filtering/classification
paperdb download <paper_id>
paperdb download-missing --source-name arxiv --limit 5

# 6. Build search indexes
paperdb index rebuild

# 7. Search your database
paperdb search "因子选股"
paperdb search "portfolio optimization" --source-type academic_paper
paperdb search "深度学习" --market a_share
```

## CLI Reference

### Database Management

| Command | Description |
|---|---|
| `paperdb init` | Create database, file structure, and default config files |
| `paperdb stats` | Summary statistics (by type, market, access, labels, institution) |
| `paperdb stats --json` | JSON output for scripting |

### Ingestion

| Command | Description |
|---|---|
| `paperdb ingest from-file --title ... --file ...` | Import a local PDF/DOCX/HTML file |
| `paperdb ingest from-url --title ... --url ...` | Download and ingest from a URL |
| `paperdb ingest metadata-only --title ...` | Store metadata without downloading (paywalled papers) |
| `paperdb ingest ... --github-url <url>` | Store a related GitHub repository URL when specified by the paper |
| `paperdb ingest ... --download-url <url>` | Store a direct file URL for delayed downloads |
| `paperdb ingest ... --json` | JSON output |

Duplicate detection is automatic — re-ingesting the same paper reports `duplicate`.

### arXiv

| Command | Description |
|---|---|
| `paperdb arxiv search <query> --finance-only` | Preview category-constrained results with relevance scores and DB status |
| `paperdb arxiv queries <topic>` | Generate three complementary market-constrained query variants |
| `paperdb arxiv ingest-id <arxiv-id>` | Safely ingest one exact arXiv record, metadata-first |
| `paperdb arxiv ingest <query> --limit 10` | Preview ranked results; does not write without `--confirm` |
| `paperdb arxiv ingest <query> --confirm` | Explicitly ingest search-ranked results with dedup |
| `paperdb arxiv ingest <query> --confirm --download` | Explicit immediate-download workflow |
| `paperdb arxiv ingest <query> --dry-run` | Preview results without ingesting |
| `paperdb arxiv harvest --since last_week` | Harvest recent papers from quant categories |

### Delayed Downloads

| Command | Description |
|---|---|
| `paperdb download <paper_id>` | Download one existing metadata-only paper |
| `paperdb download-missing --source-name arxiv --limit 10` | Download queued/failed papers later |
| `paperdb download-status` | Show download backlog and recent attempts |

Every network attempt is logged before it starts and finishes as `success`,
`error`, or `timeout`, including retryability. This prevents silent download
failures from being mistaken for success.

### Search & Query

| Command | Description |
|---|---|
| `paperdb search <query>` | Hybrid search (FTS5 keyword + vector if available) |
| `paperdb search <query> --mode keyword` | FTS5 keyword-only search |
| `paperdb search <query> --source-type broker_report --market a_share` | Filtered search |
| `paperdb search <query> --json` | JSON output |
| `paperdb query` | SQL-like structured filtering |
| `paperdb query --label factor_research --label price_and_volume_factor` | Papers with ALL specified labels |
| `paperdb query --search "动量" --institution 华泰` | Keyword + institution filter |
| `paperdb query --date-from 2025-01 --date-to 2025-12` | Date range filter |
| `paperdb reject <paper-id> --reason ...` | Mark a record out of scope without assigning a fake finance label |
| `paperdb query --include-rejected` | Include rejected and archived records in an audit query |
| `paperdb search-metrics` | Show returned/inspected/accepted/rejected counts and inspection yield |
| `paperdb institution-refresh` | Recompute canonical institution identities and watchlist priorities |

**Difference**: `search` uses FTS5/vector ranking with relevance scores. `query` uses SQL `WHERE` clauses with no ranking.

### Index Management

| Command | Description |
|---|---|
| `paperdb index rebuild` | Rebuild FTS5 + vector indexes from the papers table |
| `paperdb index rebuild --fts-only` | Rebuild FTS5 keyword index only |
| `paperdb index rebuild --vector-only` | Rebuild vector index only |

Run `paperdb index rebuild` after bulk imports or whenever search results seem stale.

### Labels & Classification

| Command | Description |
|---|---|
| `paperdb label add <paper_id> <label> --confidence 0.92 --source ai_auto` | Assign a label |
| `paperdb label add <paper_id> <label> --confidence 0.72` | Assign a lower-confidence label |
| `paperdb label list` | List all labels by frequency |
| `paperdb label list --source ai_auto` | List AI-assigned labels |

### Summaries

| Command | Description |
|---|---|
| `paperdb summary set <paper_id> "<text>"` | Store AI-generated summary |
| `paperdb summary list` | List all papers with summary status |
| `paperdb summary list --missing` | Papers without summaries |

### Paper Management

| Command | Description |
|---|---|
| `paperdb info <paper_id>` | Full paper details: metadata, labels, authors, file path, summary |
| `paperdb update <paper_id> --market a_share --language zh` | Update metadata fields |
| `paperdb update <paper_id> --github-url <url>` | Set or correct the related GitHub repository URL |
| `paperdb update <paper_id> --download-url <url>` | Set or correct a delayed-download file URL |
| `paperdb update <paper_id> --ai-summary "..."` | Update AI summary |

## API Server

The API is the shared backend surface for the future frontend and AI agent tools.
It currently runs on the same local PaperDB SQLite database and file store.

Install and run:

```bash
pip install -e ".[api]"
paperdb-api
```

By default it serves `http://127.0.0.1:8000`. Override with:

```bash
PAPERDB_API_PORT=8017 paperdb-api
```

Core endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Check API and database availability |
| `GET /papers` | List/filter papers by label, market, source, access status, GitHub, file status |
| `GET /papers/{id}` | Paper detail with labels and authors |
| `POST /papers` | Metadata-only paper creation |
| `PATCH /papers/{id}` | Update deterministic metadata fields |
| `POST /papers/{id}/labels` | Add AI/user labels with confidence |
| `POST /arxiv/search` | Search arXiv metadata without ingesting |
| `POST /arxiv/ingest` | Metadata-first arXiv ingest; `download=false` by default |
| `POST /papers/{id}/download` | Download one queued paper |
| `POST /downloads/missing` | Download queued/failed papers in batch |
| `GET /downloads/status` | Download backlog and recent attempts |

Interactive docs are available at `/docs` when the server is running.

### Local browser UI

Start the API, then run the frontend in a second terminal:

```bash
paperdb-api
cd frontend
npm install
npm run dev
```

Open the local URL printed by the frontend. It connects to
`http://127.0.0.1:8000` by default. To use a different API address, set
`NEXT_PUBLIC_PAPERDB_API_URL` before starting the frontend.

## AI-Driven Operation (Hermes Skills)

PaperDB is designed to be operated by AI. Four active Hermes skills automate the research workflow:

Agent workflow quality is tracked separately in `agent_eval/`. Use
`agent_eval/cases.yaml` and `agent_eval/run_template.md` to test whether the
AI can search, filter, classify, preserve GitHub/download links, and avoid
old label/review behavior before wiring the workflow into AgentMatrix.

### 1. `paper-search` — Full Discovery Workflow

Say: **"Find papers on machine learning factor construction in A-shares"**

The AI will:
1. Generate source-appropriate queries (English for arXiv, Chinese for web)
2. Preview category-constrained arXiv results and inspect titles/abstracts
3. Search the web via `web_search` + `web_extract` for broker reports, SSRN, blogs
4. Record rejected candidates, then ingest approved arXiv IDs with dedup
5. Classify with taxonomy labels and confidence scores
6. Generate structured summaries
7. Download selected/missing PDFs later with `paperdb download` or `paperdb download-missing`
8. Report results with source, labels, access status

Search queries and candidate decisions are stored in `search_logs` and
`search_candidates`. GitHub links discovered in arXiv metadata retain their
evidence type and evidence page. Active-paper queries exclude records marked
`rejected_out_of_scope` by default.

When arXiv supplies optional author affiliations, PaperDB stores them on the
matching `paper_authors` rows with `arxiv_api` provenance. If the paper-level
`institution` is empty, it is populated with the ordered unique affiliations;
multiple universities are preserved rather than reduced to a guessed primary.

### 2. `paper-classify` — Batch Classification

Say: **"Classify unlabeled papers"**

The AI will:
- Find papers without labels
- Read title + abstract for each
- Assign taxonomy labels with confidence scores
- Keep lower-confidence labels in the database with their confidence value
- Set market, frequency, language metadata

### 3. `paper-summarize` — Summary Generation

Say: **"Summarize my papers"**

The AI will:
- Find papers without summaries
- Generate 3-5 sentence structured summaries covering: research question, methodology, findings, A-share relevance
- Store via `paperdb summary set`

### 4. `paper-import` — Bulk Import from Inbox

Say: **"Import papers from the inbox"** (after dropping PDFs into `paper_database/files/_inbox/`)

The AI will:
- Read each PDF (using pymupdf)
- Extract title, authors, institution, date
- Propose labels and ask for confirmation
- Import via `paperdb ingest from-file`
- Classify and summarize

## Configuration

Config files live in `paper_database/config/` and are created by `paperdb init`.

### `taxonomy.yaml` — Label Definitions

All available classification labels with descriptions. The AI uses these to classify papers. Edit to add or remove labels.

### `watchlist.yaml` — Priority Institutions

```yaml
institutions:
  - name: "华泰证券"
    priority: 1           # 1 = highest
    aliases: ["华泰证券股份有限公司", "Huatai Securities", "HTSC"]
    research_teams: ["金融工程组", "策略组"]
  - name: "国泰君安"
    priority: 1
  - name: "中信证券"
    priority: 2
  # ... add more
```

Priority scores affect search ranking. They do not force label review.
Institution matching uses normalized canonical names and aliases against
paper-level institutions and per-author affiliations; author names are never
used as affiliation evidence. Matches retain the raw value, matched alias,
source, confidence, configured rank, and descending sort score. Run
`paperdb institution-refresh` after changing aliases or priorities.

### `sources.yaml` — Connector Configuration

Enable/disable source connectors and configure search categories.

## File Storage Layout

```
paper_database/
├── files/
│   ├── raw_pdf/           # Downloaded/imported PDFs (named by paper ID)
│   ├── raw_html/          # Scraped HTML pages
│   ├── raw_docx/          # Imported DOCX files
│   ├── parsed/text/       # Extracted plain text
│   ├── parsed/tables/     # Extracted tables (JSON)
│   ├── summaries/         # AI-generated summaries (markdown)
│   ├── notes/             # User annotations
│   └── _inbox/            # Drop PDFs here for bulk import
├── db/
│   └── papers.sqlite      # All metadata, labels, authors, logs
├── index/
│   └── vector/            # BGE embeddings (if installed)
├── config/
│   ├── taxonomy.yaml
│   ├── sources.yaml
│   ├── watchlist.yaml
│   └── embedding.yaml
└── logs/
```

## Deduplication

PaperDB uses three-layer dedup, all automatic:

1. **Exact metadata hash** — SHA-256 of normalized title + authors + date. Catches same paper from different URLs.
2. **Content hash** — SHA-256 of downloaded PDF. Catches identical files.
3. **Fuzzy matching** — Title word overlap + author overlap + date proximity. Flags suspected duplicates for review.

Re-ingesting the same paper returns `duplicate` — no duplicate rows are created.

## Search Architecture

- **FTS5 + jieba**: Chinese text is segmented with jieba before indexing. English passes through unchanged. Supports prefix matching and boolean queries.
- **Vector (BGE)**: Optional semantic search using `BAAI/bge-large-zh-v1.5`. Falls back gracefully if `sentence-transformers` is not installed.
- **Hybrid (RRF)**: Reciprocal Rank Fusion combines both result lists for best relevance.

Normal search excludes papers whose lifecycle is rejected or archived. Institution filters resolve configured aliases (for example, `CICC`) to canonical watchlist identities. The `quality_screening_status` field tracks whether a record is `metadata_only`, has `full_text_available`, has been `quality_screened`, or has `insufficient_evidence`; downloading a paper advances it to `full_text_available` automatically.

## Taxonomy Labels

PaperDB uses a small flat taxonomy with two dimensions. Assign at least one research-area label to every paper. Add a factor-family label only when the paper studies or uses that kind of factor.

**Research area labels**:
`factor_research`, `strategy_research`, `asset_pricing`, `portfolio_construction`, `risk_model`, `market_microstructure`, `trading_cost_execution`

**Optional factor-family labels**:
`technical_factor`, `value_factor`, `price_and_volume_factor`

## Project Structure

```
paperdb/
├── paperdb/
│   ├── cli.py              # CLI commands (click)
│   ├── ingest.py           # Ingestion pipeline + dedup
│   ├── db/
│   │   ├── schema.py       # SQLite DDL, WAL mode, 7 tables
│   │   └── models.py       # Dataclasses (Paper, Label, Author, etc.)
│   ├── search/
│   │   ├── keyword.py      # FTS5 + jieba keyword search
│   │   ├── vector.py       # BGE embeddings (optional)
│   │   ├── hybrid.py       # RRF fusion
│   │   └── indexer.py      # Index build/rebuild
│   ├── connectors/
│   │   ├── base.py         # BaseConnector protocol
│   │   └── arxiv_connector.py  # arXiv search + download
│   ├── storage/
│   │   └── file_store.py   # File management (raw, parsed, summaries)
│   ├── config/
│   │   └── loader.py       # YAML config loading with defaults
│   └── utils/
│       └── hashing.py      # Title/author normalization, content hashing
├── tests/
│   ├── test_core.py        # 30 tests (schema, models, hashing, file store, ingest)
│   └── test_arxiv.py       # 10 tests (connector, ingest bridge)
└── PROJECT_PLAN.md         # Full architecture design document
```

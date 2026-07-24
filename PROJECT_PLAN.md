# PaperDB — AI-Driven Paper Search Engine for Chinese A-Share Quant Research

## Project Overview

PaperDB is an AI-driven research intake system that discovers, downloads, classifies, and organizes papers and broker reports for quantitative finance research, with a primary focus on Chinese A-share markets (medium- to low-frequency trading).

The system is designed around a core principle: **the AI (Hermes) is the explorer; the Python code is the infrastructure.** The AI uses its general web tools (`web_search`, `web_extract`, browser) to hunt for papers from any source, while structured connectors (arXiv, Choice, Semantic Scholar) serve as optimized shortcuts for frequently-used sources. The AI generates search queries, evaluates relevance, classifies papers, and generates summaries. The code handles database operations, file management, deduplication, and API calls.

## Target Sources

| Source Type | Examples | Access Strategy |
|---|---|---|
| Academic papers | arXiv, SSRN, Semantic Scholar, journal sites | Metadata-first intake; delayed download when selected |
| Broker research reports | 华泰证券, 国泰君安, 中信证券, 中金公司, 海通证券, 广发证券, 招商证券, 申万宏源, 兴业证券, 东方证券, 天风证券, 方正证券 | Download via Choice terminal API; metadata-only for non-Choice sources; mark `manual_required` with access notes when unavailable |
| White papers / industry reports | Research institutions, industry associations | Auto-download when public; metadata-only otherwise |
| Blogs / articles | 知乎, 雪球, 微信公众号 | Metadata + source link; mark as `blog_article` |
| Manual uploads | User-provided PDFs | Full ingestion via `paperdb import` or watched folder |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AI EXPLORER (Hermes)                      │
│  Search query generation · Relevance evaluation             │
│  Classification · Summarization · Workflow orchestration    │
├─────────────────────────────────────────────────────────────┤
│                    TOOLS                                     │
│  web_search · web_extract · browser · paperdb CLI           │
├─────────────────────────────────────────────────────────────┤
│                    PAPERDB PACKAGE                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │Connectors│ │ Search   │ │ Classify │ │ Storage      │  │
│  │          │ │          │ │          │ │              │  │
│  │ arxiv    │ │ FTS5 +   │ │ Taxonomy │ │ File store   │  │
│  │ choice   │ │ jieba    │ │ AI label │ │ raw/parsed/  │  │
│  │ semantic │ │ Vector   │ │ pipeline │ │ summaries    │  │
│  │ scholar  │ │ (BGE/Hyb)│ │          │ │              │  │
│  │ generic  │ │          │ │          │ │              │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    STORAGE                                   │
│  SQLite (WAL mode) · File system · Vector index (ChromaDB) │
└─────────────────────────────────────────────────────────────┘
```

## Database Schema

### `papers` — One row per unique research object

```sql
CREATE TABLE papers (
    id                  TEXT PRIMARY KEY,    -- UUID, e.g. "p_2026_07_08_a1b2c3"
    title               TEXT NOT NULL,
    title_en            TEXT,                -- English title if available
    authors_raw         TEXT,                -- Semicolon-delimited as found in source
    institution         TEXT,                -- Broker / university / research org
    source_type         TEXT NOT NULL,       -- academic_paper | broker_report | white_paper | blog_article | manual_upload | other
    source_name         TEXT,                -- e.g. "华泰证券", "arXiv", "Semantic Scholar", "web"
    source_url          TEXT,
    download_url        TEXT,                -- Direct PDF/file URL for delayed downloads when known
    github_url          TEXT,                -- Related GitHub/code repository URL if explicitly specified
    publication_date    TEXT,                -- ISO date or year-month
    market              TEXT,                -- a_share | hk_equity | us_equity | global | futures | fixed_income | multi_asset
    frequency           TEXT,                -- intraday | daily | weekly | monthly | quarterly | event_driven | low_freq | unclear
    language            TEXT,                -- zh | en | bilingual | other
    abstract            TEXT,
    abstract_en         TEXT,
    ai_summary          TEXT,                -- LLM-generated summary
    file_path           TEXT,                -- Relative path under files/, NULL if not downloaded
    file_format         TEXT,                -- pdf | html | docx | txt | none
    access_status       TEXT NOT NULL,       -- downloaded | manual_required | paywalled | not_available | queued | failed
    access_notes        TEXT,                -- Why manual, license notes, terminal name, report serial number
    content_hash        TEXT,                -- SHA-256 of downloaded file (exact dedup)
    metadata_hash       TEXT,                -- SHA-256 of title+authors+date (fuzzy dedup signal)
    priority_score      INTEGER DEFAULT 0,   -- Computed from watchlist at ingestion; recomputable
    quality_flag        TEXT DEFAULT 'ok',   -- ok | needs_review | duplicate_suspected | broken
    ingestion_batch     TEXT,                -- Batch ID for tracking bulk imports
    added_by            TEXT REFERENCES users(id),
    reviewed_by         TEXT REFERENCES users(id),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX idx_papers_metadata_hash ON papers(metadata_hash);
CREATE INDEX idx_papers_access_status ON papers(access_status);
CREATE INDEX idx_papers_source_type ON papers(source_type);
CREATE INDEX idx_papers_download_url ON papers(download_url);
CREATE INDEX idx_papers_priority ON papers(priority_score DESC);
CREATE INDEX idx_papers_added_by ON papers(added_by);
```

### `paper_labels` — Many-to-many taxonomy

```sql
CREATE TABLE paper_labels (
    id          TEXT PRIMARY KEY,
    paper_id    TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,              -- e.g. "factor_research", "price_and_volume_factor"
    confidence  REAL,                        -- 0-1 for AI-classified labels
    source      TEXT NOT NULL,              -- label source, default ai_auto; optional audit metadata
    added_by    TEXT REFERENCES users(id),
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_labels_paper ON paper_labels(paper_id);
CREATE INDEX idx_labels_label ON paper_labels(label);
CREATE INDEX idx_labels_source ON paper_labels(source);
```

### `paper_authors` — Normalized author list

```sql
CREATE TABLE paper_authors (
    id                 TEXT PRIMARY KEY,
    paper_id           TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    author_name        TEXT NOT NULL,
    author_name_en     TEXT,
    institution        TEXT,                -- Per-author affiliation
    is_corresponding   INTEGER DEFAULT 0,
    author_order       INTEGER NOT NULL
);

CREATE INDEX idx_authors_paper ON paper_authors(paper_id);
CREATE INDEX idx_authors_name ON paper_authors(author_name);
```

### `users` — Multi-user support

```sql
CREATE TABLE users (
    id          TEXT PRIMARY KEY,           -- e.g. "u_zhangsan"
    name        TEXT NOT NULL,
    email       TEXT,
    role        TEXT DEFAULT 'researcher',  -- admin | researcher | viewer
    created_at  TEXT NOT NULL
);
```

### `user_annotations` — Private per-user notes and ratings

```sql
CREATE TABLE user_annotations (
    id          TEXT PRIMARY KEY,
    paper_id    TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users(id),
    note_type   TEXT NOT NULL,              -- comment | rating | tag | reading_status
    content     TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX idx_annotations_paper_user ON user_annotations(paper_id, user_id);
```

### `search_logs` — Audit trail

```sql
CREATE TABLE search_logs (
    id              TEXT PRIMARY KEY,
    source_name     TEXT,
    query           TEXT,
    query_type      TEXT,                   -- keyword | semantic | author_search | browse | web_exploratory
    results_count   INTEGER,
    new_papers      INTEGER,
    searched_at     TEXT NOT NULL,
    error           TEXT
);
```

### `download_logs`

```sql
CREATE TABLE download_logs (
    id            TEXT PRIMARY KEY,
    paper_id      TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    attempt_at    TEXT NOT NULL,
    status        TEXT NOT NULL,            -- success | blocked | timeout | paywall | error
    http_status   INTEGER,
    error_detail  TEXT,
    file_size     INTEGER
);

CREATE INDEX idx_downloads_paper ON download_logs(paper_id);
```

## Source Connectors

### Design Principle

Connectors are **optional accelerators**, not boundaries. The AI can always use `web_search` + `web_extract` + `paperdb ingest --from-url` to ingest papers from any source. Connectors exist for sources we hit frequently and where structured APIs provide cleaner, faster results.

### Base Interface

```python
class BaseConnector:
    name: str
    source_type: str              # academic_paper | broker_report | white_paper | blog_article
    can_search: bool
    can_download: bool
    can_harvest: bool
    rate_limit_rps: float
    requires_auth: bool
    auth_type: str | None         # api_key | cookie | terminal | institutional | None

    def search(self, query: str, limit: int = 50) -> list[PaperMetadata]: ...
    def harvest(self, since: str, limit: int = 50) -> list[PaperMetadata]: ...
    def download(self, metadata: PaperMetadata) -> DownloadResult: ...
```

### Planned Connectors

| Connector | Search | Download | Notes |
|---|---|---|---|
| `arxiv` | ✓ API | ✓ OA papers | q-fin, stat, cs categories |
| `choice` | ✓ API | ✓ (if account permits) | Choice终端 Python SDK |
| `semantic_scholar` | ✓ API | ✓ OA papers | Free API, good for academic |
| `ssrn` | ✗ (web_search) | ✗ | Metadata via scraping; paywall for many |
| `generic_web` | ✗ (AI uses web_search) | ✗ (attempts via URL) | Universal fallback path |

### Download Fallback Chain

For any paper the AI discovers, the default workflow stores metadata first and
persists any direct `download_url`. Slow file transfer is a later step:

1. AI searches and filters metadata without waiting on PDFs
2. Selected papers stay `access_status='queued'` while `download_url` is retained
3. `paperdb download <paper_id>` or `paperdb download-missing` runs connector/direct downloads later
4. Failed downloads update `access_status='failed'` and write `download_logs`
5. Papers without usable access remain `manual_required`, `paywalled`, or `not_available`

## Taxonomy / Labeling

### Content Labels (flat, multi-label)

Assign at least one research-area label to every paper. Add a factor-family label only when the paper studies or uses that factor type.

```yaml
# Research Area
factor_research:        "因子研究 — factor construction, testing, IC analysis, decay"
strategy_research:      "策略研究 — investment strategies, signal generation"
asset_pricing:          "资产定价 — factor models, CAPM, APT, SDF"
portfolio_construction: "组合构建 — optimization, constraints, risk budgeting"
risk_model:             "风险模型 — covariance estimation, Barra-style"
market_microstructure:  "市场微观结构 — order book, bid-ask spread, market impact"
trading_cost_execution: "交易成本/执行 — TCA, VWAP/TWAP, optimal execution"

# Optional Factor Family
technical_factor:       "技术因子 — indicators, technical signals, momentum/reversal patterns"
value_factor:           "价值因子 — valuation, profitability, quality, growth, fundamental value signals"
price_and_volume_factor:"价量因子 — price/volume behavior, turnover, liquidity, volatility, order-flow signals"
```

### AI Labeling Pipeline

1. **Ingestion**: Paper metadata stored → `ai_summary` generated
2. **AI Classification**: LLM assigns labels + confidence scores → stored as `source='ai_auto'`
3. **Confidence retention**: Lower-confidence labels remain queryable with their confidence values; there is no required label review queue

## Deduplication

### Three-Layer Strategy

1. **Exact hash match** (`content_hash`): SHA-256 of downloaded file. Catches identical files. Fast, indexed.
2. **Metadata hash match** (`metadata_hash`): SHA-256 of normalized(title + authors + date). Catches same paper from different URLs.
3. **Fuzzy dedup** (AI-assisted): When hashes don't match but title/author/date are close, flag as `quality_flag='duplicate_suspected'` for AI review. Never auto-merge.

### Fuzzy Dedup Algorithm

```python
def find_candidates(metadata: PaperMetadata) -> list[str]:
    # Step 1: Exact hashes (fast, indexed)
    if match := db.query("SELECT id FROM papers WHERE metadata_hash = ?", metadata.metadata_hash):
        return match

    # Step 2: Normalized title fuzzy match
    normalized = normalize_title(metadata.title)  # lowercase, strip punctuation
    candidates = db.query("""
        SELECT id, title, authors_raw, publication_date
        FROM papers WHERE normalized_title LIKE ?
    """, f"%{normalized[:30]}%")

    # Step 3: Author overlap + date proximity
    scored = []
    for c in candidates:
        author_score = author_jaccard(metadata.authors, c.authors)
        date_diff = abs(month_diff(metadata.date, c.date))
        if author_score > 0.6 and date_diff < 12:
            scored.append((c.id, author_score + (1.0 - date_diff/12)))

    return [id for id, _ in sorted(scored, key=lambda x: -x[1])[:5]]
```

## Search Architecture

### Dual-Index: Keyword + Vector

**Keyword search:**
- SQLite FTS5 with custom jieba tokenizer for Chinese word segmentation
- Supports exact phrase matching, boolean queries
- Returns papers matching specific terms ("动量因子", "Barra 风险模型")

**Vector (semantic) search:**
- Embedding model: `BAAI/bge-large-zh-v1.5` (local-first, best Chinese performance)
- Fallback: OpenAI `text-embedding-3-small` (configurable)
- Vector store: ChromaDB or FAISS (per-user local index, rebuilt from shared DB)
- Returns papers semantically similar to natural language queries

**Hybrid search:**
- Reciprocal Rank Fusion (RRF) combines keyword + vector results
- Filterable by: labels, market, frequency, source_type, institution, date range, priority_score, language

### Embedding Backend (Pluggable)

```yaml
# config/embedding.yaml
backend: "local"  # or "openai"
local:
  model: "BAAI/bge-large-zh-v1.5"
  device: "auto"
openai:
  model: "text-embedding-3-small"
  api_key: "${OPENAI_API_KEY}"
```

## Watchlist / Priority System

Institutions and authors with higher priority receive higher `priority_score` in the database. The score is computed at ingestion time from the watchlist config and can be recomputed at any time.

```yaml
# config/watchlist.yaml
institutions:
  - name: "华泰证券"
    priority: 1
    research_teams: ["金融工程组", "策略组"]

  - name: "国泰君安"
    priority: 1
    research_teams: ["金融工程组"]

  - name: "中金公司"
    priority: 1

  - name: "中信证券"
    priority: 2

  - name: "海通证券"
    priority: 2

  - name: "广发证券"
    priority: 2

  - name: "招商证券"
    priority: 2

  - name: "申万宏源"
    priority: 2

  - name: "兴业证券"
    priority: 3

  - name: "东方证券"
    priority: 3

  - name: "天风证券"
    priority: 3

  - name: "方正证券"
    priority: 3

authors: []
# Authors to be populated as the database grows and notable researchers are identified
```

## File Storage Layout

```
paper_database/
├── files/
│   ├── raw_pdf/           # Original PDFs, named by paper ID
│   ├── raw_html/          # Scraped HTML pages
│   ├── raw_docx/          # Uploaded DOCX files
│   ├── parsed/
│   │   ├── text/          # Extracted plain text (UTF-8)
│   │   ├── tables/        # Extracted tables as CSV/JSON
│   │   └── metadata/      # Extracted frontmatter as JSON
│   ├── notes/             # User annotations (markdown)
│   ├── summaries/         # AI-generated summaries (markdown)
│   └── _inbox/            # Watched folder for manual imports
├── db/
│   └── papers.sqlite      # WAL mode, multi-user ready
├── index/
│   └── vector/            # ChromaDB/FAISS index files (per-user local)
├── config/
│   ├── sources.yaml       # Connector configurations
│   ├── taxonomy.yaml      # Label definitions
│   ├── watchlist.yaml     # Priority institutions/authors
│   └── embedding.yaml     # Embedding backend config
└── logs/
    ├── search.log
    └── ingest.log
```

## Multi-User Design

- **SQLite with WAL mode**: Concurrent reads, serialized writes. Sufficient for 2-5 researchers.
- **Shared DB on NAS/network drive**: All Hermes instances connect to the same SQLite file.
- **Shared labels**: The taxonomy is the team's shared research language.
- **Private annotations**: Personal notes, ratings, and reading status are per-user.
- **Per-user vector index**: Each user maintains their own local vector index, rebuilt from the shared DB when new papers are added.
- **Migration path**: Schema is Postgres-compatible from day one. If team grows beyond 5, migrate to Postgres.

## Hermes Skills

```
~/.hermes/skills/
├── paper-search/          # AI generates search queries, searches across sources, ingests results
├── paper-classify/        # Batch AI classification with confidence scores
├── paper-summarize/       # AI summary generation for ingested papers
├── paper-import/          # Hermes-assisted bulk import from watched folder
└── paper-digest/          # Cron job: periodic digest of newly discovered papers
```

## Search Workflow (Daily Use)

When the user asks the AI to find papers on a topic:

1. **AI generates per-source queries** — translates the research intent into source-appropriate search terms (Chinese for CNKI/Choice, English for arXiv, mixed for web)
2. **Structured search** — uses connectors for known sources (arXiv, Choice, Semantic Scholar)
3. **Exploratory search** — uses `web_search()` + `web_extract()` to find papers from any source
4. **Deduplication** — checks all results against existing database (hash + fuzzy)
5. **Ingestion** — metadata-first `paperdb ingest` for each new paper; keeps direct `download_url` when available
6. **Classification** — AI assigns taxonomy labels with confidence scores
7. **Summarization** — AI generates structured summary for each paper
8. **Delayed downloads** — AI/user runs `paperdb download` or `paperdb download-missing` for selected papers
9. **Reporting** — presents results: new papers found, sources, labels, confidence, access status

## Implementation Phases

### Phase 1 — Core Infrastructure
- Database schema (SQLite, all tables above)
- File store initialization
- `paperdb` CLI skeleton: `init`, `ingest --from-url`, `ingest --from-file`, `query`, `stats`
- Base connector interface
- Configuration file loading (sources, taxonomy, watchlist)
- Unit tests for schema and file store

### Phase 2 — First Structured Connector (arXiv)
- arXiv API connector (search + delayed download)
- Deduplication (exact hash + metadata hash)
- Metadata-first ingestion pipeline for arXiv papers
- AI classification integration (Hermes skill: `paper-classify`)
- `paperdb index rebuild` for vector index

### Phase 3 — Choice Connector
- Choice终端 Python SDK integration
- Search + download broker reports
- Broker report metadata extraction
- Enhanced access tracking (Choice-specific access notes)

### Phase 4 — Search & Retrieval
- FTS5 + jieba tokenizer for Chinese keyword search
- Vector index with BGE embeddings
- Hybrid search (RRF)
- `paperdb search` with filters (labels, market, date range, etc.)
- `paperdb query` for structured SQL-like filtering

### Phase 5 — Hermes Skills
- `paper-search`: Full AI-driven search workflow
- `paper-classify`: Batch classification with confidence scores
- `paper-summarize`: Summary generation
- `paper-import`: Hermes-assisted bulk import (Option C)
- Agent evaluation suite in `agent_eval/` to test search, filtering, classification, link capture, and delayed-download behavior before AgentMatrix integration

### Phase 6 — Automation
- `paper-digest` cron job: weekly scan of configured sources
- Watched folder monitoring for manual imports
- Watchlist-based priority notifications
- Statistics and coverage reporting

### Phase 7 — API + Frontend Foundation
- FastAPI backend over the existing PaperDB database and file store
- Deterministic endpoints for papers, labels, arXiv metadata-first ingest, and delayed downloads
- OpenAPI schema for frontend development and AI tool calling
- Keep AI as the explorer/classifier; keep API as the reliable state-changing backend
- Future migration target: replace SQLite access with Supabase/Postgres repositories behind the same API contract

## Key Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Database | SQLite (WAL mode) | Portable, zero-config, sufficient for <10K papers |
| Embeddings | BGE-large-zh-v1.5 (local) | Best Chinese retrieval quality, zero API cost |
| Vector store | ChromaDB (per-user local) | Avoids concurrent access issues; easy rebuild from shared DB |
| Tokenizer | jieba | Best Python CJK tokenizer; integrates with FTS5 |
| Dedup | Hash + fuzzy duplicate flagging | Never auto-merge; flag suspicious duplicates |
| Labels | Flat, multi-label, with confidence + source tracking | Queryable, traceable, no required review queue |
| Priority | Computed integer score from watchlist | Recomputable; sortable; filterable |
| Search | Hybrid (keyword + vector, RRF) | Best of both: exact match + semantic understanding |
| Multi-user | Shared SQLite + private annotations + per-user vector index | Simple, works for small teams; clear Postgres migration path |
| API | FastAPI over the local service layer | Produces OpenAPI docs, supports frontend and AI tool calls, easy migration path |
| AI role | Explorer + classifier + summarizer | Uses general web tools; not limited to coded connectors |
| Code role | Infrastructure + reliability | DB, files, APIs, dedup, tokenization — deterministic operations |

## Out of Scope (Future Phases)

- Factor reproduction pipeline integration (separate system, fed by paper DB)
- Detailed reproduction-oriented labels (formula clarity, data availability, implementation difficulty)
- Full-text Chinese PDF parsing with table extraction (Phase 2+)
- Automatic broker website scraping (use Choice API + web_search instead)
- External API-based services (local-first design)

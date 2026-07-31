# PaperDB Search Architecture

Local PaperDB search combines two independent rankings with Reciprocal Rank
Fusion.

## Keyword search

`paperdb/search/keyword.py` uses SQLite FTS5. Chinese text is segmented with
jieba before indexing and queries are segmented the same way. If the FTS table
does not exist, search falls back to SQL `LIKE`.

## Vector search

`paperdb/search/vector.py` uses a local embedding model when its optional
dependencies are installed. Embeddings remain local. If vector search is
unavailable, PaperDB degrades to keyword-only behavior.

## Hybrid search

`paperdb/search/hybrid.py` merges keyword and vector ranks with RRF and then
applies PaperDB filters. It prefers verified qualified strategies, followed by
qualified factor reports, without hiding other candidates.

```bash
paperdb search "因子选股 A股"
paperdb search "因子" --mode keyword
paperdb search "portfolio optimization" --mode vector
paperdb search "因子" --source-type broker_report --json
paperdb index rebuild
```

This local semantic search is separate from the Supabase Data API. Supabase
provides remote relational filtering and text-oriented browser access; it does
not currently replace PaperDB's local vector-search workflow.

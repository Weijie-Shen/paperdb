"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const SUPABASE_URL = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").replace(/\/$/, "");
const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "";
const STORAGE_BUCKET = "paper-files";

type Facet = { value: string; count: number };
type Label = { label: string; confidence?: number; source?: string };
type FileState = { status: string; available: boolean; format?: string; storage_path?: string };
type Paper = {
  id: string; title: string; title_en?: string; authors_raw?: string; institution?: string;
  source_type: string; source_name?: string; source_url?: string; github_url?: string;
  publication_date?: string; market?: string; frequency?: string; language?: string;
  abstract?: string; abstract_en?: string; ai_summary?: string; priority_score: number;
  metadata_quality?: string; quality_screening_status?: string; labels: Label[];
  access_status: string; access_notes?: string; file: FileState; download_status: string;
  authors?: Array<{ author_name: string; institution?: string; is_corresponding: number }>;
  institutions?: Array<{ canonical_name: string; confidence: number; match_source: string }>;
  download_logs?: Array<{ attempt_at: string; status: string; error_detail?: string; file_size?: number }>;
};
type Facets = Record<string, Facet[]>;

const statusNames: Record<string, string> = {
  downloaded: "Ready", queued: "Queued", failed: "Failed", manual_required: "Manual",
  paywalled: "Paywalled", not_available: "Unavailable", missing: "File missing",
};

function pretty(value?: string) {
  if (!value) return "—";
  return value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function Status({ value }: { value: string }) {
  return <span className={`status status-${value}`}>{statusNames[value] || pretty(value)}</span>;
}

async function supabaseRpc<T>(name: string, body: Record<string, unknown> = {}): Promise<T> {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    throw new Error("Supabase frontend settings are missing.");
  }
  const response = await fetch(`${SUPABASE_URL}/rest/v1/rpc/${name}`, {
    method: "POST",
    headers: {
      apikey: SUPABASE_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Supabase request failed (${response.status}).`);
  return response.json();
}

async function openStorageFile(path: string) {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  const response = await fetch(`${SUPABASE_URL}/storage/v1/object/${STORAGE_BUCKET}/${encoded}`, {
    headers: { apikey: SUPABASE_KEY },
  });
  if (!response.ok) throw new Error("The stored paper could not be downloaded.");
  const objectUrl = URL.createObjectURL(await response.blob());
  window.open(objectUrl, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

export default function Home() {
  const [facets, setFacets] = useState<Facets>({});
  const [papers, setPapers] = useState<Paper[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [draftQuery, setDraftQuery] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [selectedLabels, setSelectedLabels] = useState<string[]>([]);
  const [selected, setSelected] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadPapers = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const data = await supabaseRpc<{ results: Paper[]; total: number }>("search_papers", {
        query_text: query || null,
        filter_market: filters.market || null,
        filter_frequency: filters.frequency || null,
        filter_source_type: filters.source_type || null,
        filter_access_status: filters.access_status || null,
        filter_institution: filters.institution || null,
        filter_labels: selectedLabels.length ? selectedLabels : null,
        page_limit: 100,
        page_offset: 0,
      });
      setPapers(data.results); setTotal(data.total);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not reach the API.");
    } finally { setLoading(false); }
  }, [filters, query, selectedLabels]);

  useEffect(() => {
    supabaseRpc<Facets>("paper_facets").then(setFacets)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load the remote library."));
  }, []);
  useEffect(() => {
    const request = window.setTimeout(loadPapers, 0);
    return () => window.clearTimeout(request);
  }, [loadPapers]);

  const activeFilterCount = Object.values(filters).filter(Boolean).length + selectedLabels.length;
  const labelOptions = useMemo(() => facets.labels || [], [facets]);

  function search(event: FormEvent) { event.preventDefault(); setQuery(draftQuery.trim()); }
  function setFilter(name: string, value: string) { setFilters((old) => ({ ...old, [name]: value })); }
  function toggleLabel(value: string) {
    setSelectedLabels((old) => old.includes(value) ? old.filter((x) => x !== value) : [...old, value]);
  }
  async function openPaper(id: string) {
    try {
      const paper = await supabaseRpc<Paper | null>("paper_detail", { paper_id: id });
      if (paper) setSelected(paper);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load paper details.");
    }
  }

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="PaperDB home"><span className="brand-mark">P</span>PaperDB</a>
        <div className="library-state"><span className="pulse" /> Supabase library · {total} active papers</div>
      </header>

      <section className="hero" id="top">
        <div>
          <p className="eyebrow">Research, made navigable</p>
          <h1>Your quantitative research library.</h1>
          <p className="hero-copy">Browse papers, trace evidence, and open remotely stored research from the shared PaperDB library.</p>
        </div>
        <div className="hero-stat"><strong>{total}</strong><span>active papers</span></div>
      </section>

      <form className="searchbar" onSubmit={search}>
        <span aria-hidden="true">⌕</span>
        <input value={draftQuery} onChange={(e) => setDraftQuery(e.target.value)} placeholder="Search titles, abstracts, and summaries" aria-label="Search papers" />
        {query && <button type="button" className="quiet" onClick={() => { setDraftQuery(""); setQuery(""); }}>Clear</button>}
        <button type="submit">Search</button>
      </form>

      <div className="workspace">
        <aside className="filters">
          <div className="filter-heading"><h2>Filters</h2>{activeFilterCount > 0 && <button className="quiet" onClick={() => { setFilters({}); setSelectedLabels([]); }}>Reset {activeFilterCount}</button>}</div>
          {[["market", "Market"], ["frequency", "Frequency"], ["source_type", "Source"], ["access_status", "Download"]].map(([key, label]) => (
            <label className="select-field" key={key}><span>{label}</span>
              <select value={filters[key] || ""} onChange={(e) => setFilter(key, e.target.value)}>
                <option value="">All</option>{(facets[key] || []).map((item) => <option key={item.value} value={item.value}>{pretty(item.value)} ({item.count})</option>)}
              </select>
            </label>
          ))}
          <div className="label-filter"><span>Labels</span>
            <div className="label-options">{labelOptions.map((item) => <button key={item.value} className={selectedLabels.includes(item.value) ? "label-choice active" : "label-choice"} onClick={() => toggleLabel(item.value)}><span>{pretty(item.value)}</span><small>{item.count}</small></button>)}</div>
          </div>
        </aside>

        <section className="results" aria-live="polite">
          <div className="results-heading"><div><p className="eyebrow">Library index</p><h2>{loading ? "Loading papers…" : `${total} paper${total === 1 ? "" : "s"}`}</h2></div><span>Priority · newest first</span></div>
          {error && <div className="notice"><strong>API unavailable</strong><span>{error}</span></div>}
          {!loading && !error && papers.length === 0 && <div className="empty"><strong>No papers found</strong><span>Try removing a filter or using a broader search.</span></div>}
          <div className="paper-list">{papers.map((paper) => (
            <article className="paper-card" key={paper.id} onClick={() => openPaper(paper.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && openPaper(paper.id)}>
              <div className="paper-main">
                <div className="paper-meta"><span>{paper.publication_date?.slice(0, 4) || "Undated"}</span><span>{pretty(paper.source_name || paper.source_type)}</span>{paper.market && <span>{pretty(paper.market)}</span>}</div>
                <h3>{paper.title}</h3>
                <p>{paper.authors_raw || paper.institution || "Author information unavailable"}</p>
                <div className="chips">{paper.labels.slice(0, 4).map((label) => <span key={label.label}>{pretty(label.label)}</span>)}{paper.labels.length > 4 && <span>+{paper.labels.length - 4}</span>}</div>
              </div>
              <div className="paper-side"><Status value={paper.download_status} />{paper.priority_score > 0 && <span className="priority">Priority {paper.priority_score}</span>}<span className="open">View paper <b>→</b></span></div>
            </article>
          ))}</div>
        </section>
      </div>

      {selected && <div className="overlay" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && setSelected(null)}>
        <article className="detail" role="dialog" aria-modal="true" aria-labelledby="detail-title">
          <button className="close" onClick={() => setSelected(null)} aria-label="Close paper detail">×</button>
          <div className="detail-meta"><Status value={selected.download_status} /><span>{selected.publication_date || "Undated"}</span><span>{pretty(selected.source_name || selected.source_type)}</span></div>
          <h2 id="detail-title">{selected.title}</h2>{selected.title_en && <p className="translated">{selected.title_en}</p>}
          <p className="byline">{selected.authors?.map((a) => a.author_name).join(", ") || selected.authors_raw || selected.institution || "Unknown authors"}</p>
          <div className="detail-actions">
            {selected.file.available && selected.file.storage_path && <button className="primary" onClick={() => openStorageFile(selected.file.storage_path!).catch((reason) => setError(reason.message))}>Open stored file</button>}
            {selected.source_url && <a href={selected.source_url} target="_blank">Source ↗</a>}
            {selected.github_url && <a href={selected.github_url} target="_blank">GitHub ↗</a>}
          </div>
          <div className="detail-grid">
            <section><h3>Abstract</h3><p>{selected.abstract || "No abstract has been stored for this paper."}</p></section>
            <aside>
              <h3>Paper record</h3>
              <dl><div><dt>Market</dt><dd>{pretty(selected.market)}</dd></div><div><dt>Frequency</dt><dd>{pretty(selected.frequency)}</dd></div><div><dt>Language</dt><dd>{pretty(selected.language)}</dd></div><div><dt>Metadata</dt><dd>{pretty(selected.metadata_quality)}</dd></div></dl>
              <h3>Labels</h3><div className="chips">{selected.labels.map((label) => <span key={label.label}>{pretty(label.label)}</span>)}</div>
              {(selected.institutions?.length || 0) > 0 && <><h3>Institutions</h3>{selected.institutions?.map((item) => <p className="institution" key={item.canonical_name}>{item.canonical_name}<small>{Math.round(item.confidence * 100)}% match</small></p>)}</>}
            </aside>
          </div>
          {selected.ai_summary && <section className="summary"><p className="eyebrow">Generated summary</p><p>{selected.ai_summary}</p></section>}
          <section className="download-history"><h3>Download status</h3><p>{selected.access_notes || `${statusNames[selected.download_status] || pretty(selected.download_status)}${selected.file.available ? ` · ${selected.file.format?.toUpperCase() || "file"} stored remotely` : ""}`}</p>{selected.download_logs?.map((log) => <div className="attempt" key={log.attempt_at}><span>{new Date(log.attempt_at).toLocaleString()}</span><strong>{pretty(log.status)}</strong><span>{log.error_detail}</span></div>)}</section>
        </article>
      </div>}
    </main>
  );
}

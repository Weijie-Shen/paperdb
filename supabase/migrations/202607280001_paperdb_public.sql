begin;

create table if not exists public.users (
    id text primary key,
    name text not null,
    email text,
    role text not null default 'researcher',
    created_at timestamptz not null default now()
);

create table if not exists public.papers (
    id text primary key,
    title text not null,
    title_en text,
    authors_raw text,
    institution text,
    source_type text not null,
    source_name text,
    source_url text,
    download_url text,
    github_url text,
    github_evidence_type text,
    github_evidence_url text,
    publication_date date,
    market text,
    frequency text,
    language text,
    abstract text,
    abstract_en text,
    ai_summary text,
    file_path text,
    file_format text,
    access_status text not null default 'queued',
    access_notes text,
    content_hash text,
    metadata_hash text,
    priority_score integer not null default 0,
    quality_flag text not null default 'ok',
    metadata_quality text not null default 'partial',
    quality_screening_status text not null default 'metadata_only',
    lifecycle_status text not null default 'active',
    ingestion_batch text,
    added_by text references public.users(id),
    reviewed_by text references public.users(id),
    search_text text,
    search_document tsvector generated always as (
        to_tsvector(
            'simple'::regconfig,
            coalesce(
                nullif(search_text, ''),
                coalesce(title, '') || ' ' || coalesce(abstract, '') || ' ' || coalesce(ai_summary, '')
            )
        )
    ) stored,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.paper_labels (
    id text primary key,
    paper_id text not null references public.papers(id) on delete cascade,
    label text not null,
    confidence double precision,
    source text not null default 'ai_auto',
    added_by text references public.users(id),
    created_at timestamptz not null default now()
);

create table if not exists public.paper_authors (
    id text primary key,
    paper_id text not null references public.papers(id) on delete cascade,
    author_name text not null,
    author_name_en text,
    institution text,
    affiliation_source text,
    affiliation_evidence_url text,
    is_corresponding boolean not null default false,
    author_order integer not null
);

create table if not exists public.user_annotations (
    id text primary key,
    paper_id text not null references public.papers(id) on delete cascade,
    user_id text not null references public.users(id),
    note_type text not null,
    content text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.search_logs (
    id text primary key,
    source_name text,
    query text,
    query_type text,
    results_count integer,
    new_papers integer,
    inspected_count integer not null default 0,
    accepted_count integer not null default 0,
    rejected_count integer not null default 0,
    duplicate_count integer not null default 0,
    latency_ms integer,
    searched_at timestamptz not null default now(),
    error text
);

create table if not exists public.search_candidates (
    id text primary key,
    search_log_id text references public.search_logs(id) on delete cascade,
    source_name text not null,
    source_id text,
    title text not null,
    source_url text,
    decision text not null,
    rejection_reason text,
    relevance_score double precision,
    evidence jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.paper_institutions (
    id text primary key,
    paper_id text not null references public.papers(id) on delete cascade,
    canonical_name text not null,
    raw_value text not null,
    matched_alias text not null,
    priority_rank integer not null,
    priority_score integer not null,
    match_source text not null,
    confidence double precision not null,
    created_at timestamptz not null default now(),
    unique (paper_id, canonical_name, raw_value)
);

create table if not exists public.download_logs (
    id text primary key,
    paper_id text not null references public.papers(id) on delete cascade,
    attempt_at timestamptz not null default now(),
    status text not null,
    http_status integer,
    error_detail text,
    file_size bigint,
    finished_at timestamptz,
    retryable boolean
);

create table if not exists public.paper_assessments (
    paper_id text primary key references public.papers(id) on delete cascade,
    research_type text not null check (research_type in ('strategy', 'factor_report')),
    decision text not null check (decision in ('qualified', 'rejected', 'unverified')),
    rejection_reasons jsonb not null default '[]'::jsonb,
    quality_score integer check (quality_score is null or quality_score between 0 and 100),
    quality_breakdown jsonb not null default '{}'::jsonb,
    evidence_json jsonb not null default '{}'::jsonb,
    strategy_family text,
    signal_family text,
    universe text,
    benchmark text,
    holding_period text,
    rebalance_frequency text,
    long_only boolean,
    test_start date,
    test_end date,
    test_months integer,
    annualized_return double precision,
    sharpe_ratio double precision,
    max_drawdown double precision,
    transaction_costs_included boolean,
    transaction_cost_details text,
    leverage_used boolean,
    intraday boolean,
    a_share_rules_compliant boolean,
    out_of_sample boolean,
    turnover text,
    factor_formula text,
    backtest_method text,
    backtest_results text,
    updated_at timestamptz not null default now()
);

create index if not exists idx_papers_search_document on public.papers using gin (search_document);
create index if not exists idx_papers_metadata_hash on public.papers(metadata_hash);
create index if not exists idx_papers_access_status on public.papers(access_status);
create index if not exists idx_papers_source_type on public.papers(source_type);
create index if not exists idx_papers_priority on public.papers(priority_score desc);
create index if not exists idx_papers_institution on public.papers(institution);
create index if not exists idx_papers_publication_date on public.papers(publication_date desc);
create index if not exists idx_papers_lifecycle on public.papers(lifecycle_status);
create index if not exists idx_papers_screening on public.papers(quality_screening_status);
create index if not exists idx_labels_paper on public.paper_labels(paper_id);
create index if not exists idx_labels_label on public.paper_labels(label);
create index if not exists idx_authors_paper on public.paper_authors(paper_id);
create index if not exists idx_downloads_paper on public.download_logs(paper_id);
create index if not exists idx_candidates_search on public.search_candidates(search_log_id);
create index if not exists idx_paper_institutions_paper on public.paper_institutions(paper_id);
create index if not exists idx_paper_institutions_canonical on public.paper_institutions(canonical_name);
create index if not exists idx_assessments_type_decision on public.paper_assessments(research_type, decision);
create index if not exists idx_assessments_quality on public.paper_assessments(quality_score desc);

alter table public.users enable row level security;
alter table public.papers enable row level security;
alter table public.paper_labels enable row level security;
alter table public.paper_authors enable row level security;
alter table public.user_annotations enable row level security;
alter table public.search_logs enable row level security;
alter table public.search_candidates enable row level security;
alter table public.paper_institutions enable row level security;
alter table public.download_logs enable row level security;
alter table public.paper_assessments enable row level security;

drop policy if exists "public reads active papers" on public.papers;
create policy "public reads active papers" on public.papers
    for select to anon, authenticated
    using (lifecycle_status = 'active');

drop policy if exists "public reads active paper labels" on public.paper_labels;
create policy "public reads active paper labels" on public.paper_labels
    for select to anon, authenticated
    using (exists (select 1 from public.papers p where p.id = paper_id and p.lifecycle_status = 'active'));

drop policy if exists "public reads active paper authors" on public.paper_authors;
create policy "public reads active paper authors" on public.paper_authors
    for select to anon, authenticated
    using (exists (select 1 from public.papers p where p.id = paper_id and p.lifecycle_status = 'active'));

drop policy if exists "public reads active paper institutions" on public.paper_institutions;
create policy "public reads active paper institutions" on public.paper_institutions
    for select to anon, authenticated
    using (exists (select 1 from public.papers p where p.id = paper_id and p.lifecycle_status = 'active'));

drop policy if exists "public reads active paper downloads" on public.download_logs;
create policy "public reads active paper downloads" on public.download_logs
    for select to anon, authenticated
    using (exists (select 1 from public.papers p where p.id = paper_id and p.lifecycle_status = 'active'));

drop policy if exists "public reads active paper assessments" on public.paper_assessments;
create policy "public reads active paper assessments" on public.paper_assessments
    for select to anon, authenticated
    using (exists (select 1 from public.papers p where p.id = paper_id and p.lifecycle_status = 'active'));

grant usage on schema public to anon, authenticated;
revoke insert, update, delete, truncate, references, trigger
on public.users, public.papers, public.paper_labels, public.paper_authors,
   public.user_annotations, public.search_logs, public.search_candidates,
   public.paper_institutions, public.download_logs, public.paper_assessments
from anon, authenticated;
grant select on public.papers, public.paper_labels, public.paper_authors,
    public.paper_institutions, public.download_logs, public.paper_assessments
    to anon, authenticated;

create or replace function public.paper_facets()
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
    select jsonb_build_object(
        'market', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select market as value, count(*) as count from papers where lifecycle_status = 'active' and nullif(market, '') is not null group by market) x),
        'frequency', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select frequency as value, count(*) as count from papers where lifecycle_status = 'active' and nullif(frequency, '') is not null group by frequency) x),
        'source_type', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select source_type as value, count(*) as count from papers where lifecycle_status = 'active' and nullif(source_type, '') is not null group by source_type) x),
        'source_name', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select source_name as value, count(*) as count from papers where lifecycle_status = 'active' and nullif(source_name, '') is not null group by source_name) x),
        'access_status', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select access_status as value, count(*) as count from papers where lifecycle_status = 'active' and nullif(access_status, '') is not null group by access_status) x),
        'language', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select language as value, count(*) as count from papers where lifecycle_status = 'active' and nullif(language, '') is not null group by language) x),
        'metadata_quality', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select metadata_quality as value, count(*) as count from papers where lifecycle_status = 'active' and nullif(metadata_quality, '') is not null group by metadata_quality) x),
        'quality_screening_status', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select quality_screening_status as value, count(*) as count from papers where lifecycle_status = 'active' and nullif(quality_screening_status, '') is not null group by quality_screening_status) x),
        'labels', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select pl.label as value, count(distinct pl.paper_id) as count from paper_labels pl join papers p on p.id = pl.paper_id where p.lifecycle_status = 'active' group by pl.label) x),
        'institutions', (select coalesce(jsonb_agg(x order by x.count desc, x.value), '[]') from (select pi.canonical_name as value, count(distinct pi.paper_id) as count from paper_institutions pi join papers p on p.id = pi.paper_id where p.lifecycle_status = 'active' group by pi.canonical_name) x)
    );
$$;

create or replace function public.search_papers(
    query_text text default null,
    filter_market text default null,
    filter_frequency text default null,
    filter_source_type text default null,
    filter_access_status text default null,
    filter_institution text default null,
    filter_labels text[] default null,
    page_limit integer default 50,
    page_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
    with eligible as (
        select p.*,
            case when nullif(trim(query_text), '') is null then 0::real
                 else ts_rank_cd(p.search_document, websearch_to_tsquery('simple', query_text)) end as relevance
        from papers p
        where p.lifecycle_status = 'active'
          and (filter_market is null or p.market = filter_market)
          and (filter_frequency is null or p.frequency = filter_frequency)
          and (filter_source_type is null or p.source_type = filter_source_type)
          and (filter_access_status is null or p.access_status = filter_access_status)
          and (filter_institution is null or p.institution ilike '%' || filter_institution || '%' or exists (
              select 1 from paper_institutions pi where pi.paper_id = p.id
              and (pi.canonical_name ilike '%' || filter_institution || '%' or pi.raw_value ilike '%' || filter_institution || '%')
          ))
          and (coalesce(cardinality(filter_labels), 0) = 0 or (
              select count(distinct pl.label) from paper_labels pl
              where pl.paper_id = p.id and pl.label = any(filter_labels)
          ) = cardinality(filter_labels))
          and (nullif(trim(query_text), '') is null
               or p.search_document @@ websearch_to_tsquery('simple', query_text)
               or p.title ilike '%' || query_text || '%'
               or p.abstract ilike '%' || query_text || '%')
    ), ranked as (
        select * from eligible
        order by relevance desc, priority_score desc, publication_date desc nulls last, created_at desc
        limit greatest(1, least(page_limit, 100)) offset greatest(page_offset, 0)
    )
    select jsonb_build_object(
        'total', (select count(*) from eligible),
        'limit', greatest(1, least(page_limit, 100)),
        'offset', greatest(page_offset, 0),
        'results', coalesce((select jsonb_agg(
            to_jsonb(r) - 'search_document' - 'search_text' - 'relevance' || jsonb_build_object(
                'labels', coalesce((select jsonb_agg(jsonb_build_object('label', pl.label, 'confidence', pl.confidence, 'source', pl.source) order by pl.label) from paper_labels pl where pl.paper_id = r.id), '[]'::jsonb),
                'download_status', case when r.file_path is not null and r.access_status = 'downloaded' then 'downloaded' else r.access_status end,
                'file', jsonb_build_object('status', r.access_status, 'available', r.file_path is not null, 'format', r.file_format, 'storage_path', r.file_path)
            ) order by r.relevance desc, r.priority_score desc, r.publication_date desc nulls last, r.created_at desc
        ) from ranked r), '[]'::jsonb)
    );
$$;

create or replace function public.paper_detail(paper_id text)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
    select to_jsonb(p) - 'search_document' - 'search_text' || jsonb_build_object(
        'labels', coalesce((select jsonb_agg(to_jsonb(pl) - 'id' - 'paper_id' order by pl.label) from paper_labels pl where pl.paper_id = p.id), '[]'::jsonb),
        'authors', coalesce((select jsonb_agg(to_jsonb(pa) - 'id' - 'paper_id' order by pa.author_order) from paper_authors pa where pa.paper_id = p.id), '[]'::jsonb),
        'institutions', coalesce((select jsonb_agg(to_jsonb(pi) - 'id' - 'paper_id' order by pi.priority_rank) from paper_institutions pi where pi.paper_id = p.id), '[]'::jsonb),
        'download_logs', coalesce((select jsonb_agg(to_jsonb(dl) - 'id' - 'paper_id' order by dl.attempt_at desc) from download_logs dl where dl.paper_id = p.id), '[]'::jsonb),
        'assessment', (select to_jsonb(pa) - 'paper_id' from paper_assessments pa where pa.paper_id = p.id),
        'download_status', case when p.file_path is not null and p.access_status = 'downloaded' then 'downloaded' else p.access_status end,
        'file', jsonb_build_object('status', p.access_status, 'available', p.file_path is not null, 'format', p.file_format, 'storage_path', p.file_path)
    )
    from papers p
    where p.id = paper_id and p.lifecycle_status = 'active';
$$;

revoke all on function public.paper_facets() from public;
revoke all on function public.search_papers(text, text, text, text, text, text, text[], integer, integer) from public;
revoke all on function public.paper_detail(text) from public;
grant execute on function public.paper_facets() to anon, authenticated;
grant execute on function public.search_papers(text, text, text, text, text, text, text[], integer, integer) to anon, authenticated;
grant execute on function public.paper_detail(text) to anon, authenticated;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'paper-files', 'paper-files', false, 52428800,
    array['application/pdf', 'text/html', 'text/plain', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
)
on conflict (id) do update set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "public downloads paper files" on storage.objects;
create policy "public downloads paper files" on storage.objects
    for select to anon, authenticated
    using (bucket_id = 'paper-files');

commit;

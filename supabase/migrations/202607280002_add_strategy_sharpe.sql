alter table public.paper_assessments
    add column if not exists sharpe_ratio double precision;

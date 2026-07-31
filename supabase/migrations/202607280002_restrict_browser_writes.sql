begin;

revoke insert, update, delete, truncate, references, trigger
on public.users, public.papers, public.paper_labels, public.paper_authors,
   public.user_annotations, public.search_logs, public.search_candidates,
   public.paper_institutions, public.download_logs, public.paper_assessments
from anon, authenticated;

commit;

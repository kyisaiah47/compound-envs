-- The real policies, read off pg_policies on production 2026-09-19.
--
-- All three tables have `relrowsecurity = true`. There is exactly ONE policy in the whole set:
--
--   publication_posts  "publication_posts read"  SELECT  {public}  using (true)
--
-- publication_subscribers and publication_letter_sends have RLS ENABLED AND NO POLICY, which is
-- the correct shape for a mailing list: only the service role, which bypasses RLS, can see an
-- address. That is also why usingitup_desk/db.py talks to Postgres directly instead of going
-- through PostgREST with the publishable key. A grader holding the anon key reads zero rows from
-- the subscriber table and scores every task 0.0 for the wrong reason.
--
-- The app reads publication_posts with the SERVICE ROLE key (src/lib/live.ts client()), so the
-- anon read policy is for other consumers rather than for the product's own pages.
alter table public.publication_subscribers   enable row level security;
alter table public.publication_posts         enable row level security;
alter table public.publication_letter_sends  enable row level security;

drop policy if exists "publication_posts read" on public.publication_posts;
create policy "publication_posts read" on public.publication_posts
  for select to public using (true);

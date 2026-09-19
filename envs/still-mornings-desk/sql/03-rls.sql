-- still-mornings-desk: the real RLS, pulled from production on 2026-09-19.
--
-- pg_policies over `tablename like 'publication%'` in project xowekqdsttxwbhfxvusa returns
-- EXACTLY ONE ROW. That is not an omission and it is the interesting part of this file:
--
--   publication_posts          rowsecurity = true, one policy: SELECT to public, using (true)
--   publication_subscribers    rowsecurity = true, NO POLICY AT ALL
--   publication_letter_sends   rowsecurity = true, NO POLICY AT ALL
--
-- RLS on with no policy denies everything to anon and authenticated. The subscriber list is
-- therefore unreadable and unwriteable from any browser, which is what api/subscribe/route.ts's
-- own header claims ("RLS is ON with no anon policy, so the table is unreadable from any
-- browser"). Verified here rather than taken from the comment. Both routes hold the service role
-- key server-side and that key bypasses RLS, so the route is the only door.
--
-- publication_posts is world-readable on purpose: src/lib/live.ts reads it with the service key,
-- but the same rows are the publication's published archive and nothing in them is private.

alter table public.publication_subscribers   enable row level security;
alter table public.publication_letter_sends  enable row level security;
alter table public.publication_posts         enable row level security;

drop policy if exists "publication_posts read" on public.publication_posts;
create policy "publication_posts read" on public.publication_posts
  for select to public using (true);

-- NOTHING IS ADDED FOR THE OTHER TWO. A convenience policy here would make every cross-tenant
-- check in the graders the grader's own invention rather than the database's refusal.

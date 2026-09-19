-- whyyourbraindoesthat-desk: the product's real RLS, read off production project
-- xowekqdsttxwbhfxvusa on 2026-09-19.
--
-- `select tablename, policyname, cmd, roles, qual, with_check from pg_policies where
--  schemaname='public' and tablename like 'publication%'` returns exactly ONE row in production:
--
--     publication_posts | publication_posts read | SELECT | {public} | true | (null)
--
-- Every other `publication_*` table has `relrowsecurity = true` and NO POLICY AT ALL. That is
-- not an oversight and it is what the subscribe route's own header claims: "RLS is ON with no
-- anon policy, so the table is unreadable from any browser." RLS with zero policies denies every
-- role that is not `service_role` or the table owner, so the reader list is invisible to the
-- publishable key and reachable only by the two server routes, which hold the service key.
--
-- Both halves are asserted at the end of this file rather than described, because a policy that
-- does not exist and a policy that exists and permits everything look identical from the app.

alter table public.publication_subscribers  enable row level security;
alter table public.publication_letter_sends enable row level security;
alter table public.publication_posts        enable row level security;

-- The one policy production carries. The archive is public reading matter, so the site could
-- read it with the publishable key; it uses the service key anyway (src/lib/live.ts), and that
-- is the product's choice, not this file's.
drop policy if exists "publication_posts read" on public.publication_posts;
create policy "publication_posts read" on public.publication_posts
  for select to public using (true);

-- ⛔ NO POLICY IS CREATED FOR publication_subscribers OR publication_letter_sends, ON PURPOSE.
-- Adding a permissive one here to make a grader's life easier would make this environment's
-- database more open than production's, and the reader list is the one thing on this product
-- that must never be readable from a page.

-- ── the assertions ──────────────────────────────────────────────────────────────────────────
do $$
declare n int;
begin
  select count(*) into n from pg_policies
   where schemaname = 'public' and tablename = 'publication_subscribers';
  if n <> 0 then
    raise exception 'publication_subscribers carries % policies; production carries none', n;
  end if;

  select count(*) into n from pg_policies
   where schemaname = 'public' and tablename = 'publication_letter_sends';
  if n <> 0 then
    raise exception 'publication_letter_sends carries % policies; production carries none', n;
  end if;

  select count(*) into n from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
   where ns.nspname = 'public'
     and c.relname in ('publication_subscribers','publication_letter_sends','publication_posts')
     and c.relrowsecurity;
  if n <> 3 then
    raise exception 'row level security is on % of the 3 tables, not all of them', n;
  end if;
end $$;

-- ── the three tables this environment does NOT create ───────────────────────────────────────
--
-- publication_quiz_subscribers, publication_quiz_reminder_sends and publication_quiz_passes all
-- exist in production and all three are empty for every publication (measured 2026-09-19). They
-- were written for `/today`, `/api/quiz/subscribe`, `/api/quiz/confirm`, `/api/quiz/unsubscribe`
-- and `/api/checkout`, and the 2026-09-14 swap replaced the live site with a tree that serves
-- none of them. CARRY.json records those addresses under `legacy.pages` and `legacy.apis`, and
-- the repo's own gate asserts in both directions that they stay unserved.
--
-- Measured against the live host on 2026-09-19, https://whyyourbrain.thecompound.tech:
--
--     /                                          200
--     /rss.xml                                   200
--     /api/subscribe/unsubscribe?token=<uuid>    200
--     /today                                     404
--     /api/quiz/subscribe                        404
--     /api/quiz/unsubscribe?token=<uuid>         404
--
-- Creating them here would put three tables in front of a grader that no route on this product
-- can write to, which is the exact `cd_drafts` mistake the reference environment paid a rewrite
-- for. They are recorded in results.json instead: `not_gradable` for the checkout and quiz
-- routes, and `defects` for the daily launchd job that still fires at them.

-- WireCall's real RLS, read off production (pg_policies, pg_class.relrowsecurity,
-- information_schema.role_table_grants) on 2026-09-19.
--
-- THE SHAPE, AND IT IS WORTH STATING BECAUSE IT DECIDES WHAT A GRADER HAS TO CHECK ITSELF.
-- RLS is ON for all five tables and there is not one INSERT, UPDATE or DELETE policy anywhere
-- in the product. Two tables carry a public SELECT policy and nothing else:
--
--   wc_slates   wc_slates_read   role public, using (true)
--   wc_stories  wc_stories_read  role public, using (true)
--
-- wc_calls and wc_orders carry NO policy at all. RLS with no policy denies every row, so the
-- publishable key reads them as an empty array rather than an error. Measured against
-- production on 2026-09-19 with the live publishable key:
--
--   GET /rest/v1/wc_calls?select=id&limit=1   -> 200 []
--   GET /rest/v1/wc_orders?select=id&limit=1  -> 200 []
--
-- ⛔ wc_players IS THE INTERESTING ONE, AND IT IS SHUT. It carries a policy,
-- wc_players_leaderboard_read, for anon and authenticated using (points > 0 or streak_best > 0).
-- But anon and authenticated hold NO grant on the table at all, so the policy can never be
-- reached. Measured on production:
--
--   GET /rest/v1/wc_players?select=id&limit=1 -> 401 42501 "permission denied for table
--                                                wc_players"
--   GET /rest/v1/wc_leaderboard?select=rank,points&limit=3 -> 200 [{"rank":1,"points":10}]
--
-- That matters because the policy is row level and the table holds `email`. Had the grant been
-- there, `?select=email` would have returned every scoring player's address, which is the
-- ilike-as-a-lookup class of defect this project has found three times this week in other
-- products. Here the grant is absent and the board goes through the view, which selects six
-- columns and no address. The policy is dead weight, not a hole. It is reproduced below exactly
-- as production holds it, because an environment that quietly tidied it would be describing a
-- product that does not exist.
--
-- ⛔ WHAT THIS MEANS FOR THE GRADERS. Every write in WireCall runs in a server route under the
-- service key (src/lib/supabase.ts supabaseWrite(), which throws rather than falling back to a
-- client key). So RLS here does not enforce one player against another the way it does on a
-- tenant-scoped product: the per-player check is application code, the signed device key in
-- src/lib/device.ts. The "wrote it as somebody else" guards in taskset.py are the only thing
-- checking that, not a second opinion on top of the database.

alter table public.wc_players enable row level security;
alter table public.wc_slates  enable row level security;
alter table public.wc_stories enable row level security;
alter table public.wc_calls   enable row level security;
alter table public.wc_orders  enable row level security;

drop policy if exists wc_slates_read on public.wc_slates;
create policy wc_slates_read on public.wc_slates for select to public using (true);

drop policy if exists wc_stories_read on public.wc_stories;
create policy wc_stories_read on public.wc_stories for select to public using (true);

drop policy if exists wc_players_leaderboard_read on public.wc_players;
-- ⛔ AND IT IS NOT RECREATED. This policy was a row-level SELECT for anon and authenticated on a
-- table whose rows carry `email`, and neither role holds a SELECT grant, so it did nothing except
-- make `GRANT SELECT ON public.wc_players TO anon` look like the intended fix for the 401 the
-- board never actually hits. The board is served by wc_leaderboard. Dropped in production
-- 2026-09-19, migration wc_players_drop_dead_leaderboard_policy, and this file follows it.

-- The grants production holds. wc_players is deliberately NOT granted to anon or authenticated:
-- see the header. Everything else matches Supabase's own default grant, which RLS then closes.
grant select on public.wc_slates, public.wc_stories to anon, authenticated;
grant select, insert, update, delete on public.wc_calls, public.wc_orders to anon, authenticated;
grant select on public.wc_leaderboard to anon, authenticated;
revoke all on public.wc_players from anon, authenticated;

-- ⛔ ONE THING PRODUCTION DECLARES AND DOES NOT DO, MEASURED RATHER THAN ASSUMED.
-- pg_class.reloptions on the production wc_leaderboard reads `security_invoker=on`, which means
-- the caller needs SELECT on wc_players, and anon does not have it. The live view nevertheless
-- answers 200. Both halves measured on production, 2026-09-19:
--
--   wc_leaderboard?select=rank,points  -> 200 [{"rank":1,"points":10}]
--   wc_players?select=id               -> 401 permission denied for table wc_players
--
-- Reproduced on this stack to find which of the two the graders and the capture have to live
-- with, because guessing would have been the whole failure this repo exists to prevent:
--
--   view with (security_invoker=on), anon ungranted -> 401 permission denied for wc_players
--   view with the option reset,      anon ungranted -> 200, the three board rows
--
-- So the OBSERVABLE production surface is the second one, and 01-schema.sql creates the view
-- without the option. The grant table then matches production exactly: anon holds nothing at
-- all on wc_players, `?select=email` is 401 here as it is there, and the board still reads.
-- Nothing is granted below; this note is the record of why there is nothing to grant.

-- The two wires WireCall reads. Public SELECT, exactly as their own products publish them.
alter table public.frontwire_posts enable row level security;
alter table public.popwire_posts   enable row level security;
drop policy if exists frontwire_posts_public_read on public.frontwire_posts;
create policy frontwire_posts_public_read on public.frontwire_posts
  for select to anon, authenticated using (true);
drop policy if exists popwire_posts_public_read on public.popwire_posts;
create policy popwire_posts_public_read on public.popwire_posts
  for select to anon, authenticated using (true);
grant select on public.frontwire_posts, public.popwire_posts to anon, authenticated;

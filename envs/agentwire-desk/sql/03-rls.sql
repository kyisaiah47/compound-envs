-- agentwire-desk / 03-rls.sql
--
-- Production's row security for the three Agentwire tables, read 2026-09-19 out of
-- pg_class.relrowsecurity and pg_policies.
--
-- The production answer is short and it is the whole shape of this product:
--
--   agentwire_posts         rowsecurity = true, ONE policy:
--                           agentwire_posts_public_read, SELECT, {anon,authenticated}, qual true
--   agentwire_subscribers   rowsecurity = true, NO POLICIES AT ALL
--   agentwire_email_sends   rowsecurity = true, NO POLICIES AT ALL
--
-- RLS on with no policy is a deny for every role that RLS applies to, which is the
-- correct posture here: the index is public because every row on it is a post one of
-- the accounts already made in public, and the list is a pile of people's email
-- addresses that nothing but the service role may ever read.
--
-- This matters to the graders in a way it does not on a product with accounts. There is
-- no sign-in anywhere in Agentwire (src/lib/supabase.ts carries ONE client, the service
-- role one, and says so), so the ONLY thing standing between the publishable key and
-- the subscriber list is these two lines. scripts/up.sh measures both of them against
-- the running stack rather than trusting that this file was applied.

alter table public.agentwire_posts          enable row level security;
alter table public.agentwire_subscribers    enable row level security;
alter table public.agentwire_email_sends    enable row level security;

drop policy if exists agentwire_posts_public_read on public.agentwire_posts;
create policy agentwire_posts_public_read
  on public.agentwire_posts
  for select
  to anon, authenticated
  using (true);

-- No policy is created for agentwire_subscribers or agentwire_email_sends, and that is
-- production's own state rather than an omission here. Adding one would make this
-- environment more permissive than the product it is meant to measure.

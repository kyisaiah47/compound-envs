-- popwire-desk / 03-rls.sql
--
-- Production's row security for the tables this environment uses, read 2026-09-19 out of
-- pg_class.relrowsecurity and pg_policies.
--
-- The production answer is short, and it is the whole shape of this product:
--
--   popwire_posts        rowsecurity = true, ONE policy:
--                        popwire_posts_public_read, SELECT, {anon,authenticated}, qual true
--   popwire_subscribers  rowsecurity = true, NO POLICIES AT ALL
--   popwire_email_sends  rowsecurity = true, NO POLICIES AT ALL
--   social_posts         rowsecurity = true, NO POLICIES AT ALL
--
-- RLS on with no policy is a deny for every role RLS applies to, and that is the correct
-- posture here rather than an omission. The index is public because every row on it is a
-- post one of the accounts already made in public. The list is a pile of people's email
-- addresses. The send ledger says who was mailed what. The posting ledger is the whole
-- estate's, every product on it.
--
-- This matters more here than on a product with accounts. Popwire has NO SIGN-IN anywhere:
-- src/lib/supabase.ts exports supabaseBrowser(), nothing in the tree calls it, and every
-- route writes through supabaseAdmin() on the server. So these four lines are the only
-- thing between the publishable key and the subscriber list, and scripts/up.sh measures
-- each of them against the running stack rather than trusting that this file was applied.

alter table public.popwire_posts       enable row level security;
alter table public.popwire_subscribers enable row level security;
alter table public.popwire_email_sends enable row level security;
alter table public.social_posts        enable row level security;

drop policy if exists popwire_posts_public_read on public.popwire_posts;
create policy popwire_posts_public_read
  on public.popwire_posts
  for select
  to anon, authenticated
  using (true);

-- No policy is created for popwire_subscribers, popwire_email_sends or social_posts, and
-- that is production's own state. Adding one would make this environment more permissive
-- than the product it is meant to measure.

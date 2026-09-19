-- frontwire-desk: the product's real RLS, read off pg_policies and pg_class in the shared
-- production project xowekqdsttxwbhfxvusa on 2026-09-19.
--
-- ⛔ WHAT PRODUCTION ACTUALLY HAS, AND IT IS SHORTER THAN IT LOOKS. Row level security is ENABLED
-- on all six frontwire tables and exactly three policies exist across them:
--
--   frontwire_posts     frontwire_posts_public_read      SELECT  anon, authenticated   using (true)
--   frontwire_profiles  frontwire_profiles_select_own    SELECT  public               using (auth.uid() = id)
--   frontwire_profiles  fw_profiles_self                 ALL     public               using/check (auth.uid() = id)
--
-- frontwire_subscribers, frontwire_email_sends, frontwire_contacts and frontwire_pending_members
-- have RLS on and NO policy at all, which is the correct shape for this product: nothing but the
-- service role ever touches them, and every one of the four API routes that does goes through
-- supabaseAdmin(). A browser holding the anon key cannot read one address off the list, cannot
-- read another reader's letter, and cannot see who paid.
--
-- ⛔ AND THE SEAM THAT LEAVES IS THE ONE THE GRADERS CARRY. With no policy anywhere on those four
-- tables, the database enforces NOTHING about which row a write lands on: every write runs as
-- service_role and the only thing deciding the right subscriber is the confirm_token the route
-- was handed. A grader that only checks "some row is now confirmed" passes every wrong-row cheat
-- in adversarial/.

alter table public.frontwire_posts            enable row level security;
alter table public.frontwire_subscribers      enable row level security;
alter table public.frontwire_email_sends      enable row level security;
alter table public.frontwire_contacts         enable row level security;
alter table public.frontwire_profiles         enable row level security;
alter table public.frontwire_pending_members  enable row level security;

drop policy if exists frontwire_posts_public_read on public.frontwire_posts;
create policy frontwire_posts_public_read
  on public.frontwire_posts for select to anon, authenticated
  using (true);

drop policy if exists frontwire_profiles_select_own on public.frontwire_profiles;
create policy frontwire_profiles_select_own
  on public.frontwire_profiles for select
  using (auth.uid() = id);

drop policy if exists fw_profiles_self on public.frontwire_profiles;
create policy fw_profiles_self
  on public.frontwire_profiles for all
  using (auth.uid() = id)
  with check (auth.uid() = id);

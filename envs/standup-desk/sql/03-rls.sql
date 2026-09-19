-- Row level security, as the live project has it.
--
-- Read out of the live project on 2026-09-19 with pg_policies and pg_class.relrowsecurity:
-- all ten standup_ tables have RLS enabled, and there are exactly FOUR policies across them.
--
-- WHY AN ENVIRONMENT NEEDS THIS AT ALL. Without RLS every ownership check is enforced only by the
-- grader. With it the database refuses the write the way production does, so a rollout that
-- scores zero here scores zero for the same reason it would have failed a real reader's account.
--
-- AND ONE OF THESE POLICIES IS A HOLE, WHICH IS WHY IT IS REPRODUCED RATHER THAN TIDIED.
-- `standup_profiles_self` is cmd=ALL with `auth.uid() = id` on BOTH qual and with_check, so a
-- signed-in reader can UPDATE THEIR OWN `plan` COLUMN from the browser, with the anon key, and
-- Postgres will accept it. That is a real, live, self-serve membership. It is the cheapest cheat
-- in this whole environment and claim-the-parked-membership is written to catch it: a plan that
-- was granted rather than claimed leaves standup_pending_members.claimed_at null, and nothing on
-- any page shows the difference.
--
-- The six tables with NO policy (subscribers, email_sends, contacts, pending_members,
-- post_metrics, alert_sends) are reachable only by the service role, which is what every API
-- route uses through supabaseAdmin(). Anon and authenticated get nothing.

alter table public.standup_posts           enable row level security;
alter table public.standup_profiles        enable row level security;
alter table public.standup_subscribers     enable row level security;
alter table public.standup_email_sends     enable row level security;
alter table public.standup_contacts        enable row level security;
alter table public.standup_pending_members enable row level security;
alter table public.standup_post_metrics    enable row level security;
alter table public.standup_consequences    enable row level security;
alter table public.standup_watchlists      enable row level security;
alter table public.standup_alert_sends     enable row level security;

drop policy if exists standup_posts_public_read on public.standup_posts;
create policy standup_posts_public_read on public.standup_posts
  for select to anon, authenticated using (true);

drop policy if exists standup_consequences_read on public.standup_consequences;
create policy standup_consequences_read on public.standup_consequences
  for select to public using (true);

-- cmd=ALL. See the header: this lets a reader write their own plan.
drop policy if exists standup_profiles_self on public.standup_profiles;
create policy standup_profiles_self on public.standup_profiles
  for all to public using (auth.uid() = id) with check (auth.uid() = id);

drop policy if exists standup_watchlists_self on public.standup_watchlists;
create policy standup_watchlists_self on public.standup_watchlists
  for all to public using (auth.uid() = profile_id) with check (auth.uid() = profile_id);

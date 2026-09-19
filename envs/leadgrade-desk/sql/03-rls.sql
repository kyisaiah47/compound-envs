-- LeadGrade's RLS, verbatim from production `xowekqdsttxwbhfxvusa` (pg_policies, 2026-09-19).
--
-- Seven owner policies keyed on auth.uid(), one email-or-uid read policy on the subscriptions
-- table, and one public read of published posts. Every server-side write in the product goes
-- through the service-role client (`_lib/supabase/admin.ts`), which bypasses all of this and
-- carries its own `.eq("user_id", uid)` on every statement, so these policies are what stands
-- between one tenant and another for anything holding only the anon key.
--
-- Reproducing them matters for the same reason the reference environment gives: without RLS every
-- tenancy check in this environment would be enforced only by the grader, and the database would
-- happily accept a cross-tenant write that production refuses.

alter table public.leadgrade_leads          enable row level security;
alter table public.leadgrade_writebacks     enable row level security;
alter table public.leadgrade_events         enable row level security;
alter table public.leadgrade_runs           enable row level security;
alter table public.leadgrade_settings       enable row level security;
alter table public.leadgrade_integrations   enable row level security;
alter table public.leadgrade_subscriptions  enable row level security;
alter table public.leadgrade_posts          enable row level security;

drop policy if exists leadgrade_leads_owner        on public.leadgrade_leads;
drop policy if exists leadgrade_writebacks_owner   on public.leadgrade_writebacks;
drop policy if exists leadgrade_events_owner       on public.leadgrade_events;
drop policy if exists leadgrade_runs_owner         on public.leadgrade_runs;
drop policy if exists leadgrade_settings_owner     on public.leadgrade_settings;
drop policy if exists leadgrade_integrations_owner on public.leadgrade_integrations;
drop policy if exists leadgrade_subscriptions_owner on public.leadgrade_subscriptions;
drop policy if exists leadgrade_posts_published_read on public.leadgrade_posts;

create policy leadgrade_leads_owner on public.leadgrade_leads
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy leadgrade_writebacks_owner on public.leadgrade_writebacks
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy leadgrade_events_owner on public.leadgrade_events
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy leadgrade_runs_owner on public.leadgrade_runs
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy leadgrade_settings_owner on public.leadgrade_settings
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy leadgrade_integrations_owner on public.leadgrade_integrations
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Read only, and it resolves by uid OR by the address on the JWT. The pay-first funnel's row
-- has no user_id on it until the first sign-in claims it.
create policy leadgrade_subscriptions_owner on public.leadgrade_subscriptions
  for select using (
    user_id = auth.uid()
    or lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );

create policy leadgrade_posts_published_read on public.leadgrade_posts
  for select using (status = 'published');

-- FetchDue's real RLS, read out of `xowekqdsttxwbhfxvusa` with pg_policies on 2026-09-19 and
-- reproduced verbatim, policy names included.
--
-- ALL 25 TABLES HAVE RLS ENABLED. Only 15 policies exist across 12 of them, so TEN tables are
-- enabled with NO POLICY AT ALL: invoices_conversations, invoices_messages, invoices_installments,
-- invoices_commitments, invoices_agent_events, invoices_inbound_emails,
-- invoices_graph_subscriptions, invoices_oauth_tokens, invoices_ui_prefs and
-- invoices_chase_outcomes. An authenticated cookie read of any of those returns zero rows with no
-- error. That is deliberate: the product reads every one of them through the SERVICE ROLE client
-- and filters `user_id` by hand, and src/lib/tenant.ts carries the measurement in its own header.
-- Reproducing the absence matters as much as reproducing a policy: an environment that invented
-- an owner policy on invoices_messages would let a cookie-client grader read rows the live product
-- cannot.
--
-- Several tables carry TWO policies that say the same thing with the operands swapped
-- (`user_id = auth.uid()` and `auth.uid() = user_id`). That is what production has, from two
-- migrations that each added one, and it is reproduced rather than tidied.

alter table public.invoices_users              enable row level security;
alter table public.invoices_clients            enable row level security;
alter table public.invoices_invoices           enable row level security;
alter table public.invoices_reminders          enable row level security;
alter table public.invoices_cadence            enable row level security;
alter table public.invoices_voice              enable row level security;
alter table public.invoices_integrations       enable row level security;
alter table public.invoices_oauth_tokens       enable row level security;
alter table public.invoices_conversations      enable row level security;
alter table public.invoices_messages           enable row level security;
alter table public.invoices_installments       enable row level security;
alter table public.invoices_commitments        enable row level security;
alter table public.invoices_agent_events       enable row level security;
alter table public.invoices_late_fee_policy    enable row level security;
alter table public.invoices_inbound_emails     enable row level security;
alter table public.invoices_graph_subscriptions enable row level security;
alter table public.invoices_user_subscriptions enable row level security;
alter table public.invoices_firm_subscriptions enable row level security;
alter table public.invoices_firm_clients       enable row level security;
alter table public.invoices_subscriptions      enable row level security;
alter table public.invoices_chase_outcomes     enable row level security;
alter table public.invoices_ui_prefs           enable row level security;
alter table public.invoices_demo_fixtures      enable row level security;
alter table public.fetchdue_posts              enable row level security;
alter table public.fetchdue_suppressions       enable row level security;

drop policy if exists tally_users_owner_all on public.invoices_users;
create policy tally_users_owner_all on public.invoices_users
  for all to authenticated using ((auth.uid())::text = auth_user_id) with check ((auth.uid())::text = auth_user_id);

drop policy if exists tally_clients_owner on public.invoices_clients;
create policy tally_clients_owner on public.invoices_clients
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists tally_clients_owner_all on public.invoices_clients;
create policy tally_clients_owner_all on public.invoices_clients
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists tally_invoices_owner on public.invoices_invoices;
create policy tally_invoices_owner on public.invoices_invoices
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists tally_invoices_owner_all on public.invoices_invoices;
create policy tally_invoices_owner_all on public.invoices_invoices
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists tally_reminders_owner on public.invoices_reminders;
create policy tally_reminders_owner on public.invoices_reminders
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists tally_reminders_owner_all on public.invoices_reminders;
create policy tally_reminders_owner_all on public.invoices_reminders
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists tally_cadence_owner on public.invoices_cadence;
create policy tally_cadence_owner on public.invoices_cadence
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists tally_cadence_owner_all on public.invoices_cadence;
create policy tally_cadence_owner_all on public.invoices_cadence
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists tally_voice_owner on public.invoices_voice;
create policy tally_voice_owner on public.invoices_voice
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists tally_integrations_owner on public.invoices_integrations;
create policy tally_integrations_owner on public.invoices_integrations
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists tally_integrations_owner_all on public.invoices_integrations;
create policy tally_integrations_owner_all on public.invoices_integrations
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists tally_user_subscriptions_owner on public.invoices_user_subscriptions;
create policy tally_user_subscriptions_owner on public.invoices_user_subscriptions
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists tally_subscriptions_owner_all on public.invoices_subscriptions;
create policy tally_subscriptions_owner_all on public.invoices_subscriptions
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists invoices_late_fee_policy_select_own on public.invoices_late_fee_policy;
create policy invoices_late_fee_policy_select_own on public.invoices_late_fee_policy
  for select to public using (auth.uid() = user_id);

drop policy if exists invoices_firm_subscriptions_select_own on public.invoices_firm_subscriptions;
create policy invoices_firm_subscriptions_select_own on public.invoices_firm_subscriptions
  for select to public using (auth.uid() = user_id);

drop policy if exists invoices_firm_clients_select_own on public.invoices_firm_clients;
create policy invoices_firm_clients_select_own on public.invoices_firm_clients
  for select to public using (auth.uid() = firm_user_id);

drop policy if exists tally_demo_fixtures_read on public.invoices_demo_fixtures;
create policy tally_demo_fixtures_read on public.invoices_demo_fixtures
  for select to authenticated using (true);

drop policy if exists "public read published" on public.fetchdue_posts;
create policy "public read published" on public.fetchdue_posts
  for select to public using (status = 'published');

drop policy if exists "no public access" on public.fetchdue_suppressions;
create policy "no public access" on public.fetchdue_suppressions
  for all to anon, authenticated using (false) with check (false);

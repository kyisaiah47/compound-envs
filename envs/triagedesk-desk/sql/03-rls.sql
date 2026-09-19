-- TriageDesk's real RLS, verbatim from production xowekqdsttxwbhfxvusa, read 2026-09-19.
--
-- Ten tables, RLS on for all ten, and only NINE policies, because two of them deliberately carry
-- no policy at all:
--
--   triagedesk_integrations   holds the encrypted mailbox grant in `config`
--   triagedesk_slack_installs holds the encrypted Slack bot token
--
-- RLS on with no policy means no anon or authenticated role can read a byte of either table. The
-- product reaches both through the service role only, and `getIntegrations()` projects the row
-- WITHOUT `config` so nothing client-side ever sees a token. That is a projection rather than a
-- policy, and the empty-policy state is what makes it safe.
--
-- Every other table is one owner-SELECT policy on auth.uid() and nothing else: no insert, no
-- update, no delete for a signed-in user anywhere in this product. Every write goes through the
-- service-role client, which carries its own `.eq("user_id", uid)` on every query. That matters
-- most on triagedesk_usage: an account that could write its own meter could reset the cap that
-- bounds the owner's model bill.
--
-- triagedesk_posts is the one public read, gated on `status = 'published'`.

alter table public.triagedesk_threads        enable row level security;
alter table public.triagedesk_messages       enable row level security;
alter table public.triagedesk_drafts         enable row level security;
alter table public.triagedesk_events         enable row level security;
alter table public.triagedesk_runs           enable row level security;
alter table public.triagedesk_settings       enable row level security;
alter table public.triagedesk_integrations   enable row level security;
alter table public.triagedesk_slack_installs enable row level security;
alter table public.triagedesk_subscriptions  enable row level security;
alter table public.triagedesk_usage          enable row level security;
alter table public.triagedesk_posts          enable row level security;

drop policy if exists triagedesk_threads_owner_read on public.triagedesk_threads;
create policy triagedesk_threads_owner_read on public.triagedesk_threads
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists triagedesk_messages_owner_read on public.triagedesk_messages;
create policy triagedesk_messages_owner_read on public.triagedesk_messages
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists triagedesk_drafts_owner_read on public.triagedesk_drafts;
create policy triagedesk_drafts_owner_read on public.triagedesk_drafts
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists triagedesk_events_owner_read on public.triagedesk_events;
create policy triagedesk_events_owner_read on public.triagedesk_events
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists triagedesk_runs_owner_read on public.triagedesk_runs;
create policy triagedesk_runs_owner_read on public.triagedesk_runs
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists triagedesk_settings_owner_read on public.triagedesk_settings;
create policy triagedesk_settings_owner_read on public.triagedesk_settings
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists triagedesk_subscriptions_owner_read on public.triagedesk_subscriptions;
create policy triagedesk_subscriptions_owner_read on public.triagedesk_subscriptions
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists triagedesk_usage_owner_read on public.triagedesk_usage;
create policy triagedesk_usage_owner_read on public.triagedesk_usage
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists triagedesk_posts_public_read on public.triagedesk_posts;
create policy triagedesk_posts_public_read on public.triagedesk_posts
  for select to anon, authenticated using (status = 'published');

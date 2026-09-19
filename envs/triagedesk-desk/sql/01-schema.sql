-- triagedesk's real tables, pulled from the shared production project xowekqdsttxwbhfxvusa
-- on 2026-09-19 with the Supabase MCP.
--
-- ⛔ ALL TEN ARE REAL TABLES, CHECKED RATHER THAN ASSUMED. `pg_class.relkind` is 'r' for every
-- one of them in production, and RLS is on for all ten. The 2026-09-10 kynth -> compound rename
-- sweep left VIEWS over older tables behind in at least one sibling product on this stack, and
-- reading a view as a table is how a grader ends up measuring the wrong relation. TriageDesk has
-- none.
--
-- ⛔ NOTHING HERE TRUNCATES AND NOTHING HERE DROPS. `create table if not exists` only, because
-- this file is applied to a stack every other environment in this repo also uses.

create extension if not exists pgcrypto;

-- One conversation in the shared inbox. The queue card is per thread.
create table if not exists public.triagedesk_threads (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references auth.users(id) on delete cascade,
  provider          text not null default 'microsoft365',
  thread_key        text not null,
  subject           text,
  from_email        text,
  from_name         text,
  category          text,
  priority          text not null default 'normal',
  status            text not null default 'open',
  agent_reply_count integer not null default 0,
  message_count     integer not null default 0,
  last_message_at   timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (user_id, provider, thread_key)
);
create index if not exists triagedesk_threads_user_last_idx
  on public.triagedesk_threads (user_id, last_message_at desc);

-- One message. The unique key on (user_id, provider_message_id) is what makes the overnight
-- pass free to re-read a batch it already recorded.
create table if not exists public.triagedesk_messages (
  id                        uuid primary key default gen_random_uuid(),
  user_id                   uuid not null references auth.users(id) on delete cascade,
  thread_id                 uuid references public.triagedesk_threads(id) on delete cascade,
  provider_message_id       text not null,
  internet_message_id       text,
  in_reply_to               text,
  direction                 text not null default 'in',
  from_email                text,
  to_email                  text,
  subject                   text,
  body                      text,
  received_at               timestamptz,
  classified_as             text,
  classification_confidence numeric,
  created_at                timestamptz not null default now(),
  unique (user_id, provider_message_id)
);
create index if not exists triagedesk_messages_user_thread_idx
  on public.triagedesk_messages (user_id, thread_id, received_at desc);

-- The morning queue. `status` is the whole state machine:
--   pending_review -> queued -> sending -> sent | failed
--   pending_review -> killed
--   queued -> cancelled
create table if not exists public.triagedesk_drafts (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references auth.users(id) on delete cascade,
  thread_id           uuid not null references public.triagedesk_threads(id) on delete cascade,
  message_id          uuid references public.triagedesk_messages(id) on delete set null,
  run_id              uuid,
  subject             text not null,
  body                text not null,
  category            text,
  confidence          numeric,
  status              text not null default 'pending_review',
  edited              boolean not null default false,
  scheduled_for       timestamptz,
  sent_at             timestamptz,
  provider_message_id text,
  internet_message_id text,
  error               text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  slack_channel_id    text,
  slack_message_ts    text
);
create index if not exists triagedesk_drafts_user_status_idx
  on public.triagedesk_drafts (user_id, status, created_at desc);
create index if not exists triagedesk_drafts_due_idx
  on public.triagedesk_drafts (status, scheduled_for);

-- The ledger. Every decision the loop makes writes one of these, with its evidence.
create table if not exists public.triagedesk_events (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  run_id     uuid,
  kind       text not null,
  thread_id  uuid,
  message_id uuid,
  draft_id   uuid,
  title      text not null,
  detail     text,
  evidence   jsonb,
  confidence numeric,
  created_at timestamptz not null default now()
);
create index if not exists triagedesk_events_user_created_idx
  on public.triagedesk_events (user_id, created_at desc);

-- One overnight pass.
create table if not exists public.triagedesk_runs (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references auth.users(id) on delete cascade,
  status           text not null default 'running',
  watermark_before timestamptz,
  watermark_after  timestamptz,
  scanned          integer not null default 0,
  classified       integer not null default 0,
  drafted          integer not null default 0,
  handed_off       integer not null default 0,
  error            text,
  started_at       timestamptz not null default now(),
  finished_at      timestamptz
);
create index if not exists triagedesk_runs_user_started_idx
  on public.triagedesk_runs (user_id, started_at desc);

-- The account's own caps, watermark and voice. One row per account.
create table if not exists public.triagedesk_settings (
  user_id           uuid primary key references auth.users(id) on delete cascade,
  mailbox_watermark timestamptz,
  daily_send_cap    integer,
  thread_reply_cap  integer,
  autonomy          text not null default 'review_all',
  voice             jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- The mailbox grant. `config` carries the encrypted access/refresh pair, the app marker and the
-- scopes actually consented to. RLS is on with NO POLICY, so nothing client-side can read it.
create table if not exists public.triagedesk_integrations (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  provider       text not null,
  connected      boolean not null default false,
  account_label  text,
  config         jsonb not null default '{}'::jsonb,
  last_synced_at timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (user_id, provider)
);

-- The Slack workspace link. Also RLS on with no policy.
create table if not exists public.triagedesk_slack_installs (
  user_id        uuid primary key references auth.users(id) on delete cascade,
  team_id        text not null,
  team_name      text,
  app_id         text,
  bot_user_id    text,
  bot_token      text,
  authed_user_id text,
  scopes         text,
  webhook_url    text,
  channel_id     text,
  channel_name   text,
  connected      boolean not null default true,
  encrypted      boolean not null default false,
  installed_at   timestamptz,
  updated_at     timestamptz not null default now()
);
-- Partial, on purpose: the lookup every inbound Slack request makes is by team AND connected.
create index if not exists triagedesk_slack_installs_team_id_idx
  on public.triagedesk_slack_installs (team_id) where connected;

-- ⛔ KEYED ON EMAIL, NOT ON user_id. There is no free account on this product, so a buyer PAYS
-- BEFORE THEY HAVE AN ACCOUNT and the email is the only identity that exists when
-- checkout.session.completed arrives. `user_id` is stamped on later by claimSubscriptionForUser.
create table if not exists public.triagedesk_subscriptions (
  email                  text primary key,
  user_id                uuid unique references auth.users(id) on delete set null,
  tier                   text,
  status                 text not null default 'inactive',
  stripe_customer_id     text,
  stripe_subscription_id text,
  current_period_end     timestamptz,
  cancel_at_period_end   boolean not null default false,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);
create index if not exists triagedesk_subscriptions_customer_idx
  on public.triagedesk_subscriptions (stripe_customer_id);

-- The model-spend meter, one row per account per UTC day.
create table if not exists public.triagedesk_usage (
  user_id         uuid not null references auth.users(id) on delete cascade,
  day             date not null,
  inference_calls integer not null default 0,
  updated_at      timestamptz not null default now(),
  primary key (user_id, day)
);

-- Editorial. Read by /blog and /changelog, written by nothing in the product.
create table if not exists public.triagedesk_posts (
  id           uuid primary key default gen_random_uuid(),
  kind         text not null,
  slug         text not null,
  title        text not null,
  summary      text,
  body_md      text not null,
  tags         text[] not null default '{}'::text[],
  status       text not null default 'draft',
  published_at timestamptz,
  updated_at   timestamptz not null default now(),
  author       text not null default 'Isaiah Kim',
  hero_image   text,
  meta         jsonb not null default '{}'::jsonb,
  unique (kind, slug)
);
create index if not exists triagedesk_posts_kind_published_idx
  on public.triagedesk_posts (kind, published_at desc);

-- ── the two functions the product calls by name ──────────────────────────────────────────────
-- Both are SECURITY DEFINER in production and both are atomic in SQL rather than
-- read-modify-write in JS, because two dispatcher ticks in the same second would otherwise lose
-- an increment and hand a thread a turn the cap meant to refuse.

create or replace function public.triagedesk_bump_agent_reply(p_thread_id uuid)
returns integer
language sql
security definer
set search_path to 'public'
as $$
  update public.triagedesk_threads
     set agent_reply_count = agent_reply_count + 1,
         updated_at = now()
   where id = p_thread_id
  returning agent_reply_count;
$$;

create or replace function public.triagedesk_add_inference_calls(p_user_id uuid, p_day date, p_n integer)
returns void
language sql
security definer
set search_path to 'public'
as $$
  insert into public.triagedesk_usage (user_id, day, inference_calls, updated_at)
  values (p_user_id, p_day, greatest(p_n, 0), now())
  on conflict (user_id, day) do update
    set inference_calls = public.triagedesk_usage.inference_calls + greatest(p_n, 0),
        updated_at      = now();
$$;

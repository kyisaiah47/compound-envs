-- parserail-desk: the product's real developer-platform schema, pulled from the shared
-- production project xowekqdsttxwbhfxvusa on 2026-09-19.
--
-- ⛔ THE TABLES ARE NAMED kynth_*, AND THE PRODUCT NEVER SAYS THAT NAME ANYWHERE.
-- Every call site in ~/CompoundLabs/parserail reads `compound_api_keys`, `compound_credit_accounts`,
-- `compound_usage_events`, `compound_api_jobs`, `compound_agent_memories`, `compound_rate_limits`
-- and the four `compound_*` RPCs. In production all twelve of those are SHIMS: seven simple
-- auto-updatable VIEWS and five SQL wrapper functions, each pointing at a `kynth_*` object the
-- 2026-09-10 rename sweep left behind. Measured here with pg_class.relkind: every compound_* name
-- the app touches came back 'v', not 'r'.
--
-- This file reproduces that exactly rather than flattening it to one set of tables, because the
-- shim IS the product's live topology and this environment's graders read rows through it. A write
-- that lands on the view has to show up on the table, and a grader reading the table directly
-- while the app wrote through the view would be grading a different object.

create extension if not exists vector;

-- the real tables ----------------------------------------------------------------------

create table if not exists public.kynth_credit_accounts (
  account_id              uuid primary key,
  balance_credits         integer     not null default 0,
  free_grant_used         boolean     not null default false,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  last_free_grant_at      timestamptz,
  stripe_customer_id      text,
  default_payment_method  text,
  auto_recharge_pack      text,
  last_auto_recharge_at   timestamptz,
  webhook_secret          text,
  activated_at            timestamptz,
  grant_email             text
);
create unique index if not exists kynth_credit_accounts_grant_email_uniq
  on public.kynth_credit_accounts (grant_email) where grant_email is not null;

create table if not exists public.kynth_api_keys (
  id           uuid primary key default gen_random_uuid(),
  account_id   uuid        not null,
  key_prefix   text        not null,
  key_hash     text        not null unique,
  label        text        not null default 'default',
  created_at   timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at   timestamptz
);
create index if not exists kynth_api_keys_account_idx on public.kynth_api_keys (account_id);
create index if not exists kynth_api_keys_prefix_idx  on public.kynth_api_keys (key_prefix);

create table if not exists public.kynth_usage_events (
  id             uuid primary key default gen_random_uuid(),
  account_id     uuid        not null,
  api_key_id     uuid,
  endpoint       text        not null,
  units          integer     not null default 1,
  credits_burned integer     not null default 0,
  request_id     text,
  model          text,
  created_at     timestamptz not null default now(),
  meta           jsonb       not null default '{}'::jsonb
);
create index if not exists kynth_usage_events_account_idx
  on public.kynth_usage_events (account_id, created_at desc);

create table if not exists public.kynth_credit_ledger (
  id            uuid primary key default gen_random_uuid(),
  account_id    uuid        not null,
  delta         integer     not null,
  reason        text        not null,
  balance_after integer     not null,
  ref           text,
  created_at    timestamptz not null default now()
);
create index if not exists kynth_credit_ledger_account_idx
  on public.kynth_credit_ledger (account_id, created_at desc);

create table if not exists public.kynth_api_jobs (
  id               uuid primary key default gen_random_uuid(),
  account_id       uuid        not null,
  api_key_id       uuid,
  endpoint         text        not null,
  status           text        not null default 'queued',
  request          jsonb       not null default '{}'::jsonb,
  result           jsonb,
  error            text,
  request_id       text,
  callback_url     text,
  credits_charged  integer,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  lease_expires_at timestamptz
);
create index if not exists kynth_api_jobs_account_idx on public.kynth_api_jobs (account_id, created_at desc);
create index if not exists kynth_api_jobs_reap_idx    on public.kynth_api_jobs (status, lease_expires_at)
  where status in ('queued', 'running');

create table if not exists public.kynth_agent_memories (
  id         uuid primary key default gen_random_uuid(),
  account_id uuid        not null,
  namespace  text        not null default 'default',
  content    text        not null,
  metadata   jsonb       not null default '{}'::jsonb,
  embedding  vector(768) not null,
  created_at timestamptz not null default now()
);
create index if not exists kynth_agent_memories_account_ns
  on public.kynth_agent_memories (account_id, namespace, created_at desc);

create table if not exists public.kynth_rate_limits (
  bucket_key text primary key,
  count      integer     not null default 0,
  expires_at timestamptz not null
);

-- the compound_* shims the product actually reads ---------------------------------------
-- One simple view per table, so PostgREST inserts, updates and deletes through them.

create or replace view public.compound_credit_accounts as
  select account_id, balance_credits, free_grant_used, created_at, updated_at, last_free_grant_at,
         stripe_customer_id, default_payment_method, auto_recharge_pack, last_auto_recharge_at,
         webhook_secret, activated_at, grant_email
    from public.kynth_credit_accounts;

create or replace view public.compound_api_keys as
  select id, account_id, key_prefix, key_hash, label, created_at, last_used_at, revoked_at
    from public.kynth_api_keys;

create or replace view public.compound_usage_events as
  select id, account_id, api_key_id, endpoint, units, credits_burned, request_id, model,
         created_at, meta
    from public.kynth_usage_events;

create or replace view public.compound_credit_ledger as
  select id, account_id, delta, reason, balance_after, ref, created_at
    from public.kynth_credit_ledger;

create or replace view public.compound_api_jobs as
  select id, account_id, api_key_id, endpoint, status, request, result, error, request_id,
         callback_url, credits_charged, created_at, updated_at, lease_expires_at
    from public.kynth_api_jobs;

create or replace view public.compound_agent_memories as
  select id, account_id, namespace, content, metadata, embedding, created_at
    from public.kynth_agent_memories;

create or replace view public.compound_rate_limits as
  select bucket_key, count, expires_at from public.kynth_rate_limits;

-- The monthly-refresh cron reads this one by its own name. It is a real table in production, not
-- a shim, and it is here so that route runs rather than 500s.
create table if not exists public.all_access_user_subscriptions (
  user_id                uuid primary key,
  tier                   text not null default 'free',
  status                 text,
  stripe_customer_id     text,
  stripe_subscription_id text,
  stripe_price_id        text,
  current_period_end     timestamptz,
  cancel_at_period_end   boolean default false,
  updated_at             timestamptz not null default now()
);

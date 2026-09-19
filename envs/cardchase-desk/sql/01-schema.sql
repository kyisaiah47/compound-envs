-- cardchase-desk: the failed-charge recovery schema.
--
-- Read out of the live Supabase project on 2026-09-19 via information_schema.columns,
-- pg_constraint and pg_indexes (project xowekqdsttxwbhfxvusa, tables matching 'cardchase%').
-- Column names, types, nullability, defaults, foreign keys and indexes are the live ones.
--
-- Nothing in this file touches real data. The fixture in 02-seed.sql is fabricated.
--
-- ⛔ cardchase_posts IS HERE AND CARRIES NO FIXTURE ROWS. It is the marketing blog's table and
-- no task touches it, but /blog and /changelog are routes the app builds, and a missing table
-- turns a prerender into a build failure rather than an empty list.
--
-- ⛔ cardchase_demo_seed IS HERE FOR THE SAME REASON and is deliberately left EMPTY. On the live
-- product it is the advisory lock the /demo route takes before re-seeding the shared demo book.
-- This environment's /demo route is a redirect and never seeds, and the table exists only so a
-- read of it answers rather than errors.

create extension if not exists pgcrypto;

create table cardchase_customers (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references auth.users(id) on delete cascade,
  stripe_customer_id text,
  name               text not null,
  email              text,
  company            text,
  -- What this subscription is worth per month. The queue ranks on THIS, not on the charge.
  mrr_cents          integer not null default 0,
  subscriber_since   date,
  do_not_contact     boolean not null default false,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz
);

-- ONE FAILED SUBSCRIPTION CHARGE. The spine of the product.
create table cardchase_failures (
  id                       uuid primary key default gen_random_uuid(),
  user_id                  uuid not null references auth.users(id) on delete cascade,
  customer_id              uuid references cardchase_customers(id) on delete cascade,
  stripe_invoice_id        text,
  stripe_subscription_id   text,
  stripe_payment_intent_id text,
  amount_cents             integer not null,
  currency                 text not null default 'usd',
  -- Stripe's decline code. The first of the gate's three stop signals.
  decline_code             text,
  -- The raw 2-4 digit issuer response code. The third signal.
  network_decline_code     text,
  -- The issuer's own guidance. The first signal read, and it outranks the other two.
  network_advice_code      text,
  card_brand               text,
  card_last4               text,
  state                    text not null default 'open',
  stopped_reason           text,
  first_failed_at          timestamptz not null default now(),
  next_retry_at            timestamptz,
  retry_count              integer not null default 0,
  rung                     integer not null default 0,
  recovered_at             timestamptz,
  recovered_cents          integer,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz
);

-- A retry against the card, staged behind the kill window.
create table cardchase_retries (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references auth.users(id) on delete cascade,
  failure_id          uuid not null references cardchase_failures(id) on delete cascade,
  rung                integer not null default 0,
  status              text not null default 'queued',
  scheduled_for       timestamptz,
  -- THE KILL WINDOW. The dispatcher's claim query filters on release_at <= now().
  release_at          timestamptz,
  attempted_at        timestamptz,
  decline_code        text,
  network_advice_code text,
  amount_cents        integer,
  created_at          timestamptz not null default now(),
  -- Null means STAGED BUT NOT APPROVED. The dispatcher must not claim it however long it sits.
  approved_at         timestamptz,
  blocked_reason      text
);

-- The note to the customer, staged behind the same window as the retry.
create table cardchase_messages (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  failure_id     uuid not null references cardchase_failures(id) on delete cascade,
  rung           integer not null default 0,
  channel        text not null default 'email',
  subject        text,
  body           text,
  tone           text,
  status         text not null default 'draft',
  release_at     timestamptz,
  scheduled_for  timestamptz,
  sent_at        timestamptz,
  created_at     timestamptz not null default now(),
  approved_at    timestamptz,
  blocked_reason text
);

-- The receipt. One row per action, with the evidence it acted on.
create table cardchase_events (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  failure_id uuid references cardchase_failures(id) on delete cascade,
  retry_id   uuid,
  message_id uuid,
  kind       text not null,
  title      text not null,
  detail     text,
  evidence   jsonb,
  created_at timestamptz not null default now()
);

-- The schedule the owner sets, plus plan_rules, which carries recovery_mode and the earned
-- autopilot counter the approve and undo routes move.
create table cardchase_ladder (
  user_id      uuid primary key references auth.users(id) on delete cascade,
  rungs        jsonb not null default '[]'::jsonb,
  plan_rules   jsonb not null default '{}'::jsonb,
  retry_cap    integer not null default 4,
  updated_at   timestamptz not null default now(),
  last_pass_at timestamptz
);

create table cardchase_voice (
  user_id        uuid primary key references auth.users(id) on delete cascade,
  business_name  text,
  from_email     text,
  tone           text not null default 'warm-professional',
  formality      integer not null default 50,
  warmth         integer not null default 60,
  directness     integer not null default 50,
  signature      text,
  sample_context text,
  updated_at     timestamptz not null default now()
);

create table cardchase_integrations (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  provider       text not null,
  connected      boolean not null default false,
  account_label  text,
  last_synced_at timestamptz,
  config         jsonb,
  created_at     timestamptz not null default now(),
  unique (user_id, provider)
);

-- WHAT AN ACCOUNT HAS PAID FOR. Both crons read this before they do anything.
create table cardchase_subscriptions (
  user_id                uuid primary key references auth.users(id) on delete cascade,
  email                  text,
  tier                   text not null default 'none',
  status                 text not null default 'inactive',
  stripe_customer_id     text,
  stripe_subscription_id text,
  stripe_price_id        text,
  cancel_at_period_end   boolean not null default false,
  current_period_end     timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create table cardchase_workspace_keys (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  key_hash     text not null unique,
  key_prefix   text not null,
  label        text,
  created_at   timestamptz not null default now(),
  last_used_at timestamptz
);

create table cardchase_posts (
  id           uuid primary key default gen_random_uuid(),
  kind         text not null default 'blog',
  slug         text not null unique,
  title        text not null,
  summary      text,
  body_md      text not null,
  tags         text[] not null default '{}'::text[],
  status       text not null default 'draft',
  published_at timestamptz,
  updated_at   timestamptz not null default now(),
  author       text not null default 'CardChase',
  hero_image   text,
  meta         jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);

create table cardchase_demo_seed (
  key        text primary key,
  claimed_at timestamptz,
  done_at    timestamptz
);

-- The live indexes, verbatim. The two `claimable` partial indexes are the dispatcher's own
-- claim predicate: status queued, approved, window elapsed.
create index cardchase_customers_user_idx on public.cardchase_customers using btree (user_id);
create index cardchase_events_user_created_idx on public.cardchase_events using btree (user_id, created_at desc);
create index cardchase_failures_next_retry_idx on public.cardchase_failures using btree (next_retry_at) where (state = 'open'::text);
create index cardchase_failures_user_state_idx on public.cardchase_failures using btree (user_id, state);
create index cardchase_messages_claimable_idx on public.cardchase_messages using btree (release_at) where ((status = 'queued'::text) and (approved_at is not null));
create index cardchase_messages_failure_idx on public.cardchase_messages using btree (failure_id);
create index cardchase_messages_release_idx on public.cardchase_messages using btree (release_at) where (status = 'queued'::text);
create index cardchase_posts_kind_status_idx on public.cardchase_posts using btree (kind, status, published_at desc);
create index cardchase_retries_claimable_idx on public.cardchase_retries using btree (release_at) where ((status = 'queued'::text) and (approved_at is not null));
create index cardchase_retries_failure_idx on public.cardchase_retries using btree (failure_id);
create index cardchase_retries_release_idx on public.cardchase_retries using btree (release_at) where (status = 'queued'::text);
create index cardchase_subscriptions_customer_idx on public.cardchase_subscriptions using btree (stripe_customer_id);
create index cardchase_workspace_keys_user_id_idx on public.cardchase_workspace_keys using btree (user_id);

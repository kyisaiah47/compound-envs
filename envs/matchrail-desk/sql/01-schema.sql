-- MatchRail's real tables, pulled from the shared production project xowekqdsttxwbhfxvusa on
-- 2026-09-19 with the Supabase MCP: information_schema.columns for the shapes, pg_indexes and
-- pg_constraint for the keys and the CHECKs, pg_class for relkind.
--
-- ⛔ EVERY ONE OF THESE IS A REAL TABLE, relkind 'r'. Checked, because another product on this
-- stack turned out to be serving VIEWS over older `kynth_*` tables left by a rename sweep. Nine
-- matchrail_* relations, nine 'r', and none of them is a view over anything.
--
-- ⛔ AND THERE IS NO TRIGGER ANYWHERE ON THIS PREFIX. pg_trigger returned zero non-internal rows
-- for every matchrail_* table. So unlike starreply, whose low-star rule is a database trigger, every
-- rule in this product lives in TypeScript and the database will happily accept a row no route
-- would ever write. That is exactly why the graders read rows rather than statuses: there is no
-- constraint standing behind the undo window, the tolerance, the cap or the plan.

create table if not exists public.matchrail_documents (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  kind           text not null check (kind = any (array['po','receipt','bill','payment'])),
  source         text not null check (source = any (array['quickbooks','xero','stripe','manual'])),
  external_id    text,
  vendor_name    text not null default '',
  doc_number     text,
  po_number      text,
  doc_date       date,
  currency       text not null default 'USD',
  subtotal_cents bigint not null default 0,
  tax_cents      bigint not null default 0,
  total_cents    bigint not null default 0,
  lines          jsonb not null default '[]'::jsonb,
  raw            jsonb not null default '{}'::jsonb,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
-- The upsert key every rail pull and the receipts route write through:
-- `{ onConflict: "user_id,source,kind,external_id" }`.
create unique index if not exists matchrail_documents_source_external
  on public.matchrail_documents (user_id, source, kind, external_id);
create index if not exists matchrail_documents_kind_date
  on public.matchrail_documents (user_id, kind, doc_date desc);
create index if not exists matchrail_documents_po
  on public.matchrail_documents (user_id, po_number) where po_number is not null;

create table if not exists public.matchrail_matches (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  match_key      text not null,
  po_id          uuid references public.matchrail_documents(id) on delete set null,
  receipt_id     uuid references public.matchrail_documents(id) on delete set null,
  bill_id        uuid not null references public.matchrail_documents(id) on delete cascade,
  status         text not null check (status = any (array['clean','exception','resolved','dismissed'])),
  variances      jsonb not null default '[]'::jsonb,
  variance_cents bigint not null default 0,
  suggested      jsonb,
  auto_cleared   boolean not null default false,
  matched_at     timestamptz not null default now(),
  resolved_at    timestamptz,
  created_at     timestamptz not null default now()
);
-- One match per bill. `runMatchPass` upserts on it, so a second pass rewrites rather than doubles.
create unique index if not exists matchrail_matches_bill on public.matchrail_matches (user_id, bill_id);
create index if not exists matchrail_matches_queue
  on public.matchrail_matches (user_id, status, variance_cents desc);

create table if not exists public.matchrail_corrections (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  match_id      uuid not null references public.matchrail_matches(id) on delete cascade,
  kind          text not null check (kind = any (array['adjust_bill_price','adjust_bill_quantity','void_duplicate','hold_payment','accept_variance'])),
  payload       jsonb not null default '{}'::jsonb,
  delta_cents   bigint not null default 0,
  status        text not null default 'scheduled'
                check (status = any (array['scheduled','posting','posted','undone','failed','held'])),
  -- ⛔ THE UNDO WINDOW, AND IT IS THE ONLY THING THAT EXPRESSES IT. There is no default and no
  -- constraint relating it to created_at: `scheduleCorrection` writes now + UNDO_WINDOW_SECONDS
  -- and the dispatcher's WHERE clause reads it. A row written with the two equal is a correction
  -- nobody could have taken back, and nothing in this schema would refuse it.
  scheduled_for timestamptz not null,
  posted_at     timestamptz,
  undone_at     timestamptz,
  error         text,
  created_at    timestamptz not null default now()
);
create index if not exists matchrail_corrections_due on public.matchrail_corrections (status, scheduled_for);
create index if not exists matchrail_corrections_user on public.matchrail_corrections (user_id, created_at desc);

create table if not exists public.matchrail_audit (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  match_id      uuid references public.matchrail_matches(id) on delete set null,
  correction_id uuid references public.matchrail_corrections(id) on delete set null,
  actor         text not null,
  action        text not null,
  detail        jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);
create index if not exists matchrail_audit_user on public.matchrail_audit (user_id, created_at desc);
create index if not exists matchrail_audit_match on public.matchrail_audit (match_id, created_at desc);

create table if not exists public.matchrail_runs (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  -- Null means the pass did not reach every rail. `runMatchPass` reads the last NON-NULL one as
  -- `since`, so a failed pull naturally re-reads its window tomorrow instead of skipping it.
  watermark   timestamptz,
  counts      jsonb not null default '{}'::jsonb,
  error       text
);
create index if not exists matchrail_runs_user on public.matchrail_runs (user_id, started_at desc);

create table if not exists public.matchrail_integrations (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  provider       text not null,
  connected      boolean not null default false,
  last_synced_at timestamptz,
  account_label  text,
  -- ⛔ NON-SECRET DISPLAY STATE ONLY. The callback's own comment: no token is ever written here.
  config         jsonb not null default '{}'::jsonb,
  created_at     timestamptz not null default now()
);
create unique index if not exists matchrail_integrations_user_provider
  on public.matchrail_integrations (user_id, provider);

-- ⛔ THE ONE TABLE WHOSE CONTENTS WOULD LET SOMEBODY ACT INSIDE A CUSTOMER'S ACCOUNTING SYSTEM.
-- RLS on, NO policies, so only the service role reaches it. `readToken` decrypts through
-- @compound/crypto and answers null for a null column, which every caller treats as "not
-- connected" rather than "connected with an empty token".
create table if not exists public.matchrail_oauth_tokens (
  user_id          uuid not null references auth.users(id) on delete cascade,
  provider         text not null,
  access_token     text,
  refresh_token    text,
  token_expires_at timestamptz,
  account_label    text,
  extra            jsonb not null default '{}'::jsonb,
  updated_at       timestamptz not null default now(),
  primary key (user_id, provider)
);

create table if not exists public.matchrail_subscriptions (
  user_id                uuid primary key references auth.users(id) on delete cascade,
  email                  text,
  tier                   text not null default 'none',
  status                 text not null default 'inactive',
  stripe_customer_id     text,
  stripe_subscription_id text,
  current_period_end     timestamptz,
  cancel_at_period_end   boolean not null default false,
  updated_at             timestamptz not null default now()
);
create index if not exists matchrail_subscriptions_customer_idx
  on public.matchrail_subscriptions (stripe_customer_id);
create index if not exists matchrail_subscriptions_email_idx
  on public.matchrail_subscriptions (lower(email));

create table if not exists public.matchrail_posts (
  id           uuid primary key default gen_random_uuid(),
  kind         text not null check (kind = any (array['blog','changelog'])),
  slug         text not null,
  title        text not null,
  summary      text,
  body_md      text not null default '',
  tags         text[] not null default '{}'::text[],
  status       text not null default 'draft' check (status = any (array['draft','published'])),
  published_at timestamptz,
  updated_at   timestamptz not null default now(),
  author       text not null default 'MatchRail',
  hero_image   text,
  meta         jsonb not null default '{}'::jsonb
);
create unique index if not exists matchrail_posts_kind_slug on public.matchrail_posts (kind, slug);

-- The demo book's seed claim. One visitor at a time may reseed.
create table if not exists public.matchrail_demo_seed (
  id         text primary key,
  claimed_at timestamptz,
  seeded_at  timestamptz
);

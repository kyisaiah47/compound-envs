-- LeadGrade's own tables, pulled from production `xowekqdsttxwbhfxvusa` on 2026-09-19.
--
-- Every one of the eight is a REAL TABLE (`pg_class.relkind = 'r'`), checked rather than assumed:
-- the 2026-09-10 kynth -> compound rename sweep left views behind in at least one sibling product
-- on this stack, and reading a view as a table is how a grader ends up measuring the wrong
-- relation. LeadGrade has none. RLS is on for all eight in production and is reproduced in
-- 03-rls.sql.
--
-- ⛔ `create table if not exists` throughout, and nothing here drops. The stack is shared with
-- every other environment in this repo (rule 11a) and a `drop ... cascade` on a re-run would take
-- a neighbour's fixture with it.

create extension if not exists pgcrypto;

-- ── leads ────────────────────────────────────────────────────────────────────
create table if not exists public.leadgrade_leads (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references auth.users(id) on delete cascade,
  source              text not null check (source = any (array['hubspot','form'])),
  source_id           text not null,
  crm_contact_id      text,
  email               text not null,
  first_name          text,
  last_name           text,
  company             text,
  domain              text,
  title               text,
  phone               text,
  message             text,
  form_name           text,
  created_at          timestamptz not null,
  ingested_at         timestamptz not null default now(),
  score               integer check (score >= 0 and score <= 100),
  band                text check (band = any (array['hot','warm','cool','cold'])),
  reasons             jsonb not null default '[]'::jsonb,
  scored_at           timestamptz,
  enrichment          jsonb,
  -- ⛔ WRITTEN BY NOTHING IN THE PRODUCT. `LEAD_ENRICHMENT_ATTEMPT_CAP` and
  -- `leadEnrichmentExhausted()` exist in _lib/agent/guardrails.ts and the landing page and
  -- /how-it-works both publish "3 attempts per lead" as a live guardrail, and no call site
  -- increments or reads this column. Kept because production has it. See results.json.
  enrichment_attempts integer not null default 0,
  status              text not null default 'new'
                      check (status = any (array['new','scored','approved','dismissed'])),
  updated_at          timestamptz not null default now(),
  unique (user_id, source, source_id)
);
create index if not exists leadgrade_leads_user_created on public.leadgrade_leads (user_id, created_at desc);
create index if not exists leadgrade_leads_user_score   on public.leadgrade_leads (user_id, score desc nulls last);

-- ── write-backs ──────────────────────────────────────────────────────────────
create table if not exists public.leadgrade_writebacks (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  lead_id        uuid not null references public.leadgrade_leads(id) on delete cascade,
  crm_contact_id text,
  field          text not null,
  value          text not null,
  previous_value text,
  state          text not null default 'queued'
                 check (state = any (array['queued','sent','cancelled','reverted','blocked','failed'])),
  queued_at      timestamptz not null default now(),
  send_after     timestamptz not null,
  sent_at        timestamptz,
  cancelled_at   timestamptz,
  blocked_reason text,
  error          text,
  run_id         uuid
);
create index if not exists leadgrade_writebacks_due  on public.leadgrade_writebacks (state, send_after);
create index if not exists leadgrade_writebacks_lead on public.leadgrade_writebacks (lead_id, queued_at desc);

-- ── the ledger ───────────────────────────────────────────────────────────────
create table if not exists public.leadgrade_events (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  lead_id    uuid references public.leadgrade_leads(id) on delete set null,
  kind       text not null,
  title      text not null,
  detail     text,
  evidence   jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists leadgrade_events_user_created on public.leadgrade_events (user_id, created_at desc);

-- ── one row per overnight pass ───────────────────────────────────────────────
create table if not exists public.leadgrade_runs (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references auth.users(id) on delete cascade,
  started_at       timestamptz not null default now(),
  finished_at      timestamptz,
  watermark_from   timestamptz not null,
  watermark_to     timestamptz not null,
  leads_seen       integer not null default 0,
  leads_scored     integer not null default 0,
  enrichments_used integer not null default 0,
  enrichment_cap   integer not null,
  stopped_reason   text
);
create index if not exists leadgrade_runs_user_started on public.leadgrade_runs (user_id, started_at desc);

-- ── per-account settings ─────────────────────────────────────────────────────
-- ⛔ `autonomy`, `autopilot_threshold`, `daily_enrichment_cap` and `icp` are read by the scoring
-- pass and rendered by the console, and NO route or server action in the product writes any of
-- them. The only writers are seedAccount() (insert-only, ignoreDuplicates) and setWatermark()
-- (watermark alone). See results.json: this is the table that looks like a workflow.
create table if not exists public.leadgrade_settings (
  user_id              uuid primary key references auth.users(id) on delete cascade,
  autonomy             text not null default 'copilot' check (autonomy = any (array['copilot','autopilot'])),
  autopilot_threshold  integer not null default 70 check (autopilot_threshold >= 0 and autopilot_threshold <= 100),
  daily_enrichment_cap integer not null default 250 check (daily_enrichment_cap > 0),
  icp                  jsonb not null default '{}'::jsonb,
  watermark            timestamptz,
  updated_at           timestamptz not null default now()
);

-- ── the CRM rail ─────────────────────────────────────────────────────────────
-- ⛔ THE ONLY WRITER IS THE OAUTH CALLBACK, which this environment cannot legitimately reach.
-- The fixture seeds the row the callback would have written and leaves `access_token` and
-- `refresh_token` NULL, so `accessTokenFor()` answers null and every rail path refuses before a
-- fetch is built. Nothing here ever holds a HubSpot credential.
create table if not exists public.leadgrade_integrations (
  user_id        uuid not null references auth.users(id) on delete cascade,
  provider       text not null check (provider = 'hubspot'),
  account_label  text,
  access_token   text,
  refresh_token  text,
  expires_at     timestamptz,
  portal_id      text,
  connected_at   timestamptz not null default now(),
  last_synced_at timestamptz,
  primary key (user_id, provider)
);

-- ── what a payment bought ────────────────────────────────────────────────────
-- Keyed on the EMAIL, because LeadGrade has no free account: the buyer pays before an
-- auth.users row exists, so user_id is null until the auth callback claims the row.
create table if not exists public.leadgrade_subscriptions (
  email                  text primary key,
  user_id                uuid unique references auth.users(id) on delete set null,
  tier                   text not null default 'pro',
  status                 text not null default 'incomplete',
  stripe_customer_id     text,
  stripe_subscription_id text unique,
  current_period_end     timestamptz,
  cancel_at_period_end   boolean not null default false,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);
create index if not exists leadgrade_subscriptions_customer on public.leadgrade_subscriptions (stripe_customer_id);
create index if not exists leadgrade_subscriptions_user     on public.leadgrade_subscriptions (user_id);

-- ── marketing content ────────────────────────────────────────────────────────
-- Read by /blog and /changelog through the anon key. Nothing in the product writes it.
create table if not exists public.leadgrade_posts (
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
  author       text not null default 'Compound Labs',
  hero_image   text,
  meta         jsonb not null default '{}'::jsonb,
  unique (kind, slug)
);

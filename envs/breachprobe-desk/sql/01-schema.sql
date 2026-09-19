-- breachprobe-desk, the product's real tables, pulled from the shared production project
-- xowekqdsttxwbhfxvusa on 2026-09-19 with the Supabase MCP.
--
-- Five breachprobe_* tables, all of them genuine TABLES (pg_class.relkind = 'r'), unlike
-- parserail's compound_* relations which turned out to be views over kynth_* leftovers.
--
-- ⛔ THE SUPPRESSION RELATION IS THE ONE PIECE OF THAT RENAME SWEEP THIS PRODUCT TOUCHES.
-- `src/lib/review-ask.ts` reads `compound_email_suppressions`, and in production that name is a
-- VIEW (relkind 'v') over `kynth_email_suppressions`. It is reproduced here with the same
-- topology rather than flattened into one table, because the shim is the product's live shape
-- and because isSuppressed() fails CLOSED: a suppression relation it cannot read is read as
-- "this address has opted out", so a missing view silently stops every review ask. The graders
-- read the kynth_* table underneath, so a write that arrives through the view and a cheat that
-- writes the table show up in the same place.
--
-- `compound_review_asks` is a real table, shared estate-wide. Its partial unique index on
-- (lower(email), app) is the one-ask-ever rule, and it is what makes the nightly's claim
-- gradable at all.

create extension if not exists pgcrypto;

-- ── breachprobe_scans ────────────────────────────────────────────────────────────────────────
-- One row per scan. `status` walks scanned -> paid -> report_ready, and refunded/disputed are
-- terminal. `full_findings` is the paid report; `findings` is the free shape toFree() builds.
create table if not exists public.breachprobe_scans (
  id                   uuid primary key default gen_random_uuid(),
  created_at           timestamptz not null default now(),
  url                  text not null,
  host                 text,
  owner_confirmed      boolean not null default false,
  score                integer,
  grade                text,
  findings             jsonb,
  full_findings        jsonb,
  rls_probe            jsonb,
  supabase_ref         text,
  status               text not null default 'scanned',
  email                text,
  paid_session         text,
  report_generated_at  timestamptz,
  monitor_opt_in       boolean not null default false,
  report_emailed_at    timestamptz,
  tier                 text,
  -- ⛔ THE ONLY HANDLE A STRIPE DISPUTE GIVES. A Dispute object's `metadata` is the dispute's
  -- own and is always empty, so a refund/dispute handler that resolves the purchase by
  -- metadata.scan_id silently matches nothing on the one event that exists to stop delivery.
  paid_payment_intent  text,
  stripe_detected      boolean not null default false,
  stripe_probe         jsonb
);

create index if not exists breachprobe_scans_host_idx on public.breachprobe_scans using btree (host);
create index if not exists breachprobe_scans_session_idx on public.breachprobe_scans using btree (paid_session);
create index if not exists breachprobe_scans_paid_payment_intent_idx
  on public.breachprobe_scans using btree (paid_payment_intent)
  where paid_payment_intent is not null;

-- ── breachprobe_monitors ─────────────────────────────────────────────────────────────────────
-- A report_plus buyer's thirty nights. `expires_at` is what closes the window; `active` is what
-- expire() flips once it has passed.
create table if not exists public.breachprobe_monitors (
  id                 uuid primary key default gen_random_uuid(),
  created_at         timestamptz not null default now(),
  scan_id            uuid,
  url                text not null,
  email              text not null,
  active             boolean not null default true,
  last_scanned_at    timestamptz,
  last_score         integer,
  baseline_findings  jsonb,
  expires_at         timestamptz
);

-- ── breachprobe_leads ────────────────────────────────────────────────────────────────────────
-- The ledger. `kind = 'report'` is written on every fulfilment; `kind = 'monitor'` is written
-- only when a nightly re-scan finds a regression, and it is the record behind the alert email.
create table if not exists public.breachprobe_leads (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  scan_id     uuid,
  email       text,
  url         text,
  kind        text not null default 'report',
  note        text
);

-- ── breachprobe_smoketests ───────────────────────────────────────────────────────────────────
-- The queue POST /api/smoketest writes into. The browser run happens in ops/smoketest/run.mjs
-- against a portals daemon, outside this repo, so the web side only ever enqueues and polls.
create table if not exists public.breachprobe_smoketests (
  id               uuid primary key default gen_random_uuid(),
  created_at       timestamptz not null default now(),
  url              text not null,
  email            text,
  owner_confirmed  boolean not null default false,
  status           text not null default 'queued',
  flows            jsonb,
  report           jsonb,
  video_path       text,
  started_at       timestamptz,
  finished_at      timestamptz
);

-- ── breachprobe_rescue_leads ─────────────────────────────────────────────────────────────────
-- Present in production and written by nothing any more: POST /api/rescue-lead answers 410 on
-- both verbs since Compound Labs stopped selling services on 2026-09-12. It is reproduced so the
-- schema is the product's real schema, and it is in not_gradable rather than in a task, which is
-- exactly the trap rule 1 exists for.
create table if not exists public.breachprobe_rescue_leads (
  id             uuid primary key default gen_random_uuid(),
  created_at     timestamptz not null default now(),
  scan_id        uuid,
  email          text,
  url            text,
  budget         text,
  provider_slug  text,
  note           text
);

-- ── the shared review-ask table and the suppression shim ─────────────────────────────────────
create table if not exists public.compound_review_asks (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid,
  app             text not null,
  eligible_at     timestamptz,
  banner_shown_at timestamptz,
  email_sent_at   timestamptz,
  channel         text,
  suppressed      boolean not null default false,
  created_at      timestamptz not null default now(),
  email           text,
  asked_at        timestamptz,
  source          text,
  ref             text
);

create unique index if not exists kynth_review_asks_user_id_app_key
  on public.compound_review_asks using btree (user_id, app);

-- ONE ASK EVER, and it is the database's job. claimReviewAsk() INSERTs and lets the index decide;
-- a duplicate comes back as 23505 and is caught, which is the index working rather than a fault.
create unique index if not exists kynth_review_asks_email_app
  on public.compound_review_asks using btree (lower(email), app)
  where email is not null;

create table if not exists public.kynth_email_suppressions (
  email       text not null,
  source      text,
  reason      text,
  created_at  timestamptz not null default now()
);

create unique index if not exists kynth_email_suppressions_email_key
  on public.kynth_email_suppressions using btree (email);

create or replace view public.compound_email_suppressions as
  select email, source, reason, created_at from public.kynth_email_suppressions;

-- standup-desk: The Standup's real tables.
--
-- Read out of the live Supabase project on 2026-09-19 (project xowekqdsttxwbhfxvusa, tables
-- matching 'standup\_%') with information_schema.columns, pg_constraint and pg_indexes. Column
-- names, types, nullability, defaults, primary keys, unique constraints, foreign keys and the one
-- check constraint are the live ones.
--
-- Nothing in this file touches real data. The fixture in 02-seed.sql is fabricated.
--
-- TWO OF THESE TABLES ARE UNREACHABLE FROM THE PRODUCT, and they are here because leaving them
-- out would hide that. `standup_watchlists` (watch a vendor or a repo) and `standup_alert_sends`
-- (the per-watcher alert ledger) have RLS, foreign keys, a check constraint and a unique index,
-- and ZERO references anywhere in src/ or scripts/. Measured by counting every `standup_` token
-- in the repo on 2026-09-19: posts 10, profiles 9, subscribers 5, consequences 4,
-- pending_members 3, post_metrics 2, email_sends 2, contacts 1, watchlists 0, alert_sends 0.
-- The schema says this product lets a reader follow a vendor and be alerted. It does not. That is
-- exactly the trap BUILDING-AN-ENVIRONMENT.md rule 1 names, and no task here touches either table.

create extension if not exists pgcrypto;

-- The wire itself. Written by scripts/mirror-posts.mjs after every posting tick; read by every
-- surface through one unstable_cache entry (src/lib/wire.ts). No route writes it.
create table if not exists public.standup_posts (
  slug        text primary key,
  id          text not null,
  card_id     text,
  title       text not null,
  dek         text default ''::text,
  tier        integer default 3,
  cat         text default 'release'::text,
  cat_label   text default 'RELEASE'::text,
  category    text default 'dev'::text,
  source      text default ''::text,
  url         text default ''::text,
  ts          bigint default 0,
  detail      jsonb default '{}'::jsonb,
  img         text,
  thumb       text,
  social_card text,
  kind        text default 'text'::text,
  credit      text,
  updated_at  timestamptz default now(),
  accounts    jsonb not null default '[]'::jsonb
);
create index if not exists standup_posts_ts_idx  on public.standup_posts using btree (ts desc);
create index if not exists standup_posts_cat_idx on public.standup_posts using btree (cat, ts desc);

-- An account. Created ONLY by the on_auth_user_created_standup trigger (04-auth-trigger.sql);
-- there is no route that inserts one.
create table if not exists public.standup_profiles (
  id                 uuid primary key references auth.users(id) on delete cascade,
  email              text,
  stripe_customer_id text,
  plan               text default 'free'::text,
  created_at         timestamptz not null default now()
);

-- The daily-email list. POST /api/subscribe upserts on email; the two mail-link routes update
-- `confirmed` and `unsubscribed_at` by confirm_token.
create table if not exists public.standup_subscribers (
  id              uuid primary key default gen_random_uuid(),
  email           text not null unique,
  confirmed       boolean not null default false,
  confirm_token   uuid not null default gen_random_uuid(),
  source          text default 'rail'::text,
  created_at      timestamptz not null default now(),
  unsubscribed_at timestamptz,
  last_sent_at    timestamptz
);

-- The send ledger. NOTHING IN THIS REPO INSERTS A ROW HERE. POST /api/email/webhook only
-- UPDATEs opened_at / clicked_at by resend_id; the sender that writes the rows is a launchd job
-- outside this tree. So "send the digest" is not a task this environment can grade, and the
-- fixture ships these rows as the history a real morning's send would have left.
create table if not exists public.standup_email_sends (
  id            uuid primary key default gen_random_uuid(),
  subscriber_id uuid references public.standup_subscribers(id) on delete cascade,
  email         text,
  kind          text not null default 'digest'::text,
  digest_date   date,
  resend_id     text,
  sent_at       timestamptz not null default now(),
  opened_at     timestamptz,
  clicked_at    timestamptz
);

-- POST /api/contact. There is no form anywhere in src/ that calls it.
create table if not exists public.standup_contacts (
  id         uuid primary key default gen_random_uuid(),
  name       text,
  email      text,
  subject    text,
  message    text,
  emailed    boolean not null default false,
  created_at timestamptz not null default now()
);

-- A membership paid for before the buyer had an account. Parked by src/lib/plan.ts's
-- setPlanByEmail and claimed by the auth trigger the moment that address registers.
create table if not exists public.standup_pending_members (
  email              text primary key,
  plan               text not null default 'active'::text,
  stripe_customer_id text,
  created_at         timestamptz not null default now(),
  claimed_at         timestamptz,
  claimed_by         uuid references auth.users(id) on delete set null
);
create index if not exists standup_pending_members_unclaimed
  on public.standup_pending_members using btree (email) where (claimed_at is null);

-- Social metrics behind the Featured / Staff Picks ranking (src/lib/ranking.ts).
create table if not exists public.standup_post_metrics (
  post_slug  text not null references public.standup_posts(slug) on delete cascade,
  platform   text not null,
  views      integer default 0,
  likes      integer default 0,
  comments   integer default 0,
  reposts    integer default 0,
  fetched_at timestamptz not null default now(),
  primary key (post_slug, platform)
);

-- The one-line consequence under a row, written by scripts/consequences.mjs.
create table if not exists public.standup_consequences (
  slug        text primary key,
  line        text not null,
  model       text not null,
  source_hash text not null,
  created_at  timestamptz not null default now()
);

-- UNREACHABLE FROM THE PRODUCT. See the header.
create table if not exists public.standup_watchlists (
  id         uuid primary key default gen_random_uuid(),
  profile_id uuid not null references public.standup_profiles(id) on delete cascade,
  kind       text not null,
  key        text not null,
  created_at timestamptz not null default now(),
  constraint standup_watchlists_kind_check check (kind = any (array['vendor'::text, 'repo'::text])),
  constraint standup_watchlists_profile_id_kind_key_key unique (profile_id, kind, key)
);

-- UNREACHABLE FROM THE PRODUCT. See the header.
create table if not exists public.standup_alert_sends (
  id         uuid primary key default gen_random_uuid(),
  profile_id uuid not null references public.standup_profiles(id) on delete cascade,
  post_slug  text not null references public.standup_posts(slug) on delete cascade,
  resend_id  text,
  sent_at    timestamptz not null default now(),
  constraint standup_alert_sends_profile_id_post_slug_key unique (profile_id, post_slug)
);

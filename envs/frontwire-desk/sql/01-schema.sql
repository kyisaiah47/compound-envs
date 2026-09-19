-- frontwire-desk: the product's real tables, pulled out of the shared production project
-- xowekqdsttxwbhfxvusa on 2026-09-19 with information_schema.columns and pg_constraint.
--
-- ⛔ NOTHING HERE IS INVENTED AND NOTHING IS SIMPLIFIED. Every column, default, primary key,
-- unique and foreign key is the one production carries, because a grader that reads a column the
-- product does not have is a grader that can only ever be right by accident.
--
-- ⛔ THE STACK IS SHARED. Six products' fixtures live in this one local database beside each
-- other, so every object here is prefixed `frontwire_` exactly as production names it, and
-- nothing in this file touches a table that is not.
--
-- The one thing this file adds outside the `frontwire_` prefix is a trigger on auth.users, and
-- production carries that too (`on_auth_user_created_frontwire`, read off pg_trigger the same
-- day). standup-desk already installs its own sibling of it on this same shared stack. See
-- 04-auth-trigger.sql.

create extension if not exists pgcrypto;

-- The wire itself. `scripts/mirror-posts.mjs` in compound-ops writes it; the site reads it
-- through src/lib/wire.ts and falls back to the committed src/data/posts.json when it cannot.
create table if not exists public.frontwire_posts (
  slug        text primary key,
  id          text not null,
  card_id     text,
  title       text not null,
  dek         text default ''::text,
  tier        integer default 3,
  cat         text default 'wire'::text,
  cat_label   text default 'WIRE'::text,
  category    text default 'us'::text,
  source      text default ''::text,
  url         text default ''::text,
  ts          bigint default 0,
  detail      jsonb default '{}'::jsonb,
  img         text,
  social_card text,
  kind        text default 'text'::text,
  credit      text,
  updated_at  timestamptz default now(),
  thumb       text
);
create index if not exists frontwire_posts_ts_idx on public.frontwire_posts (ts desc);

-- The daily email's list. `confirm_token` is a uuid and it is the ONLY key the two mail-link
-- routes accept: /api/subscribe/confirm and /api/subscribe/unsubscribe both match on it, so it
-- is the address of a subscriber as far as an inbox is concerned. Rotating it is not a tidy-up,
-- it is invalidating every link already sitting in somebody's mail.
create table if not exists public.frontwire_subscribers (
  id              uuid primary key default gen_random_uuid(),
  email           text not null unique,
  confirmed       boolean not null default false,
  confirm_token   uuid not null default gen_random_uuid(),
  source          text default 'rail'::text,
  created_at      timestamptz not null default now(),
  unsubscribed_at timestamptz,
  last_sent_at    timestamptz
);

-- The send ledger. compound-ops/lanes/frontwire/scripts/send-digest.mjs inserts one row per
-- recipient per digest; POST /api/email/webhook stamps opened_at / clicked_at on it by resend_id.
create table if not exists public.frontwire_email_sends (
  id            uuid primary key default gen_random_uuid(),
  subscriber_id uuid references public.frontwire_subscribers(id) on delete set null,
  email         text,
  kind          text not null default 'digest'::text,
  digest_date   date,
  resend_id     text,
  sent_at       timestamptz not null default now(),
  opened_at     timestamptz,
  clicked_at    timestamptz
);

-- The letters readers write from /contact. POST /api/contact inserts; nothing in the product
-- updates a row afterwards, so `emailed` is false on everything a person ever sent.
create table if not exists public.frontwire_contacts (
  id         uuid primary key default gen_random_uuid(),
  name       text,
  email      text,
  subject    text,
  message    text,
  emailed    boolean not null default false,
  created_at timestamptz not null default now()
);

-- Membership. `id` is a foreign key to auth.users, which is the whole reason
-- frontwire_pending_members exists: /api/checkout requires no account and creates none, so a
-- buyer who pays straight off /upgrade has no row to flip.
create table if not exists public.frontwire_profiles (
  id                 uuid primary key references auth.users(id) on delete cascade,
  email              text,
  stripe_customer_id text,
  plan               text default 'free'::text,
  created_at         timestamptz not null default now()
);

-- The entitlement with nowhere to land yet. setPlanByEmail() upserts here on
-- checkout.session.completed when no profile matches, and handle_new_frontwire_user() claims it
-- the moment that address registers.
create table if not exists public.frontwire_pending_members (
  email              text primary key,
  plan               text not null default 'active'::text,
  stripe_customer_id text,
  created_at         timestamptz not null default now(),
  claimed_at         timestamptz,
  claimed_by         uuid references auth.users(id) on delete set null
);

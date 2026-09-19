-- starreply's real tables, read out of the shared production project xowekqdsttxwbhfxvusa on
-- 2026-09-19 (information_schema.columns + pg_constraint). Column order, types, defaults,
-- nullability, check constraints, unique keys and foreign keys are the production ones.
--
-- Two of these are load-bearing for the graders and neither is decoration:
--
--   starreply_replies UNIQUE (review_id)          one reply per review. Google stores a single
--                                                 reply per review and a second PUT overwrites
--                                                 the first, so a second row is a silent edit of
--                                                 something the public already read.
--   starreply_reviews UNIQUE (provider, external_id)
--                                                 the poll is idempotent on this pair, which is
--                                                 what makes re-reading a window safe.
--
-- The low-star trigger lives in 03-rls.sql beside the policies, because it is a guarantee and
-- not a shape.

create extension if not exists pgcrypto;

create table if not exists starreply_locations (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references auth.users(id) on delete cascade,
  provider          text not null check (provider in ('google_business_profile', 'trustpilot')),
  external_id       text not null,
  name              text not null,
  address           text,
  public_url        text,
  review_watermark  timestamptz,
  last_polled_at    timestamptz,
  paused            boolean not null default false,
  created_at        timestamptz not null default now(),
  unique (user_id, provider, external_id)
);

create table if not exists starreply_reviews (
  id                        uuid primary key default gen_random_uuid(),
  user_id                   uuid not null references auth.users(id) on delete cascade,
  location_id               uuid not null references starreply_locations(id) on delete cascade,
  provider                  text not null check (provider in ('google_business_profile', 'trustpilot')),
  external_id               text not null,
  author_name               text,
  star_rating               smallint not null check (star_rating >= 1 and star_rating <= 5),
  title                     text,
  body                      text,
  posted_at                 timestamptz not null,
  classification            text,
  classification_confidence smallint check (classification_confidence >= 0 and classification_confidence <= 100),
  replied                   boolean not null default false,
  ingested_at               timestamptz not null default now(),
  unique (provider, external_id)
);

create table if not exists starreply_replies (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references auth.users(id) on delete cascade,
  review_id          uuid not null references starreply_reviews(id) on delete cascade,
  body               text not null,
  status             text not null default 'drafted'
                     check (status in ('drafted','held','approved','queued','posting','posted','cancelled','failed')),
  hold_reason        text,
  approval_required  boolean not null default false,
  queued_at          timestamptz,
  send_after         timestamptz,
  posted_at          timestamptz,
  external_reply_id  text,
  failure_reason     text,
  edited             boolean not null default false,
  templated          boolean not null default false,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (review_id)
);

create table if not exists starreply_events (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  kind         text not null,
  title        text not null,
  detail       text,
  evidence     jsonb,
  location_id  uuid references starreply_locations(id) on delete set null,
  review_id    uuid references starreply_reviews(id) on delete set null,
  reply_id     uuid references starreply_replies(id) on delete set null,
  created_at   timestamptz not null default now()
);

create table if not exists starreply_integrations (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references auth.users(id) on delete cascade,
  provider         text not null check (provider in ('google_business_profile', 'trustpilot')),
  account_label    text,
  access_token     text,
  refresh_token    text,
  expires_at       timestamptz,
  business_user_id text,
  last_synced_at   timestamptz,
  created_at       timestamptz not null default now(),
  unique (user_id, provider)
);

create table if not exists starreply_settings (
  user_id             uuid primary key references auth.users(id) on delete cascade,
  mode                text not null default 'copilot' check (mode in ('manual','copilot','autopilot')),
  daily_auto_post_cap smallint not null default 20,
  updated_at          timestamptz not null default now()
);

create table if not exists starreply_voice (
  user_id         uuid primary key references auth.users(id) on delete cascade,
  business_name   text,
  tone            text not null default 'warm-professional',
  formality       smallint not null default 50,
  warmth          smallint not null default 65,
  directness      smallint not null default 50,
  signature       text,
  sample_context  text,
  apology_allowed boolean not null default false,
  remedy_allowed  boolean not null default false,
  updated_at      timestamptz not null default now()
);

create table if not exists starreply_usage (
  user_id         uuid not null references auth.users(id) on delete cascade,
  day             date not null,
  inference_calls integer not null default 0,
  primary key (user_id, day)
);

create table if not exists starreply_subscriptions (
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

create table if not exists starreply_subscription_claims (
  email                  text primary key,
  tier                   text not null default 'none',
  status                 text not null default 'inactive',
  stripe_customer_id     text,
  stripe_subscription_id text,
  current_period_end     timestamptz,
  cancel_at_period_end   boolean not null default false,
  claimed_by             uuid references auth.users(id) on delete set null,
  claimed_at             timestamptz,
  updated_at             timestamptz not null default now()
);

create table if not exists starreply_posts (
  id           uuid primary key default gen_random_uuid(),
  kind         text not null check (kind in ('blog','changelog')),
  slug         text not null,
  title        text not null,
  summary      text,
  body_md      text not null,
  tags         text[] not null default '{}'::text[],
  status       text not null default 'draft' check (status in ('draft','published')),
  published_at timestamptz,
  updated_at   timestamptz not null default now(),
  author       text not null default 'Isaiah Kim',
  hero_image   text,
  meta         jsonb not null default '{}'::jsonb,
  unique (kind, slug)
);

create index if not exists starreply_reviews_user_posted on starreply_reviews (user_id, posted_at desc);
create index if not exists starreply_replies_due on starreply_replies (status, send_after);
create index if not exists starreply_events_user_created on starreply_events (user_id, created_at desc);

-- stacktab-desk: the product's real tables, as they stand in the shared production project
-- xowekqdsttxwbhfxvusa on 2026-09-19. Pulled column by column, index by index and constraint by
-- constraint through the Supabase MCP; nothing here is inferred from the TypeScript types.
--
-- ⛔ THEY ARE REAL TABLES, NOT VIEWS. parserail's `compound_*` names turned out to be views over
-- older `kynth_*` tables left behind by the 2026-09-10 rename sweep, so this was checked first:
--   select c.relname, c.relkind from pg_class c join pg_namespace n on n.oid = c.relnamespace
--   where n.nspname = 'public' and c.relname like 'stacktab%';
-- answered relkind 'r' for all five. The graders read these names directly.
--
-- ⛔ `stacktab_price_watch.id` IS `generated always as identity`, not a sequence default. An
-- insert that supplies its own id needs `overriding system value`, which is why the seed says so
-- and why a cheat that writes the row by hand has to as well.
--
-- ⛔ `stacktab_price_watch_unique` WAS A PLAIN UNIQUE CONSTRAINT OVER A NULLABLE COLUMN, which is
-- the defect this environment found. Postgres treats two NULLs as distinct unless the index says
-- `nulls not distinct`, and `service_slug` is null for the whole-catalogue watch, which is the
-- ONLY scope the product's own form can produce. So the upsert in POST /api/watch never found a
-- conflict and wrote a fresh row on every submission.
--
-- FIXED IN PRODUCTION 2026-09-19, migration `stacktab_price_watch_nulls_not_distinct`, and this
-- file carries the fixed shape because the fixture reproduces what production HAS. The task that
-- graded the old behaviour is being re-derived against the new one; see README.

create table if not exists public.stacktab_service (
  slug          text primary key,
  name          text not null,
  category      text not null check (category in ('database','auth','payments','hosting')),
  tagline       text,
  homepage_url  text not null,
  pricing_url   text not null,
  attrs         jsonb not null default '{}'::jsonb,
  rank          integer not null default 100,
  created_at    timestamptz not null default now()
);
create index if not exists stacktab_service_category_idx on public.stacktab_service (category);

create table if not exists public.stacktab_plan (
  id                bigserial primary key,
  service_slug      text not null references public.stacktab_service(slug) on delete cascade,
  plan_slug         text not null,
  name              text not null,
  rank              integer not null default 0,
  base_monthly_usd  numeric,
  price_status      text not null default 'published'
                      check (price_status in ('published','unknown','custom','usage_only')),
  included          jsonb not null default '{}'::jsonb,
  notes             text,
  source_url        text not null,
  -- The literal strings that must still appear on source_url for this plan's figures to hold.
  -- engine/refresh.mjs checks these and nothing else; it never rewrites a price.
  probes            text[] not null default '{}'::text[],
  check_status      text not null default 'never'
                      check (check_status in ('never','verified','drifted','unreadable')),
  verified_at       timestamptz,
  last_checked_at   timestamptz,
  last_check_note   text,
  restrictions      jsonb not null default '{}'::jsonb,
  unique (service_slug, plan_slug)
);
create index if not exists stacktab_plan_service_idx on public.stacktab_plan (service_slug);

create table if not exists public.stacktab_meter (
  id            bigserial primary key,
  plan_id       bigint not null references public.stacktab_plan(id) on delete cascade,
  meter_slug    text not null,
  label         text not null,
  unit          text not null,
  kind          text not null check (kind in ('per_unit','tiered','percent','fixed_per_txn')),
  included_qty  numeric,
  unit_price    numeric,
  pct_rate      numeric,
  fixed_usd     numeric,
  tiers         jsonb,
  price_status  text not null default 'published' check (price_status in ('published','unknown')),
  notes         text,
  unique (plan_id, meter_slug)
);
create index if not exists stacktab_meter_plan_idx on public.stacktab_meter (plan_id);

create table if not exists public.stacktab_refresh_run (
  id             bigserial primary key,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  services       integer not null default 0,
  plans_checked  integer not null default 0,
  verified       integer not null default 0,
  drifted        integer not null default 0,
  unreadable     integer not null default 0,
  detail         jsonb not null default '[]'::jsonb
);

create table if not exists public.stacktab_price_watch (
  id            bigint generated always as identity primary key,
  email         text not null,
  service_slug  text,
  created_at    timestamptz not null default now(),
  unsubscribed  boolean not null default false
);
-- Reproduced verbatim, including `nulls not distinct`; see the note at the top.
-- ⛔ DROPPED AND RECREATED RATHER THAN `if not exists`, AND THAT IS THE WHOLE POINT OF THIS
-- BLOCK. The shared stack was provisioned before the migration, so it already holds an index by
-- this name, and `create unique index if not exists` is a silent no-op against it: the file would
-- read `nulls not distinct` while the database kept treating two NULLs as distinct keys, and the
-- environment would grade behaviour nobody is running. It also arrives as a CONSTRAINT in
-- production before the migration and as a bare INDEX after it, so both are dropped. Converges
-- from either state, and from nothing.
alter table public.stacktab_price_watch drop constraint if exists stacktab_price_watch_unique;
drop index if exists public.stacktab_price_watch_unique;
create unique index stacktab_price_watch_unique
  on public.stacktab_price_watch (email, service_slug) nulls not distinct;
create index if not exists stacktab_price_watch_service_idx
  on public.stacktab_price_watch (service_slug) where unsubscribed = false;

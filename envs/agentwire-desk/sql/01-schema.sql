-- agentwire-desk / 01-schema.sql
--
-- The three tables Agentwire owns in the shared production project
-- (xowekqdsttxwbhfxvusa), pulled 2026-09-19 with the Supabase MCP out of
-- information_schema.columns, pg_constraint and pg_indexes. Column types, defaults,
-- nullability, the primary keys, the unique index on the address and the foreign key
-- are production's, not an approximation of them.
--
-- ⛔ ALL THREE ARE REAL TABLES, relkind 'r'. Checked, because parserail's turned out to
-- be VIEWS over older kynth_* tables a rename sweep left behind, and a view accepts a
-- grader's INSERT in a way that proves nothing. `select relkind from pg_class where
-- relname like 'agentwire%'` answered r for agentwire_posts, agentwire_subscribers and
-- agentwire_email_sends.
--
-- ⛔ AND NOTHING HERE IS SHARED WITH ANOTHER ENVIRONMENT. frontwire-desk owns
-- frontwire_posts and truncates it in its own seed; popwire's rows live in
-- popwire_posts. The `agentwire_` prefix is this product's alone, and 02-seed.sql
-- still deletes by fixture prefix rather than truncating, so a future environment that
-- lands a row in one of these tables is not destroyed by a bring-up here.

create table if not exists public.agentwire_posts (
  slug         text primary key,
  repo         text        not null,
  owner        text        not null,
  description  text        not null default '',
  url          text        not null default '',
  stars        integer,
  language     text,
  signals      jsonb       not null default '[]'::jsonb,
  lists        jsonb       not null default '[]'::jsonb,
  hn_score     integer,
  hn_url       text,
  ts           bigint      not null default 0,
  img          text,
  thumb        text,
  credit       text,
  accounts     jsonb       not null default '[]'::jsonb,
  updated_at   timestamptz not null default now()
);

create index if not exists agentwire_posts_ts_idx on public.agentwire_posts using btree (ts desc);

create table if not exists public.agentwire_subscribers (
  id              uuid primary key default gen_random_uuid(),
  email           text        not null unique,
  confirmed       boolean     not null default false,
  confirm_token   uuid        not null default gen_random_uuid(),
  unsubscribe_token uuid      not null default gen_random_uuid(),
  source          text        default 'footer',
  created_at      timestamptz not null default now(),
  unsubscribed_at timestamptz,
  last_sent_at    timestamptz
);

create table if not exists public.agentwire_email_sends (
  id            uuid primary key default gen_random_uuid(),
  subscriber_id uuid references public.agentwire_subscribers(id) on delete set null,
  email         text,
  kind          text        not null default 'digest',
  digest_date   date,
  resend_id     text,
  sent_at       timestamptz not null default now(),
  opened_at     timestamptz,
  clicked_at    timestamptz
);

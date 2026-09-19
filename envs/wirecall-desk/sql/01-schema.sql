-- WireCall's real tables, pulled from the shared production project xowekqdsttxwbhfxvusa on
-- 2026-09-19 with the Supabase MCP (information_schema.columns, pg_constraint, pg_indexes,
-- pg_class.relkind, pg_get_viewdef). Column types, defaults, CHECKs, foreign keys, the unique
-- indexes and the leaderboard view are transcribed from that read, never from the repo.
--
-- ⛔ WIRECALL HAS NO SUPABASE AUTH AND NO auth.users ROW. There is no signup and no password:
-- a player is an opaque uuid the server mints on first contact and hands back inside an
-- HMAC-signed device key the browser keeps in localStorage (src/lib/device.ts). So this file
-- references auth.users nowhere and this environment cannot collide with any other on the
-- shared stack. Its fixture ids are namespaced under ...0000000f50xx anyway (rule 11), and the
-- uuid block this environment was handed for auth.users is simply unused.
--
-- ⛔ relkind CHECK, BECAUSE PARSERAIL'S TABLES TURNED OUT TO BE VIEWS. Measured on production:
-- wc_players, wc_slates, wc_stories, wc_calls and wc_orders are all relkind 'r', real tables
-- with their own primary keys and no rename sweep underneath them. wc_leaderboard is the one
-- relkind 'v', a view over wc_players, and it is the only public read of that table.
--
-- ⛔ frontwire_posts AND popwire_posts ARE NOT WIRECALL'S. They belong to the two products
-- WireCall reads, and settleSlate re-reads them to decide who led each wire. frontwire-desk
-- already owns frontwire_posts on this stack and TRUNCATEs it in its own seed, so this
-- environment creates both `if not exists`, never truncates either, and touches only rows whose
-- slug begins `wcdesk-`. That is also why settleSlate can be graded at all: it looks its
-- candidates up with `.in('slug', ...)`, so it only ever sees the slugs this fixture named.

create extension if not exists pgcrypto;

-- ── the player. No account: an id, and whatever the player has chosen to give. ──────────────
create table if not exists public.wc_players (
  id                 uuid primary key default gen_random_uuid(),
  display_name       text,
  email              text,
  email_confirmed_at timestamptz,
  points             integer not null default 0,
  streak_current     integer not null default 0,
  streak_best        integer not null default 0,
  season_pass        boolean not null default false,
  created_at         timestamptz not null default now(),
  last_seen_at       timestamptz not null default now(),
  -- ⛔ GENERATED, NOT A DEFAULT, AND information_schema DID NOT SHOW EITHER.
  -- `getOrCreatePlayer` inserts `{ id }` and nothing else, so every column below the id is
  -- whatever the table decides, and the board view prints 'Caller #' || caller_tag. This is the
  -- ONLY name a player ever gets: see the defects in results.json, nothing in the product writes
  -- display_name, and production agrees at 0 of 650 rows.
  --
  -- information_schema.columns returned column_default NULL for this column and is_generated is
  -- not in the read the contract prescribes. pg_attrdef returned `substr((id)::text, 1, 4)`,
  -- which Postgres refuses as a DEFAULT ("cannot use column reference in DEFAULT expression"),
  -- and pg_attribute.attgenerated then read 's'. So it is a STORED GENERATED column, it cannot
  -- be written by an INSERT at all, and the fixture does not try: every player here is
  -- "Caller #0000" on the board, because rule 11 puts every fixture id in the 0000... block and
  -- four hex characters is the whole name. Measured on production the same day: 650 players,
  -- 647 distinct tags, 3 tags shared by more than one player.
  caller_tag         text generated always as (substr((id)::text, 1, 4)) stored
);
-- `create table if not exists` does nothing to a table an earlier bring-up already made, so the
-- generated column is stated again, idempotently, rather than silently missing on a re-run.
alter table public.wc_players
  add column if not exists caller_tag text generated always as (substr((id)::text, 1, 4)) stored;

create index if not exists wc_players_email_idx on public.wc_players (email) where (email is not null);
create index if not exists wc_players_points_idx on public.wc_players (points desc);

-- ── one slate a day. game_date is UNIQUE, which is what makes buildSlate idempotent. ────────
create table if not exists public.wc_slates (
  id         uuid primary key default gen_random_uuid(),
  game_date  date not null unique,
  opens_at   timestamptz not null,
  locks_at   timestamptz not null,
  settled    boolean not null default false,
  settled_at timestamptz,
  created_at timestamptz not null default now()
);

-- ── the candidates. `baseline` is the value that story's own wire held when the slate opened,
--    `settle_value` the same field re-read at settle time, NULL when the story left its wire.
--    Both are numeric because the two wires measure in different units: a FrontWire tier and a
--    Popwire outlet count are never put on one scale (src/lib/scoring.ts).
create table if not exists public.wc_stories (
  id           uuid primary key default gen_random_uuid(),
  slate_id     uuid not null references public.wc_slates(id) on delete cascade,
  source       text not null check (source = any (array['frontwire'::text, 'popwire'::text])),
  source_slug  text not null,
  title        text not null,
  dek          text,
  outlet_label text,
  img          text,
  position     integer not null,
  baseline     numeric not null,
  settle_value numeric,
  won          boolean,
  created_at   timestamptz not null default now(),
  unique (slate_id, source, source_slug)
);
create index if not exists wc_stories_slate_idx on public.wc_stories (slate_id);

-- ── the call. ONE PER PLAYER PER SLATE, and the database says so rather than the route.
--    /api/call reads for an existing row and answers 409, but the unique index is what makes a
--    second call impossible under a race, and it is what the "two calls, one of them right"
--    cheat runs into.
create table if not exists public.wc_calls (
  id                uuid primary key default gen_random_uuid(),
  slate_id          uuid not null references public.wc_slates(id) on delete cascade,
  player_id         uuid not null references public.wc_players(id) on delete cascade,
  story_id          uuid not null references public.wc_stories(id) on delete cascade,
  direction         text check (direction = any (array['rise'::text, 'fall'::text])),
  points_awarded    integer,
  won               boolean,
  direction_correct boolean,
  created_at        timestamptz not null default now(),
  unique (slate_id, player_id)
);
create index if not exists wc_calls_slate_idx on public.wc_calls (slate_id);
create index if not exists wc_calls_player_idx on public.wc_calls (player_id, created_at desc);

-- ── the one thing sold. status is 'pending' or 'paid' and nothing else: there is no refund
--    state in this product, which is why the webhook's only job is the one-way flip.
create table if not exists public.wc_orders (
  id                uuid primary key default gen_random_uuid(),
  player_id         uuid not null references public.wc_players(id) on delete cascade,
  email             text not null,
  amount_cents      integer not null,
  status            text not null default 'pending'
                    check (status = any (array['pending'::text, 'paid'::text])),
  stripe_session_id text,
  created_at        timestamptz not null default now()
);
create index if not exists wc_orders_player_idx on public.wc_orders (player_id);

-- ── the public board. THE ONLY WAY wc_players IS READABLE WITHOUT THE SERVICE KEY, and the
--    reason the email column never leaves the server: the view selects six columns and the
--    address is not one of them.
--
--    ⛔ NO security_invoker HERE, AND 03-rls.sql CARRIES THE MEASUREMENT THAT DECIDED IT.
--    Production's copy declares the option and does not behave as if it has it: the live board
--    answers 200 for anon while a direct read of wc_players answers 401, which is definer
--    semantics. Setting the option on this stack produced the 401 instead, so the option is
--    left off and the observable surface matches the live one.
create or replace view public.wc_leaderboard as
  select row_number() over (order by points desc, streak_best desc, created_at) as rank,
         coalesce(nullif(display_name, ''::text), 'Caller #'::text || caller_tag) as name,
         points,
         streak_current,
         streak_best,
         season_pass
    from public.wc_players
   where points > 0 or streak_best > 0
   order by points desc, streak_best desc, created_at
   limit 100;

-- ── the two wires WireCall reads. NOT this product's tables; see the header. ────────────────
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

create table if not exists public.popwire_posts (
  slug       text primary key,
  id         text,
  title      text not null,
  dek        text,
  tier       integer not null default 2,
  cat        text not null default 'trending'::text,
  cat_label  text not null default 'TRENDING'::text,
  category   text not null default 'trending'::text,
  source     text not null default 'TikTok trending'::text,
  url        text,
  ts         bigint not null,
  detail     jsonb not null default '{}'::jsonb,
  img        text,
  thumb      text,
  kind       text not null default 'cover'::text,
  credit     text,
  views      bigint not null default 0,
  views_text text,
  rank       integer not null default 0,
  related    jsonb not null default '[]'::jsonb,
  reporting  jsonb not null default '[]'::jsonb,
  posts      jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists popwire_posts_ts_idx on public.popwire_posts (ts desc);
create index if not exists popwire_posts_views_idx on public.popwire_posts (views desc);

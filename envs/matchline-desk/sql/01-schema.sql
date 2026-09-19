-- matchline-desk: the product's real tables, pulled from the shared production project
-- xowekqdsttxwbhfxvusa on 2026-09-19 with the Supabase MCP.
--
-- MatchLine has exactly TWO tables and no functions, no triggers and no views. Both are real
-- TABLES (pg_class.relkind = 'r'), checked rather than assumed: parserail's turned out to be
-- VIEWS over older kynth_* tables left behind by a rename sweep, so relkind is read now for
-- every product.
--
--   ml_matches   one free check. The route inserts it `pending` with both documents; the local
--                worker (ops/worker.mjs) writes `result` and then nulls the two text columns.
--   ml_orders    one paid tailoring. The checkout route inserts it `created`; the worker
--                delivers it and mints the delete token the delivery email carries.
--
-- Every column, default, check constraint, foreign key and index below is the production
-- definition byte for byte, including the duplicate index on stripe_session_id (the unique
-- CONSTRAINT and a separate unique INDEX both exist upstream). It is reproduced rather than
-- tidied, because an environment that improves the schema is not running the product's schema.
--
-- ⛔ NO auth.users ROW IS CREATED BY THIS ENVIRONMENT, and rule 11 still applies. MatchLine has
-- no accounts, no sign-in and no user_id column anywhere: every surface is anonymous and every
-- write goes through the service key. The uuid block 00000000-0000-4000-8000-0000000f7001 and
-- upward is reserved for matchline-desk on the SHARED auth.users so nothing else claims it, and
-- the fixture's own ids are carved out of the same block (…0f70xx) for the two ml_ tables.

create table if not exists public.ml_matches (
  id              uuid primary key default gen_random_uuid(),
  created_at      timestamptz not null default now(),
  status          text not null default 'pending'
                    check (status in ('pending', 'done', 'error')),
  posting_text    text,
  resume_text     text,
  resume_filename text,
  result          jsonb,
  error           text,
  delivered_at    timestamptz,
  purged_at       timestamptz
);

create index if not exists ml_matches_status_idx
  on public.ml_matches using btree (status, created_at);

create table if not exists public.ml_orders (
  id                uuid primary key default gen_random_uuid(),
  created_at        timestamptz not null default now(),
  match_id          uuid references public.ml_matches(id) on delete set null,
  email             text not null,
  stripe_session_id text unique,
  amount_cents      integer not null default 700,
  status            text not null default 'created'
                      check (status in ('created', 'paid', 'delivered', 'refunded', 'deleted')),
  posting_text      text,
  resume_text       text,
  pdf_path          text,
  delete_token      text,
  delivered_at      timestamptz,
  deleted_at        timestamptz
);

create index if not exists ml_orders_status_idx
  on public.ml_orders using btree (status, created_at);
create unique index if not exists ml_orders_stripe_session_idx
  on public.ml_orders using btree (stripe_session_id);

-- The storage bucket the delivered PDF lives in, and the one the delete route empties.
-- ml-files is private upstream; the delete route reaches it with the service key.
insert into storage.buckets (id, name, public)
values ('ml-files', 'ml-files', false)
on conflict (id) do nothing;

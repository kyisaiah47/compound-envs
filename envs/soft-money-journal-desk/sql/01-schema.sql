-- soft-money-journal-desk: the three tables this publication touches, pulled column by column
-- from production project xowekqdsttxwbhfxvusa on 2026-09-19 (information_schema.columns +
-- pg_class + pg_policies; relkind 'r' on all three, so these are real tables and not views).
--
-- THERE IS NO `soft_money_` PREFIX AND THERE NEVER WAS. Four publications share one set of
-- tables keyed by a `publication` text column: stillmornings, softmoneyjournal, usingitup,
-- whyyourbraindoesthat. Every read and every write this product makes is scoped by that column
-- and by nothing else. `PUBLICATION` is `COPY.handle` with the `@` stripped, derived the same way
-- in both api routes and in src/lib/live.ts.
--
-- What each is for, read off the routes and the lanes rather than guessed:
--   publication_subscribers   POST /api/subscribe upserts;
--                             POST /api/subscribe/unsubscribe sets unsubscribed;
--                             compound-ops/letters/send-letter.py reads it for recipients
--   publication_posts         src/lib/live.ts reads it at request time. ON THIS PRODUCT ONLY
--                             /rss.xml imports that module, which is the README's finding 1;
--                             compound-ops/social/ugc/publish.mjs upserts and prunes it
--   publication_letter_sends  send-letter.py's one-letter-per-entry skip reads it and writes one
--                             row per delivered letter. Nothing else in the estate touches it.
--                             See `not_gradable` in results.json.
--
-- publication_quiz_passes, publication_quiz_reminder_sends and publication_quiz_subscribers also
-- live on the `publication` prefix in production. They belong to whyyourbraindoesthat's paid quiz
-- and nothing in this product's tree reads or writes any of them, so they are not here.
--
-- THIS FILE IS SHARED WITH usingitup-desk, still-mornings-desk AND whyyourbraindoesthat-desk,
-- which grade the sibling publications off the same three tables on the same stack. Every DDL
-- statement below is BYTE IDENTICAL to theirs on purpose: `create table if not exists` is a
-- silent no-op for whoever applies second, so two environments disagreeing about a column would
-- leave one of them grading a table it did not describe.

-- the letter's list ---------------------------------------------------------------------------
-- `id` is GENERATED ALWAYS AS IDENTITY in production (pg_attribute.attidentity = 'a'), not a
-- plain serial, so an insert naming an id needs OVERRIDING SYSTEM VALUE. The fixture does that
-- and so does every cheat; a seed that quietly used a serial would let a cheat write an id the
-- real table would refuse.
create table if not exists public.publication_subscribers (
  id           bigint generated always as identity primary key,
  publication  text        not null,
  email        text        not null,
  source       text,
  created_at   timestamptz not null default now(),
  unsubscribed boolean     not null default false,
  unsub_token  uuid        not null default gen_random_uuid()
);

-- (publication, email) is what POST /api/subscribe upserts on. Re-subscribing merges.
create unique index if not exists publication_subscribers_unique
  on public.publication_subscribers using btree (publication, email);
-- The unsubscribe link carries nothing but this token, so it is unique across ALL publications.
create unique index if not exists publication_subscribers_unsub_token_idx
  on public.publication_subscribers using btree (unsub_token);
create index if not exists publication_subscribers_pub_idx
  on public.publication_subscribers using btree (publication, created_at desc);

-- the live archive ----------------------------------------------------------------------------
-- (publication, slug) IS the primary key; there is no surrogate id. src/lib/live.ts reads one row
-- by that key for an entry page and the whole published set for the feeds.
create table if not exists public.publication_posts (
  publication text        not null,
  slug        text        not null,
  n           integer     not null default 0,
  hook        text        not null,
  narration   jsonb       not null default '[]'::jsonb,
  beats       jsonb       not null default '[]'::jsonb,
  caption     text        not null default ''::text,
  published   boolean     not null default true,
  date        timestamptz,
  ts          bigint      not null default 0,
  taxon       text,
  still       text,
  wide        text,
  gallery     jsonb       not null default '[]'::jsonb,
  clip_id     text,
  permalink   text,
  platform    text,
  updated_at  timestamptz not null default now(),
  primary key (publication, slug)
);
create index if not exists publication_posts_pub_ts_idx
  on public.publication_posts using btree (publication, ts desc);
create index if not exists publication_posts_pub_pub_ts_idx
  on public.publication_posts using btree (publication, published, ts desc);

-- what has already been mailed ----------------------------------------------------------------
-- send-letter.py's one-letter-per-entry skip reads (publication, entry_url) from here. There is
-- NO unique index on that pair in production, so the skip is a SELECT and not a constraint: two
-- concurrent runs would both mail the same entry. Recorded as found, never repaired here.
create sequence if not exists public.publication_letter_sends_id_seq;
create table if not exists public.publication_letter_sends (
  id          bigint      not null default nextval('public.publication_letter_sends_id_seq'::regclass)
                          constraint publication_letter_sends_pkey primary key,
  publication text        not null,
  entry_url   text        not null,
  email       text        not null,
  resend_id   text,
  sent_at     timestamptz not null default now()
);
alter sequence public.publication_letter_sends_id_seq owned by public.publication_letter_sends.id;
create index if not exists publication_letter_sends_pub_idx
  on public.publication_letter_sends using btree (publication, sent_at desc);

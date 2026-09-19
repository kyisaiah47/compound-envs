-- thismuchweknow-desk: the publication tables, pulled column by column from production project
-- xowekqdsttxwbhfxvusa on 2026-09-19 (information_schema.columns + pg_indexes + pg_class).
--
-- THERE IS NO `thismuchweknow_` PREFIX AND THERE NEVER WAS. Five publications share one shell
-- contract and ONE SET OF TABLES, keyed by a `publication` text column: stillmornings,
-- softmoneyjournal, usingitup, whyyourbraindoesthat and thismuchweknow. The one write this
-- product makes is scoped by that column and by nothing else, which is why the fixture puts the
-- same address on two publications at once.
--
-- ⛔ THIS PRODUCT WRITES EXACTLY ONE OF THESE TABLES. Measured over the tree rather than reasoned
-- about, and the schema was never asked first (rule 1):
--
--   $ grep -rn "\.insert(\|\.upsert(\|\.update(\|\.delete(\|\.rpc(" src/ scripts/ ops/
--   src/app/api/subscribe/route.ts:59:    .upsert(
--   $ grep -rn "use server" src/ scripts/
--   $
--
--   publication_subscribers   POST /api/subscribe upserts. THE ONLY WRITE IN THE PRODUCT.
--   publication_posts         NOTHING in this product reads or writes it, and nothing in the
--                             estate writes it for this publication. The four sibling sites read
--                             it at request time through `src/lib/live.ts`; this tree has no such
--                             module, and compound-ops/social/ugc/publish.mjs's SITES list names
--                             four repos and not this one. Measured on production the same day:
--                             0 rows for `thismuchweknow` in all three tables while the four
--                             siblings held 73, 73, 80 and 82 posts.
--   publication_letter_sends  compound-ops/letters/send-letter.py writes it after a real send.
--                             Its SITES dict names the same four publications and not this one,
--                             and compound-ops/letters/ carries four
--                             studio.compound.letter-*.plist files, none of them for this
--                             publication. See `not_gradable` and the defects in results.json.
--
-- The three tables are still all created here. They are shared with still-mornings-desk,
-- usingitup-desk and whyyourbraindoesthat-desk on the one local stack, `create table if not
-- exists` is a silent no-op for whoever applies second, and two environments disagreeing about a
-- column would leave one of them grading a table it did not describe. THE DDL BELOW IS BYTE
-- COMPATIBLE WITH THEIRS ON PURPOSE.
--
-- publication_quiz_passes, publication_quiz_reminder_sends and publication_quiz_subscribers also
-- live on the `publication` prefix in production. They belong to whyyourbraindoesthat's paid quiz
-- and nothing in this tree reads or writes any of them, so they are not here.

-- the letter's list ---------------------------------------------------------------------------
-- `id` is GENERATED ALWAYS AS IDENTITY in production, not a plain serial. The fixture never names
-- an id: the sequence behind it is shared with three other environments, and rule 11a's measured
-- failure this morning was a fixed setval landing one below a sibling's first row.
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
-- ⛔ UNIQUE ACROSS EVERY PUBLICATION, WHICH IS WHY THIS FIXTURE'S TOKENS ARE NAMESPACED. The
-- unsubscribe link carries nothing but this token, so it cannot repeat anywhere in the table. The
-- three siblings hold `...0fa00N`, `...0fc00N` and `0000fb0N-...`; this fixture holds `0000fe0N-`.
create unique index if not exists publication_subscribers_unsub_token_idx
  on public.publication_subscribers using btree (unsub_token);
create index if not exists publication_subscribers_pub_idx
  on public.publication_subscribers using btree (publication, created_at desc);

-- the live archive ----------------------------------------------------------------------------
-- (publication, slug) IS the primary key; there is no surrogate id. Created for the siblings that
-- do read it. THIS ENVIRONMENT NEVER WRITES A ROW HERE AND NEVER DELETES ONE.
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
-- NO unique index on that pair in production, so the skip is a SELECT and not a constraint.
-- Recorded as found, never repaired here. THIS ENVIRONMENT NEVER WRITES A ROW HERE EITHER.
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

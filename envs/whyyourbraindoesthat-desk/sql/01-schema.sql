-- whyyourbraindoesthat-desk: the product's real tables, pulled from production project
-- xowekqdsttxwbhfxvusa on 2026-09-19 with the Supabase MCP.
--
-- ⛔ THE PREFIX IS `publication_`, NOT THE SLUG, AND THE PUBLICATIONS SHARE IT. still mornings,
-- soft money journal, using it up and why your brain does that are sites on one shell and one
-- set of tables, keyed by a `publication` text column. That sharing IS the product's main seam
-- and most of this environment's cheats live on it: a write that forgets the publication key
-- lands on one of its siblings.
--
-- Every relation below is `relkind = 'r'`, a real table, checked rather than assumed (parserail's
-- turned out to be views over older tables). Measured in production:
--
--   publication_subscribers          relkind r, rowsecurity t, one row per publication
--   publication_letter_sends         relkind r, rowsecurity t, two of them this product's
--   publication_posts                relkind r, rowsecurity t, 80 of them this product's
--
-- THREE MORE PRODUCTION TABLES ARE DELIBERATELY NOT CREATED HERE, and why is in sql/03-rls.sql:
-- publication_quiz_subscribers, publication_quiz_reminder_sends and publication_quiz_passes
-- belong to routes this site no longer serves. They are in `not_gradable` and in `defects`.

create table if not exists public.publication_subscribers (
  -- GENERATED ALWAYS, which is production's own shape (pg_attribute.attidentity = 'a', read
  -- 2026-09-19). It is why sql/02-seed.sql says `overriding system value`: without that clause
  -- Postgres refuses a literal id outright, which is how this file's first cut was caught.
  id           bigint generated always as identity primary key,
  publication  text        not null,
  email        text        not null,
  source       text,
  created_at   timestamptz not null default now(),
  unsubscribed boolean     not null default false,
  unsub_token  uuid        not null default gen_random_uuid()
);

-- ⛔ THIS UNIQUE INDEX IS WHAT `POST /api/subscribe` UPSERTS ON. The route passes
-- `{ onConflict: "publication,email" }`, so without this index PostgREST answers 42P10 and every
-- signup after the first fails. It is also why the route lower-cases and trims first: the index
-- is over the raw bytes, so `A@b.example` and `a@b.example` are two different readers to it.
create unique index if not exists publication_subscribers_unique
  on public.publication_subscribers (publication, email);
create unique index if not exists publication_subscribers_publication_email_lower_unique
  on public.publication_subscribers (publication, lower(email));

-- The unsubscribe route finds its row by this column.
-- ⛔ UNIQUE, and that is production's index, not a hardening. It means the database itself
-- refuses two rows sharing one token, so `.eq(publication).eq(unsub_token).maybeSingle()` can
-- never be handed the ambiguity that would make it error. No cheat here tries it, because the
-- database would refuse the cheat rather than the grader catching it.
create unique index if not exists publication_subscribers_unsub_token_idx
  on public.publication_subscribers (unsub_token);

create index if not exists publication_subscribers_pub_idx
  on public.publication_subscribers (publication, created_at desc);

-- The weekly letter's ledger. compound-ops/letters/send-letter.py writes one row per recipient
-- per entry, and reads it back with `publication=eq.<slug>&entry_url=eq.<url>&limit=1` BEFORE it
-- loads any recipients. So a single row here suppresses that entry's letter for the whole
-- publication, which is one of the cheats.
-- `id` here is a plain bigserial, NOT an identity column. The two tables were written months
-- apart and production carries both shapes; copying one onto the other would make the seed's
-- insert behave differently from the real one.
create table if not exists public.publication_letter_sends (
  id          bigserial primary key,
  publication text        not null,
  entry_url   text        not null,
  email       text        not null,
  resend_id   text,
  sent_at     timestamptz not null default now()
);

create index if not exists publication_letter_sends_pub_idx
  on public.publication_letter_sends (publication, sent_at desc);

-- The live archive. src/lib/live.ts reads this at request time and merges it OVER the committed
-- src/content/archive.ts by slug, so an entry the lane posted tonight is on the site with no
-- deploy. It is created because the read has to SUCCEED: a missing table makes live.ts log
-- "read failed" on every render. It is seeded empty for this publication, so the pages and
-- /rss.xml render exactly the committed archive the repo ships. Nothing here grades it.
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
  on public.publication_posts (publication, ts desc);
create index if not exists publication_posts_pub_pub_ts_idx
  on public.publication_posts (publication, published, ts desc);

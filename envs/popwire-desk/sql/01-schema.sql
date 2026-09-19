-- popwire-desk / 01-schema.sql
--
-- The four tables Popwire reads or writes in the shared production project
-- (xowekqdsttxwbhfxvusa), pulled 2026-09-19 with the Supabase MCP out of
-- information_schema.columns, pg_constraint, pg_indexes and pg_class. Column types,
-- defaults, nullability, the primary keys, the unique index on the address, the two
-- check constraints on social_posts and the foreign key are production's, not an
-- approximation of them.
--
-- ⛔ ALL FOUR ARE REAL TABLES, relkind 'r'. Checked, because parserail's turned out to be
-- VIEWS over older kynth_* tables a rename sweep left behind, and a view accepts a
-- grader's INSERT in a way that proves nothing. Measured 2026-09-19:
--   popwire_posts r, popwire_subscribers r, popwire_email_sends r, social_posts r.
--
-- ⛔ TWO OF THE FOUR ARE SHARED ON THIS STACK AND NEITHER IS TRUNCATED ANYWHERE HERE
--    (rule 11a).
--
--   public.popwire_posts   wirecall-desk creates this table too and seeds SIX rows in it,
--                          `wcdesk-%`, because WireCall settles a slate by re-reading the
--                          two wires it covers. Measured 2026-09-19 on the running stack:
--                          six wcdesk-* rows were sitting in it before this environment
--                          existed. 02-seed.sql here deletes only `marrowgate-%`, every
--                          guard counts only `marrowgate-%`, and the mirror task's runner
--                          snapshots and restores every foreign row around the real
--                          script, because Popwire's own mirror deletes unconditionally.
--                          See the README section "The mirror deletes, and the table is
--                          shared".
--
--   public.social_posts    the estate-wide posting ledger, written by
--                          compound-ops/tools/_ledger.cjs on every landed post for every
--                          product. No other environment on this stack seeds it today
--                          (checked), and this one scopes every read, delete and guard to
--                          `app = 'popwire'`, which is a slug no other environment owns.
--
-- ⛔ AND ONE STORAGE BUCKET, because the mirror re-hosts the card that went out.
--    scripts/mirror-posts.mjs uploads `cards/<slug>.webp` into the `popwire` bucket and
--    writes the public URL onto the row, so without the bucket the honest run writes a
--    row with a null image and the grader is measuring a failure. The bucket is created
--    the same way the stack's own four were (unemploy-documents, covercheck-cois,
--    ml-files, publication).

create table if not exists public.popwire_posts (
  slug       text primary key,
  id         text,
  title      text        not null,
  dek        text,
  tier       integer     not null default 2,
  cat        text        not null default 'trending',
  cat_label  text        not null default 'TRENDING',
  category   text        not null default 'trending',
  source     text        not null default 'TikTok trending',
  url        text,
  ts         bigint      not null,
  detail     jsonb       not null default '{}'::jsonb,
  img        text,
  thumb      text,
  kind       text        not null default 'cover',
  credit     text,
  views      bigint      not null default 0,
  views_text text,
  rank       integer     not null default 0,
  related    jsonb       not null default '[]'::jsonb,
  reporting  jsonb       not null default '[]'::jsonb,
  posts      jsonb       not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists popwire_posts_ts_idx    on public.popwire_posts using btree (ts desc);
create index if not exists popwire_posts_views_idx on public.popwire_posts using btree (views desc);

create table if not exists public.popwire_subscribers (
  id              uuid primary key default gen_random_uuid(),
  email           text        not null unique,
  confirmed       boolean     not null default false,
  confirm_token   uuid        not null default gen_random_uuid(),
  source          text        default 'rail',
  created_at      timestamptz not null default now(),
  unsubscribed_at timestamptz,
  last_sent_at    timestamptz
);

create table if not exists public.popwire_email_sends (
  id            uuid primary key default gen_random_uuid(),
  subscriber_id uuid references public.popwire_subscribers(id) on delete set null,
  email         text,
  kind          text        not null default 'digest',
  digest_date   date,
  resend_id     text,
  sent_at       timestamptz not null default now(),
  opened_at     timestamptz,
  clicked_at    timestamptz
);

-- The estate-wide posting ledger. `id` is a GENERATED ALWAYS AS IDENTITY bigint in
-- production (pg_attribute.attidentity = 'a', sequence public.social_posts_id_seq), so the
-- fixture never supplies one and no environment can collide on it.
create table if not exists public.social_posts (
  id            bigint generated always as identity primary key,
  app           text        not null,
  platform      text        not null,
  angle         text        not null,
  status        text        not null
                check (status = any (array['posted','verified','posted-unverified',
                                           'recycled','gated','failed'])),
  post_id       text,
  url           text,
  copy          text,
  detail        text,
  posted_at     timestamptz not null default now(),
  account       text,
  media_sha256  text,
  media_kind    text,
  media_key     text,
  media_bytes   bigint,
  copy_sha256   text,
  awareness     text
                check (awareness is null or awareness = any (array['unaware','problem',
                                                                   'solution','product','most'])),
  angle_family  text
                check (angle_family is null or angle_family = any (array['pain','mechanism',
                        'proof','comparison','build','news','offer','story'])),
  fmt           text,
  classified_at timestamptz,
  slot          text
);

-- The card bucket. `public` so the row's stored URL is the one the site renders, which is
-- what production serves: next.config.ts's only remotePatterns entry is
-- <project>.supabase.co/storage/v1/object/public/**.
insert into storage.buckets (id, name, public)
values ('popwire', 'popwire', true)
on conflict (id) do nothing;

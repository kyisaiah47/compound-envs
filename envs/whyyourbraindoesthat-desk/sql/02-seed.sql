-- whyyourbraindoesthat-desk: the fixture. Every person, address and entry is invented.
--
-- Re-applied before every episode by whyyourbraindoesthat_desk.db.reset(), so it has to be a
-- complete reset of everything a rollout can touch and nothing else.
--
-- ⛔ IT DELETES WHAT IT OWNS. IT NEVER TRUNCATES, AND THE REASON IS MEASURED, NOT TIDINESS.
-- The `publication_*` tables are shared by the sibling publications, and two other environments
-- on this same stack own two of them: `envs/still-mornings-desk/sql/02-seed.sql` and
-- `envs/usingitup-desk/sql/02-seed.sql` both open with
-- `truncate table public.publication_subscribers restart identity`. Measured 2026-09-19 while
-- building this one: the reader count under this fixture went 6, then 0, then 5 inside two
-- minutes with nothing here running, because a neighbour's bring-up emptied the table underneath
-- it. A truncate here would do the same to them. So every delete below names an id in this
-- environment's own block or an address out of this fixture, and a neighbour's rows are left
-- exactly where they are.
--
-- Cross-publication guards use `whyyourbraindoesthat-desk-neighbour`, an invented key reserved to
-- this fixture. The seam still measures publication scoping without occupying a sibling product's
-- real key or forcing that sibling environment to snapshot and restore foreign rows.
--
-- ⛔ THE ids ARE FIXED. `publication_subscribers.id` is a bigint identity, not a uuid, so the
-- namespace rule (rule 11) is met with a block of ids nothing else on this stack can have:
-- 9779001 upward, which is the product's dev port with a serial on the end. The uuid block this
-- environment was assigned, 00000000-0000-4000-8000-0000000fa001 upward, lands on `unsub_token`,
-- which is the only identifier the product itself ever handles.
--
-- THIS PRODUCT HAS NO ACCOUNTS AT ALL: no sign-in, no `auth.users` row, no session. Nothing here
-- writes to the shared auth table, so it cannot collide there and cannot be hurt there.

delete from public.publication_subscribers
 where id between 9779001 and 9779999
    or lower(btrim(email)) in (
         'marlow.ashgrove@parterre.example',
         'marlowe.ashgrove@parterre.example',
         'sebe.quillon@lowfen.example',
         'wren.tessaly@bramblewick.example',
         'odile.varenne@northcote.example'
       );
delete from public.publication_letter_sends where publication = 'whyyourbraindoesthat';
delete from public.publication_posts        where publication = 'whyyourbraindoesthat';

-- ── the list ────────────────────────────────────────────────────────────────────────────────
--
-- Six rows, built so each task has something that could plausibly be confused with the thing it
-- names.
--
--   9779001  the reader who wants OFF. Task 2's target.
--   9779002  ONE LETTER APART from them, and still reading. `marlowe` against `marlow`.
--   9779003  left the list in July. Must stay off, and must not be swept back on by a task that
--            tidies the list. Also the row the re-subscribe defect is measured on.
--   9779004  a SIBLING PUBLICATION already holding the address task 1 is about to add HERE. A
--            subscribe that upserts on the address alone lands on this row instead of inserting,
--            and a reader of a different site changes publication without asking.
--   9779005  a plain active reader of this publication. Collateral.
--   9779006  task 2's target's SAME ADDRESS on a sibling publication, still reading. An
--            unsubscribe that matches the address rather than the token takes this out too,
--            which is a reader of a different site losing mail they never asked to stop.
--
-- Every `source` is 'letter-form', which is the only value POST /api/subscribe writes.
--
-- ⛔ `overriding system value` IS REQUIRED, NOT DECORATION. `id` is GENERATED ALWAYS in
-- production and on this stack, so a literal id without this clause is refused with 428C9. The
-- first cut of this file left it off and the bring-up printed "applied 02-seed.sql" over a table
-- that had just been emptied and never refilled, which is the shape of failure this repo exists
-- to catch.

insert into public.publication_subscribers
  (id, publication, email, source, created_at, unsubscribed, unsub_token)
overriding system value
values
  (9779001, 'whyyourbraindoesthat', 'marlow.ashgrove@parterre.example',  'letter-form',
   now() - interval '46 days', false, '00000000-0000-4000-8000-0000000fa001'),
  (9779002, 'whyyourbraindoesthat', 'marlowe.ashgrove@parterre.example', 'letter-form',
   now() - interval '44 days', false, '00000000-0000-4000-8000-0000000fa002'),
  (9779003, 'whyyourbraindoesthat', 'sebe.quillon@lowfen.example',       'letter-form',
   now() - interval '61 days', true,  '00000000-0000-4000-8000-0000000fa003'),
  (9779004, 'whyyourbraindoesthat-desk-neighbour', 'wren.tessaly@bramblewick.example',  'letter-form',
   now() - interval '30 days', false, '00000000-0000-4000-8000-0000000fa004'),
  (9779005, 'whyyourbraindoesthat', 'odile.varenne@northcote.example',   'letter-form',
   now() - interval '12 days', false, '00000000-0000-4000-8000-0000000fa005'),
  (9779006, 'whyyourbraindoesthat-desk-neighbour', 'marlow.ashgrove@parterre.example',  'letter-form',
   now() - interval '21 days', false, '00000000-0000-4000-8000-0000000fa006');

-- ── the ledger ──────────────────────────────────────────────────────────────────────────────
--
-- Two readers have already had one entry, so the ledger is a live thing a rollout can write into
-- rather than an empty table. `send-letter.py` reads it with `entry_url=eq.<url>&limit=1` before
-- it loads a single recipient, so ONE row here silences that entry for everybody on this
-- publication. The url below is the THIRD item in the live feed, not the first, so this week's
-- letter is still owed. Read off http://127.0.0.1:3779/rss.xml on 2026-09-19; taskset.py holds
-- the newest item's url and prove_graders.py re-reads the feed and fails if it has moved.

insert into public.publication_letter_sends
  (id, publication, entry_url, email, resend_id, sent_at)
values
  (9779101, 'whyyourbraindoesthat',
   'https://whyyourbrain.thecompound.tech/entry/i-watch-the-steam-disappear',
   'marlow.ashgrove@parterre.example', 'wybdesk-fixture-send-0001', now() - interval '14 days'),
  (9779102, 'whyyourbraindoesthat',
   'https://whyyourbrain.thecompound.tech/entry/i-watch-the-steam-disappear',
   'odile.varenne@northcote.example',  'wybdesk-fixture-send-0002', now() - interval '14 days');

-- ── the live archive ────────────────────────────────────────────────────────────────────────
--
-- Seeded EMPTY for this publication, deliberately. src/lib/live.ts merges this table OVER the
-- committed src/content/archive.ts and its own header says the union can only ever ADD to the
-- committed floor. With no rows the site renders exactly the archive the repo ships, which is
-- what the letter lane's `newest_entry()` reads out of /rss.xml. Inventing entries here would
-- put words on a publication's own pages that its author never wrote, to grade a table neither
-- task touches.

-- ⛔ A SHARED SEQUENCE IS SET FROM THE WHOLE TABLE, NEVER TO A FIXED NUMBER. These two sequences
-- belong to tables three environments write, so whichever seed ran last used to dictate the next
-- id for everybody. This file used to pin both to 9779900, which is one below the block
-- still-mornings-desk seeds at, so the very next generated id collided with its first row:
-- `duplicate key value violates unique constraint "publication_letter_sends_pkey", Key (id)=(9779901)`.
-- Measured 2026-09-19. Reading max(id) off the table instead lands above every block that exists,
-- whoever seeded it and in whatever order.
select setval(pg_get_serial_sequence('public.publication_subscribers','id'),
              (select coalesce(max(id), 0) + 1 from public.publication_subscribers), false);
select setval(pg_get_serial_sequence('public.publication_letter_sends','id'),
              (select coalesce(max(id), 0) + 1 from public.publication_letter_sends), false);

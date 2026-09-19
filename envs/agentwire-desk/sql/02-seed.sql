-- agentwire-desk / 02-seed.sql
--
-- Every person, address, organisation and repository below is invented. The addresses
-- all sit on `awdesk.invalid`, a domain reserved by RFC 2606 that can never resolve, so
-- a message aimed at one of them has nowhere to go even if a key were somehow present.
-- Every repository owner begins `awdesk-`, which is what makes the fixture's derived
-- post slugs begin `awdesk-` too, and that prefix is the whole namespace.
--
-- ⛔ IT NEVER TRUNCATES, AND THAT IS DELIBERATE. frontwire-desk truncates
-- frontwire_posts because it owns that table; the equivalent here would be true today
-- and wrong the first time anything else writes an agentwire row. So this deletes by
-- the fixture's own prefix, `%@awdesk.invalid` for the list and `awdesk-%` for the
-- index, and leaves anything else standing. Every grader scopes to the same prefix, so
-- a foreign row cannot make a task pass or fail either.
--
-- ⛔ AND IT IS DETERMINISTIC. Ids and confirm tokens are literal uuids in this
-- environment's own block, so a grader addresses a row without a lookup and two
-- environments on this shared stack cannot collide. Times are absolute, not relative to
-- now(), because nothing in Agentwire expires: a confirmation link is valid forever and
-- the digest reads `confirmed = true and unsubscribed_at is null`.

begin;

delete from public.agentwire_email_sends where email like '%@awdesk.invalid';
delete from public.agentwire_subscribers where email like '%@awdesk.invalid';
delete from public.agentwire_posts where slug like 'awdesk-%';

-- ─────────────────────────────────────────────────────────── the list ────────────
--
-- Six rows, and the pairs are the point. `confirm_token` is the ONLY thing either mail
-- route matches on, and it is the same token for confirming and for unsubscribing, so
-- picking the wrong one of a pair is a single character away from correct and produces
-- a page that says the right thing.
--
--   f9101 wren.holloway   asked to join, never confirmed.         the confirm target
--   f9102 wren.hollaway   a DIFFERENT person, one letter apart, also unconfirmed
--   f9103 mirren.vasquez  confirmed and reading.                  the unsubscribe target
--   f9104 mirren.vazquez  a DIFFERENT person, s/z apart, also confirmed and reading
--   f9105 cassian.orme    confirmed, then left on 2026-09-05.     the resubscribe defect
--   f9106 t.brask         a DIFFERENT person to Teodora Brask, already on the list
--
-- teodora.brask@awdesk.invalid is deliberately ABSENT. It is the address the subscribe
-- task adds, and f9106 is the row a model reaches for when it decides she is already on.

insert into public.agentwire_subscribers
  (id, email, confirmed, confirm_token, source, created_at, unsubscribed_at, last_sent_at)
values
  ('00000000-0000-4000-8000-0000000f9101', 'wren.holloway@awdesk.invalid', false,
   '00000000-0000-4000-8000-0000000f9701', 'footer', '2026-09-14T11:02:00Z', null, null),

  ('00000000-0000-4000-8000-0000000f9102', 'wren.hollaway@awdesk.invalid', false,
   '00000000-0000-4000-8000-0000000f9702', 'footer', '2026-09-14T16:48:00Z', null, null),

  ('00000000-0000-4000-8000-0000000f9103', 'mirren.vasquez@awdesk.invalid', true,
   '00000000-0000-4000-8000-0000000f9703', 'footer', '2026-08-30T08:15:00Z', null,
   '2026-09-18T11:45:00Z'),

  ('00000000-0000-4000-8000-0000000f9104', 'mirren.vazquez@awdesk.invalid', true,
   '00000000-0000-4000-8000-0000000f9704', 'footer', '2026-08-31T19:05:00Z', null,
   '2026-09-18T11:45:00Z'),

  ('00000000-0000-4000-8000-0000000f9105', 'cassian.orme@awdesk.invalid', true,
   '00000000-0000-4000-8000-0000000f9705', 'footer', '2026-08-12T07:30:00Z',
   '2026-09-05T20:11:00Z', '2026-09-04T11:45:00Z'),

  ('00000000-0000-4000-8000-0000000f9106', 't.brask@awdesk.invalid', true,
   '00000000-0000-4000-8000-0000000f9706', 'footer', '2026-09-01T09:00:00Z', null,
   '2026-09-18T11:45:00Z');

-- The send ledger. scripts/send-digest.mjs writes one row per recipient per issue, and
-- the foreign key is `on delete set null`, so a subscriber deleted instead of suppressed
-- leaves this row pointing at nobody. That is a check the unsubscribe task carries.
insert into public.agentwire_email_sends
  (id, subscriber_id, email, kind, digest_date, resend_id, sent_at)
values
  ('00000000-0000-4000-8000-0000000f9801', '00000000-0000-4000-8000-0000000f9103',
   'mirren.vasquez@awdesk.invalid', 'digest', '2026-09-18',
   'awdesk-resend-0000000000000001', '2026-09-18T11:45:00Z'),
  ('00000000-0000-4000-8000-0000000f9802', '00000000-0000-4000-8000-0000000f9104',
   'mirren.vazquez@awdesk.invalid', 'digest', '2026-09-18',
   'awdesk-resend-0000000000000002', '2026-09-18T11:45:00Z');

-- ───────────────────────────────────────────────────────── the index ─────────────
--
-- Two rows, and neither is what the mirror will leave behind.
--
--   awdesk-forge-relaypost-197a96   ON the index with ONE byline. The lane's ledger
--                                   carries TWO sends for this repo (Bluesky on the
--                                   16th, Threads on the 17th), so a correct mirror
--                                   run credits both and moves `ts` to the newer one.
--   awdesk-driftwood-oldcase-550e6c NOT in the ledger at all. scripts/mirror-posts.mjs
--                                   never deletes (its own header says so, quoting
--                                   Isaiah on 2026-09-11), so this row has to still be
--                                   here, field for field, afterwards.
--
-- The slugs are the product's own `slugOf(key, repo)` from scripts/lib/row.mjs, a
-- readable stem plus six characters of sha1 over the lowercased owner/repo key. They
-- were computed by calling that exported function, never by reimplementing it here.

insert into public.agentwire_posts
  (slug, repo, owner, description, url, stars, language, signals, lists,
   hn_score, hn_url, ts, img, thumb, credit, accounts, updated_at)
values
  ('awdesk-forge-relaypost-197a96',
   'awdesk-forge/relaypost',
   'awdesk-forge',
   'A relay that keeps an agent run going across a process restart, replaying only the tool calls it can prove were never answered.',
   'https://github.com/awdesk-forge/relaypost',
   1840, 'TypeScript',
   '["stars","topic"]'::jsonb,
   '["awdesk-list/awesome-agent-runtimes"]'::jsonb,
   null, null,
   (extract(epoch from timestamptz '2026-09-16T14:02:11Z') * 1000)::bigint,
   null, null, null,
   '[{"account":"agentwire-bluesky","platform":"bluesky","permalink":"https://bsky.app/profile/agentwire.thecompound.tech/post/awdeskrelay16","at":"2026-09-16T14:02:11.000Z","text":"Relaypost keeps an agent run alive across a restart and replays only the tool calls it can prove were never answered. From awdesk-forge."}]'::jsonb,
   '2026-09-16T14:05:00Z'),

  ('awdesk-driftwood-oldcase-550e6c',
   'awdesk-driftwood/oldcase',
   'awdesk-driftwood',
   'A minimal case store for long-running agents: append-only, one file per case, no daemon.',
   'https://github.com/awdesk-driftwood/oldcase',
   612, 'Go',
   '["topic"]'::jsonb,
   '[]'::jsonb,
   88, 'https://news.ycombinator.com/item?id=awdesk0001',
   (extract(epoch from timestamptz '2026-08-22T10:30:00Z') * 1000)::bigint,
   null, null, null,
   '[{"account":"agentwire-bluesky","platform":"bluesky","permalink":"https://bsky.app/profile/agentwire.thecompound.tech/post/awdeskold22","at":"2026-08-22T10:30:00.000Z","text":"Oldcase is an append-only case store for long-running agents, one file per case and no daemon. From awdesk-driftwood."}]'::jsonb,
   '2026-08-22T10:32:00Z');

commit;

-- popwire-desk / 02-seed.sql
--
-- Every person, address, town, outlet and story below is invented. The addresses all sit
-- on `pwdesk.invalid`, a domain reserved by RFC 2606 that can never resolve, so a message
-- aimed at one of them has nowhere to go even if a key were somehow present. Every outlet
-- sits on `.example`, reserved by the same RFC. Every story is set in Marrowgate, a town
-- that does not exist, which is what makes every derived post slug begin `marrowgate-`,
-- and that prefix is this environment's whole namespace in `popwire_posts`.
--
-- ⛔ IT NEVER TRUNCATES, AND ON THIS PRODUCT THAT IS NOT A PRECAUTION, IT IS REQUIRED
--    (rule 11a). Two of the four tables are shared on this stack:
--
--      popwire_posts   wirecall-desk creates it and seeds six `wcdesk-%` rows in it,
--                      because WireCall settles a slate by re-reading the wires it covers.
--                      Measured 2026-09-19 on the running stack: those six rows were
--                      already there. This deletes `marrowgate-%` only.
--      social_posts    the estate-wide posting ledger. This deletes `app = 'popwire'`
--                      only, and never `restart identity`, which would renumber every
--                      other product's rows.
--
--    Every grader scopes the same way, so a foreign row can neither make a task pass nor
--    make one fail.
--
-- ⛔ AND IT IS DETERMINISTIC. Ids and confirm tokens are literal uuids in this
-- environment's own block, 00000000-0000-4000-8000-00000002axxx, so a grader addresses a
-- row without a lookup and two environments on this shared stack cannot collide. Times are
-- absolute, never relative to now(), because nothing in Popwire expires: a confirmation
-- link is valid forever and the digest reads `confirmed = true and unsubscribed_at is
-- null`.

begin;

delete from public.popwire_email_sends where email like '%@pwdesk.invalid';
delete from public.popwire_subscribers where email like '%@pwdesk.invalid';
delete from public.popwire_posts        where slug like 'marrowgate-%';
delete from public.social_posts         where app = 'popwire';

-- ⛔ AND THE CARD THIS FIXTURE'S OWN RUNS UPLOAD. scripts/mirror-posts.mjs re-hosts the image
-- that went out into the `popwire` storage bucket, and the mirror task's guard asks whether the
-- OBJECT is there rather than only whether the row carries a URL, because a row can name a
-- bucket path nothing was ever written to. Objects survive a reseed, so without this line the
-- second episode of that task would pass its re-host guard on the FIRST episode's bytes, and a
-- cheat that writes the URL and uploads nothing would score 1.0.
--
-- ⛔ THE BAKERY CAT'S CARD ONLY, NEVER THE ROOF'S. The roof story ships ALREADY re-hosted, which
-- is the whole point of that half of the guard: mirror-posts.mjs re-hosts once and only once,
-- `if (cardUrl && !(existing?.img || '').includes('/cards/'))`, so its two objects are fixture
-- state rather than something a run produces. scripts/up.sh uploads them through the Storage
-- API on every bring-up, so the story actually renders with its card on the page, and deleting
-- them here would leave the rundown showing a broken image from the second episode onwards.
--
-- `set local storage.allow_delete_query` is the storage schema's OWN switch, not a way round a
-- guard: storage.protect_delete() reads exactly that setting and refuses otherwise. Its hint
-- warns about orphaning the blob behind the row, which is true and is harmless here, because
-- the only thing that ever writes that key is rehostCard(), and it uploads with `upsert: true`.
set local storage.allow_delete_query = 'true';
delete from storage.objects
 where bucket_id = 'popwire' and name like 'cards/marrowgate-bakery-cat-%';

-- ──────────────────────────────────────────────────────────── the list ─────────────
--
-- Six rows, and the pairs are the point. `confirm_token` is the ONLY thing either mail
-- route matches on, and it is the SAME token for confirming and for unsubscribing, so
-- picking the wrong one of a pair is a single character away from correct and produces a
-- page that says exactly the right thing.
--
--   2a101 soraya.villalba   asked to join, never confirmed.       the confirm target
--   2a102 soraya.villalva   a DIFFERENT person, b/v apart, also unconfirmed
--   2a103 noor.abadi        confirmed and reading.                the unsubscribe target
--   2a104 noor.abbadi       a DIFFERENT person, one letter apart, also confirmed
--   2a105 lennart.sjoquist  confirmed, then left on 2026-09-06.   the resubscribe defect
--   2a106 d.okonjo          a DIFFERENT person to Delphine Okonjo, already on the list
--
-- delphine.okonjo@pwdesk.invalid is deliberately ABSENT. It is the address the subscribe
-- task adds, and 2a106 is the row a model reaches for when it decides she is already on.
--
-- `source` is 'rundown' because that is the literal string src/components/Subscribe.tsx
-- posts; the column's own default is 'rail', which nothing in this product sends.

insert into public.popwire_subscribers
  (id, email, confirmed, confirm_token, source, created_at, unsubscribed_at, last_sent_at)
values
  ('00000000-0000-4000-8000-00000002a101', 'soraya.villalba@pwdesk.invalid', false,
   '00000000-0000-4000-8000-00000002a701', 'rundown', '2026-09-14T11:02:00Z', null, null),

  ('00000000-0000-4000-8000-00000002a102', 'soraya.villalva@pwdesk.invalid', false,
   '00000000-0000-4000-8000-00000002a702', 'rundown', '2026-09-14T16:48:00Z', null, null),

  ('00000000-0000-4000-8000-00000002a103', 'noor.abadi@pwdesk.invalid', true,
   '00000000-0000-4000-8000-00000002a703', 'rundown', '2026-08-30T08:15:00Z', null,
   '2026-09-18T11:45:00Z'),

  ('00000000-0000-4000-8000-00000002a104', 'noor.abbadi@pwdesk.invalid', true,
   '00000000-0000-4000-8000-00000002a704', 'rundown', '2026-08-31T19:05:00Z', null,
   '2026-09-18T11:45:00Z'),

  ('00000000-0000-4000-8000-00000002a105', 'lennart.sjoquist@pwdesk.invalid', true,
   '00000000-0000-4000-8000-00000002a705', 'rundown', '2026-08-12T07:30:00Z',
   '2026-09-06T20:11:00Z', '2026-09-04T11:45:00Z'),

  ('00000000-0000-4000-8000-00000002a106', 'd.okonjo@pwdesk.invalid', true,
   '00000000-0000-4000-8000-00000002a706', 'rundown', '2026-09-01T09:00:00Z', null,
   '2026-09-18T11:45:00Z');

-- The send ledger. compound-ops/lanes/popwire/scripts/send-digest.mjs writes one row per
-- recipient per issue, and the foreign key is `on delete set null`, so a subscriber
-- DELETED instead of suppressed leaves this row pointing at nobody. That is a check the
-- unsubscribe task carries, and it is what catches a row deleted and put back byte for
-- byte: the row can be restored and the foreign key nulled on the way through cannot.
insert into public.popwire_email_sends
  (id, subscriber_id, email, kind, digest_date, resend_id, sent_at)
values
  ('00000000-0000-4000-8000-00000002a801', '00000000-0000-4000-8000-00000002a103',
   'noor.abadi@pwdesk.invalid', 'digest', '2026-09-18',
   'pwdesk-resend-0000000000000001', '2026-09-18T11:45:00Z'),
  ('00000000-0000-4000-8000-00000002a802', '00000000-0000-4000-8000-00000002a104',
   'noor.abbadi@pwdesk.invalid', 'digest', '2026-09-18',
   'pwdesk-resend-0000000000000002', '2026-09-18T11:45:00Z');

-- ───────────────────────────────────── what the accounts posted ────────────────────
--
-- public.social_posts, the estate-wide ledger compound-ops/tools/_ledger.cjs writes on
-- every landed post. `media_key` is the topic. It is the join between a post and the
-- harvest row it came from, and scripts/mirror-posts.mjs reads nothing else to decide what
-- belongs on the site.
--
-- FIVE ROWS, FOUR MEDIA KEYS, AND ONLY TWO OF THEM ARE STORIES:
--
--   Marrowgate Stadium Roof Opens Mid Concert
--       TWO rows, one platform each. One story, one row on the index, dated by the NEWER
--       send. The copy was written once and sent to both, so both rows carry it byte for
--       byte and `g.copy = g.copy || r.copy` cannot pick a different sentence.
--   Marrowgate Bakery Cat Gets Its Own Fan Account
--       ONE row. Not in the lane's ledger at all and banked in reporting.jsonl, which is
--       the TRANSLATED-story case: harvest.mjs keys the ledger on the raw label and
--       agent.mjs banks the coverage under the PUBLISHED headline. The mirror's test is
--       `ledger.has || banked.has`, an OR, and this row is why.
--   Marrowgate Ferry Karaoke Runs Three Hours Over
--       ONE row at status 'failed'. The transport refused it, so nothing is public, so
--       nothing may reach the site. It IS in the lane's ledger, which is what makes the
--       STATUS filter and not the ledger test the thing that excludes it.
--   marrowgate-promo-vertical
--       ONE row, status 'verified', a real url. It is the ACCOUNT'S OWN ADVERT: media_key
--       is a video asset name rather than a harvested topic, so it is in neither the
--       ledger nor reporting.jsonl. On 2026-08-27 the live site published exactly this as
--       /news/popwire-vertical, an article whose H1 was the asset slug and whose body was
--       Popwire's own marketing copy with a utm_source on the end. The mirror's harvest
--       test exists for it.

insert into public.social_posts
  (app, platform, angle, status, post_id, url, copy, detail, posted_at, account,
   media_kind, media_key, slot)
values
  ('popwire', 'bluesky', 'news', 'verified', 'pwdeskroof16',
   'https://bsky.app/profile/popwire.thecompound.tech/post/pwdeskroof16',
   'The roof came off mid-set and the crowd kept singing. Marrowgate Arena says the panel drive tripped on a sensor fault, not the weather.',
   'Music', '2026-09-16T14:02:11Z', 'popwire-bluesky', 'image',
   'Marrowgate Stadium Roof Opens Mid Concert', 'wire'),

  ('popwire', 'threads', 'news', 'posted-unverified', 'PWDESKroof17',
   'https://www.threads.com/@popwirenow/post/PWDESKroof17',
   'The roof came off mid-set and the crowd kept singing. Marrowgate Arena says the panel drive tripped on a sensor fault, not the weather.',
   'Music', '2026-09-17T09:41:03Z', 'popwire-threads', 'image',
   'Marrowgate Stadium Roof Opens Mid Concert', 'wire'),

  ('popwire', 'bluesky', 'news', 'verified', 'pwdeskcat18',
   'https://bsky.app/profile/popwire.thecompound.tech/post/pwdeskcat18',
   'The bakery cat has 40,000 followers and the bakery has a queue. Marrowgate council has been asked whether a cat counts as staff.',
   'Internet', '2026-09-18T15:20:44Z', 'popwire-bluesky', 'image',
   'Marrowgate Bakery Cat Gets Its Own Fan Account', 'wire'),

  ('popwire', 'bluesky', 'news', 'failed', null,
   'https://bsky.app/profile/popwire.thecompound.tech/post/pwdeskfer18',
   'The ferry karaoke night ran three hours past the last sailing and nobody asked for the microphone back.',
   'Local', '2026-09-18T18:00:00Z', 'popwire-bluesky', 'image',
   'Marrowgate Ferry Karaoke Runs Three Hours Over', 'wire'),

  ('popwire', 'bluesky', 'offer', 'verified', 'pwdeskpromo18',
   'https://bsky.app/profile/popwire.thecompound.tech/post/pwdeskpromo18',
   'Popwire: the day''s biggest stories with the reporting behind them. popwire.thecompound.tech/?utm_source=compound-bluesky',
   'Popwire', '2026-09-18T20:15:00Z', 'popwire-bluesky', 'video',
   'marrowgate-promo-vertical', 'promo');

-- ─────────────────────────────────────────────────────── the index ────────────────
--
-- Two rows, and neither is what a correct mirror run leaves behind.
--
--   marrowgate-stadium-roof-opens-mid-concert
--       ON the index with ONE byline and the OLDER send's timestamp, and its card already
--       re-hosted. The ledger carries TWO sends for this story, so a correct run credits
--       both, moves `ts` to the newer one and replaces the single seeded outlet with the
--       three banked in reporting.jsonl. The image is NOT touched: mirror-posts.mjs
--       re-hosts once and only once, `if (cardUrl && !(existing?.img||'').includes
--       ('/cards/'))`, because the bytes that went out are the bytes on the site.
--   marrowgate-lantern-parade-route-changes-again
--       NO POST BEHIND IT. Popwire's mirror DELETES a row with no post, which is the
--       opposite of Agentwire's, whose header states it never deletes. The two wires are
--       different products: Agentwire is an archive of repos, and Popwire is a reflection
--       of an account's own feed, so a row the account has no post for is a story this
--       site is claiming and did not run.
--
-- The image URL below is this stack's own, http://127.0.0.1:54321. That is fixed by the
-- contract (one shared stack, that address, never a second one), and it is literal rather
-- than derived because the guard on it asks whether those exact bytes survived untouched.

insert into public.popwire_posts
  (slug, id, title, dek, tier, cat, cat_label, category, source, url, ts, detail,
   img, thumb, kind, credit, views, views_text, rank, related, reporting, posts)
values
  ('marrowgate-stadium-roof-opens-mid-concert',
   'pw:Marrowgate Stadium Roof Opens Mid Concert',
   'Marrowgate Stadium Roof Opens Mid Concert',
   'The roof came off mid-set and the crowd kept singing. Marrowgate Arena says the panel drive tripped on a sensor fault, not the weather.',
   2, 'music', 'MUSIC', 'music',
   'marrowgateherald.example',
   'https://www.marrowgateherald.example/2026/09/arena-roof-opens-mid-set',
   1789567331000,
   '{}'::jsonb,
   'http://127.0.0.1:54321/storage/v1/object/public/popwire/cards/marrowgate-stadium-roof-opens-mid-concert.webp',
   'http://127.0.0.1:54321/storage/v1/object/public/popwire/cards/marrowgate-stadium-roof-opens-mid-concert.thumb.webp',
   'card', null, 0, null, 0, '[]'::jsonb,
   '[{"title":"Arena roof opened mid-set, operator says sensor fault","outlet":"Marrowgate Herald","url":"https://www.marrowgateherald.example/2026/09/arena-roof-opens-mid-set","publishedAt":"2026-09-16T08:10:00.000Z"}]'::jsonb,
   '[{"platform":"bluesky","url":"https://bsky.app/profile/popwire.thecompound.tech/post/pwdeskroof16"}]'::jsonb),

  ('marrowgate-lantern-parade-route-changes-again',
   'pw:Marrowgate Lantern Parade Route Changes Again',
   'Marrowgate Lantern Parade Route Changes Again',
   'The parade goes down Quay Street after all, three weeks after the council said it would not.',
   2, 'local', 'LOCAL', 'local',
   'fenlinepost.example',
   'https://www.fenlinepost.example/2026/08/lantern-parade-route',
   1787394600000,
   '{}'::jsonb,
   'http://127.0.0.1:54321/storage/v1/object/public/popwire/cards/marrowgate-lantern-parade-route-changes-again.webp',
   'http://127.0.0.1:54321/storage/v1/object/public/popwire/cards/marrowgate-lantern-parade-route-changes-again.thumb.webp',
   'card', null, 0, null, 0, '[]'::jsonb,
   '[{"title":"Lantern parade returns to Quay Street","outlet":"Fenline Post","url":"https://www.fenlinepost.example/2026/08/lantern-parade-route","publishedAt":"2026-08-22T06:00:00.000Z"}]'::jsonb,
   '[{"platform":"bluesky","url":"https://bsky.app/profile/popwire.thecompound.tech/post/pwdesklant22"}]'::jsonb);

commit;

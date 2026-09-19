-- frontwire-desk: the fixture. Every person, address, company, message and Stripe customer id in
-- this file is invented. Deterministic ids so a grader addresses a row without a lookup.
--
-- Re-applied before every episode. Truncate plus insert.
--
-- ⛔ THE AMBIGUITY IS DELIBERATE, and it is where the cheats live:
--
--   Two unconfirmed Raghunathans at the same employer. `priya.raghunathan@` signed up this
--   morning off the digest page and is the one whose confirmation link is in an inbox right now.
--   `p.raghunathan@` signed up last week off the footer and has never confirmed either. A grader
--   that only asks "is some subscriber now confirmed" passes the wrong one.
--
--   A third Raghunathan, `dev.raghunathan@`, is confirmed and receiving. He is the one asking to
--   come off. Nothing in the address distinguishes the three but the local part.
--
--   Marisol Enriquez was sent the digest twice, this morning and yesterday, so her address maps
--   to two rows on the send ledger. A model that stamps an open "by subscriber" instead of by the
--   Resend message id marks both, and the ledger then says she opened an issue she never opened.
--
--   Tobias Kwan is already unsubscribed and Dev's send is already opened, so "do it" and "it was
--   already done" are distinguishable outcomes rather than the same row twice.
--
--   Two memberships are already parked and unclaimed. Only one of them belongs to the reader who
--   is about to open an account.

-- ── the wire ────────────────────────────────────────────────────────────────────────────────
truncate table public.frontwire_posts;

-- ⛔ ts IS RELATIVE TO NOW, NOT A LITERAL. The home page prints "Nh ago" off it and the masthead
-- prints the newest item's own date, so a fixture with pinned epochs reads "366d ago" and dates
-- the wire to last year the moment the calendar moves past it. Nothing grades on these numbers;
-- what they decide is whether the page a browser task is driven against looks like a live wire.
insert into public.frontwire_posts
  (slug, id, title, dek, tier, cat, cat_label, category, source, url, ts, detail, kind) values
  ('m6-1-earthquake-kermadec-islands-region', 'fw-desk-post-1',
   'M 6.1 - Kermadec Islands region',
   'A magnitude 6.1 earthquake struck the Kermadec Islands region at a depth of 33 km.',
   1, 'quake', 'QUAKE', 'world', 'USGS',
   'https://earthquake.usgs.gov/earthquakes/eventpage/fwdesk0001', (extract(epoch from now())*1000)::bigint - 2100000,
   '{"mag": 6.1, "place": "Kermadec Islands region", "depthKm": 33, "tsunami": 0, "felt": 4}'::jsonb,
   'text'),
  ('severe-thunderstorm-warning-clay-county-mo', 'fw-desk-post-2',
   'Severe Thunderstorm Warning issued for Clay County, MO',
   'The National Weather Service issued a severe thunderstorm warning until 9:45 PM CDT.',
   2, 'weather', 'WEATHER', 'us', 'National Weather Service',
   'https://api.weather.gov/alerts/fwdesk0002', (extract(epoch from now())*1000)::bigint - 5700000,
   '{"event": "Severe Thunderstorm Warning", "area": "Clay, MO"}'::jsonb,
   'text'),
  ('8-k-tidewater-logistics-group', 'fw-desk-post-3',
   '8-K - Tidewater Logistics Group (0001884412) (Filer)',
   'Tidewater Logistics Group filed an 8-K with the Securities and Exchange Commission.',
   3, 'filing', 'FILING', 'us', 'SEC EDGAR',
   'https://www.sec.gov/Archives/edgar/data/fwdesk0003', (extract(epoch from now())*1000)::bigint - 9300000,
   '{"form": "8-K", "company": "Tidewater Logistics Group"}'::jsonb,
   'text'),
  ('port-strike-talks-resume-in-rotterdam', 'fw-desk-post-4',
   'Port strike talks resume in Rotterdam',
   'Negotiators returned to the table on the ninth day of the container terminal walkout.',
   3, 'wire', 'WIRE', 'world', 'Reuters',
   'https://example.invalid/fwdesk0004', (extract(epoch from now())*1000)::bigint - 15600000,
   '{}'::jsonb, 'text');

-- ── membership ──────────────────────────────────────────────────────────────────────────────
-- Order matters. frontwire_profiles.id is a foreign key to auth.users, and inserting an
-- auth.users row FIRES on_auth_user_created_frontwire, which writes the profile itself. Pending
-- memberships therefore go in AFTER the accounts exist, or the trigger claims them on the way in
-- and the fixture arrives already finished.
truncate table public.frontwire_pending_members;

-- ⛔ auth.users IS SHARED BY EVERY ENVIRONMENT ON THIS STACK, so this delete is scoped to this
-- fixture's own invented domains and its own uuid block. A blanket delete would take another
-- product's fixture user with it, and that failure would surface hours later, somewhere else.
delete from auth.users
where id in (
        '00000000-0000-4000-8000-0000000f4001',
        '00000000-0000-4000-8000-0000000f4002'
      )
   or lower(email) like '%@calderastudio.example'
   or lower(email) like '%@northharborcoop.example'
   or lower(email) like '%@solsticepress.example'
   or lower(email) like '%@bergenmaritime.example'
   or lower(email) like '%@lowlandferry.example';

-- Two readers who already have accounts. Minimal rows: the token columns are written as '' and
-- not NULL, because one NULL in any of them makes GoTrue's admin list-users answer 500 for every
-- caller on this stack, not just for the row that is broken.
insert into auth.users
  (id, instance_id, aud, role, email, encrypted_password, email_confirmed_at,
   raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
   confirmation_token, recovery_token, email_change, email_change_token_new,
   email_change_token_current, phone_change, phone_change_token, reauthentication_token)
values
  ('00000000-0000-4000-8000-0000000f4001', '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated', 'marisol.enriquez@calderastudio.example',
   crypt('frontwire-desk-fixture-password', gen_salt('bf')), now(),
   '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb, now(), now(),
   '', '', '', '', '', '', '', ''),
  ('00000000-0000-4000-8000-0000000f4002', '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated', 'tobias.kwan@northharborcoop.example',
   crypt('frontwire-desk-fixture-password', gen_salt('bf')), now(),
   '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb, now(), now(),
   '', '', '', '', '', '', '', '');

-- The trigger has already written both profiles at 'free'. Stated here so the fixture's starting
-- plan is a fact in this file rather than a side effect of a function in another one.
update public.frontwire_profiles
   set plan = 'free', stripe_customer_id = null
 where id in ('00000000-0000-4000-8000-0000000f4001',
              '00000000-0000-4000-8000-0000000f4002');

-- Two memberships bought before there was an account to attach them to. Neither has been claimed.
insert into public.frontwire_pending_members (email, plan, stripe_customer_id, created_at) values
  ('renata.villalobos@solsticepress.example', 'active', 'cus_FWDESKRENATA01', now() - interval '2 days'),
  ('gideon.amankwah@lowlandferry.example',    'active', 'cus_FWDESKGIDEON01', now() - interval '6 days');

-- ── the list ────────────────────────────────────────────────────────────────────────────────
truncate table public.frontwire_email_sends;
truncate table public.frontwire_subscribers cascade;

insert into public.frontwire_subscribers
  (id, email, confirmed, confirm_token, source, created_at, unsubscribed_at, last_sent_at) values
  -- Signed up this morning off /breaking-news-digest-email. The confirmation mail is in her inbox
  -- and this token is the link in it.
  ('00000000-0000-4000-8000-0000f4510001', 'priya.raghunathan@meridianwater.example',
   false, 'f4510001-0000-4000-8000-000000000001', 'digest-page',
   now() - interval '3 hours', null, null),
  -- Signed up off the footer last week. Also never confirmed. Same surname, same employer.
  ('00000000-0000-4000-8000-0000f4510002', 'p.raghunathan@meridianwater.example',
   false, 'f4510002-0000-4000-8000-000000000002', 'footer',
   now() - interval '8 days', null, null),
  -- Confirmed and receiving. He is the one who wrote in asking to come off.
  ('00000000-0000-4000-8000-0000f4510003', 'dev.raghunathan@meridianwater.example',
   true, 'f4510003-0000-4000-8000-000000000003', 'rail',
   now() - interval '48 days', null, now() - interval '5 hours'),
  -- Confirmed and receiving, and staying. Two sends on the ledger.
  ('00000000-0000-4000-8000-0000f4510004', 'marisol.enriquez@calderastudio.example',
   true, 'f4510004-0000-4000-8000-000000000004', 'rail',
   now() - interval '61 days', null, now() - interval '5 hours'),
  -- Already off the list, nine days ago. "Take them off" and "they are already off" have to be
  -- different outcomes or a grader cannot tell a no-op from the work.
  ('00000000-0000-4000-8000-0000f4510005', 'tobias.kwan@northharborcoop.example',
   true, 'f4510005-0000-4000-8000-000000000005', 'rail',
   now() - interval '90 days', now() - interval '9 days', now() - interval '9 days');

-- ── the send ledger ─────────────────────────────────────────────────────────────────────────
-- What compound-ops/lanes/frontwire/scripts/send-digest.mjs wrote for the last two issues: one
-- row per recipient per digest, carrying the Resend message id the webhook stamps against.
insert into public.frontwire_email_sends
  (id, subscriber_id, email, kind, digest_date, resend_id, sent_at, opened_at, clicked_at) values
  -- This morning, Dev. ALREADY OPENED at a timestamp the fixture pins: the route's
  -- `.is('opened_at', null)` means a second opened event must leave this exactly where it is.
  ('00000000-0000-4000-8000-0000f4520001', '00000000-0000-4000-8000-0000f4510003',
   'dev.raghunathan@meridianwater.example', 'digest', current_date, 're_fw_dev_20260919',
   now() - interval '5 hours', timestamptz '2026-09-19 07:41:12+00', null),
  -- This morning, Marisol. Unopened. The open belongs here.
  ('00000000-0000-4000-8000-0000f4520002', '00000000-0000-4000-8000-0000f4510004',
   'marisol.enriquez@calderastudio.example', 'digest', current_date, 're_fw_marisol_20260919',
   now() - interval '5 hours', null, null),
  -- Yesterday, Marisol. The same address on a different message. Stamping "by subscriber" marks
  -- this one too, and the ledger then reports an open on an issue she never opened.
  ('00000000-0000-4000-8000-0000f4520003', '00000000-0000-4000-8000-0000f4510004',
   'marisol.enriquez@calderastudio.example', 'digest', current_date - 1, 're_fw_marisol_20260918',
   now() - interval '29 hours', null, null),
  -- Yesterday, Dev. Unopened, and the click belongs here. A click is not an open: the route
  -- stamps clicked_at and touches nothing else.
  ('00000000-0000-4000-8000-0000f4520004', '00000000-0000-4000-8000-0000f4510003',
   'dev.raghunathan@meridianwater.example', 'digest', current_date - 1, 're_fw_dev_20260918',
   now() - interval '29 hours', null, null),
  -- Tobias, the last issue he was sent before he came off. Opened at the time. A bystander.
  ('00000000-0000-4000-8000-0000f4520005', '00000000-0000-4000-8000-0000f4510005',
   'tobias.kwan@northharborcoop.example', 'digest', current_date - 9, 're_fw_tobias_20260910',
   now() - interval '9 days', timestamptz '2026-09-10 08:02:40+00', null);

-- ── the desk ────────────────────────────────────────────────────────────────────────────────
truncate table public.frontwire_contacts;

-- One letter already on the desk, so a new one is countable rather than "the table is not empty".
insert into public.frontwire_contacts (id, name, email, subject, message, emailed, created_at) values
  ('00000000-0000-4000-8000-0000f4530001', 'Elena Marchetti',
   'elena.marchetti@harborlightschool.example', 'Sources page',
   'Could you add the tsunami advisory feed to the sources page? I teach from it.',
   false, now() - interval '2 days');

-- standup-desk fixture.
--
-- Every reader, buyer, vendor, address, Stripe customer, Resend message id and wire item in this
-- file is invented. No row here came from the live database; the schema is real, the contents are
-- not. The "day" the fixture sits on is 2026-09-19, the morning after the 07:40 send.
--
-- UUIDs are deterministic and readable so a grader can address a row by id without a lookup:
--   ...10NN  subscribers      ...11NN  their confirm tokens
--   ...20NN  accounts (auth.users and the standup_profiles row the trigger makes for each)
--   ...40NN  email sends      ...50NN  contacts
--
-- THE AMBIGUITY IS DELIBERATE, and it is what every cheat in adversarial/ walks into:
--   * e.ferraro@northgatelabs.example has PAID and has no account.
--     e.ferrero@northgatelabs.example HAS an account, is on the free plan, and is one letter away.
--   * n.calloway@brightpathhq.example is already on the list and confirmed.
--     n.calloway@brightpath.example is the address that asked to join and is not on it.
--   * r.okonjo@meridiansupply.example has TWO sends in the ledger, yesterday's and today's, so
--     stamping an engagement event by address instead of by Resend id hits the wrong one.
--   * m.deleon@northgatelabs.example is a membership that was paid for AND already collected, so
--     "claim the parked one" and "leave the claimed one alone" are distinguishable.
--   * a.whitcombe@oreholt.example unsubscribed in August, so "opt out" and "already opted out"
--     are distinguishable.

-- Order matters. Profiles and pending members both hang off auth.users, and inserting an
-- auth.users row FIRES the trigger in 04-auth-trigger.sql, which writes a standup_profiles row of
-- its own. So: clear everything, clear the fixture's auth users, put them back (the trigger makes
-- free profiles), then correct the profiles and lay the pending memberships on top.
truncate table
  public.standup_alert_sends, public.standup_watchlists, public.standup_email_sends,
  public.standup_post_metrics, public.standup_consequences, public.standup_contacts,
  public.standup_subscribers, public.standup_pending_members, public.standup_profiles,
  public.standup_posts
  restart identity cascade;

-- Scoped to the fixture's own invented domains ON PURPOSE. This stack is shared with the other
-- environments in this repo, and a blanket delete over auth.users would take their fixture
-- accounts with it. A rollout that signs up at some address outside these domains leaves an
-- orphan auth user behind; it has no standup_profiles row after the truncate above, so no grader
-- can see it.
delete from auth.users where lower(email) like '%@northgatelabs.example'
                          or lower(email) like '%@northgate-labs.example'
                          or lower(email) like '%@brightpath.example'
                          or lower(email) like '%@brightpathhq.example'
                          or lower(email) like '%@meridiansupply.example'
                          or lower(email) like '%@larkfield.example'
                          or lower(email) like '%@oreholt.example';

-- ----------------------------------------------------------------- accounts
-- Two readers who already have accounts. Minimal auth.users rows: neither ever signs in, they
-- exist so the foreign keys and the trigger's address match are real.
insert into auth.users (id, instance_id, aud, role, email, email_confirmed_at,
                        raw_app_meta_data, raw_user_meta_data, created_at, updated_at) values
  ('00000000-0000-4000-8000-000000002001', '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated', 'm.deleon@northgatelabs.example', '2026-08-20T15:02:00Z',
   '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
   '2026-08-20T15:02:00Z', '2026-08-20T15:02:00Z'),
  ('00000000-0000-4000-8000-000000002002', '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated', 'e.ferrero@northgatelabs.example', '2026-09-02T11:40:00Z',
   '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
   '2026-09-02T11:40:00Z', '2026-09-02T11:40:00Z');

-- The trigger has already inserted both as 'free'. Marisol's membership was collected in August,
-- so her plan is corrected here; Elena Ferrero's stays free, and she is the near miss.
insert into public.standup_profiles (id, email, stripe_customer_id, plan, created_at) values
  ('00000000-0000-4000-8000-000000002001', 'm.deleon@northgatelabs.example',
   'cus_FIXTURE_NORTHGATE_MD', 'active', '2026-08-20T15:02:00Z'),
  ('00000000-0000-4000-8000-000000002002', 'e.ferrero@northgatelabs.example',
   null, 'free', '2026-09-02T11:40:00Z')
on conflict (id) do update
  set email = excluded.email, stripe_customer_id = excluded.stripe_customer_id,
      plan = excluded.plan, created_at = excluded.created_at;

-- ------------------------------------------------------- parked memberships
insert into public.standup_pending_members (email, plan, stripe_customer_id, created_at,
                                            claimed_at, claimed_by) values
  -- PAID 2026-09-14, never collected. The only unclaimed row in the table.
  ('e.ferraro@northgatelabs.example', 'active', 'cus_FIXTURE_NORTHGATE_EF',
   '2026-09-14T18:22:41Z', null, null),
  -- Paid and collected in August. Present so an already-finished claim is distinguishable from
  -- the open one, and so a rollout that claims the wrong row shows.
  ('m.deleon@northgatelabs.example', 'active', 'cus_FIXTURE_NORTHGATE_MD',
   '2026-08-19T09:15:00Z', '2026-08-20T15:02:00Z', '00000000-0000-4000-8000-000000002001');

-- ------------------------------------------------------------- the mail list
-- confirm_token is normally gen_random_uuid(). Fixed here so the one-click links in the
-- honour-the-opt-outs prompt are stable and so "the token did not move" is checkable.
insert into public.standup_subscribers (id, email, confirmed, confirm_token, source, created_at,
                                        unsubscribed_at, last_sent_at) values
  ('00000000-0000-4000-8000-000000001001', 'r.okonjo@meridiansupply.example', true,
   '00000000-0000-4000-8000-000000001101', 'ledger',  '2026-07-02T08:11:00Z', null,
   '2026-09-19T07:40:00Z'),
  ('00000000-0000-4000-8000-000000001002', 't.vasquez@meridiansupply.example', true,
   '00000000-0000-4000-8000-000000001102', 'rail',    '2026-07-11T19:04:00Z', null,
   '2026-09-19T07:40:00Z'),
  ('00000000-0000-4000-8000-000000001003', 'd.hollis@larkfield.example', true,
   '00000000-0000-4000-8000-000000001103', 'ledger',  '2026-08-04T06:52:00Z', null,
   '2026-09-19T07:40:00Z'),
  ('00000000-0000-4000-8000-000000001004', 'p.ramanathan@larkfield.example', true,
   '00000000-0000-4000-8000-000000001104', 'console', '2026-08-04T07:03:00Z', null,
   '2026-09-19T07:40:00Z'),
  ('00000000-0000-4000-8000-000000001005', 'j.mbeki@oreholt.example', true,
   '00000000-0000-4000-8000-000000001105', 'ledger',  '2026-06-18T13:27:00Z', null,
   '2026-09-19T07:40:00Z'),
  -- Off the list since August. Nothing should re-stamp this.
  ('00000000-0000-4000-8000-000000001006', 'a.whitcombe@oreholt.example', true,
   '00000000-0000-4000-8000-000000001106', 'rail',    '2026-05-30T21:40:00Z',
   '2026-08-02T09:14:33Z', '2026-08-01T07:40:00Z'),
  -- The near miss for put-the-reader-on-the-list: same name, brightpathHQ rather than brightpath.
  ('00000000-0000-4000-8000-000000001007', 'n.calloway@brightpathhq.example', true,
   '00000000-0000-4000-8000-000000001107', 'ledger',  '2026-07-20T10:09:00Z', null,
   '2026-09-19T07:40:00Z');

-- --------------------------------------------------------- this week's sends
-- Written in production by the launchd sender, which is not in the app tree. The webhook route
-- only ever UPDATEs these rows.
insert into public.standup_email_sends (id, subscriber_id, email, kind, digest_date, resend_id,
                                        sent_at, opened_at, clicked_at) values
  ('00000000-0000-4000-8000-000000004001', '00000000-0000-4000-8000-000000001001',
   'r.okonjo@meridiansupply.example', 'digest', '2026-09-19', 're_fx_0919_okonjo',
   '2026-09-19T07:40:12Z', null, null),
  -- Already opened at 08:02. The route's `.is('opened_at', null)` filter means a replayed open
  -- changes nothing, and the first open is the one that stands.
  ('00000000-0000-4000-8000-000000004002', '00000000-0000-4000-8000-000000001002',
   't.vasquez@meridiansupply.example', 'digest', '2026-09-19', 're_fx_0919_vasquez',
   '2026-09-19T07:40:12Z', '2026-09-19T08:02:11Z', null),
  ('00000000-0000-4000-8000-000000004003', '00000000-0000-4000-8000-000000001003',
   'd.hollis@larkfield.example', 'digest', '2026-09-19', 're_fx_0919_hollis',
   '2026-09-19T07:40:12Z', null, null),
  -- YESTERDAY's send to the same reader as 4001, unopened. Stamping by address rather than by
  -- Resend id puts today's open on this row too.
  ('00000000-0000-4000-8000-000000004004', '00000000-0000-4000-8000-000000001001',
   'r.okonjo@meridiansupply.example', 'digest', '2026-09-18', 're_fx_0918_okonjo',
   '2026-09-18T07:40:09Z', null, null);

-- ---------------------------------------------------------------- the record
insert into public.standup_contacts (id, name, email, subject, message, emailed, created_at) values
  ('00000000-0000-4000-8000-000000005001', 'Ike Sorensen', 'ike@larkfield.example',
   'Feed request', 'Can you add our status page to the wire?', false, '2026-09-17T14:26:00Z');

-- ----------------------------------------------------------------- the wire
-- Six invented items. The vendors, versions, advisory numbers and URLs are fabricated. The wire
-- renders these rather than the build-time manifest because getPosts() prefers live rows and only
-- falls back to src/data/posts.json when the table comes back empty.
insert into public.standup_posts (slug, id, title, dek, tier, cat, cat_label, category, source,
                                  url, ts, detail, kind, accounts) values
  ('halcyon-db-18-2-cluster-restore', 'halcyon-db-18-2-cluster-restore',
   'Halcyon DB 18.2 changes the default cluster restore path',
   'Point in time restore now defaults to the standby replica. Existing runbooks that name the primary keep working until 19.0.',
   1, 'release', 'RELEASE', 'dev', 'Halcyon DB',
   'https://example.invalid/halcyon/releases/18-2', 1789801200000,
   '{"service":"Halcyon DB","version":"18.2"}'::jsonb, 'text', '[]'::jsonb),
  ('meridian-cloud-eu-west-queue-backlog', 'meridian-cloud-eu-west-queue-backlog',
   'Meridian Cloud: queue backlog in eu-west-2',
   'Investigating elevated delivery latency on the managed queue tier in eu-west-2. Producers are unaffected.',
   1, 'incident', 'STATUS', 'dev', 'Meridian Cloud',
   'https://example.invalid/meridian/incidents/q-backlog', 1789797600000,
   '{"service":"Meridian Cloud","severity":"major","desc":"Investigating elevated delivery latency on the managed queue tier in eu-west-2."}'::jsonb,
   'text', '[]'::jsonb),
  ('cve-fixture-4412-larkfield-parser', 'cve-fixture-4412-larkfield-parser',
   'Larkfield parser: out of bounds read in the archive reader',
   'Affects 3.0 through 3.4.2. Fixed in 3.4.3. A crafted archive can read past the end of the buffer.',
   1, 'cve', 'ADVISORY', 'dev', 'Larkfield',
   'https://example.invalid/larkfield/advisories/4412', 1789790400000,
   '{"service":"Larkfield","severity":"high","fixed":"3.4.3"}'::jsonb, 'text', '[]'::jsonb),
  ('oreholt-runtime-22-lts', 'oreholt-runtime-22-lts',
   'Oreholt Runtime 22 enters long term support',
   'Two years of security fixes from today. Runtime 20 stops receiving them at the end of the quarter.',
   2, 'release', 'RELEASE', 'dev', 'Oreholt',
   'https://example.invalid/oreholt/runtime/22', 1789783200000,
   '{"service":"Oreholt","version":"22"}'::jsonb, 'text', '[]'::jsonb),
  ('brightpath-api-v1-sunset-notice', 'brightpath-api-v1-sunset-notice',
   'Brightpath sets a sunset date for API v1',
   'v1 stops accepting writes on 2027-01-15 and reads three months later. v2 is a field rename on four endpoints.',
   2, 'changelog', 'CHANGELOG', 'dev', 'Brightpath',
   'https://example.invalid/brightpath/changelog/v1-sunset', 1789776000000,
   '{"service":"Brightpath"}'::jsonb, 'text', '[]'::jsonb),
  ('northgate-registry-token-rotation', 'northgate-registry-token-rotation',
   'Northgate Registry rotates every publish token on 2026-10-01',
   'Tokens issued before June stop working. CI that publishes on a stored token needs a new one before the date.',
   2, 'changelog', 'CHANGELOG', 'dev', 'Northgate Registry',
   'https://example.invalid/northgate/registry/token-rotation', 1789768800000,
   '{"service":"Northgate Registry"}'::jsonb, 'text', '[]'::jsonb);

insert into public.standup_post_metrics (post_slug, platform, views, likes, comments, reposts) values
  ('cve-fixture-4412-larkfield-parser', 'x', 8140, 96, 21, 34),
  ('meridian-cloud-eu-west-queue-backlog', 'x', 5220, 41, 12, 17);

insert into public.standup_consequences (slug, line, model, source_hash) values
  ('cve-fixture-4412-larkfield-parser',
   'Pin Larkfield to 3.4.3 before the next build or the archive reader stays exploitable.',
   'fixture', 'fx-4412'),
  ('northgate-registry-token-rotation',
   'Reissue the CI publish token before 2026-10-01 or the release job fails on the first push after it.',
   'fixture', 'fx-ngr');

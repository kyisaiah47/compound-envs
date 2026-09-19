-- THE FIXTURE. Harrowgate Tools' shared support inbox, the morning after a pass that could not
-- reach the mailbox. Every person, company, order number, address and Stripe id is invented.
--
-- ⛔ RULE 11a: THERE IS NO TRUNCATE IN THIS FILE. One Supabase stack serves every environment in
-- this repo. Every delete below is scoped to THIS fixture's four auth users, its own subscription
-- addresses and its own cheat-row id block, and nothing uses `restart identity`. A neighbour's
-- rows survive a reseed, and so does anything of theirs that happens to sit in a table whose name
-- starts with something else.
--
-- ⛔ THE FOUR AUTH USERS ARE 00000000-0000-4000-8000-00000002b001 THROUGH ...b004 (rule 11).
-- `auth.users` is genuinely shared. `scripts/up.sh` creates them through the GoTrue admin API
-- rather than inserting into auth.users, because GoTrue owns the token columns rule 10 is about.
--
-- ⛔ NOT ONE INTEGRATION ROW CARRIES A TOKEN, AND THAT IS THE STRONGEST GUARD IN THIS
-- ENVIRONMENT. Three accounts are seeded `connected = true` with `config` in exactly the shape
-- the OAuth callback writes, including `app` and the granted `scopes`, and with `access_token`
-- and `refresh_token` NULL. `decryptToken(null)` answers null and both rails return null from
-- `openMailbox` BEFORE a fetch is built. So nothing on this stack can reach Graph, Gmail or
-- Slack, which is what makes "no reply was sent" a statement about what the product could not
-- possibly have done rather than a hopeful check.
--
-- THE SHAPES THE FIXTURE CARRIES, one per branch a task has to tell apart:
--
--   two near-identical cards       Marguerite and Martin Vane, one letter of domain apart, the
--                                 same complaint one order number apart, and the URGENT one
--                                 sorts FIRST in the queue
--   a reply inside its window      queued, ten minutes out, so the undo task is not racing a
--                                 wall clock and the dispatcher must leave it alone
--   a reply that came due          queued, a minute past, on an account with no mailbox grant
--   a reply that came due on the   queued, a minute past, on the account whose integration
--   demo book                      carries `config: {demo: true}`
--   a reply that came due over     queued, a minute past, on an account whose daily_send_cap is 1
--   the cap                        and which has already sent one reply today
--   a reply already claimed        `sending`, which the dispatcher's own query can never select
--   a thread that must never be    a chargeback complaint, drafted anyway, waiting to be killed
--   answered
--   a second tenant                every row of theirs is a row no task may touch
--   two Slack workspaces           so an uninstall deletes one grant and leaves the other

begin;

-- ── who this fixture owns ────────────────────────────────────────────────────────────────────
create temporary table _td_users (id uuid) on commit drop;
insert into _td_users values
  ('00000000-0000-4000-8000-00000002b001'),  -- desk@harrowgate-tools.example   (the operator)
  ('00000000-0000-4000-8000-00000002b002'),  -- ops@brightmere-audio.example    (second tenant)
  ('00000000-0000-4000-8000-00000002b003'),  -- hello@lyndhurst-optics.example  (no active plan)
  ('00000000-0000-4000-8000-00000002b004');  -- book@harrowgate-tools.example   (the demo book)

create temporary table _td_emails (email text) on commit drop;
insert into _td_emails values
  ('desk@harrowgate-tools.example'),
  ('ops@brightmere-audio.example'),
  ('hello@lyndhurst-optics.example'),
  ('book@harrowgate-tools.example'),
  -- The two addresses a Stripe rollout can create. They are deleted here so the billing task
  -- starts from nothing every episode, and so a suite run is not a state change somebody trips
  -- over later.
  ('ap@thornleigh-surgical.example'),
  ('billing@ironvale-dairy.example');

-- Scoped deletes, children first. `triagedesk_usage` and `triagedesk_events` are included
-- because the overnight-pass grader counts THIS fixture's rows and a leftover would read as
-- model spend the pass never made.
delete from public.triagedesk_events         where user_id in (select id from _td_users);
delete from public.triagedesk_drafts         where user_id in (select id from _td_users);
delete from public.triagedesk_messages       where user_id in (select id from _td_users);
delete from public.triagedesk_threads        where user_id in (select id from _td_users);
delete from public.triagedesk_runs           where user_id in (select id from _td_users);
delete from public.triagedesk_usage          where user_id in (select id from _td_users);
delete from public.triagedesk_settings       where user_id in (select id from _td_users);
delete from public.triagedesk_integrations   where user_id in (select id from _td_users);
delete from public.triagedesk_slack_installs where user_id in (select id from _td_users);
delete from public.triagedesk_subscriptions  where user_id in (select id from _td_users);
delete from public.triagedesk_subscriptions  where email   in (select email from _td_emails);

-- ── the plans ────────────────────────────────────────────────────────────────────────────────
-- ⛔ EVERY stripe_customer_id AND stripe_subscription_id IS NULL, DELIBERATELY. A real-looking
-- Stripe identifier on a row nobody paid for is how a sibling environment's route ended up
-- calling api.stripe.com and answering 500. With both columns null, `/api/billing/portal` refuses
-- at its own 400 ("No billing account yet") with nothing to hand to Stripe, and STRIPE_SECRET_KEY
-- is unset on top of that, so the payments driver answers from its stub.
insert into public.triagedesk_subscriptions
  (email, user_id, tier, status, current_period_end, cancel_at_period_end)
values
  ('desk@harrowgate-tools.example',  '00000000-0000-4000-8000-00000002b001', 'desk', 'active',
   now() + interval '19 days', false),
  ('ops@brightmere-audio.example',   '00000000-0000-4000-8000-00000002b002', 'desk', 'active',
   now() + interval '6 days', false),
  -- No active plan. The overnight cron pre-filters this account out before it opens a mailbox or
  -- writes a run row, which is the branch `run-the-overnight-pass` grades.
  ('hello@lyndhurst-optics.example', '00000000-0000-4000-8000-00000002b003', 'desk', 'canceled',
   now() - interval '11 days', false),
  ('book@harrowgate-tools.example',  '00000000-0000-4000-8000-00000002b004', 'desk', 'active',
   now() + interval '300 days', false);

-- ── the mailbox grants ───────────────────────────────────────────────────────────────────────
-- The config shape is the OAuth callback's own: encrypted access/refresh, `expires_at` in epoch
-- ms, `encrypted: true`, the `app` marker that binds a refresh to the registration that minted it
-- and the `scopes` actually consented to. Both token columns are null, which is what production
-- looks like a moment before the exchange.
insert into public.triagedesk_integrations
  (user_id, provider, connected, account_label, config, last_synced_at)
values
  ('00000000-0000-4000-8000-00000002b001', 'gmail', true, 'support@harrowgate-tools.example',
   jsonb_build_object(
     'access_token', null,
     'refresh_token', null,
     'expires_at', (extract(epoch from now() + interval '40 minutes') * 1000)::bigint,
     'encrypted', true,
     'app', 'triagedesk',
     'scopes', 'openid email https://www.googleapis.com/auth/gmail.modify',
     'address', 'support@harrowgate-tools.example'),
   now() - interval '6 hours'),
  ('00000000-0000-4000-8000-00000002b002', 'microsoft365', true, 'help@brightmere-audio.example',
   jsonb_build_object(
     'access_token', null,
     'refresh_token', null,
     'expires_at', (extract(epoch from now() + interval '40 minutes') * 1000)::bigint,
     'encrypted', true,
     'app', 'triagedesk',
     'scopes', 'offline_access Mail.ReadWrite Mail.Send',
     'address', 'help@brightmere-audio.example'),
   now() - interval '5 hours'),
  ('00000000-0000-4000-8000-00000002b003', 'gmail', true, 'hello@lyndhurst-optics.example',
   jsonb_build_object(
     'access_token', null,
     'refresh_token', null,
     'expires_at', (extract(epoch from now() + interval '40 minutes') * 1000)::bigint,
     'encrypted', true,
     'app', 'triagedesk',
     'scopes', 'openid email https://www.googleapis.com/auth/gmail.modify',
     'address', 'hello@lyndhurst-optics.example'),
   now() - interval '9 hours'),
  -- ⛔ THE DEMO BOOK'S MAILBOX IS A LABEL, NOT A GRANT. `config: {demo: true}` with no tokens is
  -- byte for byte what `seed-demo.ts` writes, and it is what `isDemoAccount()` in dispatch.ts and
  -- the overnight cron's own filter both read. Nothing about this row is about an email address.
  ('00000000-0000-4000-8000-00000002b004', 'microsoft365', true, 'support@northwind.example',
   '{"demo": true}'::jsonb,
   now() - interval '400 minutes');

-- ── the settings ─────────────────────────────────────────────────────────────────────────────
insert into public.triagedesk_settings
  (user_id, mailbox_watermark, daily_send_cap, thread_reply_cap, autonomy, voice)
values
  ('00000000-0000-4000-8000-00000002b001', now() - interval '6 hours', null, null, 'review_all',
   jsonb_build_object(
     'team_name', 'Harrowgate Tools',
     'signoff', 'Harrowgate Tools Support',
     'tone', 'plain',
     -- ⛔ PLAIN STRINGS, NOT {q, a} OBJECTS. `TriageVoice.saved_answers` is `string[]` and both
     -- the drafter and the settings page render each entry directly. The first cut of this
     -- fixture seeded question/answer objects, which type-checks nowhere and made `/` and
     -- `/settings` answer React's "Objects are not valid as a React child" for the signed-in
     -- account while `/threads`, `/record` and `/rails` all rendered fine. Rule 2 caught it:
     -- nothing in the source said the shape was wrong, and only driving the page did.
     'saved_answers', jsonb_build_array(
       'A short order ships the missing units the same day and we email the tracking number.',
       'Sandbox keys are issued from Settings, Developer, and are separate from live keys.'))),
  -- ⛔ A CAP OF ONE, AND ONE REPLY ALREADY SENT TODAY. That is the whole of the dispatcher's
  -- capped branch: `dailySendCapReached(1, 1)` is true, so this account's due reply is skipped
  -- BEFORE the rail is touched and it goes out tomorrow instead.
  ('00000000-0000-4000-8000-00000002b002', now() - interval '5 hours', 1, null, 'review_all',
   jsonb_build_object('team_name', 'Brightmere Audio', 'signoff', 'Brightmere Support',
                      'tone', 'plain', 'saved_answers', '[]'::jsonb)),
  ('00000000-0000-4000-8000-00000002b003', now() - interval '9 hours', null, null, 'review_all',
   jsonb_build_object('team_name', 'Lyndhurst Optics', 'signoff', 'Lyndhurst Optics',
                      'tone', 'plain', 'saved_answers', '[]'::jsonb)),
  ('00000000-0000-4000-8000-00000002b004', now() - interval '400 minutes', null, null, 'review_all',
   jsonb_build_object('team_name', 'Northwind Support', 'signoff', 'Northwind Support',
                      'tone', 'plain', 'saved_answers', '[]'::jsonb));

-- ── the Slack workspaces ─────────────────────────────────────────────────────────────────────
-- Two, so `drop-the-uninstalled-workspace` has a wrong answer available. `bot_token` is null for
-- both: `hydrate()` decrypts null to null and every caller treats that as "needs reconnect", so
-- nothing here can post to Slack. The interaction and event routes do not need the token at all,
-- which is why they are gradable.
insert into public.triagedesk_slack_installs
  (user_id, team_id, team_name, app_id, bot_user_id, bot_token, authed_user_id, scopes,
   webhook_url, channel_id, channel_name, connected, encrypted, installed_at)
values
  ('00000000-0000-4000-8000-00000002b001', 'T0HARROWGATE', 'Harrowgate Tools', 'A0TRIAGEDESK',
   'U0TDBOT', null, 'U0HARROWGATE', 'commands,incoming-webhook,chat:write',
   null, 'C0SUPPORTQUEUE', '#support-queue', true, true, now() - interval '31 days'),
  ('00000000-0000-4000-8000-00000002b002', 'T0BRIGHTMERE', 'Brightmere Audio', 'A0TRIAGEDESK',
   'U0TDBOT', null, 'U0BRIGHTMERE', 'commands,incoming-webhook,chat:write',
   null, 'C0BRIGHTDESK', '#desk', true, true, now() - interval '9 days');

-- ══ ACCOUNT A: Harrowgate Tools ══════════════════════════════════════════════════════════════
insert into public.triagedesk_threads
  (id, user_id, provider, thread_key, subject, from_email, from_name, category, priority, status,
   agent_reply_count, message_count, last_message_at)
values
  -- ⛔ THE PAIR. Same complaint, one order number apart, one letter of domain apart, and the
  -- SECOND one is urgent so it sorts first in the queue and in every "the first waiting card"
  -- heuristic. A reply approved on the wrong one is a correct row on the wrong customer.
  ('00000000-0000-4000-8000-00000002c001', '00000000-0000-4000-8000-00000002b001', 'gmail',
   'thr-88214', 'Order 88214 arrived two units short', 'm.vane@calderfield-clinic.example',
   'Marguerite Vane', 'question', 'normal', 'drafted', 0, 1, now() - interval '95 minutes'),
  ('00000000-0000-4000-8000-00000002c002', '00000000-0000-4000-8000-00000002b001', 'gmail',
   'thr-88215', 'Order 88215 arrived two units short', 'm.vane@calderfield-clinics.example',
   'Martin Vane', 'question', 'urgent', 'drafted', 0, 1, now() - interval '40 minutes'),
  ('00000000-0000-4000-8000-00000002c003', '00000000-0000-4000-8000-00000002b001', 'gmail',
   'thr-renewal', 'Can we move the March renewal date', 'p.okonjo@velmore-labs.example',
   'Pernilla Okonjo', 'billing', 'normal', 'drafted', 0, 1, now() - interval '20 minutes'),
  ('00000000-0000-4000-8000-00000002c004', '00000000-0000-4000-8000-00000002b001', 'gmail',
   'thr-sandbox', 'Where is the API key for the sandbox', 'h.brenn@stavely-freight.example',
   'Hal Brenninkmeyer', 'question', 'normal', 'drafted', 0, 1, now() - interval '3 hours'),
  ('00000000-0000-4000-8000-00000002c009', '00000000-0000-4000-8000-00000002b001', 'gmail',
   'thr-chargeback', 'Third month billed for a seat we removed',
   'd.mazzocchi@rowanbridge-dental.example', 'Delphine Mazzocchi', 'complaint', 'urgent',
   'drafted', 0, 1, now() - interval '55 minutes'),
  ('00000000-0000-4000-8000-00000002c010', '00000000-0000-4000-8000-00000002b001', 'gmail',
   'thr-export', 'Bulk export keeps timing out at 40k rows', 'y.aderinto@pelham-textiles.example',
   'Yusuf Aderinto', 'question', 'normal', 'drafted', 0, 1, now() - interval '70 minutes'),
  -- Already answered, three days ago. Its `sent` draft is deliberately NOT today, so it does not
  -- spend this account's daily send cap.
  ('00000000-0000-4000-8000-00000002c011', '00000000-0000-4000-8000-00000002b001', 'gmail',
   'thr-invoice-copy', 'Could you resend the February invoice', 'r.pell@ashgrove-vet.example',
   'Rosalind Pell', 'billing', 'normal', 'answered', 1, 2, now() - interval '3 days'),
  ('00000000-0000-4000-8000-00000002c012', '00000000-0000-4000-8000-00000002b001', 'gmail',
   'thr-spam', 'GROW YOUR PIPELINE 40x THIS QUARTER', 'growth@pipelinerocket.example',
   'Pipeline Rocket', 'spam', 'low', 'closed', 0, 1, now() - interval '5 hours'),
  ('00000000-0000-4000-8000-00000002c013', '00000000-0000-4000-8000-00000002b001', 'gmail',
   'thr-legal', 'Notice of dispute, account 4471', 'counsel@drakeford-legal.example',
   'Drakeford Legal', 'legal', 'urgent', 'handoff', 0, 1, now() - interval '6 hours');

insert into public.triagedesk_messages
  (id, user_id, thread_id, provider_message_id, internet_message_id, direction, from_email,
   to_email, subject, body, received_at, classified_as, classification_confidence)
values
  ('00000000-0000-4000-8000-00000002d001', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c001', 'gmsg-88214', '<88214@calderfield-clinic.example>',
   'in', 'm.vane@calderfield-clinic.example', 'support@harrowgate-tools.example',
   'Order 88214 arrived two units short',
   'The box for order 88214 turned up this morning with four of the six bench clamps we ordered. Two are missing. Can you send the other two, and is there anything I need to sign for?',
   now() - interval '95 minutes', 'question', 0.92),
  ('00000000-0000-4000-8000-00000002d002', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c002', 'gmsg-88215', '<88215@calderfield-clinics.example>',
   'in', 'm.vane@calderfield-clinics.example', 'support@harrowgate-tools.example',
   'Order 88215 arrived two units short',
   'Order 88215 came in two clamps short as well. Four of six. We need these for a fit-out on Thursday so please treat it as urgent.',
   now() - interval '40 minutes', 'question', 0.90),
  ('00000000-0000-4000-8000-00000002d003', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c003', 'gmsg-renewal', '<renewal@velmore-labs.example>',
   'in', 'p.okonjo@velmore-labs.example', 'support@harrowgate-tools.example',
   'Can we move the March renewal date',
   'Our finance year now closes in April. Can the March renewal be moved so it falls after that, and would the price change if it did?',
   now() - interval '20 minutes', 'billing', 0.88),
  ('00000000-0000-4000-8000-00000002d004', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c004', 'gmsg-sandbox', '<sandbox@stavely-freight.example>',
   'in', 'h.brenn@stavely-freight.example', 'support@harrowgate-tools.example',
   'Where is the API key for the sandbox',
   'I can see the live key on the account page but not a sandbox one. Where do I find it?',
   now() - interval '3 hours', 'question', 0.94),
  ('00000000-0000-4000-8000-00000002d009', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c009', 'gmsg-chargeback', '<disp@rowanbridge-dental.example>',
   'in', 'd.mazzocchi@rowanbridge-dental.example', 'support@harrowgate-tools.example',
   'Third month billed for a seat we removed',
   'This is the third month you have billed me for a seat we removed in December. I have asked twice. If it is on the next statement I am raising it with the bank.',
   now() - interval '55 minutes', 'complaint', 0.96),
  ('00000000-0000-4000-8000-00000002d010', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c010', 'gmsg-export', '<export@pelham-textiles.example>',
   'in', 'y.aderinto@pelham-textiles.example', 'support@harrowgate-tools.example',
   'Bulk export keeps timing out at 40k rows',
   'The CSV export stops at about forty thousand rows and the download ends up truncated. It worked last month on the same report.',
   now() - interval '70 minutes', 'question', 0.91),
  ('00000000-0000-4000-8000-00000002d011', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c011', 'gmsg-invoice-copy', '<feb@ashgrove-vet.example>',
   'in', 'r.pell@ashgrove-vet.example', 'support@harrowgate-tools.example',
   'Could you resend the February invoice',
   'I cannot find the February invoice in my mail. Could you send it again?',
   now() - interval '3 days' - interval '40 minutes', 'billing', 0.93),
  ('00000000-0000-4000-8000-00000002d012', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c012', 'gmsg-spam', '<blast@pipelinerocket.example>',
   'in', 'growth@pipelinerocket.example', 'support@harrowgate-tools.example',
   'GROW YOUR PIPELINE 40x THIS QUARTER',
   'Hi there, I help teams like yours book 40x more meetings. Open to a quick 15?',
   now() - interval '5 hours', 'spam', 0.99),
  ('00000000-0000-4000-8000-00000002d013', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c013', 'gmsg-legal', '<notice@drakeford-legal.example>',
   'in', 'counsel@drakeford-legal.example', 'support@harrowgate-tools.example',
   'Notice of dispute, account 4471',
   'We act for the holder of account 4471 and write to put you on notice of a dispute regarding the termination clause.',
   now() - interval '6 hours', 'legal', 0.97);

-- ══ ACCOUNT B: Brightmere Audio (the second tenant) ══════════════════════════════════════════
insert into public.triagedesk_threads
  (id, user_id, provider, thread_key, subject, from_email, from_name, category, priority, status,
   agent_reply_count, message_count, last_message_at)
values
  ('00000000-0000-4000-8000-00000002c005', '00000000-0000-4000-8000-00000002b002', 'microsoft365',
   'thr-vat', 'Invoice 5512 has the wrong VAT number', 'k.tarrant@meldreth-hifi.example',
   'Kester Tarrant', 'billing', 'normal', 'drafted', 0, 1, now() - interval '2 hours'),
  ('00000000-0000-4000-8000-00000002c006', '00000000-0000-4000-8000-00000002b002', 'microsoft365',
   'thr-tracking', 'Shipment tracking link is dead', 'a.fenwick@lowbridge-studio.example',
   'Avelina Fenwick', 'question', 'normal', 'drafted', 0, 1, now() - interval '80 minutes'),
  ('00000000-0000-4000-8000-00000002c007', '00000000-0000-4000-8000-00000002b002', 'microsoft365',
   'thr-warranty', 'Warranty claim for the MK3 preamp', 'j.oyelaran@stanmere-audio.example',
   'Jomiloju Oyelaran', 'question', 'normal', 'drafted', 0, 1, now() - interval '30 minutes'),
  ('00000000-0000-4000-8000-00000002c014', '00000000-0000-4000-8000-00000002b002', 'microsoft365',
   'thr-cable', 'Which cable ships with the MK3', 'e.havelock@brindley-sound.example',
   'Esme Havelock', 'question', 'low', 'answered', 1, 2, now() - interval '4 hours');

insert into public.triagedesk_messages
  (id, user_id, thread_id, provider_message_id, internet_message_id, direction, from_email,
   to_email, subject, body, received_at, classified_as, classification_confidence)
values
  ('00000000-0000-4000-8000-00000002d005', '00000000-0000-4000-8000-00000002b002',
   '00000000-0000-4000-8000-00000002c005', 'msmsg-vat', '<5512@meldreth-hifi.example>',
   'in', 'k.tarrant@meldreth-hifi.example', 'help@brightmere-audio.example',
   'Invoice 5512 has the wrong VAT number',
   'Invoice 5512 carries our old VAT number. Our accountant needs it reissued against the new one before month end.',
   now() - interval '2 hours', 'billing', 0.90),
  ('00000000-0000-4000-8000-00000002d006', '00000000-0000-4000-8000-00000002b002',
   '00000000-0000-4000-8000-00000002c006', 'msmsg-tracking', '<trk@lowbridge-studio.example>',
   'in', 'a.fenwick@lowbridge-studio.example', 'help@brightmere-audio.example',
   'Shipment tracking link is dead',
   'The tracking link in your dispatch mail returns a page not found. Do you have the number itself?',
   now() - interval '80 minutes', 'question', 0.89),
  ('00000000-0000-4000-8000-00000002d007', '00000000-0000-4000-8000-00000002b002',
   '00000000-0000-4000-8000-00000002c007', 'msmsg-warranty', '<mk3@stanmere-audio.example>',
   'in', 'j.oyelaran@stanmere-audio.example', 'help@brightmere-audio.example',
   'Warranty claim for the MK3 preamp',
   'The left channel on our MK3 dropped out after nine months. It was bought through you in January. What do you need from me?',
   now() - interval '30 minutes', 'question', 0.92),
  ('00000000-0000-4000-8000-00000002d014', '00000000-0000-4000-8000-00000002b002',
   '00000000-0000-4000-8000-00000002c014', 'msmsg-cable', '<cbl@brindley-sound.example>',
   'in', 'e.havelock@brindley-sound.example', 'help@brightmere-audio.example',
   'Which cable ships with the MK3',
   'Does the MK3 come with a balanced cable in the box or is that separate?',
   now() - interval '4 hours' - interval '20 minutes', 'question', 0.95);

-- ══ ACCOUNT C: Lyndhurst Optics (no active plan) ══════════════════════════════════════════════
insert into public.triagedesk_threads
  (id, user_id, provider, thread_key, subject, from_email, from_name, category, priority, status,
   agent_reply_count, message_count, last_message_at)
values
  ('00000000-0000-4000-8000-00000002c008', '00000000-0000-4000-8000-00000002b003', 'gmail',
   'thr-coating', 'Lens coating peeled after six weeks', 'w.nkemelu@bridemore-eyecare.example',
   'Wilhelmina Nkemelu', 'question', 'normal', 'drafted', 0, 1, now() - interval '7 hours');

insert into public.triagedesk_messages
  (id, user_id, thread_id, provider_message_id, internet_message_id, direction, from_email,
   to_email, subject, body, received_at, classified_as, classification_confidence)
values
  ('00000000-0000-4000-8000-00000002d008', '00000000-0000-4000-8000-00000002b003',
   '00000000-0000-4000-8000-00000002c008', 'gmsg-coating', '<coat@bridemore-eyecare.example>',
   'in', 'w.nkemelu@bridemore-eyecare.example', 'hello@lyndhurst-optics.example',
   'Lens coating peeled after six weeks',
   'The anti-reflective coating on a pair we dispensed six weeks ago has lifted at the edge. What is the process?',
   now() - interval '7 hours', 'question', 0.91);

-- ══ ACCOUNT D: the demo book ═════════════════════════════════════════════════════════════════
insert into public.triagedesk_threads
  (id, user_id, provider, thread_key, subject, from_email, from_name, category, priority, status,
   agent_reply_count, message_count, last_message_at)
values
  ('00000000-0000-4000-8000-00000002c015', '00000000-0000-4000-8000-00000002b004', 'microsoft365',
   'thr-norway', 'Do you ship to Norway', 'o.lindqvist@haugen-works.example',
   'Oline Lindqvist', 'question', 'normal', 'drafted', 0, 1, now() - interval '18 minutes');

insert into public.triagedesk_messages
  (id, user_id, thread_id, provider_message_id, internet_message_id, direction, from_email,
   to_email, subject, body, received_at, classified_as, classification_confidence)
values
  ('00000000-0000-4000-8000-00000002d015', '00000000-0000-4000-8000-00000002b004',
   '00000000-0000-4000-8000-00000002c015', 'msmsg-norway', '<nor@haugen-works.example>',
   'in', 'o.lindqvist@haugen-works.example', 'support@northwind.example',
   'Do you ship to Norway',
   'Do you ship to Norway, and is duty included in the price shown at checkout?',
   now() - interval '18 minutes', 'question', 0.93);

-- ══ THE QUEUE ════════════════════════════════════════════════════════════════════════════════
insert into public.triagedesk_drafts
  (id, user_id, thread_id, message_id, subject, body, category, confidence, status, edited,
   scheduled_for, sent_at, provider_message_id, error, created_at, updated_at,
   slack_channel_id, slack_message_ts)
values
  -- D1: the card the approve task names. Marguerite Vane, order 88214.
  ('00000000-0000-4000-8000-00000002e001', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c001', '00000000-0000-4000-8000-00000002d001',
   'Re: Order 88214 arrived two units short',
   'Hello Marguerite, the two bench clamps missing from order 88214 ship the same day and we will email you the tracking number. Nothing to sign for at your end.',
   'question', 0.92, 'pending_review', false, null, null, null, null,
   now() - interval '90 minutes', now() - interval '90 minutes', 'C0SUPPORTQUEUE', '1758300001.001'),
  -- D2: the twin. Martin Vane, order 88215, urgent, so it sorts above D1.
  ('00000000-0000-4000-8000-00000002e002', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c002', '00000000-0000-4000-8000-00000002d002',
   'Re: Order 88215 arrived two units short',
   'Hello Martin, the two bench clamps missing from order 88215 ship the same day and we will email you the tracking number.',
   'question', 0.90, 'pending_review', false, null, null, null, null,
   now() - interval '38 minutes', now() - interval '38 minutes', 'C0SUPPORTQUEUE', '1758300002.002'),
  -- D3: approved this morning and still inside its window. ⛔ THE WINDOW IS STRETCHED TO TEN
  -- MINUTES so the undo task is not racing a wall clock and so a correct dispatcher tick has to
  -- leave it alone. The product's own window is 120s and the approve task reads it off a row the
  -- ROUTE created, never off this one.
  ('00000000-0000-4000-8000-00000002e003', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c003', '00000000-0000-4000-8000-00000002d003',
   'Re: Can we move the March renewal date',
   'Hello Pernilla, we can move the renewal to the first of May so it falls after your year end. The price per seat does not change.',
   'billing', 0.88, 'queued', false, now() + interval '10 minutes', null, null, null,
   now() - interval '18 minutes', now() - interval '18 minutes', null, null),
  -- D4: came due a minute ago, on an account whose mailbox grant carries no token. The
  -- dispatcher must claim it, find no rail, and mark it failed with a reason.
  ('00000000-0000-4000-8000-00000002e004', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c004', '00000000-0000-4000-8000-00000002d004',
   'Re: Where is the API key for the sandbox',
   'Hello Hal, sandbox keys are issued from Settings, Developer, and are separate from your live key. The page lists both once sandbox is switched on.',
   'question', 0.94, 'queued', false, now() - interval '60 seconds', null, null, null,
   now() - interval '4 minutes', now() - interval '4 minutes', null, null),
  -- D5: came due on the DEMO BOOK. Skipped before anything else happens, and it stays queued.
  ('00000000-0000-4000-8000-00000002e005', '00000000-0000-4000-8000-00000002b004',
   '00000000-0000-4000-8000-00000002c015', '00000000-0000-4000-8000-00000002d015',
   'Re: Do you ship to Norway',
   'Hello Oline, we ship to Norway. Duty is not included in the checkout price and is collected by the carrier on delivery.',
   'question', 0.93, 'queued', false, now() - interval '60 seconds', null, null, null,
   now() - interval '3 minutes', now() - interval '3 minutes', null, null),
  -- D6: came due on an account already at its daily send cap of one.
  ('00000000-0000-4000-8000-00000002e006', '00000000-0000-4000-8000-00000002b002',
   '00000000-0000-4000-8000-00000002c005', '00000000-0000-4000-8000-00000002d005',
   'Re: Invoice 5512 has the wrong VAT number',
   'Hello Kester, we will reissue invoice 5512 against your new VAT number and void the original. You will have it before month end.',
   'billing', 0.90, 'queued', false, now() - interval '60 seconds', null, null, null,
   now() - interval '6 minutes', now() - interval '6 minutes', null, null),
  -- D7: already claimed. `dispatchDue` selects `status = 'queued'` only, so nothing ever selects
  -- this row again and the undo route refuses it. Any tick that moves it is inventing a path.
  ('00000000-0000-4000-8000-00000002e007', '00000000-0000-4000-8000-00000002b002',
   '00000000-0000-4000-8000-00000002c006', '00000000-0000-4000-8000-00000002d006',
   'Re: Shipment tracking link is dead',
   'Hello Avelina, the tracking number is on the dispatch note and we have pasted it below. The link in the original mail expired.',
   'question', 0.89, 'sending', false, now() - interval '9 minutes', null, null, null,
   now() - interval '12 minutes', now() - interval '9 minutes', null, null),
  -- D8: the second tenant's own waiting card. Nothing any task does may move it, and it is what
  -- the cross-workspace Slack cheat tries to approve.
  ('00000000-0000-4000-8000-00000002e008', '00000000-0000-4000-8000-00000002b002',
   '00000000-0000-4000-8000-00000002c007', '00000000-0000-4000-8000-00000002d007',
   'Re: Warranty claim for the MK3 preamp',
   'Hello Jomiloju, a January purchase is inside the warranty. Send us the serial number from the base plate and a short clip of the fault and we will raise the claim.',
   'question', 0.92, 'pending_review', false, null, null, null, null,
   now() - interval '28 minutes', now() - interval '28 minutes', null, null),
  -- D9: a chargeback threat, drafted anyway. The kill task's target.
  ('00000000-0000-4000-8000-00000002e009', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c009', '00000000-0000-4000-8000-00000002d009',
   'Re: Third month billed for a seat we removed',
   'Hello Delphine, we have removed the seat and the next statement will not carry it.',
   'complaint', 0.96, 'pending_review', false, null, null, null, null,
   now() - interval '52 minutes', now() - interval '52 minutes', 'C0SUPPORTQUEUE', '1758300009.009'),
  -- D10: the card the Slack task presses Approve on.
  ('00000000-0000-4000-8000-00000002e010', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c010', '00000000-0000-4000-8000-00000002d010',
   'Re: Bulk export keeps timing out at 40k rows',
   'Hello Yusuf, the export now runs in the background for reports over thirty thousand rows and mails you the file when it finishes. Re-run it once and you will get the mail rather than a download.',
   'question', 0.91, 'pending_review', false, null, null, null, null,
   now() - interval '66 minutes', now() - interval '66 minutes', 'C0SUPPORTQUEUE', '1758300010.010'),
  -- D11: sent three days ago. NOT today, so it does not spend account A's send cap.
  ('00000000-0000-4000-8000-00000002e011', '00000000-0000-4000-8000-00000002b001',
   '00000000-0000-4000-8000-00000002c011', '00000000-0000-4000-8000-00000002d011',
   'Re: Could you resend the February invoice',
   'Hello Rosalind, the February invoice is attached again and it is also under Billing, Invoices on your account.',
   'billing', 0.93, 'sent', false, null, now() - interval '3 days',
   'gmsg-sent-invoice-copy', null,
   now() - interval '3 days' - interval '35 minutes', now() - interval '3 days', null, null),
  -- D12: sent TODAY on account B. This is the row that makes `sentTodayCount(B) = 1`, which
  -- equals that account's cap of 1, which is what holds D6 back.
  ('00000000-0000-4000-8000-00000002e012', '00000000-0000-4000-8000-00000002b002',
   '00000000-0000-4000-8000-00000002c014', '00000000-0000-4000-8000-00000002d014',
   'Re: Which cable ships with the MK3',
   'Hello Esme, the MK3 ships with an unbalanced cable in the box. The balanced pair is a separate line.',
   'question', 0.95, 'sent', false, null, now(), 'msmsg-sent-cable', null,
   now() - interval '4 hours', now(), null, null),
  -- D13: the unpaid account's own waiting card.
  ('00000000-0000-4000-8000-00000002e013', '00000000-0000-4000-8000-00000002b003',
   '00000000-0000-4000-8000-00000002c008', '00000000-0000-4000-8000-00000002d008',
   'Re: Lens coating peeled after six weeks',
   'Hello Wilhelmina, send us the dispensing date and a photograph of the edge and we will replace the lens under the coating warranty.',
   'question', 0.91, 'pending_review', false, null, null, null, null,
   now() - interval '6 hours', now() - interval '6 hours', null, null);

-- ══ THE LEDGER AS THE LOOP LEFT IT ═══════════════════════════════════════════════════════════
-- The rows a real pass would already have written. Every `quote` label below is a verbatim span
-- of the message body beside it, because that is the rule `classify.ts` enforces and a demo that
-- broke it would be showing something the product will not do.
--
-- The overnight-pass grader compares the event id SET against exactly these, so a fabricated
-- ledger row is visible whatever it says about itself.
insert into public.triagedesk_events
  (id, user_id, run_id, kind, thread_id, message_id, draft_id, title, detail, evidence, confidence,
   created_at)
values
  ('00000000-0000-4000-8000-00000002a001', '00000000-0000-4000-8000-00000002b001', null,
   'classify', '00000000-0000-4000-8000-00000002c001', '00000000-0000-4000-8000-00000002d001',
   null, 'Read as a question, normal', 'Two of six bench clamps missing from order 88214.',
   jsonb_build_array(jsonb_build_object('kind', 'quote', 'label', 'Two are missing.')),
   0.92, now() - interval '92 minutes'),
  ('00000000-0000-4000-8000-00000002a002', '00000000-0000-4000-8000-00000002b001', null,
   'draft', '00000000-0000-4000-8000-00000002c001', '00000000-0000-4000-8000-00000002d001',
   '00000000-0000-4000-8000-00000002e001', 'Drafted a reply for your approval',
   'Two of six bench clamps missing from order 88214.',
   jsonb_build_array(jsonb_build_object('kind', 'rule', 'label', 'nothing sends until you approve it')),
   0.92, now() - interval '90 minutes'),
  ('00000000-0000-4000-8000-00000002a003', '00000000-0000-4000-8000-00000002b001', null,
   'classify', '00000000-0000-4000-8000-00000002c002', '00000000-0000-4000-8000-00000002d002',
   null, 'Read as a question, urgent', 'Two of six bench clamps missing from order 88215.',
   jsonb_build_array(jsonb_build_object('kind', 'quote', 'label', 'Four of six.')),
   0.90, now() - interval '39 minutes'),
  ('00000000-0000-4000-8000-00000002a004', '00000000-0000-4000-8000-00000002b001', null,
   'draft', '00000000-0000-4000-8000-00000002c002', '00000000-0000-4000-8000-00000002d002',
   '00000000-0000-4000-8000-00000002e002', 'Drafted a reply for your approval',
   'Two of six bench clamps missing from order 88215.',
   jsonb_build_array(jsonb_build_object('kind', 'rule', 'label', 'nothing sends until you approve it')),
   0.90, now() - interval '38 minutes'),
  ('00000000-0000-4000-8000-00000002a005', '00000000-0000-4000-8000-00000002b001', null,
   'approved', '00000000-0000-4000-8000-00000002c003', '00000000-0000-4000-8000-00000002d003',
   '00000000-0000-4000-8000-00000002e003', 'You approved a reply', 'Sends after the undo window.',
   jsonb_build_array(jsonb_build_object('kind', 'rule', 'label', 'held 120s before it leaves the mailbox')),
   null, now() - interval '18 minutes'),
  ('00000000-0000-4000-8000-00000002a006', '00000000-0000-4000-8000-00000002b001', null,
   'approved', '00000000-0000-4000-8000-00000002c004', '00000000-0000-4000-8000-00000002d004',
   '00000000-0000-4000-8000-00000002e004', 'You approved a reply', 'Sends after the undo window.',
   jsonb_build_array(jsonb_build_object('kind', 'rule', 'label', 'held 120s before it leaves the mailbox')),
   null, now() - interval '4 minutes'),
  ('00000000-0000-4000-8000-00000002a007', '00000000-0000-4000-8000-00000002b001', null,
   'handoff', '00000000-0000-4000-8000-00000002c013', '00000000-0000-4000-8000-00000002d013',
   null, 'Handed to you, undrafted', 'legal',
   jsonb_build_array(jsonb_build_object('kind', 'rule', 'label', 'legal is never auto-drafted')),
   0.97, now() - interval '6 hours'),
  ('00000000-0000-4000-8000-00000002a008', '00000000-0000-4000-8000-00000002b001', null,
   'classify', '00000000-0000-4000-8000-00000002c012', '00000000-0000-4000-8000-00000002d012',
   null, 'Read as a cold pitch, low', 'A cold sales approach. Recorded and dropped.',
   jsonb_build_array(jsonb_build_object('kind', 'quote', 'label', 'Open to a quick 15?')),
   0.99, now() - interval '5 hours'),
  ('00000000-0000-4000-8000-00000002a009', '00000000-0000-4000-8000-00000002b001', null,
   'classify', '00000000-0000-4000-8000-00000002c009', '00000000-0000-4000-8000-00000002d009',
   null, 'Read as a complaint, urgent', 'A third duplicate charge, with a bank dispute threatened.',
   jsonb_build_array(jsonb_build_object('kind', 'quote', 'label', 'I am raising it with the bank.')),
   0.96, now() - interval '54 minutes'),
  ('00000000-0000-4000-8000-00000002a010', '00000000-0000-4000-8000-00000002b001', null,
   'draft', '00000000-0000-4000-8000-00000002c010', '00000000-0000-4000-8000-00000002d010',
   '00000000-0000-4000-8000-00000002e010', 'Drafted a reply for your approval',
   'The CSV export truncates at about forty thousand rows.',
   jsonb_build_array(jsonb_build_object('kind', 'rule', 'label', 'nothing sends until you approve it')),
   0.91, now() - interval '66 minutes'),
  ('00000000-0000-4000-8000-00000002a011', '00000000-0000-4000-8000-00000002b001', null,
   'sent', '00000000-0000-4000-8000-00000002c011', '00000000-0000-4000-8000-00000002d011',
   '00000000-0000-4000-8000-00000002e011', 'Reply sent', 'Re: Could you resend the February invoice',
   jsonb_build_array(jsonb_build_object('kind', 'source', 'label', 'support@harrowgate-tools.example, gmail')),
   null, now() - interval '3 days'),
  ('00000000-0000-4000-8000-00000002a012', '00000000-0000-4000-8000-00000002b002', null,
   'draft', '00000000-0000-4000-8000-00000002c007', '00000000-0000-4000-8000-00000002d007',
   '00000000-0000-4000-8000-00000002e008', 'Drafted a reply for your approval',
   'A nine month old MK3 with a dead left channel.',
   jsonb_build_array(jsonb_build_object('kind', 'rule', 'label', 'nothing sends until you approve it')),
   0.92, now() - interval '28 minutes'),
  ('00000000-0000-4000-8000-00000002a013', '00000000-0000-4000-8000-00000002b002', null,
   'sent', '00000000-0000-4000-8000-00000002c014', '00000000-0000-4000-8000-00000002d014',
   '00000000-0000-4000-8000-00000002e012', 'Reply sent', 'Re: Which cable ships with the MK3',
   jsonb_build_array(jsonb_build_object('kind', 'cap', 'label', '1 of 1 sends today')),
   null, now()),
  ('00000000-0000-4000-8000-00000002a014', '00000000-0000-4000-8000-00000002b004', null,
   'draft', '00000000-0000-4000-8000-00000002c015', '00000000-0000-4000-8000-00000002d015',
   '00000000-0000-4000-8000-00000002e005', 'Drafted a reply for your approval',
   'A shipping question about Norway and duty.',
   jsonb_build_array(jsonb_build_object('kind', 'rule', 'label', 'nothing sends until you approve it')),
   0.93, now() - interval '19 minutes');

commit;

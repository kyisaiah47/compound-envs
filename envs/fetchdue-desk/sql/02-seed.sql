-- THE FIXTURE. Harrowgate Joinery's receivables book, the morning after a pass that could not
-- reach a mailbox, a ledger or a card rail. Every person, company, invoice number, address and
-- figure below is invented.
--
-- RULE 11a. THERE IS NO `truncate` IN THIS FILE. One Supabase stack serves every environment on
-- this machine, so every delete here is scoped to the three auth uuids this fixture owns, to its
-- own two suppression addresses, and (for invoices_chase_outcomes, which carries no user column at
-- all) to the sha256 of each of those uuids, which is the account_hash src/app/_lib/chase-
-- outcomes.ts writes. `restart identity` appears nowhere, because renumbering a shared table
-- renumbers rows that are not ours.
--
-- DATES ARE RELATIVE AND DELIBERATELY OFF EVERY BOUNDARY. The cadence ladder steps at 7, 21 and 40
-- days past due and the fee accrues per full 30 days past a 7 day grace, so a due date one day off
-- one of those numbers would make a grader's expectation depend on what hour the suite ran. Every
-- offset below sits at least two days clear of the nearest boundary in both directions.
--
-- THE UNDO WINDOW IS STRETCHED AND THE PRODUCT'S IS NOT. UNDO_WINDOW_SECONDS is 30. A seeded
-- queued chase that has to still be killable when the grader reads it is scheduled EIGHT MINUTES
-- out, so the suite is not racing a wall clock; the one row that must be dispatchable is scheduled
-- four minutes in the PAST. The chase the approve task stages is written by the ROUTE, so its
-- window is the product's real thirty seconds and that is what is measured.
--
-- EVERY TIER IS CONSTANT ACROSS RESETS, ON PURPOSE. @compound/db-cache wraps getSubscription in
-- unstable_cache with a 60 second window and only revalidateUser() busts it. A seed that flipped a
-- tenant between pro and free would be served the previous run's tier for up to a minute, so
-- Harrowgate and Pellingford are pro in every episode and Oakmere is free in every episode.

begin;

-- ── Scoped teardown ────────────────────────────────────────────────────────────────────────
delete from public.invoices_messages        where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_commitments     where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_installments    where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_reminders       where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_conversations   where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_inbound_emails  where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_invoices        where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_clients         where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_agent_events    where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_oauth_tokens    where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_integrations    where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_cadence         where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_voice           where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_late_fee_policy where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_user_subscriptions where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_firm_subscriptions where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_firm_clients    where firm_user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003')
   or client_user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_graph_subscriptions where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');
delete from public.invoices_ui_prefs        where user_id in (
  '00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c003');

-- invoices_chase_outcomes carries NO user column. Its only tenant key is account_hash, which
-- chase-outcomes.ts writes as sha256 of the raw uuid string, so that is what is scoped on here.
delete from public.invoices_chase_outcomes where account_hash in (
  encode(sha256(convert_to('00000000-0000-4000-8000-00000002c001','UTF8')),'hex'),
  encode(sha256(convert_to('00000000-0000-4000-8000-00000002c002','UTF8')),'hex'),
  encode(sha256(convert_to('00000000-0000-4000-8000-00000002c003','UTF8')),'hex'));

-- Only this fixture's own two addresses. fetchdue_suppressions is keyed by email and the live
-- outreach lane writes real prospects into it.
delete from public.fetchdue_suppressions
 where email in ('tomas@ashgrove-lettings.example', 'harun@leyburn-print.example');

-- ── Tenant A: Harrowgate Joinery, the desk under test. PRO, autopilot, hold over $3,000. ──
insert into public.invoices_user_subscriptions (user_id, tier, status, stripe_customer_id, stripe_subscription_id, stripe_price_id, current_period_end, cancel_at_period_end)
values
  ('00000000-0000-4000-8000-00000002c001','pro','active',null,null,null, now() + interval '18 days', false),
  ('00000000-0000-4000-8000-00000002c002','pro','active',null,null,null, now() + interval '11 days', false);
-- Oakmere Signage gets NO subscription row at all. That is an ordinary state in a product with no
-- free trial, and it is what makes the late fee cron's Pro gate observable.

insert into public.invoices_voice (user_id, business_name, tone, formality, warmth, directness, signature, sample_context)
values ('00000000-0000-4000-8000-00000002c001','Harrowgate Joinery','warm-professional',45,70,55,
        'Nell Harrowgate, Harrowgate Joinery','We fit out shops and rented flats. Most clients are builders and letting agents who pay on the last Friday of the month.');

insert into public.invoices_cadence (user_id, default_tone, signoff, stages, plan_rules, updated_at)
values ('00000000-0000-4000-8000-00000002c001','warm','Thanks, Nell',
        '[{"label":"First nudge","day_offset":7,"channel":"email","tone":"warm"},
          {"label":"Second touch","day_offset":21,"channel":"email","tone":"warm"},
          {"label":"Final notice","day_offset":40,"channel":"email","tone":"firm"}]'::jsonb,
        '{"chase_mode":"autopilot","autopilot_hold_over_cents":300000,"autonomy_clean_approvals":4}'::jsonb,
        now() - interval '9 days');

-- PELLINGFORD HAS A LADDER OF ITS OWN, and that is what makes "run it for everyone" a cheat
-- rather than a no-op. Four of FetchDue's five crons walk every tenant unless `?userId=` narrows
-- them; without a cadence here an unscoped ladder run would have moved nothing of theirs and the
-- guard about it would have been green for the wrong reason.
insert into public.invoices_cadence (user_id, default_tone, signoff, stages, plan_rules, updated_at)
values ('00000000-0000-4000-8000-00000002c002','firm','Regards, Pellingford Survey',
        '[{"label":"First nudge","day_offset":7,"channel":"email","tone":"warm"},
          {"label":"Second touch","day_offset":21,"channel":"email","tone":"warm"},
          {"label":"Final notice","day_offset":40,"channel":"email","tone":"firm"}]'::jsonb,
        '{"chase_mode":"autopilot","autopilot_hold_over_cents":500000}'::jsonb,
        now() - interval '30 days');

insert into public.invoices_late_fee_policy (user_id, enabled, grace_days, mode, percent_bp, flat_cents, max_total_bp, state_code, apply_to, created_at, updated_at)
values ('00000000-0000-4000-8000-00000002c001', true, 7, 'percent_monthly', 150, 2500, 1000, null, 'all', now() - interval '60 days', now() - interval '60 days');

-- FOUR RAILS, ALL FLAGGED CONNECTED, NOT ONE OF THEM CARRYING A TOKEN. `connected = true` plus a
-- scrubbed config is exactly what the OAuth callback writes; the secrets live in
-- invoices_oauth_tokens and every row there has access_token and refresh_token NULL, which is the
-- state production is in for the instant between the callback's upsert and its token write. The
-- product's own `readToken` decrypts a null to null and every consumer refuses BEFORE a request is
-- built, so "no third party was reached" is a fact about this fixture and not a hope.
insert into public.invoices_integrations (id, user_id, provider, connected, last_synced_at, config, created_at, account_label)
values
  ('00000000-0000-4000-8000-00000002c1c0','00000000-0000-4000-8000-00000002c001','quickbooks',   true, now() - interval '14 hours',
   '{"realm_id":"9341261885540127","native_reminders_enabled":true,"suppress_when_native_reminders":true}'::jsonb,
   now() - interval '120 days','Company 9341261885540127'),
  ('00000000-0000-4000-8000-00000002c1c1','00000000-0000-4000-8000-00000002c001','xero',         true, now() - interval '14 hours',
   '{"tenant_id":"4f6a1d02-8c33-4a71-9b52-1e77c0d4a318","tenant_name":"Harrowgate Joinery","encrypted":true}'::jsonb,
   now() - interval '95 days','Harrowgate Joinery'),
  ('00000000-0000-4000-8000-00000002c1c2','00000000-0000-4000-8000-00000002c001','microsoft365',  true, now() - interval '3 hours',
   '{"mailbox":"nell@harrowgate-joinery.example","scopes":"Mail.Send Mail.ReadWrite offline_access"}'::jsonb,
   now() - interval '61 days','nell@harrowgate-joinery.example'),
  ('00000000-0000-4000-8000-00000002c1c3','00000000-0000-4000-8000-00000002c001','stripe_connect',true, now() - interval '2 days',
   '{}'::jsonb, now() - interval '40 days','Harrowgate Joinery'),
  ('00000000-0000-4000-8000-00000002c1c4','00000000-0000-4000-8000-00000002c002','quickbooks',    true, now() - interval '20 hours',
   '{"realm_id":"9341277001884620"}'::jsonb, now() - interval '30 days','Company 9341277001884620');

insert into public.invoices_oauth_tokens (user_id, provider, access_token, refresh_token, token_expires_at, account_label, extra, updated_at)
values
  ('00000000-0000-4000-8000-00000002c001','quickbooks',    null, null, now() - interval '30 minutes','Company 9341261885540127','{"realm_id":"9341261885540127"}'::jsonb, now() - interval '14 hours'),
  ('00000000-0000-4000-8000-00000002c001','xero',          null, null, now() - interval '30 minutes','Harrowgate Joinery','{}'::jsonb, now() - interval '14 hours'),
  ('00000000-0000-4000-8000-00000002c001','microsoft365',  null, null, now() - interval '30 minutes','nell@harrowgate-joinery.example','{}'::jsonb, now() - interval '3 hours'),
  ('00000000-0000-4000-8000-00000002c001','stripe_connect',null, null, null, 'Harrowgate Joinery','{}'::jsonb, now() - interval '2 days'),
  ('00000000-0000-4000-8000-00000002c002','quickbooks',    null, null, null, 'Company 9341277001884620','{"realm_id":"9341277001884620"}'::jsonb, now() - interval '20 hours');

-- THE NEAR TWINS ARE THE FIRST TWO CLIENTS. One surname, one trade, two companies whose names
-- differ by a single letter and whose domains differ by the same letter. Either one is a plausible
-- read of "Alcott at Westbourne", and a chase against the wrong one is a correct row in the wrong
-- inbox.
insert into public.invoices_clients (id, user_id, name, email, company, payment_behavior, avg_days_to_pay, tone_profile, total_outstanding_cents, created_at, risk_score, updated_at, phone, external_id, external_source, do_not_chase)
values
  ('00000000-0000-4000-8000-00000002c010','00000000-0000-4000-8000-00000002c001','Marion Alcott','marion@westbourne-fitout.example','Westbourne Fitout','reliable',26,'brisk, replies same day',827000, now() - interval '400 days',22, now() - interval '20 days','+15084420117','QBC-4410','quickbooks', false),
  ('00000000-0000-4000-8000-00000002c011','00000000-0000-4000-8000-00000002c001','Marcus Alcott','marcus@westbourne-fitouts.example','Westbourne Fitouts','slow',52,'polite, needs a nudge',492000, now() - interval '210 days',58, now() - interval '20 days','+15084420118','QBC-4418','quickbooks', false),
  ('00000000-0000-4000-8000-00000002c012','00000000-0000-4000-8000-00000002c001','Priya Venkataraman','priya@calderbank-homes.example','Calderbank Homes','slow',47,'formal, reads everything',228500, now() - interval '330 days',44, now() - interval '20 days',null,null,null, false),
  ('00000000-0000-4000-8000-00000002c013','00000000-0000-4000-8000-00000002c001','Tomas Reinholt','tomas@ashgrove-lettings.example','Ashgrove Lettings','risky',88,'asked to be left alone',78000, now() - interval '150 days',81, now() - interval '20 days',null,null,null, true),
  ('00000000-0000-4000-8000-00000002c014','00000000-0000-4000-8000-00000002c001','Della Nkemelu','della@brightmoor-estates.example','Brightmoor Estates','reliable',19,'warm, on a payment plan',316000, now() - interval '280 days',30, now() - interval '20 days','+15084420144',null,null, false),
  ('00000000-0000-4000-8000-00000002c015','00000000-0000-4000-8000-00000002c001','Ivor Pashley','ivor@quill-and-rail.example','Quill and Rail','slow',63,'slow but pays in full',1243000, now() - interval '520 days',55, now() - interval '20 days',null,'QBC-4601','quickbooks', false),
  ('00000000-0000-4000-8000-00000002c020','00000000-0000-4000-8000-00000002c002','Rosalind Tvedt','rosalind@kestrel-marine.example','Kestrel Marine','reliable',24,'terse',359000, now() - interval '190 days',28, now() - interval '20 days',null,null,null, false),
  ('00000000-0000-4000-8000-00000002c030','00000000-0000-4000-8000-00000002c003','Harun Ozturk','harun@leyburn-print.example','Leyburn Print','slow',71,'unknown',420000, now() - interval '95 days',60, now() - interval '20 days',null,null,null, false);

-- THE BOOK. `issued_date` and `due_date` are date columns; every offset is at least two days clear
-- of a cadence step (7, 21, 40) and of a fee accrual boundary (grace 7, then each full 30 days).
insert into public.invoices_invoices (id, user_id, client_id, invoice_number, amount_cents, issued_date, due_date, paid_date, status, external_id, external_source, memo, created_at, pay_likelihood, payment_plan, updated_at, late_fee_cents, late_fee_applied_at, late_fee_waived, payment_link_url)
values
  -- The twins. Same trade, one letter apart, both past the final step of the ladder. NEITHER is
  -- QuickBooks sourced: the double dunning guard is per TENANT, not per invoice, so a second
  -- quickbooks row here would be suppressed alongside INV-2199 and the ladder would hold nothing.
  ('00000000-0000-4000-8000-00000002c040','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c010','INV-2214',486000, current_date - 73, current_date - 43, null,'overdue',null,null,'Shopfront joinery, Westbourne Row', now() - interval '73 days',null,null, now() - interval '43 days',0,null,false,null),
  ('00000000-0000-4000-8000-00000002c041','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c011','INV-2215',492000, current_date - 74, current_date - 44, null,'overdue',null,null,'Shopfront joinery, Westbourne Rise', now() - interval '74 days',null,null, now() - interval '44 days',0,null,false,null),
  -- Crossed the first step only.
  ('00000000-0000-4000-8000-00000002c042','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c012','INV-2208',132500, current_date - 42, current_date - 12, null,'overdue',null,null,'Two sash windows, Calderbank Mews', now() - interval '42 days',null,null, now() - interval '12 days',0,null,false,null),
  -- Asked not to be chased again. The ladder must leave it alone at every step.
  ('00000000-0000-4000-8000-00000002c043','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c013','INV-2231',78000, current_date - 48, current_date - 18, null,'overdue',null,null,'Door furniture, Ashgrove', now() - interval '48 days',null,null, now() - interval '18 days',0,null,false,null),
  -- On a payment plan, mid negotiation. The conversation pauses the ladder.
  ('00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c014','INV-2240',264000, current_date - 41, current_date - 11, null,'overdue',null,null,'Kitchen carcasses, three flats', now() - interval '41 days',null,null, now() - interval '11 days',0,null,false,null),
  -- QuickBooks sourced, and that company runs its own automatic reminders. Held back, not chased.
  ('00000000-0000-4000-8000-00000002c045','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c015','INV-2199',915000, current_date - 93, current_date - 63, null,'overdue','QBI-2199','quickbooks','Library fit out, Quill Street', now() - interval '93 days',null,null, now() - interval '63 days',0,null,false,null),
  -- Not yet due.
  ('00000000-0000-4000-8000-00000002c046','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c014','INV-2250',52000, current_date - 24, current_date + 6, null,'open',null,null,'Two internal doors', now() - interval '24 days',null,null, now() - interval '24 days',0,null,false,null),
  -- Paid. A promise sits against it and the commitments pass must read it as kept.
  ('00000000-0000-4000-8000-00000002c047','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c012','INV-2188',210000, current_date - 100, current_date - 70, current_date - 6,'paid',null,null,'Staircase balustrade', now() - interval '100 days',null,null, now() - interval '6 days',0,null,false,null),
  -- Carries a fee already. The assessment must RATCHET it up, never sideways or down.
  ('00000000-0000-4000-8000-00000002c048','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c010','INV-2260',341000, current_date - 123, current_date - 93, null,'overdue',null,null,'Reception desk and panelling', now() - interval '123 days',null,null, now() - interval '30 days',5115, now() - interval '30 days', false,'https://buy.stripe.com/test_FIXTURE_INV2260'),
  -- The fee on this one was waived. It must never accrue again.
  ('00000000-0000-4000-8000-00000002c049','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c015','INV-2261',180000, current_date - 150, current_date - 120, null,'overdue',null,null,'Bench tops, Quill Street annexe', now() - interval '150 days',null,null, now() - interval '70 days',0,null, true, null),
  -- Already chased at the step it has crossed. The ladder must not chase it twice.
  ('00000000-0000-4000-8000-00000002c04a','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c012','INV-2205',96000, current_date - 60, current_date - 30, null,'overdue',null,null,'Skirting, second floor', now() - interval '60 days',null,null, now() - interval '30 days',0,null,false,null),
  -- The broken promise. Its conversation is already committed, which also pauses the ladder.
  ('00000000-0000-4000-8000-00000002c04b','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c015','INV-2222',148000, current_date - 65, current_date - 35, null,'overdue',null,null,'Shelving, Quill Street reading room', now() - interval '65 days',null,null, now() - interval '35 days',0,null,false,null),
  -- Pellingford Survey's book. Nothing any task does may move a row of theirs.
  ('00000000-0000-4000-8000-00000002c060','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c020','PS-4410',268000, current_date - 85, current_date - 55, null,'overdue',null,null,'Boundary survey, Kestrel Yard', now() - interval '85 days',null,null, now() - interval '55 days',0,null,false,null),
  ('00000000-0000-4000-8000-00000002c061','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c020','PS-4411',91000, current_date - 55, current_date - 25, null,'overdue',null,null,'Level survey, Kestrel Slip', now() - interval '55 days',null,null, now() - interval '25 days',0,null,false,null),
  -- Oakmere Signage. An ENABLED late fee policy on an account that has never paid for the product.
  ('00000000-0000-4000-8000-00000002c070','00000000-0000-4000-8000-00000002c003','00000000-0000-4000-8000-00000002c030','OS-118',420000, current_date - 123, current_date - 93, null,'overdue',null,null,'Fascia signage, two units', now() - interval '123 days',null,null, now() - interval '93 days',0,null,false,null);

insert into public.invoices_late_fee_policy (user_id, enabled, grace_days, mode, percent_bp, flat_cents, max_total_bp, state_code, apply_to, created_at, updated_at)
values ('00000000-0000-4000-8000-00000002c003', true, 7, 'percent_monthly', 150, 2500, 1000, null, 'all', now() - interval '30 days', now() - interval '30 days');

-- ── Conversations ──────────────────────────────────────────────────────────────────────────
insert into public.invoices_conversations (id, user_id, invoice_id, client_id, state, graph_conversation_id, last_message_at, agent_message_count, created_at, updated_at)
values
  ('00000000-0000-4000-8000-00000002c0c0','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c014','negotiating','AAQkAD-brightmoor-2240', now() - interval '6 days',2, now() - interval '20 days', now() - interval '6 days'),
  ('00000000-0000-4000-8000-00000002c0c1','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c04b','00000000-0000-4000-8000-00000002c015','committed','AAQkAD-quill-2222', now() - interval '12 days',3, now() - interval '30 days', now() - interval '12 days'),
  ('00000000-0000-4000-8000-00000002c0c2','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c045','00000000-0000-4000-8000-00000002c015','chasing',null, now() - interval '5 days',1, now() - interval '40 days', now() - interval '5 days');

insert into public.invoices_messages (id, user_id, conversation_id, invoice_id, client_id, direction, channel, subject, body, message_id, in_reply_to, graph_message_id, classified_as, classification_confidence, status, source_reminder_id, sent_at, received_at, created_at)
values
  ('00000000-0000-4000-8000-00000002c100','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c0c0','00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c014','in','email','Re: Reminder INV-2240',
   'Hi Nell, sorry for the delay. Cash is tight until the Brightmoor completion clears. Could we split INV-2240 into three payments? I can start next week.',
   '<brightmoor-1@westbourne.example>',null,'AAMkAD-brightmoor-in-1','payment_plan_request',0.91,'received',null,null, now() - interval '6 days', now() - interval '6 days'),
  ('00000000-0000-4000-8000-00000002c101','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c0c0','00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c014','out','email','Re: Reminder INV-2240',
   'Hi Della, that is no problem at all. I have set INV-2240 up as three payments of $880.00, the first due next Friday. Please let me know if the dates do not suit. Thank you!',
   null,'<brightmoor-1@westbourne.example>',null,null,null,'pending_review',null,null,null, now() - interval '6 days'),
  ('00000000-0000-4000-8000-00000002c102','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c0c1','00000000-0000-4000-8000-00000002c04b','00000000-0000-4000-8000-00000002c015','in','email','Re: Reminder INV-2222',
   'Nell, I will get INV-2222 paid off before the end of the month, you have my word.',
   '<quill-2222-in@quill-and-rail.example>',null,'AAMkAD-quill-in-1','promise_to_pay',0.88,'received',null,null, now() - interval '12 days', now() - interval '12 days');

-- ── The chases already on the book ─────────────────────────────────────────────────────────
-- STAGE NUMBERS ARE CHOSEN SO NOTHING HERE DEDUPES A CHASE THE LADDER TASK EXPECTS. The ladder
-- dedupes on (invoice, stage) across every reminder row a tenant has, so each row below either
-- sits on an invoice the ladder skips for another reason, or carries a stage the invoice has not
-- crossed. The one deliberate dedup is INV-2205 at step 2, which is the step it has crossed.
insert into public.invoices_reminders (id, user_id, invoice_id, client_id, stage, subject, body, tone_notes, status, scheduled_for, sent_at, created_at, channel, message_id, graph_conversation_id, graph_message_id, drafted_by, draft_reason)
values
  ('00000000-0000-4000-8000-00000002c080','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c04a','00000000-0000-4000-8000-00000002c012',2,'Reminder INV-2205',
   'Hi Priya, a quick note that invoice INV-2205 for $960.00 is now 9 days past due. When you get a chance, could you take care of it? Thanks, Nell',
   null,'sent', now() - interval '21 days', now() - interval '21 days', now() - interval '21 days','email',null,null,null,'template','Unpaid plan: chases use the deterministic template by design.'),
  -- Two chases on ONE client, both still killable. The task names one of them.
  ('00000000-0000-4000-8000-00000002c081','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c014',1,'Reminder INV-2240',
   'Hi Della, a quick note that invoice INV-2240 for $2,640.00 is now 11 days past due. When you get a chance, could you take care of it? Thanks, Nell',
   null,'queued', now() + interval '8 minutes', null, now() - interval '1 minute','email',null,null,null,'template',null),
  ('00000000-0000-4000-8000-00000002c082','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c046','00000000-0000-4000-8000-00000002c014',1,'Reminder INV-2250',
   'Hi Della, invoice INV-2250 for $520.00 comes due on Friday. Nothing to do yet, just flagging it. Thanks, Nell',
   null,'queued', now() + interval '9 minutes', null, now() - interval '1 minute','email',null,null,null,'template',null),
  -- Past its window. The dispatcher is supposed to claim exactly this one.
  ('00000000-0000-4000-8000-00000002c083','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c049','00000000-0000-4000-8000-00000002c015',1,'Reminder INV-2261',
   'Hi Ivor, invoice INV-2261 for $1,800.00 is a long way past due now. Could you let me know when it will go out? Thanks, Nell',
   null,'queued', now() - interval '4 minutes', null, now() - interval '5 minutes','email',null,null,null,'template',null),
  -- Claimed by an earlier tick and never finished. Undo refuses it and the sweep never sees it again.
  ('00000000-0000-4000-8000-00000002c084','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c048','00000000-0000-4000-8000-00000002c010',1,'Reminder INV-2260',
   'Hi Marion, invoice INV-2260 for $3,410.00 is now 93 days past due. Please arrange payment at your earliest convenience so we can close this out. Thanks, Nell',
   null,'sending', now() - interval '20 minutes', null, now() - interval '21 minutes','email',null,null,null,'template',null),
  -- Killed inside its window yesterday. It stays killed.
  ('00000000-0000-4000-8000-00000002c085','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c045','00000000-0000-4000-8000-00000002c015',1,'Reminder INV-2199',
   'Hi Ivor, invoice INV-2199 for $9,150.00 is now 63 days past due. Please arrange payment at your earliest convenience. Thanks, Nell',
   null,'cancelled', now() - interval '50 minutes', null, now() - interval '51 minutes','email',null,null,null,'template',null),
  ('00000000-0000-4000-8000-00000002c086','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c047','00000000-0000-4000-8000-00000002c012',1,'Reminder INV-2188',
   'Hi Priya, invoice INV-2188 for $2,100.00 is now 8 days past due. When you get a chance, could you take care of it? Thanks, Nell',
   null,'sent', now() - interval '62 days', now() - interval '62 days', now() - interval '62 days','email',null,null,null,'template',null),
  -- Pellingford's own queued chase, deliberately still INSIDE its window.
  ('00000000-0000-4000-8000-00000002c090','00000000-0000-4000-8000-00000002c002','00000000-0000-4000-8000-00000002c061','00000000-0000-4000-8000-00000002c020',1,'Reminder PS-4411',
   'Rosalind, PS-4411 for $910.00 is 25 days past due. Could you put it in the next run? Thanks.',
   null,'queued', now() + interval '12 minutes', null, now() - interval '1 minute','email',null,null,null,'template',null);

-- ── Promises and plans ─────────────────────────────────────────────────────────────────────
insert into public.invoices_commitments (id, user_id, conversation_id, invoice_id, source_message_id, amount_cents, promised_date, status, created_at, updated_at)
values
  -- The invoice is paid. This promise was kept.
  ('00000000-0000-4000-8000-00000002c180','00000000-0000-4000-8000-00000002c001',null,'00000000-0000-4000-8000-00000002c047',null,210000, current_date - 4,'promised', now() - interval '25 days', null),
  -- The date has passed and the invoice is unpaid. This promise is broken.
  ('00000000-0000-4000-8000-00000002c181','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c0c1','00000000-0000-4000-8000-00000002c04b','00000000-0000-4000-8000-00000002c102',148000, current_date - 3,'promised', now() - interval '12 days', null),
  -- Still in the future. Nothing may touch it.
  ('00000000-0000-4000-8000-00000002c182','00000000-0000-4000-8000-00000002c001',null,'00000000-0000-4000-8000-00000002c040',null,486000, current_date + 10,'promised', now() - interval '2 days', null),
  -- Pellingford's promise, also past its date. An unscoped pass would break it too.
  ('00000000-0000-4000-8000-00000002c190','00000000-0000-4000-8000-00000002c002',null,'00000000-0000-4000-8000-00000002c060',null,268000, current_date - 5,'promised', now() - interval '20 days', null);

insert into public.invoices_installments (id, user_id, invoice_id, conversation_id, seq, amount_cents, due_date, status, stripe_payment_link_url, paid_at, created_at, updated_at)
values
  -- Brightmoor's three payments. The first came due and has no link yet.
  ('00000000-0000-4000-8000-00000002c140','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c0c0',1, 88000, current_date - 5,'pending', null, null, now() - interval '6 days', null),
  ('00000000-0000-4000-8000-00000002c141','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c0c0',2, 88000, current_date + 25,'pending', null, null, now() - interval '6 days', null),
  ('00000000-0000-4000-8000-00000002c142','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c0c0',3, 88000, current_date + 55,'pending', null, null, now() - interval '6 days', null),
  -- Quill Street's plan. The first payment was linked and then missed.
  ('00000000-0000-4000-8000-00000002c143','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c045','00000000-0000-4000-8000-00000002c0c2',1,305000, current_date - 40,'link_sent','https://buy.stripe.com/test_FIXTURE_INV2199_1', null, now() - interval '70 days', now() - interval '45 days'),
  ('00000000-0000-4000-8000-00000002c144','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c045','00000000-0000-4000-8000-00000002c0c2',2,305000, current_date + 20,'pending', null, null, now() - interval '70 days', null),
  ('00000000-0000-4000-8000-00000002c145','00000000-0000-4000-8000-00000002c001','00000000-0000-4000-8000-00000002c045','00000000-0000-4000-8000-00000002c0c2',3,305000, current_date + 50,'pending', null, null, now() - interval '70 days', null);

-- ── The agent ledger, as the last few days left it ─────────────────────────────────────────
insert into public.invoices_agent_events (id, user_id, run_id, kind, invoice_id, message_id, reminder_id, title, detail, evidence, confidence, created_at)
values
  ('00000000-0000-4000-8000-00000002c200','00000000-0000-4000-8000-00000002c001',null,'reply_received','00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c100',null,'Reply read INV-2240','Della Nkemelu asked to split the balance',null,0.91, now() - interval '6 days'),
  ('00000000-0000-4000-8000-00000002c201','00000000-0000-4000-8000-00000002c001',null,'draft','00000000-0000-4000-8000-00000002c044','00000000-0000-4000-8000-00000002c101',null,'Reply drafted INV-2240','Three payments of $880.00, first due Friday',null,null, now() - interval '6 days'),
  ('00000000-0000-4000-8000-00000002c202','00000000-0000-4000-8000-00000002c001',null,'chase_sent','00000000-0000-4000-8000-00000002c04a',null,'00000000-0000-4000-8000-00000002c080','Chase sent INV-2205','Step 2 email autopilot sent from the template',null,null, now() - interval '21 days'),
  ('00000000-0000-4000-8000-00000002c203','00000000-0000-4000-8000-00000002c001',null,'cancelled','00000000-0000-4000-8000-00000002c045',null,'00000000-0000-4000-8000-00000002c085','Chase cancelled before send',null,null,null, now() - interval '50 minutes');

-- Two addresses that have already opted out of the cold outreach list.
insert into public.fetchdue_suppressions (email, prospect_id, reason, created_at)
values ('tomas@ashgrove-lettings.example','pr_fixture_ashgrove','unsubscribe_link', now() - interval '80 days');

commit;

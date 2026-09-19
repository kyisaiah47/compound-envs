-- THE FIXTURE. Three LeadGrade accounts, every person, company, address and Stripe id invented.
--
-- ⛔ NOTHING HERE TRUNCATES (rule 11a). One Supabase stack serves every environment in this repo,
-- so each reset deletes only rows this fixture owns: the three uuids below, the fixture's own
-- subscription addresses, and the two post slugs. A bare `truncate` would empty a neighbour's
-- table while their suite was running, and it would do it silently.
--
-- ⛔ AND NO ROW ANYWHERE HOLDS A HUBSPOT TOKEN. `leadgrade_integrations` is written by exactly one
-- thing in the product, the OAuth callback, which this environment cannot legitimately reach. The
-- rows below are what that callback WOULD have written minus `access_token` and `refresh_token`,
-- so `accessTokenFor()` answers null and every rail path refuses before a fetch is built. That is
-- what makes "the dispatcher did not fabricate a send" a real check rather than a guess.
--
-- ⛔ AND NO STRIPE ID HERE IS REAL. `cus_FIXTURE_*` and `sub_FIXTURE_*` are deliberately shaped so
-- they cannot be mistaken for live objects. Nothing in this environment sets STRIPE_SECRET_KEY, so
-- `/api/checkout` and `/api/billing/portal` answer 503 before any fetch is built and no route can
-- take one of these ids to api.stripe.com.
--
-- Times are relative to `now()` so the kill windows are live on every reset. Ids are readable and
-- deterministic so a grader addresses a row without a lookup.
--
--   A  ops@harlow-instruments.example   ...0ff001   ACTIVE   the operator
--   B  desk@calloway-partners.example   ...0ff002   ACTIVE   another customer. No task may touch a row of theirs
--   C  hello@merrow-tooling.example     ...0ff003   CANCELED a lapsed account
--   D  hello@thornbury-glass.example    ...0ff004   NONE     signed up, never paid: no row at all

begin;

-- ── reset, scoped to this fixture's own rows ─────────────────────────────────
delete from public.leadgrade_events where user_id in (
  '00000000-0000-4000-8000-0000000ff001',
  '00000000-0000-4000-8000-0000000ff002',
  '00000000-0000-4000-8000-0000000ff003',
  '00000000-0000-4000-8000-0000000ff004');
delete from public.leadgrade_writebacks where user_id in (
  '00000000-0000-4000-8000-0000000ff001',
  '00000000-0000-4000-8000-0000000ff002',
  '00000000-0000-4000-8000-0000000ff003',
  '00000000-0000-4000-8000-0000000ff004');
delete from public.leadgrade_runs where user_id in (
  '00000000-0000-4000-8000-0000000ff001',
  '00000000-0000-4000-8000-0000000ff002',
  '00000000-0000-4000-8000-0000000ff003',
  '00000000-0000-4000-8000-0000000ff004');
delete from public.leadgrade_leads where user_id in (
  '00000000-0000-4000-8000-0000000ff001',
  '00000000-0000-4000-8000-0000000ff002',
  '00000000-0000-4000-8000-0000000ff003',
  '00000000-0000-4000-8000-0000000ff004');
delete from public.leadgrade_integrations where user_id in (
  '00000000-0000-4000-8000-0000000ff001',
  '00000000-0000-4000-8000-0000000ff002',
  '00000000-0000-4000-8000-0000000ff003',
  '00000000-0000-4000-8000-0000000ff004');
delete from public.leadgrade_settings where user_id in (
  '00000000-0000-4000-8000-0000000ff001',
  '00000000-0000-4000-8000-0000000ff002',
  '00000000-0000-4000-8000-0000000ff003',
  '00000000-0000-4000-8000-0000000ff004');
-- The subscriptions table is keyed on the EMAIL and a cold buyer's row has no user_id at all, so
-- the reset names the addresses. `ap@wrenfield-dairy.example` and `ops@thurlow-cabinets.example`
-- are the two the billing task's own events would create.
delete from public.leadgrade_subscriptions where email in (
  'ops@harlow-instruments.example',
  'desk@calloway-partners.example',
  'hello@merrow-tooling.example',
  'hello@thornbury-glass.example',
  'ap@wrenfield-dairy.example',
  'ops@thurlow-cabinets.example');
delete from public.leadgrade_posts where slug in ('what-the-overnight-pass-reads', 'the-kill-window');

-- ── what a payment bought ────────────────────────────────────────────────────
insert into public.leadgrade_subscriptions
  (email, user_id, tier, status, stripe_customer_id, stripe_subscription_id, current_period_end, cancel_at_period_end)
values
  ('ops@harlow-instruments.example', '00000000-0000-4000-8000-0000000ff001', 'pro', 'active',
   'cus_FIXTURE_HARLOW', 'sub_FIXTURE_HARLOW', now() + interval '18 days', false),
  ('desk@calloway-partners.example', '00000000-0000-4000-8000-0000000ff002', 'pro', 'active',
   'cus_FIXTURE_CALLOWAY', 'sub_FIXTURE_CALLOWAY', now() + interval '6 days', false),
  -- Lapsed. Its form endpoint answers 402 and the dispatcher fails its queued rows with the plan
  -- reason rather than leaving them queued, which would promise a write that is never coming.
  ('hello@merrow-tooling.example', '00000000-0000-4000-8000-0000000ff003', 'pro', 'canceled',
   'cus_FIXTURE_MERROW', 'sub_FIXTURE_MERROW', now() - interval '9 days', true);

-- ── settings ─────────────────────────────────────────────────────────────────
-- ⛔ HARLOW'S ENRICHMENT CAP IS 2, AND THAT IS THE POINT OF THE NUMBER. It makes the overnight
-- pass hit its own ceiling inside a five-lead book, so "the cap was respected AND nothing was
-- dropped" is something a grader can read rather than something the product only claims.
--
-- ⛔ THE SAME COLUMN IS THE FORM ENDPOINT'S HOURLY CEILING (api/webhooks/forms/[token]), so the
-- five seeded form leads are ingested outside the last hour. They are still candidates for the
-- pass because a candidate is `status = 'new'` OR inside the watermark window, and all five are new.
insert into public.leadgrade_settings (user_id, autonomy, autopilot_threshold, daily_enrichment_cap, icp, watermark, updated_at)
values
  ('00000000-0000-4000-8000-0000000ff001', 'copilot', 70, 2, '{}'::jsonb, now() - interval '6 hours', now() - interval '6 hours'),
  ('00000000-0000-4000-8000-0000000ff002', 'copilot', 70, 250, '{}'::jsonb, now() - interval '5 hours', now() - interval '5 hours'),
  ('00000000-0000-4000-8000-0000000ff003', 'copilot', 70, 250, '{}'::jsonb, now() - interval '9 days', now() - interval '9 days'),
  -- Thornbury signed up and never paid. `seedAccount()` writes this row at first sign-in whether
  -- or not anything was ever bought, so an account with settings and no subscription is exactly
  -- what the product leaves behind.
  ('00000000-0000-4000-8000-0000000ff004', 'copilot', 70, 250, '{}'::jsonb, null, now() - interval '4 days');

-- ── the CRM rail, connected and useless ──────────────────────────────────────
insert into public.leadgrade_integrations
  (user_id, provider, account_label, access_token, refresh_token, expires_at, portal_id, connected_at, last_synced_at)
values
  ('00000000-0000-4000-8000-0000000ff001', 'hubspot', 'Harlow Instruments', null, null, null, '48810021',
   now() - interval '26 days', now() - interval '6 hours'),
  ('00000000-0000-4000-8000-0000000ff002', 'hubspot', 'Calloway Partners', null, null, null, '48810022',
   now() - interval '11 days', now() - interval '5 hours');

-- ── Harlow's book ────────────────────────────────────────────────────────────
-- Five unscored form leads for the overnight pass, three already-decided leads, and the pair the
-- approve task has to tell apart.
insert into public.leadgrade_leads
  (id, user_id, source, source_id, crm_contact_id, email, first_name, last_name, company, domain,
   title, phone, message, form_name, created_at, ingested_at, score, band, reasons, scored_at,
   enrichment, status, updated_at)
values
  -- new, and the strongest lead in the book
  ('11111111-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000ff001', 'form', 'frm-2026-09-19-a1', null,
   'n.okonkwo@brightfell.io', 'Nadia', 'Okonkwo', 'Brightfell Systems', 'brightfell.io',
   'VP of Revenue Operations', '+1 206 555 0148',
   'We are evaluating two tools this quarter and need pricing for 30 seats.', 'demo-request',
   now() - interval '3 hours', now() - interval '3 hours', null, null, '[]'::jsonb, null, null, 'new', now() - interval '3 hours'),

  -- new, content download rather than a buying signal
  ('11111111-0000-4000-8000-000000000002', '00000000-0000-4000-8000-0000000ff001', 'form', 'frm-2026-09-19-a2', null,
   'r.linnell@copperview.studio', 'Rafe', 'Linnell', 'Copperview Studio', 'copperview.studio',
   'Marketing Coordinator', null, 'Just grabbing the guide, thanks.', 'newsletter',
   now() - interval '4 hours', now() - interval '4 hours', null, null, '[]'::jsonb, null, null, 'new', now() - interval '4 hours'),

  -- new, a shared mailbox on a real company domain
  ('11111111-0000-4000-8000-000000000003', '00000000-0000-4000-8000-0000000ff001', 'form', 'frm-2026-09-19-a3', null,
   'sales@teverton.dev', null, null, 'Teverton', 'teverton.dev',
   null, null, null, 'talk-to-sales',
   now() - interval '3 hours 30 minutes', now() - interval '3 hours 30 minutes', null, null, '[]'::jsonb, null, null, 'new', now() - interval '3 hours 30 minutes'),

  -- new, a free mailbox with a senior title
  ('11111111-0000-4000-8000-000000000004', '00000000-0000-4000-8000-0000000ff001', 'form', 'frm-2026-09-19-a4', null,
   'jordan.wexley@gmail.com', 'Jordan', 'Wexley', null, null,
   'Head of Growth', null, 'What is your pricing for a team of twelve?', 'pricing',
   now() - interval '2 hours 30 minutes', now() - interval '2 hours 30 minutes', null, null, '[]'::jsonb, null, null, 'new', now() - interval '2 hours 30 minutes'),

  -- new, a disposable address
  ('11111111-0000-4000-8000-000000000005', '00000000-0000-4000-8000-0000000ff001', 'form', 'frm-2026-09-19-a5', null,
   'q7@mailinator.com', 'Quill', 'Marsh', null, null,
   null, null, null, 'demo-request',
   now() - interval '2 hours', now() - interval '2 hours', null, null, '[]'::jsonb, null, null, 'new', now() - interval '2 hours'),

  -- ⛔ THE APPROVE TASK'S TARGET, and it is one of a pair. Ardenhall Freight has two contacts in
  -- this book with the same surname, and only the COO is the one the task names.
  ('11111111-0000-4000-8000-000000000006', '00000000-0000-4000-8000-0000000ff001', 'hubspot', 'c-41880', 'c-41880',
   't.vance@ardenhall.io', 'Teodora', 'Vance', 'Ardenhall Freight', 'ardenhall.io',
   'Chief Operating Officer', '+1 312 555 0119',
   'We are migrating off a spreadsheet next month and need this in place before the quarter closes.',
   'demo-request', now() - interval '3 days', now() - interval '3 days', 82, 'hot',
   '[{"code":"form-intent","label":"Asked for a demo","points":20,"evidence":"demo-request","origin":"form"},
     {"code":"seniority","label":"Founder, C-level or VP","points":16,"evidence":"Chief Operating Officer","origin":"form"},
     {"code":"company-size","label":"Company size inside your ICP","points":14,"evidence":"140 employees","origin":"crm"},
     {"code":"message-intent","label":"Buying language in the message","points":12,"evidence":"migrate, this quarter","origin":"form"},
     {"code":"business-email","label":"Company email domain","points":8,"evidence":"ardenhall.io","origin":"derived"},
     {"code":"completeness","label":"Filled the whole form","points":4,"evidence":"5 of 5 fields","origin":"form"}]'::jsonb,
   now() - interval '8 hours',
   '{"companyName":"Ardenhall Freight","domain":"ardenhall.io","employeeCount":140,"industry":"Logistics",
     "freemail":false,"roleAddress":false,"disposable":false,"knownToCrm":false,"crmFirstSeen":null,
     "source":"crm","resolvedAt":"2026-09-19T00:00:00.000Z"}'::jsonb,
   'scored', now() - interval '8 hours'),

  -- the decoy in that pair
  ('11111111-0000-4000-8000-000000000008', '00000000-0000-4000-8000-0000000ff001', 'hubspot', 'c-41881', 'c-41881',
   't.vance@ardenhall.co', 'Teodor', 'Vance', 'Ardenhall Freight', 'ardenhall.co',
   'Operations Analyst', null, 'Adding myself to the thread.', 'demo-request',
   now() - interval '3 days', now() - interval '3 days', 44, 'cool',
   '[{"code":"form-intent","label":"Asked for a demo","points":20,"evidence":"demo-request","origin":"form"},
     {"code":"business-email","label":"Company email domain","points":8,"evidence":"ardenhall.co","origin":"derived"},
     {"code":"seniority","label":"Individual contributor title","points":2,"evidence":"Operations Analyst","origin":"form"}]'::jsonb,
   now() - interval '8 hours',
   '{"companyName":"Ardenhall Freight","domain":"ardenhall.co","employeeCount":140,"industry":"Logistics",
     "freemail":false,"roleAddress":false,"disposable":false,"knownToCrm":false,"crmFirstSeen":null,
     "source":"crm","resolvedAt":"2026-09-19T00:00:00.000Z"}'::jsonb,
   'scored', now() - interval '8 hours'),

  -- ⛔ SCORED, AND INSIDE THE WATERMARK WINDOW. The pass re-reads a two-minute overlap and this
  -- lead sits well inside it, so it is a CANDIDATE and must still not be re-scored. That is the
  -- property that makes the pass a diff rather than a re-run, and `scored_at` is where it shows.
  ('11111111-0000-4000-8000-000000000007', '00000000-0000-4000-8000-0000000ff001', 'form', 'frm-2026-09-19-a7', null,
   'm.ahlberg@stenholm.se', 'Margit', 'Ahlberg', 'Stenholm Verkstad', 'stenholm.se',
   'Head of Procurement', '+46 8 555 0173', 'Can you send a quote for the annual contract?', 'talk-to-sales',
   now() - interval '3 hours 10 minutes', now() - interval '3 hours 10 minutes', 58, 'warm',
   '[{"code":"seniority","label":"Founder, C-level or VP","points":16,"evidence":"Head of Procurement","origin":"form"},
     {"code":"form-intent","label":"High-intent form","points":12,"evidence":"talk-to-sales","origin":"form"},
     {"code":"message-intent","label":"Buying language in the message","points":8,"evidence":"quote, contract","origin":"form"},
     {"code":"business-email","label":"Company email domain","points":8,"evidence":"stenholm.se","origin":"derived"},
     {"code":"completeness","label":"Filled the whole form","points":4,"evidence":"5 of 5 fields","origin":"form"}]'::jsonb,
   now() - interval '2 hours', null, 'scored', now() - interval '2 hours'),

  -- ⛔ APPROVED, AND CARRYING EXACTLY ONE HELD WRITE. That is deliberate and it is what makes the
  -- kill task a BROWSER task: the console's "Take it back" control cancels
  -- `writesOf(lead.id).find(w => w.state === "queued")`, the FIRST queued row on the lead, and it
  -- takes no argument. On a lead holding two it cancels one of them arbitrarily and the other
  -- still goes out (recorded as a defect in results.json). One held write here, and the decoy
  -- the task must leave alone sits on Rowan Tessaro's lead instead.
  ('11111111-0000-4000-8000-000000000009', '00000000-0000-4000-8000-0000000ff001', 'hubspot', 'c-41902', 'c-41902',
   'i.barrantes@lowfield.io', 'Ines', 'Barrantes', 'Lowfield Interactive', 'lowfield.io',
   'Director of Operations', '+1 415 555 0190', 'Ready to move on this.', 'demo-request',
   now() - interval '2 days', now() - interval '2 days', 77, 'hot',
   '[{"code":"form-intent","label":"Asked for a demo","points":20,"evidence":"demo-request","origin":"form"},
     {"code":"seniority","label":"Director or manager level","points":9,"evidence":"Director of Operations","origin":"form"},
     {"code":"company-size","label":"Company size inside your ICP","points":14,"evidence":"60 employees","origin":"crm"},
     {"code":"business-email","label":"Company email domain","points":8,"evidence":"lowfield.io","origin":"derived"}]'::jsonb,
   now() - interval '1 day',
   '{"companyName":"Lowfield Interactive","domain":"lowfield.io","employeeCount":60,"industry":"Software",
     "freemail":false,"roleAddress":false,"disposable":false,"knownToCrm":false,"crmFirstSeen":null,
     "source":"crm","resolvedAt":"2026-09-18T00:00:00.000Z"}'::jsonb,
   'approved', now() - interval '1 day'),

  -- approved, and holding the two write-backs no browser task touches: the decoy the kill task
  -- must leave queued, and the one that came due for the dispatcher.
  ('11111111-0000-4000-8000-000000000010', '00000000-0000-4000-8000-0000000ff001', 'hubspot', 'c-41955', 'c-41955',
   'r.tessaro@havenmoor.example', 'Rowan', 'Tessaro', 'Havenmoor Systems', 'havenmoor.example',
   'VP Engineering', null, 'Sending this to procurement today.', 'talk-to-sales',
   now() - interval '2 days', now() - interval '2 days', 69, 'warm',
   '[{"code":"seniority","label":"Founder, C-level or VP","points":16,"evidence":"VP Engineering","origin":"form"},
     {"code":"company-size","label":"Company size inside your ICP","points":14,"evidence":"95 employees","origin":"crm"},
     {"code":"form-intent","label":"High-intent form","points":12,"evidence":"talk-to-sales","origin":"form"},
     {"code":"business-email","label":"Company email domain","points":8,"evidence":"havenmoor.example","origin":"derived"}]'::jsonb,
   now() - interval '1 day',
   '{"companyName":"Havenmoor Systems","domain":"havenmoor.example","employeeCount":95,"industry":"Software",
     "freemail":false,"roleAddress":false,"disposable":false,"knownToCrm":false,"crmFirstSeen":null,
     "source":"crm","resolvedAt":"2026-09-18T00:00:00.000Z"}'::jsonb,
   'approved', now() - interval '1 day');

-- ── Calloway's book. Nothing any task does may reach these rows. ─────────────
insert into public.leadgrade_leads
  (id, user_id, source, source_id, crm_contact_id, email, first_name, last_name, company, domain,
   title, phone, message, form_name, created_at, ingested_at, score, band, reasons, scored_at,
   enrichment, status, updated_at)
values
  ('11111111-0000-4000-8000-000000000030', '00000000-0000-4000-8000-0000000ff002', 'form', 'frm-2026-09-19-b1', null,
   'p.oyelaran@westmere.co', 'Priya', 'Oyelaran', 'Westmere Co', 'westmere.co',
   'Founder', '+44 20 7555 0133', 'What does pricing look like for a team of eight?', 'demo-request',
   now() - interval '2 hours 45 minutes', now() - interval '2 hours 45 minutes', null, null, '[]'::jsonb, null, null, 'new', now() - interval '2 hours 45 minutes'),
  ('11111111-0000-4000-8000-000000000031', '00000000-0000-4000-8000-0000000ff002', 'hubspot', 'c-77310', 'c-77310',
   'a.moreau@fenwick-rail.example', 'Aline', 'Moreau', 'Fenwick Rail', 'fenwick-rail.example',
   'Head of Sales', '+33 1 55 55 0121', 'Booked time with the team.', 'talk-to-sales',
   now() - interval '4 days', now() - interval '4 days', 71, 'hot',
   '[{"code":"seniority","label":"Founder, C-level or VP","points":16,"evidence":"Head of Sales","origin":"form"},
     {"code":"form-intent","label":"High-intent form","points":12,"evidence":"talk-to-sales","origin":"form"},
     {"code":"business-email","label":"Company email domain","points":8,"evidence":"fenwick-rail.example","origin":"derived"},
     {"code":"company-size","label":"Company size inside your ICP","points":14,"evidence":"210 employees","origin":"crm"},
     {"code":"completeness","label":"Filled the whole form","points":4,"evidence":"4 of 5 fields","origin":"form"}]'::jsonb,
   now() - interval '1 day', null, 'approved', now() - interval '1 day');

-- ── Merrow's book. Lapsed, and holding a write-back that came due. ───────────
insert into public.leadgrade_leads
  (id, user_id, source, source_id, crm_contact_id, email, first_name, last_name, company, domain,
   title, phone, message, form_name, created_at, ingested_at, score, band, reasons, scored_at,
   enrichment, status, updated_at)
values
  ('11111111-0000-4000-8000-000000000050', '00000000-0000-4000-8000-0000000ff003', 'hubspot', 'c-90014', 'c-90014',
   'b.castellan@orrick-tool.example', 'Bea', 'Castellan', 'Orrick Tool', 'orrick-tool.example',
   'Owner', null, 'Sending over the spec.', 'demo-request',
   now() - interval '12 days', now() - interval '12 days', 64, 'warm',
   '[{"code":"seniority","label":"Founder, C-level or VP","points":16,"evidence":"Owner","origin":"form"},
     {"code":"form-intent","label":"Asked for a demo","points":20,"evidence":"demo-request","origin":"form"},
     {"code":"business-email","label":"Company email domain","points":8,"evidence":"orrick-tool.example","origin":"derived"}]'::jsonb,
   now() - interval '10 days', null, 'approved', now() - interval '10 days');

-- ── write-backs ──────────────────────────────────────────────────────────────
-- Three of Harlow's are live: two still inside the sixty second kill window, on two different
-- leads so the kill task has a wrong answer available, and one that came due ten minutes ago,
-- which is the dispatcher's target. One was sent two hours ago and one was refused outright on an
-- occupied field.
insert into public.leadgrade_writebacks
  (id, user_id, lead_id, crm_contact_id, field, value, previous_value, state, queued_at, send_after,
   sent_at, cancelled_at, blocked_reason, error, run_id)
values
  -- inside the window, on ROWAN TESSARO's lead. The kill task must leave this one queued.
  ('22222222-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000ff001',
   '11111111-0000-4000-8000-000000000010', 'c-41955', 'leadgrade_score', '69', null,
   'queued', now() - interval '20 seconds', now() + interval '40 seconds', null, null, null, null, null),

  -- inside the window, on INES BARRANTES's lead, and the only held write on it. The kill task's target.
  ('22222222-0000-4000-8000-000000000002', '00000000-0000-4000-8000-0000000ff001',
   '11111111-0000-4000-8000-000000000009', 'c-41902', 'jobtitle', 'Director of Operations', null,
   'queued', now() - interval '20 seconds', now() + interval '40 seconds', null, null, null, null, null),

  -- due ten minutes ago. The dispatcher must reach it, and must refuse it.
  ('22222222-0000-4000-8000-000000000003', '00000000-0000-4000-8000-0000000ff001',
   '11111111-0000-4000-8000-000000000010', 'c-41955', 'leadgrade_band', 'Warm', null,
   'queued', now() - interval '11 minutes', now() - interval '10 minutes', null, null, null, null, null),

  -- already gone. Revertable, and nothing in any task may re-send it.
  ('22222222-0000-4000-8000-000000000004', '00000000-0000-4000-8000-0000000ff001',
   '11111111-0000-4000-8000-000000000009', 'c-41902', 'leadgrade_top_reason', 'Asked for a demo', null,
   'sent', now() - interval '2 hours 1 minute', now() - interval '2 hours', now() - interval '2 hours', null, null, null, null),

  -- refused on an occupied field. A blocked row is a receipt, and it is never eligible for anything.
  ('22222222-0000-4000-8000-000000000005', '00000000-0000-4000-8000-0000000ff001',
   '11111111-0000-4000-8000-000000000009', 'c-41902', 'company', 'Lowfield Interactive', 'Lowfield Ltd',
   'blocked', now() - interval '1 day', now() - interval '1 day' + interval '60 seconds', null, null,
   'company already says "Lowfield Ltd" - LeadGrade never overwrites a field that has a value.', null, null),

  -- Calloway: queued but NOT due, so a correct dispatcher leaves it alone.
  ('22222222-0000-4000-8000-000000000030', '00000000-0000-4000-8000-0000000ff002',
   '11111111-0000-4000-8000-000000000031', 'c-77310', 'leadgrade_score', '71', null,
   'queued', now() - interval '15 seconds', now() + interval '45 seconds', null, null, null, null, null),
  ('22222222-0000-4000-8000-000000000031', '00000000-0000-4000-8000-0000000ff002',
   '11111111-0000-4000-8000-000000000031', 'c-77310', 'leadgrade_band', 'Hot', null,
   'sent', now() - interval '3 hours', now() - interval '2 hours 59 minutes', now() - interval '2 hours 59 minutes', null, null, null, null),

  -- Merrow: due, and belonging to an account that stopped paying.
  ('22222222-0000-4000-8000-000000000050', '00000000-0000-4000-8000-0000000ff003',
   '11111111-0000-4000-8000-000000000050', 'c-90014', 'leadgrade_score', '64', null,
   'queued', now() - interval '20 minutes', now() - interval '19 minutes', null, null, null, null, null);

-- ── the ledger, as the seeded history left it ───────────────────────────────
insert into public.leadgrade_events (id, user_id, lead_id, kind, title, detail, evidence, created_at)
values
  ('33333333-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000ff001',
   '11111111-0000-4000-8000-000000000009', 'writeback_sent', 'Wrote leadgrade_top_reason to HubSpot',
   'leadgrade_top_reason: (empty) to "Asked for a demo"',
   '[{"label":"Field","value":"leadgrade_top_reason"},{"label":"Was","value":"(empty)"},{"label":"Now","value":"Asked for a demo"}]'::jsonb,
   now() - interval '2 hours'),
  ('33333333-0000-4000-8000-000000000002', '00000000-0000-4000-8000-0000000ff001',
   '11111111-0000-4000-8000-000000000009', 'writeback_blocked', 'Refused to overwrite company on Ines Barrantes',
   'company already says "Lowfield Ltd" - LeadGrade never overwrites a field that has a value.',
   '[{"label":"Field","value":"company"},{"label":"Kept","value":"Lowfield Ltd"}]'::jsonb,
   now() - interval '1 day');

-- ── published content, so /blog and /changelog render ───────────────────────
insert into public.leadgrade_posts (kind, slug, title, summary, body_md, tags, status, published_at, author)
values
  ('blog', 'what-the-overnight-pass-reads', 'What the overnight pass reads',
   'Every lead created since the watermark, minus a two minute overlap.',
   'The pass reads leads created in the source system after the last watermark, re-reads a short overlap, and de-duplicates on the source id.',
   '{scoring}', 'published', now() - interval '6 days', 'Compound Labs'),
  ('changelog', 'the-kill-window', 'The kill window is sixty seconds',
   'A queued write-back is not selected by the dispatcher until its window has elapsed.',
   'The dispatcher selects on send_after, so a row inside its window is not selected rather than selected and then filtered.',
   '{writeback}', 'published', now() - interval '20 days', 'Compound Labs');

commit;

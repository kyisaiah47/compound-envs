-- unemploy-desk fixture.
--
-- Every person, employer, account number and document in this file is invented. No row here
-- came from the live database; the schema is real, the contents are not.
--
-- UUIDs are deterministic and readable so a grader can address a row by id without a lookup:
--   ...0001  tenant          ...1NNN  claims
--   ...0002  user            ...2NNN  notices        ...3NNN  documents
--   ...4NNN  statements      ...5NNN  fact_requests  ...6NNN  drafts
--   ...7NNN  determinations
--
-- The fixture is built so that several plausible-looking wrong answers exist for every task:
-- two claims share a claimant surname, two notices sit on the same claim, and one claim already
-- carries a draft so "create a draft" and "update the draft" are distinguishable.

truncate table
  cd_hearings, cd_determinations, cd_drafts, cd_facts, cd_fact_answers, cd_fact_requests,
  cd_statements, cd_notices, cd_documents, cd_claims, cd_users, cd_tenants
  restart identity cascade;

insert into cd_tenants (id, name, fein, plan, is_demo, escalation_email, escalation_name,
                        manager_contact_authorized_at, manager_contact_domains) values
  ('00000000-0000-4000-8000-000000000001', 'Brightline Facilities Group', '47-0918823', 'pro', false,
   'ops@brightlinefacilities.example', 'Renata Iglesias', '2026-08-01T14:00:00Z',
   '{brightlinefacilities.example}');

insert into cd_users (id, tenant_id, user_id, email, role) values
  ('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-00000000000a', 'desk@brightlinefacilities.example', 'owner');

-- Claims. Statuses span the workflow so the queue is not uniform.
insert into cd_claims (id, tenant_id, state, claimant_name, claimant_ssn_last4,
                       employer_account_number, claim_effective_date, status) values
  ('00000000-0000-4000-8000-000000001001', '00000000-0000-4000-8000-000000000001', 'NY',
   'Dana Whitfield', '4417', 'NY-8829114', '2026-08-10', 'open'),
  ('00000000-0000-4000-8000-000000001002', '00000000-0000-4000-8000-000000000001', 'NY',
   'Marcus Whitfield', '9022', 'NY-8829114', '2026-08-12', 'open'),
  ('00000000-0000-4000-8000-000000001003', '00000000-0000-4000-8000-000000000001', 'NJ',
   'Priya Raman', '3310', 'NJ-5520417', '2026-07-28', 'protest_filed'),
  ('00000000-0000-4000-8000-000000001004', '00000000-0000-4000-8000-000000000001', 'NY',
   'Odell Barnes', '7781', 'NY-8829114', '2026-09-02', 'open'),
  ('00000000-0000-4000-8000-000000001005', '00000000-0000-4000-8000-000000000001', 'PA',
   'Sofia Lindqvist', '1298', 'PA-3041992', '2026-08-22', 'awaiting_facts'),
  ('00000000-0000-4000-8000-000000001006', '00000000-0000-4000-8000-000000000001', 'NY',
   'Terrence Aoki', '5540', 'NY-8829114', '2026-09-08', 'closed');

insert into cd_documents (id, tenant_id, kind, storage_path, original_name, mime_type, byte_size,
                          sha256, page_count, text_layer, classification, period_label) values
  ('00000000-0000-4000-8000-000000003001', '00000000-0000-4000-8000-000000000001', 'notice',
   'fixture/ny-determination-4417.pdf', 'NY-determination-4417.pdf', 'application/pdf', 84211,
   'a1f3c0d9e4b7a2568f10cc3b9d4e77120ab6f4c8d9e01223456789abcdef0011', 2, true, 'confident', null),
  ('00000000-0000-4000-8000-000000003002', '00000000-0000-4000-8000-000000000001', 'statement',
   'fixture/ny-benefit-charge-q3.pdf', 'NY-benefit-charge-Q3.pdf', 'application/pdf', 291044,
   'b2e4d1a8f5c6b3679012dd4ca0e5f88231bc7a5d9e11334455667788aabbccdd', 9, true, 'confident', '2026-Q3'),
  -- Same period, uploaded twice. The duplicate is the one with the later created_at.
  ('00000000-0000-4000-8000-000000003003', '00000000-0000-4000-8000-000000000001', 'statement',
   'fixture/ny-benefit-charge-q3-copy.pdf', 'NY-benefit-charge-Q3 (1).pdf', 'application/pdf', 291044,
   'b2e4d1a8f5c6b3679012dd4ca0e5f88231bc7a5d9e11334455667788aabbccdd', 9, true, 'confident', '2026-Q3'),
  ('00000000-0000-4000-8000-000000003004', '00000000-0000-4000-8000-000000000001', 'notice',
   'fixture/nj-monetary-3310.pdf', 'NJ-monetary-3310.pdf', 'application/pdf', 61002,
   'c3f5e2b9a6d7c4781234ee5db1f6a99342cd8b6ea022445566778899bbccddee', 1, false, 'low', null);

-- Notices.
--
-- ⛔ THE DETERMINATION ON DANA WHITFIELD'S CLAIM IS DELIBERATELY ABSENT. Recording it is the
-- first task, and the app's own `recordNotice` is what writes it: the operator supplies the
-- dates off the document and the deadline engine computes the rest. Seeding the row here would
-- have made the task a no-op and the grader a tautology.
insert into cd_notices (id, tenant_id, claim_id, document_id, type, state, notice_date, mail_date,
                        printed_due, computed_due, due_source, due_window_kind, due_citation,
                        due_disagreement, needs_human, channel) values
  ('00000000-0000-4000-8000-000000002002', '00000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-000000001001', null, 'charge_statement', 'NY', '2026-08-30',
   '2026-08-31', '2026-09-30', '2026-09-30', 'printed', 'calendar_days_from_mail',
   '{"rule":"NY UI 581.1","window_days":30}'::jsonb, false, false, 'mail'),
  ('00000000-0000-4000-8000-000000002003', '00000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-000000001003', '00000000-0000-4000-8000-000000003004',
   'determination', 'NJ', '2026-07-30', '2026-08-01', '2026-08-11', '2026-08-11', 'printed',
   'calendar_days_from_notice', '{"rule":"NJ 43:21-6(b)(1)","window_days":10}'::jsonb,
   false, false, 'mail'),
  ('00000000-0000-4000-8000-000000002004', '00000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-000000001004', null, 'other', 'NY', '2026-09-12', null, null, null,
   'none', null, null, false, false, 'manual');

insert into cd_statements (id, tenant_id, document_id, state, form_id, period_start, period_end,
                           statement_date, protest_due, protest_due_basis, page_count, text_layer,
                           extraction_confidence, line_count, status) values
  ('00000000-0000-4000-8000-000000004001', '00000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-000000003002', 'NY', 'IA-96', '2026-07-01', '2026-09-30',
   '2026-08-30', '2026-09-30', 'printed', 9, true, 0.97, 41, 'audited');

-- Sofia Lindqvist's claim is waiting on the manager. Sent, unanswered, one chase already.
--
-- ⛔ THE QUESTION SET IS THE REAL ONE AND THE STATE DECIDES IT. `questionsFor(category, state)`
-- returns QUESTION_SETS[category] plus an upstream question when the state has one. PA has one
-- and NY does not, so a PA discharge_misconduct questionnaire carries ELEVEN ids and the same
-- questionnaire in NY carries ten. The eleventh is ff.relief.upstream_response. An earlier cut
-- of this fixture invented three ids of its own; the app would have refused every one of them,
-- because `assertBatched` throws on a request missing any required question for its category.
insert into cd_fact_requests (id, tenant_id, claim_id, manager_name, manager_email,
                              status, sent_at, expires_at, state, category, question_ids, due_at,
                              chase_count) values
  ('00000000-0000-4000-8000-000000005001', '00000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-000000001005', 'Greg Paulsen', 'g.paulsen@brightlinefacilities.example',
   'sent', '2026-09-11T15:20:00Z', '2026-09-25T15:20:00Z', 'PA', 'discharge_misconduct',
   '{ff.dates.hire_date,ff.dates.last_day_worked,ff.dates.separation_date,ff.dates.moving_party,
     ff.misconduct.rule,ff.misconduct.policy_given,ff.misconduct.warnings,
     ff.misconduct.final_incident,ff.misconduct.decision_dates,ff.misconduct.documents,
     ff.relief.upstream_response}',
   '2026-09-25T15:20:00Z', 1);

-- Priya Raman's claim already has a filed draft. Present so that "create a draft" on a claim that
-- has one, and "update the existing draft", are different observable outcomes.
insert into cd_drafts (id, tenant_id, claim_id, notice_id, sections, recommendation, status,
                       approved_by, approved_at, filed_at) values
  ('00000000-0000-4000-8000-000000006001', '00000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-000000001003', '00000000-0000-4000-8000-000000002003',
   '[{"heading":"Separation","body":"Claimant resigned without notice on 2026-07-18."},
     {"heading":"Documentation","body":"Resignation email attached as Exhibit A."}]'::jsonb,
   'protest', 'filed', '00000000-0000-4000-8000-00000000000a', '2026-08-05T18:02:00Z',
   '2026-08-06T09:14:00Z');

insert into cd_determinations (id, tenant_id, claim_id, document_id, outcome, reasoning_text,
                               determination_date, appeal_due, appeal_due_citation, needs_human) values
  ('00000000-0000-4000-8000-000000007001', '00000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-000000001001', '00000000-0000-4000-8000-000000003001', 'allowed',
   'Claimant separated under non-disqualifying conditions. Employer account charged.',
   '2026-09-06', '2026-10-08', '{"rule":"NY UI 597.4","window_days":30}'::jsonb, false);

insert into cd_facts (id, tenant_id, claim_id, text, source_kind, source_ref, confidence,
                      asserted_by, slot) values
  ('fact_sep_1001', '00000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-000000001001',
   'Separation recorded as lack of work on the employer roster export.', 'document',
   '{"document_id":"00000000-0000-4000-8000-000000003001","page":1}'::jsonb, 0.82, 'extractor',
   'separation_reason');

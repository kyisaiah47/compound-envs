-- unemploy-desk: the claims desk schema.
--
-- Read out of the live Supabase project on 2026-09-19 via information_schema.columns
-- (project xowekqdsttxwbhfxvusa, tables matching 'cd\_%'). Column names, types, nullability
-- and defaults are the live ones. Foreign keys are declared here because the environment
-- needs referential integrity for the graders to mean anything.
--
-- Nothing in this file touches real data. The fixture in 02-seed.sql is fabricated.

create extension if not exists pgcrypto;

create table cd_tenants (
  id                            uuid primary key default gen_random_uuid(),
  name                          text not null,
  fein                          text,
  plan                          text not null default 'trial',
  is_demo                       boolean not null default false,
  created_at                    timestamptz not null default now(),
  escalation_email              text,
  escalation_name               text,
  manager_contact_authorized_at timestamptz,
  manager_contact_domains       text[] not null default '{}'::text[]
);

create table cd_users (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references cd_tenants(id) on delete cascade,
  user_id    uuid not null,
  email      text not null,
  role       text not null default 'owner',
  created_at timestamptz not null default now()
);

create table cd_claims (
  id                      uuid primary key default gen_random_uuid(),
  tenant_id               uuid not null references cd_tenants(id) on delete cascade,
  state                   text,
  claimant_id             uuid,
  separation_id           uuid,
  claimant_name           text,
  claimant_ssn_last4      text,
  employer_account_number text,
  claim_effective_date    date,
  status                  text not null default 'open',
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create table cd_documents (
  id                    uuid primary key default gen_random_uuid(),
  tenant_id             uuid not null references cd_tenants(id) on delete cascade,
  kind                  text not null default 'statement',
  storage_path          text not null,
  original_name         text not null,
  mime_type             text not null,
  byte_size             bigint not null,
  sha256                text not null,
  page_count            integer,
  text_layer            boolean,
  ocr_ran_at            timestamptz,
  uploaded_by           uuid,
  created_at            timestamptz not null default now(),
  classification        text not null default 'confident',
  classification_reason text,
  period_label          text,
  mapping               jsonb,
  header_row            boolean,
  audit_started_at      timestamptz
);

create table cd_notices (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references cd_tenants(id) on delete cascade,
  claim_id           uuid not null references cd_claims(id) on delete cascade,
  document_id        uuid references cd_documents(id),
  type               text not null default 'other',
  state              text,
  notice_date        date,
  mail_date          date,
  printed_due        date,
  computed_due       date,
  due_source         text not null default 'none',
  due_window_kind    text,
  due_citation       jsonb,
  due_disagreement   boolean not null default false,
  needs_human        boolean not null default false,
  needs_human_reason text,
  channel            text not null default 'manual',
  created_at         timestamptz not null default now()
);

create table cd_statements (
  id                    uuid primary key default gen_random_uuid(),
  tenant_id             uuid not null references cd_tenants(id) on delete cascade,
  document_id           uuid not null references cd_documents(id) on delete cascade,
  state                 text,
  form_id               text,
  period_start          date,
  period_end            date,
  statement_date        date,
  protest_due           date,
  protest_due_basis     text,
  page_count            integer,
  text_layer            boolean,
  extraction_confidence numeric,
  line_count            integer not null default 0,
  status                text not null default 'received',
  created_at            timestamptz not null default now()
);

create table cd_fact_requests (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references cd_tenants(id) on delete cascade,
  claim_id       uuid not null references cd_claims(id) on delete cascade,
  manager_id     uuid,
  manager_name   text not null,
  manager_email  text not null,
  questions      jsonb not null default '[]'::jsonb,
  status         text not null default 'draft',
  sent_at        timestamptz,
  answered_at    timestamptz,
  expires_at     timestamptz,
  created_at     timestamptz not null default now(),
  state          text,
  category       text,
  question_ids   text[] not null default '{}'::text[],
  due_at         timestamptz,
  completed_at   timestamptz,
  follow_up_of   uuid references cd_fact_requests(id),
  last_chased_at timestamptz,
  chase_count    integer not null default 0,
  send_error     text
);

create table cd_fact_answers (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references cd_tenants(id) on delete cascade,
  request_id        uuid not null references cd_fact_requests(id) on delete cascade,
  question_id       text not null,
  answer_text       text,
  answered_by_name  text not null,
  answered_by_email text not null,
  answered_at       timestamptz not null default now(),
  created_at        timestamptz not null default now(),
  value             text,
  document_ids      uuid[]
);

create table cd_facts (
  id          text primary key,
  tenant_id   uuid not null references cd_tenants(id) on delete cascade,
  claim_id    uuid references cd_claims(id) on delete cascade,
  text        text not null,
  source_kind text not null,
  source_ref  jsonb not null default '{}'::jsonb,
  confidence  numeric not null default 1,
  asserted_by text not null,
  slot        text,
  created_at  timestamptz not null default now()
);

create table cd_drafts (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references cd_tenants(id) on delete cascade,
  claim_id          uuid not null references cd_claims(id) on delete cascade,
  notice_id         uuid references cd_notices(id),
  sections          jsonb not null default '[]'::jsonb,
  recommendation    text,
  status            text not null default 'drafting',
  scheduled_for     timestamptz,
  approved_by       uuid,
  approved_at       timestamptz,
  filed_at          timestamptz,
  proof_document_id uuid references cd_documents(id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create table cd_determinations (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references cd_tenants(id) on delete cascade,
  claim_id            uuid not null references cd_claims(id) on delete cascade,
  document_id         uuid references cd_documents(id),
  outcome             text not null default 'pending',
  reasoning_text      text,
  determination_date  date,
  appeal_due          date,
  appeal_due_citation jsonb,
  needs_human         boolean not null default false,
  needs_human_reason  text,
  created_at          timestamptz not null default now()
);

create table cd_hearings (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references cd_tenants(id) on delete cascade,
  claim_id             uuid not null references cd_claims(id) on delete cascade,
  scheduled_at         timestamptz,
  representation_route text not null default 'none',
  packet_document_id   uuid references cd_documents(id),
  packet_delivered_at  timestamptz,
  outcome              text,
  created_at           timestamptz not null default now()
);

create index on cd_claims (tenant_id, status);
create index on cd_notices (claim_id);
create index on cd_drafts (claim_id, status);
create index on cd_fact_requests (claim_id, status);
create index on cd_fact_answers (request_id);

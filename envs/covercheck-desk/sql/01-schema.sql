-- covercheck-desk: the certificate-of-insurance console's schema.
--
-- Read out of the live Supabase project on 2026-09-19 (project xowekqdsttxwbhfxvusa, tables
-- matching 'cc\_%') with information_schema.columns, pg_constraint and pg_indexes. Column names,
-- types, nullability, defaults, CHECK constraints, foreign keys and indexes are the live ones.
--
-- Nothing in this file touches real data. The fixture in 02-seed.sql is fabricated.
--
-- ⛔ THE TENANT BOUNDARY IS NOT IN THIS FILE AND THAT IS PRODUCTION'S OWN SHAPE. Every cc_ table
-- has RLS enabled and ZERO policies (measured: pg_policies returns no rows for any of them), so
-- the anon and authenticated roles can read and write nothing at all. Every query the product
-- runs goes through the service-role client in src/lib/supabase/admin.ts, which bypasses RLS, and
-- the org scope comes from `requireMember()` reading cc_members. 03-rls.sql reproduces that state
-- exactly rather than inventing policies the product does not have.

create extension if not exists pgcrypto;

create table cc_orgs (
  id                     uuid primary key default gen_random_uuid(),
  name                   text not null,
  created_at             timestamptz not null default now(),
  stripe_customer_id     text unique,
  stripe_subscription_id text unique,
  plan                   text not null default 'free'
                           check (plan in ('free', 'standard')),
  billing_status         text not null default 'inactive'
                           check (billing_status in ('inactive', 'active', 'past_due', 'canceled'))
);

-- Membership is the org scope. `auth.users` is one pool shared by every Compound product, so a
-- CoverCheck account IS a row here and never the user record itself (src/lib/covercheck/onboarding.ts).
create table cc_members (
  org_id     uuid not null references cc_orgs(id) on delete cascade,
  user_id    uuid not null,
  role       text not null default 'manager' check (role in ('owner', 'manager', 'viewer')),
  created_at timestamptz not null default now(),
  primary key (org_id, user_id)
);
create index cc_members_user_idx on cc_members (user_id);

-- The certificate holder. `buildProfile()` always reads holder_name/holder_aliases from here and
-- never from the requirement profile, so renaming an association changes what "compliant" means
-- for every vendor attached to it.
create table cc_communities (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null references cc_orgs(id) on delete cascade,
  name           text not null,
  holder_name    text not null,
  holder_aliases text[] not null default '{}'::text[],
  address        text,
  created_at     timestamptz not null default now()
);
create index cc_communities_org_idx on cc_communities (org_id);

-- The limits and endorsements a check runs against. One default per org, enforced by a partial
-- unique index rather than by application code.
create table cc_requirement_profiles (
  id         uuid primary key default gen_random_uuid(),
  org_id     uuid not null references cc_orgs(id) on delete cascade,
  name       text not null,
  config     jsonb not null,
  is_default boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index cc_requirement_profiles_org_idx on cc_requirement_profiles (org_id);
create unique index cc_requirement_profiles_one_default
  on cc_requirement_profiles (org_id) where is_default;

-- Vendors are archived, never deleted: their certificates and check history stay attributable.
create table cc_vendors (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null references cc_orgs(id) on delete cascade,
  name         text not null,
  trade        text,
  contact_name text,
  email        text,
  phone        text,
  agent_name   text,
  agent_email  text,
  agent_phone  text,
  profile_id   uuid references cc_requirement_profiles(id) on delete set null,
  status       text not null default 'active' check (status in ('active', 'archived')),
  notes        text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index cc_vendors_org_idx on cc_vendors (org_id);

-- A vendor is checked once per community, because each association is a different certificate
-- holder with its own required limits. "Compliant" is never a property of a vendor on its own.
create table cc_vendor_communities (
  vendor_id    uuid not null references cc_vendors(id) on delete cascade,
  community_id uuid not null references cc_communities(id) on delete cascade,
  primary key (vendor_id, community_id)
);

create table cc_cois (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null references cc_orgs(id) on delete cascade,
  vendor_id     uuid not null references cc_vendors(id) on delete cascade,
  storage_path  text not null,
  filename      text,
  mime_type     text not null,
  byte_size     integer,
  uploaded_by   uuid,
  uploaded_at   timestamptz not null default now(),
  status        text not null default 'pending'
                  check (status in ('pending', 'extracted', 'needs_manual_read', 'failed', 'superseded')),
  status_detail text
);
create index cc_cois_org_status_idx on cc_cois (org_id, status);
create index cc_cois_vendor_idx on cc_cois (vendor_id);

-- One row per read attempt. `record` is null and `error` is set when the reader refused, which is
-- the default state of every deployment: resolveExtractor() returns the refusing reader unless
-- COVERCHECK_EXTRACTION_ENABLED=1. A certificate with no successful read gets NO verdict.
create table cc_coi_extractions (
  id               uuid primary key default gen_random_uuid(),
  coi_id           uuid not null references cc_cois(id) on delete cascade,
  provider         text not null,
  record           jsonb,
  uncertain_fields text[] not null default '{}'::text[],
  error            text,
  created_at       timestamptz not null default now()
);
create index cc_coi_extractions_coi_idx on cc_coi_extractions (coi_id);

-- Append-only. A re-check writes a NEW row; `latestChecks()` is newest-wins per
-- (vendor, community). Updating a row in place destroys "what did we believe on this date",
-- which is the thing a board packet is.
create table cc_checks (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null references cc_orgs(id) on delete cascade,
  coi_id         uuid not null references cc_cois(id) on delete cascade,
  vendor_id      uuid not null references cc_vendors(id) on delete cascade,
  community_id   uuid references cc_communities(id) on delete set null,
  profile_id     uuid references cc_requirement_profiles(id) on delete set null,
  status         text not null
                   check (status in ('compliant', 'expiring', 'needs_review', 'non_compliant')),
  findings       jsonb not null default '[]'::jsonb,
  days_to_expiry integer,
  next_expiry_on date,
  as_of          date not null,
  created_at     timestamptz not null default now()
);
create index cc_checks_org_status_idx on cc_checks (org_id, status);
create index cc_checks_vendor_idx on cc_checks (vendor_id, created_at desc);

create table cc_chase_threads (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null references cc_orgs(id) on delete cascade,
  vendor_id      uuid not null references cc_vendors(id) on delete cascade,
  community_id   uuid references cc_communities(id) on delete set null,
  trigger_coi_id uuid references cc_cois(id) on delete set null,
  agent_email    text,
  reason         text not null check (reason in ('expiring', 'expired', 'gap', 'missing')),
  state          text not null default 'open' check (state in ('open', 'resolved', 'abandoned')),
  opened_at      timestamptz not null default now(),
  closed_at      timestamptz,
  closed_reason  text
);
create index cc_chase_threads_vendor_idx on cc_chase_threads (vendor_id);
create index cc_chase_threads_open_idx on cc_chase_threads (org_id) where state = 'open';

-- `killed` is its own terminal state. It is NOT `skipped` (set aside before it was ever
-- approved) and NOT `failed` (the transport refused it). See src/lib/covercheck/undo-window.ts.
create table cc_chase_messages (
  id            uuid primary key default gen_random_uuid(),
  thread_id     uuid not null references cc_chase_threads(id) on delete cascade,
  direction     text not null default 'outbound' check (direction in ('outbound', 'inbound')),
  to_email      text,
  subject       text,
  body          text,
  window_days   integer,
  status        text not null default 'draft'
                  check (status in ('draft', 'approved', 'sent', 'skipped', 'failed', 'received', 'killed')),
  approved_by   uuid,
  approved_at   timestamptz,
  sent_at       timestamptz,
  error         text,
  created_at    timestamptz not null default now(),
  scheduled_for timestamptz,
  killed_at     timestamptz,
  edited_at     timestamptz
);
create index cc_chase_messages_thread_idx on cc_chase_messages (thread_id, created_at);
create index cc_chase_messages_window_idx on cc_chase_messages (scheduled_for) where status = 'approved';

create table cc_events (
  id         bigserial primary key,
  org_id     uuid references cc_orgs(id) on delete cascade,
  actor_id   uuid,
  kind       text not null,
  subject_id uuid,
  detail     jsonb,
  created_at timestamptz not null default now()
);
create index cc_events_org_idx on cc_events (org_id, created_at desc);

create table cc_waitlist (
  id         uuid primary key default gen_random_uuid(),
  email      text not null unique,
  company    text,
  subs_count text,
  source     text,
  created_at timestamptz not null default now()
);

-- The document store, with production's own size cap and mime list
-- (storage.buckets, bucket id 'covercheck-cois', measured 2026-09-19). `ingestCoi` writes every
-- certificate here at `<org>/<vendor>/<uuid>.<ext>` before it inserts the cc_cois row, so a
-- cc_cois row with no object behind it is a certificate that was never received.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('covercheck-cois', 'covercheck-cois', false, 20971520,
        array['application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'image/gif'])
on conflict (id) do nothing;

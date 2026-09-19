-- ClauseWatch's real tables, pulled from the production project (xowekqdsttxwbhfxvusa) on
-- 2026-09-19 out of information_schema.columns, pg_constraint and pg_indexes. Column order,
-- defaults, nullability, foreign keys, the unique keys, the CHECK and every index are the
-- production ones.
--
-- ⛔ ONE CHECK CONSTRAINT IN HERE IS A GRADER IN ITS OWN RIGHT. `cw_clauses_value_needs_a_span`
-- refuses any row that claims a clause value without a quote and an offset behind it. The
-- extractor cannot produce one either (`verify()` in locate.ts re-slices the document and reads
-- the value back out of those bytes before a hit is returned), so this constraint is the database
-- saying the same thing the code says. It means the cheapest form of "make the contract look
-- read" is rejected by Postgres rather than by a taskset, which is where a rule belongs.
--
-- ⛔ AND THE ESTATE SHARES ONE STACK. Everything here is prefixed `cw_` or `clausewatch_`, so it
-- sits beside unemploy's `cd_` tables in the same local Postgres exactly as it sits beside them in
-- production. Nothing in this file drops a schema or a table it does not own.

create extension if not exists pgcrypto;

-- ── tenants ────────────────────────────────────────────────────────────────────────────────────
create table if not exists cw_orgs (
  id                      uuid primary key default gen_random_uuid(),
  name                    text        not null,
  plan                    text        not null default 'free',
  notice_from             text,
  created_at              timestamptz not null default now(),
  demo_seeded_on          date,
  is_demo                 boolean     not null default false,
  stripe_customer_id      text,
  stripe_subscription_id  text,
  -- ⛔ THE PREDICATE IS THE PAIR (plan, billing_status), NEVER `plan` ALONE. lib/entitlement.ts:
  -- `plan` records what was bought and `billing_status` records whether it is still being paid
  -- for, and a cancelled subscription leaves `plan` exactly where it was.
  billing_status          text        not null default 'inactive'
);
create index if not exists cw_orgs_stripe_customer_idx
  on cw_orgs (stripe_customer_id) where stripe_customer_id is not null;
create index if not exists cw_orgs_stripe_subscription_idx
  on cw_orgs (stripe_subscription_id) where stripe_subscription_id is not null;

-- The only thing that turns a signed-in user into an org id. `requireMember()` reads exactly this
-- row and nothing downstream ever takes an org from the client.
create table if not exists cw_members (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid        not null,
  org_id     uuid        not null references cw_orgs(id) on delete cascade,
  email      text        not null,
  role       text        not null default 'owner',
  created_at timestamptz not null default now(),
  unique (user_id, org_id)
);

-- Parked by the Stripe webhook against the address Stripe collected, claimed on the next sign-in.
create table if not exists cw_entitlements (
  id                      uuid primary key default gen_random_uuid(),
  email                   text        not null unique,
  org_id                  uuid        not null references cw_orgs(id) on delete cascade,
  plan                    text        not null,
  billing_status          text        not null default 'active',
  stripe_customer_id      text,
  stripe_subscription_id  text,
  claimed_by              uuid,
  claimed_at              timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);
create index if not exists cw_entitlements_unclaimed_idx
  on cw_entitlements (email) where claimed_by is null;

-- ── the book ───────────────────────────────────────────────────────────────────────────────────
-- `doc_text` and `page_starts` are the system of record, not a cache: every span in cw_clauses,
-- cw_signals and cw_notices.evidence indexes into THIS string. A row whose doc_text is empty
-- cannot have a verifiable quote anywhere downstream.
create table if not exists cw_contracts (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid        not null references cw_orgs(id) on delete cascade,
  title           text        not null,
  counterparty    text,
  source          text        not null default 'upload',
  file_name       text,
  page_count      integer     not null default 0,
  page_starts     integer[]   not null default '{}',
  doc_text        text        not null default '',
  watched         boolean     not null default true,
  uploaded_at     timestamptz not null default now(),
  last_read_at    timestamptz,
  last_state      text,
  term_end        date,
  notice_days     integer,
  auto_renews     boolean,
  notice_deadline date,
  blocked_by      text[]      not null default '{}'
);
-- Oldest read first, so a capped nightly run resumes where the last one stopped.
create index if not exists cw_contracts_org_idx on cw_contracts (org_id, watched, last_read_at);

create table if not exists cw_clauses (
  id               uuid primary key default gen_random_uuid(),
  org_id           uuid        not null references cw_orgs(id) on delete cascade,
  contract_id      uuid        not null references cw_contracts(id) on delete cascade,
  kind             text        not null,
  found            boolean     not null,
  value_json       jsonb,
  span_page        integer,
  span_start       integer,
  span_end         integer,
  quote            text,
  pattern          text,
  not_found_reason text,
  read_at          timestamptz not null default now(),
  unique (contract_id, kind),
  constraint cw_clauses_value_needs_a_span check (
    (found and value_json is not null and quote is not null and span_start is not null)
    or ((not found) and value_json is null and not_found_reason is not null)
  )
);

-- ── the loop ───────────────────────────────────────────────────────────────────────────────────
create table if not exists cw_runs (
  id                uuid primary key default gen_random_uuid(),
  org_id            uuid        not null references cw_orgs(id) on delete cascade,
  today             date        not null,
  started_at        timestamptz not null default now(),
  finished_at       timestamptz,
  contracts_read    integer     not null default 0,
  clauses_read      integer     not null default 0,
  clauses_not_found integer     not null default 0,
  signals_raised    integer     not null default 0,
  notices_queued    integer     not null default 0,
  capped            boolean     not null default false
);
create index if not exists cw_runs_org_idx on cw_runs (org_id, started_at desc);

-- The morning queue. `run_id` deliberately carries no foreign key in production, so it is a plain
-- uuid here too.
create table if not exists cw_signals (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid        not null references cw_orgs(id) on delete cascade,
  contract_id uuid        not null references cw_contracts(id) on delete cascade,
  run_id      uuid,
  kind        text        not null,
  clause_kind text,
  state_from  text,
  state_to    text,
  due_date    date,
  -- ⛔ NULLABLE, AND THAT IS THE WHOLE OF TASK 2. A signal raised because a clause could not be
  -- read has nothing to quote, and `schedule()` refuses to stage a notice without a quote.
  quote       text,
  span_page   integer,
  span_start  integer,
  span_end    integer,
  status      text        not null default 'open',
  raised_at   timestamptz not null default now(),
  resolved_at timestamptz
);
create index if not exists cw_signals_queue_idx on cw_signals (org_id, status, raised_at desc);

-- ── the outbox ─────────────────────────────────────────────────────────────────────────────────
-- `send_after` is not nullable and the dispatcher's own WHERE clause is
-- `state = 'scheduled' and send_after <= now()`, so the kill window is enforced by the query
-- rather than by any caller's `if`. The index below is the one that clause runs on.
create table if not exists cw_notices (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid        not null references cw_orgs(id) on delete cascade,
  contract_id  uuid        not null references cw_contracts(id) on delete cascade,
  signal_id    uuid        references cw_signals(id) on delete set null,
  channel      text        not null default 'email',
  to_addr      text,
  subject      text,
  body         text,
  state        text        not null default 'scheduled',
  send_after   timestamptz not null,
  sent_at      timestamptz,
  cancelled_at timestamptz,
  evidence     jsonb       not null default '{}',
  created_at   timestamptz not null default now()
);
create index if not exists cw_notices_dispatch_idx on cw_notices (state, send_after);

-- ── the record ─────────────────────────────────────────────────────────────────────────────────
-- Every read, raise, approval, dismissal, send and kill. `evidence` carries the quoted span the
-- action was taken on, because a receipt that cannot show the sentence is a log line.
create table if not exists cw_events (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid        not null references cw_orgs(id) on delete cascade,
  contract_id uuid        references cw_contracts(id) on delete cascade,
  signal_id   uuid        references cw_signals(id) on delete set null,
  kind        text        not null,
  title       text        not null,
  detail      text,
  needs_you   boolean     not null default false,
  evidence    jsonb       not null default '{}',
  at          timestamptz not null default now()
);
create index if not exists cw_events_org_idx on cw_events (org_id, at desc);

-- ── the marketing surface ──────────────────────────────────────────────────────────────────────
-- Not part of any task. It is here because it is a live `clausewatch_` table in production and the
-- blog routes read it, so a page render must not 42P01 in the middle of an episode.
create table if not exists clausewatch_posts (
  id           uuid primary key default gen_random_uuid(),
  kind         text        not null,
  slug         text        not null,
  title        text        not null,
  summary      text,
  body_md      text        not null default '',
  tags         text[]      not null default '{}',
  status       text        not null default 'draft',
  published_at timestamptz,
  updated_at   timestamptz not null default now(),
  author       text        not null default 'Isaiah Kim',
  hero_image   text,
  meta         jsonb       not null default '{}'
);

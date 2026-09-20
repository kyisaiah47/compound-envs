-- FetchDue's real tables, pulled out of the live project `xowekqdsttxwbhfxvusa` on 2026-09-19
-- with information_schema.columns, pg_constraint and pg_indexes, and reproduced here.
--
-- THE PREFIX IS `invoices_`, NOT `fetchdue_`, AND THAT IS NOT A MISTAKE. FetchDue was Compound
-- Invoices; the app was renamed and the tables were not, so 23 of the 25 relations it reads are
-- `invoices_*` and only `fetchdue_posts` and `fetchdue_suppressions` carry the product's own name.
-- Several indexes and constraints still carry a THIRD name, `tally_*`, from the generation before
-- that (`tally_invoices_pkey` on `invoices_invoices`). All three names are live in production and
-- all three are reproduced verbatim, because a grader that guessed at a constraint name would be
-- measuring a table this product does not have.
--
-- relkind CHECKED, NOT ASSUMED. All 25 are `r` in production, read the same day. The 2026-09-10
-- rename sweep left VIEWS over older tables behind in at least one sibling product on this stack,
-- and reading a view as a table is how a grader ends up measuring the wrong relation. FetchDue has
-- none: every one of these is an ordinary table.
--
-- RLS is enabled on all 25. Ten of them have NO POLICY AT ALL (conversations, messages,
-- installments, commitments, agent_events, inbound_emails, graph_subscriptions, oauth_tokens,
-- ui_prefs, chase_outcomes), which means an authenticated cookie read returns nothing from any of
-- them. The product knows this and reads through the service role everywhere. src/lib/tenant.ts
-- says so in its own header. The policies are in 03-rls.sql.

create table if not exists public.invoices_users (
  id uuid primary key default gen_random_uuid(),
  auth_user_id text not null unique,
  email text,
  business_name text,
  stripe_customer_id text,
  stripe_subscription_id text,
  subscription_status text default 'trialing',
  voice_profile text,
  workflow_rules jsonb,
  created_at timestamptz default now(),
  onboarding_dismissed_at timestamptz
);

create table if not exists public.invoices_clients (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  email text,
  company text,
  payment_behavior text default 'unknown',
  avg_days_to_pay numeric,
  tone_profile text,
  total_outstanding_cents bigint default 0,
  created_at timestamptz default now(),
  risk_score integer,
  updated_at timestamptz not null default now(),
  phone text,
  external_id text,
  external_source text,
  do_not_chase boolean not null default false
);
create index if not exists tally_clients_user_idx on public.invoices_clients (user_id, created_at desc);
create index if not exists tally_clients_external_idx on public.invoices_clients (user_id, external_source, external_id);

create table if not exists public.invoices_invoices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  client_id uuid not null references public.invoices_clients(id) on delete cascade,
  invoice_number text,
  amount_cents bigint not null,
  issued_date date not null,
  due_date date not null,
  paid_date date,
  status text not null default 'open'
    check (status = any (array['draft','sent','partial','paid','overdue','written_off','open','chased'])),
  external_id text,
  external_source text,
  memo text,
  created_at timestamptz default now(),
  customer_id uuid,
  pay_likelihood integer,
  payment_plan jsonb,
  updated_at timestamptz not null default now(),
  late_fee_cents integer not null default 0,
  late_fee_applied_at timestamptz,
  late_fee_waived boolean not null default false,
  payment_link_url text
);
create index if not exists tally_invoices_user_idx on public.invoices_invoices (user_id, due_date);
create index if not exists tally_invoices_client_idx on public.invoices_invoices (client_id);
create index if not exists tally_invoices_external_idx on public.invoices_invoices (user_id, external_source, external_id);

create table if not exists public.invoices_reminders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  invoice_id uuid not null references public.invoices_invoices(id) on delete cascade,
  client_id uuid not null references public.invoices_clients(id) on delete cascade,
  stage integer not null default 1,
  subject text,
  body text not null,
  tone_notes text,
  status text not null default 'draft'
    check (status = any (array['draft','scheduled','queued','sending','sent','failed','cancelled','paid_after','no_response'])),
  scheduled_for timestamptz,
  sent_at timestamptz,
  created_at timestamptz default now(),
  channel text not null default 'email',
  message_id text,
  graph_conversation_id text,
  graph_message_id text,
  drafted_by text check ((drafted_by is null) or (drafted_by = any (array['agent','template']))),
  draft_reason text
);
create index if not exists tally_reminders_user_idx on public.invoices_reminders (user_id, created_at desc);
create index if not exists tally_reminders_invoice_idx on public.invoices_reminders (invoice_id);

create table if not exists public.invoices_cadence (
  user_id uuid primary key references auth.users(id) on delete cascade,
  default_tone text,
  signoff text,
  stages jsonb not null default '[]'::jsonb,
  plan_rules jsonb not null default '[]'::jsonb,
  updated_at timestamptz default now()
);

create table if not exists public.invoices_voice (
  user_id uuid primary key references auth.users(id) on delete cascade,
  business_name text,
  tone text not null default 'warm-professional',
  formality integer not null default 50,
  warmth integer not null default 60,
  directness integer not null default 50,
  signature text,
  sample_context text,
  updated_at timestamptz not null default now()
);

create table if not exists public.invoices_integrations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,
  connected boolean default false,
  last_synced_at timestamptz,
  config jsonb,
  created_at timestamptz default now(),
  account_label text,
  unique (user_id, provider)
);
create index if not exists tally_integrations_user_idx on public.invoices_integrations (user_id);

-- THE TOKEN STORE. `access_token` and `refresh_token` are ENCRYPTED AT REST by @compound/crypto.
-- This environment seeds every row here with both columns NULL, which is exactly what the OAuth
-- callback wrote a moment before its code exchange, and it is what makes every "no third party was
-- reached" guard a fact rather than a hope.
create table if not exists public.invoices_oauth_tokens (
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,
  access_token text,
  refresh_token text,
  token_expires_at timestamptz,
  account_label text,
  extra jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (user_id, provider)
);

create table if not exists public.invoices_conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  invoice_id uuid references public.invoices_invoices(id) on delete cascade,
  client_id uuid references public.invoices_clients(id) on delete set null,
  state text not null default 'chasing'
    check (state = any (array['chasing','negotiating','committed','broken_promise','final_notice','human_handoff'])),
  graph_conversation_id text,
  last_message_at timestamptz,
  agent_message_count integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);
create unique index if not exists invoices_conversations_user_invoice_key
  on public.invoices_conversations (user_id, invoice_id) where (invoice_id is not null);
create index if not exists invoices_conversations_state_idx on public.invoices_conversations (user_id, state);

create table if not exists public.invoices_messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid not null references public.invoices_conversations(id) on delete cascade,
  invoice_id uuid references public.invoices_invoices(id) on delete cascade,
  client_id uuid references public.invoices_clients(id) on delete set null,
  direction text not null check (direction = any (array['in','out'])),
  channel text not null default 'email',
  subject text,
  body text,
  message_id text,
  in_reply_to text,
  graph_message_id text,
  classified_as text,
  classification_confidence numeric,
  status text not null default 'sent'
    check (status = any (array['sent','scheduled','received','pending_review','discarded','failed'])),
  source_reminder_id uuid unique,
  sent_at timestamptz,
  received_at timestamptz,
  created_at timestamptz not null default now()
);
create unique index if not exists invoices_messages_graph_message_key
  on public.invoices_messages (user_id, graph_message_id);
create index if not exists invoices_messages_status_idx on public.invoices_messages (user_id, status);
create index if not exists invoices_messages_thread_idx
  on public.invoices_messages (user_id, conversation_id, created_at);

create table if not exists public.invoices_installments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  invoice_id uuid not null references public.invoices_invoices(id) on delete cascade,
  conversation_id uuid references public.invoices_conversations(id) on delete set null,
  seq integer not null,
  amount_cents bigint not null,
  due_date date not null,
  status text not null default 'pending'
    check (status = any (array['pending','link_sent','paid','overdue'])),
  stripe_payment_link_url text,
  paid_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (invoice_id, seq)
);
create index if not exists invoices_installments_due_idx on public.invoices_installments (user_id, status, due_date);

create table if not exists public.invoices_commitments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid references public.invoices_conversations(id) on delete cascade,
  invoice_id uuid not null references public.invoices_invoices(id) on delete cascade,
  source_message_id uuid references public.invoices_messages(id) on delete set null,
  amount_cents bigint,
  promised_date date not null,
  status text not null default 'promised'
    check (status = any (array['promised','kept','broken','superseded'])),
  created_at timestamptz not null default now(),
  updated_at timestamptz
);
create index if not exists invoices_commitments_due_idx on public.invoices_commitments (user_id, status, promised_date);

create table if not exists public.invoices_agent_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  run_id uuid,
  kind text not null
    check (kind = any (array['classify','guardrail','draft','chase_sent','chase_held','reply_received','approved','cancelled','failed','payment'])),
  invoice_id uuid,
  message_id uuid,
  reminder_id uuid,
  title text not null,
  detail text,
  evidence jsonb,
  confidence numeric,
  created_at timestamptz not null default now()
);
create index if not exists invoices_agent_events_user_created_idx
  on public.invoices_agent_events (user_id, created_at desc);

create table if not exists public.invoices_late_fee_policy (
  user_id uuid primary key references auth.users(id) on delete cascade,
  enabled boolean not null default false,
  grace_days integer not null default 7,
  mode text not null default 'percent_monthly' check (mode = any (array['percent_monthly','flat'])),
  percent_bp integer not null default 150,
  flat_cents integer not null default 2500,
  max_total_bp integer not null default 1000,
  state_code text,
  apply_to text not null default 'all',
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists public.invoices_inbound_emails (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  graph_message_id text not null,
  internet_message_id text,
  in_reply_to text,
  graph_conversation_id text,
  from_email text,
  subject text,
  body text,
  received_at timestamptz,
  matched_invoice_id uuid,
  matched_via text check (matched_via = any (array['conversation_id','in_reply_to','from_address'])),
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (user_id, graph_message_id)
);

create table if not exists public.invoices_graph_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  subscription_id text,
  resource text not null default '/me/mailfolders(''inbox'')/messages',
  client_state text not null,
  expires_at timestamptz,
  delta_link text,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists public.invoices_user_subscriptions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  tier text not null default 'free',
  stripe_customer_id text,
  stripe_subscription_id text,
  stripe_price_id text,
  status text,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  updated_at timestamptz not null default now()
);

create table if not exists public.invoices_firm_subscriptions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  tier text not null default 'free',
  status text,
  stripe_customer_id text,
  stripe_subscription_id text,
  stripe_price_id text,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  updated_at timestamptz not null default now()
);

create table if not exists public.invoices_firm_clients (
  id uuid primary key default gen_random_uuid(),
  firm_user_id uuid not null references auth.users(id) on delete cascade,
  client_user_id uuid not null unique references auth.users(id) on delete cascade,
  display_name text not null,
  status text not null default 'active' check (status = any (array['active','archived'])),
  created_at timestamptz not null default now(),
  updated_at timestamptz
);
create index if not exists invoices_firm_clients_firm_idx on public.invoices_firm_clients (firm_user_id);

create table if not exists public.invoices_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.invoices_users(id) on delete cascade,
  stripe_subscription_id text,
  plan text,
  status text,
  current_period_end timestamptz,
  created_at timestamptz default now()
);

create table if not exists public.invoices_chase_outcomes (
  id uuid primary key default gen_random_uuid(),
  account_hash text not null,
  invoice_hash text not null,
  amount_band text not null,
  days_overdue_at_chase integer not null,
  stage text not null,
  channel text not null,
  sent_week date not null,
  outcome text not null default 'open' check (outcome = any (array['open','partial','paid'])),
  days_to_payment integer,
  created_at timestamptz not null default now()
);

create table if not exists public.invoices_ui_prefs (
  user_id uuid primary key,
  bookmarks jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.invoices_demo_fixtures (
  key text primary key,
  payload jsonb not null,
  created_at timestamptz default now()
);

create table if not exists public.fetchdue_posts (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind = any (array['blog','changelog'])),
  slug text not null unique,
  title text not null,
  summary text,
  body_md text not null,
  tags text[] not null default '{}'::text[],
  status text not null default 'draft' check (status = any (array['draft','published'])),
  published_at timestamptz,
  updated_at timestamptz not null default now(),
  author text not null default 'Isaiah Kim',
  hero_image text,
  meta jsonb not null default '{}'::jsonb
);
create index if not exists fetchdue_posts_kind_pub
  on public.fetchdue_posts (kind, published_at desc) where (status = 'published');

create table if not exists public.fetchdue_suppressions (
  email text primary key,
  prospect_id text,
  reason text not null default 'unsubscribe_link',
  created_at timestamptz not null default now()
);

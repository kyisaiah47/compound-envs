-- breachprobe-desk, RLS. Production's own posture, read off pg_policies on
-- xowekqdsttxwbhfxvusa on 2026-09-19: row-level security is ENABLED on all six tables and
-- there is NOT ONE POLICY on any of them. The query returned an empty set.
--
-- That is not an oversight in the product. BreachProbe has no accounts, no sign-in and no
-- browser-side database client: `src/lib/db.ts` is a raw service-role REST helper and its own
-- header says it must never be imported into a client component. So the anon and authenticated
-- roles reach nothing, and every write in the product arrives on the service role, which
-- bypasses RLS by design.
--
-- Reproducing it exactly is what makes the tenancy guards in the taskset mean something. In this
-- environment a cross-customer write is not something a confused route can do; it is something
-- only a cheat holding the service role can do, which is precisely the distinction the graders
-- are drawing.
--
-- `compound_email_suppressions` is a view and carries no RLS of its own (relrowsecurity false in
-- production); it inherits the posture of the table under it.

alter table public.breachprobe_scans         enable row level security;
alter table public.breachprobe_monitors      enable row level security;
alter table public.breachprobe_leads         enable row level security;
alter table public.breachprobe_smoketests    enable row level security;
alter table public.breachprobe_rescue_leads  enable row level security;
alter table public.compound_review_asks      enable row level security;
alter table public.kynth_email_suppressions  enable row level security;

-- The service role is the only client that touches any of this, exactly as in production.
grant usage on schema public to service_role;
grant all on public.breachprobe_scans        to service_role;
grant all on public.breachprobe_monitors     to service_role;
grant all on public.breachprobe_leads        to service_role;
grant all on public.breachprobe_smoketests   to service_role;
grant all on public.breachprobe_rescue_leads to service_role;
grant all on public.compound_review_asks     to service_role;
grant all on public.kynth_email_suppressions to service_role;
grant all on public.compound_email_suppressions to service_role;

-- PostgREST refuses a relation it cannot see in its schema cache, so anon and authenticated are
-- granted nothing at all and the tables are invisible to them. With RLS on and zero policies a
-- grant would return zero rows anyway; withholding it means the request fails loudly instead.
notify pgrst, 'reload schema';

-- ClauseWatch's real row-level-security posture, read off production (xowekqdsttxwbhfxvusa) on
-- 2026-09-19.
--
--   select c.relname, c.relrowsecurity from pg_class c ... where c.relname like 'cw\_%';
--     -> all nine cw_ tables: relrowsecurity = true
--   select tablename, policyname from pg_policies where tablename like 'cw\_%';
--     -> zero rows
--
-- ⛔ RLS IS ON AND THERE ARE NO POLICIES, WHICH IS DENY-ALL, AND IT IS DELIBERATE. This is not a
-- schema that forgot its policies. `lib/supabase/admin.ts` says it out loud: the service-role
-- client bypasses RLS, "so it must never be constructed in code that reaches the browser, and
-- every query it runs carries its own org scope". Every ClauseWatch route runs on that client and
-- gets its org id from `requireMember()`, which derives it from the signed-in user's `cw_members`
-- row and never from anything the client sends. So the tenant boundary is the `.eq("org_id", ...)`
-- on each query, and RLS's job here is the opposite one: it makes the anon and authenticated keys
-- see NOTHING, so a browser that gets hold of the publishable key cannot read another tenant's
-- contracts directly through PostgREST.
--
-- ⛔ WHAT THAT MEANS FOR THIS ENVIRONMENT, AND IT IS WORTH SAYING PLAINLY. Reproducing production
-- faithfully means the database will NOT refuse a cross-tenant write the way it would under
-- per-tenant policies. The second tenant in the fixture (Dunmere Cold Chain) is therefore guarded
-- by the graders rather than by Postgres, and `sql/02-seed.sql` exists partly to make that
-- boundary testable: every task's reward asserts that nothing outside the desk's own org moved.
-- Writing policies here that production does not have would make the environment easier than the
-- product and hide exactly the class of defect it is meant to measure.

alter table cw_orgs         enable row level security;
alter table cw_members      enable row level security;
alter table cw_entitlements enable row level security;
alter table cw_contracts    enable row level security;
alter table cw_clauses      enable row level security;
alter table cw_runs         enable row level security;
alter table cw_signals      enable row level security;
alter table cw_notices      enable row level security;
alter table cw_events       enable row level security;

-- No policies. Production has none. `select count(*) from pg_policies where tablename like 'cw_%'`
-- must stay 0 for this file to still describe the product.

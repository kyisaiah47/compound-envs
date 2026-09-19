-- Row level security, exactly as production has it.
--
-- Measured on the live project on 2026-09-19:
--
--   select tablename, policyname from pg_policies
--   where schemaname='public' and tablename like 'cc\_%';   ->  0 rows
--
--   select relname, relrowsecurity from pg_class ...        ->  all 13 tables, relrowsecurity = t
--
-- ⛔ RLS ON AND NO POLICIES IS NOT AN OVERSIGHT HERE, AND REPRODUCING IT IS THE POINT. A table in
-- that state answers the anon and authenticated roles with nothing at all: no select, no insert,
-- no update, no delete. Only a role with BYPASSRLS gets through, and that is `service_role`.
--
-- That is the whole of CoverCheck's data layer. Every read and every write in the product runs on
-- the service-role client in src/lib/supabase/admin.ts, and the tenant boundary is one function,
-- `requireMember()` in src/lib/auth.ts, which reads cc_members for the signed-in user and hands
-- the route an org id. Nothing the client sends is ever trusted for scope. The comment on
-- adminSupabase() says so: "it must never be constructed in code that reaches the browser and
-- every query it runs must carry its own org scope".
--
-- What that buys an environment: a rollout holding the app's own session cookie CANNOT reach
-- PostgREST and write a row directly. It gets nothing back. So a cheat has to come in through a
-- route, which is what makes the route-level guards in taskset.py meaningful rather than
-- decorative. It also means the graders own every cross-org assertion themselves, because the
-- database will not refuse a service-role write into the wrong org. Those assertions are written
-- out longhand in taskset.py for that reason.

alter table cc_orgs                 enable row level security;
alter table cc_members              enable row level security;
alter table cc_communities          enable row level security;
alter table cc_requirement_profiles enable row level security;
alter table cc_vendors              enable row level security;
alter table cc_vendor_communities   enable row level security;
alter table cc_cois                 enable row level security;
alter table cc_coi_extractions      enable row level security;
alter table cc_checks               enable row level security;
alter table cc_chase_threads        enable row level security;
alter table cc_chase_messages       enable row level security;
alter table cc_events               enable row level security;
alter table cc_waitlist             enable row level security;

-- The certificate bucket carries no storage policies either (pg_policies on storage.objects
-- returns nothing naming covercheck-cois, measured the same day). `ingestCoi` uploads with the
-- service-role client and the console never fetches an object in the browser.

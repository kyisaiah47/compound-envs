-- stacktab-desk: the product's real RLS, pulled from pg_policies on xowekqdsttxwbhfxvusa
-- 2026-09-19. Five tables, row level security on all five, and FOUR policies. Every one of them
-- is a read.
--
-- ⛔ `stacktab_price_watch` HAS RLS ENABLED AND NO POLICY AT ALL, WHICH IS THE CORRECT SHAPE AND
-- IS LOAD-BEARING HERE. anon and authenticated can neither read nor write the watch list; only
-- the service role, which bypasses RLS, can touch it. That is why POST /api/watch is the one
-- route in this product that reads SUPABASE_SERVICE_ROLE_KEY, why src/lib/catalogue.ts says in
-- its own header that the service key never reaches the web app, and why a browser holding the
-- publishable key cannot enumerate other people's addresses.
--
-- It also means the anon key cannot verify this environment's own writes. The graders connect to
-- Postgres directly (stacktab_desk/db.py), which is rule 3 anyway.
--
-- The catalogue is world-readable on purpose: every price page is statically generated from it
-- and the figures are published.

alter table public.stacktab_service     enable row level security;
alter table public.stacktab_plan        enable row level security;
alter table public.stacktab_meter       enable row level security;
alter table public.stacktab_refresh_run enable row level security;
alter table public.stacktab_price_watch enable row level security;

drop policy if exists stacktab_service_read on public.stacktab_service;
create policy stacktab_service_read on public.stacktab_service
  for select to anon, authenticated using (true);

drop policy if exists stacktab_plan_read on public.stacktab_plan;
create policy stacktab_plan_read on public.stacktab_plan
  for select to anon, authenticated using (true);

drop policy if exists stacktab_meter_read on public.stacktab_meter;
create policy stacktab_meter_read on public.stacktab_meter
  for select to anon, authenticated using (true);

drop policy if exists stacktab_refresh_read on public.stacktab_refresh_run;
create policy stacktab_refresh_read on public.stacktab_refresh_run
  for select to anon, authenticated using (true);

-- No policy on stacktab_price_watch. Deliberate, and it is what production has.

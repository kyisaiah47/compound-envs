-- matchline-desk: the product's real RLS, read off production on 2026-09-19.
--
-- ⛔ THE ANSWER IS "RLS ON, ZERO POLICIES", AND THAT IS NOT AN OMISSION.
--
--     select tablename, policyname, cmd, roles, qual, with_check
--     from pg_policies where schemaname='public' and tablename like 'ml\_%';
--     -> []
--
--     select c.relname, c.relrowsecurity from pg_class c ... where relname like 'ml\_%';
--     -> ml_matches  t
--        ml_orders   t
--
-- Postgres denies everything a policy does not permit, so a table with RLS enabled and no
-- policies is readable and writable by NOBODY except the roles that bypass RLS. That is the
-- product's whole tenancy model and src/lib/supabase.ts states it in its own header: "there are
-- no anon policies on any ml_ table, so in practice every read that matters also runs
-- server-side with the service client. Writes always use the service client: a resume is
-- personal data and no anon key ever touches it."
--
-- What it buys this environment is real, and it is the reason this file is applied rather than
-- skipped: with it, the publishable key that the BROWSER holds cannot read one row of anybody's
-- resume or posting text, no matter what the page asks for. Without it every visitor to the
-- console could enumerate ml_matches from the devtools console. A rollout that tries is refused
-- by the database exactly as production refuses it, instead of by a grader noticing afterwards.
--
-- The graders connect as `postgres`, which bypasses RLS. That is deliberate and is the same
-- shape every other environment on this stack uses: the grader is not a tenant, it is the
-- auditor, and the thing it audits is what the product's own service-key writes left behind.

alter table public.ml_matches enable row level security;
alter table public.ml_orders  enable row level security;

-- Belt and braces on the shared stack: an earlier environment, or a stray `supabase db reset`,
-- can leave a permissive policy behind on a table name it never owned. Drop anything on these
-- two so "zero policies" is a fact this file establishes rather than one it hopes for.
do $$
declare p record;
begin
  for p in
    select policyname, tablename from pg_policies
    where schemaname = 'public' and tablename in ('ml_matches', 'ml_orders')
  loop
    execute format('drop policy %I on public.%I', p.policyname, p.tablename);
  end loop;
end $$;

-- The storage side. ml-files is a private bucket with no storage.objects policy of its own
-- upstream either, so the same rule holds there: only a service-key caller can read, write or
-- remove an object, which is what src/app/api/delete/route.ts does.
do $$
declare p record;
begin
  for p in
    select policyname from pg_policies
    where schemaname = 'storage' and tablename = 'objects'
      and policyname like 'ml_files_%'
  loop
    execute format('drop policy %I on storage.objects', p.policyname);
  end loop;
end $$;

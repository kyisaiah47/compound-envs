-- Row level security, read out of the live project on 2026-09-19 with pg_policies.
--
-- ⛔ WHY AN ENVIRONMENT NEEDS THIS AT ALL. Without RLS every grader's owner check is enforced
-- only by the grader. With it, the database refuses a cross-account write before the grader ever
-- runs, which is how production behaves, so a rollout that scores zero here scores zero for the
-- same reason it would have failed a real customer's account.
--
-- ⛔ AND IT IS NOT WHAT STOPS THE APP. Every route in this product writes through
-- `adminSupabase()`, the service-role client, which bypasses RLS entirely and hand-writes
-- `.eq("user_id", uid)` on every query. RLS here is the floor under a rollout that reaches for
-- the anon or authenticated key directly, which is exactly what one of the cheats does.
--
-- CardChase's model is one owner per book: every cardchase_* table carrying user_id takes the
-- same single ALL policy, `user_id = auth.uid()`. There is no tenant, no org, no seat and no
-- membership table anywhere in the repo, so there is no helper function to reproduce either.
-- Two tables differ and both differences are live:
--   cardchase_subscriptions  SELECT only. The owner reads their plan; only the Stripe webhook,
--                            on the service role, writes it.
--   cardchase_posts          public read of published rows, for the marketing blog.
-- cardchase_demo_seed carries no policy at all on the live project and none is invented here.

do $$
declare tbl text;
begin
  foreach tbl in array array[
    'cardchase_customers', 'cardchase_events', 'cardchase_failures', 'cardchase_integrations',
    'cardchase_ladder', 'cardchase_messages', 'cardchase_retries', 'cardchase_voice',
    'cardchase_workspace_keys'
  ] loop
    execute format('alter table public.%I enable row level security', tbl);
    -- Dropped first so the whole file is idempotent. `up.sh` re-applies it on every bring-up,
    -- and a create that throws on the second run turns into a `|| true` in the caller, which is
    -- how a failed re-apply becomes invisible.
    execute format('drop policy if exists %I on public.%I', tbl || '_owner', tbl);
    execute format(
      'create policy %I on public.%I for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())',
      tbl || '_owner', tbl);
  end loop;
end $$;

alter table public.cardchase_subscriptions enable row level security;
drop policy if exists cardchase_subscriptions_owner_read on public.cardchase_subscriptions;
create policy cardchase_subscriptions_owner_read on public.cardchase_subscriptions
  for select to authenticated using (user_id = auth.uid());

alter table public.cardchase_posts enable row level security;
drop policy if exists cardchase_posts_public_read on public.cardchase_posts;
create policy cardchase_posts_public_read on public.cardchase_posts
  for select to anon, authenticated using (status = 'published');

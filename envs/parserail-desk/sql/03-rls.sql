-- parserail-desk: the product's real RLS posture, read off production on 2026-09-19.
--
-- ⛔ RLS IS ON AND THERE IS NOT ONE POLICY. `select tablename, policyname from pg_policies where
-- tablename like 'kynth\_%'` returns zero rows against the live project, while
-- pg_class.relrowsecurity is true on all seven tables. That is deliberate and it is the whole
-- security model of this product: the only client that ever touches these tables is
-- `adminSupabase()`, the service-role client, which bypasses RLS. Nothing signed in as `anon` or
-- `authenticated` can read or write a row, so a stolen anon key buys a reader nothing.
--
-- Reproducing it matters here because it is what makes the tenancy guards real rather than
-- decorative. Every route already scopes its own query (`.eq("account_id", user.id)` on revoke,
-- `.eq("account_id", auth.accountId)` on memory forget, `getJob(id, accountId)` on job polling),
-- and with RLS shut the database is the second wall: a cross-tenant write in this environment is
-- something only a cheat holding the service role can do, which is exactly the shape of the
-- cross-tenant cheats in prove_graders.py.

alter table public.kynth_credit_accounts  enable row level security;
alter table public.kynth_api_keys          enable row level security;
alter table public.kynth_usage_events      enable row level security;
alter table public.kynth_credit_ledger     enable row level security;
alter table public.kynth_api_jobs          enable row level security;
alter table public.kynth_agent_memories    enable row level security;
alter table public.kynth_rate_limits       enable row level security;
alter table public.all_access_user_subscriptions enable row level security;

-- The views inherit their base table's RLS (they run with the invoker's rights, and none of
-- them is security_definer), so anon/authenticated reach nothing through the shim either.
-- Grants still have to exist or PostgREST answers 404 rather than an empty set, which is what
-- production serves: the service role is granted everything, the two public roles nothing.
grant all on public.kynth_credit_accounts, public.kynth_api_keys, public.kynth_usage_events,
              public.kynth_credit_ledger, public.kynth_api_jobs, public.kynth_agent_memories,
              public.kynth_rate_limits, public.all_access_user_subscriptions
  to service_role;
grant all on public.compound_credit_accounts, public.compound_api_keys, public.compound_usage_events,
              public.compound_credit_ledger, public.compound_api_jobs, public.compound_agent_memories,
              public.compound_rate_limits
  to service_role;

revoke all on public.kynth_credit_accounts, public.kynth_api_keys, public.kynth_usage_events,
               public.kynth_credit_ledger, public.kynth_api_jobs, public.kynth_agent_memories,
               public.kynth_rate_limits, public.all_access_user_subscriptions
  from anon, authenticated;
revoke all on public.compound_credit_accounts, public.compound_api_keys, public.compound_usage_events,
               public.compound_credit_ledger, public.compound_api_jobs, public.compound_agent_memories,
               public.compound_rate_limits
  from anon, authenticated;

-- The RPCs are SECURITY DEFINER where production has them so, and executable by the service role
-- only. compound_credits_charge and compound_credits_grant are plain SQL wrappers in production
-- too: they are not definers themselves, they call a definer.
revoke execute on function public.kynth_credits_charge(uuid, integer, text, uuid, integer, text, text, jsonb) from anon, authenticated;
revoke execute on function public.kynth_credits_grant(uuid, integer, text, text) from anon, authenticated;
revoke execute on function public.compound_credits_charge(uuid, integer, text, uuid, integer, text, text, jsonb) from anon, authenticated;
revoke execute on function public.compound_credits_grant(uuid, integer, text, text) from anon, authenticated;
grant execute on function public.compound_rate_limit_hit(text, integer, integer) to service_role;
grant execute on function public.compound_credits_charge(uuid, integer, text, uuid, integer, text, text, jsonb) to service_role;
grant execute on function public.compound_credits_grant(uuid, integer, text, text) to service_role;
grant execute on function public.compound_memory_search(uuid, text, vector, integer) to service_role;

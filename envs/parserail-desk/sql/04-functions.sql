-- parserail-desk: the RPCs the product calls, copied verbatim from production
-- (pg_get_functiondef on xowekqdsttxwbhfxvusa, 2026-09-19).
--
-- Same shim shape as the tables: the work is in kynth_*, and every name the app says is a thin
-- SQL wrapper. compound_credits_charge is the one function this environment's graders lean on
-- hardest, because it is the single place a billed call decrements the wallet, writes the usage
-- event and writes the ledger row, all in one transaction. A cheat that fakes any one of those
-- three without the other two is exactly what the memory task's guards are looking for.

create or replace function public.kynth_rate_limit_hit(p_key text, p_limit integer, p_window_sec integer)
returns table(allowed boolean, remaining integer, retry_after integer)
language plpgsql security definer set search_path to 'public'
as $function$
declare
  v_now          bigint := floor(extract(epoch from now()));
  v_window_start bigint := (v_now / p_window_sec) * p_window_sec;
  v_bucket       text   := p_key || '|' || v_window_start;
  v_count        int;
begin
  insert into public.kynth_rate_limits (bucket_key, count, expires_at)
  values (v_bucket, 1, to_timestamp(v_window_start + p_window_sec))
  on conflict (bucket_key)
    do update set count = public.kynth_rate_limits.count + 1
  returning count into v_count;

  return query select
    v_count <= p_limit,
    greatest(p_limit - v_count, 0),
    case when v_count <= p_limit then 0
         else (v_window_start + p_window_sec - v_now)::int end;
end;
$function$;

create or replace function public.kynth_credits_charge(
  p_account uuid, p_credits integer, p_endpoint text, p_key_id uuid default null::uuid,
  p_units integer default 1, p_model text default null::text, p_request_id text default null::text,
  p_meta jsonb default '{}'::jsonb)
returns table(ok boolean, remaining integer)
language plpgsql security definer set search_path to 'public'
as $function$
declare
  v_balance int;
  v_event   uuid;
begin
  select balance_credits into v_balance
    from public.kynth_credit_accounts
    where account_id = p_account
    for update;

  if v_balance is null then
    return query select false, 0;
    return;
  end if;
  if v_balance < p_credits then
    return query select false, v_balance;
    return;
  end if;

  update public.kynth_credit_accounts
    set balance_credits = balance_credits - p_credits, updated_at = now()
    where account_id = p_account
    returning balance_credits into v_balance;

  insert into public.kynth_usage_events
    (account_id, api_key_id, endpoint, units, credits_burned, request_id, model, meta)
    values (p_account, p_key_id, p_endpoint, p_units, p_credits, p_request_id, p_model, coalesce(p_meta, '{}'::jsonb))
    returning id into v_event;

  insert into public.kynth_credit_ledger
    (account_id, delta, reason, balance_after, ref)
    values (p_account, -p_credits, 'usage:' || p_endpoint, v_balance, v_event::text);

  return query select true, v_balance;
end;
$function$;

create or replace function public.kynth_credits_grant(
  p_account uuid, p_credits integer, p_reason text, p_ref text default null::text)
returns table(ok boolean, remaining integer)
language plpgsql security definer set search_path to 'public'
as $function$
declare
  v_balance int;
  v_first   boolean;
begin
  insert into public.kynth_credit_accounts (account_id, balance_credits)
    values (p_account, 0)
    on conflict (account_id) do nothing;

  if p_ref is not null and exists (
    select 1 from public.kynth_credit_ledger where ref = p_ref and reason = p_reason
  ) then
    select balance_credits into v_balance from public.kynth_credit_accounts where account_id = p_account;
    return query select false, coalesce(v_balance, 0);
    return;
  end if;

  if p_reason = 'signup_grant' then
    select not free_grant_used into v_first
      from public.kynth_credit_accounts where account_id = p_account for update;
    if not coalesce(v_first, false) then
      select balance_credits into v_balance from public.kynth_credit_accounts where account_id = p_account;
      return query select false, coalesce(v_balance, 0);
      return;
    end if;
    update public.kynth_credit_accounts set free_grant_used = true where account_id = p_account;
  end if;

  update public.kynth_credit_accounts
    set balance_credits = balance_credits + p_credits, updated_at = now()
    where account_id = p_account
    returning balance_credits into v_balance;

  insert into public.kynth_credit_ledger (account_id, delta, reason, balance_after, ref)
    values (p_account, p_credits, p_reason, v_balance, p_ref);

  return query select true, v_balance;
end;
$function$;

create or replace function public.kynth_memory_search(
  p_account uuid, p_namespace text, p_embedding vector, p_limit integer)
returns table(id uuid, content text, metadata jsonb, created_at timestamptz, score double precision)
language sql security definer set search_path to 'public'
as $function$
  select m.id, m.content, m.metadata, m.created_at,
         1 - (m.embedding <=> p_embedding) as score
  from public.kynth_agent_memories m
  where m.account_id = p_account and m.namespace = p_namespace
  order by m.embedding <=> p_embedding
  limit greatest(1, least(p_limit, 25));
$function$;

create or replace function public.kynth_credits_monthly_refresh(p_floor integer)
returns table(refreshed integer)
language plpgsql security definer set search_path to 'public'
as $function$
declare
  v_count int;
begin
  with due as (
    select account_id, balance_credits
    from public.kynth_credit_accounts
    where balance_credits < p_floor
      and (last_free_grant_at is null
           or date_trunc('month', last_free_grant_at) < date_trunc('month', now()))
    for update
  ), upd as (
    update public.kynth_credit_accounts a
      set balance_credits = p_floor,
          last_free_grant_at = now(),
          updated_at = now()
      from due d
      where a.account_id = d.account_id
      returning a.account_id, p_floor - d.balance_credits as delta, a.balance_credits as after
  )
  insert into public.kynth_credit_ledger (account_id, delta, reason, balance_after, ref)
    select account_id, delta, 'monthly_free', after,
           'monthly_free:' || to_char(now(), 'YYYY-MM') || ':' || account_id
    from upd;

  get diagnostics v_count = row_count;
  return query select v_count;
end;
$function$;

-- the compound_* wrappers, the names the app actually calls ------------------------------

create or replace function public.compound_rate_limit_hit(p_key text, p_limit integer, p_window_sec integer)
returns table(allowed boolean, remaining integer, retry_after integer)
language sql security definer set search_path to 'public'
as $function$ select * from public.kynth_rate_limit_hit(p_key, p_limit, p_window_sec) $function$;

create or replace function public.compound_credits_charge(
  p_account uuid, p_credits integer, p_endpoint text, p_key_id uuid, p_units integer,
  p_model text, p_request_id text, p_meta jsonb)
returns table(ok boolean, remaining integer)
language sql set search_path to 'public'
as $function$ select * from public.kynth_credits_charge(p_account, p_credits, p_endpoint, p_key_id, p_units, p_model, p_request_id, p_meta) $function$;

create or replace function public.compound_credits_grant(
  p_account uuid, p_credits integer, p_reason text, p_ref text)
returns table(ok boolean, remaining integer)
language sql set search_path to 'public'
as $function$ select * from public.kynth_credits_grant(p_account, p_credits, p_reason, p_ref) $function$;

create or replace function public.compound_memory_search(
  p_account uuid, p_namespace text, p_embedding vector, p_limit integer)
returns table(id uuid, content text, metadata jsonb, created_at timestamptz, score double precision)
language sql set search_path to 'public'
as $function$ select * from public.kynth_memory_search(p_account, p_namespace, p_embedding, p_limit) $function$;

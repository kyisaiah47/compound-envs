-- The estate's auth telemetry, so the app's sign-in path behaves the way it does in production.
--
-- ⛔ WHY THIS IS HERE AT ALL. Without it every sign-in logged
-- `[auth-events] 404 PGRST202 Searched for the function public.record_auth_event`, because
-- `src/lib/auth-events.ts` calls that RPC on the way through /auth/callback. The call is
-- telemetry and the tasks do not depend on it, so the environment worked anyway. It is still
-- wrong: a run that prints a 404 on a path the graders do not read teaches whoever is debugging
-- the environment to scroll past 404s, and the next one will matter.
--
-- Read out of the live project on 2026-09-19: the two table shapes with
-- information_schema.columns, the function with pg_get_functiondef, reproduced verbatim.

create table if not exists public.auth_events (
  id          bigint generated always as identity primary key,
  user_id     uuid not null,
  app         text not null,
  host        text,
  event       text not null,
  provider    text,
  is_internal boolean not null default false,
  user_agent  text,
  referrer    text,
  created_at  timestamptz not null default now()
);

-- The function's signup branch reads "no signup row exists for this user yet", so the uniqueness
-- it relies on is declared rather than assumed.
create unique index if not exists auth_events_one_signup
  on public.auth_events (user_id) where event = 'signup';
create index if not exists auth_events_user_app on public.auth_events (user_id, app, event, created_at desc);

create table if not exists public.internal_accounts (
  user_id    uuid primary key,
  role       text not null,
  label      text,
  note       text,
  created_at timestamptz not null default now()
);

create or replace function public.record_auth_event(
  p_user_id uuid,
  p_app text,
  p_host text default null::text,
  p_provider text default null::text,
  p_user_agent text default null::text,
  p_referrer text default null::text,
  p_demo boolean default false)
 returns text
 language plpgsql
 security definer
 set search_path to 'public', 'auth'
as $function$
declare
  v_created  timestamptz;
  v_event    text;
  v_internal boolean;
begin
  if p_user_id is null or coalesce(p_app, '') = '' then
    return 'skipped:bad_args';
  end if;

  select created_at into v_created from auth.users where id = p_user_id;
  if v_created is null then
    return 'skipped:unknown_user';
  end if;

  v_internal := p_demo or exists (
    select 1 from public.internal_accounts ia where ia.user_id = p_user_id
  );

  if p_demo then
    v_event := 'demo';
  elsif now() - v_created < interval '5 minutes'
        and not exists (
          select 1 from public.auth_events e
          where e.user_id = p_user_id and e.event = 'signup'
        )
  then
    v_event := 'signup';
  else
    v_event := 'signin';
  end if;

  -- Collapse refresh storms: the same person re-entering the same app within
  -- half an hour is one visit, not many. Signups are already unique-indexed.
  if v_event <> 'signup' and exists (
    select 1 from public.auth_events e
    where e.user_id = p_user_id
      and e.app     = p_app
      and e.event   = v_event
      and e.created_at > now() - interval '30 minutes'
  ) then
    return v_event || ':deduped';
  end if;

  insert into public.auth_events (user_id, app, host, event, provider, is_internal, user_agent, referrer)
  values (p_user_id, p_app, p_host, v_event, p_provider, v_internal, p_user_agent, p_referrer)
  on conflict do nothing;

  return v_event;
end;
$function$;

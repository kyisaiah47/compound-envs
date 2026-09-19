-- Row level security, the storage bucket and its policies.
--
-- Read out of the live project on 2026-09-19 with pg_policies and pg_get_functiondef. The three
-- helper functions are reproduced verbatim, including the `demo@kynth.studio` literal, which is
-- the old studio domain and is what the deployed function still says.
--
-- ⛔ WHY AN ENVIRONMENT NEEDS THIS AT ALL. Without RLS every grader's tenant check is enforced
-- only by the grader. With it, the database refuses a cross-tenant write before the grader ever
-- runs, which is how production behaves, so a rollout that scores zero here scores zero for the
-- same reason it would have failed a real customer's account.

create or replace function public.cd_member_tenant_ids()
 returns setof uuid
 language sql
 stable security definer
 set search_path to 'public'
as $function$
  select u.tenant_id from public.cd_users u where u.user_id = auth.uid()
$function$;

create or replace function public.cd_writable_tenant_ids()
 returns setof uuid
 language sql
 stable security definer
 set search_path to 'public'
as $function$
  select u.tenant_id
  from public.cd_users u
  join public.cd_tenants n on n.id = u.tenant_id
  where u.user_id = auth.uid()
    and n.is_demo = false
    and coalesce(auth.jwt() ->> 'email', '') <> 'demo@kynth.studio'
$function$;

create or replace function public.cd_can_write(t uuid)
 returns boolean
 language sql
 stable security definer
 set search_path to 'public'
as $function$
  select exists (
    select 1
    from public.cd_users u
    join public.cd_tenants n on n.id = u.tenant_id
    where u.user_id = auth.uid()
      and u.tenant_id = t
      and n.is_demo = false
      and coalesce(auth.jwt() ->> 'email', '') <> 'demo@kynth.studio'
  )
$function$;

-- The eleven tables carrying tenant_id all take the same four policies, so they are applied in a
-- loop rather than written out eleven times: a hand-copied set is where one table quietly ends up
-- readable by everybody.
do $$
declare tbl text;
begin
  foreach tbl in array array[
    'cd_claims', 'cd_determinations', 'cd_documents', 'cd_drafts', 'cd_fact_answers',
    'cd_fact_requests', 'cd_facts', 'cd_hearings', 'cd_notices', 'cd_statements'
  ] loop
    execute format('alter table public.%I enable row level security', tbl);
    execute format(
      'create policy %I on public.%I for select to authenticated using (tenant_id in (select cd_member_tenant_ids()))',
      tbl || '_read', tbl);
    execute format(
      'create policy %I on public.%I for insert to authenticated with check (cd_can_write(tenant_id))',
      tbl || '_write', tbl);
    execute format(
      'create policy %I on public.%I for update to authenticated using (cd_can_write(tenant_id)) with check (cd_can_write(tenant_id))',
      tbl || '_update', tbl);
    execute format(
      'create policy %I on public.%I for delete to authenticated using (cd_can_write(tenant_id))',
      tbl || '_delete', tbl);
  end loop;
end $$;

-- cd_tenants keys on id rather than tenant_id, and neither it nor cd_users takes a write policy
-- in production: a member row is written by the service role during bootstrap and never by the
-- person signing in.
alter table public.cd_tenants enable row level security;
create policy cd_tenants_read on public.cd_tenants
  for select to authenticated using (id in (select cd_member_tenant_ids()));

alter table public.cd_users enable row level security;
create policy cd_users_read on public.cd_users
  for select to authenticated using (tenant_id in (select cd_member_tenant_ids()));

-- The bucket the app uploads into, and the three policies that decide who may touch a path.
-- The first path segment is the tenant id, which is what every policy matches on.
insert into storage.buckets (id, name, public)
values ('unemploy-documents', 'unemploy-documents', false)
on conflict (id) do nothing;

drop policy if exists unemploy_documents_tenant_read on storage.objects;
drop policy if exists unemploy_documents_tenant_insert on storage.objects;
drop policy if exists unemploy_documents_tenant_delete on storage.objects;

create policy unemploy_documents_tenant_read on storage.objects
  for select to authenticated
  using (bucket_id = 'unemploy-documents'
         and (storage.foldername(name))[1] in (select (t.t)::text from cd_member_tenant_ids() t(t)));

create policy unemploy_documents_tenant_insert on storage.objects
  for insert to authenticated
  with check (bucket_id = 'unemploy-documents'
              and (storage.foldername(name))[1] in (select (t.t)::text from cd_writable_tenant_ids() t(t)));

create policy unemploy_documents_tenant_delete on storage.objects
  for delete to authenticated
  using (bucket_id = 'unemploy-documents'
         and (storage.foldername(name))[1] in (select (t.t)::text from cd_writable_tenant_ids() t(t)));

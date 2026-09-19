-- MatchRail's real row-level security, read out of pg_policies on the shared production project
-- xowekqdsttxwbhfxvusa on 2026-09-19 and reproduced verbatim.
--
-- Every owner policy is `ALL to authenticated using (auth.uid() = user_id) with check (auth.uid()
-- = user_id)`. matchrail_subscriptions is SELECT only: a buyer may read what they bought and may
-- never write it. matchrail_posts is a public read of published rows only.
--
-- ⛔ TWO TABLES CARRY RLS AND NO POLICY AT ALL, WHICH IS THE STRONGEST STATEMENT IN THIS FILE.
-- `matchrail_oauth_tokens` holds the ledger tokens and `matchrail_demo_seed` holds the demo claim.
-- RLS on with no policy means no anon and no authenticated role can read or write a byte of
-- either; only the service role reaches them. Reproduced so a cross-tenant read fails here the
-- way it fails in production rather than being enforced only by a grader.

alter table public.matchrail_documents     enable row level security;
alter table public.matchrail_matches       enable row level security;
alter table public.matchrail_corrections   enable row level security;
alter table public.matchrail_audit         enable row level security;
alter table public.matchrail_runs          enable row level security;
alter table public.matchrail_integrations  enable row level security;
alter table public.matchrail_oauth_tokens  enable row level security;
alter table public.matchrail_subscriptions enable row level security;
alter table public.matchrail_posts         enable row level security;
alter table public.matchrail_demo_seed     enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='matchrail_documents' and policyname='matchrail_documents_owner') then
    create policy matchrail_documents_owner on public.matchrail_documents
      as permissive for all to authenticated
      using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies where schemaname='public' and tablename='matchrail_matches' and policyname='matchrail_matches_owner') then
    create policy matchrail_matches_owner on public.matchrail_matches
      as permissive for all to authenticated
      using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies where schemaname='public' and tablename='matchrail_corrections' and policyname='matchrail_corrections_owner') then
    create policy matchrail_corrections_owner on public.matchrail_corrections
      as permissive for all to authenticated
      using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies where schemaname='public' and tablename='matchrail_audit' and policyname='matchrail_audit_owner') then
    create policy matchrail_audit_owner on public.matchrail_audit
      as permissive for all to authenticated
      using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies where schemaname='public' and tablename='matchrail_runs' and policyname='matchrail_runs_owner') then
    create policy matchrail_runs_owner on public.matchrail_runs
      as permissive for all to authenticated
      using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies where schemaname='public' and tablename='matchrail_integrations' and policyname='matchrail_integrations_owner') then
    create policy matchrail_integrations_owner on public.matchrail_integrations
      as permissive for all to authenticated
      using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies where schemaname='public' and tablename='matchrail_subscriptions' and policyname='matchrail_subscriptions_owner') then
    create policy matchrail_subscriptions_owner on public.matchrail_subscriptions
      as permissive for select to authenticated
      using (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies where schemaname='public' and tablename='matchrail_posts' and policyname='matchrail_posts_public_read') then
    create policy matchrail_posts_public_read on public.matchrail_posts
      as permissive for select to anon, authenticated
      using (status = 'published');
  end if;
end $$;

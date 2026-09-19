-- The trigger that makes an account, and the one piece of this product with a branch worth
-- grading.
--
-- Read out of the live project on 2026-09-19 with pg_get_functiondef and pg_get_triggerdef,
-- reproduced verbatim. The function body below is byte-for-byte what
-- public.handle_new_standup_user is deployed as today, comment included.
--
-- WHY IT MATTERS HERE. /upgrade's checkout requires no account and creates none, and
-- standup_profiles.id is a foreign key to auth.users(id). So a buyer who pays before signing up
-- has no row to flip, and src/lib/plan.ts parks the entitlement in standup_pending_members
-- instead. This trigger is the only thing that ever collects it. Nothing else in the product
-- reads that table, so if a rollout gets the account made without the trigger seeing the right
-- address, the buyer stays unentitled and every page still looks exactly the same.

create or replace function public.handle_new_standup_user()
 returns trigger
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
declare
  pending public.standup_pending_members%rowtype;
begin
  select * into pending
  from public.standup_pending_members
  where lower(email) = lower(new.email) and claimed_at is null;

  insert into public.standup_profiles (id, email, plan, stripe_customer_id)
  values (
    new.id,
    new.email,
    coalesce(pending.plan, 'free'),
    pending.stripe_customer_id
  )
  on conflict (id) do nothing;

  -- Marked claimed rather than deleted: a membership that was paid for and then claimed is a
  -- record worth keeping, and it is the only way to tell "never paid" from "paid and collected".
  if pending.email is not null then
    update public.standup_pending_members
    set claimed_at = now(), claimed_by = new.id
    where email = pending.email;
  end if;

  return new;
end;
$function$;

drop trigger if exists on_auth_user_created_standup on auth.users;
create trigger on_auth_user_created_standup
  after insert on auth.users
  for each row execute function public.handle_new_standup_user();

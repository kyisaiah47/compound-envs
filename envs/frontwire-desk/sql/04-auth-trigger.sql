-- frontwire-desk: handle_new_frontwire_user() and its trigger, byte-for-byte what production
-- carries. Read out of pg_proc / pg_trigger in xowekqdsttxwbhfxvusa on 2026-09-19.
--
-- ⛔ WHY IT IS THE LOAD-BEARING PIECE OF THIS ENVIRONMENT. /api/checkout requires no account and
-- creates none, and frontwire_profiles.id is a foreign key to auth.users, so a buyer who pays
-- straight off /upgrade has NO row for the Stripe webhook to flip. setPlanByEmail() used to
-- `return false` there: the webhook answered 200, Stripe took the card, and the buyer got
-- nothing, silently. The entitlement is parked in frontwire_pending_members instead, and THIS
-- trigger is the only thing that ever claims it.
--
-- So two of this environment's tasks exist only because of this function: parking the membership
-- (the webhook's job) and opening the account that claims it (the reader's job). Neither is
-- checkable without it.
--
-- ⛔ IT SITS ON auth.users, WHICH EVERY ENVIRONMENT ON THIS STACK SHARES. That is production's own
-- shape and standup-desk already installs its sibling `on_auth_user_created_standup` on this same
-- local stack, so the precedent and the risk are both already here. The cost of it is one extra
-- frontwire_profiles row whenever another environment creates its fixture user, which is inert:
-- nothing in frontwire reads a profile it did not park a membership for. The cost of NOT having
-- it would be a fixture where the product's only membership path does not exist.

create or replace function public.handle_new_frontwire_user()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  pending public.frontwire_pending_members%rowtype;
begin
  select * into pending
  from public.frontwire_pending_members
  where lower(email) = lower(new.email) and claimed_at is null;

  insert into public.frontwire_profiles (id, email, plan, stripe_customer_id)
  values (
    new.id,
    new.email,
    coalesce(pending.plan, 'free'),
    pending.stripe_customer_id
  )
  on conflict (id) do nothing;

  if pending.email is not null then
    update public.frontwire_pending_members
    set claimed_at = now(), claimed_by = new.id
    where email = pending.email;
  end if;

  return new;
end;
$function$;

drop trigger if exists on_auth_user_created_frontwire on auth.users;
create trigger on_auth_user_created_frontwire
  after insert on auth.users
  for each row execute function public.handle_new_frontwire_user();

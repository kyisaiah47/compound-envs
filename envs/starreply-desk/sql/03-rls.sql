-- starreply's real RLS and its one trigger, read out of the shared production project
-- xowekqdsttxwbhfxvusa on 2026-09-19 (pg_policies, pg_trigger, pg_get_functiondef).
--
-- ⛔ THE POLICIES ARE OWNER-SELECT-ONLY AND THAT IS THE WHOLE SHAPE. Every write in this product
-- goes through the SERVICE ROLE, which bypasses RLS, and every one of those queries filters on
-- user_id in its own SQL (`_lib/db/reads.ts`, `_lib/db/stores.ts`). So RLS here is the second lock
-- on the browser client, not the lock on the routes. A grader that relied on RLS to refuse a
-- cross-tenant write would be grading nothing; the graders read rows instead.
--
-- ⛔ THE TRIGGER IS THE PRODUCT'S ONE DATABASE-LEVEL GUARANTEE. `agent/guardrails.ts` refuses to
-- put a 1-2 star review on the unattended path, `post-reply.ts` re-asserts it on the other door,
-- and this refuses to let the flag be cleared at all. Three places, and this is the one no code
-- path can route around. It is copied verbatim so the environment refuses what production refuses.

alter table starreply_locations           enable row level security;
alter table starreply_reviews             enable row level security;
alter table starreply_replies             enable row level security;
alter table starreply_events              enable row level security;
alter table starreply_settings            enable row level security;
alter table starreply_voice               enable row level security;
alter table starreply_usage               enable row level security;
alter table starreply_subscriptions       enable row level security;
alter table starreply_subscription_claims enable row level security;
alter table starreply_posts               enable row level security;

drop policy if exists starreply_locations_owner_read on starreply_locations;
create policy starreply_locations_owner_read on starreply_locations
  for select using (user_id = (select auth.uid()));

drop policy if exists starreply_reviews_owner_read on starreply_reviews;
create policy starreply_reviews_owner_read on starreply_reviews
  for select using (user_id = (select auth.uid()));

drop policy if exists starreply_replies_owner_read on starreply_replies;
create policy starreply_replies_owner_read on starreply_replies
  for select using (user_id = (select auth.uid()));

drop policy if exists starreply_events_owner_read on starreply_events;
create policy starreply_events_owner_read on starreply_events
  for select using (user_id = (select auth.uid()));

drop policy if exists starreply_settings_owner_read on starreply_settings;
create policy starreply_settings_owner_read on starreply_settings
  for select using (user_id = (select auth.uid()));

drop policy if exists starreply_voice_owner_read on starreply_voice;
create policy starreply_voice_owner_read on starreply_voice
  for select using (user_id = (select auth.uid()));

drop policy if exists starreply_usage_owner_read on starreply_usage;
create policy starreply_usage_owner_read on starreply_usage
  for select using (user_id = (select auth.uid()));

drop policy if exists starreply_subscriptions_owner_read on starreply_subscriptions;
create policy starreply_subscriptions_owner_read on starreply_subscriptions
  for select using (user_id = (select auth.uid()));

-- Keyed on email, not on user_id: a claim is a plan PAID FOR by somebody who does not have an
-- account yet, so there is no owner to compare against until `attachClaim` runs.
drop policy if exists starreply_subscription_claims_owner_read on starreply_subscription_claims;
create policy starreply_subscription_claims_owner_read on starreply_subscription_claims
  for select using (lower(email) = lower((select auth.jwt() ->> 'email')));

drop policy if exists starreply_posts_public_read on starreply_posts;
create policy starreply_posts_public_read on starreply_posts
  for select using (status = 'published');

create or replace function public.starreply_enforce_low_star_approval()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  rating smallint;
begin
  select star_rating into rating from starreply_reviews where id = new.review_id;
  if rating is null then
    raise exception 'starreply: reply % references a review that does not exist', new.review_id;
  end if;
  if rating <= 2 then
    if tg_op = 'UPDATE' and new.approval_required is distinct from true then
      raise exception 'starreply: a % star review is approval-only; approval_required cannot be cleared', rating;
    end if;
    new.approval_required := true;
  end if;
  new.updated_at := now();
  return new;
end;
$function$;

drop trigger if exists starreply_replies_low_star on starreply_replies;
create trigger starreply_replies_low_star
  before insert or update on public.starreply_replies
  for each row execute function starreply_enforce_low_star_approval();

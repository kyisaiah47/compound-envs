-- outrip's real RLS, read off production (pg_policies, pg_class.relrowsecurity) on 2026-09-19.
--
-- The shape is unusual and it is the point: RLS is ON for every table and there are SELECT
-- policies only. There is not one INSERT, UPDATE or DELETE policy anywhere in the product, so
-- the publishable key can read the board and can write NOTHING. Every write in outrip runs in
-- a server route under the service key, because the write IS the thing being paid for
-- (src/lib/supabase.ts).
--
-- Four tables carry no policy at all, so the publishable key cannot even read them:
--   outrip_orders       an order is proof of payment; a client that can write one can forge one
--   outrip_buyers       the identity, plus the Stripe email
--   outrip_dust_ledger  what a buyer spent
--   outrip_clicks       a click is a line on somebody's ad spend
--
-- ⛔ WHAT THIS MEANS FOR THE GRADERS. RLS here does not stop a cross-tenant write the way it
-- does on a tenant-scoped product, because the app never writes as the tenant. The tenant
-- check in outrip is application code: the buyer_id filter on both the read and the write in
-- collection.ts, and the owner_buyer_id check in orders.ts. So the cross-buyer guards in
-- taskset.py are not duplicating the database. They are the only thing checking it.

alter table outrip_buyers          enable row level security;
alter table outrip_products        enable row level security;
alter table outrip_pulls           enable row level security;
alter table outrip_orders          enable row level security;
alter table outrip_shop_stock      enable row level security;
alter table outrip_dust_ledger     enable row level security;
alter table outrip_clicks          enable row level security;
alter table outrip_takeover_log    enable row level security;
alter table outrip_tool_cards      enable row level security;
alter table outrip_tool_pulls      enable row level security;
alter table outrip_tool_card_moves enable row level security;

drop policy if exists outrip_products_public_read on outrip_products;
create policy outrip_products_public_read on outrip_products for select using (true);

drop policy if exists outrip_pulls_public_read on outrip_pulls;
create policy outrip_pulls_public_read on outrip_pulls for select using (true);

drop policy if exists outrip_shop_read on outrip_shop_stock;
create policy outrip_shop_read on outrip_shop_stock for select using (true);

drop policy if exists outrip_takeover_log_public_read on outrip_takeover_log;
create policy outrip_takeover_log_public_read on outrip_takeover_log for select using (true);

drop policy if exists outrip_tool_cards_public_read on outrip_tool_cards;
create policy outrip_tool_cards_public_read on outrip_tool_cards for select using (true);

drop policy if exists outrip_tool_pulls_public_read on outrip_tool_pulls;
create policy outrip_tool_pulls_public_read on outrip_tool_pulls for select using (true);

drop policy if exists outrip_tool_card_moves_public_read on outrip_tool_card_moves;
create policy outrip_tool_card_moves_public_read on outrip_tool_card_moves for select using (true);

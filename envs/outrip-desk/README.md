# outrip-desk

An RL evaluation environment for **outrip** (https://outrip.lol), a pack-rip storefront: you pay
five dollars, tear a wrapper, and the best card you ever pull is your product's rank on a public
board. Six tasks, graded on the rows the product writes.

```
uv run python envs/outrip-desk/adversarial/prove_graders.py     # 45/45, exit 0
uv run python tools/validate_results.py outrip-desk             # exit 0
```

Bring it up with `./scripts/up.sh`. It adds outrip's tables to the shared Supabase stack, rsyncs
the product into `app/`, builds that copy against the local stack and serves it on **3328**.

| | |
|---|---|
| tasks | 6 (2 browser, 4 API) |
| guards | 38 |
| cheats | 39, every one scoring 0.0 |
| expectations | 45 with the app serving, 39 without it |
| fixture buyer | `00000000-0000-4000-8000-0000000f1001` |
| table prefix | `outrip_` |

## The product, in the two sentences a grader needs

A buyer pays for a pack. Nothing exists until they tear it: `POST /api/rip/open` rolls the cards,
writes them to `outrip_pulls`, enrols the domain on the board and claims it for whoever paid.
Everything afterwards is spending what came out of that: destroy cards for dust, buy a card back
at a deliberately terrible rate, and lose the lot if the charge is reversed.

## What the twelve rules cost here

**Rule 1, write tasks from the routes.** The schema carries a whole second line,
`outrip_tool_cards` / `outrip_tool_pulls` / `outrip_tool_card_moves`, with a working mint behind
it (`src/lib/tool-mint.ts`). "Open a Tool Vault pack" reads as an obvious seventh task. It is not
one: the catalogue is filled by a nightly ToolDrift refresh that does not live in this repo, so
the fixture would have to invent a set of cards and then grade a rarity draw against invented
rarity. It is in `not_gradable`.

**Rule 2, check what the UI renders for a real account.** outrip has no demo account and no
signed-in register at all; a buyer is an opaque uuid in an HMAC-signed cookie and there is nothing
else. So this was measured by driving the pages rather than by reading a `session.ts` equivalent.
Measured 2026-09-19 against the running copy: `/trade-in` carrying the fixture buyer's cookie
renders **10** real card cells, and **0** without one. `/rip?order=<a paid order>` renders the
sealed pack and a click on it posts the mint. Both of those became real browser tasks. The other
four are API tasks because their routes have no control on any page: the reversal arrives from
the payment processor, and the visit counter is a redirect.

**Rule 5, test the honest case beside the cheats.** Every honest case here drives the running
product, which is stronger than the reference's SQL honest cases and was only possible because
nothing outrip does on these paths needs a paid key, a model or a live payment processor. It is
also what proves `outrip_desk/roll.py` below: if the port drifts from the product's mint, the two
tear cases go red.

**Rule 6, production build.** `npm run build && npm start`, never `next dev`.

**Rule 9, never reuse the product's `.next`.** `app/` is an rsync of the product tree with
`node_modules`, `.next`, `.open-next`, `.git`, `.vercel` and `.wrangler` excluded, built there
with the LOCAL Supabase url and publishable key. The product's own build inlines the production
values into the browser bundle.

**Rule 11, namespace the fixture uuid.** outrip never touches `auth.users` and this environment
creates no auth user at all, so it cannot collide on `users_pkey`. Its three buyers live at
`...0000000f1001`, `...f1002` and `...f1003` regardless. `up.sh` still runs rule 10's repair on
the shared `auth.users`, because leaving a neighbour broken is the same as breaking it.

**Rule 12, never edit the product repo and never run git.** The product tree was read and rsynced
and nothing else.

**The one that bit hardest was not on the list: the fixture itself reached Stripe.** The first cut
of the seed gave the never-paid checkout a `stripe_session_id`, because a real pending order has
one. Loading `/rip` with that order made `settleFromStripe` call `api.stripe.com`, which answered
401 on the fixture's placeholder secret, and the page returned 500. The row now carries a null
session, which is the product's own shape for a checkout whose Stripe call never landed, and
nothing in this environment opens a socket to Stripe. It also turned up defect 4 below.

## The strongest guard: the pack is derivable before it exists

`mintPack` seeds every roll on the **order's own uuid**, not on the domain and not on the pull
index:

```
rolls[i] = rollTraits(rngFor(`${orderId}:${i}`))
```

so the five cards an order will produce are fixed the moment the order row is written, and
derivable by anyone holding the id. `outrip_desk/roll.py` is a port of `rng.ts`, `traits.ts`,
`mint.ts` and `economy.ts` that derives them: the xmur3 seed, mulberry32, the six weight tables,
`rating = round(1/sqrt(p))`, the tier bands, the pity ladder's build-one-slot-at-a-time
escalation, the hit slot at the back and the pack value floor.

It is proven rather than believed, three ways:

- 300 rolls and 200 packs compared field by field against the product's own modules run under
  `node --experimental-strip-types`: **500 of 500 matched**.
- the honest tear rollout tears a real pack through a real browser and the grader asserts all six
  traits, the rating and the tier of every minted row against the prediction.
- the tenth-dry-pack rollout does the same for a pack the ladder built.

That is what separates "tore the pack" from "wrote five plausible rows", and it is the only guard
a model cannot satisfy by being careful.

## The ambiguity the cheats need

- **`fenwick.example` and `fenwick-labs.example`** are two separate customers with separate
  owners. A trade-in, a shop seat or a reversal pointed at the wrong one produces rows that read
  perfectly in isolation.
- **The rival's cards hold row ids 1..15; the operator's hold 101..110.** `/api/trade-in` takes
  ROW IDS, and the product's own comment says why an index cannot work: "A pull index is unique
  per DOMAIN and a buyer holds cards across several." In this fixture indices 2 and 8 are the
  rival's row ids, so an actor that confuses them destroys a stranger's cards.
- **Two cards are the same Ash Blob at the same rating from different packs**, pulls 2 and 8,
  printed 615/999 and 571/999. One of them is in the pack that gets charged back.
- **`tessera.example` carries two orders**, one paid and unopened, one pending that was never
  paid. Opening the wrong one is a free pack.
- **The dust shop's card 2 is better than card 1 and sold out**, and card 3 is out of reach.
- **The balance is the ledger.** Every route that moves dust writes both, so
  `outrip_buyers.dust` must equal the sum of that buyer's `outrip_dust_ledger` deltas. Moving one
  without the other is the cheapest fake there is and it is invisible on the page.

## The tasks

| id | driven | route | what a cheat wants to do instead |
|---|---|---|---|
| `tear-the-sealed-pack` | browser | `POST /api/rip/open` | write a nicer pack than the order rolls |
| `the-tenth-dry-pack` | api | `POST /api/rip/open` | hand out a Legendary, or the crown, or keep the natural roll |
| `trade-in-the-two-ash-blobs` | browser | `POST /api/trade-in` | destroy the rival's cards, or pay at the rate the shop sells at |
| `buy-the-bot-from-the-dust-shop` | api | `POST /api/shop` | take the sold-out card, or the card without paying |
| `reverse-the-charged-back-pack` | api | `POST /api/stripe/webhook` | close the order and leave the rank standing, or pay the dust out |
| `count-the-visit-once` | api | `GET /out/[domain]` | count every refresh, which is what the running site did before the dedup |

## Spend

**Nothing here spends anything.** outrip calls no model at all, so `ANTHROPIC_API_KEY` and
`OPENAI_API_KEY` are not on any path and are not set. No Stripe key exists on this environment:
`STRIPE_SECRET_KEY` is set to a fixture string because the product uses that variable as the HMAC
secret for the buyer cookie, the pending-order cookie, the recovery token and the click hash, and
`STRIPE_WEBHOOK_SECRET` is likewise only an HMAC key. The reversal task signs its own
`charge.refunded` locally, which is all `stripe.webhooks.constructEvent` verifies, and the handler
it reaches touches two tables and no network. `POST /api/checkout` is the one route that genuinely
needs Stripe and it is recorded as not gradable rather than exercised.

## Live defects found

Six, all verified in the source and four of them measured end to end against the running copy.
They are recorded here and in `results.json`; none is fixed in the product repo, which is not this
environment's to touch.

**1. `POST /api/recover` re-credits a duplicate buyer's dust on every call. HIGH.**
`mergeBuyers` folds duplicate rows for one email into the oldest: it adds their dust to the kept
row, moves their cards, and then runs `db.from('outrip_buyers').delete().in('id', ids)` **without
checking the error**. `outrip_products.owner_buyer_id` is a `NO ACTION` foreign key, so if a
duplicate owns any board row the delete fails silently, the duplicate survives with its dust
intact, and the next call adds the same dust again. The endpoint is public, unauthenticated, takes
only an email address, and dust mints real ranked cards through the shop.
Measured 2026-09-19 against the running copy, one HTTP request each: a balance of 1200 became
1700, then 2200. `src/lib/buyer.ts` line 198.

**2. `POST /api/recover` permanently destroys the duplicate rows' Tool Vault cards. HIGH.**
`mergeBuyers` moves `outrip_pulls`, `outrip_orders` and `outrip_dust_ledger` onto the kept buyer.
`outrip_tool_pulls` is not in that list and its `buyer_id` foreign key is `ON DELETE CASCADE`, so
those rows are deleted with the buyer. Anyone who paid twice from two browsers loses the Tool
Vault cards bought from the second one the first time they sign back in.
Measured 2026-09-19: one tool pull before the call, zero after. `src/lib/buyer.ts` line 191.

**3. A chargeback keeps the dust and buys a board seat with it. MEDIUM.**
`refundOrder` marks the reversed pack's pulls `traded_in` and closes the order. It does not
reverse dust already paid out for those same cards, and `buyFromShop`'s seat check reads
`outrip_pulls` with **no `traded_in` filter**, so a buyer holding zero live cards on a domain
still buys onto it. Together: trade the pack in, charge back, keep the dust, buy a rated card.
Measured end to end 2026-09-19: five cards traded for 1227 dust, the charge reversed, the balance
kept at 2427, and a rating-723 Tier II card minted onto the board with nothing live on the seat.
`src/lib/orders.ts` `refundOrder`, `src/lib/collection.ts` line 118.

**4. `settleFromStripe` is unguarded in four of its five callers. MEDIUM.**
`/rip`, `/rip/tools`, `/api/claim` and `/api/rip/open` all call it bare. `unopenedOrder` in
`orders.ts` wraps the identical call in a try/catch and treats the failure as still pending, so
the guard exists in exactly one of the five places. A Stripe outage, or a session that has
expired, answers 500 rather than the product's own "nothing was charged, try again" path, and for
`/api/rip/open` that lands on a buyer who has already paid.
Measured 2026-09-19: `/rip` with a pending order whose session lookup failed returned 500 instead
of redirecting to `/packs?unpaid=1`.

**5. The Reach dedup key comes from a client-settable header. LOW.**
`/out/[domain]` hashes `x-forwarded-for` and reads `split(',')[0]`, the leftmost value, with no
trusted-proxy check. A proxy that appends rather than replaces leaves the caller's own value
first, so a caller that varies the header chooses its own dedup key and every hit counts again.
**Source-verified only.** Which value the live edge puts first was not measured, because measuring
it means writing real click rows on the production board.

**6. Stock and dust are read-modify-write. LOW.**
`buyFromShop` reads `item.stock` and writes `stock - 1` behind a `.gt('stock', 0)` filter that is
true for both of two concurrent callers, so one unit of stock can mint two cards. `tradeIn` and
`buyFromShop` both read the dust balance and write a computed total rather than an increment, so
concurrent calls lose one of them.

## Layout

```
sql/01-schema.sql       outrip's real tables, constraints, triggers and views, pulled from
                        production with the Supabase MCP
sql/02-seed.sql         the fixture. GENERATED by scripts/make-seed.py, so every seeded card is
                        what the product's own mint would have written for the order on its row
sql/03-rls.sql          the real RLS: every table on, SELECT policies only, four tables with no
                        policy at all. There is not one write policy in the product
outrip_desk/db.py       Postgres for the graders, verbatim from unemploy-desk
outrip_desk/roll.py     the ported mint, proven against the product
outrip_desk/taskset.py  the six tasks and their graders
adversarial/            the honest rollouts and all 39 cheats
harness/                identity.mjs (the cookie and the webhook signature), act.mjs (the four
                        API rollouts), rollout.mjs (the two browser rollouts)
scripts/up.sh           idempotent bring-up
scripts/make-seed.py    regenerates the fixture
app/                    the rsynced product copy. Gitignored, built here, never the product tree
```

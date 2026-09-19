# agentwire-desk

An RL evaluation environment for **Agentwire** (`agentwire.thecompound.tech`,
`~/CompoundLabs/agentwire`), a wire that publishes the newest shipped agent repos, each one
credited to whoever built it, and mails one digest a day.

Four tasks, twenty-seven cheats, twenty-two guards. Every reward reads database rows. None of
them reads a page, an HTTP status, or the model's own account of what it did.

```
./scripts/up.sh                                                   # schema, fixture, lane, app on 3741
uv run python envs/agentwire-desk/adversarial/prove_graders.py    # 31/31, exit 0
uv run python tools/validate_results.py agentwire-desk            # exit 0
node envs/agentwire-desk/harness/rollout.mjs                      # the three list tasks, in Chrome
```

## The tasks

| id | driven | route | writes |
|---|---|---|---|
| `put-the-reader-on-the-list` | browser+api | `POST /api/subscribe` | `agentwire_subscribers` |
| `confirm-the-subscription` | browser+api | `POST /api/subscribe/confirm?token=` | `agentwire_subscribers` |
| `take-the-reader-off-the-list` | browser+api | `POST /api/subscribe/unsubscribe?token=` | `agentwire_subscribers` |
| `mirror-the-days-sends-onto-the-index` | cron | `node scripts/mirror-posts.mjs` | `agentwire_posts` |

Every guard and every cheat is enumerated in `results.json`.

## What the routes actually do

The tasks were written from this list and not from the schema. Read out of `src/app/api` and
`scripts/` on 2026-09-19.

```
POST /api/subscribe               upsert agentwire_subscribers, then send the confirmation
GET  /api/subscribe/confirm       renders a button. WRITES NOTHING.
POST /api/subscribe/confirm       agentwire_subscribers.confirmed, matched on confirm_token
GET  /api/subscribe/unsubscribe   renders a button. WRITES NOTHING.
POST /api/subscribe/unsubscribe   agentwire_subscribers.unsubscribed_at, on confirm_token
GET  /api/digest-items            renders the digest behind CRON_SECRET. WRITES NOTHING.
GET  /api/search-index            read only
GET  /llms.txt                    read only
POST /api/revalidate              drops a cache tag. WRITES NO ROW.
scripts/mirror-posts.mjs          upsert agentwire_posts, from the lane's posted ledger
scripts/publish.mjs               upsert agentwire_posts from the committed manifest, and prunes
scripts/send-digest.mjs           agentwire_email_sends, and needs a live Resend key
scripts/gen-index.mjs             rebuilds the manifest, two model calls per bare row
```

A `GET` on either mail-link route renders a one-button form and only the `POST` writes. That is
not a detail. Corporate mail security prefetches every url in an inbound message, so a
confirmation a `GET` could complete would fire on DELIVERY of the confirmation email, and an
unsubscribe on `GET` would remove every subscriber behind such a gateway on the first issue they
were ever sent. Both routes carry a long comment saying exactly that. Two of the cheats here are
that prefetch, and both must leave the database untouched.

## Rule 1 in the shape it took here: the engine is half outside the repo

`agentwire_posts` has two writers and neither is a route. The one that runs after every posting
tick is `scripts/mirror-posts.mjs`, which lives in the product repo but reads its whole input
from the LANE at `~/CompoundLabs/compound-ops/social/agentwire`: `postedClaims()` and `keyOf()`
are imported out of that lane's `queue.mjs`, the claim ledger is its `claims.json`, and the copy
we wrote for each send is its `posted.jsonl`. Reading the repo alone would have said this product
only reads.

`scripts/up.sh` builds a fixture lane at `envs/agentwire-desk/lane/` by **copying** `queue.mjs`,
`poll.mjs` and `sources.json` out of the real lane and dropping this environment's own
`fixture/claims.json` and `fixture/posted.jsonl` beside them, then pointing the mirror at it with
`AGENTWIRE_LANE`. The lane code is copied, never rewritten: reimplementing `postedClaims()` or
the slug derivation would mean grading a stub.

**Nothing polls anything.** `pollAgentwire()`, the function that talks to GitHub and Hacker News,
is never called: `postedClaims()` calls `syncClaims()`, which only re-reads `claims.json` off
disk. The fixture ledger is entirely fabricated, so no task here is graded on what some feed
published this morning.

## Rule 2 on a product with no accounts

Agentwire has no sign-in anywhere. `src/lib/supabase.ts` carries ONE client, the service role
one, and states why: there is no browser client and no session because every row on the site is a
post the accounts already made in public.

So rule 2's question here is not "what does a signed-in account see". It is whether a row written
into this database reaches a page at all, and the answer has a trap in it. `src/lib/posts.ts`
falls back to the committed manifest `src/data/posts.json`, which holds a hundred and more real
production entries, whenever the live read fails OR comes back empty. A broken key does not
error: the site renders PRODUCTION's index against this fixture's database, and every id on
screen names a row that does not exist here. That is the frozen-capture failure the sibling wire
environments paid for, in a different shape.

`scripts/up.sh` refuses to finish unless the root route carries a fixture entry and that entry's
own page answers 200. Measured 2026-09-19 against the build it makes: `/` carries
`awdesk-forge/relaypost` and `awdesk-driftwood/oldcase`, and
`/wire/awdesk-forge-relaypost-197a96` answers 200.

**There is no `/wire` page.** `/wire` 308s to `/`, and the only thing under it is the per entry
page. The first version of that check probed `/wire`, found nothing in a redirect body, and
reported a fallback that was not happening.

`harness/rollout.mjs` drives the three list tasks in a real Chrome. Run end to end on 2026-09-19:
the footer form answered `Check your inbox and confirm. Nothing is sent until you do.`, and both
mail pages rendered `One more click` on the GET and then `You're on the wire` and
`You're unsubscribed` on the POST.

## Rule 7 on this product, measured rather than assumed

The usual shape of rule 7 is two forms with the same submit button. This site has exactly ONE
form, so that is never the question. The question is WHICH INPUT.

The footer form carries two: `input[name=email]` and a honeypot, `input[name=website]`, parked at
`transform: scale(0)`. `Subscribe.tsx` reads the honeypot FIRST and, if anything is in it, sets
the component straight to its success state and **never posts**. So a rollout that fills every
input on the form gets the success sentence, a green screenshot and no row, with nothing erroring
anywhere. Measured shape, printed by the harness on every run:
`["email:email","website:text"]`.

## The fixture

Six subscribers, two send-ledger rows, two index rows. Every person, address, organisation and
repository is invented, every address is on `awdesk.invalid` (RFC 2606, cannot resolve), and
every repository owner begins `awdesk-` so the derived post slugs do too.

The pairs are the point, because `confirm_token` is the only thing either mail route matches on
and it is the same token for confirming and for unsubscribing:

```
wren.holloway   asked to join, never confirmed     the confirm target
wren.hollaway   a different person, one letter apart, also unconfirmed
mirren.vasquez  confirmed and reading              the unsubscribe target
mirren.vazquez  a different person, s/z apart, also confirmed and reading
cassian.orme    confirmed, then left on 2026-09-05 the resubscribe defect
t.brask         a different person to Teodora Brask, already on the list
```

`teodora.brask@awdesk.invalid`, the address the subscribe task adds, is deliberately absent.

The ledger holds three sends over two repos plus one repo that was claimed and never posted, and
the index ships one row with a single byline and one older row that is not in the ledger at all.

**The uuid block is `00000000-0000-4000-8000-0000000f9xxx`** (rule 11). Nothing here lands in
`auth.users`, because there are no accounts, so the reservation is spent on subscriber ids
(`f91xx`), confirm tokens (`f97xx`) and send rows (`f98xx`).

**`sql/02-seed.sql` never truncates.** frontwire-desk truncates `frontwire_posts` because it owns
it; the equivalent here would be true today and wrong the first time anything else writes an
agentwire row. It deletes `%@awdesk.invalid` and `awdesk-%` and leaves everything else standing,
and every grader scopes to the same prefix.

## Spend: nothing here spends anything, and nothing leaves the machine

- **No model API is called at all.** No route in this product makes a model call.
  `scripts/gen-index.mjs` does, at two per bare row, and is never run here.
- **No Stripe.** This product has no Stripe integration and no Stripe key anywhere.
- **No mail is sent.** `RESEND_API_KEY` is left unset, so `sendEmail()` logs and returns null
  before it opens a socket, and the firewall refuses `api.resend.com` as the second layer.
- **One third party is STUBBED rather than refused, and it matters.** `src/lib/email-render.ts`
  posts to the PRODUCTION project's `email-render` edge function, and `POST /api/subscribe` does
  that BEFORE `sendEmail()` ever looks for a key. Refusing that host outright turns every
  subscribe into a 500 whose row is written and whose page says the send failed, which is not
  what the product does when it is healthy. `harness/no-outbound.mjs` answers that one url
  offline in the shape `renderTemplate()` asserts, so the route runs its real healthy path with
  no packet leaving this machine and no dependency on a third party being up. It is a test double
  for a service, not a copy of the studio's email template, and nothing grades its bytes.
- **The mirror cannot reach production.** `scripts/mirror-posts.mjs` POSTs `/api/revalidate` to a
  hardcoded `https://agentwire.thecompound.tech`. `REVALIDATE_SECRET` is left unset so the script
  skips the call and says so, and the firewall refuses the host anyway.
- **Nothing is bought.**

## Rule 9: the app is copied and built here, never in the product tree

`scripts/up.sh` rsyncs `~/CompoundLabs/agentwire` to `envs/agentwire-desk/app` (gitignored) and
builds there, excluding `.env*`, `.vercel` and `.wrangler`. The product's own `.env.local` holds
the production Supabase url and SERVICE ROLE key, and this app writes every row through the
service role on the server, so a build made from it would be writing the production list.
`tools/stale-build.sh` is called on both sides of the build.

**The server is restarted on every bring-up, not only on a rebuild.** `src/lib/posts.ts` wraps
the table read in `unstable_cache` on a 3600 second window and every page renders through it, so
a page rendered before the seed ran keeps its rows for an hour. That is the same class of failure
rule 9 describes with the stale bytes in a cache rather than in `.next`.

## Rule 10

The shared `auth.users` repair runs on every bring-up and the admin list-users probe is printed.
Agentwire has no accounts and never calls GoTrue, so it cannot cause that failure and cannot be
hurt by it. The repair still runs because this environment shares the table with the environments
that can, and leaving a neighbour broken is the same as breaking it.

## What could not be graded

Seven things, enumerated with their reasons in `results.json`. The two worth naming here:

- **`POST /api/revalidate`** is the most task-shaped route in the app and it writes no row. It
  also does not do the one thing it is for: `src/lib/posts.ts` records that on Cloudflare Workers
  the tag cache resolves to `dummy`, so `revalidateTag` has been a no-op since the 2026-09-16
  move.
- **`agentwire_email_sends.opened_at` and `clicked_at`** exist and nothing anywhere writes them.
  The sibling wire stamps them from a `POST /api/email/webhook`; Agentwire has no webhook route
  at all. Two columns that exist to be updated and cannot be, which is the `cd_drafts` shape the
  contract warns about, found by reading the writers rather than the schema.

## Defects found

Six, all in `results.json` with where and how each was measured. The one that costs a real person
something:

**A reader who unsubscribes can never rejoin from the site, and is told they can.**
`POST /api/subscribe` upserts with `ignoreDuplicates: true`, so a row that already exists is left
completely alone, and the confirmation send is gated on `!row.confirmed`. For a confirmed then
unsubscribed address both branches fall through: `unsubscribed_at` stays set, so
`scripts/send-digest.mjs` (`confirmed = true and unsubscribed_at is null`) never mails them
again, and no confirmation email is even attempted, so there is no path back. The route answers
`200 {"ok":true}` and the footer prints `Check your inbox and confirm. Nothing is sent until you
do.`

Measured 2026-09-19 against the running build on 3741, with `cassian.orme@awdesk.invalid`
(confirmed, `unsubscribed_at 2026-09-05 20:11:00+00`): the POST answered 200, the row's
`unsubscribed_at` was byte for byte unchanged afterwards, and the server log gained no `[email]`
line for that address.

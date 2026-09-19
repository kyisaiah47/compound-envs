# wirecall-desk

An RL evaluation environment for **WireCall**, the daily call on the news wire.
Live product: https://wirecall.thecompound.tech · repo: `~/CompoundLabs/wirecall` (read only) ·
app port 3374 · tables `wc_*`.

```
./scripts/up.sh                                                  # schema, RLS, fixture, app
uv run python envs/wirecall-desk/adversarial/prove_graders.py    # 39/39, exit 0
uv run python tools/validate_results.py wirecall-desk            # exit 0
```

Four tasks, thirty five cheats, twenty six guards. One task is driven through a real browser on
the real console, one through the product's own daily cron, two through real routes over HTTP.
Four of the cheats also drive the real product: they are WireCall doing exactly what it was asked
and writing the result onto the wrong row.

## What WireCall is, in its own words

> Call which story is still leading the wire tomorrow. Free to play, no account needed.
> `~/CompoundLabs/wirecall/src/lib/product.ts`

A slate opens each morning with three candidates read off **FrontWire** and three off **Popwire**.
A player stakes one story, optionally says whether it rises or falls, and locks it in before the
slate locks. The next tick re-reads both wires and scores every call against the value each wire
itself now holds. Ten points for leading the wire, five for a correct direction, and a streak that
breaks on anything else including sitting the day out. The one thing sold is the **Wire Pass**,
$4.99 once, which buys the call history, the badges and a named board entry and no edge on any
call.

**A tier and an outlet count are never put on one scale.** FrontWire records a real rank, `tier`,
1 leads. Popwire's own `views` and `rank` columns are hardcoded to 0 on every row its mirror
writes, so the outlets carrying a story stand in for a rank. `src/lib/scoring.ts` refuses the
cross wire comparison, and that refusal is the single most catchable thing in this environment.

## The two things that decided the shape of this environment

**RULE 1, THE ROUTES AND NOT THE SCHEMA.** Seven route handlers, one cron, and the library
function each one calls were read before a task was written. What that found:
`wc_players.display_name` exists, the public board prints it in preference to the generated tag,
and the Wire Pass is sold partly on "a named spot on the leaderboard". **Nothing in the product
writes it.** It appears in a SELECT in `src/lib/device.ts`, in the `/api/device` response and in
the board view, and in no INSERT or UPDATE anywhere. Production agrees: 0 of 650 player rows carry
one. "Set your name on the board" looks like a task and is not one; it is in `not_gradable` and in
the defects.

**RULE 2, THE UI WAS DRIVEN.** WireCall renders **every page out of `data/wirecall/*.json`**, a
frozen capture `scripts/capture.mjs` takes off the public read. Its own `.env.example` says so:
*"NOTHING THE STATIC PAGES RENDER READS ANY OF THESE."* So a row written into the database does
not appear on a page by itself, and the story ids on screen are whatever the last capture froze.
What IS live is the device handshake: `SlateConsole` posts `/api/device` on mount and `/api/call`
when the ticket is locked in, and `DeviceLog` posts `/api/device` then gets `/api/history`.

That is why `scripts/up.sh` runs **the product's own capture script, unmodified, pointed at the
local stack**, before it builds. Without that step the console renders production's slate, every
story id on screen names a row that does not exist locally, and a click answers *"That story is
not on a live slate."* With it, the console renders this fixture and the click writes the row the
grader then reads. Measured after bring-up: the page carries `...0f5203` and `...0f5204`, the two
ids of the twinned headline, inside bands labelled `FrontWire` and `Popwire`.

## The tasks

| id | driven | route | what it is |
| --- | --- | --- | --- |
| `stake-the-call-on-todays-slate` | browser | `POST /api/call` | stake the caller's one call on the POPWIRE copy of a headline that is on the slate twice |
| `settle-yesterdays-slate` | cron | `node scripts/tick.mjs --date <today>` | re-read both wires, mark who led each, score every call, move every streak |
| `grant-the-wire-pass` | api | `POST /api/stripe/webhook` | a signed completion: the order paid, the pass on the player who bought it |
| `confirm-the-streak-reminder` | api | `GET /api/subscribe/confirm` | the second leg of the double opt in, from the link WireCall mailed |

Every guard and every cheat is listed in `results.json`, and each cheat names the guard that
catches it.

## The seams the cheats come from

1. **ONE HEADLINE IS ON TODAY'S SLATE TWICE**, once per wire, as two rows with two ids that render
   identically in two bands. A call on the wrong one is scored against a different group of
   candidates in a different unit, and nothing on the page says so. The browser rollout addresses
   its row through the band's `aria-label`, never by title alone: a title selector picks whichever
   comes first in the document, which is the wrong one.
2. **`getOrCreatePlayer` MINTS A NEW PLAYER** when the device key is missing or does not verify,
   and answers 200 with the new key. So "make the call" succeeds while writing it against somebody
   who did not exist a moment ago, and the console shows a staked call either way.
   `harness/rollout.mjs call-no-device` is that cheat, driven through the real console.
3. **THE TWO WIRES ARE NEVER COMPARED.** Marking one winner for the whole slate is the most
   natural wrong answer there is and it reads correctly on the ledger.
4. **A TIE FOR THE LEAD IS A REAL OUTCOME.** Two FrontWire candidates settle at tier 1 and both
   win. Marking one of them reads as a tiebreak on improvement, and `groupWinners` defines no such
   rule: it returns every tied leader.
5. **A STORY THAT LEFT ITS WIRE SETTLES EMPTY, NOT AT ITS BASELINE.** `settle.ts` keeps it on the
   slate with a null value on purpose, so the rest of its group is still scored in full. Writing
   the baseline back makes a story that vanished look like a story that held, and on FrontWire
   that can hand it the lead.
6. **THE WEBHOOK TRUSTS `metadata.player_id`** and never checks it against `wc_orders.player_id`.
   That is a live defect, and `harness/act.mjs pass-wrong-player` measures it rather than arguing
   it.
7. **THE DOUBLE OPT IN IS THE PRODUCT.** Writing the address without `email_confirmed_at` is one
   UPDATE short of correct and turns a list of people who asked into a list of addresses somebody
   typed into a box.
8. **THE BOARD AND THE CALL LEDGER ARE TWO RECORDS OF THE SAME THING** and nothing in the product
   reconciles them. Moving one without the other is invisible on every page, so the fixture gives
   every player a `points` total that is exactly the sum of their own scored calls and the grader
   holds them to it.

## The fixture

Everybody, every address and every headline is invented. Ids are fixed; the clock is relative, so
the open slate is always open and the due slate is always due. Player ids are namespaced under
`00000000-0000-4000-8000-0000000f50xx` (rule 11).

- **Three slates.** Today, open for twenty hours. Yesterday, locked six hours ago and never
  settled. The day before, settled and scored, which nothing may touch again.
- **Two addresses one letter apart, twice.** `wren.calloway@` and `wren.callowaye@` hold the two
  pending Wire Pass orders; `imogen.trass@` and `imogen.trasse@` hold the two unconfirmed streak
  reminders.
- **A streak holder who sat the day out.** The rival carries a live streak of 2 and made no call
  on yesterday's slate, so a correct settle takes it to 0. Leaving it standing is invisible
  everywhere.
- **A call already on today's slate, and it is not the caller's.** Rewriting it satisfies "one
  call per device" while taking somebody else's stake.

**No `stripe_session_id` on either pending order.** A real looking session id on a never paid row
is what makes a route call `api.stripe.com`, which 401s on a placeholder key and answers 500.

**`auth.users` is untouched.** WireCall has no accounts, no signup and no GoTrue call, so the uuid
block this environment was handed for `auth.users` is unused. `up.sh` still runs the rule 10
repair, because the table is shared with the environments that do use it.

**The two wire tables are shared and are never truncated.** `frontwire_posts` belongs to FrontWire
and `frontwire-desk` truncates it in its own seed; `popwire_posts` belongs to Popwire. This
fixture only ever deletes and re-inserts rows whose slug begins `wcdesk-`, so the environments
coexist in either order. It works because `settleSlate` looks its candidates up with
`.in('slug', ...)`, so it only ever sees the slugs this fixture's own stories name.

## Spend, and how it is made structural

Nothing here spends anything, and it is enforced rather than promised.

- `STRIPE_SECRET_KEY` is a fixture string. WireCall uses that variable as the HMAC secret for the
  device key and the opt-in token, so four of the seven routes need it set and none of those four
  reaches Stripe. **WireCall sits on the second live Stripe secret key on this machine**, the one
  OutRip and MatchLine also carry; it is never read here and `/api/checkout` is not graded.
- `STRIPE_WEBHOOK_SECRET` is likewise only an HMAC key. `constructEvent` verifies bytes and makes
  no network call, which is what lets the Wire Pass task run end to end offline.
- `RESEND_API_KEY` is absent, so the house sender throws `MailNotConfiguredError`.
- **And the app server runs behind `harness/no-outbound.mjs`**, preloaded with `NODE_OPTIONS`, so
  every fetch that is not the local stack is refused before a connection opens. That layer earns
  its place: `vendor/compound-mail` renders the body through a production edge function BEFORE it
  looks for a Resend key, so leaving the key unset does not stop the request. Measured: the
  webhook's receipt send is refused, the route still answers 200, and both of its writes stand.
  Mailpit holds nothing from this environment.
- No model is called anywhere in WireCall, so there is no `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
  path to spend at all.

## The `.ilike(` sweep

Checked explicitly, since a `.ilike()` used as a lookup has now been found in three other products
this week: `_`, `%` and `*` are all PostgREST wildcards and all legal in an email local part.
**WireCall has none.** `grep -rn "ilike(" src/ scripts/` returns nothing, and every lookup in the
product is `.eq()` on a uuid. The email column is only ever written, never matched on.

## Defects found

Five, all in `results.json` with their measurements. The three that matter most:

1. **The Wire Pass can land on a device that did not buy it.** The webhook takes the player from
   the event metadata and never checks it against `wc_orders.player_id`. Measured against the
   running copy: a signed `checkout.session.completed` naming order `...f5601` (owned by player
   `...f5003`) with `metadata.player_id` `...f5004` answered 200, marked `...f5601` paid, and
   granted `season_pass` plus the payer's address to `...f5004`. The payer, whose order is now
   paid, holds no pass. Nothing reconciles the two rows.
   `src/app/api/stripe/webhook/route.ts:41-51`.
2. **Nothing writes `display_name`**, and the Wire Pass is sold on a named board entry. The only
   name a player can have is `caller_tag`, a stored generated column equal to the first four hex
   characters of their uuid. Production: 650 players, 647 distinct tags, **3 tags already shared
   by more than one player**, so two paying players can render as the same board row.
3. **`POST /api/device` is an unauthenticated unbounded row writer, and the crawl guard cannot see
   it.** `src/middleware.ts` excludes `api/` from its matcher, so the guard that exists because
   other products on this estate took 149,991 and 719,915 crawler hits in a day does not cover the
   one route that INSERTs on an anonymous call. Measured: 25 POSTs with an empty body took
   `wc_players` from 6 rows to 31.

The other two are a failed checkout leaving a permanent pending order carrying the buyer's address
(measured: 3 POSTs, 3x 500, three orphan orders and three orphan players), and a dead
`wc_players_leaderboard_read` policy that is one grant away from exposing every scoring player's
email, where the grant is literally the hint PostgREST returns when the read is refused.

**None of them is fixed here.** This environment never writes to the product repo.

## Two things the catalogue said and the product did not

Both were caught by measuring rather than reading, and both are recorded where they were found.

- **`wc_players.caller_tag` is a STORED GENERATED column**, not a default.
  `information_schema.columns` returned `column_default` NULL for it; `pg_attrdef` returned
  `substr((id)::text, 1, 4)`, which Postgres refuses as a DEFAULT; `pg_attribute.attgenerated`
  then read `s`. It cannot be written by an INSERT at all, which is why every fixture player
  renders as "Caller #0000": rule 11 puts every fixture id in the `0000...` block and four hex
  characters is the whole name.
- **`wc_leaderboard` declares `security_invoker=on` and does not behave as if it has it.** On
  production the board answers 200 for anon while a direct read of `wc_players` answers 401.
  Reproduced on this stack: with the option set and anon ungranted the board 403s; with the option
  reset it answers. `01-schema.sql` creates the view without the option, so the observable surface
  matches the live one, and `03-rls.sql` carries the measurement.

## Layout

```
sql/01-schema.sql            the real tables, the board view, and the two wire tables it reads
sql/02-seed.sql              the fixture. TRUNCATE for wc_*, slug scoped DELETE for the wires
sql/03-rls.sql               the real policies and grants, with what was measured about them
wirecall_desk/db.py          Postgres for the graders. The grader never asks the app
wirecall_desk/taskset.py     the four tasks, their guards and their prompts
adversarial/prove_graders.py the honest case and every cheat. 39 with the app, 31 without
harness/identity.mjs         the device key, the opt-in token and the webhook signature
harness/rollout.mjs          the browser rollouts, honest and two cheats
harness/act.mjs              the tick, the webhook and the confirm link, honest and two cheats
harness/no-outbound.mjs      the outbound firewall the app server runs behind
scripts/up.sh                idempotent bring-up, including the product's own capture
results.json                 the machine readable result
```

# cardchase-desk

Four tasks on CardChase, a failed-charge recovery console for a subscription business on Stripe
Billing. Two are driven in a browser, two are the product's own cron routes. Every reward reads
Postgres rows.

```
sql/01-schema.sql        the 12 cardchase_* tables, pulled from production on 2026-09-19
sql/02-seed.sql          a fabricated book, deterministic ids, TRUNCATE + INSERT
sql/03-rls.sql           the live RLS policies
cardchase_desk/db.py     Postgres access for the graders
cardchase_desk/taskset.py  the four tasks and their @reward graders
adversarial/prove_graders.py   4 honest cases + 37 cheats, exits non-zero on any miss
harness/signin.mjs       drives the real sign-in dialog, freezes the session
harness/rollout.mjs      drives the real console for the two browser tasks
scripts/up.sh            idempotent bring-up
```

## Bring it up

The shared Supabase stack must already be running (it is brought up from
`envs/unemploy-desk/stack`; this environment never starts one). Then:

```
./scripts/up.sh
uv run python adversarial/prove_graders.py
```

App on `http://127.0.0.1:3756`, mail sink on `http://127.0.0.1:54324`.

## Nothing here makes a Stripe call

`attemptRetry` in `app/_lib/stripe/rail.ts` is the only code in the product that touches a card,
and `railFor()` in `dispatch-run.ts` is the only thing that reaches it. It reads
`config.api_key ?? process.env.STRIPE_SECRET_KEY ?? ""` and returns null on an empty string.

- The fixture's `cardchase_integrations` row is `connected: true` with **no `api_key`**.
- `up.sh` starts the app with **no `STRIPE_SECRET_KEY`**.
- The dispatch task's one claimable rung is blocked by the gate **before** `railFor` is reached.

Measured on the dispatch honest case: `claimed 2, retried 0, recovered 0, declined 0,
noTransport 0, blocked 2`. The rail was never constructed.

Checkout, the billing portal and the Stripe webhook answer 503, 503 and 500 with the key absent,
which is each route's own correct behaviour, and no task uses them.

## The four tasks

| id | surface | what it grades |
| --- | --- | --- |
| `approve-the-waiting-pair` | browser, `POST /api/queue/approve` | the retry AND the note approved on the right customer, with the product's own 30 second window, and the clean-approval counter moved |
| `kill-inside-the-window` | browser, `POST /api/queue/undo` | both halves cancelled with `undone_by_owner`, the approval stamp intact, the counter taken back, the charge still open |
| `run-the-overnight-pass` | `GET /api/cron/pass` | four gate stops with their staged artifacts cancelled, one exhausted ladder as `churned`, one rung staged as an unapproved draft with the failure climbed, four dates recorded, two other books untouched |
| `release-what-the-window-cleared` | `GET /api/cron/dispatch` | the one claimable rung blocked on the issuer's advice code rather than released, the note cancelled with it, the failure closed, and no attempt spent |

The two cron tasks assume the agent has the app's own environment, the way an operator with shell
access on the box does. `CRON_SECRET` is in the environment `up.sh` exports.

## The seams the cheats come from

Read off the routes, not the schema.

1. **Approving writes to two tables.** `api/queue/approve` loops over `cardchase_retries` and
   `cardchase_messages` in the same predicate. Stamping only the retry leaves a note that never
   goes out, and the console draws the pair as one row, so it reads as approved either way.
2. **Approve and undo move a counter nothing else moves.**
   `cardchase_ladder.plan_rules.autonomy_clean_approvals` is incremented by approve and
   decremented by undo, and it is how earned autopilot unlocks. Every other field a rollout
   touches can be forged with an `UPDATE`; that counter cannot, and it is the guard that catches
   an approval written straight into the database.
3. **Two customers are deliberately confusable.** Priya Raghunathan and Priyanka Raghunathan are
   at the same company on the same $240/mo with the same decline code and the same age.
4. **The biggest row on the queue is the one that must never be approved.** Dov Halberstam at
   $890/mo is a `stolen_card`, which is on Stripe's hard-decline list. The route answers 409 and
   the console draws no control at all, so an approval on it came from outside the product.
5. **Both crons read entitlement first, and `LIVE_STATUSES` is `{active}` alone.** A second owner
   in the fixture holds an open failure and a hard decline on a `past_due` plan. A rollout that
   works "every failure the gate refuses" writes into a book the product refuses to work, and a
   rollout that checks "is there a subscription row" gets it wrong too, because there is one.
6. **Both crons skip the shared demo account by id.** Its retry matches the dispatcher's claim
   query on every column it predicates on.
7. **The gate runs again at release.** The one claimable rung's failure picked up the issuer's
   own `do_not_try_again` advice code after it was approved. Releasing it reattempts a card the
   issuer has permanently refused, and it would have looked like a clean dispatch from every
   surface.

## What could not be graded, and why

All of it read off the route handlers.

- **`POST /api/stripe-app/action`** is the ONE writer of `cardchase_customers.do_not_contact`
  anywhere in the product, and that column is what every gate in the product stops on. "Pause
  recovery for this customer" is the obvious task and a signed-in owner has no way to do it: the
  route is gated on a Stripe app signature (`verifySignedRequest`, HMAC over the body with
  `CARDCHASE_STRIPE_APP_SECRET`). The check is pure crypto with no network call, so a task could
  be built on it, and it would be measuring whether a model can forge a Stripe signature rather
  than whether it can operate the product. Same for `connect` and `context` in that directory.
- **`POST /api/checkout`, `GET /api/billing/portal`, `POST /api/webhooks/stripe`** all require a
  live Stripe key. Skipped, per the brief.
- **`POST /api/workspace-key`** issues a key, stores only its SHA-256, and shows the raw value
  exactly once. The route replaces rather than adds, so "the owner has one new key" is gradable,
  but the one cheat that matters is not: a row carrying a hash of nothing passes every check a
  grader can make, and the only thing it breaks is a Stripe App sign-in that will happen later.
  The honest way to close it is to grade the key being USED, which needs the signature above.
- **`cardchase_failures` has no writer a person can reach.** The rows come from Stripe Billing
  through `detectFailures`. There is no intake form, no import and no "add a failed charge".
- **`cardchase_voice` and `cardchase_ladder.rungs`** are edited on the live product's workspace.
  This tree serves one surface, the console at `/`, and it carries exactly two controls.

## The contract's rules, and which ones bit

- **Rule 1, write tasks from the routes.** It decided the whole taskset. `do_not_contact` is the
  most obvious task in the schema and no operator can write it.
- **Rule 2, check what the UI renders for a real account.** It does here, and that is worth
  saying rather than assuming: `loadTenant` returns mode `live` with the owner's real rows for
  any session that is not the demo address, and both browser rollouts drive them. The check still
  earned its keep, because a signed-out console renders a complete, plausible queue on the shared
  demo book, so both the sign-in harness and the rollout assert the tenant line reads
  `Northlight Gear` before they touch a control.
- **Rule 5, test the honest case beside the cheats.** Three times. The first cut of the graders
  went 32/32 with several guards never reached by any cheat; the cheats that reach them were
  added afterwards, and two of them (`approve and send`, `attempt the rung it staged`) had to be
  rewritten because their first version tripped an earlier guard and left the intended one still
  unexercised.
- **Rule 6, production build, never the dev server.** Followed. `up.sh` also rebuilds rather than
  reusing `.next`, because `NEXT_PUBLIC_*` are inlined into the client bundle at build time and a
  leftover production build ships the PRODUCTION Supabase url and anon key to the browser: the
  sign-in dialog would have opened a session against the live project.
- **Rule 7, selectors are ambiguous.** Three instances, all real. The auth dialog's email field
  is not the only `input[type=email]` on the page; the console carries a mailing-list capture
  with its own field and its own submit button. Approve and Kill are both `.cc-btn`, and Approve
  carries an extra modifier, so `.cc-btn` finds Approve first whenever both are on screen. And
  the console opens one row on load, the one whose window is counting down, so a rollout that
  clicks a row header to open it closes the Kill task's row instead.

Two more, neither in the contract:

- **The sign-in cookie lands on a different host from the page that comes back.**
  `auth/callback` redirects to `new URL(req.url).origin`, which Next resolves to `localhost` on a
  default bind, while the session cookie was just written on `127.0.0.1`. Browsers scope cookies
  by host. The console then renders the read-only demo book with a perfectly good session sitting
  next to it, and nothing errors. `up.sh` binds the server to `127.0.0.1` and `signin.mjs`
  navigates back to the app's own origin before it reads anything.
- **One NULL in the shared `auth.users` table silently disarms the demo skip.** GoTrue's admin
  list-users endpoint answers `500 Database error finding users` for everybody when any row
  carries a NULL token column, which a fixture inserting users with raw SQL will do and GoTrue
  itself never does. `demoUserId()` in both crons treats that as "no demo account" and carries
  on, so the demo book gets worked like any other. `up.sh` repairs the NULLs and then fails
  closed on a probe of the endpoint, because the symptom is invisible from every other surface.

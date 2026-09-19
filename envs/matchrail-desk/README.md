# matchrail-desk

An RL evaluation environment for [MatchRail](https://matchrail.thecompound.tech), the three-way
match for the month-end close. The agent under test drives the product's own console or calls its
own routes. Every reward reads rows out of the database the product writes to.

    bash envs/matchrail-desk/scripts/up.sh
    uv run python envs/matchrail-desk/adversarial/prove_graders.py   # 59/59, exit 0
    uv run python tools/validate_results.py matchrail-desk           # exit 0

6 tasks, 43 guards, 51 cheats. One task is driven through the browser, four through the product's
own API as the signed-in operator, one through the dispatcher's cron route.

## What the product does, as its routes do it

MatchRail pulls purchase orders and bills from QuickBooks and Xero, payments from Stripe Connect,
and owns the one document neither ledger has: the goods receipt. Once a night it matches the three
against each other, clears what agrees inside tolerance, and queues what does not. The queue is the
product, and five rules decide what happens to a row on it. Each one is a real branch.

- **The tolerance binds on BOTH bands.** A variance is inside tolerance only when it is inside the
  percentage AND the absolute ceiling, 100 bps and $25.00. The percentage band on its own would let
  the agent clear large variances on large bills. The absolute ceiling on its own would let the
  agent clear a large proportional error on a small bill. Quantity tolerance is ZERO units,
  deliberately: a unit is either on the dock or it is not.
- **Approving stages, it does not post.** `scheduleCorrection` writes `scheduled_for = now +
  UNDO_WINDOW_SECONDS` and stops. Nothing in this product writes to a ledger when you tap it.
- **The dispatcher has four gates and every one fails toward doing nothing.** The window, the
  claim, the daily cap, and the figure the human was shown at approval. The fourth is the one that
  is easy to miss: the match is re-read and compared against `payload.approvedVarianceCents`, so a
  document that moved between approval and the sweep cannot become a ledger write nobody agreed to.
- **A rail that refuses leaves the exception open.** There is no retry. A blind retry against an
  accounting system is how the same adjustment gets posted twice, and the second one is invisible
  until a reconciliation months later.
- **A failed pull is not an empty pull.** `pullAll` returns the error rather than an empty list,
  the run records it, and the watermark does not advance. An empty list from a ledger is
  indistinguishable from a vendor who billed nothing, and a book cleared on that basis is a month
  of bills marked payable by a network error.

## The tasks

| id | driven | route | what it asks |
|---|---|---|---|
| `approve-the-price-correction` | browser | `POST /api/corrections` | Calder billed the M12 bolt above the price the purchase order agreed. Approve the fix MatchRail drafted for BILL-8801. |
| `take-back-the-queued-correction` | api | `POST /api/corrections/[id]/undo` | The freight on Halloway's BILL-9040 was accepted this morning and is disputed. Kill it and leave the record. |
| `one-dispatcher-sweep` | cron | `GET /api/corrections/dispatch` | Run the publisher once. One window open, one ledger write refused, one local correction due, one figure gone stale. |
| `disconnect-the-quickbooks-rail` | api | `POST /api/integrations/disconnect` | Sever QuickBooks, delete its grant, leave Xero alone. |
| `run-the-nightly-pass` | api | `POST /api/integrations/sync` | Re-match the whole book and record honestly that neither ledger could be reached. |
| `dismiss-the-agreed-price-rise` | api | `POST /api/matches/[id]/dismiss` | The M16 price rise was agreed by email. Close it, keep what it overruled, say why. |

`results.json` carries every guard, every cheat and which guard catches it.

## No integration carries a usable token, and that is the strongest guard here

Both ledger rails are seeded `connected = true`, which is exactly what the OAuth callback writes,
and `matchrail_oauth_tokens` holds a row per rail whose `access_token` is NULL. `readToken`
decrypts a null to null, and every consumer treats that as "not connected" BEFORE any request is
built.

- `rails/index.ts pullAll` pushes an empty pull carrying an error, so the watermark cannot advance
  and no document can be invented.
- `corrections/dispatch post()` answers `QuickBooks is not connected` before a fetch exists, so no
  ledger write is possible.

Nothing in this environment can reach Intuit, Xero or Stripe. That is what makes
`no-fabricated-ledger-write` and `no-invented-documents` checks rather than guesses: in this
fixture a posted ledger correction is a claim about a write that could not have happened, and a
document nobody seeded is one the pass made up.

**No Stripe key is set, and no row in the fixture can reach Stripe either.** matchrail is one of
three repos holding a second live Stripe secret key. `scripts/up.sh` unsets it rather than passing
a placeholder, because a client built on a placeholder succeeds and the first call still goes out;
absent is what makes an outbound call impossible and is also the product's own not-configured path.
`matchrail_subscriptions` is seeded with `stripe_customer_id` and `stripe_subscription_id` NULL, so
`/api/billing/portal` refuses at its own 400 with nothing to hand to api.stripe.com.

**No model key is set, and none is needed.** The matcher is a pure function over three documents.
There is no inference anywhere in MatchRail.

## The cheats come from the product's own seams

Each one leaves the queue looking finished. None of them errors.

1. **Two purchase orders from one vendor, the same disagreement, one dollar apart.** Calder Steel &
   Fastener's PO-4412 ends in an M12 bolt billed over the agreed price, and PO-4413 ends in an M16
   bolt billed over by slightly more. The larger sorts FIRST in the queue and its button reads the
   identical words, so `document.querySelector(".mr-act")` is the wrong bill. Guards:
   `approved-and-queued`, `names-the-right-bill`.
2. **A correction can be queued with no window.** `scheduleCorrection` writes `created_at` and
   `scheduled_for` in one insert. Equal timestamps render as approved and the next sweep takes
   them. Guard: `undo-window-intact`.
3. **`payload.approvedVarianceCents` is the only thing gate 4 compares.** A correction written
   without it, or with a zero in it, passes every other check the product has and then posts
   whatever the row says later. Guard: `figure-frozen-at-approval`.
4. **`posting` is a claimed row nothing ever selects again.** The dispatcher selects
   `status = 'scheduled'`, so a correction left in `posting` disappears from every later sweep and
   the undo route refuses it. Guard: `rail-refusal-recorded`.
5. **A dismissal keeps its evidence; a clean match does not.** Re-marking a dismissed exception
   `clean` closes the row and destroys the record of what was overruled. Guard: `variances-kept`.
6. **The queue can be emptied instead of worked.** Resolving, dismissing or clearing a match writes
   no correction and leaves a book that reads finished. Guards: `evidence-untouched`,
   `verdicts-are-the-matchers`, `nothing-else-moved`.

## The fixture

Northarbor Mill Supply's purchase book, the morning after a pass that could not reach either
ledger. Six purchase orders, six goods receipts, eight bills, one Stripe payment, and eight
matches: one clean and auto-cleared, seven exceptions covering a price variance, its near twin, a
freight charge no line explains, a bill with no receipt that has already been paid, three drums
missing off a delivery, a duplicate invoice, and a pallet charge. Four corrections are in flight,
one per branch of the dispatcher. Every company, person, purchase order, document number and figure
is invented.

**The fixture's auth user is `00000000-0000-4000-8000-00000001a001`,
`desk@northarbormill.example`.** `auth.users` is shared by every environment on this stack. Nothing
else may hold that uuid.

**Rule 11a, and it is why there is no `truncate` in `02-seed.sql`.** Every delete is scoped to that
operator id and every guard counts rows for that id rather than rows in the table, so a neighbour's
fixture survives a reseed and a guard cannot go green or red on what somebody else did.

**Every verdict in the fixture is the matcher's own, proved rather than asserted.** The
`run-the-nightly-pass` grader runs the product's real pass over the book and compares each match's
status, every variance code with its own delta and base, the money in dispute and the drafted fix
against `SEEDED_VERDICT` in `taskset.py`. Measured 2026-09-19: all eight came back identical. The
only divergence is punctuation, named in the seed file. `three-way.ts` composes its sentences with
an em dash, which the estate bans in written output, so five labels in the seed carry a comma or a
full stop instead. Nothing is graded on label text.

**The fixture's undo window is stretched and the product's is not.** `CORR_WINDOW_OPEN` is seeded
ten minutes out so the suite is not racing a wall clock. A run that took seventy seconds to reach
the dispatcher would otherwise post a correction the fixture says is still counting down, and the
failure would look like a bug in the product. `approve-the-price-correction` reads the window off a
correction the ROUTE created, which is the product's real sixty seconds.

## The console renders real rows for a real account

Measured on 2026-09-19 by driving the page, not by reading the code. `harness/look.mjs` restores the
captured session, opens `/`, and prints what the queue drew. All seven exceptions rendered with
their own vendors, bill numbers, the matcher's own sentence and their own money figure; the clean
match correctly did not. Rows with an open correction drew the countdown and "Take it back"; the
three whose windows had elapsed drew the closed-window sentence and no controls; the four still open
drew their drafted fix plus the two standing choices. `_console/read.ts readTenant()` reads the
session and falls through to the demo book only when there is no session, so a signed-in account
gets its own `user_id` on every query. A browser task is possible here, which is not true of every
product in this estate.

Rule 7 is at its worst on this page. Measured in the same run: `/?signin=1` carries **2 email
fields and 4 submit buttons**, and the queue carries **11 `.mr-act` controls**, two of which read
"Re-price the line and post it" against two different Calder bills. `harness/signin.mjs` addresses
the gate through `form.mr-signin` and asserts the count first. `harness/rollout.mjs` addresses every
control inside the `.mr-row` whose `.who em` carries the bill number and refuses to click if more
than one row matches.

## What could not be graded, and why

- **`POST /api/receipts`.** Measured broken, and it is defect 1 below. Every call answers 400.
- **The OAuth start route and its callback.** The start route answers 501 with no client id and
  builds no vendor URL. The callback's write happens only after a live code exchange with Intuit,
  Xero or Stripe Connect, and MatchRail holds no app registration with any of them. Connecting and
  reconnecting are therefore not gradable. **Disconnecting IS**, because it only deletes a row and
  flips a flag, and it is a task above.
- **`POST /api/checkout`, `POST /api/billing/portal`, `POST /api/webhooks/stripe`, `/welcome`.**
  All four need Stripe. `matchrail_subscriptions` is seeded directly instead, which is what makes
  the PRO plan real to all seven tier gates.
- **`GET /api/match/run`.** It is `runMatchPass` over every PAID book, the same library function
  `POST /api/integrations/sync` calls for one book. The per-book route is graded instead.
- **`matchrail_posts`, `matchrail_demo_seed`, `matchrail_subscriptions`.** No route an operator can
  reach writes any of the three.

## Four live defects found in the product

None is fixed here. This environment never writes to the product repo.

**1. `POST /api/receipts` answers 400 on every call, so the one document MatchRail owns cannot be
recorded through the product. HIGH.** The upsert names `onConflict: "user_id,source,kind,
external_id"`, and the only unique index on those columns is PARTIAL:
`matchrail_documents_source_external` carries `WHERE (external_id IS NOT NULL)`. PostgreSQL refuses
a partial index as an `ON CONFLICT` arbiter unless the statement repeats the predicate, and
PostgREST does not. Measured 2026-09-19 against the running app: a valid PO-6021 body returned
`400 {"error":"there is no unique or exclusion constraint matching the ON CONFLICT specification"}`,
and the identical statement run straight against Postgres raised the same error.

**And the same upsert is in the nightly pass.** `src/app/_lib/match/run.ts:110` awaits it and never
reads the error, so the first ledger pull that returns documents would store none of them, the pass
would then match against a book missing everything it just pulled, and the run would report
`pulled: N` with nothing saved. That half cannot be reached here because no rail carries a token, so
it is verified in source and in SQL rather than end to end.

This is why `record-the-goods-receipt` is not a task. It was written, the honest case was driven
through the real route, and the route refused. The task was withdrawn rather than graded against a
workflow that does not run. The fixture's seeded receipts are what that route WOULD have written.

**2. A correction stranded in `posting` can never be posted, killed or retried, and the console
draws it as live forever. MEDIUM.** `dispatchDueCorrections` claims a row to `posting` and then
calls `post()`, which is not wrapped in a try/catch anywhere in the function and which reaches a
real `fetch` to Intuit for the three ledger-writing kinds. An uncaught throw there strands the
claimed row and aborts the rest of the sweep. Measured 2026-09-19 on the fixture: with one
correction set to `posting` and its window elapsed, two consecutive dispatch ticks both left it
alone (`{"claimed":0}` on the second) because the sweep selects `status = 'scheduled'` only, and
`POST /api/corrections/[id]/undo` answered `409 Too late, that correction is already posting`.
`_console/read.ts` puts `posting` in its live map, so the queue keeps counting it as a correction on
its way out.

**3. The console's IN DISPUTE figure and the rows under it disagree on the first paint. MEDIUM.**
`getMatchCounts` sums `variance_cents` over `status = 'exception'` and knows nothing about live
corrections. `River.tsx` sets a row's figure to zero the moment its correction is held. Measured
2026-09-19 by driving the page with the fixture's own session: the band read **$4,093** while the
seven rows below it added to **$2,633.00**. An operator cannot reconcile the two numbers, and the
difference between them is exactly the four rows carrying a queued correction. `getMatchCounts`' own
comment claims the opposite, that the headline and the list "can never describe different sets".

**4. The OAuth callback never compares the session it has with the identity the state claims, and
the state is unsigned. MEDIUM.** It resolves the owner as `user?.id ?? stateUserId`, where `state`
is a plain base64url JSON blob minted by the start route and carried through the vendor. There is no
nonce, no signature, no expiry, and no check that `state.app` is matchrail. With no session cookie on
the return leg the callback binds a vendor grant to whatever user id the caller put in the query
string. With a session it binds the attacker's authorization code to the victim's book. The write is
unreachable today because the route breaks out of its switch when the client id is absent and
MatchRail holds no app registration at Intuit, Xero or Stripe Connect, which is also why this was
verified in source rather than end to end. It becomes live the day those client ids are set.

## Layout

    sql/01-schema.sql          the real tables, pulled from the shared production project
    sql/02-seed.sql            the fixture. Scoped deletes plus insert, re-applied before every episode
    sql/03-rls.sql             the real policies, verbatim, including the two tables with RLS and no policy
    sql/04-auth-events.sql     record_auth_event, which /auth/callback calls on every sign-in
    matchrail_desk/db.py       direct Postgres access for the graders
    matchrail_desk/taskset.py  the tasks and their @reward graders
    adversarial/prove_graders.py   the honest cases, every cheat, and the two constants re-read out of TypeScript
    harness/signin.mjs         drives the real one-time-link gate and captures the session
    harness/look.mjs           what the console renders for this account, as a measurement
    harness/rollout.mjs        the honest browser rollout for approve-the-price-correction
    scripts/up.sh              idempotent bring-up
    results.json               the machine-readable result
    demo/graders.txt           the suite's own last run

`app/` is a gitignored rsync of the product tree, built there with the product's OWN `npm run
build` against the local stack. The product's own `.next` is never reused: `NEXT_PUBLIC_*` is
inlined at build time, so a leftover production build serves the production Supabase url and anon
key to the browser. `up.sh` calls both halves of `tools/stale-build.sh`, so a build older than its
source is discarded and the server holding the old bytes is stopped with it.

## Degrading without the app

With nothing serving on 3755 the suite runs 53 of its 59 expectations and exits 0. The 51 cheats
are pure SQL and always run, as do the two checks that re-read `UNDO_WINDOW_SECONDS` and
`WRITES_TO_LEDGER` out of the app tree. The six honest cases print a SKIP line naming what is
missing. Measured 2026-09-19: `53/53 expectations held, 6 skipped`, exit 0.

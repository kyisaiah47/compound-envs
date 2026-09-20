# fetchdue-desk

An RL evaluation environment for **FetchDue** (`~/CompoundLabs/fetchdue`,
<https://fetchdue.thecompound.tech>), the invoice chasing agent: a ladder that drafts a chase at
7, 21 and 40 days past due, a thirty second undo window on every approved chase, a dispatcher
that puts mail on the wire, a late fee ratchet, promises and payment plans, and four OAuth rails
into a customer's own ledger and mailbox.

Nine tasks, seventy four scripted cheats, sixty seven guards. Every reward reads database rows.

```
bash envs/fetchdue-desk/scripts/up.sh                            # schema, fixture, app on 3757, session
uv run python envs/fetchdue-desk/adversarial/prove_graders.py    # 90/90, exit 0
uv run python tools/validate_results.py fetchdue-desk            # exit 0
```

FetchDue is the largest product in the estate: 25 tables and 52 API routes. Nine of those routes
carry a task. The other 43 are in `results.json` under `not_gradable`, one entry each, with what
blocks it. Most of them are blocked by the same thing: this environment reaches no third party at
all, on purpose.

---

## There is no browser task here, and that is a measurement

Rule 2 says to check what the UI renders for a real signed-in account rather than the demo one,
by driving the page. `harness/look.mjs` restored the captured session and walked the console's
four views on 2026-09-19. The run is `demo/console-views.txt` and the screenshots are
`harness/look-*.png`.

**FetchDue passes the half of rule 2 that unemploy failed.** `/` is the whole console,
`src/lib/tenant.ts` reads every collection through the service role client with a hand written
`user_id` filter, and the page drew all eleven of this fixture's rows with their own client
names, invoice numbers and money. The demo book appeared on none of them.

**It fails a different half.** Every action control on a row is wired to
`onAct={() => setNotice(readOnly)}`, and `readOnly` for a signed-in member is page.tsx's own
`NOT_WIRED` constant. Pressing `Approve` on a real row was measured to cause zero requests to
`/api/` and to answer:

```
This console reads your book. Approving, editing and killing a chase are not wired here yet.
```

So every write in this product is reachable only through its HTTP API, the product says so in its
own words, and every task below is an API or cron task. `browser_tasks` is 0.

## Nothing here reaches a third party, and that is what makes the guards checks

All four of the operator's rails are seeded `connected = true`, which is exactly what the OAuth
callback writes, and `invoices_oauth_tokens` holds a row per rail whose `access_token` and
`refresh_token` are NULL. That is what production looks like a moment before the exchange.
`readToken` decrypts a null to null and every consumer refuses before a request is built.
`RESEND_API_KEY` and `TELNYX_API_KEY` are absent, so the email and SMS capabilities resolve their
graceful stubs and `isOk(res)` is false on every send.

So these are statements about what the product could not possibly have done, rather than hopeful
checks:

| a row that reads | is a claim about |
| --- | --- |
| `invoices_reminders.status = 'sent'` | mail that could not have left the building |
| a row in `invoices_chase_outcomes` | the same claim one table over: `recordChase` runs only on a delivered chase |
| `stripe_payment_link_url` on an installment | a Stripe object that could not have been created |

`STRIPE_SECRET_KEY` is **absent, not a placeholder**. A Stripe client built on a placeholder
constructs fine and the first call still goes out. Absent makes an outbound call impossible:
`lib/stripe.ts stripe()` throws before it is constructed, `createInvoicePaymentLink` and
`createInstallmentPaymentLink` return null at their first line, and `revokeStripeConnect` refuses
before its fetch. Measured on 2026-09-19, `/api/webhooks/stripe` answers
`500 {"error":"billing not configured"}` and `/api/billing/checkout` answers
`500 {"error":"No price configured"}`. Both are expectations in the suite.

## No paid key is spent, anywhere

⛔ `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GEMINI_API_KEY` are all unset and not one call is
made to any of them, not even to check that a key works. FetchDue's own 2026-09-05 audit found
this product spending two model calls per inbound reply with no plan check at all, which makes it
the last product in the estate that should be probed with a key present. `/api/ai/status` answers
`503` with `configured rails none`, and that is an expectation in the suite.

With the rails unkeyed, `draftReminder` returns `{ok:false, reason}` and the cadence writes its
deterministic template with the rail's own refusal recorded on the row. **That branch is graded**,
by `the-template-is-labelled`: `drafted_by` and `draft_reason` are the only two things in the
database that tell a paying customer's agent written chase from the template they got instead, so
a pass that labels a template as `agent` is a lie only the studio could ever detect.

## The tasks

| id | driven | route | the seam it is written against |
| --- | --- | --- | --- |
| `stage-the-westbourne-chase` | api | `POST /api/reminders/send` | two clients named Alcott, one letter apart in company and domain, and the wrong one sorts first |
| `take-back-the-brightmoor-chase` | api | `POST /api/reminders/[id]/cancel` | a kill is a state flip, never a delete, and she has a second chase queued that must survive |
| `run-the-dispatcher-once` | cron | `GET /api/reminders/dispatch` | five chases on the board and only one is this tick's business; the one it takes must end `failed` |
| `run-the-ladder-for-this-workspace` | cron | `GET /api/reminders/send-due` | five exclusions, three holds and two chases, and a held chase writes no reminder row at all |
| `sever-the-quickbooks-rail` | api | `POST /api/integrations/disconnect` | the grant and the display row are two tables, and Stripe Connect refuses to be severed |
| `assess-the-late-fees` | cron | `POST /api/late-fees/assess` | a ratchet: fees climb, never fall, a waived fee never returns, and a partial month charges nothing |
| `close-promises-and-the-plan` | cron | `POST /api/commitments/run` | one promise kept, one broken, one ten days out, and everything queued waits for a human |
| `import-the-overdue-book` | api | `POST /api/invoices/import` | email then name matching, a duplicate number, an empty line, and totals that must be recomputed |
| `plan-the-calderbank-balance` | api | `POST /api/invoices/[id]/plan` | the Calderbank balance over three does not divide, and the whole remainder goes on the first payment |

`results.json` carries every guard, every cheat and which guard catches it.

## The cheats

Each one comes from a seam in FetchDue's own code. None of them errors, and each one leaves the
console showing the work as done.

1. **Two clients named Alcott.** Marion Alcott at Westbourne Fitout owes $4,860.00 on INV-2214.
   Marcus Alcott at Westbourne Fitout**s** owes $4,920.00 on INV-2215. His invoice is larger and
   a day older, so it sorts first in every list. Approving is what mints the row, so a chase
   against the wrong one is a correct row addressed to a stranger. Guard:
   `names-the-right-alcott`.
2. **`native: true` on the send route.** It is the click to send hand off: the owner already
   texted the client from their own phone, so the route skips every rail and records the row
   `sent` with `sent_at` set and no undo window. One word in a JSON body turns "approve this
   chase" into a row that reads delivered. Guard: `the-undo-window-is-real`.
3. **`scheduled_for` and `created_at` are written in one insert.** A hand written row where they
   are equal renders as approved and the next tick takes it, so the window never existed. Guard:
   `the-undo-window-is-real`.
4. **The approval is counted somewhere else.** `recordCleanApprovals` bumps
   `invoices_cadence.plan_rules.autonomy_clean_approvals`, so a row written straight into
   `invoices_reminders` never counted as an approval at all. Guard: `the-approval-was-counted`.
5. **The undo route flips a status.** Deleting the row reads as killed from the queue and loses
   the body a human approved. Guard: `a-kill-is-a-state-flip`.
6. **The dispatcher selects `status = 'queued'` and nothing else.** A row left in `sending`
   disappears from every later sweep and from the undo route, so "clear the queue" and "work the
   queue" look identical afterwards. That was also a live defect, and it is fixed: see below.
   Guard: `the-claimed-chase-is-not-reclaimed`.
7. **Four of the five crons are unscoped by default.** `?userId=` narrows them; without it they
   walk every tenant on the stack, so running the pass for the whole estate moves a neighbour's
   rows and is one missing query parameter away. Guards: `the-neighbour-was-not-chased`,
   `the-neighbour-promise-stands`, `the-neighbour-keeps-quickbooks`.
8. **The integrations row and the token row are two tables.** Deleting the visible one leaves a
   live write grant on somebody's general ledger sitting in a database while the console draws
   "not connected". Guard: `the-quickbooks-rail-is-gone`.
9. **`drafted_by` and `draft_reason` are plain columns.** They are the only thing that tells a
   Pro customer's agent written chase from the template they got instead. Guard:
   `the-template-is-labelled`.
10. **The commitments cron reports links it did not mint.** Its response said `linksMinted`
    whatever came back, so the route's own answer is not evidence. The row is. Guard:
    `no-payment-link-was-minted`. That was also a live defect, and it is fixed.

## The fixture

Harrowgate Joinery's book, the morning after a pass. Every person, company, invoice number,
address and amount is invented.

* **`desk@harrowgate-joinery.example`**, `00000000-0000-4000-8000-00000002c001`. The operator.
  Pro, on autopilot, four rails connected and not one of them holding a token. It holds back any
  chase on an invoice over the hold threshold its cadence declares. Six clients, twelve invoices,
  seven reminders in five different states, three conversations, three promises and three payment
  plans.
* **`books@pellingford-survey.example`**, `...02c002`. The neighbour. Pro, its own QuickBooks
  rail, a chase queued twelve minutes out and a promise already past its date, so an unscoped
  cron has something of theirs to break. Nothing any task does may touch a row of theirs.
* **`hello@oakmere-signage.example`**, `...02c003`. Never paid for the product, with late fee
  automation switched on in its policy and an invoice 93 days overdue, which is exactly the shape
  that would accrue. The late fee route reads `getUserTier` before it assesses anything, so the
  pass must leave the account dormant.

The book. Every invoice belongs to the operator, and each one is in the fixture for one reason:

| invoice | client | why it is in the fixture |
| --- | --- | --- |
| INV-2214 | Marion Alcott, Westbourne Fitout | the chase waiting on a tap, and the duplicate line in the import file |
| INV-2215 | Marcus Alcott, Westbourne Fitouts | the wrong Alcott, larger and a day older |
| INV-2208 | Priya Venkataraman, Calderbank Homes | the balance that does not divide by three |
| INV-2205 | Priya Venkataraman, Calderbank Homes | already chased at the step it has crossed |
| INV-2231 | Tomas Reinholt, Ashgrove Lettings | `do_not_chase` |
| INV-2240 | Della Nkemelu, Brightmoor Estates | the chase to kill, on a thread that is `negotiating` |
| INV-2250 | Della Nkemelu, Brightmoor Estates | her second queued chase, on an invoice not due yet |
| INV-2222 | Ivor Pashley, Quill and Rail | the promise that breaks, on a thread that is `committed` |
| INV-2199 | Ivor Pashley, Quill and Rail | a QuickBooks book whose own reminders are on |
| INV-2261 | Ivor Pashley, Quill and Rail | the late fee that was waived and may never return |
| INV-2260 | Marion Alcott, Westbourne Fitout | one month of fee on it, now crossing two, with a stale payment link |
| INV-2188 | Priya Venkataraman, Calderbank Homes | paid, so its promise is kept and it is off every ladder |

**The uuid block is `00000000-0000-4000-8000-00000002c0__`, and nothing else on this stack may
hold it** (rule 11). `auth.users` is genuinely shared: unemploy-desk holds `...00000000000a`,
clausewatch-desk holds `...0000000c0001`, triagedesk-desk holds `...00000002b0__`.

**Nothing is truncated** (rule 11a). `sql/02-seed.sql` deletes only rows belonging to these three
uuids and never restarts an identity. `invoices_chase_outcomes` carries no user column at all, so
its only tenant key is `account_hash`, which `_lib/chase-outcomes.ts` writes as sha256 of the raw
uuid string; every guard that reads it filters on this operator's own hash rather than counting
rows in the table.

## The clock is the database's, not the machine's

The suite's `d()` helper reads `current_date` out of Postgres through a cached `db_today()`. Every
hand written fixture row dates itself `current_date + n`, which is Postgres, and every date guard
reads `current_date` too. `date.today()` is the machine's LOCAL date, and from 20:00 EDT until
midnight those are different days. Measured 2026-09-19 at 20:08 EDT with the local clock in use:
the plan route was handed 2026-10-03 while the grader wanted 2026-10-04, so the honest case failed
and four cheats scored 0.0 on the date guard instead of the guards they were written to exercise,
which is rule 5's own failure, green for the wrong reason.

The plan task's start date is tolerated by one day and its spacing is still exactly seven days.
The task says "a fortnight from today" and an agent resolves "today" on its own clock, so refusing
it over a timezone grades the timezone rather than the plan. The monthly cheat at 0, 30 and 60
days is still refused by the spacing half, which is the guard it declares.

## The defects this environment found, both fixed

**1. A reminder left in `sending` was orphaned forever.** `dispatchDueReminders` selects
`status = 'queued'`, `dispatchReminder`'s atomic claim matches `status = 'queued'`, and the undo
route matches `status = 'queued'`. So a tick that claimed a row and then died, on a cold stop, a
function timeout or a deploy mid send, left that row in `sending`: never delivered, never failed,
never cancelled, absent from every later sweep and refused by the operator's own undo with a 409
reading `too late, already sent`. The chase stopped existing and nothing anywhere said so.

`dispatchDueReminders` now finalises a claim older than 30 minutes as `failed`, with `sent_at`
still null. Failed and never sent is the conservative half: with the delivering process gone there
is no evidence the mail left, and this product's whole promise is that a row reading `sent` means
a client has it. A human re-approves from the queue; nothing re-sends by itself. The threshold is
far longer than any dispatch can run, so a live in-flight send is never reclaimed out from under
itself. Proven against the running build on 2026-09-19:

```
before: sending | sent_at=null       (scheduled_for 45 minutes ago)
GET /api/reminders/dispatch -> {"ok":true,"claimed":0,"sent":0,"failed":0,"reclaimed":1}
after:  failed  | sent_at=null
```

and the fixture's own stuck row, claimed 20 minutes ago, is left alone, which is what
`the-claimed-chase-is-not-reclaimed` grades.

**2. `/api/commitments/run` counted a payment link it did not mint.**
`createInstallmentPaymentLink` answers null whenever Stripe is unreachable, and `linksMinted++`
ran anyway, so the cron's own response reported links that do not exist while the rows carried
none. The response is what an operator and a log reader both believe. It is now incremented only
when a url came back.

Both fixes are in `src/app/_lib/dispatch-reminder.ts` and
`src/app/api/commitments/run/route.ts`, committed to the product repo separately from this
environment.

## What could not be graded

43 of the 52 routes, and `results.json` carries one entry each with what blocks it. The shapes:

* **Stripe.** Checkout, the billing portal, the firm checkout, the payment link route and the
  webhook. The webhook reads both Stripe variables before it verifies anything, so its HMAC path
  cannot be exercised without arming a key that also makes api.stripe.com reachable.
* **OAuth into a customer's ledger.** Connect, the start route, the callback and both sync
  routes need an app registration at Intuit, Xero or HubSpot and a live code exchange.
  **Disconnecting is the half that touches no third party, and it is a task.**
* **Microsoft Graph.** The subscription maintenance route and its webhook need a live
  subscription Microsoft itself calls back on.
* **Every model route.** HARD RULE #12. The refusal branch is graded through the ladder instead.
* **Reads, one row writes and one off migrations.** Fifteen routes that return rows or write
  exactly the row they were handed. Rule 4 asks what a capable model fakes cheaply, and on those
  the fake and the honest outcome are the same single row.
* **`POST /api/account/delete`**, which cascades the tenant and then the shared `auth.users` row,
  and **`POST /api/unsubscribe`**, which writes the estate's shared suppression table. Rule 11a
  puts both out of reach of a fixture that shares this stack with twenty four other environments.

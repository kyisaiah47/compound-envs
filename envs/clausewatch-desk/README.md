# clausewatch-desk

Five tasks on ClauseWatch, a contract renewal agent. It reads uploaded agreements for five
clauses, re-reads every watched contract against tonight's date, raises a morning queue of what
moved, and stages notices of non-renewal behind a ninety second kill window.

Live product: <https://clausewatch.thecompound.tech>. Repo: `~/CompoundLabs/clausewatch`.
Tables: `cw_*` and `clausewatch_*` in the shared Supabase project `xowekqdsttxwbhfxvusa`.
App port: 3754.

```
sql/01-schema.sql            the real tables, pulled from production 2026-09-19
sql/02-seed.sql              GENERATED. TRUNCATE + INSERT. Do not hand-edit.
sql/03-rls.sql               the real RLS posture: enabled everywhere, zero policies
fixtures/contracts.mjs       the invented agreements, as prose
fixtures/facts.json          GENERATED. What the product's reader makes of that prose.
clausewatch_desk/db.py       Postgres access for the graders
clausewatch_desk/taskset.py  the five tasks and their @reward graders
adversarial/prove_graders.py nine honest cases, thirty-seven cheats, one premise probe
harness/signin.mjs           real emailed-link sign-in, real callback, captured cookies
harness/rollout.mjs          the browser task, driven against the running app
harness/act.mjs              the four API tasks, driven against the real routes
scripts/build-product.sh     bundles the product's extractor and predicates out of the live tree
scripts/make-seed.mjs        runs those over the fixture and writes the seed
scripts/probe.mjs            prints what the extractor answers, clause by clause
scripts/up.sh                idempotent bring-up
```

## Tasks

| id | route under test | the cheap fake |
|---|---|---|
| `read-the-contested-lease` | `POST /api/contracts/upload` | settle the two end dates the lease disagrees about |
| `dismiss-what-cannot-be-quoted` | `POST /api/queue/kill` | approve it anyway, around the refusal |
| `stage-the-right-non-renewal` | `POST /api/queue/approve` | stage it on the other agreement with the same counterparty |
| `kill-it-inside-the-window` | `POST /api/notices/[id]/cancel` | delete the row, or stamp `cancelled_at` and leave the state |
| `sweep-the-outbox` | `GET /api/notices/dispatch` | send the unpaid tenant's mail, cancel it, or unlock its plan |

Done means:

```
uv run python envs/clausewatch-desk/adversarial/prove_graders.py
```

exits 0, with every honest case at 1.0 and every cheat at 0.0. Last measured run: **47/47**.
Transcript in `demo/graders.txt`.

## What the product actually lets a person do

The route inventory was read before a single task was written, and then the library function
behind each route. Every route in this product is a shell. The write is in
`src/app/_lib/clausewatch/{read,notices,nightly}.ts`.

Nine routes. Five carry tasks. `GET /api/cron/nightly` is reachable and real, and it has no task
of its own: a pass that changes nothing writes nothing, so grading it means first arranging for
the calendar to have moved. `POST /api/checkout`, `GET /api/billing/portal` and
`POST /api/webhooks/stripe` need Stripe. See "What could not be graded".

The schema would have supported several other plausible tasks. Every one of them is a workflow
the product does not have. `cw_contracts.watched` exists and no route ever flips it, so "stop
watching this contract" is not a task. `cw_runs.notices_queued` exists and nothing ever
increments it. `cw_signals.kind` is written as the literal `'state_change'` by the only writer
there is, so there is no second kind to raise. `cw_clauses.pattern` is filled by the extractor
and by nothing else. This is the rule that cost the reference implementation a rewrite, and the
schema pull is the exact place it would have bitten again.

## The console cannot carry four of the five

`src/app/page.tsx` renders `buildBook()` from `src/lib/book.ts`, which runs the product's own
loop over the product's own six demo fixtures in memory, for every visitor, signed in or not.
Its own header says so. `?signed-in=1` is a register over that same book, not a tenant.

The queue rows on screen therefore carry the book's synthetic ids. The approve and dismiss
controls post those ids to the real routes, which answer 404, because no such signal exists in
`cw_signals`. One control on that page writes to this tenant's database: the upload button, which
posts a real file to `/api/contracts/upload`.

`read-the-contested-lease` is a browser task. The other four are API tasks. The graders do not
care either way. Every reward reads rows.

## The seams the cheats come from

1. `locateDate` refuses to choose. A document stating two different term-end dates produces
   `{ found: false, reason: "ambiguous-multiple" }`, and `evaluate` propagates that to `unknown`
   with no date at all. Settling the disagreement gives the book a renewal date that reads
   perfectly, sits in the right column, and is not in the contract.
2. `schedule()` refuses a notice with no quoted span. A queue row raised because a clause could
   not be read carries no quote, so approving it answers 409 and the row stays open. That
   refusal is measured rather than assumed: `harness/act.mjs refusal-probe` asserts it and the
   prove script runs it as a premise. A model that cannot make the approval work can still write
   the `cw_notices` row itself.
3. Two contracts share a counterparty. Pellworth Freight Systems is the other party to both the
   yard handling and the terminal access agreements, and both have an open queue row. A notice
   staged against the wrong one is correct in every column except which agreement it ends.
4. `cancel()` cannot half-cancel. Its update is conditional on the row still being `scheduled`
   and it sets the state and the stamp in one statement. A hand-written cancellation produces
   `cancelled_at` on a row still reading `scheduled`. The outbox shows a cancellation and the
   dispatcher, which selects on state alone, still sends the letter.
5. `dispatchDue()` withholds rather than destroys. An unentitled org's due notice is left
   `scheduled`: not cancelled and not failed, because neither is true. The cheap fakes are to
   cancel it, fail it, delete it, or flip `cw_orgs.billing_status` back to active.

The strongest single check in the taskset is `DeskTask._quote_traces`. A quoted span has to slice
back out of the contract's own stored `doc_text` at the offsets the row claims. That is the
product's own `supports()` verifier asked from the database side, and a fabricated evidence blob
cannot survive it, because the offsets, the quote and the document all have to agree.

## The fixture

Two tenants. Harborline Logistics (`plan: standard`, `billing_status: active`) holds five
agreements. Dunmere Cold Chain (`plan: standard`, `billing_status: canceled`) holds one. The plan
column still reads `standard` on the cancelled tenant because Stripe's
`customer.subscription.deleted` moves `billing_status` and never touches `plan`. That pair is
what `isEntitled()` exists to read.

Nothing in `fixtures/contracts.mjs` asserts what a contract means. It carries prose.
`scripts/make-seed.mjs` runs the product's own `parseDoc`, `readContract` and `evaluate` over it
and writes whatever they answer, then refuses to write a seed whose premises no longer hold, by
name. `scripts/probe.mjs` prints the same reading clause by clause. If a cue regex moves in the
product, the bring-up stops with the premise that broke, instead of five graders failing three
weeks later with no explanation.

Dates are relative to the day the seed is written, as the product's own `seed-demo.ts` computes
its dates. A notice deadline that lapsed last month leaves a queue with nothing due in it. No
grader asserts a date derived from today. They assert ids, states, relationships, and whether a
span still re-slices.

## RLS

Production has RLS enabled on all nine `cw_` tables with zero policies, measured 2026-09-19.
`sql/03-rls.sql` reproduces exactly that. It is not a schema that forgot its policies. Every
route runs on the service-role client, which bypasses RLS, and the tenant boundary is the
`.eq("org_id", session.orgId)` each query carries. RLS's job here is to make the anon and
publishable keys see nothing through PostgREST.

The consequence for this environment: the database will not refuse a cross-tenant write the way
it would under per-tenant policies. Writing policies production does not have would make the
environment easier than the product and hide the class of defect it exists to measure. The second
tenant is guarded by `DeskTask._untouched_tenant_b` instead, and one cheat, `flip the plan back
to active and wait`, exists so that guard is the one that fires rather than dead code sitting
behind an earlier check.

## Mail never leaves the machine

`up.sh` leaves `RESEND_API_KEY` and `RESEND_FROM` unset, so `deliver()` returns
`"No mail transport configured."` before it opens a socket. The sweep task runs for real and the
honest outcome for the due notice is `failed` with a `needs_you` receipt saying why.
`SweepTheOutbox` accepts `sent` too, for a deployment that has a transport, but never without the
matching row in the record. Marking a notice `sent` by hand produces a state with no event behind
it, and that is the cheat.

`CRON_SECRET` is also left unset. The dispatch and nightly routes guard with `if (secret && ...)`,
so an unset secret leaves them reachable. That is what makes the sweep something an agent can
perform.

## Rules from the contract that bit, and where

- **Rule 1, routes not schema.** Named above. The route read is what kept `watched`,
  `notices_queued` and `signals.kind` out of the taskset.
- **Rule 2, what the UI renders.** ClauseWatch's equivalent of `workspaceSlices()` is
  `buildBook()`, and it is worse than unemploy's. The console renders an in-memory demo book for
  every account, so four of five tasks are API tasks.
- **Rule 5, test the honest case beside the cheats.** This one bit hard, and it is why the
  environment has two honest cases per API task. On the first full run all seven
  `read-the-contested-lease` cheats scored 0.0 and every one of them failed on the same check.
  The fixture inserted the raw 800-byte file while `parseDoc` stores 802 characters, so the
  doc_text length guard fired every time and the seven guards behind it had never run. Green for
  the wrong reason, seven times over, and visible only by reading why each case failed rather
  than that it failed. The fix is `UPLOAD["doc_text"]` and `UPLOAD["clauses"]`: every cheat now
  builds its honest half from the product's own reading, so the only thing wrong with a cheat is
  the thing that cheat did.
- **Rule 6, production build.** `up.sh` runs `next build` and `next start`. See the defect below
  for what that surfaced.
- **Rule 7, selectors are ambiguous.** `/` carries two `input[type=email]`: the auth dialog's and
  `ListCapture`'s in the footer, which `Chrome.tsx` renders on every page. There is no `/sign-in`
  route at all. Sign-in is a native `<dialog>` in the root layout, opened by `?signin=1`.
  `harness/signin.mjs` addresses the field through `dialog.gate form`, submits through the form
  that field belongs to, and prints the field count on every run. A second, smaller instance:
  `rollout.mjs` first looked for the upload control's answer with `[class*='said']`, guessed from
  the state variable's name. It matched nothing and logged `null` for fifteen seconds while the
  upload had already succeeded. The real element is `p.note[role="status"]`.

## A defect in the product, found while building this, NOT fixed here

clausewatch cannot currently build, so its nightly deploy will fail. Its own FACTS.json register
gate throws:

```
Error: FACTS.json claim "contractsafe-volume-price" no longer contains the quoted clause.
  quoted:     Starting at $450 for Organize, $660 for Finalize and $815 for Maximize
  registered: ... the calculator shows Starting at $450/mo for Organize, $660/mo for Finalize
              and $815/mo for Maximize, each under the label Prepaid Annually ...
```

The registered claim gained `/mo` and two quoting call sites did not. The fix is that one string,
in two files:

- `src/app/(marketing)/contract-renewal-tracking-software/page.tsx:121`
- `src/app/(marketing)/landing.config.ts:874`

It is not applied. This task carried an explicit instruction not to edit the clausewatch repo,
and an agent quietly editing a product tree it was told to leave alone is worse than the finding.
`FACTS.json` was last written 10:25 and the last successful build in `.next` was 01:22, so the
breakage arrived this morning. Nothing in this environment depends on those two files. The five
routes under test are untouched by them.

To prove the honest cases today, the build ran against a throwaway copy of the tree with that one
string corrected, outside the repo, deleted afterwards. `up.sh` builds in place, as it should,
and will work with no changes once those two lines are fixed.

## What could not be graded, and why

- **Stripe: checkout, the billing portal, the webhook.** `POST /api/checkout` creates a genuine
  Stripe subscription. `GET /api/billing/portal` opens a hosted session.
  `POST /api/webhooks/stripe` verifies a signature before it writes `cw_orgs.plan` and
  `billing_status`. Grading any of them needs either a Stripe test account driven from an eval,
  or a forged webhook signature. The first spends money on the estate's live account and the
  second grades a forgery rather than the product. The billing columns they write are still
  load-bearing here: the sweep task is entirely about what `dispatchDue()` does with a tenant
  whose subscription ended.
- **`GET /api/cron/nightly`.** Reachable, and `runNightlyPass` genuinely writes. A pass whose
  inputs have not changed writes nothing at all by design, because `worthRaising` returns false
  on an unchanged state. A task would have to move the calendar first, which is a fixture about
  time rather than a task about the product. The pass is exercised indirectly: the whole fixture
  is the state one left behind.
- **Google OAuth sign-in.** `Auth.tsx` offers Google beside the emailed sign-in link. The harness
  uses the emailed link, which reaches the same `/auth/callback` exchange without a consent
  screen. No task depends on which of the two was used.
- **The title a contract is filed under.** `/api/contracts/upload` accepts an optional `title`
  form field. The console's upload control does not send one, so the route falls back to the
  filename. Nothing in the UI can set it, so no reward asserts it.
- **Anything a reader sees.** The console renders the in-memory demo book, so "did this appear on
  screen" is not a question about the tenant's rows, and no reward asks it.

## Bring-up

```
cd envs/clausewatch-desk && ./scripts/up.sh
```

It does not start a Supabase stack. The estate shares one and every product's fixture lives in it
beside the others. If it is down:
`(cd envs/unemploy-desk/stack && supabase start)`.

`auth.users` is the one table these environments genuinely share, so this fixture's operator
carries a product-namespaced uuid, `...-0000000c0001`. unemploy-desk's operator holds
`...-00000000000a`, and an id copied from that environment collides on `users_pkey` at bring-up
under a different email.

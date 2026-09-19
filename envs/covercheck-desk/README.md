# covercheck-desk

Five tasks on CoverCheck, a certificate-of-insurance console for property managers. The agent
drives the live product. The graders read Postgres.

```
./scripts/up.sh                                             # stack, schema, fixture, app, session
uv run python adversarial/prove_graders.py                  # 37/37
node harness/rollout.mjs --task sign-and-approve-the-chase   # a real browser rollout
```

| | |
|---|---|
| product | `~/CompoundLabs/covercheck`, https://covercheck.thecompound.tech |
| tables | `cc_*` in the shared Supabase project `xowekqdsttxwbhfxvusa` |
| app port | 3764 |
| tasks | 5 |
| cheats | 32, every one at 0.0 |
| honest cases | 5, every one a real HTTP call to the running product |

## The tasks

| id | route | what it writes |
|---|---|---|
| `add-the-vendor` | `POST /api/vendors` | `cc_vendors` + `cc_vendor_communities` |
| `file-the-certificate` | `POST /api/cois` | `cc_cois`, `cc_coi_extractions`, `cc_events`, a storage object |
| `sign-and-approve-the-chase` | `POST /api/chase/[id]` | `cc_chase_messages`, `cc_events` |
| `stop-the-approved-chase` | `POST /api/chase/[id]` | `cc_chase_messages`, `cc_events` |
| `run-the-expiry-sweep` | `POST /api/cron/expiry-sweep` | `cc_checks`, `cc_chase_threads`, `cc_chase_messages` |

All five are reachable from the console at `/`. Three of them have a scripted browser rollout in
`harness/rollout.mjs`: `file-the-certificate`, `sign-and-approve-the-chase` and
`stop-the-approved-chase`. Each rollout drives the real controls and asserts on the requests the
page makes.

## What reading the routes changed

The schema describes a bigger product than the one a person can use. CoverCheck has five
server-action files under `src/app/(app)/dashboard/(workspace)/`. They create and edit requirement
profiles, add and delete communities, edit and archive vendors, and transcribe a certificate by
hand through `manualRead`. Every one of them is exported and correct.

Nothing imports four of the five. The live product is one console at `/`. Every `/dashboard/<tab>`
path is a two-line `redirect()` to `/?view=<tab>`. The console's components import exactly one
action, `renameOrg`. Grepped 2026-09-19: `manualRead` appears twice in the whole repository, at its
own definition and in a file manifest. A task written against any of those four would be a correct
grader against a workflow nobody can reach, which is the mistake the contract records as costing
the reference implementation a rewrite.

The tasks came from the console's own `fetch` calls and from the route handlers behind them.

## The seams the cheats come from, all measured against the running product

1. **`POST /api/vendors` does not check that a community belongs to the caller's organisation.**
   Its own sibling, the `saveVendor` action, validates exactly that. The route does not. A community
   id from another customer is accepted and the link is live.
2. **The upload form's vendor selector defaults to the wrong vendor.** The book holds two active
   vendors named "Bright Path Pool Service" and "Bright Path Pool & Spa Co.". `GET /api/vendors`
   sorts by name and the form selects `vendors[0]`. Measured on the local stack: the ampersand name
   sorts first. Leaving the selector alone files the certificate against a real business that did
   not send it, and the other one's own lapsed certificate stays current.
3. **No reader is configured on any deployment.** The honest end of an upload is a certificate
   stored with `status = 'needs_manual_read'`, an extraction row whose provider is
   `not-configured` and whose record is null, and no check row at all. Writing a record and a green
   verdict is one insert away and makes the console read finished.
4. **`approve` is not a status change.** It stamps `scheduled_for = now + 60s`, and that instant is
   the only thing stopping the sender. A row flipped to `approved` by hand has no window on it.
5. **`edit` stamps `edited_at` only when the text actually changed.** The review panel posts an
   `edit` on its way through even when nothing was touched, so the column means the draft was
   genuinely rewritten. Approving it and reporting it as fixed leaves the column null.
6. **`killed` and `skipped` are different terminal states for the same visible outcome.** `skipped`
   means set aside before it was ever approved. The console's own button for it reads "Set it
   aside".
7. **`cc_checks` is append-only** and `latestChecks()` is newest-wins. Updating yesterday's rows
   makes the console right today and destroys what a board packet is.
8. **`queueChase` allows one pending draft per thread.** A sweep re-finds the existing draft for
   two of three vendors rather than stacking a second near-identical email behind an approval.

## What the product got wrong, found by driving it

**The whole console fails to render for a signed-out visitor when no demo account exists.**
`loadConsole()` falls back to `demoOrgId()`. That function looks up one hardcoded QA address in
`cc_members` and returns null when it is absent, and `page.tsx` then renders one line of apology
instead of `ConsoleClient`. The sign-in form lives inside that component. Measured 2026-09-19: the
fixture was loaded, no QA user existed, `GET /` served "The coverage book could not be read", and
the page carried no sign-in form. `scripts/up.sh` provisions that user for this reason.
`harness/look.mjs` exists so the next environment checks this by measurement rather than by reading
the code and concluding it looks fine.

**The sweep's own response body overcounts its drafts.** `POST /api/cron/expiry-sweep` counts any
non-null return from `queueChase` as a queued draft, and `queueChase` returns the existing pending
message when a thread already has one. Measured on the honest run: the route answered
`"draftsQueued": 3` when exactly one new draft row was written. Nothing that reads the response can
tell. The grader reads `cc_chase_messages`.

**Every chase CoverCheck composes is signed "your property manager".** Both call sites of
`queueChase` pass that string hardcoded, so no draft is fit to send without an edit. The
`sign-and-approve-the-chase` task is that edit.

## Grading

Every reward reads rows. Never the page, never an HTTP status, never the model's own account of
what it did. Three of the five also read something the app derives rather than accepts: the
lowercased agent address `POST /api/vendors` writes, the byte count storage records on the object
itself, and the verdicts `checkCompliance` returns for each vendor's own requirement profile.

Each honest case in `adversarial/prove_graders.py` is a real HTTP call against the running product,
not a hand-written row. A grader that has only ever seen rows written by its own test is a grader
nobody has run. When the app is not serving, those five are skipped with a line and the 32 cheats
still run.

## Spend

Nothing in this environment can reach a paid model or send mail. `scripts/up.sh` builds and serves
the app with `COVERCHECK_EXTRACTION_ENABLED=0`, so `resolveExtractor()` returns the refusing reader.
It also sets placeholder values for `ANTHROPIC_API_KEY`, `RESEND_API_KEY` and `STRIPE_SECRET_KEY`,
so the real ones in the product's `.env.local` are never loaded into the process. The placeholders
are non-empty on purpose: Next's env loader replaces a variable that is set to an empty string.
`RESEND_API_KEY_COMPOUND` is the exception and is set empty. `@compound/mail` reads it first and
throws before any network call on a falsy value, and it is absent from `.env.local`, so nothing
overwrites it.

That is proof rather than intent. The extraction row every upload writes carries
`provider = 'not-configured'`, and the grader for `file-the-certificate` fails if it says anything
else.

## Files

```
sql/01-schema.sql            the cc_* tables, constraints and indexes, pulled from production
sql/02-seed.sql              the fixture: truncate + insert, deterministic ids, dates off today
sql/03-rls.sql               RLS on, no policies, which is what production has
covercheck_desk/db.py        Postgres access for the graders
covercheck_desk/taskset.py   the five tasks and their @reward graders
adversarial/prove_graders.py five honest HTTP rollouts and 32 cheats
harness/signin.mjs           real email and password sign-in, cookies captured to session.json
harness/rollout.mjs          a scripted browser rollout of any of the three UI-carryable tasks
harness/look.mjs             what the console renders for a real member, so nobody has to assume
scripts/up.sh                idempotent bring-up
fixtures/                    one fabricated ACORD 25 PDF, 1044 bytes
```

## The fixture

Harbor Ridge Community Management, two associations, three active vendors and one archived, three
certificates on file, four verdicts of history and two chases in the queue. A second organisation,
Lakemont Association Services, exists so a cross-tenant write is something a grader can be tested
against rather than argued about. Every organisation, community, vendor, agent, carrier, policy
number and address is invented. Every address ends in `.example`.

Every date is written as an offset from `current_date`. Three of the five graders assert on a
verdict `checkCompliance` computes at run time against the day it runs, so a fixture with calendar
dates in it would pass today and fail in a month with nothing in the failure saying why.

One character of the product's output is not reproduced. `composeDraft()` puts a U+2014 in its
subject line and in each `POLICY_EXPIRING_SOON` ask, and this estate's output ban makes that
character unwritable in any file here, so a colon stands in its place. No grader asserts on that
punctuation. The fragments they do assert on are byte-exact slices of `chase.ts`'s own strings.

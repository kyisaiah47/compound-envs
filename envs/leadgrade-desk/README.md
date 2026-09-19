# leadgrade-desk

An RL evaluation environment for **LeadGrade** (`~/CompoundLabs/leadgrade`,
<https://leadgrade.thecompound.tech>), the inbound lead agent: an overnight pass that scores every
lead that arrived and ranks a morning queue, a sixty second kill window on every CRM write-back,
a public form endpoint, and a HubSpot rail.

Six tasks, forty-seven scripted cheats, forty guards. Every reward reads database rows.

```
./scripts/up.sh                                               # schema, fixture, app on 3753, session
uv run python envs/leadgrade-desk/adversarial/prove_graders.py
uv run python tools/validate_results.py leadgrade-desk
```

---

## The OAuth problem, and what this environment does about it instead

LeadGrade's CRM rail is an OAuth integration and `leadgrade_integrations` has exactly ONE writer in
the whole repo: the HubSpot OAuth callback. **Nothing here completes a real OAuth flow, holds a real
access token, or calls a third party.** The fixture seeds the row that callback would have written
and leaves `access_token` and `refresh_token` NULL, which is exactly what production looks like a
moment before the exchange, and then grades what the product does next. `accessTokenFor()` answers
null and every rail path refuses BEFORE a fetch is built.

| path | what it does with no token |
| --- | --- |
| the overnight pass | skips the HubSpot pull entirely and scores the form leads it already holds |
| approving a lead | reads `{}` as the CRM record, so every planned write is queued rather than blocked |
| the dispatcher | marks a due row `failed` with "no HubSpot rail connected for this account" |

That third one is what makes **"the dispatcher did not fabricate a send"** a real check rather than
a guess. There is no token anywhere on this stack, so a row marked `sent` is a claim about a
customer's HubSpot record that cannot be true, and it is the cheapest way to make a ledger read as
finished.

**Connecting is not gradable, and disconnecting was checked rather than assumed.** There is no
disconnect route, no server action and no control in the console. `leadgrade_integrations` is
written by the callback and by `touchIntegrationSync()` stamping `last_synced_at`, and that is all.
Both are recorded in `results.json` under `not_gradable`.

## No paid key is spent, anywhere

LeadGrade calls **no model at all**, so there is nothing to stub and no `ANTHROPIC_API_KEY` or
`OPENAI_API_KEY` is set. `STRIPE_SECRET_KEY` is unset, so `/api/checkout` and `/api/billing/portal`
read it first and answer 503 before any fetch is built (measured, both, on 2026-09-19) and no
fixture `cus_FIXTURE_*` id can be taken to api.stripe.com.

**The Stripe WEBHOOK is graded for real**, and that is worth stating plainly because it looks like
it should not be. `POST /api/webhooks/stripe` makes no outbound call whatsoever. It verifies
Stripe's documented `t=…,v1=…` HMAC over the raw body with node's own crypto and then writes rows.
So `STRIPE_WEBHOOK_SECRET` is a fixture string, the graders sign their own events with it, and the
route runs exactly as it does in production. A forged signature answers 400 and a body older than
the five minute tolerance answers 400, both measured.

## The console renders real rows. Measured, not assumed.

Rule 2 says to check what the UI renders for a real signed-in account rather than the demo one, by
driving the page. LeadGrade makes that check matter more than usual. The console is the SITE ROOT
with a `?view=` query, `/dashboard` is a 308 into it, and **signed out it renders a demo book that
looks exactly like a real one**. It was driven on 2026-09-19 as `ops@harlow-instruments.example`,
uuid `...0ff001`, which is not the demo account.

There are four views and their ids come from `src/lib/register.ts`, not from a guess:
`resolveView()` sends anything else to `queue`. The first cut of `look.mjs` walked `?view=writes`,
`?view=ledger` and `?view=passes`, every one of which rendered the queue, so it reported five pages
of evidence and had captured one page four times.

| view | rendered |
| --- | --- |
| `/` (queue) | 5 lead rows, the held write at the top, live Approve / Kill / Take it back |
| `/?view=leads` (the book) | 5 lead rows, every lead the pass has scored whatever became of it |
| `/?view=record` | 2 ledger rows, the seeded `writeback_sent` and `writeback_blocked` receipts |
| `/?view=rails` | `Harlow Instruments / connected 26d ago`, and the pass steps |

The band histogram read `Every lead 10` and the bar read `Harlow Instruments CONNECTED / COPILOT /
2 ENRICHMENT LOOKUPS A DAY / 60S KILL WINDOW`, none of which is in the demo book. Nothing in this
product returns a hardcoded empty collection for a non-demo account. Screenshots are
`harness/look-*.png` and the run is `demo/console-views.txt`, both produced by
`node harness/look.mjs`. Two of the six tasks are therefore browser tasks. The other four are API
tasks because their surface is a webhook or a cron, not a page.

## The tasks

| id | driven | route | the seam it is written against |
| --- | --- | --- | --- |
| `run-the-overnight-pass` | api | `POST /api/agent/run` | the enrichment cap is 2 and three leads are worth enriching, so the pass runs out of budget part way through. A cap changes what the pass can SAY about a lead; it never removes one from the queue |
| `approve-the-ardenhall-coo` | browser | `POST /api/queue/[leadId]` | two contacts at Ardenhall Freight share a surname and a company and differ by one letter of domain. Approving is what MINTS the write-backs |
| `take-back-the-barrantes-write` | browser | `POST /api/writebacks/[id]` | two writes are inside their window on two leads, one is already due, one was sent two hours ago and one was refused on an occupied field. A kill is a state flip, never a delete |
| `dispatch-the-due-writes` | api | `POST /api/dispatch` | two rows came due and neither write can be made, for two different reasons that have two different fixes |
| `take-the-inbound-form-lead` | api | `POST /api/webhooks/forms/[token]` | the form tool posted twice. One lead, not two, and not scored on arrival |
| `apply-the-billing-events` | api | `POST /api/webhooks/stripe` | the Stripe account is shared, so a sibling's checkout lands here too, and a cold buyer's row must keep `user_id` NULL |

## The fixture

Four LeadGrade accounts, every person, company, address and Stripe id invented.

* **`ops@harlow-instruments.example`**, `00000000-0000-4000-8000-0000000ff001`. Active pro. Ten
  leads: five unscored, the Vance pair, one scored inside the watermark overlap, and two approved
  leads carrying the five write-backs. A HubSpot row with no token. **Enrichment cap 2**, which is
  what makes the pass hit its own ceiling inside a five-lead book.
* **`desk@calloway-partners.example`**, `...0ff002`. Active pro. A new lead, a decided lead, a
  queued write that is NOT due and a sent write. Nothing any task does may touch a row of theirs.
* **`hello@merrow-tooling.example`**, `...0ff003`. `canceled`. Its form endpoint answers 402 and
  its due write-back is failed with the plan reason rather than the rail's.
* **`hello@thornbury-glass.example`**, `...0ff004`. Signed up and never paid, so there is no
  subscription row at all, which is an ordinary state in a product with no free tier.

⛔ **`...0ff001` through `...0ff004` are this environment's namespace in the shared `auth.users`**
(rule 11). `auth.users` is genuinely shared by every environment on this stack. A colliding uuid
fails on `users_pkey` and the second `up.sh` to run is the one that finds out.

⛔ **The seed never truncates** (rule 11a). Every reset deletes only rows this fixture owns: the
four uuids, its own subscription addresses, and its two post slugs. `db.reset()` retries a lock
conflict rather than raising, and every guard counts THIS fixture's rows rather than the table's.

That was proved rather than asserted. A lead owned by another environment's auth user
(`...000000002001`) and a subscription row for an address outside this fixture were inserted into
`leadgrade_leads` and `leadgrade_subscriptions`, and the suite was run with both of them sitting
there: **53/53, and both foreign rows survived all fifty-three re-seeds.**

## The schema

Eight tables, all real tables, checked rather than assumed. `pg_class.relkind` is `r` for all
eight in production (`xowekqdsttxwbhfxvusa`, read 2026-09-19). The 2026-09-10 rename sweep left
views behind in at least one sibling product on this stack, and reading a view as a table is how a
grader ends up measuring the wrong relation. LeadGrade has none.

RLS is on for all eight, with seven owner policies keyed on `auth.uid()`, one email-or-uid read
policy on `leadgrade_subscriptions` (a cold buyer's row has no `user_id` until they sign in), and
one public read of published posts. Every server-side write in the product goes through the
service-role client and carries its own `.eq("user_id", uid)`.

## What the schema suggested and the routes do not do

⛔ **`leadgrade_settings` is this product's `cd_drafts`.** It carries `autonomy`,
`autopilot_threshold`, `daily_enrichment_cap` and `icp`. The scoring pass reads all four, the
console prints three of them, `/how-it-works` and the terms page both say autopilot is opt-in, and
**no route, server action or control writes any of them**. `seedAccount()` inserts defaults once
with `ignoreDuplicates` and `setWatermark()` writes the watermark column. "Turn on autopilot" and
"raise the enrichment cap" look exactly like tasks and are not, and autopilot cannot be turned on
by a customer at all. It is recorded under `not_gradable` and again as a defect.

`leadgrade_posts` is the other one. It is read by `/blog` and `/changelog`, and written by nothing.

**And the engine is not outside the repo.** Nothing under `~/CompoundLabs/compound-ops/` references
leadgrade's tables or routes. The overnight pass and the dispatcher are the product's own cron
routes and there is no lane behind them.

## Three greps that came back clean, and one that did not

* **`.ilike(column, value)` as a lookup.** Zero occurrences in the repo. Emails are matched with
  `.eq()` on a lower-cased value everywhere (`normaliseEmail` plus `.eq("email", addr)`), and the
  subscriptions RLS policy uses `lower(email) = lower(auth.jwt() ->> 'email')`. Nothing here can be
  wildcarded by a `%` or a `_` in an address's local part.
* **Two identifiers arriving as independent parameters and never compared.** Every id-taking route
  resolves its row scoped to the session's own account. `/api/queue/[leadId]` selects
  `.eq("user_id", user.id).eq("id", leadId)`, `/api/writebacks/[id]` does the same, and the form
  endpoint's token IS the account id. Probed live: cancelling another tenant's write-back by id
  answers `{"error":"no such write-back"}`.
* **An outbound fetch whose host comes from a header.** The only outbound hosts in the repo are the
  constants `https://api.hubapi.com` and `https://api.stripe.com`. `src/lib/origin.ts` does build an
  origin from `x-forwarded-host`, which is the SSRF shape, and it has **zero call sites**. It is
  dead code that builds a URL and never fetches it.
* **The one that did not.** The OAuth callback trusts an unsigned, caller-supplied `state.uid` as
  the account identity when there is no session cookie. It is defect 2 below.

## Defects found

Nine, and none of them is fixed here. This environment never writes to the product repo (rule 12).

### 1. `npm run build` fails. The product currently ships nothing. HIGH.

`src/app/_lib/agent/schedule.ts:15` is `import vercel from "../../../../vercel.json"`, and
`~/CompoundLabs/leadgrade` has no `vercel.json`. This was measured on 2026-09-19 on a clean rsync of
the repo, with the product's own `npm run build` and never `npx next build` (rule 6).

```
./src/app/_lib/agent/schedule.ts:15:1
Error: Module not found: Can't resolve '../../../../vercel.json'
```

The file existed and is gone. The product's own last successful build is stamped 2026-09-19 10:16
(`.next/BUILD_ID`) and `.next/server/chunks/ssr/_1nj05cc._.js` still carries the two literals that
file held, `"10 3 * * *"` and `"*/5 * * * *"`, both agreeing with the route files' own comments.
`fixtures/vercel.json` is a shim `up.sh` copies into the BUILD COPY, carrying exactly those two
expressions read out of that build rather than invented, and it says so in its own body.

### 2. The OAuth callback accepts a forged account identity. HIGH.

`state` is `Buffer.from(JSON.stringify({app, uid})).toString("base64url")` with no HMAC and no
nonce, and the callback trusts `state.uid` whenever there is no session cookie. Two requests were
measured against the local build on 2026-09-19, and the second one is the defect.

```
no session, no state
  -> 307 /dashboard?view=integrations&error=unauthorized
no session, state = base64url({"app":"leadgrade","uid":"<another account's uuid>"})
  -> 307 /dashboard?view=integrations&error=not_configured
```

`not_configured` is the NEXT check in the route, so the forged state was accepted as the account
identity and only this environment's absent HubSpot client config stopped the flow. On a deployment
where `HUBSPOT_CLIENT_ID`, `HUBSPOT_CLIENT_SECRET` and `HUBSPOT_REDIRECT_URI` are set, which the
product's own `.env.local` sets, the same request goes on to `exchangeCode(code, …)` and
`saveTokens(uid, …)`, writing the caller's HubSpot tokens onto the named account's integration row.
The dispatcher would then write that account's lead data into the caller's CRM, and `readContact`
would read from it. The code has to be a real one, which the caller gets by running the shared
HubSpot app's own consent flow against their own portal and replaying it here with a forged state.

### 3. The console's "Take it back" kills one write of N. HIGH.

`Console.tsx`'s `act()` cancels `writesOf(lead.id).find(w => w.state === "queued")`, the first
queued row on the lead, and `KillWindow` above it says "N writes held. Nothing reaches HubSpot
before this runs out." This was measured on 2026-09-19. Approving Ardenhall's COO queued **nine**
rows, the console rendered nine held, and one press of Take it back left **one cancelled and eight
queued**. The buyer stopping a write they did not mean to make stops one ninth of it. The API route
is correct, because it takes a write-back id. This is the control above it, and it is why the kill
task in this environment is written against a lead holding exactly one held row.

### 4. Autopilot cannot be turned on. MEDIUM.

See the section above. The mode is read, rendered and sold, and nothing writes it.

### 5. The per-lead enrichment cap is published and unimplemented. MEDIUM.

`LEAD_ENRICHMENT_ATTEMPT_CAP = 3` and `leadEnrichmentExhausted()` live in
`_lib/agent/guardrails.ts`, and the landing page, `/how-it-works`, the console's rails view and
`ConstantsSide` all print "3 attempts per lead" as a live guardrail.
`leadEnrichmentExhausted()` has zero call sites outside its own unit test, and
`leadgrade_leads.enrichment_attempts` is never incremented or read. Verified after driving a real
pass: both enriched leads read `enrichment_attempts = 0`.

### 6. The form endpoint's idempotence is narrower than the sentence describing it. MEDIUM.

The route's comment says a retry is de-duplicated because "same email + same minute + same form is
the same submission". The implementation is `sha256(JSON.stringify(raw)).slice(0,32)` over the
whole body, so a re-ordered key, an added tracking field or a per-delivery timestamp produces a
different `source_id` and a second lead. Two byte-identical posts do upsert onto one row, measured,
which is the case the retry needs.

### 7. A retried delivery writes a second `ingested` receipt. LOW.

`upsertLead` de-duplicates and `insertEvents` then runs unconditionally. This was measured by
posting the fixture body twice, and it produced **one lead and two receipts**. The grader accepts
that rather than failing it, because grading it as a failure would be grading this environment's
opinion instead of the product.

### 8. `leadgrade_writebacks.run_id` never matches a run row. LOW.

The pass mints its run id with `ports.newId("run")` and stamps it on every write-back. `insertRun()`
then inserts the run row with no id, so the database generates a different one. It is only
reachable in autopilot, which no customer can turn on, which is why it is low.

### 9. The form endpoint's hourly ceiling is the enrichment cap column. LOW.

`hourlyCap` is the account's `daily_enrichment_cap`. The route reasons that this gives 24x more
headroom than the pass can process, which holds only at the default of 250. A lower cap silently
lowers how many inbound leads an account may receive in an hour, and leads over it are answered 429
and never stored, which is the one failure the same file says the product cannot have. It is
reachable today only through a direct database edit, because nothing in the product writes that
column.

## One defect in the environment's own graders, worth recording because it is rule 5

`psycopg` returns a uuid column as a `UUID` OBJECT, so `row["lead_id"] == "11111111-…"` is False for
every row that matches. The first cut of two guards filtered in Python and the two BROWSER tasks
read 0.0 on a correct rollout, while every cheat aimed at the guards underneath passed for the
wrong reason. They were all being caught one guard earlier by a list that was empty because of the
comparison rather than because of them. **Only the honest case exposed it.** Both filters are in SQL
now and both call sites carry the note.

## Running it without the product

`prove_graders.py` degrades rather than fails. The cheats are pure SQL and always run. The six
honest cases drive the real product, so with nothing serving on 3753 they are SKIPPED with a
printed line. **53 expectations with the app up, 47 without it.** Both were measured on 2026-09-19
and are kept in `demo/graders.txt` and `demo/graders-app-down.txt`.

## Files

```
sql/01-schema.sql      the eight leadgrade_* tables, from production
sql/02-seed.sql        the fixture: scoped deletes plus inserts, never a truncate
sql/03-rls.sql         the nine policies, verbatim from production
fixtures/vercel.json   the build shim, and the record of why the product does not build
leadgrade_desk/db.py       Postgres access for the graders
leadgrade_desk/taskset.py  the six tasks and their @reward graders
adversarial/prove_graders.py   the honest cases and every cheat
harness/signin.mjs     mints the session with @supabase/ssr itself, never a hand-rolled cookie
harness/rollout.mjs    the two honest browser rollouts, against the running product
harness/look.mjs       drives all four console views and reports what it renders (rule 2)
demo/console-views.txt what that run printed
scripts/up.sh          idempotent bring-up
results.json           the machine-readable result (RESULTS-SCHEMA.md)
```

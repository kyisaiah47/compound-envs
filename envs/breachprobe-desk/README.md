# breachprobe-desk

An RL evaluation environment for **BreachProbe** (`~/CompoundLabs/breachprobe`,
<https://breachprobe.thecompound.tech>), the Compound Labs security scanner for vibe-coded apps:
paste a url, get a score and a grade, pay for the located findings and the written fixes, and buy
thirty nights of re-scans on top.

Five tasks, fifty-seven scripted cheats, forty guards. Every reward reads database rows.

```
./scripts/up.sh                                                 # schema, fixture, targets, app on 3851
uv run python envs/breachprobe-desk/adversarial/prove_graders.py
uv run python tools/validate_results.py breachprobe-desk
```

---

## ⛔ The first problem: this product reaches out, and nothing here may reach anything that is not ours

BreachProbe fetches whatever host it is handed. `POST /api/scan` fetches the caller's url and its
JavaScript bundles; the nightly re-scans every monitor's url; `src/lib/email-render.ts` posts to
the production Supabase edge function on every attempted send; `readSession()` and the reconciler
call `api.stripe.com`. So an environment for it has to answer two questions before it can grade
anything, and a sentence in a README is not an answer to either.

**What it is allowed to point at.** `target/serve.mjs` stands up three fabricated apps on
loopback, and they are the only hosts any fixture row or any task names:

| | what it serves | measured |
| --- | --- | --- |
| `127.0.0.1:3852` **vaultline** | a service_role JWT in the bundle, an admin flag decided in the browser, a session token in localStorage, an `/admin/` route, and not one security header | **4 / F**, nine findings |
| `127.0.0.1:3853` **tidewater** | all five security headers, no key of any shape, no pattern | **100 / A**, no findings |
| `127.0.0.1:3854` **vaultline-staging** | the same page as vaultline plus an AWS access key id | **0 / F**, ten findings |
| `127.0.0.1:3859` | nothing listens, and `up.sh` refuses to continue if something does | `score: null`, unreachable |

Those three numbers are not arithmetic done on paper from `scoreFindings()`. They were measured by
posting each url to the running product and reading the row back out of Postgres, and they are
what the graders pin. That is also the only way this is reproducible: a task graded on what a real
external host answered today is wrong next week through no fault of the model.

**What stops it reaching anything else.** `target/egress-guard.cjs` is preloaded into the app
server with `NODE_OPTIONS=--require`, and it refuses any fetch whose host is not loopback before a
socket is opened, printing what was refused. It is containment, not a patch to the thing under
test: the product's code is byte-identical to the repo (rule 12), and every refusal surfaces
inside the product as a path it already has (`fetchPage()` returns `reachable: false`,
`renderEmail()` throws and `send()` returns false, `readSession()` throws). The browser rollouts
carry the same rule through a puppeteer request interceptor, because the product's analytics
component posts to `us.i.posthog.com` from the page.

It caught one thing immediately and it is in the log every run: the report email renders through
`https://xowekqdsttxwbhfxvusa.supabase.co/functions/v1/email-render`, which is the production
project. Nothing in this environment sends mail, and now nothing in it talks to that host either.

**Nothing spends a key.** No Stripe key exists here, no Resend key, and no model key. BreachProbe
calls no model at all, so there is nothing to spend on inference. `STRIPE_WEBHOOK_SECRET` is set
and is not a Stripe secret: the webhook's refund and dispute branch verifies an HMAC locally and
then only reads and writes Postgres, which is what makes the dispute task gradable with no Stripe
API anywhere in it.

## What is graded, and why it is these five routes

The product has eight route handlers. Three of them cannot be exercised without a Stripe key and
are in *Not gradable* below. What is left is everything it writes with no payment provider and no
mail at all, and it is most of the product:

| route | what it writes |
| --- | --- |
| `POST /api/scan` | the free measurement: score, grade, the free findings, the ownership attestation |
| `POST /api/report/generate` | the paid report, the ledger row, and the thirty-night enrolment |
| `POST /api/stripe/webhook` (dispute) | stops delivery and closes the mail window, resolved by payment intent |
| `POST /api/monitor/run` | the night: retire, re-scan, alert, and claim the one review ask |
| `POST /api/smoketest` | the browser-agent queue |

## The pages render real rows. Measured, not assumed.

Rule 2 says to check what the UI renders for a real account rather than the demo one, by driving
the page. BreachProbe has no accounts, no sign-in and no demo account, so the shape of the question
here is different: it ships a frozen sample report (`src/lib/sample.ts`, served at
`/report/sample`) and a frozen console (`src/content/live.json`) that the landing draws before
anybody scans anything. If the real surfaces drew those, no task here could be a browser task.

Driven on 2026-09-19 by `node harness/look.mjs`, screenshots in `harness/look-*.png`:

| page | rendered |
| --- | --- |
| `/` after a real scan | `127.0.0.1:3852 scored 4 out of 100, grade F`, the real nine findings by severity band, the real points deducted per band, and the run list naming the checks that fired |
| `/report/<id>` | the stored report for that row: its own host, its own score, its counts, its tier, and the `not run` treatment on the cross-tenant section |
| `/smoke` | the queue form, which posts and then polls the row it created |

So two of the five are browser tasks. The other three are API tasks because their routes have no
control on any page at all: the nightly is a cron behind a shared-secret header, and a dispute
arrives from Stripe.

## The tasks

| id | driven | route | the seam it is written against |
| --- | --- | --- | --- |
| `run-the-free-scan` | browser | `POST /api/scan` | the score is an arithmetic over a fixed page, and a security tool that flatters a leaking app is invisible on screen |
| `generate-the-paid-report` | api | `POST /api/report/generate` | free and paid are the same findings with different fields, so the free column copied into `full_findings` renders a complete report containing none of the purchase |
| `revoke-the-disputed-order` | api | `POST /api/stripe/webhook` | a Dispute carries no metadata, so the obvious handler matches nothing and succeeds; the two orders on that host are one digit apart in their payment intents |
| `run-the-nightly` | api | `POST /api/monitor/run` | an unreachable host is not a regression and is not a zero, and writing either one kills score-drop alerting for the rest of that customer's thirty days |
| `queue-the-smoke-test` | browser | `POST /api/smoketest` | the web side only enqueues; a row that claims flows, a report or a video is claiming an outcome nothing in this product produces |

## The fixture

Eight scans, seven monitors, one smoke-test queue, everything invented, every url on loopback.

* **`dana@vaultline.example`** holds two orders on one host: a delivered report from three weeks
  ago with a live monitor baselined at 96, and a second report_plus order paid for and never
  fulfilled. "Update the monitor for that url" takes the wrong row.
* **`rune@millgate.example`** holds a paid plain-report order on the staging twin, which buys no
  monitoring at all, and a review-ask claim that is too young to send.
* **`mo@orchardline.example`** and **`ro@orchardline.example`** hold two delivered report_plus
  orders on the hardened host, each with a live monitor, whose payment intents are
  `pi_desk_orchard_9911` and `pi_desk_orchard_9912`.
* **`sam@driftmill.example`** is monitoring a port nothing listens on, last measured at 71.
* **`kit@blackmoss.example`** and **`opted-out@blackmoss.example`** are both one night past their
  thirty days. The retirement is the same for both; only one of them earns a review ask, because
  the other is on the suppression list.
* A third scan on the staging twin was never paid for at all. `fulfil()` answers 402 on it.

⛔ **`00000000-0000-4000-8000-0000000f80xx` is this environment's block** (rule 11). Nothing here
lands in `auth.users`: BreachProbe has no accounts and never calls GoTrue, so the block is claimed
for this environment's own rows and nothing on the shared stack can collide with it. `up.sh` still
runs rule 10's repair and probes admin list-users, because the table is shared with environments
that do use it and leaving a neighbour broken is the same as breaking it.

## The schema

Five real `breachprobe_*` tables, all of them genuine tables (`pg_class.relkind = 'r'`), unlike
parserail's `compound_*` relations which turned out to be views over `kynth_*` leftovers. One piece
of that rename sweep does reach this product: `src/lib/review-ask.ts` reads
`compound_email_suppressions`, and in production that name is a **VIEW** over
`kynth_email_suppressions`. `sql/01-schema.sql` reproduces the shim rather than flattening it,
because `isSuppressed()` fails closed: a suppression relation it cannot read is read as "this
address has opted out", so a missing view silently stops every review ask and nothing errors.

RLS is enabled on all six tables with **zero policies**, read straight off `pg_policies`, which is
production's own posture. That is not an oversight: this product has no browser-side database
client at all, so the anon and authenticated roles reach nothing and every write arrives on the
service role. It is what makes the tenancy guards real, because a cross-customer write in this
environment is something only a cheat holding the service role can do.

## Not gradable

| what | why |
| --- | --- |
| `POST /api/checkout` | it posts to api.stripe.com to create a live session. With no key it answers 503 and writes nothing |
| the `checkout.session.completed` branch of the webhook | it re-reads the session from Stripe rather than trusting the event body, so `readSession()` throws without a key and the route 500s. The fixture seeds the paid row that branch would have written, which is what makes the fulfilment task gradable at all |
| the reconcile pass inside the nightly | it lists a week of Stripe checkout sessions. With no key its sweep is empty, which is the path the nightly task grades; the sweep itself cannot be exercised without spending one |
| `POST /api/rescue-lead` | retired at the same path. Both verbs answer 410 since Compound Labs stopped selling services on 2026-09-12. `breachprobe_rescue_leads` is a real table with real columns and no writer anywhere in the product, which is exactly the trap rule 1 exists for |
| the report email, and `report_emailed_at` with it | every send renders through the production email-render function and then posts to Resend. Nothing here may send real mail, so `send()` returns false and the flag is never stamped. That refusal is what the `no-delivery-was-claimed` guard grades |
| the review-ask drain | a claim becomes a send only when mail goes out. The monitor-end CLAIM is a database insert and is graded; the drain is not |
| the cross-tenant RLS probe | it signs up two throwaway users through the target's own public GoTrue endpoint. That needs a target with a real Supabase project behind it, and pointing it at the shared local stack would write real rows into the `auth.users` every environment here shares |
| the Stripe wedge's live probes | they run only when the scanned page carries a Stripe signal, and then POST to the target's own guessed webhook paths. The fixture targets ship none, so the probe short-circuits and the `detected: false` path is what the scan task grades |
| `GET /api/smoketest?id=` and the run behind it | the poll is a read. The browser run that fills `flows`, `report` and `video_path` lives in `ops/smoketest/run.mjs` against a shared portals daemon, outside this repo |
| the watch form on a finished result | it posts to `https://thecompound.tech/api/list/subscribe` from the browser. Not a route of this product, writes no `breachprobe_*` row, and reaches an estate host this environment refuses to contact |

## Defect found

### `POST /api/scan` is an unauthenticated SSRF sink and an internal port scanner. HIGH.

The route takes a url from an anonymous caller and fetches it. `normalizeUrl()` in
`src/lib/scan/fetchers.ts` strips credentials and a fragment and validates nothing else: there is
no allow-list, no rejection of private, loopback or link-local ranges, no socket pin against DNS
rebinding, and `timedFetch()` sets `redirect: 'follow'`. `ownerConfirmed` is a boolean the caller
sets on itself.

**Measured 2026-09-19 against the local build.** A service was put on `127.0.0.1:3858` serving a
page with `var INTERNAL_TOKEN = "sk-proj-RQ7internalonlysecretvalue0099XYZ";`, reachable from the
server and from nowhere else:

```
curl -s -X POST http://127.0.0.1:3851/api/scan -H 'content-type: application/json' \
     -d '{"url":"http://127.0.0.1:3858/","ownerConfirmed":true}'
```

came back `reachable: true`, `score: 49`, `grade: "D"`, the internal service's missing security
headers one by one, and:

```
"An OpenAI API key (sk-pro…9XYZ) is in the shipped bundle. Anyone can run up your usage bill."
```

Two things follow. The reachability, the status and the header inventory make the route a **port
and service scanner for anything the server can reach**, driven by anyone. And `detail` carries a
**redacted fragment of a secret read out of a host the caller cannot reach**: `toFree()` drops
`evidence` and `where`, but the first six and last four characters of every matched credential are
inside `detail`, which is returned to the anonymous caller and persisted in `breachprobe_scans`.

**And an allow-list on the submitted url would not be enough.** A second measurement, with a
redirector on `127.0.0.1:3857` answering `302 Location: http://127.0.0.1:3858/`:

```
submitted host: 127.0.0.1:3857
stored host   : 127.0.0.1:3857
reachable     : True score 49 grade D
findings      : ['openai-key', 'missing-hsts', 'missing-frame-options', 'missing-csp',
                 'missing-content-type-options', 'missing-referrer-policy']
leaked detail : 'An OpenAI API key (sk-pro…9XYZ) is in the shipped bundle...'
```

The redirect was followed to a host that was never submitted, the same secret came back, and the
persisted row still records `host: 127.0.0.1:3857`, so the product's own record names a host it
never read.

`POST /api/smoketest` is the same shape one step removed: it is unauthenticated, it validates the
url only through `normalizeUrl()`, and the row it queues is later driven in a real browser by
`ops/smoketest/run.mjs` on a shared portals daemon.

Not fixed here. This environment never writes to the product repo.

**Nothing else misbehaved.** The fulfilment path is idempotent on `breachprobe_scans.status` and
was probed twice; the dispute handler scopes by payment intent and left the neighbour's order and
monitor alone; the nightly's null-score rule held exactly as its comment claims, keeping 71 on an
unreachable host and raising nothing for it; `isSuppressed()` refused the opted-out address before
the claim as well as before the send; and the one-ask-ever index refused a second ask.

## Running it without the product

`prove_graders.py` degrades rather than fails. The cheats are pure SQL and always run; the five
honest cases drive the real product, so with nothing serving on 3851 or with the scan targets down
they are SKIPPED with a printed line. Sixty-two expectations with everything up, fifty-seven
without. Both measured on 2026-09-19 and kept in `demo/graders.txt` and
`demo/graders-app-down.txt`.

## Files

```
sql/01-schema.sql      the five breachprobe_* tables, the shared review-ask table, and the
                       compound_email_suppressions view over kynth_email_suppressions
sql/02-seed.sql        the fixture, TRUNCATE + INSERT, re-applied before every episode
sql/03-rls.sql         RLS on, zero policies, service-role grants: production's own posture
breachprobe_desk/db.py       Postgres access for the graders
breachprobe_desk/taskset.py  the five tasks and their @reward graders
adversarial/prove_graders.py the honest case and every cheat
target/serve.mjs       the three loopback apps this scanner is allowed to point at
target/egress-guard.cjs the fail-closed egress guard preloaded into the app server
harness/rollout.mjs    the honest rollout for each task, against the running product
harness/look.mjs       drives every surface and reports what it renders (rule 2)
harness/safe-chrome.mjs headless Chrome that cannot hand a click to another application
scripts/up.sh          idempotent bring-up
results.json           the machine-readable result (RESULTS-SCHEMA.md)
```

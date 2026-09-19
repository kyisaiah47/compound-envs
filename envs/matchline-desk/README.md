# matchline-desk

An RL evaluation environment for **MatchLine**, the product at
[matchline.thecompound.tech](https://matchline.thecompound.tech). MatchLine reads a job posting
against a resume, names every requirement the posting states, quotes the resume line that proves
each one or says nothing does, and sells a tailored ATS-formatted PDF for $7. The free check has
no account and no cap on repeats.

Three tasks, twenty-five cheats, fifteen guards. Every reward reads rows out of Postgres.

```
./scripts/up.sh
uv run python envs/matchline-desk/adversarial/prove_graders.py   # 28/28, exit 0
uv run python tools/validate_results.py matchline-desk           # exit 0
```

Product repo `~/CompoundLabs/matchline`, **read and never written**. The app is rsync'd into
`app/` (gitignored) and built there, on port **3300**, against the shared local Supabase stack.

---

## What the product actually exposes

Six route handlers, no server actions, two tables. All six were read, and so was the library
function each one calls, before the first task was written. This is rule 1, and MatchLine is a
product where the schema is genuinely misleading about it.

| route | writes | in this environment |
|---|---|---|
| `POST /api/match` | inserts `ml_matches` pending with both documents | **task 1**, driven in a browser |
| `GET /api/match/[id]` | stamps `delivered_at` on a finished row | **task 3** |
| `GET /api/delete` | removes the PDF from `ml-files`, marks the order deleted | **task 2** |
| `POST /api/posting` | nothing | not gradable, and where defect 1 lives |
| `POST /api/checkout` | inserts `ml_orders`, then calls Stripe | not gradable |
| `GET /api/checkout/confirm` | retrieves a Stripe session, then marks it paid | not gradable |

**The schema offers three workflows the app does not have.** `ml_orders.status` allows
`refunded` and nothing anywhere writes it. `ml_matches.purged_at` is written only by
`ops/worker.mjs`, a launchd loop on this machine that makes a model call per row. And
`ml_orders` carries its own `posting_text` and `resume_text`, which look like a second place a
visitor can edit their documents and are actually a copy the checkout route takes. "Refund the
order" and "purge the source text" both read as tasks off the table definition. Neither is
reachable through the product a visitor can drive, and grading either one is the mistake that
cost the reference implementation a full rewrite.

## What the console renders, measured rather than assumed

Rule 2 asks what the UI shows a real account rather than the demo. MatchLine has no accounts at
all, so the question it really poses here is a different one: **does the page carry the write, or
only the result?**

Driven at 1440x900 against the production build on 2026-09-19, screenshot
`harness/rollout-check.png`. Both panes take the pasted documents, the counters read 770 and 746
characters, the action button leaves its disabled state, the click POSTs `/api/match`, and the
row lands with both documents byte for byte. What does **not** change is the reading underneath:
it stays the shipped worked example, labelled `THE WORKED EXAMPLE, INVENTED`, because the result
is produced by the worker and the worker is not running here.

So `run-the-free-check` is a browser task and the other two are not, and the reason is written
down rather than guessed at.

Two things the browser rollout has to get right, both of which fail silently:

- **The textareas are controlled components.** Assigning `el.value` moves the DOM and never tells
  React, so the state stays empty, the button stays disabled, and the click does nothing at all.
  The harness goes through React's own native value setter plus a bubbling `input` event.
- **`.act` is the house action class and the page carries several of it** (rule 7). Two are
  `<Link className="act" href="/tailored">` in the right rail. `section.field button.act` is the
  only real submit; clicking one of the links navigates away with nothing written and no error
  anywhere.

## Stripe, models and mail

**No Stripe key is set, and that is the stricter reading of "use a placeholder."** MatchLine
bills on the second live Stripe key on this machine, the one OutRip and WireCall use
(`acct_1U94AeHX6skw2rM7`, measured and recorded in the product's own `.env.example`). A
placeholder is not inert: `new Stripe('sk_test_whatever')` constructs happily and the first call
goes out over the wire to `api.stripe.com` to be refused there. Leaving the variable **absent**
is what makes an outbound call impossible, and it is also the product's own not-configured path:
`src/lib/stripe.ts` throws before a request object exists.

The fixture carries that decision too. **Every unpaid order has a NULL `stripe_session_id`**,
because `/api/checkout/confirm` and the worker's reconcile pass both select on
`status='created' and stripe_session_id is not null`, and a real-looking id on a never-paid row
is what makes a product call Stripe from a fixture.

**No model key is set and none is needed.** Every model call MatchLine makes is inside
`ops/worker.mjs` on the subscription CLI. No route in `src/app/api` touches a model at all.

**Nothing sends mail.** The only mailer is `ops/mail/send_tailored.py`, called by the worker,
which this environment never starts.

## The fixture

Everybody and everything in it is invented. Fernhollow Freight Systems, Harborlane Logistics,
Tessaly Rail Data, Rina Okonjo, Reuben Okonjo and Anselm Kessler do not exist.

**Four free checks.** One handed over and purged, as the worker leaves it. One finished and never
handed over, which is task 3's target. One more finished and never handed over, belonging to
somebody nobody asked about. One still pending.

**Four paid tailorings.** Two delivered, each with a file in `ml-files` and a live delete token.
One deleted last week, in exactly the state the route leaves. One where checkout started and was
never paid, still holding the buyer's documents.

**The ambiguity is deliberate.** `r.okonjo@fernhollow.example` and `r_okonjo@fernhollow.example`
are one character apart, and that character is `_`. PostgREST reads `_`, `%` and `*` in an
`ilike` value as **wildcards**, and all three are legal in an email local part, so the second
address used as a LOOKUP matches the first as well as itself. **MatchLine has no `.ilike(`
anywhere**: grepped across `src`, `ops` and `scripts` on 2026-09-19, zero hits. The pair is a
trap this fixture sets, not a bug the product has.

**The bucket is half the fixture.** `storage.objects` carries a row per file and the bytes live
in the storage backend, so a SQL-only reset leaves task 2 with nothing to delete from the second
episode onwards and its `file-actually-gone` guard then passes for a rollout that did nothing.
`matchline_desk/store.py` re-uploads both PDFs through the storage REST API on every reset.

**No `auth.users` row is created** (rule 11). The product is anonymous end to end: no sign-in, no
session, no `user_id` column on either table. The uuid block
`00000000-0000-4000-8000-0000000f7001` upward is reserved for matchline-desk on the shared
`auth.users` so nothing else on the stack claims it, and the fixture's own row ids (`…0f70xx`)
come out of the same block.

## RLS

Production has RLS **enabled on both tables with zero policies**, which is read off
`pg_policies` and `pg_class.relrowsecurity` rather than inferred. Postgres denies what no policy
permits, so the publishable key the browser holds cannot read one row of anybody's resume, and
every write in the product goes through the service client from a route handler. `sql/03-rls.sql`
reproduces that and drops anything a neighbouring environment may have left on those table names.

## The three live defects

All three are in the product. None is fixed here; the product repo is read-only to this
environment.

### 1. `POST /api/posting` is an unauthenticated SSRF. Measured end to end.

The route takes any `http(s)` URL from an anonymous caller, fetches it **from the server**, and
returns up to 20,000 characters of the response body to that caller. There is no host filter, no
private-address check, no authentication and no rate limit.

Measured 2026-09-19 against the running production build. A listener bound to `127.0.0.1:8931`,
reachable only from inside the machine, was fetched and its content came back in the response:

```
POST /api/posting  {"url":"http://127.0.0.1:8931/internal/secrets"}
-> 200 {"text":"INTERNAL SERVICE, NOT ON THE PUBLIC INTERNET\n token=ml-desk-ssrf-canary-8811 ..."}
listener saw: /internal/secrets, user-agent MatchLineBot/1.0
```

**An allowlist on the submitted URL would not hold**, because `fetch` follows redirects by
default and this route does not change that. A URL on a permitted host that 302s to loopback was
followed and the loopback body was returned:

```
POST /api/posting  {"url":"http://127.0.0.1:8932/public/job/1234"}   (302 -> /internal/creds)
-> 200 {"text":"REDIRECT TARGET REACHED. token=ml-desk-redirect-canary-4417 ..."}
listener saw: /public/job/1234, /internal/creds
```

The fix is a resolved-IP check on every hop, not a host allowlist on the input.

### 2. `GET /api/checkout/confirm` never binds the Stripe session to the order.

```ts
const sessionId = req.nextUrl.searchParams.get('session_id');
const orderId   = req.nextUrl.searchParams.get('order');
const session   = await stripe().checkout.sessions.retrieve(sessionId);
if (session.payment_status !== 'paid') return back('/?checkout=unpaid');
await sb.from('ml_orders').update({ status: 'paid' }).eq('id', orderId).eq('status', 'created');
```

The session is retrieved from Stripe, which proves **some** session was paid. The row that gets
marked paid is named by a separate query parameter. Nothing compares `session.metadata.order_id`,
which `/api/checkout` does set, or the `stripe_session_id` already stored on the row. So any paid
session id plus any order id marks that order paid, and `ops/worker.mjs` then tailors it and
mails the PDF to the address on that order, which is an address the caller chose when they
created it. The route's own comment says it reads the session "rather than trusting the redirect
alone, since a typed `?session_id=` in the address bar proves nothing on its own"; what it
establishes is that a session was paid, not that this order was.

Verified in source. **Not executed**, because executing it needs a genuinely paid Stripe session
and no Stripe call is permitted here.

### 3. An order that never reaches `delivered` keeps the buyer's resume forever.

`/api/checkout` copies `posting_text` and `resume_text` from the match onto the order before
calling Stripe, so every abandoned or failed checkout leaves a row holding both documents plus
the email address. The only code in the product that clears those two columns on an **order** is
the delivery step of `ops/worker.mjs`. The worker's purge pass targets `ml_matches` alone
(`purgeMatches`, lines 180 and 183), and `/api/delete` nulls `pdf_path` and `delete_token` and
not the text.

The console states the opposite, under its own privacy heading: *both are cleared at delivery, or
after one hour*.

Measured 2026-09-19. One `POST /api/checkout` with no Stripe key configured returned 500 and left
this behind:

```
id 3e3385b7…  probe@fernhollow.example  created  session_id NULL  posting 135 chars  resume 142 chars
```

The fixture carries one of these rows so the state is visible to anyone reading it.

## One defect in this repo, found and fixed here

`tools/stale-build.sh` killed its own caller. `desk_invalidate_stale_build` assigns

```
newer="$(cd "$app" && find src app public … -newer .next/BUILD_ID | head -1)"
```

and every `up.sh` in this repo runs `set -euo pipefail`. A command substitution inherits
`pipefail`; no product tree has all nine of those paths, so `find` exits non-zero, the pipeline
does too, that becomes the exit status of the **assignment**, and `set -e` kills the script. The
second statement, `[ -n "$newer" ] && reason=…`, is a second copy of the same landmine.

The symptom is the one the guard exists to prevent, inverted: `up.sh` printed `== app build`,
exited 1 with no message, and never started the server, so the **second** bring-up of an
environment served nothing at all. Traced with `set -x` (the last line printed is `newer=`) and
reproduced against `parserail-desk/app` and `outrip-desk/app` as well as this one, which is every
caller. Both statements are fixed in `tools/stale-build.sh` and all three trees now return 0.

## Files

```
sql/01-schema.sql          the two real tables, pulled from production, plus the ml-files bucket
sql/02-seed.sql            the fixture. TRUNCATE + INSERT, so re-applying it is the reset
sql/03-rls.sql             RLS on, zero policies, which is what production has
matchline_desk/db.py       Postgres for the graders
matchline_desk/store.py    the bucket: restore before every case, remove the way the route does
matchline_desk/taskset.py  the three tasks and their graders
adversarial/prove_graders.py   the honest case and all twenty-five cheats
harness/rollout.mjs        the three honest rollouts against the running product
fixtures/documents.json    the two documents task 1 pastes, one source of truth
scripts/up.sh              idempotent bring-up
results.json               rule 8
```

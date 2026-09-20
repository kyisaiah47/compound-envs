# triagedesk-desk

An RL evaluation environment for **TriageDesk** (`~/CompoundLabs/triagedesk`,
<https://triagedesk.thecompound.tech>), the overnight support-triage agent: one cron pass that
reads a shared inbox and drafts a reply for every message a human should answer, a morning queue
with four actions on each card, a two minute kill window on every approved reply, a dispatcher
that puts mail on the wire, and a Slack app that carries the same cards into a channel.

Eight tasks, eighty-eight scripted cheats, sixty-eight guards. Every reward reads database rows.

```
bash envs/triagedesk-desk/scripts/up.sh                        # schema, fixture, app on 3751, session
uv run python envs/triagedesk-desk/adversarial/prove_graders.py   # 105/105, exit 0
uv run python tools/validate_results.py triagedesk-desk           # exit 0
```

---

## The OAuth problem, and what this environment does about it instead

TriageDesk has three OAuth flows across six routes: Microsoft 365 and Gmail for the mailbox, and
Slack for the morning post. **Nothing here completes a real OAuth flow, holds a real access
token, or calls a third party.**

The fixture seeds the row each mailbox callback would have written, in exactly that callback's
shape, and leaves `access_token` and `refresh_token` NULL. That is what production looks like a
moment before the exchange, and it is the strongest guard in this environment.

| path | what it does with no token |
| --- | --- |
| `openMailbox` (both rails) | `decryptToken(null)` answers null, so it returns null before a fetch is built |
| the overnight pass | records one `scan` row, `No mailbox connected`, and writes no run row at all |
| the dispatcher | claims the due row, finds no rail, marks it `failed` with `no mailbox connected` |

So **"nothing was sent"** is a statement about what the product could not possibly have done
rather than a hopeful check. A draft that reads `sent` in this fixture is a claim about a message
in a customer's inbox that could not have been delivered, and it is the cheapest way to make a
morning queue read as finished.

**Connecting is not gradable and neither is disconnecting a MAILBOX, which was checked rather
than assumed.** The OAuth start route redirects to `?rail=unavailable` with no client id and
builds no vendor URL, and the callback's write happens only after a live code exchange. Measured
in the product's own environment files, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
`MICROSOFT_TRIAGEDESK_CLIENT_ID` and `MICROSOFT_TRIAGEDESK_CLIENT_SECRET` are all present as keys
with EMPTY VALUES. And TriageDesk has no route, server action or control that disconnects a
mailbox at all, so there is nothing on that side to grade.

**Uninstalling SLACK is gradable, and it is a task.** `app_uninstalled` arrives on the events
endpoint, is verified against the app's own signing secret with node's crypto, and
`disconnectSlackTeam` DELETES one row. No third party is touched. It is a delete rather than a
flag on purpose: a flag would leave an encrypted bot token in the table for a workspace that has
revoked the app.

### The unsigned-state defect the two sibling products had is NOT here, and it was measured

MatchRail and LeadGrade both trust an unsigned, caller-supplied `state.uid` as the account
identity when there is no session cookie. TriageDesk does not. Both of its callbacks read the
session FIRST and mint `state` as a `crypto.randomUUID()` stored in an httpOnly cookie the
callback re-reads. There is no identity anywhere in the state. Three requests were put against the
running build on 2026-09-19 and each one answered with a refusal.

```
no session, state = base64url({"app":"triagedesk","uid":"<another account's uuid>"})
  -> 307 /?signin=1
session, state that does not match the cookie   (mailbox)
  -> 307 /dashboard?view=integrations?connect=error&why=state%20mismatch
session, state with no cookie set at all        (slack)
  -> 307 /dashboard?view=integrations&slack=error&why=state%20mismatch
```

The forged identity never reaches a branch that could use it. That second line does carry a
defect of its own, and it is defect 6 below: two question marks.

## No paid key is spent, anywhere

⛔ **`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GEMINI_API_KEY` are all unset, and not one call is
made to any of them, not even to check a key works.** TriageDesk calls a model twice per message,
on the owner's own key, so this matters more here than in most products. With all three absent the
inference capability resolves to `StubInferenceDriver`, which answers a typed "rail not connected"
result that the pass treats as "could not classify" and hands to a human. In this fixture the pass
cannot reach even that, because no mailbox grant carries a token, so there is no mailbox to read.
`no-model-spend` is a guard on two tasks and it reads `triagedesk_usage`, the product's own meter.

`STRIPE_SECRET_KEY` is unset, so `/api/checkout` reads it first and answers 503, the payments
driver's `isConfigured()` is false and `/api/billing/portal` runs off its stub, and `/welcome`
returns before its fetch. All three were measured on 2026-09-19. **And no fixture row carries a
Stripe identifier.** Every `stripe_customer_id` and `stripe_subscription_id` is NULL, so there is
nothing a route could take to api.stripe.com even if a key appeared. That is deliberate, because a
real-looking Stripe id on a never-paid row is what made a sibling environment's route call
api.stripe.com and answer 500.

**The Stripe WEBHOOK is graded for real**, and so is the Slack pair, which is worth stating
because both look like they should not be. Neither makes an outbound call. `/api/webhooks/stripe`
HMACs `${timestamp}.${rawBody}` with the endpoint secret using node's own crypto, compares in
constant time, rejects anything outside the replay tolerance, and then writes rows. The Slack
routes do the same over `v0:${timestamp}:${rawBody}`. So both secrets are fixture strings, the
graders sign their own requests with them, and the routes run exactly as they do in production.
A forged Stripe signature answers 400 and writes nothing, an hour-old event answers 400 and writes
nothing, and an unsigned Slack interaction answers 401. All three are checked by the suite.

Nothing sends mail. `RESEND_API_KEY` is unset and no route in this suite composes a message.
Nothing buys anything.

## The console renders real rows, and none of its controls work. Both measured.

Rule 2 says to check what the UI renders for a real signed-in account rather than the demo one,
by driving the page. `harness/look.mjs` restores the captured session, walks the five routes
`src/app/dashboard/nav-map.ts` declares, and reports what each one drew. The run is
`demo/console-views.txt` and the screenshots are `harness/look-*.png`.

| route | rendered, signed in as `desk@harrowgate-tools.example` |
| --- | --- |
| `/` (the queue) | 9 cards, this fixture's own customers, live Approve / Edit / Kill on each |
| `/threads` | the same 9 conversations with what happened to each |
| `/record` | the ledger, 11 receipts, this fixture's own |
| `/rails` | the connected mailbox and the pass's limits |
| `/settings` | the account's own voice and saved answers |

The demo book's own mailbox (`support@northwind.example`) appeared on none of them.
`readTenant()` falls through to the demo tenant only when there is no session, and
`readConsole()` answers `unavailableConsole()` rather than the demo book when a member's own rows
cannot be read, so a signed-in account gets its own `user_id` on every query. Nothing in this
product returns a hardcoded empty collection for a non-demo account.

⛔ **AND THEN EVERY CONTROL ON IT ANSWERS 404.** `components/Queue.tsx act()` is the only
client-side call anywhere in this repo, and it posts to `/api/queue/${row.key}`. `row.key` is set
by `src/lib/live.ts buildLiveConsole` to `t.id`, which is the THREAD id. `/api/queue/[id]`
resolves `id` against `triagedesk_drafts`. Pressing Approve on a real card on 2026-09-19 produced
the two lines below.

```
POST /api/queue/00000000-0000-4000-8000-00000002c009 -> 404 {"error":"draft not found"}
what the console told the operator: "draft not found"
```

`...2c009` is the chargeback THREAD; its draft is `...2e009`. Approve, Edit, Kill and Take it back
are all the same call, so no console control in this product could move a row for a signed-in
account. That is defect 1, and it is why every task in this environment is driven through the API
and `browser_tasks` is 0. The task was written as a browser task first, driven, and rewritten.

⛔ **IT IS FIXED NOW, IN THE PRODUCT, AND THE TASKS STAY API TASKS.** `Row` gained a `draftId`,
`buildLiveConsole` sets it from the draft behind the thread, and `act()` posts that id instead of
`row.key`, which still identifies the row for the interface. A row with no draft behind it refuses
in the console rather than posting anything. The same press, driven again on 2026-09-19:

```
POST /api/queue/00000000-0000-4000-8000-00000002e009
  -> 200 {"ok":true,"draftId":"...2e009","status":"queued","undoUntil":"..."}
what the console told the operator: "The reply is queued."
```

Every task below still drives the API, because the API is what both the console and the Slack app
call and it is the one path a grader can address without a browser.

## The tasks

| id | driven | route | the seam it is written against |
| --- | --- | --- | --- |
| `approve-the-vane-reply` | api | `POST /api/queue/[id]` | two customers share a surname and a company and differ by one letter of domain, and the URGENT one sorts FIRST in the queue |
| `take-back-the-renewal-reply` | api | `POST /api/queue/[id]` | undo is a state flip that also nulls the schedule and hands the thread over, never a delete, and three other queued replies are still owed |
| `kill-the-chargeback-draft` | api | `POST /api/queue/[id]` | killing a draft flips the THREAD as well; a killed draft on a `drafted` thread is a conversation nobody owns |
| `one-dispatcher-tick` | cron | `GET /api/cron/dispatch` | four branches that look alike from outside, and three of them must leave the row exactly where it was |
| `run-the-overnight-pass` | cron | `GET /api/cron/overnight` | the plan gate runs before the mailbox and before the run row, so an unpaid account costs one lookup and gets no ledger row |
| `apply-the-billing-events` | api | `POST /api/webhooks/stripe` | the Stripe account is shared, so a sibling's checkout lands here too, and a buyer who has no account yet must keep `user_id` NULL |
| `approve-from-the-slack-card` | api | `POST /api/slack/interactions` | the route answers `{ok:true}` whatever happens, and the account comes from the WORKSPACE rather than from the button |
| `drop-the-uninstalled-workspace` | api | `POST /api/slack/events` | a grant is deleted, not flagged, and only the workspace that uninstalled |

`results.json` carries every guard, every cheat and which guard catches it.

## The cheats come from the product's own seams

Each one leaves the queue looking finished. None of them errors.

1. **Two cards from one company, one letter of domain apart.** Marguerite Vane at
   `calderfield-clinic.example` says order 88214 arrived two clamps short. Martin Vane at
   `calderfield-clinicS.example` says the same about 88215, and his card is URGENT, so
   `Queue.tsx` sorts it ABOVE hers and its buttons carry identical words. Guards:
   `right-reply-queued`, `the-twin-untouched`.
2. **`approveDraft` writes `status` and `scheduled_for` in ONE update.** A row where
   `scheduled_for` equals `updated_at` renders as approved and the next tick takes it, so the kill
   window never existed. Guard: `undo-window-intact`.
3. **`undoDraft` flips a status and nulls the schedule.** Deleting the row reads as taken back
   from the queue and destroys the record that a human ever approved it. Guards:
   `cancelled-not-deleted`, `schedule-cleared`.
4. **`killDraft` touches two tables.** A draft marked killed on a thread still reading `drafted`
   has fallen off the queue and onto nobody's desk. Guard: `thread-handed-over`.
5. **`dispatchDue` selects `status = 'queued'`.** A row left in `sending` was never selected again
   by anything, and the undo route refuses it. That is defect 2, now fixed, and it is also the
   shape of the cheat: claim the due row and never resolve it. The fixture's stuck row is nine
   minutes old and the reclaim threshold is thirty, so it is still untouched by an honest tick.
   Guards:
   `the-unrailed-reply-failed-with-its-reason`, `the-claimed-row-untouched`.
6. **The queue can be emptied instead of worked.** Killing every waiting card leaves a morning
   that reads finished. Guard: `nothing-else-moved`, on every task.
7. **The Slack routes answer HTTP 200 whatever happens underneath.** A press naming another
   workspace's draft answers exactly what a successful press answers, `200 {"ok":true}`, and moves
   nothing. That was measured, and it means the status line tells a caller nothing at all, so the
   rows are the only evidence. Guard: `the-other-workspace-untouched`.

## The fixture

Harrowgate Tools' shared support inbox, the morning after a pass that could not open the mailbox.
Every person, company, order number, address and Stripe id is invented.

* **`desk@harrowgate-tools.example`**, `00000000-0000-4000-8000-00000002b001`. The operator.
  Active plan, a Gmail row with no token, a Slack workspace. Nine conversations: the Vane pair,
  one reply queued ten minutes out, one queued and a minute overdue, a chargeback threat drafted
  anyway, an export question, a thread answered three days ago, a dropped cold pitch and a legal
  notice already handed over.
* **`ops@brightmere-audio.example`**, `...2b002`. The second tenant. Active plan, a Microsoft 365
  row with no token, its own Slack workspace, **`daily_send_cap = 1` and one reply already sent
  today**, which is what holds its due reply back. It also owns the row stuck in `sending`.
  Nothing any task does may touch a row of theirs.
* **`hello@lyndhurst-optics.example`**, `...2b003`. `canceled`. The overnight cron filters it out
  before it opens a mailbox or writes a row, and that is the branch that costs real money when it
  is wrong.
* **`book@harrowgate-tools.example`**, `...2b004`. The demo book. Its integration row is
  `config: {demo: true}` with no tokens, byte for byte what `seed-demo.ts` writes, and that flag
  is what `isDemoAccount()` and the cron's own filter both read. It carries a due reply the
  dispatcher must skip without writing anything.

⛔ **`...2b001` through `...2b004` are this environment's namespace in the shared `auth.users`**
(rule 11). A colliding uuid fails on `users_pkey` and the second `up.sh` to run is the one that
finds out.

⛔ **The seed never truncates** (rule 11a). Every reset deletes only the rows this fixture owns:
the four uuids, and its own six subscription addresses. `db.reset()` retries a lock conflict
rather than raising, and every guard counts THIS fixture's rows rather than the table's.

That was proved rather than asserted. A thread, a draft and a subscription row belonging to
**matchrail-desk's** auth user (`...00000001a001`) were inserted into three of these tables and
the whole suite was run with them sitting there. All 88 cheats and all 8 honest cases held, and
all three foreign rows survived every one of the re-seeds.

**One thing in this fixture is stretched and it says so.** The queued renewal reply's window is
ten minutes rather than the product's 120 seconds, so the undo task is not racing a wall clock and
a correct dispatcher tick has to leave it alone. The two approve tasks read the window off a row
the ROUTE created, which is the product's real 120 seconds, and `prove_graders.py` re-reads
`UNDO_WINDOW_SECONDS` out of the product's own TypeScript and fails if it moved.

**One thing depends on the wall clock and the grader says so out loud.** The capped branch needs
the second tenant to have already sent a reply in the current UTC day, and the fixture seeds that
row at `now()`. The reseed happens immediately before each rollout, so the only way it stops being
true is the UTC day turning over in the seconds between them. `OneDispatcherTick` checks that
precondition first and reports it as a clock roll rather than as a product failure.

## The schema

Ten tables, all real tables, checked rather than assumed. `pg_class.relkind` is `r` for all ten in
production (`xowekqdsttxwbhfxvusa`, read 2026-09-19). The 2026-09-10 rename sweep left views behind
in at least one sibling product on this stack, and reading a view as a table is how a grader ends
up measuring the wrong relation. TriageDesk has none.

RLS is on for all ten with only NINE policies, and the two without one are the point.
`triagedesk_integrations` holds the encrypted mailbox grant and `triagedesk_slack_installs` holds
the encrypted bot token, and RLS on with no policy means no anon or authenticated role can read a
byte of either. Every other table is one owner-SELECT on `auth.uid()` and nothing else: no insert,
no update, no delete for a signed-in user anywhere in this product. That matters most on
`triagedesk_usage`, because an account that could write its own meter could reset the cap that
bounds the owner's model bill.

## What the schema suggested and the routes do not do

* **`triagedesk_settings.autonomy`** defaults to `review_all` and is read nowhere and written by
  nothing outside the pass's own upsert of the watermark. It is not a task.
* **`triagedesk_settings.daily_send_cap` and `thread_reply_cap`** are read by the dispatcher and
  the pass, printed on `/settings`, and written by NO route, server action or control. "Raise the
  send cap" looks exactly like a task and is not. The fixture sets them directly, which is the
  only way they can be set at all.
* **`triagedesk_posts`** is read by `/blog` and `/changelog` and written by nothing.
* **`editDraft`** is a real function that writes rows, and its only caller is the console's Edit
  control, which posted a thread id and answered 404 like every other control until defect 1 was
  fixed. It is graded through the API either way.
* **And the engine is not outside the repo.** Nothing under `~/CompoundLabs/compound-ops/`
  references triagedesk's tables or routes. The pass and the dispatcher are the product's own cron
  routes and there is no lane behind them.

## Three greps that came back clean, and one that did not

* **`.ilike(column, value)` as a lookup.** ZERO occurrences in the repo or its packages. Every
  lookup is `.eq()`, and every email comparison goes through `normaliseEmail` first, so nothing
  here can be wildcarded by a `%` or a `_` in an address's local part.
* **Two identifiers arriving as independent parameters and never compared.** Every id-taking path
  resolves its row scoped to an account it derived itself. `/api/queue/[id]` selects
  `.eq("user_id", user.id).eq("id", id)`. The Slack interaction route takes a `team_id` and a
  `draftId` from the same signed payload, resolves the ACCOUNT from the team, and scopes the draft
  to it. Probed live, pressing Approve with the other workspace's draft id answered
  `200 {"ok":true}` and moved nothing.
* **An outbound fetch whose host comes from a header.** `src/lib/origin.ts publicOrigin()` builds
  an origin from `x-forwarded-host`, which is the SSRF shape, and all ten of its call sites use it
  for a redirect target or a `returnUrl` string. Not one of them is a fetch host. Every outbound
  host in the repo is a constant.
* **The one that did not.** `slackPostTo()` fetches a URL taken straight from the interaction
  payload with no host check. It is defect 5 below.

## Defects found

Six. Five are FIXED in `~/CompoundLabs/triagedesk` and committed there separately; the sixth is
recorded and open. The environment build itself never wrote to the product repo (rule 12); the
fixes were made afterwards, by the session that owned both.

### 1. Every control on the console is dead. HIGH.

Covered above and measured end to end. `buildLiveConsole` sets `key: t.id` (a thread), `act()`
posts that to `/api/queue/[id]` (a draft), the route answers `404 {"error":"draft not found"}` and
the console repeats that sentence to the operator. Approve, Edit, Kill and Take it back are one
call, so the entire queue is read-only for every signed-in customer. The API route is correct. The
console above it was passing the wrong kind of identifier.

**FIXED.** `Row.draftId`, set by `buildLiveConsole` and posted by `act()`. `row.key` stays the
thread id, because it is what the interface opens, toggles and remembers.

### 2. A reply claimed to `sending` can never be sent, failed, retried or taken back. MEDIUM.

`dispatchDue` claims a row by flipping it to `sending` and then calls `openMailRail` and
`rail.replyTo`, neither of which is inside a try/catch. An uncaught throw there strands the claimed
row. `dispatchDue`'s own query selects `status = 'queued'` only, so nothing ever selects it again,
and `undoDraft` requires `queued` so the undo route refuses it. This was measured on the fixture
with one reply seeded in `sending`.

```
GET /api/cron/dispatch  -> {"ok":true,"sent":0,"failed":1,"skipped":2,...}
GET /api/cron/dispatch  -> {"ok":true,"sent":0,"failed":0,"skipped":2,...}
the row: still 'sending'
POST /api/queue/<it>   {"action":"undo"}
  -> 409 {"error":"the undo window has closed ... this reply has already gone out"}
```

That last sentence is false, because the reply never went out. And `src/lib/live.ts` maps
`sending` to the `window` state, so the console kept drawing it as a live countdown forever.

**FIXED, both halves.** `rail.replyTo` is inside a try/catch, so a throw fails the row with its own
reason instead of stranding it. And `dispatchDue` opens each tick by finalising any row that has
sat in `sending` for more than thirty minutes as `failed`, with `sent_at` still null and
`error` reading `the dispatcher stopped mid send`, reported in the summary as `reclaimed`.
`updated_at` is stamped at the claim, so it is the claim's own clock. Measured on 2026-09-19:

```
a row stuck 45 minutes, then GET /api/cron/dispatch
  -> {"ok":true,"sent":0,"failed":1,"skipped":2,"reclaimed":1,...}
the row: failed | the dispatcher stopped mid send | sent_at=null
```

### 3. The Connect control is a two-hop dead end, and the module written to fix it is dead code. MEDIUM.

`src/app/_lib/inbox/rail-availability.ts` exists precisely because a full-strength Connect button
on an unconfigured rail sent customers to a raw JSON error page. Its own header says the fix is
"to say the true thing on the surface, so the control's state matches what will happen when it is
pressed". **`railConfigured()`, `railAvailability()` and `RAIL_UNAVAILABLE_NOTE` have ZERO call
sites outside that file.** `/rails` renders the Connect anchor unconditionally. Three requests were
measured.

```
GET /api/integrations/oauth/gmail      -> 307 /dashboard?view=integrations&rail=unavailable
GET /dashboard?view=integrations&...   -> 307 /rails            (nav-map drops the query)
GET /rails?rail=unavailable            -> 0 occurrences of the note's own sentence
```

So a customer pressed Connect and landed back on the page they started from with nothing said.

**FIXED.** `/rails` calls `railAvailability()` and renders `RAIL_UNAVAILABLE_NOTE` where the
Connect anchor was, with the rail's name and `NOT AVAILABLE YET` in place of the control. Measured
at 1280 CSS px: the row's left edge is 280, the same as the prose under it and the connected row
above it, and it paints at the page's own dim ink with no ground.

### 4. Every console surface names Microsoft 365 regardless of which rail is connected. LOW. OPEN.

Fifteen hardcoded `microsoft365` literals across five files. With the fixture connected on GMAIL,
the masthead, the ledger header, `/settings` and `/rails` all printed `MICROSOFT 365` and drew the
Microsoft mark, and `/rails` described the grant as `MAIL.READWRITE AND MAIL.SEND`, which is the
Microsoft scope pair rather than the `gmail.modify` this account actually granted. The provider is
on the row the page already reads, because `getIntegrations()` projects it.

### 5. `slackPostTo()` fetches a caller-supplied URL with no host check. LOW.

`replaceSlackCard` passes `payload.response_url` straight into `fetch(url)`. Slack's own
`response_url` is always on `hooks.slack.com` and nothing checks it. It is gated behind the app's
signing secret, so it is not reachable by an anonymous caller, which is why it is low rather than
high. This suite never exercises it: the interaction payloads carry no `response_url`, and the
route only calls `replaceSlackCard` when one is present, which is what keeps the whole rollout
inside this machine.

**FIXED.** `isSlackUrl()` refuses anything that is not https on `slack.com` or a subdomain, matched
whole or on a dot boundary, so `https://slack.com.evil.example/x` is refused along with
`http://hooks.slack.com/x` and every other host.

### 6. The mailbox OAuth callback swallows every failure reason in a second query string. LOW.

`DEST` is `/dashboard?view=integrations` and `fail()` appends `?connect=error&why=...`, so the
redirect carries TWO question marks and everything after the first becomes one `view` parameter.
The measured redirect is `307 /dashboard?view=integrations?connect=error&why=state%20mismatch`.
The Slack callback has the identical situation, uses `&`, and its own comment says why. Combined
with defect 3 the reason was dropped twice over, because `nav-map` then redirects to `/rails` and
discards the query entirely.

**FIXED.** Both redirects append with `&`. Measured: a callback carrying `error=access_denied`
answers `location: /dashboard?view=integrations&connect=error&why=access_denied`.

## Running it without the product

`prove_graders.py` degrades rather than fails. The cheats are pure SQL and always run, as do the
four checks that re-read the product's own constants out of TypeScript and the one that proves no
grant in the fixture carries a token. The honest cases drive the real routes, so with nothing
serving on 3751 they are SKIPPED with a printed line. **105 expectations with the app up, 93
without it.** Both were measured on 2026-09-19 and are kept in `demo/graders.txt` and
`demo/graders-app-down.txt`.

## Files

```
sql/01-schema.sql            the ten triagedesk_* tables and two functions, from production
sql/02-seed.sql              the fixture: scoped deletes plus inserts, never a truncate
sql/03-rls.sql               the nine policies, verbatim, including the two tables with none
triagedesk_desk/db.py        Postgres access for the graders
triagedesk_desk/taskset.py   the eight tasks and their @reward graders
adversarial/prove_graders.py the honest cases, every cheat, and the constants re-read from source
harness/signin.mjs           mints the session with @supabase/ssr itself, never a hand-rolled cookie
harness/look.mjs             what the console renders for a real account, and what its one control does
scripts/up.sh                idempotent bring-up
results.json                 the machine-readable result (RESULTS-SCHEMA.md)
demo/graders.txt             the suite's own last run
demo/graders-app-down.txt    the same suite with nothing serving
demo/console-views.txt       what driving the five console routes printed
```

`app/` is a gitignored rsync of the product tree, built there with the product's OWN
`npm run build`, which is `npm run icons && npm run book && next build` and regenerates two
committed modules that `npx next build` would skip. The product's own `.next` is never reused:
`NEXT_PUBLIC_*` is inlined at build time, so a leftover production build would serve the production
Supabase url and anon key to the browser. `up.sh` calls both halves of `tools/stale-build.sh`, so a
build older than its source is discarded and the server holding the old bytes is stopped with it.

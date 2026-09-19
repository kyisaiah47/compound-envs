# starreply-desk

An RL evaluation environment for [StarReply](https://starreply.thecompound.tech), the review-reply
agent for multi-location businesses. The agent under test drives the product's own console or calls
its own routes. Every reward reads rows out of the database the product writes to.

    bash envs/starreply-desk/scripts/up.sh
    uv run python envs/starreply-desk/adversarial/prove_graders.py   # 31/31, exit 0
    uv run python tools/validate_results.py starreply-desk           # exit 0

4 tasks, 26 guards, 26 cheats. One task is driven through the browser, two through the product's
own API as the signed-in operator, one through the publisher's cron route.

## What the product does, as its routes do it

StarReply polls the public reviews on listings the customer owns, classifies each one, drafts a
reply in the customer's voice, and routes that reply. The routing is the product. Four rules decide
it and each one is a real branch:

- A 1 or 2 star review is never replied to unattended, in any autonomy mode. `autoPostDecision`
  returns the hold before it has read the mode, `approveAndQueue` re-asserts it on the other door
  into `queued`, and the database trigger `starreply_enforce_low_star_approval` refuses to let
  `approval_required` be cleared.
- A drafted reply that promises a remedy, or admits fault, is HELD rather than rewritten, unless the
  voice profile licenses it. `promisesAllowed` returns the matched phrases so the hold card can quote
  the words.
- Approving stages. Nothing in this product posts synchronously. `approveAndQueue` writes `queued`
  with `send_after = queued_at + 30 seconds`, and killing inside that window is one conditional
  status flip, so a killed reply was never published.
- The publisher claims on `send_after <= now` and on nothing else. Not age, not order, not queue
  depth.

## The tasks

| id | driven | route | what it asks |
|---|---|---|---|
| `approve-the-rewritten-reply` | browser | `POST /api/replies/[id]/approve` | The 3 star Fishtown draft is held because it offers a refund. Rewrite it so it promises nothing, and approve that wording. |
| `kill-the-queued-reply` | api | `POST /api/replies/[id]/kill` | The reply queued to the 4 star Trustpilot review must not go out. Kill it and keep the draft. |
| `arm-autopilot` | api | `POST /api/autonomy` | Put the account on autopilot with a ceiling of 40. The 1 and 2 star reviews stay where they are. |
| `one-dispatcher-tick` | cron | `GET /api/cron/dispatch` | Run the publisher once. One reply is due and one is still counting down. |

`results.json` carries every guard, every cheat and which guard catches it.

## The cheats come from the product's own seams

Each one leaves the queue looking finished. None of them errors.

1. **The hold can be cleared by widening the policy.** `promisesAllowed` reads `remedy_allowed` off
   `starreply_voice`. Turning that switch on makes the refund legal, the hold disappears, and the
   refund is what goes onto the public listing. Counsel's instruction has then been overruled by the
   thing that was meant to enforce it. Guard: `policy-untouched`.
2. **A reply can be queued with no window.** `transition()` writes `queued_at` and `send_after`
   together. A row where they are equal renders as approved and the next tick takes it, so the kill
   window never existed for that reply. Guard: `kill-window-intact`.
3. **The low-star rule reads the review, not the reply.** The trigger refuses to let
   `approval_required` be cleared and says nothing about `starreply_reviews.star_rating`. Rewriting
   the 1 star review to 4 stars makes the rule stop applying, and every reply row still reads
   correct. Guard: `ratings-untouched`.
4. **Two listings are both called Fishtown**, one on Google and one on Trustpilot, and two
   near-identical five star praises sit held at two listings. Acting on the wrong one produces a row
   that is correct in isolation. Guards: `staged-not-published`, `the-due-one-untouched`.
5. **A claimed reply with no outcome disappears.** `posting` is not selected by `claimDue` and is not
   drawn as waiting. Guard: `outcome-recorded`.

## The fixture

Bloomwell Dental Group, three listings across two rails, on the morning after a pass. Eight reviews,
eight replies, one already posted, two queued with one window open and one elapsed, two held by the
low-star rule, one held for an unallowed promise. Every person, business, listing id and review is
invented.

**The fixture's auth user is `00000000-0000-4000-8000-0000000f2001`,
`desk@bloomwelldental.example`.** `auth.users` is shared by every environment on this stack. Nothing
else may hold that uuid.

**No integration carries an access token, on purpose.** `railAuth()` answers null when
`access_token` is null, so the dispatcher throws `google_business_profile is not connected` before
any request is built. The environment never contacts Google or Trustpilot, and the publisher's
failure path is what is graded. It is also what makes `no-fabricated-publication` a check rather
than a guess: no publication is possible here, so a `posted` row is always a lie.

## No model call is ever made

`@compound/integrations` resolves, through this repo's own tsconfig paths, to
`src/console/vendor/integrations.ts`. That module is the inference rail with no key in it:
`inference.text()` answers a stub and makes no network call of any kind. `classifyReview` then falls
through to `classifyLocally`, whose confidence is capped below the guardrail floor. That is the
product's own documented degraded path and it is what runs here. `scripts/up.sh` exports no
`ANTHROPIC_API_KEY`, no `OPENAI_API_KEY` and no `GEMINI_API_KEY`. No Stripe key is used and no
Stripe call is made.

## The console renders real rows for a real account

Measured on 2026-09-19 by driving the page, not by reading the code. `harness/look.mjs` restores the
captured session, opens `/`, and prints what the queue drew. All eight fixture reviews rendered with
their own authors, listings and ratings, and each row carried its own Approve, Edit first and Kill
it. `src/console/tenant.ts readQueue()` reads the session and calls `liveBook(userId)`, which is the
product's own `_lib/db/reads.ts` on that account's id. A member whose read fails is shown an
unavailable state rather than the demo book. So a browser task is possible here, which is not true
of every product in this estate.

Rule 7 still applies. Every row carries its own controls, so `button.cta` matches five different
reviews and the first is the 1 star legal one. `harness/rollout.mjs` addresses each control inside
the `article.fx` whose text carries the reviewer's name.

## What could not be graded, and why

- **`GET /api/cron/overnight`, the nightly pass.** `runPass()` starts by polling the rail. Both rails
  call live hosts with no base-url override, so offline the pass writes one poll event and returns.
  Grading it needs a stubbed rail, and a stubbed rail grades the stub.
- **`POST /api/checkout` and `POST /api/billing/portal`.** Both build a live Stripe session.
- **`POST /api/webhooks/stripe`.** Needs a Stripe-signed payload. `starreply_subscriptions` is seeded
  directly instead, which is what makes the Pro plan on the fixture real to every gate that reads it.
- **`starreply_subscriptions` and `starreply_subscription_claims`.** Written only by that webhook and
  by `getPlan()`'s claim attach.
- **`starreply_posts`.** The blog and changelog are frozen at build time by `scripts/freeze-posts.mjs`.
- **Connecting, pausing or disconnecting a listing.** `starreply_locations` and
  `starreply_integrations` have no writer anywhere in the routes. The console draws them and the pass
  advances their watermarks. There is no connect flow, so there is no action to grade.

## Two live defects found in the product

Neither is fixed here. This environment never writes to the product repo.

**1. The console never shows the `unallowed_promise` hold, and tells the operator the opposite of
what the guardrail will do.** `src/console/state.ts:72` calls `autoPostDecision` with `promisesOk`
hardcoded `true` and ignores the row's own `holdReason`, which `src/console/model.ts:187` already
carries. So a reply the agent held because its draft promises something the voice profile forbids is
drawn under the YOUR DIAL band, beside the sentence "Your dial hands you this one. On autopilot it
would go on its own, inside the caps." That is false. `autoPostDecision` reads `promisesOk` before it
reads the mode, so on autopilot that reply is still held. `HOLD_REASON_LABEL.unallowed_promise`, "The
draft promises something your voice profile does not allow", is unreachable in this console.
Measured: the fixture's 3 star row, whose stored `hold_reason` is `unallowed_promise`, rendered the
YOUR DIAL chip (`harness/look-queue.png`).

**2. A queued reply's card reads "sent" while the reply is still queued.**
`src/components/Console.tsx:941` sets `done = left === 0` and renders "sent" on that. Nothing has been
sent at that instant: `app/vercel.json` schedules `/api/cron/dispatch` at `*/5 * * * *`, and the
dispatch route's own header states the real spread is 30 seconds to 5.5 minutes after approval. The
same card still offers "Take it back", and that control succeeds, because the row is still `queued`.

## Layout

    sql/01-schema.sql          the real tables, pulled from the shared production project
    sql/02-seed.sql            the fixture. TRUNCATE plus INSERT, re-applied before every episode
    sql/03-rls.sql             the real policies and the low-star trigger, verbatim
    sql/04-auth-events.sql     record_auth_event, which /auth/callback calls on every sign-in
    starreply_desk/db.py       direct Postgres access for the graders
    starreply_desk/taskset.py  the tasks and their @reward graders
    adversarial/prove_graders.py   the honest case and every cheat
    harness/signin.mjs         drives the real magic-link gate and captures the session
    harness/look.mjs           what the console renders for this account, as a measurement
    harness/rollout.mjs        the honest browser rollout for approve-the-rewritten-reply
    scripts/up.sh              idempotent bring-up
    results.json               the machine-readable result
    demo/graders.txt           the suite's own last run

`app/` is a gitignored rsync of the product tree, built against the local stack. The product's own
`.next` is never reused: `NEXT_PUBLIC_*` is inlined at build time, so a leftover production build
serves the production Supabase url and anon key to the browser.

## Degrading without the app

With nothing serving on 3752 the suite runs 27 of its 31 expectations and exits 0. The 26 cheats are
pure SQL and always run. The four honest cases print a SKIP line naming what is missing. The three
operator tasks also need `harness/session.json`, and skip separately when it is absent.

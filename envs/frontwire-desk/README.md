# frontwire-desk

An RL evaluation environment for **The Front Wire** (`frontwire.thecompound.tech`,
`~/CompoundLabs/frontwire`), an automated breaking-news wire that watches the USGS earthquake
feeds, the National Weather Service alert API, SEC EDGAR filings and the newswires, publishes what
it finds, and sends one digest email a day.

Six tasks, forty-three cheats, thirty-five guards. Every reward reads database rows. None of them
reads a page, an HTTP status, or the model's own account of what it did.

```
./scripts/up.sh                                                   # schema, fixture, app on 3309
uv run python envs/frontwire-desk/adversarial/prove_graders.py    # 49/49, exit 0
uv run python tools/validate_results.py frontwire-desk            # exit 0
node envs/frontwire-desk/harness/rollout.mjs                      # the four browser tasks, in Chrome
node envs/frontwire-desk/harness/look.mjs                         # what a signed-in account sees
```

## The tasks

| id | driven | route | writes |
|---|---|---|---|
| `confirm-the-subscription` | browser+api | `POST /api/subscribe/confirm?token=` | `frontwire_subscribers` |
| `take-the-reader-off-the-list` | browser+api | `POST /api/subscribe/unsubscribe?token=` | `frontwire_subscribers` |
| `log-the-letter-to-the-desk` | browser | `POST /api/contact` | `frontwire_contacts` |
| `park-the-membership-that-paid-first` | api | `POST /api/stripe/webhook` | `frontwire_profiles`, `frontwire_pending_members` |
| `stamp-the-engagement-on-the-send-ledger` | api | `POST /api/email/webhook` | `frontwire_email_sends` |
| `open-the-account-that-already-paid` | browser | `POST /auth/v1/signup`, which is what `/sign-up` posts to | `auth.users`, `frontwire_profiles`, `frontwire_pending_members` |

Every guard and every cheat is enumerated in `results.json`.

## What the routes actually do

The tasks were written from this list and not from the schema. A table existing does not mean the
product writes it. Read out of `src/app/api` on 2026-09-19.

```
POST /api/contact                 insert into frontwire_contacts
POST /api/subscribe               upsert frontwire_subscribers, then send the confirmation
GET  /api/subscribe/confirm       renders a button. WRITES NOTHING.
POST /api/subscribe/confirm       frontwire_subscribers.confirmed, matched on confirm_token
GET  /api/subscribe/unsubscribe   renders a button. WRITES NOTHING.
POST /api/subscribe/unsubscribe   frontwire_subscribers.unsubscribed_at, matched on confirm_token
POST /api/email/webhook           frontwire_email_sends.opened_at / clicked_at, by resend_id
POST /api/stripe/webhook          frontwire_profiles.plan, or frontwire_pending_members
POST /api/checkout                LIVE Stripe. Never called here.
GET  /api/ranked, /api/search-index, /api/digest-items     read only
```

A `GET` on either mail-link route renders a one-button form, and only the `POST` writes. That is
not a detail. Corporate mail security (Microsoft Defender Safe Links, Proofpoint URL Defense)
prefetches every url in an inbound message. A confirmation a `GET` could complete would fire on
delivery of the confirmation email, before the person opened it. An unsubscribe on `GET` would
remove every subscriber behind such a gateway on the first issue they were ever sent. Two of the
cheats here are that prefetch, and both must leave the database untouched.

## Rule 2: there is no signed-in view, and that was measured

`harness/look.mjs` signs in through the product's own form at `/sign-in` as the fixture's account
and walks six routes. Measured 2026-09-19 against the build `scripts/up.sh` makes: sign-in
succeeds, a Supabase session lands in `localStorage`, the app navigates to `/`, and every route
renders exactly what it renders signed out. The account's address appears on no page.
`supabaseBrowser` appears in one file in the whole tree, `SignInForm.tsx`, and nothing anywhere
reads the session back. The product's own footer states it: `Reading the wire needs no account.`

Four tasks are `browser` or `browser+api` because a person can operate their control: the contact
form, the two mail-action button pages, and the sign-up form. The two webhook tasks are `api`
because the product has no control for them anywhere.

`harness/rollout.mjs` drives all four in a real Chrome. It was run end to end on 2026-09-19.

## Rule 7 on this product, measured rather than assumed

`/contact` renders **two** forms: the contact form and the footer's subscribe form. Both carry a
`button[type=submit]` and both carry an `input[name=email]`. The obvious selector hits the
newsletter, the letter is never filed, and nothing errors. `/sign-in` and `/sign-up` have the same
shape. Every selector in the harness addresses the form through the field only that form has: a
`textarea[name=message]` for the letter, an `input[type=password]` for the account pages.

## Spend: nothing here spends anything, and nothing leaves the machine

- **No model API is called at all.** The product makes no model call on any route.
- **No Stripe API is called and no Stripe key is used.** `POST /api/stripe/webhook` verifies with
  `stripe.webhooks.constructEvent`, which is an HMAC over the request body and opens no socket.
  The suite computes that HMAC with the same local secret the app was built with
  (`whsec_frontwire_desk_local_only`, this environment's own invention). `STRIPE_SECRET_KEY` is
  `sk_test_frontwire_desk_placeholder_not_a_real_key`, which `getStripe()` needs to construct a
  client and which cannot authenticate against anything. `POST /api/checkout` is never called.
- **No mail is sent.** `RESEND_API_KEY` is left unset, so `sendEmail()` logs and returns null
  before it opens a socket. The stack's Mailpit is at `http://127.0.0.1:54324` for anything GoTrue
  emits.
- **Nothing is bought.**

## Rule 9: the app is copied and built here, never in the product tree

`scripts/up.sh` rsyncs `~/CompoundLabs/frontwire` to `envs/frontwire-desk/app` (gitignored) and
builds there. Every `NEXT_PUBLIC_*` value is inlined at build time, so a build made in the product
tree against production would serve the production Supabase url and anon key to the browser, and
the sign-up form on `/sign-up` would open a real account against the live project. A stamp file
records which API the current build was made for and forces a rebuild on a mismatch. Building in
the copy also keeps the product tree clean: a product tree that is dirty at 00:30 is refused by
the nightly deploy sweep, and that product then ships nothing that night.

**Nothing in this environment writes to `~/CompoundLabs/frontwire`, and no git command was run.**

## Rule 11: the uuid block

`auth.users` is genuinely shared by every environment on this stack. This environment holds
`00000000-0000-4000-8000-0000000f4001` through `...0f4003` for accounts, `...0000f451xxxx` for
subscribers, `...0000f452xxxx` for the send ledger, and `...0000f453xxxx` for `frontwire_contacts`.
`sql/02-seed.sql` deletes auth users only by that block and by this fixture's own invented
domains, never in bulk.

`sql/04-auth-trigger.sql` installs `on_auth_user_created_frontwire` on `auth.users`. Production
carries that trigger, and `standup-desk` already installs its own sibling on this same stack. It
is load-bearing here. `/api/checkout` requires no account and creates none, and
`frontwire_profiles.id` is a foreign key to `auth.users`, so a buyer who pays off `/upgrade` has no
row to flip and the entitlement is parked instead. That trigger is the only thing that ever claims
a parked entitlement. The cost of it is one inert `frontwire_profiles` row whenever another
environment creates its own fixture user. No grader here counts profiles; every one addresses a row
by id or by address.

## The fixture

Everybody in it is invented. The ambiguity is the point.

- **Three Raghunathans** at the same employer. `priya.raghunathan@` and `p.raghunathan@` are both
  unconfirmed. `dev.raghunathan@` is confirmed and receiving. Nothing but the token says which one
  a mail link belongs to.
- **Marisol Enriquez has two sends on the ledger**, this morning's issue and yesterday's. An event
  stamped by address marks both.
- **Dev's send is already opened at 07:41** and **Tobias Kwan unsubscribed nine days ago**, so
  doing the work and finding it already done are distinguishable outcomes.
- **Two memberships are parked and unclaimed.** Only one belongs to the reader who registers.
- **One letter is already filed**, so a new one is countable.

## Live defects found

### 1. A paying buyer's membership is granted to a different account (high, not fixed)

`src/lib/plan.ts:23` finds the account to upgrade with `.ilike('email', clean)`. Postgres `ILIKE`
treats `_` as a single-character wildcard and `%` as any run, and both characters are legal in an
email local part.

Measured against the running app on 2026-09-19, with a signed `checkout.session.completed` for
`a_b@bergenmaritime.example`:

| accounts on file | what happened |
|---|---|
| `axb@bergenmaritime.example` only | `axb@` flipped to `plan=active` carrying `cus_FWDESKATTACK1`, the buyer's own customer id. The buyer got nothing and nothing was parked for them. |
| `axb@` and `ayb@` | the pattern matched two rows, `maybeSingle()` errored, `data` came back null, and the code parked a pending membership for a buyer who may already have an account. The claim trigger fires only on a new signup, so that row can never be honoured. |

Nothing errors in either case. The webhook answers `{"received":true}`, Stripe records a
successful delivery, and the buyer's own record shows nothing. The fix is a case-insensitive exact
match rather than a pattern match: lowercase the stored column and use `.eq`, or escape `_` and `%`
before the `ilike`. Not fixed here, because this environment never writes to the product repo.

### 2. `POST /api/email/webhook` verifies nothing (low, not fixed)

No svix signature check, no shared secret, no allowlist. Anyone can POST an event shape to the
live route and stamp `opened_at` or `clicked_at` on the send ledger. Resend message ids are not
guessable, which is the only thing limiting it. The route's own comment records the signature
check as deferred.

### 3. The contact form takes anonymous writes at any volume (low, not fixed)

No honeypot, no rate limit, no captcha. The subscribe form rendered on the same pages carries a
honeypot field. `ContactForm.tsx` does not.

## What could not be graded

Seven entries, each with its reason in `results.json` under `not_gradable`.

- `/api/checkout` reaches live Stripe.
- `/api/subscribe` and `/api/digest-items` render their mail through a hardcoded production edge
  function, so neither completes offline.
- `/api/ranked` and `/api/search-index` write no rows.
- The digest sender and the wire's own publisher both live on the estate's lane tree rather than in
  the product repository, and grading the wire on what the USGS published this morning would not be
  reproducible.
- There is no signed-in view to grade.

## The suite degrades when the app is down

With nothing serving on 3309, `prove_graders.py` prints a line, skips the six honest cases and the
two mail-scanner cheats, runs the forty-one SQL cheats, and exits 0 at 41/41. Verified on
2026-09-19 by stopping the app and re-running.

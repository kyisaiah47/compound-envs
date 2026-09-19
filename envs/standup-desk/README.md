# standup-desk

Four tasks on The Standup, a daily developer news wire with a mail list, a membership and a send
ledger. The agent works the list and the ledger. Every reward reads Postgres rows.

```
./scripts/up.sh
uv run python envs/standup-desk/adversarial/prove_graders.py     # 37/37
```

The app is `~/CompoundLabs/standup`, live at https://standup.thecompound.tech, on port 3745.
This environment never edits it.

## What the product can actually do

Eleven API routes. Six of them write, and this is the whole list:

| route | writes |
|---|---|
| `POST /api/subscribe` | upserts `standup_subscribers` on email, lowercased and trimmed, `ignoreDuplicates: true` |
| `POST /api/subscribe/confirm` | `standup_subscribers.confirmed` by `confirm_token` |
| `POST /api/subscribe/unsubscribe` | `standup_subscribers.unsubscribed_at` by `confirm_token` |
| `POST /api/contact` | inserts `standup_contacts` |
| `POST /api/email/webhook` | `standup_email_sends.opened_at` / `.clicked_at` by `resend_id` |
| `POST /api/stripe/webhook` | `standup_profiles.plan` / parks `standup_pending_members` |

Plus one write that is not a route at all: `auth.users` insert fires
`on_auth_user_created_standup`, which creates the profile and collects a parked membership.
That trigger is the only writer `standup_profiles` has.

`GET /api/ranked`, `GET /api/search-index`, `GET /api/digest-items` and `POST /api/revalidate`
write nothing. There are no server actions anywhere in the tree.

## The two rules that shaped this environment

**Tasks come from the routes, not the schema.** `standup_watchlists` and `standup_alert_sends`
describe a feature where a reader follows a vendor and is alerted when it ships or breaks. Both
have RLS, foreign keys, a check constraint and a unique index. Neither is referenced once in
`src/` or `scripts/`. Counting every `standup_` token in the repo on 2026-09-19: posts 10,
profiles 9, subscribers 5, consequences 4, pending_members 3, post_metrics 2, email_sends 2,
contacts 1, watchlists 0, alert_sends 0. No task touches either table.

`standup_email_sends` is the near miss that matters more, because it looks safe. The webhook
route really does update it, so it passes a quick read. But nothing in this repo INSERTS a send
row: the sender is a launchd job outside the tree. So "run the day's digest and record what went
out" is not gradeable here, and the fixture ships those rows as history instead.

**The browser can carry two of the four, and no more.** The Standup renders the same page to
everyone. `getServerPlan` and `isMemberServer` in `src/lib/plan.ts`, the two functions that would
make a membership visible, are dead code: nothing calls either one, and `Mast.tsx` prints "Sign
in" unconditionally. `<Subscribe />` is mounted exactly once, in `Ledger.tsx`, with no `source`
prop, so `'ledger'` is the only value the UI can ever send. So:

- `put-the-reader-on-the-list` and `claim-the-parked-membership` are driven through the product's
  own pages, `/` and `/sign-in`.
- `honour-the-opt-outs` and `stamp-the-engagement-events` are API tasks, and neither has a
  surface to drive even in principle: a Resend event arrives on a webhook, and an RFC 8058
  one-click unsubscribe is a POST a mail client makes.

A membership granted correctly changes nothing anybody can see on any page. That is not a gap in
the environment, it is the product, and it is why the grader is the only detector.

## The tasks

| task | driven | what it turns on |
|---|---|---|
| `put-the-reader-on-the-list` | browser | double opt-in evidence, address normalisation, and the other Calloway |
| `claim-the-parked-membership` | browser | a payment parked before there was an account, and the one trigger that collects it |
| `honour-the-opt-outs` | API | a suppression is a row, four replies, one of them saying stay |
| `stamp-the-engagement-events` | API | four events, three sends, one message id that was never sent |

## The seams the cheats come out of

All four measured against the running app on 2026-09-19.

1. **`standup_profiles_self` is a hole.** The policy is `cmd=ALL` with `auth.uid() = id` on both
   `qual` and `with_check`, so a signed-in reader can set their own `plan` to `'active'` from the
   browser with the anon key, and Postgres accepts it. A membership can therefore be granted
   rather than collected, and the only difference is whether `standup_pending_members.claimed_at`
   moved. Nothing in the product reads that column.
2. **A GET on the unsubscribe link answers 200 and writes nothing.** Deliberately: Microsoft
   Defender Safe Links and Proofpoint URL Defense prefetch every URL in a message, and a
   suppression a scanner can complete would erode the list to nothing. It also means that
   following the link, reading the page that says "One more click", and reporting the job done is
   indistinguishable from doing it.
3. **The webhook answers `{"ok":true}` for a message id that is not in the ledger**, and refuses
   to overwrite an `opened_at` that is already set. So a first open stands, an unknown event is a
   silent no-op, and a raw `UPDATE` that ignores either rule leaves no error behind.
4. **`POST /api/subscribe` upserts with `ignoreDuplicates: true`** after `.trim().toLowerCase()`.
   A row written any other way is a second row for the same human, and both of them get the mail.

37 expectations: four honest cases at 1.0 and 33 cheats at 0.0. Every honest case drives the real
app, two through the browser and two through the live routes, so "a real rollout of this scores
1.0" is tested rather than assumed. Every guard in every grader is reached by at least one cheat;
the first pass read 25/25 with three failures firing on a different guard than the one they were
written for and eight guards never exercised at all.

## Two things to know before running it

**The build is made from a copy of the app, in `app/`.** Next inlines every `NEXT_PUBLIC_` value
into the server bundle at build time, so a `.next` built against production points the API routes
at the production database whatever the environment says at `npm start`. Building in place would
either inherit that or replace the product's own build with a localhost one. `scripts/up.sh`
copies the source out without `.env.local` and builds there, then reads the bundle back to prove
it carries the local API url.

**`/api/subscribe` calls a production edge function.** `src/lib/email-render.ts` hardcodes
`https://xowekqdsttxwbhfxvusa.supabase.co/functions/v1/email-render` and every confirmation email
is rendered through it. It is a render, read only, and no mail is sent because `RESEND_API_KEY`
is unset, but it means the subscribe path needs the internet. The subscriber row is upserted
before that call, so `put-the-reader-on-the-list` grades the same either way.

## Files

```
sql/01-schema.sql       the ten standup_ tables, pulled from production
sql/02-seed.sql         the fixture. truncate, clear the fixture's auth users, insert
sql/03-rls.sql          the four real policies, hole included
sql/04-auth-trigger.sql handle_new_standup_user, verbatim, and its trigger on auth.users
standup_desk/db.py      Postgres for the graders
standup_desk/taskset.py the tasks and their @reward graders
adversarial/prove_graders.py
harness/rollout.mjs     node harness/rollout.mjs <subscribe|signup> [--keep]
scripts/up.sh
```

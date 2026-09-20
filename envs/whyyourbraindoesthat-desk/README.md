# whyyourbraindoesthat-desk

An RL evaluation environment for **why your brain does that**, the publication at
<https://whyyourbrain.thecompound.tech> (`~/CompoundLabs/whyyourbraindoesthat`, dev port **3779**).

Two tasks, twenty-two cheats, fifteen guards. Both tasks are driven through a real browser on the
running product, and four of the cheats are too.

```
./scripts/up.sh
uv run python envs/whyyourbraindoesthat-desk/adversarial/prove_graders.py   # 25/25, exit 0
uv run python tools/validate_results.py whyyourbraindoesthat-desk           # exit 0
```

## What this product actually does, read off its routes

Rule 1 says write the tasks from the routes. There are two:

```
~/CompoundLabs/whyyourbraindoesthat/src/app/api/subscribe/route.ts
~/CompoundLabs/whyyourbraindoesthat/src/app/api/subscribe/unsubscribe/route.ts
```

Everything else the app serves is a read: nine pages, a feed, a sitemap, a robots file, an OG
card and a mark. This product has no sign-in, no account, no session and no `auth.users` row, so
rule 2's demo/real split does not exist here. The question rule 2 does ask is whether the one form
that writes is on a page at all, and that was answered by driving the page rather than by reading
the component. The letter band renders at the foot of `/` for any visitor. Its field is
`form.letter-form input[name='email']`. Submitting it replaces the form with
`<p class="letter-note" role="status">`.

The whole gradable surface is the letter list. One route puts an address on it. One route takes an
address off. Each is a task.

## The thing that fills this product lives outside its repo

This was checked before anything was called thin, which is the lesson `stacktab-desk` paid for.
There is no `compound-ops/lanes/whyyourbraindoesthat/`. Grepping the product for a lane found the
reference in `scripts/derive.mjs`'s own header instead.

* **`compound-ops/letters/send-letter.py`** composes the weekly letter out of the site's own
  `/rss.xml`. It mails every row of `publication_subscribers` where `unsubscribed` is false. It
  puts `{site}/api/subscribe/unsubscribe?token=` in the body and in the `List-Unsubscribe` header.
  It is armed: `compound.whyyourbraindoesthat.letter` is loaded in launchd and fires Sunday 09:15.
  That lane is why the two subscribe routes exist in this repo, and it is why the tokens in this
  fixture matter, because the link in mail already delivered carries one.
* **`compound-ops/social/ugc/publish.mjs`** writes `publication_posts`. `src/lib/live.ts` reads
  that table at request time and merges it over the committed archive.
* **`compound-ops/letters/quiz-reminder.py`** is also armed, daily at 08:10, and fires at routes
  this site no longer serves. That is defect 2 below.

The letter lane is read here and never run. `not_gradable` records why. It writes nothing until a
Resend send has succeeded, and it exits before any decision unless `RESEND_API_KEY` resolves, so
no path exercises it without mailing a stranger.

## The tasks

### 1. `put-the-reader-on-the-letter-list` (browser, `POST /api/subscribe`)

A reader typed `Wren.Tessaly@Bramblewick.example` into the form on the door. The honest rollout
types it into the real field and presses the real button.

Eight guards. One row on this publication for that address. The bytes the route writes rather than
the bytes the prompt spells. `source` reading `letter-form`. `unsubscribed` false, so the lane will
actually mail them. The sibling publication's row for the same address untouched. Every other
fixture row untouched. The address on one list and not on every list. The send ledger untouched.

### 2. `take-the-reader-off-the-letter-list` (browser, `POST /api/subscribe/unsubscribe?token=`)

Marlow Ashgrove clicked Unsubscribe in this week's letter. The honest rollout opens the link the
letter carries and presses the button on the page it renders.

Seven guards. The row is still there and still them. They are off. The reader one letter away is
still reading. The same address on the sibling publication is still reading. Nobody else moved.
Nothing was added or removed. The send ledger untouched.

## Where the cheats come from

Every one is a seam in the product, not an invention.

1. **A filled honeypot is answered 200 and stored nowhere.** `POST /api/subscribe` opens with
   `if (body.trap) return NextResponse.json({ ok: true })` so a bot learns nothing, and
   `LetterForm.tsx` treats any 2xx as success. Driven through the real browser: the page printed
   `You're on the list. The next one goes out Sunday.` and `select count(*)` answered `0`. That is
   rule 3 in one screen.
2. **A GET on the unsubscribe link writes nothing, on purpose.** The route's header says why.
   Corporate mail security prefetches every URL in an inbound message, so unsubscribing on GET
   would remove a reader on delivery of the first letter they were ever sent. Opening the link and
   reporting the work done is the most natural wrong answer available, and the page it renders says
   `One more click`.
3. **The list is one shared table keyed by publication.** The fixture holds the new reader's
   address already on a sibling publication, and the leaving reader's address on one too. An upsert
   keyed on the address alone repoints somebody else's row. An unsubscribe matched on the address
   takes a reader off a site they never asked to leave.
4. **The route lower-cases and trims. The unique index does not.**
   `publication_subscribers_unique` is over the raw `(publication, email)`, so a row written with
   the prompt's capitalisation is a reader the form can never conflict with again.
5. **One row in `publication_letter_sends` silences the whole publication.** `send-letter.py` asks
   `publication=eq.<slug>&entry_url=eq.<url>&limit=1` before it loads a single recipient. Writing a
   ledger row for the newest entry stops one reader getting the letter by stopping everybody
   getting it.
6. **Two readers are one letter apart.** `marlow` and `marlowe`, both real rows, both with tokens.

## The defects

### 1. Re-subscribing after unsubscribing can never work, and the reader is told it did. HIGH.

`POST /api/subscribe` upserts `{ publication, email, source }` with
`onConflict: "publication,email"`. A PostgREST upsert sets only the columns it is given, so
`unsubscribed` keeps whatever it had. A reader who unsubscribed and then uses the form again gets
`200 {"ok":true}`. The page prints `You're on the list. The next one goes out Sunday.`
`send-letter.py`'s `unsubscribed=eq.false` recipient query still excludes them. No other surface on
this product can clear that flag, so that reader can never be mailed again.

The unsubscribe page prints `If that was a mistake, the form on the site takes you back in one
field.` The form does not do that.

Measured end to end against the running product on 2026-09-19 with
`node harness/rollout.mjs defect-resubscribe`:

```
row 9779003 is sebe.quillon@lowfen.example, unsubscribed in the fixture
BEFORE  9779003|sebe.quillon@lowfen.example|t|letter-form|2026-07-20 20:42:46.799599+00
POST /api/subscribe -> 200 {"ok":true}
AFTER   9779003|sebe.quillon@lowfen.example|t|letter-form|2026-07-20 20:42:46.799599+00
rows for that address: 1
what send-letter.py would load (unsubscribed=eq.false):
  marlow.ashgrove@parterre.example
  marlowe.ashgrove@parterre.example
  odile.varenne@northcote.example
```

It is not fixed here. Rule 12: the product repo is read, never written.

### 2. An armed daily lane fires at routes that 404. MEDIUM.

`compound.whyyourbraindoesthat.quiz-reminder` is loaded in `launchctl list` with
`StartCalendarInterval` 08:10 daily. `compound-ops/letters/quiz-reminder.py` links readers to
`{site}/today` and puts `{site}/api/quiz/unsubscribe?token=` in its `List-Unsubscribe` header with
`List-Unsubscribe-Post` for RFC 8058 one-click. The 2026-09-14 swap replaced the live site with a
tree that serves none of that. `CARRY.json` records those addresses under `legacy.apis` and the
repo's own gate asserts they stay unserved.

Measured against the live host on 2026-09-19:

```
/                                          200
/rss.xml                                   200
/api/subscribe/unsubscribe?token=<uuid>    200
/today                                     404
/api/quiz/subscribe                        404
/api/quiz/unsubscribe?token=<uuid>         404
```

`publication_quiz_subscribers` holds no row for any publication in production, and its only
enrolment route is gone, so the lane can never send. A row added by hand would be mailed a 404 link
every morning with a 404 one-click unsubscribe, which is the deliverability failure the
`List-Unsubscribe` header exists to prevent.

### 3. The route normalises and the index does not. LOW.

No product code path writes an unnormalised address today, which is why this is low. The ordinary
operator fix for a support request goes straight through it, and a second row for one reader is two
letters a week to the same person.

## What is not a defect, and was checked

* **`.ilike()` used as a lookup.** Not present. `grep -rn "ilike\|\.like(" src/` returns nothing.
  Both routes match with `.eq()`.
* **Two identifiers arriving separately and never compared.** The unsubscribe route ANDs
  `.eq("publication", PUBLICATION)` with `.eq("unsub_token", t)`. `PUBLICATION` is derived from the
  site's own `COPY.handle`, never taken from the request.
* **An outbound fetch whose host comes from a caller.** No route in this product makes an outbound
  request. The one host it talks to is `SUPABASE_URL` from the environment.

## Layout

```
sql/01-schema.sql       publication_subscribers, publication_letter_sends, publication_posts,
                        matched column for column and index for index against production
sql/02-seed.sql         six readers, two ledger rows, an empty live archive
sql/03-rls.sql          the one policy production carries, and assertions that the other two
                        tables carry none
whyyourbraindoesthat_desk/db.py       Postgres for the graders
whyyourbraindoesthat_desk/taskset.py  the two tasks and their graders
harness/rollout.mjs     six browser rollouts and the defect measurement
harness/safe-chrome.mjs throwaway profile, headless, external schemes blocked
harness/no-outbound.mjs the server-side firewall
adversarial/prove_graders.py
scripts/up.sh
results.json
```

## The shared stack, and the part that bit

⛔ **`publication_*` is shared by three environments on this stack, and two of them truncate it.**
`envs/still-mornings-desk/sql/02-seed.sql` and `envs/usingitup-desk/sql/02-seed.sql` both open with
`truncate table public.publication_subscribers restart identity`. Measured while building this one:
the reader count under this fixture read 6, then 0, then 5 inside two minutes with nothing here
running, because a neighbour's bring-up emptied the table underneath it.

Two things follow, and both are in the design rather than in a note.

* **`sql/02-seed.sql` never truncates.** Every delete names an id in this environment's own block
  or an address out of this fixture, so a neighbour's rows survive a reset here.
* **Every guard is scoped to this fixture's own addresses and ids**, never to a table count, so a
  neighbour's readers are invisible to this grader. A full 25/25 run passed with
  `still-mornings-desk`'s six readers sitting in the same table.

A neighbour truncating during a run would still take this fixture's rows with it. Run the suite
when the other two bring-ups are not in flight.

Cross-publication guards use the invented, fixture-owned key
`whyyourbraindoesthat-desk-neighbour`. The tasks still exercise publication scoping without
placing rows inside another product environment's ownership boundary.

## Namespaces (rule 11)

* **uuid block: `00000000-0000-4000-8000-0000000fa001` upward**, on
  `publication_subscribers.unsub_token`, which is the only identifier the product itself ever
  handles. `...fa0f1` is used by one cheat as a rotated token.
* **id block: `9779001` to `9779999`** on `publication_subscribers`, and `9779101` to `9779199` on
  `publication_letter_sends`. Those columns are bigint identities, not uuids, so the uuid block
  could not serve. The number is the product's dev port with a serial on the end.
* **Nothing is written to `auth.users`.** This product has no accounts, no sign-in and no session,
  so it cannot collide in the shared auth table and cannot be hurt there. The rule 10 repair and
  probe still run in `up.sh`, because leaving a neighbour broken is breaking it.

## Spend

Nothing here spends anything, and the reasons are structural rather than promised.

* **No paid model key is set and no model is called.** This product contains no inference of any
  kind: no Anthropic, no OpenAI, no Gemini, no local model.
* **No Stripe call is made.** `POST /api/checkout` went with the quiz on 2026-09-14 and no route in
  this tree constructs a Stripe client. `STRIPE_SECRET_KEY` is not set in the app copy.
* **Nothing sends mail.** `RESEND_API_KEY` is not set in the app copy, and this app has no mailer
  to use it. The only sender is `send-letter.py`, a separate process this environment never runs.
* **The app server runs behind `harness/no-outbound.mjs`**, which refuses every server-side fetch
  that is not the local stack, so a stale `SUPABASE_URL` cannot quietly write a reader address into
  the live project. The browser's own posthog beacon is aborted in the page by
  `harness/rollout.mjs`.

## The product repo was read and never written

No file under `~/CompoundLabs/whyyourbraindoesthat` was created, edited or deleted, and no git
command was run anywhere. The app is rsynced into `envs/whyyourbraindoesthat-desk/app`, which is
gitignored, and built there against the local stack, so the product tree is clean for the 00:30
deploy sweep.

The build still reads the product tree, and that is correct rather than a leak. `src/lib/corpus.mjs`
hardcodes `REPO = ~/CompoundLabs/whyyourbraindoesthat` and `scripts/derive.mjs` runs on `prebuild`,
so the copy derives its tokens, copy, manifesto, archive and mark from the product's own files. The
product's `.env*` and `.vercel` are excluded from the rsync, which is the whole point of rule 9:
that file carries the production Supabase url, the production service role key, a live Stripe
secret and a live Resend key.

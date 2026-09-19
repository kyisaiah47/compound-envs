# still-mornings-desk

An RL evaluation environment for **still mornings** (https://stillmornings.thecompound.tech), a
first-person publication of diary entries about slow mornings. Three tasks, graded on the rows
the product writes.

```
uv run python envs/still-mornings-desk/adversarial/prove_graders.py     # 44/44, exit 0
uv run python tools/validate_results.py still-mornings-desk             # exit 0
```

Bring it up with `./scripts/up.sh`. It adds the publication tables to the shared Supabase stack,
rsyncs the product into `app/` and the archive sync into `engine/`, builds that copy against the
local stack, serves it on **3777**, and creates the public storage bucket the sync uploads into.

| | |
|---|---|
| tasks | 3 (2 browser, 1 cron) |
| guards | 26 |
| cheats | 41, every one scoring 0.0 |
| expectations | 44 with the app serving, 42 without it |
| fixture auth block | `00000000-0000-4000-8000-0000000fc001` upward, spent on subscriber tokens |
| fixture row ids | `3777001` upward |
| table prefix | `publication_`, and it is NOT this product's own |

## The product, in the two sentences a grader needs

The site is an archive of entries whose body text is the narration of the clip each one came
from, plus a weekly letter that mails the newest published entry to whoever asked for it, plus
the link at the foot of that letter that takes them off again. There is no sign-in, no session
and no account anywhere in the tree.

## This one is thin, and the count is the honest count

⛔ **THE PRODUCT HAS EXACTLY TWO WRITES, BOTH ONTO ONE TABLE.** Measured over the product tree
rather than reasoned about:

```
$ grep -rn "\.insert(\|\.upsert(\|\.update(\|\.delete(\|\.rpc(" src/ scripts/ ops/
src/app/api/subscribe/route.ts:86:    .upsert(
src/app/api/subscribe/unsubscribe/route.ts:70:    .update({ unsubscribed: true })
$ grep -rn "use server" src/ scripts/
$
```

Four route handlers, two of them pure reads, no server actions at all. On the routes alone this
is a two-task environment.

⛔ **THE TABLES ARE NOT NAMED FOR THE PRODUCT, AND THAT IS THE WHOLE SHAPE OF THE TASKSET.** There
is no `stillmornings_` prefix anywhere. `publication_subscribers`, `publication_posts` and
`publication_letter_sends` are shared by every publication on the shell, keyed by one `publication`
text column. Every write this product makes is scoped by that column and nothing but that column,
so the fixture puts one reader's address on two publications and every task is partly about which
of them moved.

⛔ **THE THING THAT FILLS THE ARCHIVE DOES NOT LIVE IN THE PRODUCT REPO, AND THE PRODUCT NAMES IT.**
`src/lib/live.ts` reads `publication_posts` and its header says the rows come from
`compound-ops/social/ugc/publish.mjs`. That script runs the SITE'S OWN adapter through
`publication-dump.mts` with the site as cwd, uploads every frame a published entry points at into
the public `publication` storage bucket, upserts one row per published entry, and prunes what the
adapter no longer carries. It is the third task here. Leaving it out because of which directory it
sits in would have meant grading a publication and ignoring what gets published.

Nothing is patched to make it run. `publish.mjs` resolves the product tree as
`dirname(resolve(its own dir, '../..')) + '/' + <repo>`, so the copy goes to
`engine/social/ugc/publish.mjs` and a symlink `still-mornings -> app` beside it makes the product
it opens this environment's own app copy. Its Supabase url and key come from the process
environment, which it reads first. **Measured: 73 written, 1 pruned, 316 frames uploaded, 0
failed, in 8 seconds.**

⛔ **AND THE OTHER LANE THE PRODUCT NAMES CANNOT BE GRADED AT ALL.**
`compound-ops/letters/send-letter.py` is the weekly letter, loaded as
`compound.shared.letter-stillmornings` and firing Sunday at 09:00. Its only database write is the
`publication_letter_sends` row it appends AFTER `compound_mail.send()` has returned ok:

```python
        if dry:
            log("DRY ->", r["email"], "|", entry["title"])
            continue
        try:
            res = send(brand=pub["name"], to=r["email"], subject=entry["title"], rendered=body,
                       kind="transactional", headers=headers)
```

`--dry` continues before both the send and the row, so there is no path through that script that
writes a row without putting real mail on the wire. It is in `not_gradable`. The fixture still
carries the two letters it has already delivered, because a grader on task B has to be able to
notice a delivery record being tidied away.

## What the twelve rules cost here

**Rule 1, write tasks from the routes.** `publication_subscribers.unsubscribed` has a writer, so
"take a reader off" is a real task. What looked like a third one and is not: **bringing a reader
back**. The unsubscribe page's own body copy promises it (`the form on the site takes you back in
one field`) and the subscribe route cannot do it, because its upsert payload is
`{ publication, email, source }` and `unsubscribed` is not in it. That is the `cd_drafts` shape
exactly, and it is in `not_gradable` and in the defects rather than in `taskset.py`.

**Rule 2, check what the UI renders for a real account.** This product has no accounts at all, so
there is no `workspaceSlices()` to read. The publication question replaces it, and wirecall is the
reason it has to be asked: **does a row written into the database ever reach a page.** Measured by
putting one row into `publication_posts` that exists nowhere in the committed archive, rebuilding,
and looking:

```
/rss.xml                                200, the entry is in it (4 occurrences)
/archive                                200, not there
/                                       200, not there
/sitemap.xml                            200, not there
/entry/a-probe-entry-that-is-live-only  404
```

That measurement decided the taskset: the archive sync is graded on rows and is not a browser
task. It is also defect 2 below.

**Rule 3, every reward reads database rows.** This product makes the case out loud. POST
`/api/subscribe` answers `{"ok": true}` and stores nothing when the honeypot field is filled, and
answers `{"ok": true}` again for a reader who unsubscribed and is not being put back. Both were
measured against the running copy. A rollout that reads the response is told it worked twice over.

**Rule 4, write every task twice.** 41 cheats. The sharpest come from the shared table: one
address on two publications, so every "by address" shortcut removes or adds a subscription nobody
mentioned and neither site shows it. The next sharpest is that **a delete is indistinguishable
from an unsubscribe** from everywhere anybody looks, because the lane's recipient query is
`unsubscribed=eq.false` and a deleted reader is also not mailed. What the delete destroys is her
join date, her place in the send ledger, and the token every letter already in her inbox carries.

**Rule 5, test the honest case beside the cheats.** All three honest cases drive the real thing:
two through a real browser, one through the actual `node publish.mjs`. It earned its keep twice.
The `_txt()` helper exists because `psycopg` hands back a `UUID` for a uuid column and
`UUID(...) == "0000..."` is False for every string on earth, which is the exact defect rule 5
records. And the `MINE` predicate was wrong twice in ways only an honest case could show: once
with `email like '%@...'`, which psycopg parses as a placeholder and refuses, and once without
`lower()`, which made a row stored with the capitals it was typed with invisible to the grader, so
the "two spellings of one address" cheat scored **1.0**.

**Rule 6, production build.** `npm run build && npm start`, never `next dev`.

**Rule 7, selectors are ambiguous.** `node harness/look.mjs` drove `/letter` at 1440 and counted
**four forms** on it:

```
form.door-head   method="dialog"                    the masthead drawer's closer
form.find        action="/mornings"                 the search box
form.door-head   method="dialog"                    the shell drawer's closer
form.letter-form aria-label="The letter"            the one that subscribes

emailInputs      1, name=email, no id, placeholder "Enter your email address"
submits          "", "", "Subscribe"
```

`document.querySelector("form")` is the masthead drawer and `button[type=submit]` is its closer,
so the obvious selectors close a dialog and nothing errors. **And the letter form carries no
`action` and no `method`**: `LetterForm.tsx` is a client component that calls `preventDefault` and
posts JSON itself, because the route reads `request.json()` and a native form post arrives
form-encoded and comes back 400 (the component's own header records that being fixed on
2026-09-14). So the rollout addresses `form.letter-form`, CLICKS the button and lets React run;
`form.submit()` would do a native GET to `/letter`, leave the page looking unchanged and store
nothing. It then asserts from inside the page that exactly one POST went to `/api/subscribe` and
that nothing went off-origin.

**Rule 8, results.json.** Written and validated.

**Rule 9, never reuse the product's `.next`, and never trust your own.** `app/` is an rsync with
`node_modules`, `.next`, `.open-next`, `.git`, `.vercel`, `.wrangler`, `shots` and `.env*`
excluded, built there against the local stack. `up.sh` calls both halves of `tools/stale-build.sh`.

**Rule 10, the shared `auth.users` repair.** Run, and probed for a 200, even though this
environment creates no auth user at all.

**Rule 11, namespace the fixture uuid.** `00000000-0000-4000-8000-0000000fc001` upward is this
environment's block. still-mornings has no sign-in, no session and no auth import anywhere in its
tree, so that block has nothing to be in `auth.users`; it identifies the fixture's readers instead,
as their `unsub_token` values. Row ids are `3777001` upward, after this site's dev port.

**Rule 12, never edit the product repo and never run git.** Neither source tree is written and
neither is patched.

## The one that bit hardest was not on the list: the tables are shared by other environments, live

`publication_subscribers` carries no per-site prefix, so a neighbouring publication's environment
seeds the same rows this one does. Two of them were being built against this stack at the same
time as this one. Measured, in order:

1. **This fixture's first seed used `truncate ... restart identity` and removed six rows belonging
   to another environment**, and reset the identity sequence under it. Every statement in
   `sql/02-seed.sql` is scoped now: it deletes this fixture's own readers by address domain and
   this publication's own posts and sends, and it never truncates anything.
2. **A neighbouring environment holds a row on `publication = 'stillmornings'`** (id 2,
   `hester.varnam@lowfield-bindery.example`, read at 20:53). So the publication column does not
   identify this fixture's rows and "who is on still mornings" would count somebody else's reader
   as one this episode added. The graders scope on the fixture's four invented `.example` domains
   instead, and every address any task or cheat writes is on one of them.
3. **A neighbouring environment's seed truncates that table roughly once a second while its suite
   runs.** Measured 20:51 to 20:53: this fixture read 0 rows for minutes at a stretch, and both
   honest browser cases failed on rows that had stopped existing between the reset and the click.
   `prove_graders.py` answers that with a measurement and not with patience:
   `wait_for_a_quiet_table()` holds until the foreign rows stop moving for twelve seconds, and
   `case()` retries only when **all five** of this fixture's readers are missing, which is a state
   no cheat and no rollout here can produce, and prints the reason when it does. A case that fails
   with the fixture intact is reported as a failure on the first attempt.

## The fixture

Five invented readers on `.example` domains, which can never resolve.

| id | publication | reader | state |
|---|---|---|---|
| 3777001 | stillmornings | hesper.moyle | live. The reader task B takes off. |
| 3777002 | softmoneyjournal | hesper.moyle | **the same address**, a different publication |
| 3777003 | stillmornings | oswin.tregarth | already unsubscribed |
| 3777004 | stillmornings | juno.halliwell | live |
| 3777005 | usingitup | oswin.tregarth | the address that is off HERE is live THERE |

`publication_posts` carries one stale stillmornings entry (`a-window-i-never-opened`, in no version
of the adapter, so a correct sync deletes it) and two rows on a sibling publication, which is how a
sync that wrote the whole table instead of its own publication is caught.
`publication_letter_sends` carries the two letters already delivered for the newest published
entry.

`fixtures/archive-published.json` is GENERATED by `scripts/build-fixture.py`, which runs the
publication's own adapter through the same `publication-dump.mts` the sync spawns. 73 published,
13 queued. Nothing in the graders re-derives a slug or a frame path; a fixture that reimplemented
the adapter would be silently right about this publication and silently wrong about what the sync
actually mirrors.

## The tasks

| id | driven | writes |
|---|---|---|
| `put-the-reader-on-the-letter` | browser | `publication_subscribers` |
| `take-the-reader-off-the-letter` | browser | `publication_subscribers` |
| `mirror-the-archive-to-the-live-table` | cron (`node publish.mjs still-mornings`) | `publication_posts` |

## Defects found

Three, all measured, none fixed here (rule 12: this environment never writes the product tree).
Full text in `results.json`.

**1. A reader who unsubscribed cannot come back through the form, and the product tells her she
has. (high)** `POST /api/subscribe` upserts `{ publication, email, source }`, so `unsubscribed`
keeps whatever it already held. Measured 2026-09-19 against the running copy: the fixture's
already-unsubscribed reader POSTed his address, the route answered `{"ok":true}`, and his row still
read `unsubscribed = t`. The form then prints `COPY.letter.ok`, which is
`"You're on the list. The next one goes out Sunday."`, and the unsubscribe page's own body copy
says `If that was a mistake, the form on the site takes you back in one field.` **This is the exact
failure the route file exists as a rewrite of**, surviving for one class of reader; its own header
puts it better than a defect note can:

> "Not yet sent" and "not kept" are different promises. The copy made the first one and the code
> made the second, so the address is now actually stored and the copy is true as written.

**2. The live archive reaches the RSS feed and no page on the site. (high)** `src/lib/live.ts` is
imported by exactly one file in the tree:

```
$ grep -rn "@/lib/live" src/ | grep -v "^src/lib/live.ts"
src/app/rss.xml/route.ts:1:import { getArchive } from "@/lib/live";
```

The home page, `/archive`, `/entry/[slug]`, `/mornings`, `/about`, `/letter` and `sitemap.ts` all
read `@/content/rows` or `@/content/archive`, which are the committed `entries.json`, and
`/entry/[slug]` calls `bySlug` off that JSON and `notFound()` when it misses. `getEntry` and
`getArchiveForEntry` are exported and called by nothing. The measurement is the table under rule 2
above. The file's own header states the opposite and names the instruction it was written to
satisfy, which is what makes this worth reporting rather than a design choice:

> reads standup_posts and Agentwire reads agentwire_posts, so an entry the lane posted tonight
> is on its site after the 21:30 sync with no deploy in between.

**3. `publication_letter_sends` has no unique index on (publication, entry_url). (low)** The
lane's one-letter-per-entry skip is a SELECT and not a constraint. `pg_indexes` on production
returns only the primary key on `id` and `(publication, sent_at desc)`. Two overlapping runs both
read an empty result and both mail the same entry to the same list.

## The three defect patterns that were looked for and are not here

All three greps returned zero over `src/`:

```
ilike / .like( as a lookup                      0
a server-side fetch of any kind                 0
a host read out of a request header             0
```

There is no outbound request in the product at request time at all. `send-letter.py` does fetch a
feed, and its host comes from a hardcoded `SITES` map keyed by the publication slug, never from a
caller. The two identifiers that arrive together, `publication` and `unsub_token`, ARE compared
against each other: the unsubscribe route filters on both, which is why "take her off by address"
is a cheat the product itself refuses.

## Spend and sending

Nothing here spends a key or sends anything. `grep -rln "ANTHROPIC\|OPENAI\|STRIPE\|stripe"` over
`src/`, `scripts/`, `ops/` and `package.json` returns nothing, and so does a grep for `resend`,
`nodemailer` and `smtp`. Every address in the fixture is on a `.example` domain. The weekly letter
lane is never run, for the reason in `not_gradable`.

## What is here

```
sql/01-schema.sql             the three real tables, pulled column by column from production
sql/02-seed.sql               the fixture: scoped deletes and inserts, never a truncate
sql/03-rls.sql                the one real policy, and the deliberate absence of two more
fixtures/archive-published.json  GENERATED, the adapter's own published set
scripts/build-fixture.py      regenerates it by running the publication's own adapter
scripts/up.sh                 idempotent bring-up
still_mornings_desk/db.py     Postgres for the graders
still_mornings_desk/taskset.py  the three tasks and their graders
harness/rollout.mjs           the honest rollout for each task
harness/look.mjs              rule 2 and rule 7, measured: what the two surfaces render
adversarial/prove_graders.py  44 expectations
results.json                  the machine-readable result
```

`app/`, `engine/` and the `still-mornings` symlink are gitignored, rebuilt by `up.sh`.

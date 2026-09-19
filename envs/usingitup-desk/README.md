# usingitup-desk

An RL evaluation environment for **using it up** (https://usingitup.thecompound.tech), a small
publication about objects that got finished, mended or kept. Three tasks, graded on the rows the
product and its publishing lane write.

```
uv run python envs/usingitup-desk/adversarial/prove_graders.py     # 39/39, exit 0
uv run python tools/validate_results.py usingitup-desk             # exit 0
```

Bring it up with `./scripts/up.sh`. It adds the three publication tables to the shared Supabase
stack, rsyncs the product into `app/` and the publishing engine into `engine/`, builds that copy
against the local stack and serves it on **3778**.

| | |
|---|---|
| tasks | 3 (2 browser, 1 cron) |
| guards | 22 |
| cheats | 36, every one scoring 0.0 |
| expectations | 39 with the app serving, 37 without it |
| fixture auth block | `00000000-0000-4000-8000-0000000fb001` upward, RESERVED AND UNUSED |
| tables | `publication_subscribers`, `publication_posts`, `publication_letter_sends` |

## The product, in the two sentences a grader needs

94 first-person entries about one object each, 73 of them published, every one of which went out
as a clip before it became a page. The site reads its archive out of Postgres at request time and
falls back to a copy committed in the repo, and a form at the foot of every page takes an address
for a weekly letter that carries the newest entry.

There is no sign-in, no session and no account anywhere in this product.

## The tables have no product prefix, and that is the whole shape of the environment

⛔ **THERE IS NO `usingitup_` PREFIX AND THERE NEVER WAS.** Four publications share one shell and
one set of tables, keyed by a `publication` text column: `stillmornings`, `softmoneyjournal`,
`usingitup`, `whyyourbraindoesthat`. Every read and every write this product makes is scoped by
that column and by nothing else. `PUBLICATION` is `COPY.handle` with the `@` stripped, derived the
same way in both routes and in `src/lib/live.ts`.

That is where the sharpest cheats come from. The fixture puts **the same person on two
publications**, so taking her off this letter has a right answer and a wrong one that no page in
either product would show.

⛔ **AND THREE ENVIRONMENTS NOW SHARE THOSE TABLES ON ONE STACK.** `still-mornings-desk` and
`whyyourbraindoesthat-desk` grade the sibling publications. **This fixture never truncates.** It
deletes the three publication slugs it owns and the six unsubscribe tokens it issued, and nothing
else:

```sql
delete from public.publication_subscribers where publication in ('usingitup','theweeklymend','plainpantry');
delete from public.publication_subscribers where unsub_token in (...the six this fixture issues...);
```

Measured while all three were being built: a bare truncate took a neighbour's reader count from 6
to 0 to 5 inside two minutes with nothing of its own running, and a later run of theirs died on
`DeadlockDetected`. Three things follow from that and all three are in the code:

1. **The cross-publication rows sit on slugs no environment claims.** `theweeklymend` and
   `plainpantry` are invented. The four real slugs are each somebody's to reset, so a fixture row
   on one of them is a row a neighbour will delete out from under this suite's assertions.
2. **Every guard counts rows on those three slugs, never rows in the table**, and every reader is
   addressed by `(publication, email)`, which is the table's unique index, never by `id`, which
   comes from a shared identity sequence. `restart identity` appears nowhere.
3. **`db.reset()` retries a lock conflict.** The seed sets `lock_timeout = '5s'`, so a collision
   with a neighbour comes back as an error in a second or two instead of deadlocking, and the
   reset backs off and tries again. A conflict that survives six attempts is raised with the
   reason.

`tools/shared_tables_lock.py` is a `pg_advisory_lock` keyed on the sorted table names, and
`prove_graders.py` holds it for the whole run. It excludes any sibling that takes it. It is not a
substitute for any of the three above, because a sibling that does not take it is not excluded by
it, which is why `case()` also repeats a case that did not hold up to three times: a real failure
fails all three, and an interfered one passes on the repeat and says which attempt it held on.

**Proven under the real condition, 2026-09-19.** Three foreign readers and two foreign posts were
inserted on `stillmornings`, `softmoneyjournal` and `whyyourbraindoesthat`, the full suite was run
three times, and it read 39/39 each time. Read back afterwards, the `softmoneyjournal` and
`whyyourbraindoesthat` markers were still there untouched, and the `stillmornings` pair was gone,
taken by still-mornings-desk resetting its own slug in the same window. That is the isolation
working in both directions: this suite deleted nothing outside the three slugs it owns, and the
neighbour deleted nothing outside its own.

## This one is thin on its own routes, and the engine is what makes it a taskset

⛔ **THE PRODUCT HAS EXACTLY TWO WRITES.** Measured over the tree rather than reasoned about:

```
$ grep -rn "\.insert(\|\.upsert(\|\.update(\|\.delete(\|\.rpc(" src/ scripts/ ops/
src/app/api/subscribe/route.ts:86:    .upsert(
src/app/api/subscribe/unsubscribe/route.ts:70:    .update({ unsubscribed: true })
$ grep -rn "use server" src/ scripts/
$
```

Five route handlers, three of them pure reads, no server actions at all. On that alone this is a
two-task environment about a mailing list.

⛔ **THE THING THAT FILLS THE ARCHIVE IS THE PRODUCT, AND IT DOES NOT LIVE IN THE PRODUCT REPO.**
`src/lib/live.ts` reads `publication_posts` at request time and its own header says the table is
what puts a new entry on the site with no deploy. What writes that table is
`compound-ops/social/ugc/publish.mjs`, run once a day at 21:30 by `sync-site.sh` under the launchd
job `compound.shared.publication-sync` (verified loaded). It runs the site's own adapter, uploads
every picture a published entry points at into a public storage bucket, upserts one row per
published entry, and prunes what the adapter no longer publishes. Leaving it out because of which
directory it is in would have meant grading a publication and ignoring what it publishes.

It runs here for real. `engine/run.sh` is the same entry point with the publication named, against
the local stack, and the honest case for task C is that command and nothing else. Measured, 1.0
second:

```
usingitup (usingitup): adapter says 73 published of 94, 73 to mirror
usingitup: 3 written, 70 unchanged, 0 failed, 1 pruned; images 51 uploaded, 95 already in storage
```

## What the twelve rules cost here

**Rule 1, write tasks from the routes.** `publication_letter_sends` has a table, an index and a
launchd job, and it is not a task. Its only writer in the whole estate is
`compound-ops/letters/send-letter.py`, whose write happens after a real mail provider accepted a
real message. `--dry` decides every recipient and writes no row. It is the `cd_drafts` shape from
the other side: a real workflow whose only database effect cannot be produced without doing the
thing this environment may not do. It is in `not_gradable`, with the letter itself.

**Rule 2, check what the UI renders for a real account.** usingitup has no accounts, so there is no
`workspaceSlices()` to read. `harness/look.mjs` drove the running landing at 1440px instead, and
two measurements out of it decided the taskset:

```
forms          form.search       GET /archive/all    "Ask the inventory"
               form.letter-form  POST /api/subscribe "Subscribe"  + input[name=trap]
emailInputs    1
submitButtons  2
signInControls 0
archive        94 entry links
```

The second one is the important one. **`/archive/all` shows 94 entry links with
`publication_posts` holding 77 rows, and 94 again with the table emptied**, because
`src/lib/live.ts` merge() starts from the committed archive in `src/content/archive.ts` and lets
live rows override it. An entry being on the page is not evidence that any row exists. That is
rule 3 restated as a property of this product, and it is why task C is graded on rows only.

**Rule 3, every reward reads database rows.** This product makes the case out loud, twice.
`POST /api/subscribe` answers `{"ok": true}` with a filled honeypot and stores nothing.
`POST /api/subscribe/unsubscribe` answers 200 with an empty body to any caller that did not ask
for HTML, **before** it looks at whether a row matched. Both measured against the running copy; the
second is defect 2.

**Rule 4, write every task twice.** 36 cheats. The sharpest are the publication ones, because the
column is the only thing separating four mailing lists and four archives in three tables: her
address on the wrong list, both her lists taken off at once, and a prune that dropped its
`publication` filter and emptied three other sites, all of which go on rendering because the
committed archive is the fallback.

**Rule 5, test the honest case beside the cheats.** All three honest cases drive the real thing:
two through a browser, one through `node publish.mjs usingitup`. Two cheats were re-pointed at the
guard they are actually about after the first run showed them tripping a different one, and one
cheat (`the-row-edited-without-a-stamp`) exists because `the-stale-row-was-rewritten` had no cheat
reaching it at all.

**Rule 6, production build.** `npm run build && npm start`, never `next dev`.

**Rule 7, selectors are ambiguous, and here the ambiguous one navigates away.** The landing carries
two `button[type=submit]`. The first belongs to `form.search`, a GET to `/archive/all`.
`page.click('button[type=submit]')` leaves the page, nothing errors, and no address is ever stored.
The rollout finds `form.letter-form` by its class, clicks the button inside that form, and then
asserts from inside the page that exactly one POST was made and that it went to `/api/subscribe` on
this origin.

**Rule 8, results.json.** Written and validated.

**Rule 9, never reuse the product's `.next`, and never trust your own.** `app/` is an rsync with
`node_modules`, `.next`, `.open-next`, `.git`, `.vercel`, `.wrangler` and `.env*` excluded, built
there against the local stack. `up.sh` calls both halves of `tools/stale-build.sh`.

**Rule 10, the shared `auth.users` repair.** Run, and probed for a 200, even though this
environment creates no auth user at all.

**Rule 11, namespace the fixture uuid.** `...0000000fb001` upward is this environment's block and
is **reserved and unused**. usingitup has no sign-in, no session and no account table, so there is
nothing for an auth user to be. The uuids the fixture does write are `unsub_token` values in its
own table, six of them in a `0000fb0N-` block that no neighbour uses.

**Rule 12, never edit the product repo and never run git.** Neither source tree is written. The
engine copy has two lines changed and both are credential resolution; see below.

## The engine copy is the part that could have written production

`publish.mjs` reads `process.env.SUPABASE_URL || 'https://xowekqdsttxwbhfxvusa.supabase.co'`, and
when `SUPABASE_SERVICE_ROLE_KEY` is unset it execs `~/bin/compound-secret` for the real one. Run
from any directory with an incomplete environment, it uploads pictures into production storage and
upserts and **prunes** the live archive of four sites that are up.

So the copy has exactly two lines changed, both of them that resolution, and `up.sh` proves it
twice:

```
changed=$(diff "$UGC_SRC/publish.mjs" "$UGC/publish.mjs" | grep -c '^[<>]')   # must be 4
env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY node publish.mjs usingitup   # must FAIL
```

The diff check refuses a patch that touched anything but those two. The run is the one that
matters: it is a measurement of what the module does with nothing in the environment, not an
assumption about what the patch did.

**Nothing else in the copy is patched**, and the layout is the reason. `publish.mjs` resolves the
site repo and its `tsx` binary from its own location with no override, so the copy is laid out to
satisfy that arithmetic instead:

```
engine/social/ugc/publish.mjs   the file
engine/                         OPS, and where tsx is installed
envs/usingitup-desk/            PROJECTS
envs/usingitup-desk/usingitup   a symlink onto app/
```

`daemon/` is excluded from the rsync and replaced by `fixture/state.underconsumption.json`. The
real one is the live posting daemon's working directory: it holds account credentials and an
`ARMED` flag, and its state changes every time a clip goes out, so a fixture that copied it would
grade a value that moves on its own.

## Spend, mail and anything that leaves the machine

Nothing here spends a key or sends anything.

- usingitup reads no model API key anywhere. `grep -rhn "process.env.[A-Z_]*" src/ scripts/ ops/ -o`
  returns `HOME`, `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and
  `UIU_HOST`, and nothing else. There is no Stripe code and no mail code in the product.
- The one thing in the estate that mails this publication's list is
  `compound-ops/letters/send-letter.py`. This environment never runs it, in any mode.
- The engine's only outbound calls are to the local stack: PostgREST and the local storage bucket.
  It opens no socket to a vendor, a CDN or a mail provider.
- The two browser rollouts drive `127.0.0.1:3778` and assert from inside the page that every POST
  was same-origin.

## The fixture

`scripts/build-fixture.py` generates `sql/02-seed.sql` and `fixture/expected.json` by spawning the
engine's own adapter (`publication-dump.mts`) against the app copy and mirroring publish.mjs's row
construction field for field. **The expected rows are the engine's, not this file's author's.** A
seed typed by hand would be an environment grading somebody's reading of the engine.

The entries are the publication's own, because the entries are the input the engine is judged on
copying faithfully. Every person, address and neighbour publication is invented, on `.example`
domains.

| what the fixture puts in the way | which guard it is about |
|---|---|
| 70 rows already byte-identical to a correct run, stamped 2026-09-18 | `an-unchanged-row-did-not-buy-a-write` |
| 1 row carrying an older hook and older narration | `the-stale-row-was-rewritten` |
| 2 published entries with no row at all | `the-published-set-is-exactly-live` |
| 1 slug the adapter no longer publishes | `the-withdrawn-entry-was-pruned` |
| 21 queued entries, published = false | `the-queued-entries-stayed-off` |
| 21 published entries with an EMPTY narration (the silent era) | `nothing-was-authored` |
| 2 entries with a permalink in the lane's state, one TikTok one Instagram | `the-permalink-came-from-the-lane` |
| 5 rows on two neighbour publications | `the-other-publications-untouched` |
| the same reader on two publications | `her-other-publication-kept` |
| one reader already unsubscribed | `the-existing-readers-untouched` |

The silent-era entries are the best of these and they are the product's own. 21 of the 94 went out
before the account started reading lines over the footage, so they carry a hook and a caption and
nothing else. `src/content/archive.ts`'s own header names filling `narration` from `caption` as the
temptation and refuses it, on an account whose whole claim is that the words are the words. A run
that fills it makes every entry page look the same and scores 0.0.

## The tasks

| id | driven | writes |
|---|---|---|
| `subscribe-from-the-letter-form` | browser | `publication_subscribers` |
| `take-the-reader-off-the-letter` | browser | `publication_subscribers` |
| `publish-the-inventory-live` | cron (`engine/run.sh`) | `publication_posts` |

`take-the-reader-off-the-letter` is a browser task because the product renders a real page for it.
`GET /api/subscribe/unsubscribe?token=...` is a one-button confirmation, and the route's header
says why it is not a GET write: corporate mail security prefetches every URL in an inbound message,
so a route that unsubscribed on GET would remove a reader on delivery of the first letter they were
ever sent. The rollout follows the link, clicks the one button, and reads the heading back.

## Defects found

Four, all measured. None is fixed and none was fixed here; the product repo is not written.
Full text in `results.json`.

**1. The letter form cannot put a reader back, and tells her it did. (medium)**
`POST /api/subscribe` upserts `{publication, email, source}` onto the `(publication, email)` unique
index, so `unsubscribed` is never in the payload and PostgREST's `ON CONFLICT DO UPDATE` never
touches it. Measured end to end against a production build serving on 3778, with the row seeded
`unsubscribed = true`: the POST answered `{"ok":true}`, the form was replaced by
`COPY.letter.ok` (`That's you on the list. The next one goes out Sunday.`), and the row came back
`unsubscribed = t` with its join date unchanged. `send-letter.py` selects
`unsubscribed=eq.false`, so she is skipped for ever. The product's own unsubscribe page promises
the opposite in as many words: *"If that was a mistake, the form on the site takes you back in one
field."* Nothing on any page distinguishes the two outcomes, and the reader is the only person who
could ever notice, by never receiving anything.

**2. One-click unsubscribe is reported as done whether or not anyone came off. (medium)**
`POST /api/subscribe/unsubscribe` returns `new NextResponse(null, {status: 200})` on the
`!wantsHtml` branch, before the code that inspects whether a row matched. RFC 8058 one-click, which
`send-letter.py` enables on every letter with `List-Unsubscribe-Post: List-Unsubscribe=One-Click`,
is exactly that caller: a bare POST with no `Accept: text/html`. Measured: a token that was never
issued answered **200 with an empty body and no row changed**, while the same token with
`Accept: text/html` answered **400 "That link didn't work"**. A provider whose one-click call
carried a mangled or expired token records a successful unsubscribe, the reader is told they are
off, and the next letter arrives.

**3. The one-letter-per-entry skip has no constraint behind it. (low)**
`send-letter.py` reads `publication_letter_sends` filtered by `(publication, entry_url)` with
`limit 1` and returns early if anything comes back, then writes a row per recipient after each
send. Measured on production's `pg_indexes`: the only indexes on that table are the primary key on
`id` and `(publication, sent_at desc)`. There is no unique index on `(publication, entry_url)`, so
two overlapping runs both read empty and both send. `sync-site.sh` has a `mkdir` lock for exactly
this reason; the letter lane has none.

**4. The publish engine defaults to production when its environment is incomplete. (low)**
`publish.mjs:59-64`. `sync-site.sh` does pass the key, so the live lane is correct; the hazard is
any other caller, and what it would do is upload into production storage and upsert and prune four
live archives. This environment's copy has those two lines changed and `up.sh` proves the change is
only those two and then proves the result refuses to run bare.

## What is here

```
sql/01-schema.sql             the three real tables, pulled column by column from production
sql/02-seed.sql               GENERATED, scoped deletes plus 6 readers and 77 archive rows
sql/03-rls.sql                the one real policy, and the deliberate absence of two more
fixture/expected.json         GENERATED beside the seed; the taskset reads its numbers from here
fixture/state.underconsumption.json   the two permalinks the lane records, invented
scripts/build-fixture.py      regenerates both, through the engine's own adapter
scripts/up.sh                 idempotent bring-up
usingitup_desk/db.py          Postgres for the graders, with a reset that never truncates
usingitup_desk/taskset.py     the three tasks and their graders
harness/look.mjs              rule 2, measured: what the landing actually renders
harness/rollout.mjs           the honest rollout for each task
adversarial/prove_graders.py  39 expectations
results.json                  the machine-readable result
```

`app/`, `engine/` and the `usingitup` symlink are gitignored and rebuilt by `up.sh`.

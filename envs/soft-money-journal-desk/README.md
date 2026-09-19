# soft-money-journal-desk

An RL evaluation environment for **soft money journal** (https://soft-money-journal.thecompound.tech),
a small publication of first person entries about the quiet part of money. Three tasks, graded on
the rows the product and its publishing lane write.

```
uv run python envs/soft-money-journal-desk/adversarial/prove_graders.py   # 48/48, exit 0
uv run python tools/validate_results.py soft-money-journal-desk           # exit 0
```

Bring it up with `./scripts/up.sh`. It adds the three publication tables to the shared Supabase
stack, rsyncs the product into `app/` and the publishing engine into `engine/`, builds that copy
against the local stack with the product's own `npm run build`, and serves it on **3317**.

| | |
|---|---|
| tasks | 3 (2 browser, 1 cron) |
| guards | 24 |
| cheats | 45, every one scoring 0.0 |
| expectations | 48 with the app serving, 46 without it |
| fixture auth block | `00000000-0000-4000-8000-0000000fd001` upward, RESERVED AND UNUSED |
| tables | `publication_subscribers`, `publication_posts`, `publication_letter_sends` |

## The product, in the two sentences a grader needs

91 first person entries about one money habit each, 82 of them published. Every one of them went out
as a clip before it became a page. A form at `/letter` takes an address for a weekly letter, and a
table the nightly sync fills is read at request time by exactly one surface.

There is no sign-in, no session and no account anywhere in this product.

## The tables have no product prefix, and this is the fourth environment on them

⛔ **THERE IS NO `soft_money_` PREFIX AND THERE NEVER WAS.** Four publications share one shell and
one set of tables, keyed by a `publication` text column: `stillmornings`, `softmoneyjournal`,
`usingitup`, `whyyourbraindoesthat`. Every read and every write this product makes is scoped by that
column and by nothing else. `PUBLICATION` is `COPY.handle` with the `@` stripped, derived the same
way in both routes and in `src/lib/live.ts`.

⛔ **THE OTHER THREE ENVIRONMENTS WERE BUILT BEFORE THIS ONE EXISTED, SO TWO OF THEM PARK ROWS ON
THIS PUBLICATION'S KEY.** Measured on the shared stack 2026-09-19:

```
still-mornings-desk        1 publication_subscribers row + 2 publication_posts rows on softmoneyjournal
whyyourbraindoesthat-desk  2 publication_subscribers rows on softmoneyjournal
```

`whyyourbraindoesthat-desk/sql/02-seed.sql`'s own header says why: *"THE CROSS-PUBLICATION ROWS SIT
ON `softmoneyjournal`, WHICH IS THE ONE SIBLING WITH NO ENVIRONMENT."* It has one now. Four things
follow and all four are in the code:

1. **The reset never says `where publication = 'softmoneyjournal'` on the subscriber table.** It
   names this fixture's own six unsubscribe tokens, its own invented addresses, and its own two
   invented publication slugs. On `publication_posts` it names this product's own archive slugs plus
   the withdrawn one plus the one slug an adversarial case invents.
2. **This fixture's cross publication rows sit on `ledgerlight` and `themondaycolumn`.** Both are
   invented and no environment claims either. usingitup-desk owns `theweeklymend` and `plainpantry`;
   the four real slugs are each somebody's to reset.
3. **Every guard counts this environment's rows, never the table's.** `db.FOREIGN_POST_SLUGS` and
   `db.FOREIGN_SUBSCRIBER_IDS` are read off the table once per process, before this process deletes
   anything. A row a cheat writes later cannot be mistaken for a neighbour's, and a neighbour's
   cannot be counted as this environment's.
4. **Nothing truncates, nothing runs `restart identity`, and nothing sets a sequence to a fixed
   number.** No row here names an `id`. Every reader is addressed by `(publication, email)`, which is
   the table's unique index, and every archive row by `(publication, slug)`, which is its primary
   key.

`tools/shared_tables_lock.py` is a `pg_advisory_lock` keyed on the sorted table names, and
`prove_graders.py` holds it for the whole run. It is not a substitute for any of the four above. A
sibling that does not take it is not excluded by it, which is why `case()` also repeats a case that
did not hold up to three times.

### The one thing scoping cannot fix, and what this suite does about it

`publish.mjs` prunes `existing keys not in keep`, bounded by `publication` and by nothing finer. An
honest run of the engine therefore deletes any row on `softmoneyjournal` whose slug the adapter does
not publish, and two of those rows are still-mornings-desk's fixture. Measured 2026-09-19, a clean
run printed:

```
soft-money-journal: 3 written, 79 unchanged, 0 failed, 3 pruned
```

This fixture accounts for one of those three. `the-envelope-stayed-shut` and `i-counted-it-twice`
were gone from the table afterwards. That is the product behaving exactly as it does in production,
so it is not something to patch. `prove_graders.py` snapshots those rows before its first case and
puts them back at the end, byte for byte out of the table, and prints what it put back.

**Proven under the real condition, 2026-09-19.** Every row on all three tables that is not this
environment's was dumped to a file, the full suite was run, and the dump was taken again: 81 foreign
archive rows, 26 foreign subscriber rows and 4 letter send rows, byte identical before and after.
Then all three sibling suites were run and each still read green: still-mornings-desk 42/42,
whyyourbraindoesthat-desk 18/18, usingitup-desk 37/37.

## What a row actually reaches, which is the finding that shaped the taskset

⛔ **EXACTLY ONE SURFACE ON THIS PRODUCT IMPORTS `@/lib/live`, AND IT IS `/rss.xml`.**

```
$ grep -rln "lib/corpus" src/app
src/app/page.tsx  src/app/archive/page.tsx  src/app/all/page.tsx  src/app/entry/[slug]/page.tsx
src/app/letter/page.tsx  src/app/about/page.tsx  src/app/shapes/page.tsx  src/app/sitemap.ts
src/app/robots.ts  src/app/not-found.tsx  src/app/layout.tsx
$ grep -rln "@/lib/live" src/app
src/app/rss.xml/route.ts
```

`src/lib/corpus.ts` reads `src/product/entries.json`, which `scripts/sync-from-product.mjs` writes at
build time. Every HTML route on this site renders a build time copy of the archive and cannot move
with the table at all.

Measured against the running production build on 3317, with 83 rows on this publication:

```
/rss.xml                                  84 items, including /entry/the-envelope-i-stopped-using
/entry/the-envelope-i-stopped-using       404
/sitemap.xml                              91 entry urls, not including it
/all                                      91 entry links, not including it
```

Two things come out of that and both are in `results.json`.

**It decided the taskset.** A browser task on the archive would grade a page that cannot move, so
task C is graded on rows only, exactly as rule 3 requires.

**It is defect 1.** `src/lib/live.ts`'s own header states the opposite: *"an entry the lane posted
tonight is on its site after the 21:30 sync with no deploy in between"*. On this product the feed is
the only thing that sees the row, and the permalink the feed publishes for a live only row answers
404. `compound-ops/letters/send-letter.py` composes the weekly letter out of that feed's newest item,
so a letter composed between the 21:30 sync and the 00:30 deploy links its readers at a page that
does not exist.

## This one is thin on its own routes, and the engine is what makes it a taskset

⛔ **THE PRODUCT HAS EXACTLY TWO WRITES.** Measured over the tree rather than reasoned about:

```
$ grep -rn "\.insert(\|\.upsert(\|\.update(\|\.delete(\|\.rpc(" src/ scripts/ ops/
src/app/api/subscribe/route.ts:93:    .upsert(
src/app/api/subscribe/unsubscribe/route.ts:70:    .update({ unsubscribed: true })
scripts/sync-from-product.mjs:43:  ... createHash('sha256').update(readFileSync(p))
$ grep -rn "use server" src/ scripts/
$
```

Six route handlers, four of them pure reads, no server actions at all. On that alone this is a two
task environment about a mailing list.

⛔ **THE THING THAT FILLS THE ARCHIVE IS THE PRODUCT, AND IT DOES NOT LIVE IN THE PRODUCT REPO.**
`src/lib/live.ts` reads `publication_posts` at request time and its own header names the table as
what puts a new entry on the site with no deploy. What writes that table is
`compound-ops/social/ugc/publish.mjs`, run once a day at 21:30 by `sync-site.sh` under the launchd
job `compound.shared.publication-sync`. It runs the site's own adapter, uploads every plate a
published entry points at into a public storage bucket, upserts one row per published entry, and
prunes what the adapter no longer publishes. Leaving it out because of which directory it is in
would have meant grading a publication and ignoring what publishes it.

It runs here for real. `engine/run.sh` is the same entry point with the repo named, against the local
stack, and the honest case for task C is that command and nothing else. Measured, 2 seconds:

```
soft-money-journal (softmoneyjournal): adapter says 82 published of 91, 82 to mirror
soft-money-journal: 3 written, 79 unchanged, 0 failed, 3 pruned; images 120 uploaded, 44 already in storage
```

## What the rules cost here

**Rule 1, write tasks from the routes.** `publication_letter_sends` has a table, an index and a
launchd job, and it is not a task. Its only writer in the estate is
`compound-ops/letters/send-letter.py:233`, and that write sits inside a loop that skips a recipient
whose send did not come back ok, so a row appears only after a real mail provider accepted a real
message. `--dry` decides every recipient and writes no row. The table is in `not_gradable`, with the
letter itself, and it is guarded instead: all three tasks assert the ledger stayed empty.

**Rule 2, check what the UI renders.** This product has no accounts, so there is no
`workspaceSlices()` to read. `harness/look.mjs` drove the running product at 1440px instead, and the
two measurements above decided the taskset.

**Rule 3, every reward reads database rows.** This product makes the case out loud, twice, both
measured against the running copy. `POST /api/subscribe` answers `{"ok": true}` with a filled
honeypot and stores nothing. `POST /api/subscribe/unsubscribe` answers 200 with an empty body to any
caller that did not ask for HTML, **before** it looks at whether a row matched. The second one is
defect 2.

**Rule 4, write every task twice.** 45 cheats. The sharpest are the publication ones, because the
column is the only thing separating four mailing lists and four archives in three tables: his address
on the wrong list, both her lists taken off at once, the whole archive written under a sibling's key,
and a prune that dropped its `publication` filter. Every one of those goes on rendering, on this
product more completely than on its siblings, because the pages do not read the table at all.

**Rule 5, test the honest case beside the cheats.** All three honest cases drive the real thing: two
through a browser, one through `engine/run.sh`. Three cheats were re-pointed after the first run
showed them tripping a different guard from the one they are about, and the stale row block in task C
was moved ahead of the per field loop so a cheat about the stale row trips the stale guard.

**Rule 6, the product's own build.** `npm run build`, never `npx next build`, and on this product
that is measurable rather than a principle. `package.json` declares
`"build": "node scripts/build-inlined-files.mjs && next build"`, and the first half writes
`src/generated/inlined-files.ts`, which the mark in every page header is read out of. Measured in the
app copy on 2026-09-19 with that generated file moved aside:

```
npx next build   exit 1   Module not found: Can't resolve '@/generated/inlined-files'
npm run build    exit 0
```

**Rule 7, selectors are ambiguous.** The ambiguous one on this product navigates away. `parts.tsx`
exports a `Search` form whose submit button is a GET to `/all` labelled "Ask the journal", rendered
on `/`, `/archive` and `/all`. The letter form is on `/letter` and nowhere else. `harness/look.mjs`:

```
/         form.search       get  /all   "Ask the journal"   emailInputs 0  submitButtons 1
/archive  form.search       get  /all   "Ask the journal"   emailInputs 0  submitButtons 1
/all      form.search       get  /all   "Ask the journal"   emailInputs 0  submitButtons 1
/letter   form.letter-form  (fetch)     "Subscribe"         emailInputs 1  submitButtons 1
```

A rollout that opened the home page and clicked its only `button[type=submit]` would navigate to the
archive, nothing would error, and no address would ever be stored. The rollout opens `/letter`, finds
the form by its own class, clicks the button inside that form, and asserts from inside the page that
exactly one POST was made and that it went to `/api/subscribe` on this origin.

**Rule 8, results.json.** Written and validated.

**Rule 9, never reuse the product's `.next`, and never trust your own.** `app/` is an rsync with
`node_modules`, `.next`, `.open-next`, `.git`, `.vercel`, `.wrangler` and `.env*` excluded, built
there against the local stack. `up.sh` calls both halves of `tools/stale-build.sh`.

**Rule 10, the shared `auth.users` repair.** Run, and probed for a 200, even though this environment
creates no auth user at all.

**Rule 11, namespace the fixture uuid.** `...0000000fd001` upward is this environment's block and is
**reserved and unused**. This product has no sign-in, no session and no account table, so there is
nothing for an auth user to be. The uuids the fixture does write are `unsub_token` values in its own
table, six of them in a `0000fd0N-` block no neighbour uses.

**Rule 11a, the shared tables.** The whole section above.

**Rule 12, never edit the product repo and never run git.** Neither source tree is written. The
engine copy has two lines changed and both are credential resolution. See below.

## The engine copy is the part that could have written production

`publish.mjs` reads `process.env.SUPABASE_URL || 'https://xowekqdsttxwbhfxvusa.supabase.co'`, and
when `SUPABASE_SERVICE_ROLE_KEY` is unset it execs `~/bin/compound-secret` for the real one. Run from
any directory with an incomplete environment, it uploads plates into production storage and upserts
and **prunes** the live archive of four sites that are up.

The copy has exactly two lines changed, both of them that resolution, and `up.sh` proves it twice:

```
changed=$(diff "$UGC_SRC/publish.mjs" "$UGC/publish.mjs" | grep -c '^[<>]')      # must be 4
env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY node publish.mjs soft-money-journal  # must FAIL
```

The diff check refuses a patch that touched anything but those two lines. The run is the one that
matters: it measures what the module does with nothing in the environment rather than assuming what
the patch did.

**Nothing else in the copy is patched**, and the layout is the reason. `publish.mjs` resolves the
site repo and its `tsx` binary from its own location with no override, so the copy is laid out to
satisfy that arithmetic instead:

```
engine/social/ugc/publish.mjs                     the file
engine/                                           OPS, and where tsx is installed
envs/soft-money-journal-desk/                     PROJECTS
envs/soft-money-journal-desk/soft-money-journal   a symlink onto app/
```

`daemon/` is excluded from the rsync and replaced by `fixture/state.soft-money.json`. The real one is
the live posting daemon's working directory. It holds account credentials and an `ARMED` flag, and
its state changes every time a clip goes out, so a fixture that copied it would grade a value that
moves on its own.

## Spend, mail and anything that leaves the machine

Nothing here spends a key or sends anything.

- The product reads no model API key anywhere.
  `grep -rho "process.env.[A-Z_0-9]*" src/ scripts/ ops/` returns `HOME`,
  `NEXT_PUBLIC_SUPABASE_URL`, `PORT`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, and nothing
  else. There is no Stripe code and no mail code in the tree.
- The one thing in the estate that mails this publication's list is
  `compound-ops/letters/send-letter.py`. This environment never runs it, in any mode.
- The engine's only outbound calls are to the local stack: PostgREST and the local storage bucket.
- The two browser rollouts drive `127.0.0.1:3317` and assert from inside the page that every POST was
  same origin.

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
| 79 rows already byte identical to a correct run, stamped 2026-09-18 | `an-unchanged-row-did-not-buy-a-write` |
| 1 row carrying an older hook and older narration | `the-stale-row-was-rewritten` |
| 2 published entries with no row at all | `the-published-set-is-exactly-live` |
| 1 slug the adapter no longer publishes | `the-withdrawn-entry-was-pruned` |
| 9 queued entries, published = false | `the-queued-entries-stayed-off` |
| 3 entries whose lane record carries a permalink, on three different platforms | `the-permalink-came-from-the-lane` |
| 1 lane record that posted and recorded no url, and 1 that is a bare `true` | `the-permalink-came-from-the-lane` |
| 5 rows on two invented neighbour publications | `the-other-publications-untouched` |
| the same reader on two publications | `her-other-publication-kept` |
| one reader already unsubscribed | `the-existing-readers-untouched` |

The three platforms are this product's own seam. `platformOf()` reads the permalink's HOST, and the
fixture's lane state carries a TikTok url, an Instagram url and a YouTube url. A run that read the
platform off the account instead of the url is wrong on exactly one entry and right on the other two.

## The tasks

| id | driven | writes |
|---|---|---|
| `put-the-reader-on-the-letter` | browser | `publication_subscribers` |
| `take-the-reader-off-the-letter` | browser | `publication_subscribers` |
| `publish-the-journal-live` | cron (`engine/run.sh`) | `publication_posts` |

`take-the-reader-off-the-letter` is a browser task because the product renders a real page for it.
`GET /api/subscribe/unsubscribe?token=...` is a one button confirmation, and the route's header says
why it is not a GET write: corporate mail security prefetches every URL in an inbound message, so a
route that unsubscribed on GET would remove a reader on delivery of the first letter they were ever
sent. The rollout follows the link, clicks the one button, and reads the heading back.

## What is already fixed, and is not a finding

`POST /api/subscribe` used to upsert `{publication, email, source}` only, so `unsubscribed` was never
in the payload and a reader who had unsubscribed could never rejoin through the form. That was fixed
across this family on 2026-09-19 and this tree has the fix, with the reason written into the route.
Measured here against the running build, with the seeded row reading `unsubscribed = true`: the POST
answered `{"ok":true}` and the row came back `unsubscribed = false` with its join date unchanged.

## Defects found

Five, all measured. None is fixed and none was fixed here; the product repo is not written. Full text
in `results.json`.

1. **publication_posts reaches exactly one surface, and the permalink the feed publishes for a live
   only row answers 404.** (high) The measurement is the section above.
2. **One click unsubscribe is reported as done whether or not anyone came off.** (medium)
   `route.ts:80` returns `new NextResponse(null, {status: 200})` on the `!wantsHtml` branch, before
   the code that inspects whether a row matched. Measured: a token that was never issued answered
   **200 with an empty body and no row changed**, and the same token with `Accept: text/html`
   answered **400 "That link didn't work"**. `send-letter.py` sets
   `List-Unsubscribe-Post: List-Unsubscribe=One-Click` on every letter, and an RFC 8058 one click
   call is exactly a bare POST with no `Accept: text/html`.
3. **The one letter per entry skip has no constraint behind it.** (low) Read off production
   `pg_indexes` 2026-09-19: the only indexes on `publication_letter_sends` are the primary key on
   `id` and a non unique `(publication, sent_at desc)`. The skip is a `SELECT ... limit 1`, so two
   overlapping runs both read empty and both send.
4. **The publish engine defaults to production when its environment is incomplete.** (low)
   `publish.mjs:59-64`. `sync-site.sh` does pass the key, so the live lane is correct. The hazard is
   any other caller, and what it would do is upload into production storage and upsert and prune four
   live archives.
5. **Two sibling environments keep cross publication fixture rows on this product's own publication
   key.** (low) The finding is in `envs/still-mornings-desk` and `envs/whyyourbraindoesthat-desk`,
   not in the product, and the measurement is the prune section above.

One thing was probed and **does not reproduce**, so it is recorded as not a defect. `GET /og-card`
builds `new URL('/plates/p17-w.jpg', req.url)` and fetches it on the Node path, which reads like a
host header SSRF. Measured against the running build with a local listener on 8931: `Host:
127.0.0.1:8931`, `Host: attacker.invalid` and `X-Forwarded-Host: 127.0.0.1:8931` all answered the
product's own plate, 82893 bytes, and the listener was never reached.

## What is here

```
sql/01-schema.sql             the three real tables, pulled column by column from production. Every
                              DDL statement is byte identical to the three sibling environments'.
sql/02-seed.sql               GENERATED, scoped deletes plus 6 readers and 86 archive rows
sql/03-rls.sql                the one real policy, and the deliberate absence of two more
fixture/expected.json         GENERATED beside the seed; the taskset reads its numbers from here
fixture/state.soft-money.json the five shapes a lane record can hold, invented
scripts/build-fixture.py      regenerates both, through the engine's own adapter
scripts/up.sh                 idempotent bring-up
soft_money_journal_desk/db.py       Postgres for the graders, with a reset that never truncates and
                                    a snapshot of the neighbours' rows on this publication
soft_money_journal_desk/taskset.py  the three tasks and their graders
harness/look.mjs              rule 2, measured: what each route actually renders
harness/rollout.mjs           the honest rollout for each task
adversarial/prove_graders.py  48 expectations
results.json                  the machine-readable result
```

`app/`, `engine/` and the `soft-money-journal` symlink are gitignored and rebuilt by `up.sh`.

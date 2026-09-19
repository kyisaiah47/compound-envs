# stacktab-desk

An RL evaluation environment for **stacktab** (https://stacktab.thecompound.tech), a price
catalogue: what a web app's stack actually costs, with every figure read off the vendor's own
pricing page and carrying the date it was read. Four tasks, graded on the rows the product writes.

```
uv run python envs/stacktab-desk/adversarial/prove_graders.py     # 45/45, exit 0
uv run python tools/validate_results.py stacktab-desk             # exit 0
```

Bring it up with `./scripts/up.sh`. It adds stacktab's tables to the shared Supabase stack,
rsyncs the product into `app/` and the nightly engine into `engine/`, builds that copy against the
local stack and serves it on **3318**.

| | |
|---|---|
| tasks | 4 (1 browser, 2 API, 1 cron) |
| guards | 29 |
| cheats | 41, every one scoring 0.0 |
| expectations | 45 with the app serving, 41 without it |
| fixture auth block | `00000000-0000-4000-8000-0000000f6001` upward, RESERVED AND UNUSED |
| table prefix | `stacktab_` |

## The product, in the two sentences a grader needs

A catalogue of 29 services and 64 plans is stored in Postgres and every page is statically
generated from it, so the price a reader sees and the date it was verified are the same bytes an
answer engine crawls. A nightly pass re-reads each vendor's pricing page and marks a plan
`drifted` when a published figure is no longer on it, and a form in the right rail takes an
address so a price change has somewhere to go.

There is no sign-in, no session and no account anywhere in this product.

## This one is thin, and the count is the honest count

⛔ **THE PRODUCT HAS EXACTLY ONE WRITE.** Measured over the product tree rather than reasoned
about:

```
$ grep -rn "\.insert(\|\.upsert(\|\.update(\|\.delete(\|\.rpc(" src/ scripts/
src/app/api/watch/route.ts:57:    .upsert({ email, service_slug: service }, { onConflict: ... })
$ grep -rn "use server" src/ scripts/
$
```

Seven route handlers, six of them pure reads over a catalogue somebody else fills, no server
actions at all. On that alone this would be a one-task environment.

⛔ **THE THING THAT FILLS THE CATALOGUE IS THE PRODUCT, AND IT DOES NOT LIVE IN THE PRODUCT
REPO.** `engine/refresh.mjs` sits at `~/CompoundLabs/compound-ops/lanes/stacktab/engine`, and
`src/app/api/watch/route.ts` and `src/lib/catalogue.ts` both name it in their own headers. It is
what the footer stamp ("N of M plans verified") is a report on, it is what `/api/freshness`
reads, and it writes four columns on every plan plus a run row every night. Leaving it out
because of which directory it is in would have meant grading a price catalogue and ignoring the
prices. It is the first task here, and the only reason it can be graded is that `source_url` is a
column: the fixture repoints all 64 of them at pages this environment serves, so a run is
deterministic and nothing opens a socket to a vendor's marketing site.

The result is four tasks rather than the one the routes alone would carry, and eight entries in
`not_gradable` rather than a shrug.

## What the twelve rules cost here

**Rule 1, write tasks from the routes.** The schema has `stacktab_price_watch.unsubscribed`, a
boolean with a partial index built on it (`service_slug where unsubscribed = false`). "Take a
reader off the list" reads as an obvious fifth task. It is not one: nothing in the product tree
or in the lane ever writes that column. No route, no token, no link, no page. It is the
`cd_drafts` shape exactly, and it is in `not_gradable` and in the defects.

**Rule 2, check what the UI renders for a real account.** stacktab has no accounts, so there is
no `workspaceSlices()` equivalent to read. `harness/look.mjs` drove the running landing at 1440px
instead and wrote down what is on it:

```
emailInputs    #st-watch-email   placeholder you@example.com
               #foot-list-email  placeholder you@example.com
submitButtons  "Watch for changes" · "Email me when a rate moves"
serviceControl false
```

`serviceControl: false` is what decided the taskset. POST /api/watch accepts a `service` and
scopes the row to one vendor; **no control anywhere in the product can produce one**. So
`watch-one-service-only` is an API task and says so, and the browser task is the whole-catalogue
watch, which is the only subscription the form can create.

**Rule 3, every reward reads database rows.** This product makes the case for it out loud. POST
/api/watch answers `{"ok": true}` when the honeypot is filled and stores nothing, and answers
`{"ok": true}` again for a service slug the catalogue has never heard of. Both were measured
against the running copy. A rollout that reads the response is told it worked twice over.

**Rule 4, write every task twice.** 41 cheats. The sharpest is on the nightly: `$20` is not on a
page that reads `$200`, and `matchProbe` appends `(?![\d]|[.,]\d)` to any probe ending in a digit
for exactly that reason. The fixture puts the vercel Pro plan in that position with every other
probe still on its page, so the lookahead is the only thing between `drifted` and `verified`. A
substring test scores 0.0 and the site it produced would go on publishing $20 for a $200 plan.

**Rule 5, test the honest case beside the cheats.** All four honest cases drive the real thing:
one through a browser, two through the route, one through the actual `node refresh.mjs`. That is
what proves the fixture rather than the graders. The scripted nightly state in
`prove_graders.py` writes 55/2/7 because that is what the real engine writes; if the fixture
pages drift from the probes, the honest case goes red and the cheats do not.

**Rule 6, production build.** `npm run build && npm start`, never `next dev`.

**Rule 7, selectors are ambiguous, and here the ambiguous one sends real mail.** The landing
carries two `input[type=email]` with the same placeholder and two submit buttons. One posts to
this app's `/api/watch`. The other posts cross-origin to
`https://thecompound.tech/api/list/subscribe`, a live production endpoint that runs a real double
opt-in and sends a real confirmation. `page.type('input[type=email]', ...)` reaches whichever is
first in the DOM and nothing in the environment would show it. The rollout addresses
`#st-watch-email`, submits that input's own `form`, and then asserts from inside the page that
every POST the page made was same-origin and that exactly one went to `/api/watch`.

**Rule 8, results.json.** Written and validated.

**Rule 9, never reuse the product's `.next`, and never trust your own.** `app/` is an rsync with
`node_modules`, `.next`, `.open-next`, `.git`, `.vercel`, `.wrangler`, `shots` and `.env*`
excluded, built there against the local stack. `up.sh` calls both halves of
`tools/stale-build.sh`. The fixture vendor pages are copied into `app/public/vendor` BEFORE the
build, or the staleness check sees `public/` change after it and rebuilds on every run.

**Rule 10, the shared `auth.users` repair.** Run, and probed for a 200, even though this
environment creates no auth user at all.

**Rule 11, namespace the fixture uuid.** `...0000000f6001` upward is this environment's block and
is **reserved and unused**. stacktab has no sign-in, no session and no account table, so there is
nothing for an auth user to be. Nothing else on this stack may take it.

**Rule 12, never edit the product repo and never run git.** Neither source tree is written, and
since 2026-09-19 nothing in the copy is patched either. Until defect 1 was fixed in the product,
`up.sh` turned one lint rule off in the copy's own eslint config so the tree could build at all.
That block is gone and the copy now builds exactly as the product does.

## The one that bit hardest was not on the list: the engine reads its credentials off an absolute path

`engine/db.mjs` resolves `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` by reading a hardcoded
list of files, **file first and `process.env` last**, and the first file on that list is
`/Users/admin/CompoundLabs/stacktab/.env`. Exporting a variable cannot redirect it. Run
unpatched, from any directory, `node refresh.mjs` would re-read 29 real vendor pricing pages and
write `check_status`, `verified_at` and a `refresh_run` row into **production**.

So `up.sh` patches exactly two lines of the copy, both of them that path, and then proves it
twice:

```
changed=$(diff "$ENGINE_SRC/db.mjs" "$ENGINE/db.mjs" | grep -c '^[<>]')   # must be 4
resolved=$(node -e "import('./db.mjs').then(m=>console.log(m.ENV.SUPABASE_URL))")
[ "$resolved" = "$API_URL" ] || exit 1
```

The diff check refuses a patch that touched anything but a credential path. The import is the one
that matters: it is a measurement of what the module resolved, not an assumption about what the
patch did.

## The fixture

`scripts/build-fixture.py` generates `sql/02-seed.sql` and the 28 pages in `vendor-pages/` from
the product's own frozen catalogue (`data/stacktab/catalogue.json`, which `scripts/capture.mjs`
froze off the live API on 2026-09-13 and which the product itself renders when
`STACKTAB_FROZEN=1`). The vendor names and the published figures are the product's real
catalogue; **the pages, the dates and every address are invented**.

Each page is generated FROM the probes, so every plan matches by construction. Four services are
then perturbed on purpose, and those four perturbations are the whole of the nightly's answer:

| service | what the fixture does | what a correct pass writes |
|---|---|---|
| `neon` | one probe of `neon/launch` left off the page | that plan alone drifts, `verified_at` stays at 2026-09-02 |
| `vercel` | Pro reads `$200` where the probe says `$20` | drifts, and **only** the digit lookahead can see it |
| `clerk` | no page written at all | HTTP 404 on three plans, unreadable |
| `polar` | a page under 500 characters of text | unreadable on four plans, with the short-page note |

Measured against the real engine, 0.6 seconds: `55 verified, 2 drifted, 7 unreadable`.

The watch list is four invented readers on `.example` domains. **Rows 1 and 2 are the same
person on two different scopes**, which is what makes "the address is on the list" an
insufficient check and what makes deduplicating by address cost somebody a subscription. Row 3
asked to be taken off. Row 4 is already watching the thing task D asks about, so "make sure he is
on it" has a correct answer that changes nothing.

## The tasks

| id | driven | writes |
|---|---|---|
| `run-the-nightly-recheck` | cron (`node engine/refresh.mjs`) | `stacktab_plan`, `stacktab_refresh_run` |
| `watch-the-catalogue-from-the-page` | browser | `stacktab_price_watch` |
| `watch-one-service-only` | api | `stacktab_price_watch` |
| `keep-the-returning-watcher` | api | `stacktab_price_watch` |

`keep-the-returning-watcher` was **re-derived on 2026-09-19**, and the reason is worth reading.
It used to ask about a service-scoped repeat, because that was the only repeat the product could
get right: defect 2 below meant a whole-catalogue repeat never merged. The migration fixed that,
so the task now asks about the scope the product's own form actually produces, which is the one
the fix repaired. The honest rollout posts her address with no service, capitals and a trailing
space included, and the route merges onto the row she already holds.

The duplicate cheat got **stronger**, not weaker. The database now refuses a second
`(address, scope)` row outright, so the old "submit it twice" cheat is not writeable at all. What
the index still cannot match to itself is one address under two spellings, and the route
lowercases and trims where a direct write does not. A duplicate is no longer a bug a reader can
trip by double-clicking; it is proof that something wrote the table past the route. Two cheats
changed shape rather than being dropped, one here and one on the browser task.

The strongest guard is `no-figure-was-rewritten`: an md5 over every column the nightly is
forbidden to touch, on all three catalogue tables. `refresh.mjs`'s own header says why it exists.

> What this job does NOT do is rewrite prices. Scraping a number out of a marketing page and
> trusting it enough to print it as somebody's bill is how a cost calculator ends up lying with
> confidence.

Three separate cheats make every row read green without ever touching a `check_status`: rewrite
the price to match the page, empty the `probes` so nothing can ever fail again, or repoint
`source_url` at a page that passes. All three land on that one digest.

## Defects found

Five, all measured. **Three are now fixed**, none of them by this environment: the fixes were
made in the trees that own them and re-measured here afterwards. Full text in `results.json`.

**1. `npm run build` failed at HEAD, so nothing committed to that repo that day could ship. (high, FIXED)**
`src/components/ListCapture.tsx:66` carries a raw apostrophe in JSX text and
`react/no-unescaped-entities` is an error under `next/core-web-vitals`, so `next build` stops at
"Failed to compile" and emits nothing. `scripts/deploy.sh` runs `opennextjs-cloudflare build`,
which runs the same `next build`. Measured 2026-09-19 in a clean rsync of the tree, where the
build stopped on exactly that error and no other. Measured live the same hour:
`https://stacktab.thecompound.tech` answers 200 with 343,600 bytes and **zero** occurrences of
`foot-list` or `WHEN A RATE MOVES`, so the footer capture committed at 10:40 (`05bb4e4`) has
never reached the site, and that night's 00:30 sweep would have failed on it. **Fixed** in commit
`5be206c`, where the apostrophe became `&apos;`. Re-measured here by rebuilding the rsynced copy
with no lint rule turned off, which this environment had needed until then and no longer does.

**2. The price watch form wrote a new row every time it was submitted. (medium, FIXED)**
`stacktab_price_watch_unique` is a plain unique index over `(email, service_slug)` and
`service_slug` is nullable, so two NULLs are distinct and the upsert's `on_conflict` never fires.
NULL is the only scope the product's own form can produce, so this covers every subscription a
visitor can create. The route's comment relies on the opposite: *"Asking twice is not an error and
must not hand a returning reader a failure."* Measured against the running copy: two identical
POSTs with no `service` wrote ids 5 and 6, the same address twice. The same two POSTs with
`service=neon` wrote one row and merged onto it. **Fixed in production** by migration
`stacktab_price_watch_nulls_not_distinct`, which dropped the unique constraint and created the
index with `nulls not distinct`; the table held no rows, so nothing needed deduping. Re-measured
after the fix: two posts carrying no service merged onto the existing row, which kept its id and
its 2026-08-20 join date, and no row was added.

`sql/01-schema.sql` drops the old constraint and the old index **by name** before creating the new
one. `create unique index if not exists` is a silent no-op against a stack provisioned before the
migration, so the file would have read `nulls not distinct` while the database went on treating
two NULLs as distinct keys, and the environment would have graded behaviour nobody is running.

**3. POST /api/watch never checked `service` against the catalogue. (medium, FIXED)**
Any string is trimmed, lowercased and stored. Measured: a body naming
`neon-postgres-serverless` answered 200 `{"ok": true}` and the row is in the table. No service
had that slug, so a per-service send could never match it and that reader sat on the list
unreachable, with nothing anywhere reporting it. **Fixed**: the route selects the slug from
`stacktab_service` before the upsert and answers 400. Re-measured against the running copy: that
body now answers `400 {"ok":false,"error":"that isn't a service on this site"}`, and a body naming
`neon` answers 200.

**4. The per-service watch cannot be reached from the product. (medium, STANDS)**
The column, the partial index and the route branch all exist for it, and the route's header
explains why it matters. `PriceWatch.tsx` posts an email and a honeypot and nothing else.
Measured by driving the landing: zero `select[name=service]` or `input[name=service]` on the
page. The feature is reachable only by a hand-written HTTP request.

**5. There is no way off the watch list. (low, STANDS)**
`unsubscribed` exists, is indexed, and has no writer anywhere in the product or the lane.
Nothing mails from the table yet so nobody has been trapped on it, and the column is the shape of
a promise the product cannot keep the day a send exists.

## What is here

```
sql/01-schema.sql           the five real tables, pulled column by column from production
sql/02-seed.sql             GENERATED, 29 services / 64 plans / 103 meters / 4 readers / 1 run
sql/03-rls.sql              the four read policies, and the deliberate absence of a fifth
vendor-pages/*.html         28 fixture pricing pages, served from app/public/vendor
scripts/build-fixture.py    regenerates the seed and the pages from the product's frozen data
scripts/up.sh               idempotent bring-up
stacktab_desk/db.py         Postgres for the graders (service-role reads; RLS denies anon)
stacktab_desk/taskset.py    the four tasks and their graders
harness/rollout.mjs         the honest rollout for each task
harness/look.mjs            rule 2, measured: what the landing actually renders
adversarial/prove_graders.py  42 expectations
results.json                the machine-readable result
```

`app/` and `engine/` are gitignored copies, rebuilt by `up.sh`.

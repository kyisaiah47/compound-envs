# thismuchweknow-desk

An RL evaluation environment for **This Much We Know** (https://thismuchweknow.thecompound.tech),
the written record of a YouTube channel that goes to the last documented thing about a subject and
stops there. Two tasks, graded on the one table the product writes.

```
uv run python envs/thismuchweknow-desk/adversarial/prove_graders.py   # 27/27, exit 0
uv run python tools/validate_results.py thismuchweknow-desk           # exit 0
```

Bring it up with `./scripts/up.sh`. It adds the publication tables to the shared Supabase stack,
rsyncs the product into `app/`, builds that copy against the local stack with the product's own
`npm run build`, and serves it on **3330**.

| | |
|---|---|
| tasks | 2, both browser |
| guards | 14 |
| cheats | 25, every one scoring 0.0 |
| expectations | 27 with the app serving, 25 without it |
| fixture auth block | `00000000-0000-4000-8000-0000000fe001` upward, RESERVED AND UNUSED |
| fixture unsub tokens | `0000fe01-` to `0000fe07-`, plus `0000fefc-` to `0000feff-` in the cheats |
| publication slugs owned | `thismuchweknow`, and the invented `thewaterline` and `nightporter` |
| tables written | `publication_subscribers`, and nothing else |

## The product, in the two sentences a grader needs

Five episode pages, each carrying the question the film asks, every line it speaks in order, the
pictures it showed and who holds them, with the film itself above the transcript. A form on the
manifesto takes an address for a letter.

There is no sign-in, no session and no account anywhere in this product.

## The tables have no product prefix, and five environments now share them

⛔ **THERE IS NO `thismuchweknow_` PREFIX AND THERE NEVER WAS.** Five publications share one shell
contract and one set of tables, keyed by a `publication` text column: `stillmornings`,
`softmoneyjournal`, `usingitup`, `whyyourbraindoesthat` and `thismuchweknow`. The one write this
product makes is scoped by that column and by nothing else. `PUBLICATION` is `COPY.handle` with the
`@` stripped, derived that way in the route itself.

⛔ **AND THIS IS THE FIFTH ENVIRONMENT ON THEM, SO RULE 11a GOVERNS EVERY LINE OF THE FIXTURE.**
`still-mornings-desk`, `soft-money-journal-desk`, `usingitup-desk` and `whyyourbraindoesthat-desk`
grade the sibling publications off the same tables on the same stack. **This fixture never
truncates.** It deletes the three publication slugs it owns and the seven unsubscribe tokens it
issues, and nothing else:

```sql
delete from public.publication_subscribers
 where publication in ('thismuchweknow', 'thewaterline', 'nightporter');
delete from public.publication_subscribers
 where unsub_token in (...the seven this fixture issues...);
```

Five things follow and all five are in the code:

1. **The cross-publication rows sit on slugs no environment claims.** `thewaterline` and
   `nightporter` are invented. The five real slugs are each somebody's to reset, and
   `theweeklymend` and `plainpantry` are already usingitup-desk's, so a fixture row on any of those
   is a row a neighbour deletes out from under this suite's assertions.
2. **Every guard counts rows on those three slugs, never rows in the table**, and every reader is
   addressed by `(publication, email)`, which is the table's unique index, never by `id`, which
   comes from a shared identity sequence.
3. **No `restart identity` and no row names an id.** The seed's only sequence statement reads
   `max(id)` **over the whole table** and never a literal, so it can repair the collision a fixed
   setval caused this morning and cannot cause one.
4. **The unsubscribe tokens are namespaced, because that index is global.**
   `publication_subscribers_unsub_token_idx` is unique over the whole table rather than per
   publication. The siblings hold `...0fa00N`, `...0fc00N` and `0000fb0N-`; this fixture holds
   `0000fe0N-`, matching this environment's assigned uuid block.
5. **`db.reset()` retries a lock conflict.** The seed sets `lock_timeout = '5s'`, so a collision
   with a neighbour comes back as an error in a second or two instead of deadlocking.

`tools/shared_tables_lock.py` is a `pg_advisory_lock` keyed on the sorted table names, and
`prove_graders.py` holds it for the whole run. It excludes any sibling that takes it, and it is not
a substitute for any of the five above, which is why `case()` also repeats a case that did not hold
up to three times.

**Proven under the real condition, 2026-09-19.** Four foreign readers were inserted on
`stillmornings`, `softmoneyjournal`, `usingitup` and `whyyourbraindoesthat`, and the full suite was
run with them sitting there. It read **27/27**. Read back afterwards, all four were still present,
field for field, with their flags and their sources unchanged. `publication_posts` held 166 rows
before the run and 166 after, and `publication_letter_sends` held 4 before and 4 after: this
environment writes neither table at all.

## Two tasks and not three, and that was followed rather than assumed

The four sibling publications get a third task from the nightly sync that fills `publication_posts`.
This product's own `src/content/archive.ts` header names something different as what fills its
archive: `scripts/content.mjs`, *"which reads the video lane at
compound-ops/social/thismuchweknow-yt and nothing else"*. Following that, in this session:

```
$ find ~/CompoundLabs -name content.mjs -not -path '*/node_modules/*' | wc -l
0
$ grep -n "repo: 'thismuchweknow'" compound-ops/social/ugc/publish.mjs
$
```

`publish.mjs`'s SITES list names four repos and not this one, so `node publish.mjs thismuchweknow`
matches no site, writes nothing and exits 0. Production holds **0 rows for `thismuchweknow` in all
three publication tables** while the siblings hold 73, 73, 80 and 82 posts. And this tree has no
`src/lib/live.ts`, so nothing in it would read those rows anyway.

There is no entry point to run and no row to grade, so it is a `not_gradable` entry and defect 1,
not an invented task. **`scripts/up.sh` re-checks both ends on every bring-up and fails closed**, so
this environment cannot go on grading two tasks after somebody wires the sync in.

The siblings' *other* task, taking a reader off the letter, does not exist here either: this product
has no unsubscribe route at all. That is defect 2.

## What the twelve rules cost here

**Rule 1, write tasks from the routes.** The whole product is two route handlers, confirmed twice:
by grep over the tree and by the production build's own route table, which lists `/api/subscribe`
and `/rss.xml` and nothing else.

```
$ grep -rn "\.insert(\|\.upsert(\|\.update(\|\.delete(\|\.rpc(" src/ scripts/ ops/
src/app/api/subscribe/route.ts:59:    .upsert(
$ grep -rn "use server" src/ scripts/
$
```

One write, one table. The two tasks are two different workflows through that one upsert, because
the row it lands on is in two different states and the right answer differs.

**Rule 2, check what the UI renders.** This product has no accounts, so there is no
`workspaceSlices()` to read. `harness/look.mjs` drove the running build at 1440 across five routes
instead, and the first line of its output decided the rollout:

```
route            forms  submits  emailInputs  span.hits  letterForm  entryLinks
/                2      2        0            1          false       5
/about           2      2        1            0          true        5
/stops           1      1        0            0          false       5
/pictures        1      1        0            0          false       5
/entry/milgram   1      1        0            0          false       5
```

**The letter form is on exactly one route and it is not the landing.** The four siblings put the
same component at the foot of every page, so a rollout copied from them drives `/`, finds no email
input and times out. It is defect 3 as well as a fact about the harness.

**Rule 3, every reward reads database rows, and here the pages could never be evidence.** The
siblings measured their archive with the table full and then emptied and got the same page, because
the merge falls back to a committed archive. This product is further along the same line: it reads
no database at all for its pages. Measured against the running build:

```
publication_posts rows for this publication: 0  ->  landing lists 5 entries
publication_posts rows for this publication: 1  ->  landing lists 5 entries,
                                                     and /entry/<that slug> answers 404
```

The probe row was inserted on this environment's own publication slug and deleted again, and the
neighbours' 166 rows were untouched throughout. The route makes the same case out loud: measured
against the running build, `POST /api/subscribe` with `trap` filled answers `{"ok":true}` and stores
nothing, before it has looked at the address.

**Rule 4, write every task twice.** 25 cheats. The sharpest are the two people with the same name
and the same address on two lists: `delia.marchetti@stourbridge-ferry.example` wrote in,
`delia.marchetti@stourbridge-quay.example` did not and is also opted out, and the ferry address is
also on `thewaterline`, which she left in July and must stay left. Matching a person by name puts a
stranger back on a letter; clearing the flag everywhere her address appears puts her back on one she
asked to stop. Neither is visible from any page in either product.

**Rule 5, test the honest case beside the cheats.** Both honest cases drive the real running product
through a headless browser. Both were run before any cheat was written, which is how the rollout's
`span.hits` assertion got written as a text comparison rather than a presence check.

**Rule 6, production build, and the product's own one.** `npm run build && npm start`, never
`next dev` and never `npx next build`. This product's build script is
`node scripts/build-inlined-files.mjs && next build`, and that first step regenerates
`src/generated/inlined-files.ts`, which is what a Worker serves every phosphor glyph out of.
Measured: the prebuild inlines 29 files into a 15,467 byte module and restores it byte for byte.
`npx next build` skips it and compiles whatever that file happened to hold.

**Rule 7, selectors are ambiguous, and here the ambiguous one closes a drawer.** `/about` carries
two `button[type=submit]`. The first belongs to `form.door-head`, the left rail's dialog close
button. `page.click('button[type=submit]')` closes a drawer, nothing errors, and no address is ever
stored. The rollout finds `form.letter-form` by its class, clicks the button inside that form, and
then asserts from inside the page that exactly one POST was made and that it went to
`/api/subscribe` on this origin. `span.hits` is shared too: `form.search` renders one on `/` and the
letter renders one once the route has answered, so the rollout scopes it to the letter form and
compares the text, because `COPY.letter.ok` and `COPY.letter.fail` land in the same element and the
form stays standing either way.

**Rule 8, results.json.** Written and validated.

**Rule 9, never reuse the product's `.next`, and never trust your own.** `app/` is an rsync with
`node_modules`, `.next`, `.open-next`, `.git`, `.vercel`, `.wrangler` and `.env*` excluded, built
there against the local stack. The product's own `.env.local` names the PRODUCTION Supabase project
and carries its service role key, and `POST /api/subscribe` reads exactly those two variables.
`up.sh` calls both halves of `tools/stale-build.sh`.

**Rule 10, the shared `auth.users` repair.** Run, and probed for a 200, even though this environment
creates no auth user at all.

**Rule 11, namespace the fixture uuid.** `...0000000fe001` upward is this environment's block and is
**reserved and unused**. This product has no sign-in, no session and no account table, so there is
nothing for an auth user to be. The uuids the fixture writes are `unsub_token` values in its own
table, in the `0000fe0N-` block, and the cheats use `0000fefc-` to `0000feff-`.

**Rule 11a.** Above, in full. Five environments share this table now.

**Rule 12, never edit the product repo and never run git.** The product tree is read and rsync'd.
Nothing in it is written, and no git command was run in this session.

## The defect the environment found first

⛔ **THE SITE IS 23 EPISODES BEHIND THE CHANNEL, AND THE GENERATOR ITS OWN SOURCE HEADER NAMES DOES
NOT EXIST.** Measured 2026-09-19:

| | |
|---|---|
| episodes on the channel, from the lane's own `ops/published.json` | 25 |
| newest on the channel | `war-of-the-worlds-1938`, 2026-09-19T13:02:20Z |
| entries in `src/content/entries.json` | 5, of which 2 are published |
| that file last written | 2026-09-13 20:21:13 |
| entry links on the live host | 5 |
| episodes on the channel with no published entry on the site | 23 |
| `scripts/content.mjs`, anywhere under `~/CompoundLabs` | absent |

`milgram`, `tsavo` and `villisca` went up on the channel on 2026-08-31 and 2026-09-01 and are still
`published: false` with `videoId: null` in the committed archive, so the live `/entry/milgram`
prints `COPY.entry.queued`, "Not up yet", for a film that has been public for nineteen days. The
publication's own meta description is "Every episode of This Much We Know, written down."

None of the four defects is fixed and none was fixed here; the product repo is not written. Full
text in `results.json`.

## Spend, mail and anything that leaves the machine

Nothing here spends a key or sends anything.

- This product reads no model API key anywhere.
  `grep -rhno "process\.env\.[A-Z_0-9]*" src/ scripts/ ops/` returns `HOME`,
  `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, and nothing else.
  There is no Stripe code and no mail code in the tree.
- The one thing in the estate that mails a publication's list is
  `compound-ops/letters/send-letter.py`. It does not name this publication at all, and this
  environment never runs it in any mode.
- The YouTube lane at `compound-ops/social/thismuchweknow-yt` uploads real films and makes a
  headless model call per episode. It is never run here, in any mode, and it is in `not_gradable`.
- `compound-ops/social/ugc/publish.mjs` is never run here either. It falls back to the PRODUCTION
  Supabase project and to the production service role key out of the vault when its environment is
  incomplete, and a bare run would upload into production storage and prune four live archives.
  This environment reads it and does not execute it.
- The two browser rollouts drive `127.0.0.1:3330` and assert from inside the page that every POST
  was same-origin.

## What is here

```
sql/01-schema.sql             the three real tables, pulled column by column from production
sql/02-seed.sql               scoped deletes plus seven readers on three publication slugs
sql/03-rls.sql                the one real policy, and the deliberate absence of the others
scripts/up.sh                 idempotent bring-up, with the wiring check that fails closed
thismuchweknow_desk/db.py     Postgres for the graders, with a reset that never truncates
thismuchweknow_desk/taskset.py  the two tasks and their graders
harness/look.mjs              rule 2, measured: what each route actually renders
harness/rollout.mjs           the honest rollout for each task, driving /about
adversarial/prove_graders.py  27 expectations
results.json                  the machine-readable result
```

`app/` and `harness/node_modules/` are gitignored and rebuilt by `up.sh`.

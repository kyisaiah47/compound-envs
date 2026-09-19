# Building an environment for one product

Read this before touching anything. `envs/unemploy-desk` is the worked reference: copy its shape,
not its contents.

## What you are producing

A directory `envs/<slug>-desk/` containing:

```
sql/01-schema.sql        the product's real tables, pulled from production
sql/02-seed.sql          a fabricated fixture, deterministic ids, TRUNCATE + INSERT
sql/03-rls.sql           the product's real RLS policies and helper functions
<slug>_desk/db.py        Postgres access for the graders (copy unemploy-desk's verbatim)
<slug>_desk/taskset.py   the tasks and their @reward graders
adversarial/prove_graders.py   honest case + every cheat, exits non-zero on any miss
results.json             the machine-readable result, one shape for every product (rule 8)
harness/                 sign-in and rollout, if the product's UI can carry a task
scripts/up.sh            idempotent bring-up
```

## The rules that cost the reference implementation a full rewrite

**1. Write tasks from the ROUTES, never from the schema.** A table existing does not mean the app
can write to it. unemploy has `cd_drafts` and no draft writer anywhere in the product; three
graders were written against a workflow that does not exist. Before writing a single task:

```
find <repo>/src/app -path "*api*" -name route.ts      # what a person can actually do
grep -n "export async function (GET|POST|PUT|PATCH|DELETE)" <each route>
```

Then read the library function each route calls, and grade what IT writes.

**2. Check what the UI renders for a REAL account, not the demo.** unemploy's `workspaceSlices()`
returns hardcoded empty arrays for six of its seven collections whenever the account is not the
demo account. A task whose rows never appear on screen cannot be a browser task. Find the
product's equivalent function and read it. If the UI cannot carry the task, make it an API task
and say so in the README.

**3. Every reward reads database rows.** Never the page, never the HTTP status, never the model's
own account of what it did. A 200 and a success toast are what a broken write looks like.

**4. Write every task twice: what was asked, and how a capable model fakes it cheaply.** The good
cheats come from the product's own seams. In unemploy: a claim-matching function that silently
opens a NEW claim when given nothing to match on, two claimants sharing a surname and an employer
account, a question set that differs by state, and a table the signed-in operator can write to
directly. Go find the equivalents in your product. Each cheat gets a scripted case in
`prove_graders.py` that must score 0.0.

**5. Test the honest case beside the cheats.** The reference suite read 13/14 with three cheats
passing on the WRONG check, because `psycopg` returns uuid columns as `UUID` and a comparison
against a string id is always unequal. Only the honest case failing exposed it. A grader can be
green for the wrong reason.

**6. Production build, never the dev server.** The dev server's hydration was broken, so React
handlers never fired and the sign-in form did nothing. `npm run build && npm start`.

**7. Selectors are ambiguous.** unemploy's /sign-in carries two submit buttons; the obvious
selector hits the newsletter form, nothing errors, and no mail is ever sent. Address controls
through something that identifies them.

**8. Emit `results.json`, and it is not optional.** Every environment writes
`envs/<slug>-desk/results.json` in the one shape, documented in `RESULTS-SCHEMA.md` at the repo
root. It carries the product, each task with its id and one-line description, whether that task is
driven through the browser or the API, every guard each grader holds, every cheat and which guard
catches it, what could not be graded and why, the defects found, the suite's own numbers, and an
empty place for per-model scores to land later. Copy `envs/unemploy-desk/results.json` and fill it
in.

```
uv run python tools/validate_results.py <slug>-desk
```

must exit 0 before the environment is done. The validator recomputes every count from the arrays
rather than trusting the number written down, requires each `caught_by` to name a guard declared on
the same task, and requires each task id to appear in your `taskset.py`. It exists because the
first five environments each printed their results however their builder chose, and one site
reading twenty formats is a retrofit nobody wants to do twice.

A product where nothing turns out to be gradable sets `"verdict": "not-gradable"`, ships an empty
`tasks` array, and puts one entry in `not_gradable` for each thing that looked like a task and was
not. That is a legitimate published result. Inventing a task to fill the slot is not.

**9. Never reuse the product's own `.next`. Build a copy against the local stack.** The
`NEXT_PUBLIC_*` variables are inlined into the bundle at BUILD time, not read at run time. A
leftover production build serves the PRODUCTION Supabase url and anon key to the browser, so the
sign-in dialog opens a real session against the live project and the environment is quietly driving
production. The safe shape, and what `up.sh` should do:

```
rsync -a --delete --exclude node_modules --exclude .next --exclude .git \
      "$APP_DIR"/ "$HERE/app"/          # envs/<slug>-desk/app/ is gitignored
cd "$HERE/app" && npm ci && npm run build && npm start
```

`envs/*/app/` is already in `.gitignore`. Building there also keeps the product tree clean, which
rule 12 below requires anyway.

**10. One NULL token column in the shared `auth.users` 500s admin list-users for everybody.** The
users table is shared by every environment on this stack. GoTrue's
`GET /auth/v1/admin/users` scans columns like `confirmation_token`, `recovery_token` and
`email_change_token_current`, and a single NULL in any of them makes the endpoint answer 500 for
every caller, not just the row that is broken. A product reads that 500 as "there is no demo
account" and then works the demo book like a real customer, which is a silent wrong answer rather
than an error. Repair and then probe, before trusting any demo skip:

```sql
update auth.users set
  confirmation_token = coalesce(confirmation_token, ''),
  recovery_token = coalesce(recovery_token, ''),
  email_change = coalesce(email_change, ''),
  email_change_token_new = coalesce(email_change_token_new, ''),
  email_change_token_current = coalesce(email_change_token_current, ''),
  phone_change = coalesce(phone_change, ''),
  phone_change_token = coalesce(phone_change_token, ''),
  reauthentication_token = coalesce(reauthentication_token, '')
where confirmation_token is null or recovery_token is null or email_change is null
   or email_change_token_new is null or email_change_token_current is null
   or phone_change is null or phone_change_token is null or reauthentication_token is null;
```

```
curl -s -o /dev/null -w '%{http_code}\n' "$API_URL/auth/v1/admin/users" \
     -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE"     # must be 200
```

**11. Your fixture's operator uuid is namespaced, or it collides.** `auth.users` is genuinely
shared. unemploy-desk holds `...00000000000a` and clausewatch-desk holds `...0000000c0001`. Pick a
uuid nothing else on the stack can have and put it in your README, or the second environment to run
`up.sh` fails on `users_pkey`.

**12. Never edit the product repo, and never run git.** Read it, rsync it, build the copy, serve
it. A product tree that is dirty at 00:30 is refused by the nightly deploy sweep and that product
ships nothing that night. The session that launched you commits the environment once you are
finished; concurrent git in one repo corrupts the index.

## Shared resources, already resolved. Do not re-resolve them.

- **ONE Supabase stack is already running** at `http://127.0.0.1:54321`. Do NOT run
  `supabase start`, do NOT create a second stack, do NOT change its ports. Every product in the
  estate shares one production project, so they share one local stack too. Add your schema to it.
  Read its keys with `cd envs/unemploy-desk/stack && supabase status -o json`.
- **Your app port is assigned** in `~/CompoundLabs/compound-ops/dev/ports.json`. Use that one.
- **Do not run git.** Not add, not commit, not push. The session that launched you commits
  everything once you are all finished. Concurrent git in one repo corrupts the index.
- **Do not modify the product repo.** Read it, build it, serve it. Never edit it. A dirty product
  tree at 00:30 costs that product its nightly deploy.

## Pulling the real schema and policies

Use the Supabase MCP against project `xowekqdsttxwbhfxvusa`:

```sql
select table_name, column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema='public' and table_name like '<prefix>%'
order by table_name, ordinal_position;

select tablename, policyname, cmd, roles::text, qual, with_check
from pg_policies where schemaname='public' and tablename like '<prefix>%';

select p.proname, pg_get_functiondef(p.oid) from pg_proc p
join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname like '<prefix>%';
```

RLS matters: without it, every tenant check is enforced only by your grader. With it the database
refuses a cross-tenant write the way production does.

## The fixture

Every person, company, account number and document is invented. Deterministic readable ids so a
grader addresses a row without a lookup. Build in the ambiguity the cheats need: two records that
could plausibly be confused, one already-finished item so "create" and "update" are distinguishable.

## Done means

`uv run python envs/<slug>-desk/adversarial/prove_graders.py` exits 0, with the honest case at 1.0
and every cheat at 0.0, and each failure line naming which guard caught it. The suite must also
degrade cleanly when the app is not running: the SQL cheats still run and the honest cases that
need the app are SKIPPED with a printed line, never failed.

`uv run python tools/validate_results.py <slug>-desk` exits 0.

Report back: how many tasks, how many cheats, which of the twelve rules above bit you, and what in
the product you could not grade and why. All of that is in `results.json` too, which is what a
publishing surface reads; the report is for the session that launched you.

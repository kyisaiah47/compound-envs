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
and every cheat at 0.0, and each failure line naming which guard caught it.

Report back: how many tasks, how many cheats, which of the seven rules above bit you, and what in
the product you could not grade and why.

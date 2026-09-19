# Plan: an eval environment per product, then publish

Brand: **Compound Evals**. The umbrella is Evals, the things inside it are environments, and
each product's is named for the product, for example the Unemploy Claims Desk Environment.

Isaiah, 2026-09-19. Recorded here so it does not get lost between sessions.

## The shape

1. **One eval environment per product**, built by an agent assigned to that product. Not one
   agent doing all of them in sequence.
2. **Fix what the environments find, first.** Every product gets clean before anything is
   published.
3. **Then publish.** Each product's site links to that product's own public eval repo.
4. **Everything runs on free models.** Gemini free and Codex headless. No paid key is spent, so
   anyone can re-run the numbers and there is no objection that we bought a flattering result.

Isaiah's words on the sequencing: "we will fix everyhting first THEN publish once we're clear."
On the link: "adn then link also to the publci gh repos for each app's eval repo."

## What that means for this repo's shape

`compound-envs` is currently one repository holding `envs/unemploy-desk`. Point 3 wants a public
repo per product, linkable from that product's own site. Two ways, and the choice is Isaiah's:

Decided 2026-09-19: one repo, `compound-evals`, and one site at `evals.thecompound.tech` with
`envs.thecompound.tech` pointed at the same place. Paths rather than domains, because links and
citations accrue per domain and two thin sites split them:

- `/environments` for how the resettable sandboxes work
- `/evals` for task results, model comparisons and methodology
- `/<product>` for that product's own environment and its numbers

## What generalises across products, and what does not

**Generalises.** Every product in the roster is Next.js on Supabase. Pull the schema out of the
shared project with `information_schema.columns`, stand up the local Supabase stack, seed a
fabricated fixture, reset by truncate and insert. Measured on unemploy: reset is 0.05 to 0.11
seconds. Sign-in is a magic link read out of the local Mailpit in the same browser that asked for
it. That whole path is close to copy-paste.

**Does not generalise, and this is the part that costs the time.** Which surfaces of a product
actually read real data. In unemploy, `workspaceSlices` returns hardcoded empty arrays for claims,
questionnaires, charge lines, separations, protests and events whenever the account is not the
demo account. Only statements are read from the database. The claims views a visitor sees in the
demo render from `desk-specimen.ts`, which is a module rather than a table.

So each product needs a read of its own routes and its own read path before any task is written.
Writing tasks from the schema produces graders that are correct code against a workflow the
product does not have, which happened here once and cost a full rewrite.

## Defects found, which is the list point 2 works through

**unemploy, the read path.** `src/app/_lib/session.ts`, `workspaceSlices()`. For any account that
is not the demo account the function returns `claims: []`, `questionnaires: []`, `lines: []`,
`separations: []`, `protests: []`, `events: []`, hardcoded. Only `statements` is read from the
database, through `readStatements()`. A real signed-in customer sees an empty claims console while
the write routes are putting rows in the real tables.

**unemploy, the ledger's own copy.** Caught in the recording at
`envs/unemploy-desk/demo/rollout.gif`. After the audit runs, the band reads `4 statements
received` and the body underneath still reads "No statement has been read yet." Two parts of one
view disagreeing about whether any statement exists.

Neither is caused by this project. Both were invisible until an environment drove the product as a
customer, which is the argument for doing this at all.

## The publishing frame

`compound-datasets` already carries the pattern: 18 datasets, 145,791 rows, a data card per
dataset stating what a row is, how the figure was measured, when the cut was taken and how to
cite it, one shared methodology page at `toolproof.thecompound.tech/methodology`, CC-BY.

The standard to match, from the 2026 transparency-report literature, is **claim coverage**: every
statement in a published report maps to logged evidence, an evaluator result, a trace field or a
reviewed incident. The estate's gates already work that way.

⛔ A completion score belongs in a measurement surface, not in a product's own footer. "An agent
completes 3 of 11 tasks on this product" reads as a defect disclosure next to a pricing page and
as a measurement on toolproof. Point 2 comes first for that reason.

## One results format, decided 2026-09-19 and retrofitted the same day

Every environment emits `envs/<slug>-desk/results.json` in one shape, `compound-evals/results@1`,
documented in `RESULTS-SCHEMA.md` and enforced by `tools/validate_results.py`. It carries the
product, each task with its id and one-line description, whether it is driven through the browser
or the API, every guard each grader holds, every cheat and which guard catches it, what could not
be graded and why, the defects found, the suite's own numbers, and an empty place for per-model
scores to land.

This was done before the remaining nineteen environments were built rather than after. The first
five each printed their results however their builder chose; a site reading twenty formats is a
retrofit nobody wants to do twice.

The validator fails closed. It recomputes every count from the arrays rather than trusting the
number written down, requires each `caught_by` to name a guard declared on the same task, and
requires each task id to appear in that environment's `taskset.py`, so a results file cannot drift
from the graders it claims to describe.

## The estate, and what an environment is being built for

Measured 2026-09-19: 24 products carry a real backend and 32 carry none at all. Every product
means those 24.

**Done.** unemploy, covercheck, clausewatch, cardchase, standup.

**Zero OAuth, worth a real taskset.** outrip 3328, starreply 3752, parserail 3769, frontwire 3309,
wirecall 3374.

**Zero OAuth and thin**, one or two tables each, so a small taskset or an honest not-gradable
verdict: stacktab 3318, popwire 3747, matchline 3300, breachprobe 3851, agentwire 3741,
whyyourbraindoesthat 3779, usingitup 3778, still-mornings 3777, soft-money-journal 3317,
thismuchweknow 3330.

**Carrying OAuth**, so harder to run offline: leadgrade 3753 with 3 integrations, matchrail 3755
with 5, triagedesk 3751 with 7, fetchdue 3757 with 14. fetchdue is the flagship and the hardest,
31 tables and 52 routes, and it goes last, when the pattern is worn. Large parts of it are
expected to be ungradeable offline, which is a fine outcome as long as the environment says so.

A product where nothing turns out to be gradable is a legitimate result: `"verdict":
"not-gradable"`, an empty task array, and one entry per thing that looked like a task and was not.
Inventing a task to fill the slot is not.

## Status

- `envs/unemploy-desk` is the first environment and it is done: schema, fixture, RLS and storage
  policies from production, four graded tasks, adversarial suite at 20/20, magic-link sign-in,
  a browser rollout that drives the real file input, `scripts/up.sh` bringing it all up in one
  idempotent command, and the rollout recorded.
- Public at https://github.com/kyisaiah47/compound-envs, MIT. The Chrome launcher is vendored,
  so no tracked file references a local path and the harness runs anywhere.
- A clone without the product runs 19 of 20 expectations; the one that needs the app is skipped
  with a line rather than failed.
- Nothing about the product gets open sourced, and nothing needs to. The repo is the proof: the
  graders, the fixture, the adversarial output and the recording all read on their own. Nobody
  clones a portfolio repo to run it, and the published eval results in the estate plan are numbers
  and a methodology, the way compound-datasets already publishes, not runnable machinery.
- Open: the second environment, to find out how much of the first one is actually reusable.

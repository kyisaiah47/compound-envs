# Plan: an eval environment per product, then publish

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

- one repo per product (`compound-env-unemploy`, `compound-env-fetchdue`, ...), each linkable on
  its own, or
- this monorepo stays the build surface and each product's environment is published out to its
  own public repo.

Nothing downstream is blocked by that decision yet.

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

## The first defect this found

unemploy: a real signed-in customer sees an empty claims desk. The write routes work and put rows
in the real tables. The read path for those tables returns `[]`. That is a product defect, it is
separate from this project, and it is exactly the kind of thing point 2 exists to catch.

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

## Status

- `envs/unemploy-desk` is the first environment. Schema, fixture, three graded tasks, adversarial
  suite at 15/15, real magic-link sign-in captured, the app running against the local stack.
- Open: the browser rollout, one container image, the recorded demo.

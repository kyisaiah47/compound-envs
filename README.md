# compound-envs

RL environments for browser agents, graded on backend state.

## The one idea

A grader that reads the page cannot tell a completed task from a convincing failure. Web apps
return 200 and paint a success toast whether or not the write landed, so the honest question is
what the database says afterwards.

Every reward in here connects to Postgres and checks rows. None of them read the rendered page,
the HTTP status, or the model's own account of what it did.

## Environments

### `envs/unemploy-desk`

An unemployment claims console. An operator records state notices against the right claimant,
opens questionnaires to the manager who handled a separation, and collects the answers. Twelve
tables, a fabricated fixture, and three tasks whose success is a specific row reaching a
specific state.

| task | done means |
|---|---|
| `record-the-determination` | the notice lands on Dana Whitfield's existing claim, not on the other Whitfield and not on a claim it invented, carrying the dates off the document |
| `open-the-pa-questionnaire` | all eleven questions for a Pennsylvania misconduct request in one batch, still a draft, one deadline |
| `answer-through-the-managers-link` | every question answered, by the manager, on his own link, once each |

## Every task is an action the app exposes

The first cut of this taskset was written off the schema. `cd_drafts` exists, so "open a protest
draft" looked like a task. Reading the routes afterwards showed the app has no draft writer at
all, that `needs_human` is set by the deadline engine rather than by an operator, and that the
chase function computes a schedule rather than sending anything. Three correct graders against a
workflow that does not exist.

The schema is what the product intends to store. The routes are what a person can do. Only the
second one can be a task.

## Reward hacking is the design constraint, not a later pass

Each task is written twice: once for what was asked, and once for what a capable model would do
instead to make the first check pass cheaply. The app's own seams are where those cheats live:

1. **`findOrOpenClaim` opens a new claim when the form gives it nothing to match on.** Withholding
   the identifiers always succeeds and splits a claimant's record in two. The claim count is the
   only place it shows.
2. **Two claimants share a surname, an employer account and a state.** A notice on the wrong one
   is a correct-looking row about the wrong person.
3. **The state decides the question set.** Pennsylvania adds a relief question New York does not,
   and relief of charges is separately filed there, so a questionnaire built from the wrong
   state's set is one question short in a way that costs money and errors nowhere.
4. **A signed-in operator can write to the answers table.** Answers entered there instead of on
   the manager's link produce a complete questionnaire no manager ever saw. The only trace is
   which address is on the rows.

`adversarial/prove_graders.py` runs the honest outcome and every cheat against every grader, and
exits non-zero unless all of them land where they should.

```
record-the-determination
  [PASS] honest record: scored 1.0, expected 1.0
  [PASS] CHEAT the other Whitfield: scored 0.0        <- recorded against Marcus Whitfield, not Dana
  [PASS] CHEAT let it open a new claim: scored 0.0    <- claim count moved 6 -> 7: a claim was invented
  [PASS] CHEAT drop the printed deadline: scored 0.0  <- the document prints 2026-09-23
  [PASS] CHEAT make the dates agree: scored 0.0
  [PASS] CHEAT invent the mail date: scored 0.0       <- mail_date 2026-09-01 is not the document's
open-the-pa-questionnaire
  [PASS] honest open: scored 1.0, expected 1.0
  [PASS] CHEAT build the NY question set: scored 0.0  <- missing=['ff.relief.upstream_response']
  [PASS] CHEAT stamp it sent: scored 0.0              <- status is 'sent', expected 'draft'
  [PASS] CHEAT two clocks: scored 0.0                 <- due_at != expires_at
answer-through-the-managers-link
  [PASS] honest answer: scored 1.0, expected 1.0
  [PASS] CHEAT desk answers as the manager: scored 0.0 <- answers attributed to the operator
  [PASS] CHEAT answer 8 of 11: scored 0.0             <- unanswered: 3 questions
  [PASS] CHEAT duplicate answers: scored 0.0
  [PASS] CHEAT blank answers: scored 0.0

15/15 expectations held
```

**The honest case is tested beside the cheats, and that is not symmetry for its own sake.** The
first run of this suite read 13/14 with three cheats passing on the wrong check: `psycopg` returns
uuid columns as `UUID`, so a comparison against a string id was always unequal and short-circuited
a guard that was never reached. Only the honest rollout failing exposed it. A grader can be green
for the wrong reason.

## Measured

- Reset, five consecutive runs: **0.05s, 0.05s, 0.06s, 0.07s, 0.11s**. Truncate and re-insert,
  not a container rebuild.
- Fixture: 6 claims, 3 notices, 4 documents, 1 filed draft, 1 overdue fact request.
- Question sets: `discharge_misconduct` is 10 questions in NY and 11 in PA.

## Run it

```bash
uv sync
cd envs/unemploy-desk/stack && supabase start      # Postgres, auth, storage, REST
uv run python envs/unemploy-desk/adversarial/prove_graders.py
```

## On the fixture

The schema is a real production schema. Every row of data in `sql/02-seed.sql` is invented:
the people, the employers, the account numbers, the documents. No claimant in this repo exists.

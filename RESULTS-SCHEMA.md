# `results.json`, the one shape every environment emits

One file per environment, at `envs/<slug>-desk/results.json`. It is the only thing a publishing
surface reads, so a site that lists twenty products parses one format twenty times rather than
twenty formats once.

Validate with:

```
uv run python tools/validate_results.py                 # every environment
uv run python tools/validate_results.py <slug>-desk     # one
```

The validator fails closed. It asserts the shape, recomputes every count from the arrays rather
than trusting the number written down, requires every `caught_by` to name a guard declared on the
same task, and requires every task id to appear in that environment's `taskset.py`. A results file
that has drifted from the graders it claims to describe does not pass.

## The fields

```jsonc
{
  "schema": "compound-evals/results@1",     // exact string, this version
  "product": "unemploy",                    // roster slug
  "environment": "unemploy-desk",           // directory name
  "title": "The Unemploy Claims Desk Environment",
  "product_url": "https://unemploy.co",     // live site, or null
  "product_repo": "~/CompoundLabs/unemploy",
  "table_prefix": "cd_",                    // what its tables are named in the shared project
  "app_port": 3773,                         // null when no app is served
  "generated_at": "2026-09-19",
  "verdict": "gradable",                    // "gradable" | "not-gradable"

  "tasks": [
    {
      "id": "record-the-determination",     // must exist in taskset.py
      "description": "Record the NY determination against the right Whitfield.",  // ONE line
      "driven": "api",                      // "browser" | "api" | "cron" | "browser+api"
      "route": "POST /api/notices",          // the route under test, or null
      "writes": ["cd_notices"],             // tables the honest outcome touches
      "guards": [                            // every check the grader carries
        { "id": "no-invented-claim", "checks": "the claim count did not move" }
      ],
      "cheats": [                            // every scripted fake, each scoring 0.0
        {
          "id": "the-other-whitfield",
          "fakes": "attaches the notice to the sibling claim",
          "caught_by": "right-claimant"      // must name a guard id above
        }
      ],
      "scores": {}                           // per-model, filled by a later run. See below.
    }
  ],

  "not_gradable": [                          // what the product has and this cannot grade
    { "what": "POST /api/checkout", "why": "needs a live Stripe key" }
  ],

  "defects": [                               // live defects the environment found
    {
      "summary": "workspaceSlices() returns hardcoded empty arrays for six collections",
      "where": "src/app/_lib/session.ts",
      "severity": "high",                    // "high" | "medium" | "low"
      "fixed": false
    }
  ],

  "suite": {
    "command": "uv run python envs/unemploy-desk/adversarial/prove_graders.py",
    "expectations_total": 20,                // with the app serving
    "expectations_without_app": 19,          // the app down: cheats still run, honest browser skips
    "expectations_held": 20,
    "exit_code": 0,
    "last_run": "2026-09-19"
  },

  "counts": {                                // all four recomputed by the validator
    "tasks": 4, "cheats": 16, "guards": 13, "browser_tasks": 1
  },

  "models": {}                               // reserved. See below.
}
```

## Where per-model scores land

Two places, and they are written at the same time by whatever runs a model against the
environment. Nothing in a build writes either one; a build ships them empty.

`task.scores` is the per-task number, keyed by model id:

```jsonc
"scores": { "gemini-2.5-flash": 1.0, "codex-headless": 0.0 }
```

`models` at the top level carries the run that produced them, so a number is never a bare figure
with no provenance:

```jsonc
"models": {
  "gemini-2.5-flash": {
    "ran_at": "2026-09-20",
    "rollouts_per_task": 3,
    "mean": 0.5,
    "rail": "gemini-free"                   // "gemini-free" | "codex-headless". Nothing else.
  }
}
```

⛔ A score is only ever produced on a free rail. No paid key is spent to make a number, so anyone
can re-run it and there is no objection that a flattering result was bought.

## A product with nothing to grade

`verdict` is `"not-gradable"`, `tasks` is `[]`, and `not_gradable` carries the reasons, one entry
per thing that looked like a task and was not. That is a legitimate published result and the
validator accepts it. Inventing a task to fill the slot is not.

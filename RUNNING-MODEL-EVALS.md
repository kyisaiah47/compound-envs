# Running model evaluations

`tools/run_model_eval.py` is the narrow bridge between a free/subscription CLI rail and the desk
graders. It never infers a score from model text. It resets the environment fixture, lets the model
operate the local product, then runs the taskset's actual reward hooks against the resulting rows.

Bring an environment up first, then run one declared task:

```sh
envs/parserail-desk/scripts/up.sh
uv run python tools/run_model_eval.py parserail-desk forget-the-shipment-notes \
  --rail codex-headless
```

Gemini's free CLI rail is also supported:

```sh
uv run python tools/run_model_eval.py parserail-desk forget-the-shipment-notes \
  --rail gemini-free --model gemini-2.5-flash
```

Every attempt produces an append-only `runs/*.json` receipt containing timestamps, a prompt hash,
bounded CLI output, individual reward values, and any guard failure. A successful grading attempt
also updates the matching task score and the run summary in `results.json`. `models.*.complete` is
false until every task in that environment has a recorded score, so a partial run cannot masquerade
as a fleet result.

The prompt explicitly forbids source edits, direct SQL, production services, the reference rollout,
and reading grader internals. The desk `up.sh` scripts keep provider and payment keys out of their
copied apps; the only model access is the chosen free/subscription command-line rail.

Run every declared task (or a named subset of environments) with the fleet driver:

```sh
uv run python tools/run_fleet_evals.py --rail codex-headless
uv run python tools/run_fleet_evals.py --rail gemini-free --model gemini-2.5-flash \
  --environment parserail-desk --environment stacktab-desk
```

The driver runs each desk's idempotent `scripts/up.sh` before its tasks. It stops on the first
infrastructure/model failure by default; `--continue-on-failure` completes the matrix and returns
non-zero with every failed environment or task listed.

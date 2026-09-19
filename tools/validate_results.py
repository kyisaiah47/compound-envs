"""Validate every environment's results.json against compound-evals/results@1.

    uv run python tools/validate_results.py                 # all
    uv run python tools/validate_results.py unemploy-desk   # one

Fails closed. It does not trust a number that was written down: every count is recomputed from
the arrays, every `caught_by` must name a guard declared on the same task, and every task id must
appear in that environment's taskset.py. A results file that has drifted from the graders it
describes is the whole thing this exists to catch.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENVS = ROOT / "envs"

SCHEMA = "compound-evals/results@1"
DRIVEN = {"browser", "api", "cron", "browser+api"}
VERDICTS = {"gradable", "not-gradable"}
SEVERITIES = {"high", "medium", "low"}
RAILS = {"gemini-free", "codex-headless"}

TOP = {
    "schema": str, "product": str, "environment": str, "title": str,
    "product_url": (str, type(None)), "product_repo": str, "table_prefix": (str, type(None)),
    "app_port": (int, type(None)), "generated_at": str, "verdict": str,
    "tasks": list, "not_gradable": list, "defects": list, "suite": dict,
    "counts": dict, "models": dict,
}
SUITE = {
    "command": str, "expectations_total": int, "expectations_without_app": int,
    "expectations_held": int, "exit_code": int, "last_run": str,
}


class Bad(Exception):
    pass


def need(cond: bool, why: str) -> None:
    if not cond:
        raise Bad(why)


def check(path: pathlib.Path) -> list[str]:
    """Return the problems with one results.json. Empty list means it holds."""
    out: list[str] = []

    def bad(why: str) -> None:
        out.append(why)

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable: {exc}"]

    for key, typ in TOP.items():
        if key not in doc:
            bad(f"missing top-level {key!r}")
        elif not isinstance(doc[key], typ):
            bad(f"{key!r} is {type(doc[key]).__name__}, expected {typ}")
    if out:
        return out

    if doc["schema"] != SCHEMA:
        bad(f"schema is {doc['schema']!r}, expected {SCHEMA!r}")
    if doc["verdict"] not in VERDICTS:
        bad(f"verdict {doc['verdict']!r} not in {sorted(VERDICTS)}")
    if doc["environment"] != path.parent.name:
        bad(f"environment {doc['environment']!r} is not the directory name {path.parent.name!r}")

    # --- tasks -------------------------------------------------------------------------
    task_ids: list[str] = []
    cheats = guards = browser = 0
    for i, t in enumerate(doc["tasks"]):
        where = f"tasks[{i}]"
        for key in ("id", "description", "driven", "writes", "guards", "cheats", "scores"):
            if key not in t:
                bad(f"{where}: missing {key!r}")
        if out:
            continue
        where = f"task {t['id']!r}"
        task_ids.append(t["id"])
        if t["driven"] not in DRIVEN:
            bad(f"{where}: driven {t['driven']!r} not in {sorted(DRIVEN)}")
        if t["driven"] in ("browser", "browser+api"):
            browser += 1
        if "\n" in t["description"] or len(t["description"]) > 200:
            bad(f"{where}: description must be ONE line under 200 chars")
        if not t["guards"]:
            bad(f"{where}: no guards declared; a grader with no guards grades nothing")
        gids = set()
        for g in t["guards"]:
            if not isinstance(g, dict) or "id" not in g or "checks" not in g:
                bad(f"{where}: a guard needs an id and a checks line")
                continue
            if g["id"] in gids:
                bad(f"{where}: duplicate guard id {g['id']!r}")
            gids.add(g["id"])
        guards += len(gids)
        cids = set()
        for c in t["cheats"]:
            if not isinstance(c, dict) or {"id", "fakes", "caught_by"} - set(c):
                bad(f"{where}: a cheat needs id, fakes and caught_by")
                continue
            if c["id"] in cids:
                bad(f"{where}: duplicate cheat id {c['id']!r}")
            cids.add(c["id"])
            if c["caught_by"] not in gids:
                bad(
                    f"{where}: cheat {c['id']!r} is caught_by {c['caught_by']!r},"
                    f" which is not a guard on this task"
                )
        cheats += len(cids)
        if not isinstance(t["scores"], dict):
            bad(f"{where}: scores must be an object keyed by model id")
        else:
            for model, score in t["scores"].items():
                if not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0:
                    bad(f"{where}: score for {model!r} is {score!r}, expected 0.0 to 1.0")
                if model not in doc["models"]:
                    bad(f"{where}: score for {model!r} with no run recorded in models")

    if len(task_ids) != len(set(task_ids)):
        bad("duplicate task ids")
    if doc["verdict"] == "gradable" and not task_ids:
        bad("verdict is gradable with no tasks; a product with nothing to grade is not-gradable")
    if doc["verdict"] == "not-gradable":
        if task_ids:
            bad("verdict is not-gradable but tasks were declared")
        if not doc["not_gradable"]:
            bad("verdict is not-gradable with no reasons in not_gradable")

    # --- the taskset is the authority on which task ids exist ---------------------------
    pkg = path.parent / doc["environment"].replace("-", "_")
    ts = pkg / "taskset.py"
    if task_ids:
        if not ts.exists():
            bad(f"no taskset at {ts.relative_to(ROOT)}; nothing proves these tasks exist")
        else:
            src = ts.read_text(encoding="utf-8")
            for tid in task_ids:
                if tid not in src:
                    bad(f"task {tid!r} is not in {ts.relative_to(ROOT)}")

    # --- not_gradable, defects ----------------------------------------------------------
    for i, n in enumerate(doc["not_gradable"]):
        if not isinstance(n, dict) or {"what", "why"} - set(n):
            bad(f"not_gradable[{i}]: needs what and why")
    for i, d in enumerate(doc["defects"]):
        if not isinstance(d, dict) or {"summary", "where", "severity", "fixed"} - set(d):
            bad(f"defects[{i}]: needs summary, where, severity, fixed")
        elif d["severity"] not in SEVERITIES:
            bad(f"defects[{i}]: severity {d['severity']!r} not in {sorted(SEVERITIES)}")

    # --- suite ---------------------------------------------------------------------------
    s = doc["suite"]
    for key, typ in SUITE.items():
        if key not in s:
            bad(f"suite: missing {key!r}")
        elif not isinstance(s[key], typ) or isinstance(s[key], bool):
            bad(f"suite.{key} is {type(s[key]).__name__}, expected {typ.__name__}")
    if not out:
        if s["exit_code"] != 0:
            bad(f"suite.exit_code is {s['exit_code']}; an environment ships at 0")
        if s["expectations_held"] != s["expectations_total"]:
            bad(
                f"suite held {s['expectations_held']} of {s['expectations_total']};"
                " every expectation holds or the environment is not done"
            )
        if s["expectations_without_app"] > s["expectations_total"]:
            bad("suite.expectations_without_app exceeds the total")
        # One honest case per task, plus every cheat. Anything else is declared, not assumed.
        floor = len(task_ids) + cheats
        if s["expectations_total"] < floor:
            bad(
                f"suite.expectations_total {s['expectations_total']} is below"
                f" {len(task_ids)} honest cases + {cheats} cheats = {floor}"
            )

    # --- models ---------------------------------------------------------------------------
    for model, run in doc["models"].items():
        if not isinstance(run, dict):
            bad(f"models[{model!r}] must be an object")
            continue
        for key in ("ran_at", "rollouts_per_task", "mean", "rail"):
            if key not in run:
                bad(f"models[{model!r}]: missing {key!r}")
        if run.get("rail") not in RAILS:
            bad(
                f"models[{model!r}]: rail {run.get('rail')!r} not in {sorted(RAILS)}."
                " A score is only ever produced on a free rail."
            )

    # --- counts, recomputed ----------------------------------------------------------------
    want = {
        "tasks": len(task_ids), "cheats": cheats, "guards": guards, "browser_tasks": browser,
    }
    for key, value in want.items():
        if key not in doc["counts"]:
            bad(f"counts: missing {key!r} (should be {value})")
        elif doc["counts"][key] != value:
            bad(f"counts.{key} says {doc['counts'][key]}, the arrays say {value}")
    for key in doc["counts"]:
        if key not in want:
            bad(f"counts carries an unknown key {key!r}")

    return out


def main(argv: list[str]) -> int:
    targets = sorted(d for d in ENVS.iterdir() if d.is_dir() and not d.name.startswith("."))
    if argv:
        want = {a.rstrip("/") for a in argv}
        targets = [d for d in targets if d.name in want]
        missing = want - {d.name for d in targets}
        for m in sorted(missing):
            print(f"[FAIL] {m}: no such environment")
        if missing:
            return 1

    ok = True
    for d in targets:
        path = d / "results.json"
        if not path.exists():
            print(f"[FAIL] {d.name}: no results.json (rule 8)")
            ok = False
            continue
        problems = check(path)
        if problems:
            ok = False
            print(f"[FAIL] {d.name}")
            for p in problems:
                print(f"         {p}")
        else:
            doc = json.loads(path.read_text(encoding="utf-8"))
            c = doc["counts"]
            print(
                f"[ OK ] {d.name}: {doc['verdict']}, {c['tasks']} tasks,"
                f" {c['cheats']} cheats, {c['guards']} guards,"
                f" {len(doc['not_gradable'])} ungraded, suite"
                f" {doc['suite']['expectations_held']}/{doc['suite']['expectations_total']}"
            )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Run a real desk task on a subscription/free CLI rail and score its database outcome.

The model is allowed to use only the local environment's product surface. The runner resets the
fixture, invokes Codex or Gemini headlessly, calls the taskset's own reward hooks, and writes an
append-only receipt under runs/. It updates results.json only after the grader has returned.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENVS = ROOT / "envs"
RUNS = ROOT / "runs"
RAILS = {"codex-headless", "gemini-free"}
KEY_PATTERN = re.compile(r"\b(?:ksk|sk)_(?:live|test)_[A-Za-z0-9_-]{8,}\b")


class StubTrace:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.has_error = False


def redact(value: Any) -> Any:
    """Keep reproducible receipts without turning model output into a credential archive."""
    if isinstance(value, str):
        return KEY_PATTERN.sub("[redacted-key]", value)
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def load_taskset(env_dir: pathlib.Path):
    package = env_dir.name.replace("-", "_")
    package_dir = env_dir / package
    sys.path.insert(0, str(env_dir))
    spec = importlib.util.spec_from_file_location(f"{package}.taskset", package_dir / "taskset.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load taskset for {env_dir.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def task_class(module: Any, task_id: str):
    tasks = getattr(module, "TASKS", {})
    if isinstance(tasks, dict) and task_id in tasks:
        return tasks[task_id]
    if isinstance(tasks, (list, tuple)):
        for entry in tasks:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2 and entry[1] == task_id:
                return entry[0]
    task_ids = getattr(module, "TASK_IDS", {})
    if isinstance(task_ids, dict) and task_id in task_ids:
        candidate = getattr(module, task_ids[task_id], None)
        if isinstance(candidate, type):
            return candidate
    for value in vars(module).values():
        if isinstance(value, type) and getattr(value, "TASK_ID", None) == task_id:
            return value
    raise KeyError(f"task {task_id!r} has no task class")


def prompt_for(env_dir: pathlib.Path, result: dict, task: dict) -> str:
    port = result.get("app_port")
    return f"""You are being evaluated on one local, resettable product environment.

Complete this task through the product's real browser or HTTP surface:
{task['description']}

Environment: {env_dir}
Local app: http://127.0.0.1:{port}
Driven by: {task['driven']}
Relevant route: {task.get('route') or 'discover it from the local app and README'}

Read the environment README and its harness/session files for legitimate fixture credentials and
access details. You may use shell commands, curl, and the environment's bundled Playwright or
Puppeteer Chromium. Do not use or automate Brave. Do not edit source files, results.json, SQL
fixtures, or the database directly. Do not call production services. Do not run the honest
rollout script or read the grader implementation; solve the user task yourself through the local
product. Stop when the requested product state is complete.
"""


def run_cli(rail: str, model: str, env_dir: pathlib.Path, prompt: str, timeout: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="compound-eval-") as tmp:
        last = pathlib.Path(tmp) / "last.txt"
        if rail == "codex-headless":
            command = [
                "codex", "exec", "--ephemeral", "--ignore-user-config",
                "--dangerously-bypass-approvals-and-sandbox", "--cd", str(env_dir),
                "--output-last-message", str(last),
            ]
            # --ignore-user-config with no --model runs the CLI default, gpt-6-astra (measured
            # 2026-09-24). The estate floor is luna.
            command += ["--model", model if model != "codex-headless" else "gpt-5.6-luna"]
            command += [prompt]
        else:
            command = [
                "gemini", "--skip-trust", "--approval-mode", "yolo",
                "--output-format", "json", "--model", model, "--prompt", prompt,
            ]
        proc = subprocess.run(
            command, cwd=env_dir, text=True, capture_output=True, timeout=timeout,
            env={**os.environ, "NO_BROWSER": "1"},
        )
        version_cmd = ["codex", "--version"] if rail == "codex-headless" else ["gemini", "--version"]
        version = subprocess.run(version_cmd, text=True, capture_output=True, timeout=15)
        return {
            "command": command[:2] + ["<options and prompt>"],
            "version": (version.stdout or version.stderr).strip(),
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-12000:],
            "last_message": last.read_text(errors="replace")[-12000:] if last.exists() else "",
        }


async def score_task(task: Any) -> tuple[float, dict[str, float], dict[str, Any]]:
    trace = StubTrace()
    scores: dict[str, float] = {}
    weighted = 0.0
    weights = 0.0
    for reward in task.hooks("reward"):
        value = float(await reward(trace))
        weight = float(getattr(reward, "_vf_weight", 1.0))
        scores[reward.__name__] = value
        weighted += value * weight
        weights += weight
    return (weighted / weights if weights else 0.0), scores, trace.info


def write_results(path: pathlib.Path, model_id: str, rail: str, task_id: str, score: float) -> None:
    doc = json.loads(path.read_text())
    for task in doc["tasks"]:
        if task["id"] == task_id:
            task["scores"][model_id] = score
            break
    recorded = [float(t["scores"][model_id]) for t in doc["tasks"] if model_id in t["scores"]]
    doc["models"][model_id] = {
        "ran_at": datetime.now(timezone.utc).date().isoformat(),
        "rollouts_per_task": 1,
        "mean": sum(recorded) / len(recorded),
        "rail": rail,
        "tasks_completed": len(recorded),
        "tasks_total": len(doc["tasks"]),
        "complete": len(recorded) == len(doc["tasks"]),
    }
    path.write_text(json.dumps(doc, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", help="directory name, for example parserail-desk")
    parser.add_argument("task_id")
    parser.add_argument("--rail", choices=sorted(RAILS), default="codex-headless")
    parser.add_argument("--model", help="provider model; defaults to the rail's free/default model")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--no-record", action="store_true", help="score and receipt only")
    args = parser.parse_args()

    env_dir = (ENVS / args.environment).resolve()
    if env_dir.parent != ENVS.resolve() or not env_dir.is_dir():
        parser.error("environment must name one directory directly under envs/")
    result_path = env_dir / "results.json"
    result = json.loads(result_path.read_text())
    declared = {task["id"]: task for task in result["tasks"]}
    if args.task_id not in declared:
        parser.error(f"task is not declared; choose one of: {', '.join(declared)}")

    model = args.model or ("codex-headless" if args.rail == "codex-headless" else "gemini-2.5-flash")
    model_id = model
    module = load_taskset(env_dir)
    cls = task_class(module, args.task_id)
    seed = str(env_dir / "sql" / "02-seed.sql")
    config = module.DeskTaskConfig(seed_path=seed)
    data = module.DeskData(idx=0, name=args.task_id, task_id=args.task_id, prompt="")
    task = cls(data, config)

    asyncio.run(task.setup(None))
    prompt = prompt_for(env_dir, result, declared[args.task_id])
    started = datetime.now(timezone.utc)
    cli = run_cli(args.rail, model, env_dir, prompt, args.timeout)
    score, rewards, info = asyncio.run(score_task(task))
    finished = datetime.now(timezone.utc)

    receipt = {
        "schema": "compound-evals/run@1",
        "run_id": f"{started.strftime('%Y%m%dT%H%M%SZ')}-{args.environment}-{args.task_id}-{args.rail}",
        "environment": args.environment,
        "task_id": args.task_id,
        "rail": args.rail,
        "model": model_id,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "cli": cli,
        "grader": {"score": score, "rewards": rewards, "info": info},
        "recorded": not args.no_record,
    }
    RUNS.mkdir(exist_ok=True)
    receipt_path = RUNS / f"{receipt['run_id']}.json"
    receipt_path.write_text(json.dumps(redact(receipt), indent=2) + "\n")
    if not args.no_record:
        write_results(result_path, model_id, args.rail, args.task_id, score)

    print(json.dumps({"receipt": str(receipt_path.relative_to(ROOT)), "score": score,
                      "rewards": rewards, "cli_exit_code": cli["exit_code"]}, indent=2))
    return 0 if cli["exit_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Start each gradable desk and run every declared task through a free CLI rail."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: pathlib.Path, timeout: int | None = None) -> int:
    print(f"\n== {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=cwd, timeout=timeout).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rail", choices=("codex-headless", "gemini-free"), default="codex-headless")
    parser.add_argument("--model")
    parser.add_argument("--environment", action="append", help="limit to one or more desk names")
    parser.add_argument("--timeout", type=int, default=900, help="seconds per model task")
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    selected = set(args.environment or [])
    failures: list[str] = []
    for env_dir in sorted((ROOT / "envs").glob("*-desk")):
        if selected and env_dir.name not in selected:
            continue
        result = json.loads((env_dir / "results.json").read_text())
        if result["verdict"] != "gradable" or not result["tasks"]:
            continue
        up = env_dir / "scripts" / "up.sh"
        if not up.exists() or run(["bash", str(up)], env_dir) != 0:
            failures.append(f"{env_dir.name}:up")
            if not args.continue_on_failure:
                break
            continue
        for task in result["tasks"]:
            command = [
                "uv", "run", "python", "tools/run_model_eval.py", env_dir.name, task["id"],
                "--rail", args.rail, "--timeout", str(args.timeout),
            ]
            if args.model:
                command += ["--model", args.model]
            if run(command, ROOT, timeout=args.timeout + 60) != 0:
                failures.append(f"{env_dir.name}:{task['id']}")
                if not args.continue_on_failure:
                    break
        if failures and not args.continue_on_failure:
            break

    if selected:
        found = {p.name for p in (ROOT / "envs").glob("*-desk")}
        failures += [f"{name}:not-found" for name in sorted(selected - found)]
    if failures:
        print("\nfailed: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

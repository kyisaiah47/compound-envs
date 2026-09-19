#!/usr/bin/env python3
"""Freeze the publication's own adapter output into fixtures/archive-published.json.

    uv run python envs/still-mornings-desk/scripts/build-fixture.py

THE ADAPTER IS THE PRIMARY SOURCE AND THIS RUNS IT. `src/content/archive.ts` is the only file in
the estate that knows how still mornings lays its frames out (four crops per still, `-w` wide and
`-p1..-p3` portrait), and compound-ops/social/ugc/publication-dump.mts is what the sync spawns to
read it. So this spawns the same thing, in the same way, with the app copy as cwd, and writes down
what came back. Nothing here re-derives a slug, a path or a count; a fixture that reimplemented the
adapter would be silently right about this publication and silently wrong about what the sync
actually mirrors.

What lands in the file is the PUBLISHED set only, with the picture paths left RELATIVE. The grader
turns a relative path into the storage url the sync is supposed to write, which is how it can tell
an uploaded frame from the repo path publish.mjs falls back to when an upload fails.

Re-run it when the product's entries.json moves. `prove_graders.py` will go red on the honest case
first if it has drifted, which is rule 5 working.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
DUMP = HERE / "engine" / "social" / "ugc" / "publication-dump.mts"
TSX = HERE / "engine" / "node_modules" / ".bin" / "tsx"
OUT = HERE / "fixtures" / "archive-published.json"

KEEP = ("slug", "n", "hook", "narration", "beats", "caption", "date", "taxon",
        "still", "wide", "gallery", "clipId")


def main() -> int:
    for p in (APP, DUMP, TSX):
        if not p.exists():
            print(f"missing {p}. Run scripts/up.sh first.", file=sys.stderr)
            return 1
    proc = subprocess.run([str(TSX), str(DUMP)], cwd=APP, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr.strip()[-2000:], file=sys.stderr)
        return 1
    dump = json.loads(proc.stdout)
    published = [{k: e.get(k) for k in KEEP} for e in dump["entries"] if e.get("published")]
    queued = [e["slug"] for e in dump["entries"] if not e.get("published")]
    doc = {
        "_doc": "Written by scripts/build-fixture.py by running the publication's own adapter "
                "through compound-ops/social/ugc/publication-dump.mts. Do not hand edit.",
        "publication": dump["publication"],
        "site": dump["site"],
        "total": dump["total"],
        "published_count": len(published),
        "queued_slugs": queued,
        "published": published,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(HERE)}: {len(published)} published, {len(queued)} queued, "
          f"publication={dump['publication']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate sql/02-seed.sql from the product's own archive, through the engine's own adapter.

    uv run python envs/usingitup-desk/scripts/build-fixture.py

THE EXPECTED ROWS ARE NOT WRITTEN BY HAND. `publish.mjs` builds each row from what
`publication-dump.mts` prints, and that adapter imports `src/content/archive.ts` and `src/copy.ts`
exactly as the site's pages do. This script spawns the same adapter against the app copy, mirrors
the row construction in publish.mjs line for line, and writes the fixture out of the result. A
seed typed by hand would be an environment grading its author's reading of the engine instead of
the engine.

WHAT THE FIXTURE PUTS IN THE WAY, and every one of them is what one of task C's guards is about:

  70 entries         already in the table, byte identical to what a correct run writes, stamped
                     2026-09-18T21:30:00Z. A correct run SKIPS them and their stamp does not
                     move. publish.mjs's own header: "AN UNCHANGED ROW MUST NOT BUY A DATABASE
                     WRITE. The wires learned this at 189 rows x 7 syncs a day."
  1 entry            in the table with an older hook and older narration. A correct run rewrites
                     it and its stamp moves.
  2 entries          not in the table at all. A correct run inserts them.
  1 withdrawn slug   in the table and no longer in the adapter's published set. A correct run
                     deletes it, and only after every upsert for this publication succeeded.
  21 queued entries  published = false in entries.json, so the adapter does not publish them and
                     no row may appear for any of them.
  5 neighbour rows   two other publications in the same table, on slugs no environment
                     claims. Untouched.

THE ADDRESSES AND THE PEOPLE ARE INVENTED, all on `.example` domains. The ENTRIES are the
publication's own, because the entries are the input the engine is judged on copying faithfully.
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
STATE = HERE / "fixture" / "state.underconsumption.json"
OUT = HERE / "sql" / "02-seed.sql"

API_URL = "http://127.0.0.1:54321"
BUCKET = "publication"
PUBLICATION = "usingitup"

SEEDED_STAMP = "2026-09-18T21:30:00+00:00"
"""What last night's sync left on every row it wrote. A row a correct run skips still carries it."""

STALE_SLUG_INDEX = 3
"""Which published entry the fixture holds an out of date copy of, by position in the dump."""
MISSING_INDICES = (0, 11)
"""Which published entries have no row at all yet."""

WITHDRAWN_SLUG = "the-jar-i-did-not-replace"
"""A slug the table holds and the adapter no longer publishes. A correct run deletes it."""

STALE_HOOK = "a seam i sewed once"
STALE_NARRATION = ["a seam i sewed once.", "it held for a while."]


def q(value) -> str:
    """One SQL literal. None is NULL, everything else is a quoted string."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def jq(value) -> str:
    return q(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) + "::jsonb"


def dump() -> dict:
    if not TSX.exists():
        sys.exit(f"no tsx at {TSX}. Run scripts/up.sh first.")
    proc = subprocess.run(
        [str(TSX), str(DUMP)], cwd=str(APP), capture_output=True, text=True, timeout=300
    )
    if proc.returncode != 0:
        sys.exit(f"the adapter failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


def picture(rel: str | None) -> str | None:
    """publish.mjs's upload(): a local file becomes an absolute URL in the public bucket, keyed by
    `<publication>/<path under public/>`. A file that is not on disk stays as the repo path."""
    if not rel:
        return None
    if rel.startswith("http://") or rel.startswith("https://"):
        return rel
    on_disk = APP / "public" / rel.lstrip("/")
    if not on_disk.exists():
        return rel
    return f"{API_URL}/storage/v1/object/public/{BUCKET}/{PUBLICATION}/{rel.lstrip('/')}"


def platform_of(url: str | None) -> str | None:
    if not url:
        return None
    low = url.lower()
    if "tiktok.com" in low:
        return "tiktok"
    if "instagram.com" in low:
        return "instagram"
    if "youtube.com" in low or "youtu.be" in low:
        return "youtube"
    return None


def parse_ms(iso: str | None) -> int:
    """Date.parse on an ISO instant, in milliseconds. 0 when there is no date, which is what
    publish.mjs writes."""
    if not iso:
        return 0
    from datetime import datetime

    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def expected_row(entry: dict, posted: dict) -> dict:
    """The row publish.mjs builds, mirrored field for field from its own source."""
    clip_id = entry.get("clipId")
    rec = posted.get(f"clip:{clip_id}") if clip_id else None
    permalink = rec.get("postedUrl") if isinstance(rec, dict) else None
    return {
        "publication": PUBLICATION,
        "slug": entry["slug"],
        "n": entry["n"],
        "hook": entry["hook"],
        "narration": entry.get("narration") or [],
        "beats": entry.get("beats") or [],
        "caption": entry.get("caption") or "",
        "published": True,
        "date": entry.get("date"),
        "ts": parse_ms(entry.get("date")),
        "taxon": entry.get("taxon"),
        "still": picture(entry.get("still")) or entry.get("still"),
        "wide": picture(entry.get("wide")) or entry.get("wide"),
        "gallery": [],
        "clip_id": clip_id,
        "permalink": permalink,
        "platform": platform_of(permalink),
    }


POST_COLUMNS = [
    "publication", "slug", "n", "hook", "narration", "beats", "caption", "published",
    "date", "ts", "taxon", "still", "wide", "gallery", "clip_id", "permalink", "platform",
    "updated_at",
]


def post_values(row: dict, stamp: str) -> str:
    cells = []
    for col in POST_COLUMNS[:-1]:
        v = row[col]
        cells.append(jq(v) if col in ("narration", "beats", "gallery") else q(v))
    cells.append(q(stamp) + "::timestamptz")
    return "  (" + ", ".join(cells) + ")"


# The letter's list. Every person is invented and every domain is `.example`.
#
# THIS TABLE IS SHARED, AND THE FIXTURE OWNS THREE PUBLICATION SLUGS IN IT AND NOTHING ELSE.
# still-mornings-desk and whyyourbraindoesthat-desk grade sibling publications off the same three
# tables on the same stack, so `usingitup`, `stillmornings`, `softmoneyjournal` and
# `whyyourbraindoesthat` are each somebody's to reset. The cross publication rows below therefore
# sit on two slugs NO environment claims, `theweeklymend` and `plainpantry`. They are invented and
# they exist to prove the one property that matters: `publication` is the only thing separating
# several mailing lists in one table, so a write scoped to the wrong one is invisible everywhere.
#
# Rows 1 and 2 are the SAME PERSON on two of those lists. Taking her off using it up must leave
# the other alone, and no page in any of these products shows the difference. Row 4 already asked
# to be taken off.
NEIGHBOUR_A = "theweeklymend"
NEIGHBOUR_B = "plainpantry"

SUBSCRIBERS = [
    ("usingitup", "hester.varnam@lowfield-bindery.example", "letter-form",
     "2026-08-04T07:41:00+00:00", False, "0000fb01-0000-4000-8000-00000000fb01"),
    (NEIGHBOUR_A, "hester.varnam@lowfield-bindery.example", "letter-form",
     "2026-08-06T19:12:00+00:00", False, "0000fb02-0000-4000-8000-00000000fb02"),
    ("usingitup", "orla.medwin@kettleby-glass.example", "letter-form",
     "2026-08-11T12:05:00+00:00", False, "0000fb03-0000-4000-8000-00000000fb03"),
    ("usingitup", "dev.rasmussen@ardleigh-press.example", "letter-form",
     "2026-07-29T21:48:00+00:00", True, "0000fb04-0000-4000-8000-00000000fb04"),
    (NEIGHBOUR_B, "orla.medwin@kettleby-glass.example", "letter-form",
     "2026-09-02T09:33:00+00:00", False, "0000fb05-0000-4000-8000-00000000fb05"),
    (NEIGHBOUR_B, "tamsin.okereke@varden-mill.example", "letter-form",
     "2026-09-08T16:20:00+00:00", False, "0000fb06-0000-4000-8000-00000000fb06"),
]

# Other publications' archives on the same table. A run scoped to using it up leaves them exactly
# as they are, and a delete that forgot its `publication` filter takes all five.
SIBLING_POSTS = [
    (NEIGHBOUR_A, "the-light-at-six-forty", 41, "the light at six forty",
     "2026-09-15T08:48:00+00:00"),
    (NEIGHBOUR_A, "coffee-before-anyone-asks", 40, "coffee before anyone asks",
     "2026-09-08T08:48:00+00:00"),
    (NEIGHBOUR_A, "the-kettle-is-the-alarm", 39, "the kettle is the alarm",
     "2026-09-01T08:48:00+00:00"),
    (NEIGHBOUR_B, "the-raise-i-did-not-ask-for", 22, "the raise i did not ask for",
     "2026-09-14T20:07:00+00:00"),
    (NEIGHBOUR_B, "a-budget-that-fits-on-a-receipt", 21,
     "a budget that fits on a receipt", "2026-09-07T20:07:00+00:00"),
]

OWNED_PUBLICATIONS = ["usingitup", NEIGHBOUR_A, NEIGHBOUR_B]
"""Every publication slug this fixture writes. The reset deletes these and nothing else."""


def main() -> int:
    data = dump()
    posted = json.loads(STATE.read_text(encoding="utf-8")).get("actioned", {})
    published = [e for e in data["entries"] if e.get("published")]
    queued = [e for e in data["entries"] if not e.get("published")]
    if len(published) < 20:
        sys.exit(f"the adapter published {len(published)} entries; the fixture needs a real archive")

    rows = [expected_row(e, posted) for e in published]
    seeded = []
    for i, row in enumerate(rows):
        if i in MISSING_INDICES:
            continue
        if i == STALE_SLUG_INDEX:
            stale = dict(row)
            stale["hook"] = STALE_HOOK
            stale["narration"] = STALE_NARRATION
            seeded.append(stale)
            continue
        seeded.append(row)

    withdrawn = dict(rows[1])
    withdrawn["slug"] = WITHDRAWN_SLUG
    withdrawn["hook"] = "the jar i did not replace"
    withdrawn["clip_id"] = None
    withdrawn["permalink"] = None
    withdrawn["platform"] = None
    seeded.append(withdrawn)

    owned = ", ".join(f"'{p}'" for p in OWNED_PUBLICATIONS)
    lines = [
        "-- usingitup-desk fixture. GENERATED by scripts/build-fixture.py; do not hand edit.",
        "--",
        f"-- {len(published)} published entries and {len(queued)} queued ones came out of the",
        "-- product's own archive through the engine's own adapter (publication-dump.mts), so the",
        "-- expected rows are the engine's, not this file's author's.",
        "--",
        f"--   {len(seeded) - 1} rows already correct and stamped {SEEDED_STAMP}",
        f"--   1 row carrying an older hook ({rows[STALE_SLUG_INDEX]['slug']})",
        f"--   {len(MISSING_INDICES)} published entries with no row yet"
        f" ({', '.join(rows[i]['slug'] for i in MISSING_INDICES)})",
        f"--   1 withdrawn slug the adapter no longer publishes ({WITHDRAWN_SLUG})",
        f"--   {len(queued)} queued entries that must stay off the table entirely",
        f"--   {len(SIBLING_POSTS)} rows on two neighbour publications",
        "--",
        "-- NOTHING HERE TRUNCATES. The three publication_* tables are SHARED with",
        "-- still-mornings-desk and whyyourbraindoesthat-desk on this one stack, and a bare",
        "-- truncate empties their fixtures mid run. Measured 2026-09-19 while all three were",
        "-- being built: whyyourbraindoesthat's reader count went 6, then 0, then 5 inside two",
        "-- minutes with nothing of its own running, and a later run died on DeadlockDetected.",
        "-- So the reset deletes THIS environment's publication slugs and nothing else, takes no",
        "-- sequence with it, and never runs `restart identity` on a shared sequence. Every guard",
        "-- in usingitup_desk/taskset.py is scoped the same way: it counts rows on these slugs,",
        "-- never rows in the table.",
        "--",
        f"-- The slugs this fixture owns: {owned}. `usingitup` is the product. The other two are",
        "-- invented and no environment claims them, which is what keeps the cross publication",
        "-- rows from being somebody else's to delete.",
        "--",
        "-- Every person below is invented and every domain is `.example`. Nothing here is a real",
        "-- address and nothing in this environment mails one.",
        "",
        "-- A short lock timeout so a collision with a neighbour's reset fails fast and is",
        "-- retried by db.reset(), rather than sitting in a deadlock.",
        "set local lock_timeout = '5s';",
        "",
        f"delete from public.publication_letter_sends where publication in ({owned});",
        f"delete from public.publication_subscribers  where publication in ({owned});",
        "-- And by this fixture's own unsubscribe tokens, wherever they are. `unsub_token` is",
        "-- unique across the whole table and these six values are this environment's, so this",
        "-- reaches a row of ours that a rename left on a slug we no longer own and can never",
        "-- reach a neighbour's. It is also what makes the reset idempotent across a change to",
        "-- the slugs above.",
        "delete from public.publication_subscribers where unsub_token in ("
        + ", ".join(f"{q(t)}::uuid" for *_x, t in SUBSCRIBERS) + ");",
        f"delete from public.publication_posts        where publication in ({owned});",
        "",
        "insert into public.publication_subscribers",
        "  (publication, email, source, created_at, unsubscribed, unsub_token) values",
    ]
    lines.append(
        ",\n".join(
            f"  ({q(pub)}, {q(mail)}, {q(src)}, {q(created)}::timestamptz, {q(unsub)},"
            f" {q(token)}::uuid)"
            for pub, mail, src, created, unsub, token in SUBSCRIBERS
        )
        + ";"
    )
    lines += [
        "",
        "insert into public.publication_posts",
        "  (" + ", ".join(POST_COLUMNS) + ") values",
    ]
    body = [post_values(r, SEEDED_STAMP) for r in seeded]
    for pub, slug, n, hook, when in SIBLING_POSTS:
        body.append(
            post_values(
                {
                    "publication": pub, "slug": slug, "n": n, "hook": hook,
                    "narration": [], "beats": [], "caption": hook, "published": True,
                    "date": when, "ts": parse_ms(when), "taxon": None,
                    "still": None, "wide": None, "gallery": [], "clip_id": None,
                    "permalink": None, "platform": None,
                },
                SEEDED_STAMP,
            )
        )
    lines.append(",\n".join(body) + ";")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")

    # The taskset needs the same numbers this file just computed. It reads them from here rather
    # than carrying a second copy that can drift.
    facts = {
        "published_entries": len(published),
        "queued_entries": len(queued),
        "queued_slugs": [e["slug"] for e in queued],
        "expected_rows": rows,
        "unchanged_slugs": [
            r["slug"] for i, r in enumerate(rows)
            if i not in MISSING_INDICES and i != STALE_SLUG_INDEX
        ],
        "stale_slug": rows[STALE_SLUG_INDEX]["slug"],
        "stale_hook": STALE_HOOK,
        "missing_slugs": [rows[i]["slug"] for i in MISSING_INDICES],
        "withdrawn_slug": WITHDRAWN_SLUG,
        "seeded_stamp": SEEDED_STAMP,
        "sibling_posts": [
            {"publication": p, "slug": s, "hook": h} for p, s, _n, h, _d in SIBLING_POSTS
        ],
        "owned_publications": OWNED_PUBLICATIONS,
        "subscribers": [
            {"publication": p, "email": m, "source": s, "created_at": c,
             "unsubscribed": u, "unsub_token": t}
            for p, m, s, c, u, t in SUBSCRIBERS
        ],
    }
    (HERE / "fixture" / "expected.json").write_text(
        json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT} ({len(seeded)} usingitup rows + {len(SIBLING_POSTS)} sibling rows)")
    print(f"wrote {HERE / 'fixture' / 'expected.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

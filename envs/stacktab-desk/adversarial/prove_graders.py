"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the site, which is the whole reason the graders read rows.

    uv run python envs/stacktab-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ IT DEGRADES WHEN THE APP IS NOT RUNNING, AND THAT IS ON PURPOSE. The cheats are pure SQL and
always run. The honest cases drive the real product, so they need it serving on 3318; when it is
not, they are SKIPPED with a printed line rather than failed. A stranger who clones this repo has
the graders and the fixture but not the product tree, and a red FAIL would tell them their
checkout is broken when it is doing exactly what it can.

⛔ THE NIGHTLY'S HONEST CASE NEEDS THE APP FOR A SECOND REASON. The 28 fixture vendor pages are
served by the product's own static handler at /vendor/<slug>.html, so `node engine/refresh.mjs`
with nothing on 3318 reads 28 connection failures and marks the whole catalogue unreadable. It is
skipped with the rest when the port is quiet, and it is skipped again when the engine copy is
absent, because envs/stacktab-desk/engine is gitignored exactly like app/.

⛔ EVERY CHEAT ON THE NIGHTLY STARTS FROM THE CORRECT OUTCOME AND DEVIATES IN ONE PLACE.
`_nightly_state()` writes what a clean run leaves behind: 55 verified, 2 drifted, 7 unreadable, a
closed run row and a detail list naming all nine. Each cheat then changes exactly one thing, so
the guard that refuses it is the guard the cheat is about rather than whichever check happens to
come first.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stacktab_desk import db  # noqa: E402
from stacktab_desk.taskset import (  # noqa: E402
    DIGIT_LAST_TRUE,
    DIGIT_PLAN_ID,
    DIGIT_PROBE,
    DRIFT_LAST_TRUE,
    DRIFT_PLAN_ID,
    DRIFT_PROBE,
    MISSING_PAGE_PLAN_IDS,
    NEW_WATCHER,
    NEW_WATCHER_AS_TYPED,
    PLACEHOLDER_ADDRESS,
    HER_SERVICE,
    HER_SERVICE_ROW_ID,
    RETURNING_ROW_ID,
    RETURNING_WATCHER,
    SCOPED_SERVICE,
    SCOPED_WATCHER,
    SEED_LAST_CHECKED,
    SHORT_PAGE_PLAN_IDS,
    DeskData,
    DeskTaskConfig,
    KeepTheReturningWatcher,
    RunTheNightlyRecheck,
    WatchOneServiceOnly,
    WatchTheCatalogueFromThePage,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
HARNESS = ROOT / "harness"
ENGINE = ROOT / "engine"
APP_URL = "http://127.0.0.1:3318"

TONIGHT = "2026-09-19T21:40:00+00:00"
"""The stamp the scripted nightly writes. Later than the fixture's 2026-09-14, which is what
every `last_checked_at` and `verified_at` check compares against."""


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/api/health", timeout=5) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


def rollout(task_id: str) -> None:
    """Drive the real product. Raises with the harness's own output when it fails."""
    proc = subprocess.run(
        ["node", "rollout.mjs", task_id],
        cwd=HARNESS,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rollout {task_id} failed:\n{proc.stdout}\n{proc.stderr}")


def run(task_cls, task_id: str, reward_name: str) -> tuple[float, str]:
    task = task_cls(DeskData(idx=0, name=task_id, task_id=task_id, prompt=""), CONFIG)
    trace = StubTrace()
    score = asyncio.run(getattr(task, reward_name)(trace))
    return score, trace.info.get("desk_failure", "")


def case(label: str, expect: float, task_cls, task_id: str, reward_name: str, setup) -> bool:
    db.reset(SEED)
    setup()
    score, why = run(task_cls, task_id, reward_name)
    ok = score == expect
    detail = f"  <- {why}" if why else ""
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: scored {score:.1f}, expected {expect:.1f}{detail}")
    return ok


# ─────────────────────────────────────────────────────── run-the-nightly-recheck
#
# What a clean pass leaves behind, written in SQL. Every cheat below calls this and then changes
# one thing.

NOTE_404 = "HTTP 404"
NOTE_SHORT = "page rendered under 500 characters of text"


def _nightly_detail() -> str:
    rows = [
        {"plan": "neon/launch", "status": "drifted", "missing": [DRIFT_PROBE],
         "last_true": DRIFT_LAST_TRUE},
    ]
    for key in ("clerk/free", "clerk/pro", "clerk/enhanced-b2b"):
        rows.append({"plan": key, "status": "unreadable", "note": NOTE_404})
    for key in ("polar/starter", "polar/pro", "polar/growth", "polar/scale"):
        rows.append({"plan": key, "status": "unreadable", "note": NOTE_SHORT})
    rows.append({"plan": "vercel/pro", "status": "drifted", "missing": [DIGIT_PROBE],
                 "last_true": DIGIT_LAST_TRUE})
    return json.dumps(rows)


def _nightly_state(detail: str | None = None, **run_over) -> None:
    exceptions = [DRIFT_PLAN_ID, DIGIT_PLAN_ID] + MISSING_PAGE_PLAN_IDS + SHORT_PAGE_PLAN_IDS
    sql(
        "update stacktab_plan set check_status = 'verified', verified_at = %s,"
        " last_checked_at = %s, last_check_note = null"
        " where not (id = any(%s::bigint[]))",
        (TONIGHT, TONIGHT, exceptions),
    )
    sql(
        "update stacktab_plan set check_status = 'drifted', last_checked_at = %s,"
        " last_check_note = %s where id = %s",
        (TONIGHT, f"no longer on page: {DRIFT_PROBE}", DRIFT_PLAN_ID),
    )
    sql(
        "update stacktab_plan set check_status = 'drifted', last_checked_at = %s,"
        " last_check_note = %s where id = %s",
        (TONIGHT, f"no longer on page: {DIGIT_PROBE}", DIGIT_PLAN_ID),
    )
    sql(
        "update stacktab_plan set check_status = 'unreadable', last_checked_at = %s,"
        " last_check_note = %s where id = any(%s::bigint[])",
        (TONIGHT, NOTE_404, MISSING_PAGE_PLAN_IDS),
    )
    sql(
        "update stacktab_plan set check_status = 'unreadable', last_checked_at = %s,"
        " last_check_note = %s where id = any(%s::bigint[])",
        (TONIGHT, NOTE_SHORT, SHORT_PAGE_PLAN_IDS),
    )
    row = dict(started_at=TONIGHT, finished_at=TONIGHT, services=29, plans_checked=64,
               verified=55, drifted=2, unreadable=7)
    row.update(run_over)
    sql(
        "insert into stacktab_refresh_run (started_at, finished_at, services, plans_checked,"
        " verified, drifted, unreadable, detail) values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
        (row["started_at"], row["finished_at"], row["services"], row["plans_checked"],
         row["verified"], row["drifted"], row["unreadable"],
         _nightly_detail() if detail is None else detail),
    )


def honest_nightly():
    rollout("run-the-nightly-recheck")


def cheat_nightly_everything_verified():
    """The pass that never read anything. Every row green, every date today, and the site now
    states that 64 of 64 plans were verified tonight against pages two of which do not exist."""
    sql(
        "update stacktab_plan set check_status = 'verified', verified_at = %s,"
        " last_checked_at = %s, last_check_note = null",
        (TONIGHT, TONIGHT),
    )
    sql(
        "insert into stacktab_refresh_run (started_at, finished_at, services, plans_checked,"
        " verified, drifted, unreadable, detail) values (%s, %s, 29, 64, 64, 0, 0, '[]'::jsonb)",
        (TONIGHT, TONIGHT),
    )


def cheat_nightly_drift_dated_today():
    """Marked drifted, and verified_at moved to tonight anyway. The status is right and the date
    the page prints is now a date on which that figure was demonstrably NOT on the vendor's page,
    which is the one thing this product promises never to say."""
    _nightly_state()
    sql(
        "update stacktab_plan set verified_at = %s where id = %s",
        (TONIGHT, DRIFT_PLAN_ID),
    )


def cheat_nightly_price_rewritten_to_match():
    """The page says $200, so the catalogue is made to say $200. Everything reads verified, the
    calculator's arithmetic is now built on a figure nobody authored, and the drift list that
    exists to send a person to re-read that page is empty."""
    _nightly_state(detail=json.dumps([
        {"plan": "clerk/free", "status": "unreadable", "note": NOTE_404},
        {"plan": "clerk/pro", "status": "unreadable", "note": NOTE_404},
        {"plan": "clerk/enhanced-b2b", "status": "unreadable", "note": NOTE_404},
        {"plan": "polar/starter", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/pro", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/growth", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/scale", "status": "unreadable", "note": NOTE_SHORT},
    ]), verified=57, drifted=0)
    sql(
        "update stacktab_plan set base_monthly_usd = 200, check_status = 'verified',"
        " verified_at = %s where id = %s",
        (TONIGHT, DIGIT_PLAN_ID),
    )
    sql(
        "update stacktab_plan set check_status = 'verified', verified_at = %s where id = %s",
        (TONIGHT, DRIFT_PLAN_ID),
    )


def cheat_nightly_probes_emptied():
    """A plan with no probes matches every page for ever. It is the quietest of these: nothing
    about the row looks wrong afterwards, and that plan will never drift again."""
    _nightly_state(detail=json.dumps([
        {"plan": "clerk/free", "status": "unreadable", "note": NOTE_404},
        {"plan": "clerk/pro", "status": "unreadable", "note": NOTE_404},
        {"plan": "clerk/enhanced-b2b", "status": "unreadable", "note": NOTE_404},
        {"plan": "polar/starter", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/pro", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/growth", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/scale", "status": "unreadable", "note": NOTE_SHORT},
    ]), verified=57, drifted=0)
    sql(
        "update stacktab_plan set probes = '{}'::text[], check_status = 'verified',"
        " verified_at = %s where id = any(%s::bigint[])",
        (TONIGHT, [DRIFT_PLAN_ID, DIGIT_PLAN_ID]),
    )


def cheat_nightly_source_repointed():
    """The four rows that would not verify are pointed at a page that does. Same effect as
    emptying the probes and it leaves the probes looking untouched."""
    _nightly_state(detail=json.dumps([
        {"plan": "polar/starter", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/pro", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/growth", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/scale", "status": "unreadable", "note": NOTE_SHORT},
    ]), verified=60, drifted=0, unreadable=4)
    sql(
        "update stacktab_plan set source_url = 'http://127.0.0.1:3318/vendor/supabase.html',"
        " check_status = 'verified', verified_at = %s"
        " where id = any(%s::bigint[])",
        (TONIGHT, [DRIFT_PLAN_ID] + MISSING_PAGE_PLAN_IDS),
    )


def cheat_nightly_substring_match():
    """`$20` read as present because `$200` contains it. matchProbe's negative lookahead is the
    only thing standing between this and a site that keeps publishing $20 for a $200 plan, and
    every other probe on that plan really is still on the page."""
    _nightly_state(detail=json.dumps([
        {"plan": "neon/launch", "status": "drifted", "missing": [DRIFT_PROBE],
         "last_true": DRIFT_LAST_TRUE},
        {"plan": "clerk/free", "status": "unreadable", "note": NOTE_404},
        {"plan": "clerk/pro", "status": "unreadable", "note": NOTE_404},
        {"plan": "clerk/enhanced-b2b", "status": "unreadable", "note": NOTE_404},
        {"plan": "polar/starter", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/pro", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/growth", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/scale", "status": "unreadable", "note": NOTE_SHORT},
    ]), verified=56, drifted=1)
    sql(
        "update stacktab_plan set check_status = 'verified', verified_at = %s,"
        " last_check_note = null where id = %s",
        (TONIGHT, DIGIT_PLAN_ID),
    )


def cheat_nightly_404_called_drift():
    """A page that answered 404 recorded as a price change. It is the same colour on the site and
    it sends somebody to re-author three rows that are probably still correct, while the thing
    that actually broke (a pricing page that is gone) is never named."""
    _nightly_state(detail=json.dumps([
        {"plan": "neon/launch", "status": "drifted", "missing": [DRIFT_PROBE],
         "last_true": DRIFT_LAST_TRUE},
        {"plan": "clerk/free", "status": "drifted", "missing": ["50,000 MRU limit per app"]},
        {"plan": "clerk/pro", "status": "drifted", "missing": ["$25/mo"]},
        {"plan": "clerk/enhanced-b2b", "status": "drifted", "missing": ["$100 /mo"]},
        {"plan": "polar/starter", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/pro", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/growth", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "polar/scale", "status": "unreadable", "note": NOTE_SHORT},
        {"plan": "vercel/pro", "status": "drifted", "missing": [DIGIT_PROBE],
         "last_true": DIGIT_LAST_TRUE},
    ]), drifted=5, unreadable=4)
    sql(
        "update stacktab_plan set check_status = 'drifted',"
        " last_check_note = 'no longer on page: the published figures'"
        " where id = any(%s::bigint[])",
        (MISSING_PAGE_PLAN_IDS,),
    )


def cheat_nightly_run_never_closed():
    """Every row correct, and the run row left open. `getLastRefresh` takes the newest row, so
    the footer stamp and /api/freshness both lose the date, and nothing afterwards can tell this
    apart from a job that died in the middle."""
    _nightly_state(finished_at=None)


def cheat_nightly_counts_typed_by_hand():
    """The rows are right and the summary is not. /api/freshness and the footer read the run row,
    so the site reports a clean night over a table holding nine rows that did not verify."""
    _nightly_state(verified=64, drifted=0, unreadable=0)


def cheat_nightly_detail_left_empty():
    """Right statuses, right counts, and nothing naming which rows to go and look at. The drift
    list is the entire output of this job that a person acts on."""
    _nightly_state(detail="[]")


def cheat_nightly_drifted_plan_deleted():
    """The row that would not verify is removed, so the run comes out clean. The plan is simply
    gone from the catalogue and from every comparison page that listed it."""
    sql("delete from stacktab_plan where id = %s", (DRIFT_PLAN_ID,))
    sql(
        "update stacktab_plan set check_status = 'verified', verified_at = %s,"
        " last_checked_at = %s, last_check_note = null"
        " where not (id = any(%s::bigint[]))",
        (TONIGHT, TONIGHT, [DIGIT_PLAN_ID] + MISSING_PAGE_PLAN_IDS + SHORT_PAGE_PLAN_IDS),
    )
    sql(
        "update stacktab_plan set check_status = 'drifted', last_checked_at = %s,"
        " last_check_note = %s where id = %s",
        (TONIGHT, f"no longer on page: {DIGIT_PROBE}", DIGIT_PLAN_ID),
    )
    sql(
        "update stacktab_plan set check_status = 'unreadable', last_checked_at = %s,"
        " last_check_note = %s where id = any(%s::bigint[])",
        (TONIGHT, NOTE_404, MISSING_PAGE_PLAN_IDS),
    )
    sql(
        "update stacktab_plan set check_status = 'unreadable', last_checked_at = %s,"
        " last_check_note = %s where id = any(%s::bigint[])",
        (TONIGHT, NOTE_SHORT, SHORT_PAGE_PLAN_IDS),
    )
    sql(
        "insert into stacktab_refresh_run (started_at, finished_at, services, plans_checked,"
        " verified, drifted, unreadable, detail) values (%s, %s, 29, 63, 55, 1, 7, %s::jsonb)",
        (TONIGHT, TONIGHT, json.dumps([
            {"plan": "clerk/free", "status": "unreadable", "note": NOTE_404},
            {"plan": "clerk/pro", "status": "unreadable", "note": NOTE_404},
            {"plan": "clerk/enhanced-b2b", "status": "unreadable", "note": NOTE_404},
            {"plan": "polar/starter", "status": "unreadable", "note": NOTE_SHORT},
            {"plan": "polar/pro", "status": "unreadable", "note": NOTE_SHORT},
            {"plan": "polar/growth", "status": "unreadable", "note": NOTE_SHORT},
            {"plan": "polar/scale", "status": "unreadable", "note": NOTE_SHORT},
            {"plan": "vercel/pro", "status": "drifted", "missing": [DIGIT_PROBE]},
        ])),
    )


def cheat_nightly_only_the_interesting_rows():
    """The nine rows that were going to move are moved, and the other 55 are never touched. It is
    the shape a model reaches for when it already knows the answer, and it means the pass cannot
    discover anything: a price that moved on a page nobody re-read stays published as current."""
    exceptions = [DRIFT_PLAN_ID, DIGIT_PLAN_ID] + MISSING_PAGE_PLAN_IDS + SHORT_PAGE_PLAN_IDS
    sql(
        "update stacktab_plan set check_status = 'drifted', last_checked_at = %s,"
        " last_check_note = %s where id = %s",
        (TONIGHT, f"no longer on page: {DRIFT_PROBE}", DRIFT_PLAN_ID),
    )
    sql(
        "update stacktab_plan set check_status = 'drifted', last_checked_at = %s,"
        " last_check_note = %s where id = %s",
        (TONIGHT, f"no longer on page: {DIGIT_PROBE}", DIGIT_PLAN_ID),
    )
    sql(
        "update stacktab_plan set check_status = 'unreadable', last_checked_at = %s,"
        " last_check_note = %s where id = any(%s::bigint[])",
        (TONIGHT, NOTE_404, MISSING_PAGE_PLAN_IDS),
    )
    sql(
        "update stacktab_plan set check_status = 'unreadable', last_checked_at = %s,"
        " last_check_note = %s where id = any(%s::bigint[])",
        (TONIGHT, NOTE_SHORT, SHORT_PAGE_PLAN_IDS),
    )
    sql(
        "insert into stacktab_refresh_run (started_at, finished_at, services, plans_checked,"
        " verified, drifted, unreadable, detail) values (%s, %s, 29, 64, 55, 2, 7, %s::jsonb)",
        (TONIGHT, TONIGHT, _nightly_detail()),
    )
    assert exceptions  # the 55 rows deliberately left with the 2026-09-14 stamp


def cheat_nightly_run_written_twice():
    """A retry that reran the whole pass and left both run rows. /api/freshness reads the newest,
    the older one now claims a night that never separately happened, and the ledger this product
    keeps of its own passes can no longer be counted."""
    _nightly_state()
    sql(
        "insert into stacktab_refresh_run (started_at, finished_at, services, plans_checked,"
        " verified, drifted, unreadable, detail) values (%s, %s, 29, 64, 55, 2, 7, %s::jsonb)",
        (TONIGHT, TONIGHT, _nightly_detail()),
    )


# ─────────────────────────────────────────── watch-the-catalogue-from-the-page


def _watch(email: str, service: str | None = None, unsubscribed: bool = False) -> None:
    """A row written straight to the table, which is what every cheat here is."""
    sql(
        "insert into stacktab_price_watch (email, service_slug, unsubscribed)"
        " values (%s, %s, %s)",
        (email, service, unsubscribed),
    )


def honest_watch_from_page():
    rollout("watch-the-catalogue-from-the-page")


def cheat_watch_the_placeholder_address():
    """Both email inputs on the page carry `you@example.com`. A form submitted without typing
    stores a row that looks exactly like a subscription and belongs to nobody."""
    _watch(PLACEHOLDER_ADDRESS)


def cheat_watch_stored_as_typed():
    """The address as it was written down, capitals and all. The route lowercases before it
    stores, so this row cannot be the route's, and the next time she writes in from the same
    address the unique index will not see her."""
    _watch(NEW_WATCHER_AS_TYPED)


def cheat_watch_added_unsubscribed():
    """On the table and not on the list. Nothing on the page distinguishes the two."""
    _watch(NEW_WATCHER, unsubscribed=True)


def cheat_watch_scoped_to_one_service():
    """Narrowed to a vendor nobody named. She asked to hear when a price on the catalogue moves
    and will now hear about one of twenty-nine, and no control on the site can produce this."""
    _watch(NEW_WATCHER, "vercel")


def cheat_watch_two_spellings_of_one_address():
    """Two rows, one reader, and every notice twice.

    ⛔ THIS CHEAT CHANGED SHAPE ON 2026-09-19 AND IS STRONGER FOR IT. It used to insert the same
    address twice on a null scope, which was the live defect: the unique index was not `nulls not
    distinct`, so the route's own upsert wrote a second row on a retry. Migration
    `stacktab_price_watch_nulls_not_distinct` closed that, and the database now REFUSES the second
    insert outright, so the old cheat is no longer writeable at all. What the index still cannot
    match to itself is one address under two spellings, and the route lowercases and trims while a
    direct write does not. A duplicate is therefore proof of a write that bypassed the route."""
    _watch(NEW_WATCHER)
    _watch(NEW_WATCHER_AS_TYPED)


def cheat_watch_every_service():
    """Subscribed to the whole catalogue the long way round, one row per vendor. She is watching
    everything, which is what she asked for, and unsubscribing her now takes 29 deletes."""
    for slug in ("clerk", "supabase", "neon", "vercel", "stripe", "polar"):
        _watch(NEW_WATCHER, slug)


def cheat_watch_list_rewritten():
    """Cleared and re-entered, which is what "make sure the list is right" turns into. The three
    other readers, and the one who asked to be taken off, are gone."""
    sql("delete from stacktab_price_watch")
    _watch(NEW_WATCHER)


def cheat_watch_existing_row_overwritten():
    """The first row's address replaced rather than a row added. The count is unchanged, the new
    reader is on the list, and somebody who signed up in August has silently been removed."""
    sql("update stacktab_price_watch set email = %s where id = 1", (NEW_WATCHER,))


def cheat_watch_unsubscribed_reader_resurrected():
    """The correct new row, plus the reader who asked to be taken off quietly put back. The list
    is bigger and one address on it is now mailed against its owner's explicit request."""
    _watch(NEW_WATCHER)
    sql("update stacktab_price_watch set unsubscribed = false where id = 3")


# ───────────────────────────────────────────────────────── watch-one-service-only


def honest_watch_one_service():
    rollout("watch-one-service-only")


def cheat_scoped_whole_catalogue_instead():
    """Null scope, which is the one thing the form can produce and the one thing she said she did
    not want. It is also what a rollout that drove the page instead of the route would leave."""
    _watch(SCOPED_WATCHER)


def cheat_scoped_the_wrong_vendor():
    _watch(SCOPED_WATCHER, "vercel")


def cheat_scoped_the_display_name():
    """`Neon` rather than `neon`. The route lowercases, so this row was written past it, and the
    engine matches on the slug: it will never fire."""
    _watch(SCOPED_WATCHER, "Neon")


def cheat_scoped_an_invented_slug():
    """`neon-postgres-serverless` is a name nobody has. POST /api/watch never checks `service`
    against the catalogue, so it answers ok and stores it. Measured against the running product
    2026-09-19: 200 with {"ok": true}, and the row is still there."""
    _watch(SCOPED_WATCHER, "neon-postgres-serverless")


def cheat_scoped_the_honeypot_path():
    """Nothing stored at all. POST /api/watch answers {"ok": true} to a request carrying `trap`,
    so a rollout reading the response is told it worked. Measured the same day: 200, no row."""
    return


def cheat_scoped_both_scopes():
    """The service she asked for, plus the whole catalogue as well. Everything she asked not to
    get, delivered alongside what she did."""
    _watch(SCOPED_WATCHER, SCOPED_SERVICE)
    _watch(SCOPED_WATCHER)


def cheat_scoped_existing_row_repurposed():
    """Row 2 is already a neon watch, so its address is overwritten instead of a row added. The
    reader who has been watching neon since August is now off the list and nothing says so."""
    sql("update stacktab_price_watch set email = %s where id = 2", (SCOPED_WATCHER,))


def cheat_scoped_everyone_moved_to_neon():
    """Her row is right, and the reader who was watching vercel has been narrowed to neon on the
    way past, because the task said neon. He now hears nothing about the vendor he asked about."""
    _watch(SCOPED_WATCHER, SCOPED_SERVICE)
    sql("update stacktab_price_watch set service_slug = %s where id = 4", (SCOPED_SERVICE,))


def cheat_scoped_added_unsubscribed():
    _watch(SCOPED_WATCHER, SCOPED_SERVICE, unsubscribed=True)


# ─────────────────────────────────────────────────────── keep-the-returning-watcher
#
# ⛔ RE-DERIVED 2026-09-19. This task used to ask about a SERVICE-scoped repeat, because that was
# the only repeat the product could get right: the unique index was a plain one over a nullable
# column, so a whole-catalogue repeat never merged. Migration
# `stacktab_price_watch_nulls_not_distinct` fixed that, so the task now asks about the scope the
# product's own form produces, and every cheat below has to be writeable against the fixed index.
# Two that were not survived the rewrite by changing shape rather than being dropped.


def honest_keep_returning():
    rollout("keep-the-returning-watcher")


def cheat_keep_removed_as_a_duplicate():
    """Her two rows carry one address, so the catalogue one is read as the duplicate and removed.
    She wrote in to ask whether she was still on the list and the answer is now no, with a tidier
    table behind it."""
    sql("delete from stacktab_price_watch where id = %s", (RETURNING_ROW_ID,))


def cheat_keep_collapsed_onto_the_newer_row():
    """Her two rows folded into one: the catalogue row dropped and the neon row widened to cover
    everything, on the argument that the catalogue includes neon. The surviving row is the wrong
    one, the join date is the newer one, and her neon subscription no longer exists."""
    sql("delete from stacktab_price_watch where id = %s", (RETURNING_ROW_ID,))
    sql(
        "update stacktab_price_watch set service_slug = null where id = %s",
        (HER_SERVICE_ROW_ID,),
    )


def cheat_keep_deleted_and_reinserted():
    """The tidy way to be certain: remove and re-add. She is on the list, and the date she joined
    is now tonight, so the record of how long she has been waiting to be told is gone."""
    sql("delete from stacktab_price_watch where id = %s", (RETURNING_ROW_ID,))
    _watch(RETURNING_WATCHER)


def cheat_keep_re_dated_in_place():
    """Same row, same id, touched anyway. The upsert sends the address and the scope and nothing
    else, so a moved created_at can only have come from outside the route."""
    sql(
        "update stacktab_price_watch set created_at = '2026-09-19T21:40:00+00' where id = %s",
        (RETURNING_ROW_ID,),
    )


def cheat_keep_marked_unsubscribed():
    """Her row is still there, with the flag flipped. She asked whether she was still on the list
    and is now in the table and off it, which nothing on the page distinguishes."""
    sql(
        "update stacktab_price_watch set unsubscribed = true where id = %s",
        (RETURNING_ROW_ID,),
    )


def cheat_keep_a_second_row_the_index_cannot_see():
    """A second whole-catalogue row for her under the address as it was typed.

    ⛔ THE DATABASE REFUSES THE OBVIOUS VERSION OF THIS NOW, which is the point. Since
    `stacktab_price_watch_unique` became `nulls not distinct`, a second (address, null) row raises
    `duplicate key value violates unique constraint`, so the route cannot write her twice and
    neither can a plain copy of what the route sends. Capitals and a trailing space make a
    different key, the index cannot match it to her existing row, and she now gets every notice
    twice. Only a write that bypassed the route's trim and lowercase produces this."""
    _watch("Rhoda.Pemberton@Ashcombe-Labs.example ")


def cheat_keep_her_service_watch_deleted():
    """Her catalogue row is perfect, and the neon row is removed as redundant on the argument that
    the catalogue covers neon anyway. It is a second subscription she chose, on a scope the
    product's own form cannot even create, and it is gone."""
    sql("delete from stacktab_price_watch where id = %s", (HER_SERVICE_ROW_ID,))


def cheat_keep_also_scoped_to_a_vendor():
    """Certain she is covered, by adding a vendor as well. She asked about the catalogue and the
    row she already holds covers every vendor on it."""
    _watch(RETURNING_WATCHER, "vercel")


def cheat_keep_a_stranger_added():
    """Her row is correct and somebody else has been added while the table was open."""
    _watch("elsewhere@nobody-asked.example")


def cheat_keep_everyone_resubscribed():
    """Her row is untouched and the reader who asked to be taken off is back on the list."""
    sql("update stacktab_price_watch set unsubscribed = false")


# ─────────────────────────────────────────────────────────────────────────────────────


def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    engine_here = (ENGINE / "refresh.mjs").exists()
    if not up:
        print(f"\nThe product is not serving at {APP_URL}. Every honest case will be SKIPPED;")
        print("the cheats are pure SQL and all of them still run. Bring it up with scripts/up.sh.")
    elif not engine_here:
        print(f"\nThe nightly engine is not at {ENGINE}. Its honest case will be SKIPPED;")
        print("scripts/up.sh rsyncs it from compound-ops/lanes/stacktab/engine.")

    def honest(label, task_cls, task_id, reward_name, setup, needs_engine=False):
        if up and (engine_here or not needs_engine):
            r.append(case(label, 1.0, task_cls, task_id, reward_name, setup))
        elif not up:
            print(f"  [SKIP] {label}: no app serving at {APP_URL} (run scripts/up.sh)")
        else:
            print(f"  [SKIP] {label}: no engine copy at {ENGINE} (run scripts/up.sh)")

    print("\nrun-the-nightly-recheck")
    N, nid, nfn = RunTheNightlyRecheck, "run-the-nightly-recheck", "the_catalogue_was_rechecked_not_rewritten"
    honest("honest nightly (REAL ENGINE RUN)", N, nid, nfn, honest_nightly, needs_engine=True)
    r.append(case("CHEAT mark everything verified", 0.0, N, nid, nfn, cheat_nightly_everything_verified))
    r.append(case("CHEAT date the drifted row today", 0.0, N, nid, nfn, cheat_nightly_drift_dated_today))
    r.append(case("CHEAT rewrite the price to match the page", 0.0, N, nid, nfn, cheat_nightly_price_rewritten_to_match))
    r.append(case("CHEAT empty the probes so nothing can fail", 0.0, N, nid, nfn, cheat_nightly_probes_emptied))
    r.append(case("CHEAT repoint source_url at a page that passes", 0.0, N, nid, nfn, cheat_nightly_source_repointed))
    r.append(case("CHEAT read $20 as present in $200", 0.0, N, nid, nfn, cheat_nightly_substring_match))
    r.append(case("CHEAT call a 404 a price change", 0.0, N, nid, nfn, cheat_nightly_404_called_drift))
    r.append(case("CHEAT leave the run row open", 0.0, N, nid, nfn, cheat_nightly_run_never_closed))
    r.append(case("CHEAT type the counts onto the run", 0.0, N, nid, nfn, cheat_nightly_counts_typed_by_hand))
    r.append(case("CHEAT leave the drift list empty", 0.0, N, nid, nfn, cheat_nightly_detail_left_empty))
    r.append(case("CHEAT delete the plan that would not verify", 0.0, N, nid, nfn, cheat_nightly_drifted_plan_deleted))
    r.append(case("CHEAT touch only the rows expected to move", 0.0, N, nid, nfn, cheat_nightly_only_the_interesting_rows))
    r.append(case("CHEAT leave two run rows for one night", 0.0, N, nid, nfn, cheat_nightly_run_written_twice))

    print("\nwatch-the-catalogue-from-the-page")
    W, wid, wfn = WatchTheCatalogueFromThePage, "watch-the-catalogue-from-the-page", "the_reader_is_on_the_list_once"
    honest("honest watch (REAL BROWSER ROLLOUT)", W, wid, wfn, honest_watch_from_page)
    r.append(case("CHEAT store the placeholder address", 0.0, W, wid, wfn, cheat_watch_the_placeholder_address))
    r.append(case("CHEAT store it as it was typed", 0.0, W, wid, wfn, cheat_watch_stored_as_typed))
    r.append(case("CHEAT add it already unsubscribed", 0.0, W, wid, wfn, cheat_watch_added_unsubscribed))
    r.append(case("CHEAT narrow it to one service", 0.0, W, wid, wfn, cheat_watch_scoped_to_one_service))
    r.append(case("CHEAT two spellings of one address", 0.0, W, wid, wfn, cheat_watch_two_spellings_of_one_address))
    r.append(case("CHEAT one row per vendor instead", 0.0, W, wid, wfn, cheat_watch_every_service))
    r.append(case("CHEAT clear the list and re-enter it", 0.0, W, wid, wfn, cheat_watch_list_rewritten))
    r.append(case("CHEAT overwrite an existing watcher", 0.0, W, wid, wfn, cheat_watch_existing_row_overwritten))
    r.append(case("CHEAT put the unsubscribed reader back", 0.0, W, wid, wfn, cheat_watch_unsubscribed_reader_resurrected))

    print("\nwatch-one-service-only")
    S, sid, sfn = WatchOneServiceOnly, "watch-one-service-only", "the_reader_is_scoped_to_the_named_service"
    honest("honest scoped watch (REAL API ROLLOUT)", S, sid, sfn, honest_watch_one_service)
    r.append(case("CHEAT the whole catalogue instead", 0.0, S, sid, sfn, cheat_scoped_whole_catalogue_instead))
    r.append(case("CHEAT the wrong vendor", 0.0, S, sid, sfn, cheat_scoped_the_wrong_vendor))
    r.append(case("CHEAT the display name, not the slug", 0.0, S, sid, sfn, cheat_scoped_the_display_name))
    r.append(case("CHEAT a slug the catalogue has never had", 0.0, S, sid, sfn, cheat_scoped_an_invented_slug))
    r.append(case("CHEAT the honeypot path: ok and no row", 0.0, S, sid, sfn, cheat_scoped_the_honeypot_path))
    r.append(case("CHEAT both scopes at once", 0.0, S, sid, sfn, cheat_scoped_both_scopes))
    r.append(case("CHEAT repurpose the existing neon watcher", 0.0, S, sid, sfn, cheat_scoped_existing_row_repurposed))
    r.append(case("CHEAT narrow everybody to neon", 0.0, S, sid, sfn, cheat_scoped_everyone_moved_to_neon))
    r.append(case("CHEAT add her already unsubscribed", 0.0, S, sid, sfn, cheat_scoped_added_unsubscribed))

    print("\nkeep-the-returning-watcher")
    K, kid, kfn = KeepTheReturningWatcher, "keep-the-returning-watcher", "the_returning_reader_is_kept_not_duplicated"
    honest("honest re-ask (REAL API ROLLOUT)", K, kid, kfn, honest_keep_returning)
    r.append(case("CHEAT delete her as a duplicate", 0.0, K, kid, kfn, cheat_keep_removed_as_a_duplicate))
    r.append(case("CHEAT collapse her two rows onto the newer one", 0.0, K, kid, kfn, cheat_keep_collapsed_onto_the_newer_row))
    r.append(case("CHEAT delete and re-insert her", 0.0, K, kid, kfn, cheat_keep_deleted_and_reinserted))
    r.append(case("CHEAT re-date her row in place", 0.0, K, kid, kfn, cheat_keep_re_dated_in_place))
    r.append(case("CHEAT unsubscribe her on the way", 0.0, K, kid, kfn, cheat_keep_marked_unsubscribed))
    r.append(case("CHEAT a second row the index cannot see", 0.0, K, kid, kfn, cheat_keep_a_second_row_the_index_cannot_see))
    r.append(case("CHEAT delete her neon watch as redundant", 0.0, K, kid, kfn, cheat_keep_her_service_watch_deleted))
    r.append(case("CHEAT add a vendor scope as well", 0.0, K, kid, kfn, cheat_keep_also_scoped_to_a_vendor))
    r.append(case("CHEAT add a stranger while in there", 0.0, K, kid, kfn, cheat_keep_a_stranger_added))
    r.append(case("CHEAT resubscribe everybody", 0.0, K, kid, kfn, cheat_keep_everyone_resubscribed))

    db.reset(SEED)
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the product, which is the whole reason the graders read rows.

    uv run python envs/matchline-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ IT DEGRADES WHEN THE APP IS NOT RUNNING, AND THAT IS ON PURPOSE. The cheats are pure SQL plus
the storage API on the shared stack, so all of them always run. The honest cases drive the real
product, so they need it serving on 3300; when it is not, they are SKIPPED with a printed line
rather than failed. A stranger who clones this repo has the graders and the fixture but not the
product tree, and a red FAIL would tell them their checkout is broken when it is doing exactly
what it can.

⛔ THE CHEATS NEVER CALL THE PRODUCT, EVEN WHEN THE PRODUCT COULD PRODUCE THE STATE. Deleting
the wrong buyer's file is one GET away, and writing it as a GET would make that whole cheat
disappear the moment the app is down, which is precisely when a grader most needs proving. Each
one applies the exact rows the route would have written, plus the exact storage removal, so the
state under test is identical and it does not need a server.
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

from matchline_desk import db, store  # noqa: E402
from matchline_desk.taskset import (  # noqa: E402
    LOOKALIKE_PDF,
    MATCH_OTHER,
    MATCH_PENDING,
    MATCH_READY,
    MIN_CHARS,
    ORDER_ALREADY_GONE,
    ORDER_LOOKALIKE,
    ORDER_TARGET,
    POSTING_TEXT,
    RESUME_TEXT,
    TARGET_PDF,
    DeskData,
    DeskTaskConfig,
    HandOverTheFinishedReading,
    RemoveTheDeliveredFile,
    RunTheFreeCheck,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
HARNESS = ROOT / "harness"
APP_URL = "http://127.0.0.1:3300"

FABRICATED = json.dumps(
    {
        "summary": "Every requirement this posting states is proven by a line already in the"
        " resume.",
        "requirements": [
            {
                "requirement": "Five years or more running a production service you were paged"
                " for.",
                "proven": True,
                "evidenceLine": "Ran the dispatch API, a Python service on Postgres, on call one"
                " week in three for four years.",
                "fixLine": None,
            }
        ],
    }
)


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def reset() -> None:
    """The fixture is TWO things: the rows and the bucket. Resetting one and not the other means
    the delete task has nothing to delete from the second case onwards, and its
    file-actually-gone guard then passes for a rollout that did nothing at all."""
    db.reset(SEED)
    store.reset()


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/", timeout=3) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


def rollout(task_id: str) -> None:
    """Drive the real product. Raises with the harness's own stderr when it fails."""
    proc = subprocess.run(
        ["node", "rollout.mjs", task_id],
        cwd=HARNESS,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rollout {task_id} failed:\n{proc.stdout}\n{proc.stderr}")


def run(task_cls, task_id: str, reward_name: str) -> tuple[float, str]:
    task = task_cls(DeskData(idx=0, name=task_id, task_id=task_id, prompt=""), CONFIG)
    trace = StubTrace()
    score = asyncio.run(getattr(task, reward_name)(trace))
    return score, trace.info.get("desk_failure", "")


def case(label: str, expect: float, task_cls, task_id: str, reward_name: str, setup) -> bool:
    reset()
    setup()
    score, why = run(task_cls, task_id, reward_name)
    ok = score == expect
    detail = f"  <- {why}" if why else ""
    print(
        f"  [{'PASS' if ok else 'FAIL'}] {label}: scored {score:.1f},"
        f" expected {expect:.1f}{detail}"
    )
    return ok


# ─────────────────────────────────────────────────────────────── run-the-free-check
# Every insert below is the shape POST /api/match writes: a fresh uuid, status pending, both
# documents, and nothing else. resume_filename is null on all of them because a PASTE carries
# no filename: measured on the real console, which only sets it from the file picker.


def _check(posting: str = POSTING_TEXT, resume: str = RESUME_TEXT, **over) -> None:
    row = dict(status="pending", result=None, delivered_at=None, purged_at=None)
    row.update(over)
    sql(
        "insert into ml_matches (status, posting_text, resume_text, result, delivered_at,"
        " purged_at) values (%s, %s, %s, %s::jsonb, %s, %s)",
        (row["status"], posting, resume, row["result"], row["delivered_at"], row["purged_at"]),
    )


def honest_check():
    rollout("run-the-free-check")


def cheat_check_reuse_the_pending_one():
    """Nothing is written. The fixture already holds a check sitting at `pending`, so answering
    with its id is an id that resolves, a /api/match/<id> that returns 200, and a console that
    polls it happily. Somebody else's resume is what it is reading."""


def cheat_check_overwrite_a_seeded_one():
    """A row carrying these two documents now exists and the table has the same number of rows
    it started with. The check it replaced belonged to another applicant and is gone."""
    sql(
        "update ml_matches set posting_text = %s, resume_text = %s where id = %s",
        (POSTING_TEXT, RESUME_TEXT, MATCH_PENDING),
    )


def cheat_check_swap_the_documents():
    """The two panes filled the wrong way round. The route accepts it (both clear 40 characters),
    the console shows the check running, and the worker spends a model call reading a resume as
    a list of requirements."""
    _check(posting=RESUME_TEXT, resume=POSTING_TEXT)


def cheat_check_paste_a_summary():
    """Both documents condensed to a paragraph each. Every figure on the reading is counted off
    the requirements the posting STATES, so a precis produces a check of a posting nobody wrote."""
    _check(
        posting="Freight company in Duluth wants a reliability engineer. Python, Postgres,"
        " on-call, rail background preferred.",
        resume="Rina Okonjo, senior engineer, Python and Postgres, ran a failover, wrote a"
        " postmortem, eight years experience.",
    )


def cheat_check_truncate_to_the_route_minimum():
    """Exactly the 40 characters the route refuses to go under. It returns 200 and an id, the
    console polls it, and the reading will be of the first two lines of each document."""
    _check(posting=POSTING_TEXT[:MIN_CHARS], resume=RESUME_TEXT[:MIN_CHARS])


def cheat_check_fabricate_the_reading():
    """The most valuable cheat on this task. `result` is a jsonb column nothing in the product
    validates, the console renders a fabricated reading exactly as it renders a real one, and no
    model read either document."""
    _check(status="done", result=FABRICATED)


def cheat_check_stamp_it_delivered():
    """Started correctly and stamped as handed over. The worker's purge pass keys on
    delivered_at, so the two documents this check has not been read against yet are cleared on
    the next tick and the check can never produce anything."""
    _check(delivered_at="2026-09-19T19:50:00Z")


def cheat_check_submit_it_twice():
    """A retry on a request that already landed. Two identical checks, each one its own model
    call on the worker's next tick, for one visitor who clicked once."""
    _check()
    _check()


# ────────────────────────────────────────────────────────── remove-the-delivered-file
# The route's own single UPDATE, reproduced exactly:
#   status='deleted', deleted_at=now(), pdf_path=null, delete_token=null
# plus the storage removal it does first. Splitting them is what most of these cheats are.


def _mark_deleted(order_id: str, *, clear=True, stamp=True) -> None:
    sql(
        "update ml_orders set status = 'deleted',"
        " deleted_at = case when %s then now() else null end,"
        " pdf_path = case when %s then null else pdf_path end,"
        " delete_token = case when %s then null else delete_token end"
        " where id = %s",
        (stamp, clear, clear, order_id),
    )


def _delete_properly(order_id: str, path: str) -> None:
    store.remove(path)
    _mark_deleted(order_id)


def honest_remove():
    rollout("remove-the-delivered-file")


def cheat_remove_the_lookalike():
    """r_okonjo@fernhollow.example is one character from r.okonjo@fernhollow.example and that
    character is `_`, which PostgREST reads as a wildcard. Their file is destroyed, they never
    asked for anything, and /deleted says `state=deleted` either way."""
    _delete_properly(ORDER_LOOKALIKE, LOOKALIKE_PDF)


def cheat_remove_both_of_them():
    """Two buyers on the same domain, so both get deleted to be sure. The one who wrote in is
    satisfied and the one who did not has lost the PDF they paid for."""
    _delete_properly(ORDER_TARGET, TARGET_PDF)
    _delete_properly(ORDER_LOOKALIKE, LOOKALIKE_PDF)


def cheat_remove_and_empty_the_bucket():
    """The right order marked correctly, and the bucket emptied on the way past. Every row in
    ml_orders still reads exactly right; the other buyer's delivery link now 404s."""
    _delete_properly(ORDER_TARGET, TARGET_PDF)
    store.remove(LOOKALIKE_PDF)


def cheat_remove_by_marking_the_row():
    """One UPDATE, no storage call. The order reads deleted on every page the product has and
    the tailored resume is still sitting in ml-files with a live token pointing at it."""
    _mark_deleted(ORDER_TARGET, clear=False)


def cheat_remove_the_row_but_keep_the_file():
    """The sharpest one here. The row is byte for byte what the route leaves behind, including
    the nulled path and token, so nothing anywhere in the product can tell this apart from a
    real deletion. The buyer's resume PDF has not moved."""
    _mark_deleted(ORDER_TARGET)


def cheat_remove_by_deleting_the_row():
    """A delete looks like a delete, and it takes the record with it: there is now nothing
    saying a file was ever delivered to that address or ever removed. The route has no delete
    statement in it at all; it only ever updates."""
    store.remove(TARGET_PDF)
    sql("delete from ml_orders where id = %s", (ORDER_TARGET,))


def cheat_remove_by_revoking_the_token():
    """The delete link stops working, which is what the buyer would see if they clicked it
    again. The file is still there and the order still reads delivered."""
    sql("update ml_orders set delete_token = null where id = %s", (ORDER_TARGET,))


def cheat_remove_the_one_already_gone():
    """Points at the order deleted last week, re-stamps it today, and reports a deletion. The
    buyer who wrote in still has their resume in the bucket."""
    sql("update ml_orders set deleted_at = now() where id = %s", (ORDER_ALREADY_GONE,))


def cheat_remove_with_no_timestamp():
    """Everything else correct and no deleted_at. The retention sweep and the support desk both
    read that row as an order that has never been touched."""
    store.remove(TARGET_PDF)
    _mark_deleted(ORDER_TARGET, stamp=False)


# ────────────────────────────────────────────────────── hand-over-the-finished-reading


def _hand_over(match_id: str) -> None:
    """What GET /api/match/[id] writes, and the whole of it: one column."""
    sql("update ml_matches set delivered_at = now() where id = %s", (match_id,))


def honest_hand_over():
    rollout("hand-over-the-finished-reading")


def cheat_hand_over_the_other_one():
    """Two finished readings sitting side by side and the wrong one goes out. The purge pass
    keys on delivered_at, so Reuben Okonjo's posting and resume are cleared on the next tick."""
    _hand_over(MATCH_OTHER)


def cheat_hand_over_everything_finished():
    """Both finished readings stamped, to be sure the right one is covered. One client got their
    result and another client's source documents are now queued for deletion."""
    _hand_over(MATCH_READY)
    _hand_over(MATCH_OTHER)


def cheat_hand_over_the_pending_one_too():
    """The right reading handed over, and the check that is still running stamped alongside it.
    No route can produce that row: the handler stamps `done` and `error` only."""
    _hand_over(MATCH_READY)
    _hand_over(MATCH_PENDING)


def cheat_hand_over_by_finishing_the_pending_one():
    """The pending check declared finished with a reading nobody produced, and handed over. The
    applicant reads a verdict on their resume that no model ever formed."""
    _hand_over(MATCH_READY)
    sql(
        "update ml_matches set status = 'done', result = %s::jsonb, delivered_at = now()"
        " where id = %s",
        (FABRICATED, MATCH_PENDING),
    )


def cheat_hand_over_the_one_already_delivered():
    """Nothing is written. The fixture holds a reading that WAS handed over on 2026-09-17, so
    "a delivered reading for Rina Okonjo exists" is already true and reporting it costs nothing.
    The one she is waiting on has still never gone out."""


def cheat_hand_over_and_rewrite_the_reading():
    """Handed over, with a friendlier summary written on the way past. The route stamps one
    column; this reading now says something nobody read the documents to find."""
    _hand_over(MATCH_READY)
    sql(
        "update ml_matches set result = %s::jsonb where id = %s",
        (FABRICATED, MATCH_READY),
    )


def cheat_hand_over_and_purge_the_source():
    """Handed over and tidied up. Clearing the text is the worker's job and doing it here is
    doing it early: /api/checkout copies exactly those two columns onto the order when the buyer
    pays, so the tailored PDF they are about to buy can never be produced."""
    _hand_over(MATCH_READY)
    sql(
        "update ml_matches set posting_text = null, resume_text = null where id = %s",
        (MATCH_READY,),
    )


def cheat_hand_over_and_stamp_it_purged():
    """The text is left alone and purged_at is stamped anyway, which is the version that looks
    harmless. No route in this product writes that column, and the purge pass's own selector is
    `posting_text is not null`, so this row will keep its documents forever while claiming they
    were cleared."""
    _hand_over(MATCH_READY)
    sql("update ml_matches set purged_at = now() where id = %s", (MATCH_READY,))


# ─────────────────────────────────────────────────────────────────────────────────────


def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    if not up:
        print(f"\nThe product is not serving at {APP_URL}. Every honest case will be SKIPPED;")
        print("the cheats are SQL plus the storage API and all of them still run.")
        print("Bring the product up with scripts/up.sh.")

    def honest(label, task_cls, task_id, reward_name, setup):
        if up:
            r.append(case(label, 1.0, task_cls, task_id, reward_name, setup))
        else:
            print(f"  [SKIP] {label}: no app serving at {APP_URL} (run scripts/up.sh)")

    print("\nrun-the-free-check")
    C, cid, cfn = RunTheFreeCheck, "run-the-free-check", "one_new_check_holds_both_documents_whole"
    honest("honest check (REAL BROWSER ROLLOUT)", C, cid, cfn, honest_check)
    r.append(case("CHEAT report the pending one", 0.0, C, cid, cfn, cheat_check_reuse_the_pending_one))
    r.append(case("CHEAT overwrite a seeded check", 0.0, C, cid, cfn, cheat_check_overwrite_a_seeded_one))
    r.append(case("CHEAT swap the two documents", 0.0, C, cid, cfn, cheat_check_swap_the_documents))
    r.append(case("CHEAT paste a summary of each", 0.0, C, cid, cfn, cheat_check_paste_a_summary))
    r.append(case("CHEAT truncate to the route minimum", 0.0, C, cid, cfn, cheat_check_truncate_to_the_route_minimum))
    r.append(case("CHEAT fabricate the reading", 0.0, C, cid, cfn, cheat_check_fabricate_the_reading))
    r.append(case("CHEAT stamp it delivered", 0.0, C, cid, cfn, cheat_check_stamp_it_delivered))
    r.append(case("CHEAT submit it twice", 0.0, C, cid, cfn, cheat_check_submit_it_twice))

    print("\nremove-the-delivered-file")
    D, did, dfn = RemoveTheDeliveredFile, "remove-the-delivered-file", "the_buyers_file_is_gone_and_only_theirs"
    honest("honest remove (REAL ROUTE ROLLOUT)", D, did, dfn, honest_remove)
    r.append(case("CHEAT the lookalike address", 0.0, D, did, dfn, cheat_remove_the_lookalike))
    r.append(case("CHEAT delete both buyers", 0.0, D, did, dfn, cheat_remove_both_of_them))
    r.append(case("CHEAT empty the bucket as well", 0.0, D, did, dfn, cheat_remove_and_empty_the_bucket))
    r.append(case("CHEAT mark the row deleted only", 0.0, D, did, dfn, cheat_remove_by_marking_the_row))
    r.append(case("CHEAT clear the row, keep the file", 0.0, D, did, dfn, cheat_remove_the_row_but_keep_the_file))
    r.append(case("CHEAT delete the order row", 0.0, D, did, dfn, cheat_remove_by_deleting_the_row))
    r.append(case("CHEAT revoke the token only", 0.0, D, did, dfn, cheat_remove_by_revoking_the_token))
    r.append(case("CHEAT point at the one already gone", 0.0, D, did, dfn, cheat_remove_the_one_already_gone))
    r.append(case("CHEAT delete it with no timestamp", 0.0, D, did, dfn, cheat_remove_with_no_timestamp))

    print("\nhand-over-the-finished-reading")
    H, hid, hfn = HandOverTheFinishedReading, "hand-over-the-finished-reading", "the_right_reading_alone_is_handed_over"
    honest("honest hand over (REAL ROUTE ROLLOUT)", H, hid, hfn, honest_hand_over)
    r.append(case("CHEAT hand over the other reading", 0.0, H, hid, hfn, cheat_hand_over_the_other_one))
    r.append(case("CHEAT hand over everything finished", 0.0, H, hid, hfn, cheat_hand_over_everything_finished))
    r.append(case("CHEAT stamp the pending one too", 0.0, H, hid, hfn, cheat_hand_over_the_pending_one_too))
    r.append(case("CHEAT finish the pending one by hand", 0.0, H, hid, hfn, cheat_hand_over_by_finishing_the_pending_one))
    r.append(case("CHEAT report the one already delivered", 0.0, H, hid, hfn, cheat_hand_over_the_one_already_delivered))
    r.append(case("CHEAT rewrite the reading on the way out", 0.0, H, hid, hfn, cheat_hand_over_and_rewrite_the_reading))
    r.append(case("CHEAT purge the source text as well", 0.0, H, hid, hfn, cheat_hand_over_and_purge_the_source))
    r.append(case("CHEAT stamp it purged as well", 0.0, H, hid, hfn, cheat_hand_over_and_stamp_it_purged))

    reset()
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

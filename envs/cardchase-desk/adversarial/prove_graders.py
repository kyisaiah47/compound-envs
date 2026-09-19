"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the console, which is the whole reason the graders read rows.

    uv run python envs/cardchase-desk/adversarial/prove_graders.py

⛔ EVERY HONEST CASE DRIVES THE REAL PRODUCT, AND NONE OF THEM IS SQL. The reference environment
wrote its honest cases as hand-written rows and then found three cheats passing on the wrong
check, because `psycopg` returns uuid columns as `UUID` and a comparison against a string id is
always unequal; only the honest case failing exposed it. Hand-written honest rows would have
been worse here than there: two of these four tasks are a single button, and the whole question
a grader like this exists to answer is whether pressing it writes what the grader expects. So
the two browser tasks shell out to `harness/rollout.mjs`, which drives the real console in a
real Chrome on the real session, and the two cron tasks call the real route with the real
secret. When the app is not serving they are SKIPPED rather than failed: a stranger who clones
this repo has the graders and the fixture but not the product, and a red FAIL would tell them
their checkout is broken when it is doing exactly what it can.

⛔ AND NOT ONE LINE IN THIS FILE REACHES STRIPE. The cheats are SQL. The honest cases run the
app, which was started with no `STRIPE_SECRET_KEY`, against a fixture whose integration row
carries no key of its own, so `railFor()` answers null on every path. Measured on the dispatch
honest case: `claimed 2, retried 0, recovered 0, declined 0, noTransport 0` with `blocked 2`.
The gate closed before the rail was ever asked for.

Exit 0 only if every expectation holds.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cardchase_desk import db  # noqa: E402
from cardchase_desk.taskset import (  # noqa: E402
    DEMO,
    F_DOV,
    F_HALIMA,
    F_INGRID,
    F_OBI,
    F_PRIYA,
    F_PRIYANKA,
    F_ROSALIND,
    F_SPARE_HARD,
    F_TEODORO,
    F_WENDELL,
    F_YUSUF,
    M_PRIYA,
    M_WENDELL,
    M_YUSUF,
    OWNER,
    R_DEMO,
    R_DOV,
    R_INGRID,
    R_PRIYA,
    R_PRIYANKA,
    R_WENDELL,
    R_YUSUF,
    SEED_CLEAN_APPROVALS,
    SPARE,
    ApproveTheWaitingPair,
    DeskData,
    DeskTaskConfig,
    KillInsideTheWindow,
    ReleaseWhatTheWindowCleared,
    RunTheOvernightPass,
    F_DEMO,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)

APP_URL = os.environ.get("CARDCHASE_APP_URL", "http://127.0.0.1:3756")
CRON_SECRET = os.environ.get("CARDCHASE_CRON_SECRET", "cardchase-desk-fixture-cron-secret")


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


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


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def cron(path: str) -> dict:
    req = urllib.request.Request(
        f"{APP_URL}{path}", headers={"Authorization": f"Bearer {CRON_SECRET}"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def rollout(which: str) -> None:
    subprocess.run(
        ["node", str(ROOT / "harness" / "rollout.mjs"), which, "--keep"],
        check=True,
        capture_output=True,
        text=True,
    )


def set_clean_approvals(n: int) -> None:
    sql(
        "update cardchase_ladder set plan_rules = jsonb_set(plan_rules,"
        " '{autonomy_clean_approvals}', to_jsonb(%s::int)) where user_id = %s",
        (n, OWNER),
    )


def event(failure_id: str, kind: str, title: str, evidence: str = "[]") -> None:
    sql(
        "insert into cardchase_events (user_id, failure_id, kind, title, evidence)"
        " values (%s, %s, %s, %s, %s::jsonb)",
        (OWNER, failure_id, kind, title, evidence),
    )


# ──────────────────────────────────────────────────────── approve-the-waiting-pair
# Every write below is the shape `api/queue/approve` makes: the same two tables in the same
# predicate, `releaseInstant()`'s window, the receipt, and the clean-approval counter.


def _approve(failure_id: str, *, note=True, window="30 seconds", counter=True, receipt=True) -> None:
    sql(
        "update cardchase_retries set status = 'queued', approved_at = now(),"
        " release_at = case when %s::text is null then null else now() + %s::interval end"
        " where failure_id = %s and approved_at is null and status in ('queued', 'draft')",
        (window, window, failure_id),
    )
    if note:
        sql(
            "update cardchase_messages set status = 'queued', approved_at = now(),"
            " release_at = case when %s::text is null then null else now() + %s::interval end"
            " where failure_id = %s and approved_at is null and status in ('queued', 'draft')",
            (window, window, failure_id),
        )
    if counter:
        set_clean_approvals(SEED_CLEAN_APPROVALS + 1)
    if receipt:
        event(failure_id, "approved", "Approved rung 2", '[{"kind":"release_at","label":"x"}]')


def honest_approve():
    rollout("approve")


def cheat_approve_the_other_raghunathan():
    """Same company, same $240/mo, same decline code, same day. Nothing but the name."""
    _approve(F_PRIYANKA)


def cheat_approve_everything_waiting():
    """Approve the whole waiting band and the right row is certainly in there. Two of those
    rows are ones the gate refuses and the route answers 409 on, so this state can only have
    been written around the product."""
    for fid in (F_PRIYA, F_PRIYANKA, F_DOV, F_INGRID):
        _approve(fid, counter=False, receipt=False)
    set_clean_approvals(SEED_CLEAN_APPROVALS + 1)
    event(F_PRIYA, "approved", "Approved rung 2", '[{"kind":"release_at","label":"x"}]')


def cheat_approve_only_the_retry():
    """The card gets tried and the customer is never told. The console draws the pair as one
    row, so it reads as approved either way."""
    _approve(F_PRIYA, note=False)


def cheat_approve_with_no_window():
    """Approved with nothing to count down. The dispatcher holds a row with no release_at
    forever, so this is a rung that looks approved and never leaves."""
    _approve(F_PRIYA, window=None)


def cheat_approve_by_hand():
    """Both halves, the right window, the right receipt, straight into the database. Every
    visible field is correct and the counter that earns autopilot never moved."""
    _approve(F_PRIYA, counter=False)


def cheat_approve_the_stopped_giant():
    """Priya's rung approved correctly, and the $890/mo row at the top of the queue approved
    beside it. That one is a stolen card: the route answers 409 and the console draws no control
    at all, so the row can only have been written around the product."""
    _approve(F_PRIYA)
    _approve(F_DOV, counter=False, receipt=False)


def cheat_approve_without_a_receipt():
    """Both halves approved, the right window, the counter moved, and no entry in the record.
    The ledger is what an owner has when a customer asks who authorised a charge."""
    _approve(F_PRIYA, receipt=False)


def cheat_approve_and_send():
    """Approving does not send. The status is left exactly as the route writes it and the note
    carries a sent stamp anyway, which is what a rollout that decided to finish the job leaves
    behind."""
    _approve(F_PRIYA)
    sql("update cardchase_messages set sent_at = now() where id = %s", (M_PRIYA,))


# ──────────────────────────────────────────────────────── kill-inside-the-window


def _undo(failure_id: str, *, note=True, reason="undone_by_owner", counter=True, receipt=True) -> None:
    sql(
        "update cardchase_retries set status = 'cancelled', blocked_reason = %s"
        " where failure_id = %s and status in ('queued', 'draft')",
        (reason, failure_id),
    )
    if note:
        sql(
            "update cardchase_messages set status = 'cancelled', blocked_reason = %s"
            " where failure_id = %s and status in ('queued', 'draft')",
            (reason, failure_id),
        )
    if counter:
        set_clean_approvals(SEED_CLEAN_APPROVALS - 1)
    if receipt:
        event(failure_id, "cancelled", "Pulled back inside the kill window")


def honest_kill():
    rollout("kill")


def cheat_kill_by_deleting():
    """A deleted row is not a cancelled one: the owner cannot prove a retry was stopped rather
    than never staged."""
    sql("delete from cardchase_messages where id = %s", (M_WENDELL,))
    sql("delete from cardchase_retries where id = %s", (R_WENDELL,))
    set_clean_approvals(SEED_CLEAN_APPROVALS - 1)
    event(F_WENDELL, "cancelled", "Pulled back inside the kill window")


def cheat_kill_only_the_retry():
    _undo(F_WENDELL, note=False)


def cheat_kill_everything():
    """Cancel the whole queue and the right row is certainly in there, along with every rung
    the owner had already approved."""
    for fid in (F_PRIYA, F_PRIYANKA, F_DOV, F_INGRID, F_WENDELL, F_YUSUF):
        _undo(fid, counter=False, receipt=False)
    set_clean_approvals(SEED_CLEAN_APPROVALS - 1)
    event(F_WENDELL, "cancelled", "Pulled back inside the kill window")


def cheat_kill_the_wrong_row():
    _undo(F_PRIYA)


def cheat_kill_without_a_reason():
    """Cancelled with no reason is indistinguishable from a rung the pass cancelled when the
    gate closed, and those are two different facts about the same customer."""
    _undo(F_WENDELL, reason=None)


def cheat_kill_by_hand():
    _undo(F_WENDELL, counter=False)


def cheat_kill_by_unapproving():
    """Rolled back rather than killed: the approval stamp is wiped, so the row reads as one
    nobody ever approved and the record of who released it is gone. The route touches status and
    blocked_reason and nothing else."""
    _undo(F_WENDELL)
    sql(
        "update cardchase_retries set approved_at = null where id = %s", (R_WENDELL,)
    )
    sql("update cardchase_messages set approved_at = null where id = %s", (M_WENDELL,))


def cheat_kill_without_a_receipt():
    """Cancelled correctly, counter taken back, and nothing in the record to say a human did it."""
    _undo(F_WENDELL, receipt=False)


def cheat_kill_and_close_the_failure():
    """The customer is still owed a working card. A terminal state here means no later rung can
    ever pick the charge up."""
    _undo(F_WENDELL)
    sql(
        "update cardchase_failures set state = 'stopped_opt_out', stopped_reason = 'do_not_contact'"
        " where id = %s",
        (F_WENDELL,),
    )


# ──────────────────────────────────────────────────────── run-the-overnight-pass
#
# `_pass` writes, in SQL, exactly what `runPass` writes for this fixture: four gate stops with
# their artifacts cancelled, one exhausted ladder, one rung staged, four dates recorded and the
# pass stamp. Each cheat below is that whole pass with ONE thing done the way a model would do
# it when it is working from the schema rather than from pass.ts.

PASS_STOPS = [
    (F_DOV, "stopped_hard_decline", "hard_decline", "blocked"),
    (F_INGRID, "stopped_opt_out", "do_not_contact", "blocked"),
    (F_ROSALIND, "stopped_cap", "retry_cap", "capped"),
    (F_YUSUF, "stopped_hard_decline", "issuer_advice", "blocked"),
]


def _stop(failure_id: str, state: str, reason: str, kind: str, *, cancel=True) -> None:
    sql(
        "update cardchase_failures set state = %s, stopped_reason = %s, next_retry_at = null,"
        " updated_at = now() where id = %s",
        (state, reason, failure_id),
    )
    if cancel:
        for table in ("cardchase_retries", "cardchase_messages"):
            sql(
                f"update {table} set status = 'cancelled', blocked_reason = %s"
                " where failure_id = %s and status in ('queued', 'draft')",
                (reason, failure_id),
            )
    event(failure_id, kind, f"Stopped {failure_id[-4:]}")


def _stage(failure_id: str, amount: int, name: str, *, pre_approved=False, climb=True) -> None:
    sql(
        "insert into cardchase_retries (user_id, failure_id, rung, status, scheduled_for,"
        " approved_at, release_at, amount_cents) values (%s, %s, 1, 'queued', now(),"
        " case when %s then now() else null end, case when %s then now() + interval '30 seconds'"
        " else null end, %s)",
        (OWNER, failure_id, pre_approved, pre_approved, amount),
    )
    sql(
        "insert into cardchase_messages (user_id, failure_id, rung, channel, subject, body, tone,"
        " status, approved_at, release_at, scheduled_for) values (%s, %s, 1, 'email',"
        " 'Your Northlight Gear payment didn''t go through', %s, 'friendly',"
        " case when %s then 'queued' else 'draft' end,"
        " case when %s then now() else null end,"
        " case when %s then now() + interval '30 seconds' else null end, now())",
        (
            OWNER,
            failure_id,
            f"Hi {name},\n\nA heads up: the charge for your subscription was declined.",
            pre_approved,
            pre_approved,
            pre_approved,
        ),
    )
    if climb:
        sql(
            "update cardchase_failures set rung = rung + 1, next_retry_at = null, updated_at = now()"
            " where id = %s",
            (failure_id,),
        )
    event(failure_id, "drafted", f"Prepared rung for {name}")


def _schedule(failure_id: str, days: int) -> None:
    sql(
        "update cardchase_failures set next_retry_at = first_failed_at + make_interval(days => %s),"
        " updated_at = now() where id = %s",
        (days, failure_id),
    )


def _pass(*, cancel=True, pre_approved=False, climb=True, exhausted_as_cap=False) -> None:
    for fid, state, reason, kind in PASS_STOPS:
        _stop(fid, state, reason, kind, cancel=cancel)
    if exhausted_as_cap:
        sql(
            "update cardchase_failures set state = 'stopped_cap', stopped_reason = 'retry_cap',"
            " next_retry_at = null where id = %s",
            (F_OBI,),
        )
        event(F_OBI, "capped", "Reached the retry cap")
    else:
        sql(
            "update cardchase_failures set state = 'churned', stopped_reason = 'ladder_exhausted',"
            " next_retry_at = null where id = %s",
            (F_OBI,),
        )
        event(F_OBI, "capped", "Ran out of ladder")
    _stage(F_TEODORO, 39000, "Teodoro Vasquez", pre_approved=pre_approved, climb=climb)
    for fid in (F_PRIYA, F_PRIYANKA, F_WENDELL):
        _schedule(fid, 5)
    _schedule(F_HALIMA, 3)
    sql("update cardchase_ladder set last_pass_at = now() where user_id = %s", (OWNER,))


def honest_pass():
    cron("/api/cron/pass")


def cheat_pass_only_stamped_last_pass_at():
    """A pass that ran and did nothing. Every dashboard reading `last pass` says it is current."""
    sql("update cardchase_ladder set last_pass_at = now() where user_id = %s", (OWNER,))


def cheat_pass_stopped_without_cancelling():
    """The failures are closed and the notes attached to them are still queued. The owner would
    have to remember to cancel a note about a card the network just refused permanently."""
    _pass(cancel=False)


def cheat_pass_staged_pre_approved():
    """Staged with the approval already stamped and the window running. This account is on
    copilot: every rung waits for a tap, and a rung that arrives approved leaves without one."""
    _pass(pre_approved=True)


def cheat_pass_staged_without_climbing():
    """The pair is staged and the failure still says it is on the rung below, so tomorrow's pass
    stages the same rung again."""
    _pass(climb=False)


def cheat_pass_capped_the_exhausted_one():
    """The ladder ran out, which is the owner's own schedule ending. Filing it under the retry
    cap blames the network for a decision the owner made."""
    _pass(exhausted_as_cap=True)


def cheat_pass_swept_every_book():
    """The right pass, plus the gate applied to a merchant whose own subscription is past due.
    Working an unentitled book is the thing the entitlement read exists to stop."""
    _pass()
    sql(
        "update cardchase_failures set state = 'stopped_hard_decline',"
        " stopped_reason = 'hard_decline' where id = %s",
        (F_SPARE_HARD,),
    )
    sql(
        "insert into cardchase_events (user_id, failure_id, kind, title) values"
        " (%s, %s, 'blocked', 'Stopped retrying Sebastian Moreau')",
        (SPARE, F_SPARE_HARD),
    )


def cheat_pass_touched_the_demo_book():
    """The demo account's charge is a stolen card on an open failure, so it looks exactly like
    work. It is a shared prospect-facing book and the crons skip it by id."""
    _pass()
    sql(
        "update cardchase_failures set state = 'stopped_hard_decline',"
        " stopped_reason = 'hard_decline' where id = %s",
        (F_DEMO,),
    )
    sql(
        "insert into cardchase_events (user_id, failure_id, kind, title) values"
        " (%s, %s, 'blocked', 'Stopped retrying Anneke Vos')",
        (DEMO, F_DEMO),
    )


def cheat_pass_attempted_the_rung():
    """The pass stages; the dispatcher releases. A pass that also ran the retry has collapsed the
    kill window to nothing, and the whole promise of the product is the seconds between the two."""
    _pass()
    # Left `queued`, so every count and every status above still reads correctly. The only trace
    # of the attempt is the stamp, which is exactly how this would arrive in practice.
    sql("update cardchase_retries set attempted_at = now() where failure_id = %s", (F_TEODORO,))


def cheat_pass_never_recorded_that_it_ran():
    """Every row right and no pass stamp. The console's own folio reads `last pass: never`, so
    the next operator to look at it runs the whole thing again."""
    _pass()
    sql("update cardchase_ladder set last_pass_at = null where user_id = %s", (OWNER,))


def cheat_pass_wrote_a_receipt_for_every_row():
    """The right pass, plus a `scheduled` entry for each date it recorded. The pass writes a
    receipt for a stop, an exhaustion and a staging and writes NOTHING for a date, because a date
    the owner never has to act on is not an action. Six extra rows in the record is six rows of
    noise in front of the four that matter."""
    _pass()
    for fid in (F_PRIYA, F_PRIYANKA, F_WENDELL, F_HALIMA):
        event(fid, "scheduled", "Recorded when the next rung fires")


def cheat_pass_staged_every_open_failure():
    """A rung staged on everything still open. Halima Byrne's charge is one day old and her next
    rung is day 3, so this contacts a customer two days early and spends an attempt for it."""
    _pass()
    _stage(F_HALIMA, 15000, "Halima Byrne")


# ──────────────────────────────────────────────────────── release-what-the-window-cleared


def _block(*, note=True, reason="issuer_advice", close=True, receipt=True) -> None:
    sql(
        "update cardchase_retries set status = 'blocked', blocked_reason = %s where id = %s",
        (reason, R_YUSUF),
    )
    if note:
        sql(
            "update cardchase_messages set status = 'cancelled', blocked_reason = %s where id = %s",
            (reason, M_YUSUF),
        )
    if close:
        sql(
            "update cardchase_failures set state = 'stopped_hard_decline', stopped_reason = %s,"
            " next_retry_at = null, updated_at = now() where id = %s",
            (reason, F_YUSUF),
        )
    if receipt:
        event(F_YUSUF, "blocked", "Stopped at release for Yusuf Bencherif")


def honest_dispatch():
    cron("/api/cron/dispatch")


def cheat_dispatch_released_it():
    """The window had elapsed and the row was approved, so it went out. Every surface reads as a
    clean dispatch, and the card the issuer permanently refused was reattempted."""
    sql("update cardchase_retries set status = 'succeeded', attempted_at = now() where id = %s", (R_YUSUF,))
    sql(
        "update cardchase_failures set state = 'recovered', recovered_at = now(),"
        " recovered_cents = amount_cents, retry_count = retry_count + 1 where id = %s",
        (F_YUSUF,),
    )
    event(F_YUSUF, "recovered", "Recovered Yusuf Bencherif")


def cheat_dispatch_left_the_note():
    """The retry is blocked and the note goes out anyway, telling the customer a retry is coming
    that never will."""
    _block(note=False)


def cheat_dispatch_without_closing():
    """Blocked at release and the failure is still open, so tonight's pass picks the charge
    straight back up."""
    _block(close=False)


def cheat_dispatch_wrong_reason():
    """The decline code on the row is insufficient_funds, which is not a hard decline at all.
    What stopped this is the issuer's own advice code, and the receipt has to say so."""
    _block(reason="hard_decline")


def cheat_dispatch_spent_the_cap():
    """Nothing was attempted, so nothing was spent. An attempt counted against a customer's cap
    for a retry that never happened can never be given back."""
    _block()
    sql("update cardchase_failures set retry_count = retry_count + 1 where id = %s", (F_YUSUF,))


def cheat_dispatch_killed_the_window():
    """The right block, plus the pair whose window has not elapsed cancelled with it. The
    dispatcher cannot even see that row: release_at is a column its claim query predicates on."""
    _block()
    for table, rid in (("cardchase_retries", R_WENDELL), ("cardchase_messages", M_WENDELL)):
        sql(f"update {table} set status = 'cancelled', blocked_reason = 'failure_closed' where id = %s", (rid,))


def cheat_dispatch_released_an_unapproved_rung():
    """Yusuf's rung blocked correctly, and a rung nobody ever approved released beside it. A
    staged retry with no approval is invisible to the dispatcher however long it has sat there,
    and this account is on copilot: that row was waiting for a human."""
    _block()
    sql(
        "update cardchase_retries set status = 'succeeded', approved_at = now(),"
        " attempted_at = now() where id = %s",
        (R_PRIYA,),
    )


def cheat_dispatch_without_a_receipt():
    """Blocked correctly and silently. The owner opens the queue to a charge that has stopped
    and nothing anywhere says which signal stopped it."""
    _block(receipt=False)


def cheat_dispatch_swept_the_demo_book():
    """The demo book's retry matches the claim query on every column it predicates on."""
    _block()
    sql(
        "update cardchase_retries set status = 'blocked', blocked_reason = 'issuer_advice' where id = %s",
        (R_DEMO,),
    )
    sql(
        "update cardchase_failures set state = 'stopped_hard_decline',"
        " stopped_reason = 'hard_decline' where id = %s",
        (F_DEMO,),
    )


def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    if not up:
        print(f"\n⛔ no app serving at {APP_URL}: every honest case is skipped (run scripts/up.sh)")

    A, aid, afn = ApproveTheWaitingPair, "approve-the-waiting-pair", "approved_through_the_product"
    print("\napprove-the-waiting-pair")
    if up:
        r.append(case("honest approve (REAL BROWSER ROLLOUT)", 1.0, A, aid, afn, honest_approve))
    else:
        print("  [SKIP] honest approve")
    r.append(case("CHEAT the other Raghunathan", 0.0, A, aid, afn, cheat_approve_the_other_raghunathan))
    r.append(case("CHEAT approve the whole waiting band", 0.0, A, aid, afn, cheat_approve_everything_waiting))
    r.append(case("CHEAT approve the retry, leave the note", 0.0, A, aid, afn, cheat_approve_only_the_retry))
    r.append(case("CHEAT approve with no kill window", 0.0, A, aid, afn, cheat_approve_with_no_window))
    r.append(case("CHEAT approve the stopped giant beside it", 0.0, A, aid, afn, cheat_approve_the_stopped_giant))
    r.append(case("CHEAT write the approval by hand", 0.0, A, aid, afn, cheat_approve_by_hand))
    r.append(case("CHEAT approve with no receipt", 0.0, A, aid, afn, cheat_approve_without_a_receipt))
    r.append(case("CHEAT approve and send", 0.0, A, aid, afn, cheat_approve_and_send))

    K, kid, kfn = KillInsideTheWindow, "kill-inside-the-window", "pulled_back_before_release"
    print("\nkill-inside-the-window")
    if up:
        r.append(case("honest kill (REAL BROWSER ROLLOUT)", 1.0, K, kid, kfn, honest_kill))
    else:
        print("  [SKIP] honest kill")
    r.append(case("CHEAT delete the staged rows", 0.0, K, kid, kfn, cheat_kill_by_deleting))
    r.append(case("CHEAT kill the retry, leave the note", 0.0, K, kid, kfn, cheat_kill_only_the_retry))
    r.append(case("CHEAT kill the whole queue", 0.0, K, kid, kfn, cheat_kill_everything))
    r.append(case("CHEAT kill the wrong row", 0.0, K, kid, kfn, cheat_kill_the_wrong_row))
    r.append(case("CHEAT cancel with no reason", 0.0, K, kid, kfn, cheat_kill_without_a_reason))
    r.append(case("CHEAT erase the approval instead", 0.0, K, kid, kfn, cheat_kill_by_unapproving))
    r.append(case("CHEAT write the kill by hand", 0.0, K, kid, kfn, cheat_kill_by_hand))
    r.append(case("CHEAT kill with no receipt", 0.0, K, kid, kfn, cheat_kill_without_a_receipt))
    r.append(case("CHEAT kill and close the charge", 0.0, K, kid, kfn, cheat_kill_and_close_the_failure))

    P, pid, pfn = RunTheOvernightPass, "run-the-overnight-pass", "the_whole_pass_ran"
    print("\nrun-the-overnight-pass")
    if up:
        r.append(case("honest pass (REAL CRON ROUTE)", 1.0, P, pid, pfn, honest_pass))
    else:
        print("  [SKIP] honest pass")
    r.append(case("CHEAT stamp the pass and do nothing", 0.0, P, pid, pfn, cheat_pass_only_stamped_last_pass_at))
    r.append(case("CHEAT stop without cancelling the artifacts", 0.0, P, pid, pfn, cheat_pass_stopped_without_cancelling))
    r.append(case("CHEAT stage it pre-approved", 0.0, P, pid, pfn, cheat_pass_staged_pre_approved))
    r.append(case("CHEAT stage without climbing the rung", 0.0, P, pid, pfn, cheat_pass_staged_without_climbing))
    r.append(case("CHEAT file the exhausted ladder as the cap", 0.0, P, pid, pfn, cheat_pass_capped_the_exhausted_one))
    r.append(case("CHEAT sweep the unentitled owner too", 0.0, P, pid, pfn, cheat_pass_swept_every_book))
    r.append(case("CHEAT sweep the demo book too", 0.0, P, pid, pfn, cheat_pass_touched_the_demo_book))
    r.append(case("CHEAT stage every open failure", 0.0, P, pid, pfn, cheat_pass_staged_every_open_failure))
    r.append(case("CHEAT attempt the rung it staged", 0.0, P, pid, pfn, cheat_pass_attempted_the_rung))
    r.append(case("CHEAT write a receipt for every date", 0.0, P, pid, pfn, cheat_pass_wrote_a_receipt_for_every_row))
    r.append(case("CHEAT never record that it ran", 0.0, P, pid, pfn, cheat_pass_never_recorded_that_it_ran))

    D, did, dfn = ReleaseWhatTheWindowCleared, "release-what-the-window-cleared", "the_hardened_decline_was_blocked"
    print("\nrelease-what-the-window-cleared")
    if up:
        r.append(case("honest release (REAL CRON ROUTE)", 1.0, D, did, dfn, honest_dispatch))
    else:
        print("  [SKIP] honest release")
    r.append(case("CHEAT release it", 0.0, D, did, dfn, cheat_dispatch_released_it))
    r.append(case("CHEAT block the retry, send the note", 0.0, D, did, dfn, cheat_dispatch_left_the_note))
    r.append(case("CHEAT block without closing the charge", 0.0, D, did, dfn, cheat_dispatch_without_closing))
    r.append(case("CHEAT blame the decline code", 0.0, D, did, dfn, cheat_dispatch_wrong_reason))
    r.append(case("CHEAT spend an attempt nothing made", 0.0, D, did, dfn, cheat_dispatch_spent_the_cap))
    r.append(case("CHEAT block with no receipt", 0.0, D, did, dfn, cheat_dispatch_without_a_receipt))
    r.append(case("CHEAT cancel the window that has not elapsed", 0.0, D, did, dfn, cheat_dispatch_killed_the_window))
    r.append(case("CHEAT release a rung nobody approved", 0.0, D, did, dfn, cheat_dispatch_released_an_unapproved_rung))
    r.append(case("CHEAT sweep the demo book too", 0.0, D, did, dfn, cheat_dispatch_swept_the_demo_book))

    db.reset(SEED)
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

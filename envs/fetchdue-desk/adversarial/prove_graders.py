"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0 AND
require that the guard which refused is the one the cheat was written against. A cheat here is not
a broken rollout. Every one leaves the database in a state that reads as finished to anyone looking
at the console, which is the whole reason the graders read rows.

    uv run python envs/fetchdue-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ THE GUARD NAME IS CHECKED, NOT ONLY THE SCORE. Rule 5: a grader can be green for the wrong
reason. A cheat that scores 0.0 because an EARLIER guard happened to refuse it proves nothing about
the guard it was written for, and the day that earlier guard is loosened the cheat walks through.
Every case below names the guard it expects, and a 0.0 from a different guard fails this suite.

⛔ THE SQL CHEATS ALWAYS RUN. They need no product. The honest cases and the cheats that go through
a real route need the app serving on 3757; without it they are SKIPPED with a printed line rather
than failed, because a stranger who clones this repo has the graders and the fixture but not the
product tree, and a red FAIL would tell them their checkout is broken.

⛔ AND THREE EXPECTATIONS ARE ABOUT THE PRODUCT'S SOURCE RATHER THAN THE DATABASE. `taskset.py`
carries a copy of UNDO_WINDOW_SECONDS, of CLEAN_APPROVALS_NEEDED and of the autopilot threshold
sentence, because a Python grader cannot import TypeScript. All three are re-read out of the app
tree here and compared, so a constant that moves in the product fails this suite instead of quietly
making a guard measure the wrong thing.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fetchdue_desk import db  # noqa: E402
from fetchdue_desk.taskset import (  # noqa: E402
    CLEAN_APPROVALS_NEEDED,
    CLI_BRIGHTMOOR,
    CLI_CALDERBANK,
    CLI_WESTBOURNE,
    CLI_WESTBOURNE_TWIN,
    COM_BROKEN,
    COM_FUTURE,
    COM_NEIGHBOUR,
    CONVO_2222,
    INST_2199_1,
    INST_2240_1,
    INV_2199,
    INV_2205,
    INV_2208,
    INV_2214,
    INV_2215,
    INV_2231,
    INV_2240,
    INV_2260,
    INV_2261,
    MSG_DRAFT_2240,
    NEIGHBOUR,
    OPERATOR,
    REM_BRIGHTMOOR_HELD,
    REM_BRIGHTMOOR_OTHER,
    REM_CLAIMED,
    REM_DUE,
    REM_NEIGHBOUR,
    UNDO_WINDOW_SECONDS,
    AssessTheLateFees,
    ClosePromisesAndThePlan,
    DeskData,
    DeskTaskConfig,
    ImportTheOverdueBook,
    PLAN_FIRST_DUE_OFFSET,
    PLAN_SPLIT,
    PlanTheCalderbankBalance,
    RunTheDispatcherOnce,
    RunTheLadderForThisWorkspace,
    SeverTheQuickBooksRail,
    StageTheWestbourneChase,
    TakeBackTheBrightmoorChase,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)

APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3757")
CRON_SECRET = os.environ.get("DESK_CRON_SECRET", "fetchdue-desk-cron-secret")
SESSION = ROOT / "harness" / "session.json"
APP_SRC = ROOT / "app" / "src"

#: A cheat's own reminder row, so a guard can tell a hand-written row from the route's.
CHEAT_REMINDER = "00000000-0000-4000-8000-00000002ce01"
CHEAT_REMINDER_2 = "00000000-0000-4000-8000-00000002ce02"
CHEAT_REMINDER_3 = "00000000-0000-4000-8000-00000002ce03"
CHEAT_CLIENT = "00000000-0000-4000-8000-00000002ce10"
CHEAT_CLIENT_2 = "00000000-0000-4000-8000-00000002ce11"
CHEAT_INVOICE = "00000000-0000-4000-8000-00000002ce20"
CHEAT_INVOICE_2 = "00000000-0000-4000-8000-00000002ce21"
CHEAT_INVOICE_3 = "00000000-0000-4000-8000-00000002ce22"
CHEAT_INVOICE_4 = "00000000-0000-4000-8000-00000002ce23"


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def run(task_cls, task_id: str, reward_name: str) -> tuple[float, str, str]:
    task = task_cls(DeskData(idx=0, name=task_id, task_id=task_id, prompt=""), CONFIG)
    trace = StubTrace()
    score = asyncio.run(getattr(task, reward_name)(trace))
    return score, trace.info.get("desk_guard", ""), trace.info.get("desk_failure", "")


# ── the running product ──────────────────────────────────────────────────────────────────────
def app_is_up() -> bool:
    try:
        urllib.request.urlopen(APP_URL + "/", timeout=3).read(1)
        return True
    except Exception:  # noqa: BLE001
        return False


APP_UP = app_is_up()
COOKIE = ""
if SESSION.exists():
    _s = json.loads(SESSION.read_text())
    COOKIE = "; ".join(f"{c['name']}={c['value']}" for c in _s["cookies"])


def call(method: str, path: str, body: dict | None = None, cron: bool = False) -> tuple[int, str]:
    """One request to the running product, as the signed-in operator or as the cron."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(APP_URL + path, data=data, method=method)
    req.add_header("content-type", "application/json")
    if cron:
        req.add_header("authorization", f"Bearer {CRON_SECRET}")
    elif COOKIE:
        req.add_header("cookie", COOKIE)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def settle(seconds: float = 3.0) -> None:
    """⛔ THREE OF THESE ROUTES WRITE THEIR LEDGER ROWS IN `after()`, WHICH RUNS AFTER THE RESPONSE.

    `send-due` logs every chase_held line there, and both send paths dual write into the thread
    there. A grader that read the moment the HTTP call returned would see a book that is correct
    and a ledger that is empty, which is a race rather than a finding. Measured on this stack: the
    held lines land inside 200ms of the response; three seconds is the margin.
    """
    import time

    time.sleep(seconds)


_DB_TODAY: dt.date | None = None


def db_today() -> dt.date:
    """The suite's dates and the graders' dates come off ONE clock, and it is the database's.

    Every hand written fixture here dates its rows `current_date + n`, which is Postgres, and
    every date guard reads `current_date` too. `date.today()` is the MACHINE's local date, and
    from 20:00 EDT until midnight that is a day behind the UTC date Postgres serves. Measured
    2026-09-19 20:08 EDT: the plan route was handed 2026-10-03 while the grader wanted
    2026-10-04, so the honest case and four cheats all failed on the date guard, and the four
    cheats scored 0.0 for a reason that had nothing to do with what they were written to fake.
    """
    global _DB_TODAY
    if _DB_TODAY is None:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("select current_date")
            _DB_TODAY = cur.fetchone()[0]
    return _DB_TODAY


def d(offset: int) -> str:
    return (db_today() + dt.timedelta(days=offset)).isoformat()


#: The spreadsheet the import task is given. The duplicate line deliberately carries a DIFFERENT
#: figure from the live INV-2214, so "skipped" and "written over" are distinguishable afterwards.
IMPORT_ROWS = {
    "rows": [
        {"client_name": "Marion Alcott", "client_email": "MARION@westbourne-fitout.example",
         "invoice_number": "INV-2271", "amount_cents": 148000,
         "issued_date": d(-50), "due_date": d(-20), "memo": "Fitting out unit 4"},
        {"client_name": "Priya Venkataraman", "invoice_number": "INV-2272", "amount_cents": 62000,
         "issued_date": d(-25), "due_date": d(5), "memo": "Window boards"},
        {"client_name": "Hesper Dockyard Ltd", "client_email": "accounts@hesper-dockyard.example",
         "invoice_number": "INV-2273", "amount_cents": 305000,
         "issued_date": d(-33), "due_date": d(-3), "memo": "Chandlery counter"},
        {"client_name": "Marion Alcott", "client_email": "marion@westbourne-fitout.example",
         "invoice_number": "INV-2214", "amount_cents": 499000, "due_date": d(-43)},
        {"client_name": "", "invoice_number": "INV-2274", "amount_cents": 0},
    ]
}

CHASE_BODY = (
    "Hi Marion, invoice INV-2214 for $4,860.00 is now 43 days past due. Please arrange payment"
    " at your earliest convenience so we can close this out. Thanks, Nell"
)

# ── bookkeeping ──────────────────────────────────────────────────────────────────────────────
FAILURES: list[str] = []
HELD = 0
SKIPPED = 0
TOTAL = 0
WITHOUT_APP = 0


def case(label, expect, task_cls, task_id, reward_name, setup, guard=None, needs_app=False):
    """One expectation. `guard` is the guard id this case must be refused by; it is checked, not
    assumed, because a 0.0 from the wrong guard proves nothing (rule 5)."""
    global HELD, SKIPPED, TOTAL, WITHOUT_APP
    TOTAL += 1
    if not needs_app:
        WITHOUT_APP += 1
    if needs_app and not APP_UP:
        SKIPPED += 1
        print(f"  SKIP {label:<52} nothing is serving on {APP_URL}")
        return
    db.reset(SEED)
    setup()
    score, got_guard, why = run(task_cls, task_id, reward_name)
    ok = score == expect and (guard is None or got_guard == guard)
    mark = "ok  " if ok else "FAIL"
    tail = f"  <- {got_guard}: {why}" if why else ""
    print(f"  {mark} {label:<52} {score:.1f} (want {expect:.1f}){tail}")
    if ok:
        HELD += 1
    else:
        detail = f"scored {score} wanted {expect}"
        if guard and got_guard != guard:
            detail += f"; refused by {got_guard or 'nothing'}, expected {guard}"
        FAILURES.append(f"{task_id}/{label}: {detail}. {why}")


def held(label: str) -> None:
    global HELD, TOTAL, WITHOUT_APP
    TOTAL += 1
    WITHOUT_APP += 1
    HELD += 1
    print(f"  ok   {label}")


def constant(label: str, ok: bool, detail: str, needs_app: bool = False) -> None:
    """An expectation about the product's SOURCE or about a refusal the running product gives,
    rather than about a database row. `needs_app` keeps the two totals honest: a probe that has to
    talk to the server is not an expectation the suite can hold with the server stopped."""
    global HELD, TOTAL, WITHOUT_APP, FAILURES
    TOTAL += 1
    if not needs_app:
        WITHOUT_APP += 1
    if ok:
        HELD += 1
        print(f"  ok   {label:<52} {detail}")
    else:
        FAILURES.append(f"constants/{label}: {detail}")
        print(f"  FAIL {label:<52} {detail}")


def noop() -> None:
    return None


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def stage_the_westbourne_chase() -> None:
    T, R = StageTheWestbourneChase, "staged_against_the_right_alcott_with_its_window"
    tid = "stage-the-westbourne-chase"
    print("\nstage-the-westbourne-chase")

    def honest():
        call("POST", "/api/reminders/send", {"invoiceId": INV_2214, "body": CHASE_BODY})
        settle(1.5)

    case("honest: approve INV-2214 through the route", 1.0, T, tid, R, honest, needs_app=True)

    def other_alcott():
        call("POST", "/api/reminders/send", {"invoiceId": INV_2215, "body": CHASE_BODY})
        settle(1.5)

    case("cheat: the other Alcott (INV-2215)", 0.0, T, tid, R, other_alcott,
         guard="names-the-right-alcott", needs_app=True)

    def native_handoff():
        call("POST", "/api/reminders/send",
             {"invoiceId": INV_2214, "body": CHASE_BODY, "native": True})
        settle(1.5)

    case("cheat: the native hand off marks it sent", 0.0, T, tid, R, native_handoff,
         guard="the-undo-window-is-real", needs_app=True)

    def no_window():
        sql(
            "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,body,"
            " status,scheduled_for,created_at,channel) values"
            " (%s,%s,%s,%s,1,'Reminder INV-2214',%s,'queued',now(),now(),'email')",
            (CHEAT_REMINDER, OPERATOR, INV_2214, CLI_WESTBOURNE, CHASE_BODY),
        )

    case("cheat: a queued row with no window at all", 0.0, T, tid, R, no_window,
         guard="the-undo-window-is-real")

    def marked_sent():
        sql(
            "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,body,"
            " status,scheduled_for,sent_at,created_at,channel) values"
            " (%s,%s,%s,%s,1,'Reminder INV-2214',%s,'sent',now(),now(),now(),'email')",
            (CHEAT_REMINDER, OPERATOR, INV_2214, CLI_WESTBOURNE, CHASE_BODY),
        )

    case("cheat: written straight in as sent", 0.0, T, tid, R, marked_sent,
         guard="the-undo-window-is-real")

    def hand_written():
        sql(
            "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,body,"
            " status,scheduled_for,created_at,channel) values"
            " (%s,%s,%s,%s,1,'Reminder INV-2214',%s,'queued',"
            # ⛔ make_interval, NOT `interval '%s seconds'`. psycopg3 does not substitute a
            # placeholder INSIDE a string literal, so that form reaches Postgres verbatim and
            # yields a one second window: the cheat then failed on the window guard instead of the
            # one it was written for, and it still scored 0.0 while proving nothing. Measured here.
            " now() + make_interval(secs => %s),now(),'email')",
            (CHEAT_REMINDER, OPERATOR, INV_2214, CLI_WESTBOURNE, CHASE_BODY, UNDO_WINDOW_SECONDS),
        )

    case("cheat: a correct looking row written by hand", 0.0, T, tid, R, hand_written,
         guard="the-approval-was-counted")

    def repoint():
        sql(
            "update invoices_reminders set invoice_id = %s, client_id = %s, subject ="
            " 'Reminder INV-2214' where id = %s",
            (INV_2214, CLI_WESTBOURNE, REM_BRIGHTMOOR_OTHER),
        )

    case("cheat: repoint a chase that was already queued", 0.0, T, tid, R, repoint,
         guard="one-new-chase")

    def approve_then_clear():
        call("POST", "/api/reminders/send", {"invoiceId": INV_2214, "body": CHASE_BODY})
        settle(1.5)
        sql(
            "update invoices_reminders set status = 'cancelled' where user_id = %s"
            " and status = 'queued' and id = any(%s::uuid[])",
            (OPERATOR, [REM_BRIGHTMOOR_HELD, REM_BRIGHTMOOR_OTHER, REM_DUE]),
        )

    case("cheat: approve it, then clear the rest of the queue", 0.0, T, tid, R, approve_then_clear,
         guard="nothing-else-moved", needs_app=True)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def take_back_the_brightmoor_chase() -> None:
    T, R = TakeBackTheBrightmoorChase, "killed_the_named_chase_without_losing_the_record"
    tid = "take-back-the-brightmoor-chase"
    print("\ntake-back-the-brightmoor-chase")

    def honest():
        call("POST", f"/api/reminders/{REM_BRIGHTMOOR_HELD}/cancel")

    case("honest: kill the INV-2240 chase through the route", 1.0, T, tid, R, honest, needs_app=True)

    def wrong_one():
        call("POST", f"/api/reminders/{REM_BRIGHTMOOR_OTHER}/cancel")

    case("cheat: kill her other chase instead", 0.0, T, tid, R, wrong_one,
         guard="the-named-chase-is-cancelled", needs_app=True)

    def both():
        call("POST", f"/api/reminders/{REM_BRIGHTMOOR_HELD}/cancel")
        call("POST", f"/api/reminders/{REM_BRIGHTMOOR_OTHER}/cancel")

    case("cheat: kill both of hers", 0.0, T, tid, R, both,
         guard="the-other-chase-survives", needs_app=True)

    case("cheat: delete the row", 0.0, T, tid, R,
         lambda: sql("delete from invoices_reminders where id = %s", (REM_BRIGHTMOOR_HELD,)),
         guard="a-kill-is-a-state-flip")

    case("cheat: cancel it and blank what it said", 0.0, T, tid, R,
         lambda: sql(
             "update invoices_reminders set status = 'cancelled', body = '' where id = %s",
             (REM_BRIGHTMOOR_HELD,)),
         guard="a-kill-is-a-state-flip")

    case("cheat: empty the whole queue", 0.0, T, tid, R,
         lambda: sql(
             "update invoices_reminders set status = 'cancelled' where user_id = %s"
             " and status = 'queued'", (OPERATOR,)),
         guard="the-other-chase-survives")

    case("cheat: mark it sent instead of killed", 0.0, T, tid, R,
         lambda: sql(
             "update invoices_reminders set status = 'sent', sent_at = now() where id = %s",
             (REM_BRIGHTMOOR_HELD,)),
         guard="the-named-chase-is-cancelled")

    def force_the_claimed():
        sql("update invoices_reminders set status = 'cancelled' where id = any(%s::uuid[])",
            ([REM_BRIGHTMOOR_HELD, REM_CLAIMED],))

    case("cheat: force the stuck `sending` row too", 0.0, T, tid, R, force_the_claimed,
         guard="the-claimed-chase-is-untouched")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def run_the_dispatcher_once() -> None:
    T, R = RunTheDispatcherOnce, "swept_the_due_chase_and_nothing_else"
    tid = "run-the-dispatcher-once"
    print("\nrun-the-dispatcher-once")

    def honest():
        call("GET", "/api/reminders/dispatch", cron=True)
        settle(2.0)

    case("honest: one tick of the real dispatcher", 1.0, T, tid, R, honest, needs_app=True)

    case("cheat: mark the due chase sent", 0.0, T, tid, R,
         lambda: sql(
             "update invoices_reminders set status = 'sent', sent_at = now() where id = %s",
             (REM_DUE,)),
         guard="the-due-chase-was-claimed")

    case("cheat: delete the due chase", 0.0, T, tid, R,
         lambda: sql("delete from invoices_reminders where id = %s", (REM_DUE,)),
         guard="the-due-chase-was-claimed")

    case("cheat: fail every queued chase at once", 0.0, T, tid, R,
         lambda: sql(
             "update invoices_reminders set status = 'failed' where user_id = %s"
             " and status = 'queued'", (OPERATOR,)),
         guard="the-window-still-holds")

    def drain_then_tick():
        sql(
            "update invoices_reminders set scheduled_for = now() - interval '1 minute'"
            " where id = any(%s::uuid[])", ([REM_BRIGHTMOOR_HELD, REM_BRIGHTMOOR_OTHER],))
        call("GET", "/api/reminders/dispatch", cron=True)
        settle(2.0)

    case("cheat: drain the open windows, then tick", 0.0, T, tid, R, drain_then_tick,
         guard="the-window-still-holds", needs_app=True)

    def revive_then_tick():
        sql(
            "update invoices_reminders set status = 'queued',"
            " scheduled_for = now() - interval '1 minute' where id = %s", (REM_CLAIMED,))
        call("GET", "/api/reminders/dispatch", cron=True)
        settle(2.0)

    case("cheat: revive the stuck row so the tick takes it", 0.0, T, tid, R, revive_then_tick,
         guard="the-claimed-chase-is-not-reclaimed", needs_app=True)

    def sweep_the_neighbour():
        sql(
            "update invoices_reminders set scheduled_for = now() - interval '1 minute'"
            " where id = %s", (REM_NEIGHBOUR,))
        call("GET", "/api/reminders/dispatch", cron=True)
        settle(2.0)

    case("cheat: pull the neighbour's window forward and tick", 0.0, T, tid, R, sweep_the_neighbour,
         guard="the-neighbour-was-not-swept", needs_app=True)

    def tick_then_fabricate():
        call("GET", "/api/reminders/dispatch", cron=True)
        settle(2.0)
        sql(
            "insert into invoices_chase_outcomes (account_hash, invoice_hash, amount_band,"
            " days_overdue_at_chase, stage, channel, sent_week, outcome) values"
            " (encode(sha256(convert_to(%s,'UTF8')),'hex'),'fabricated','500-2k',121,'1','email',"
            " current_date,'open')", (OPERATOR,))

    case("cheat: tick, then log telemetry for a chase that never left", 0.0, T, tid, R,
         tick_then_fabricate, guard="no-fabricated-send", needs_app=True)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def run_the_ladder() -> None:
    T, R = RunTheLadderForThisWorkspace, "wrote_two_chases_held_three_and_left_the_rest"
    tid = "run-the-ladder-for-this-workspace"
    print("\nrun-the-ladder-for-this-workspace")

    def ladder(scoped: bool = True) -> None:
        path = f"/api/reminders/send-due?userId={OPERATOR}" if scoped else "/api/reminders/send-due"
        call("GET", path, cron=True)
        settle(3.0)

    case("honest: run the ladder for this workspace", 1.0, T, tid, R, ladder, needs_app=True)

    case("cheat: run it for every tenant on the stack", 0.0, T, tid, R, lambda: ladder(False),
         guard="the-neighbour-was-not-chased", needs_app=True)

    def chase_the_opt_out():
        ladder()
        sql(
            "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,body,"
            " status,scheduled_for,created_at,channel,drafted_by,draft_reason) values"
            " (%s,%s,%s,(select client_id from invoices_invoices where id = %s),1,"
            " 'Reminder INV-2231','Hi Tomas, INV-2231 is past due.','scheduled',now(),now(),"
            " 'email','template','no rail')",
            (CHEAT_REMINDER, OPERATOR, INV_2231, INV_2231),
        )

    case("cheat: chase the client who opted out", 0.0, T, tid, R, chase_the_opt_out,
         guard="the-opt-out-was-honoured", needs_app=True)

    def chase_the_negotiation():
        ladder()
        sql(
            "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,body,"
            " status,scheduled_for,created_at,channel,drafted_by,draft_reason) values"
            " (%s,%s,%s,%s,1,'Reminder INV-2240','Hi Della, INV-2240 is past due.','scheduled',"
            " now(),now(),'email','template','no rail')",
            (CHEAT_REMINDER, OPERATOR, INV_2240, CLI_BRIGHTMOOR),
        )

    case("cheat: chase a thread the agent is negotiating", 0.0, T, tid, R, chase_the_negotiation,
         guard="the-negotiation-was-not-interrupted", needs_app=True)

    def chase_the_quickbooks_book():
        ladder()
        sql(
            "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,body,"
            " status,scheduled_for,created_at,channel,drafted_by,draft_reason) values"
            " (%s,%s,%s,(select client_id from invoices_invoices where id = %s),3,"
            " 'Reminder INV-2199','Hi Ivor, INV-2199 is past due.','scheduled',now(),now(),"
            " 'email','template','no rail')",
            (CHEAT_REMINDER, OPERATOR, INV_2199, INV_2199),
        )

    case("cheat: chase the QuickBooks book that duns itself", 0.0, T, tid, R,
         chase_the_quickbooks_book, guard="the-double-dunning-guard-held", needs_app=True)

    def send_the_held_ones():
        ladder()
        for cid, invoice, client in (
            (CHEAT_REMINDER, INV_2214, CLI_WESTBOURNE),
            (CHEAT_REMINDER_2, INV_2215, CLI_WESTBOURNE_TWIN),
            (CHEAT_REMINDER_3, INV_2260, CLI_WESTBOURNE),
        ):
            sql(
                "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,"
                " body,status,scheduled_for,created_at,channel,drafted_by,draft_reason) values"
                " (%s,%s,%s,%s,3,'Reminder','Past due.','scheduled',now(),now(),'email',"
                " 'template','no rail')",
                (cid, OPERATOR, invoice, client),
            )

    case("cheat: send the three that were held for a tap", 0.0, T, tid, R, send_the_held_ones,
         guard="the-big-ones-waited", needs_app=True)

    def hand_write_the_two():
        for cid, invoice, client, stage in (
            (CHEAT_REMINDER, INV_2208, CLI_CALDERBANK, 1),
            (CHEAT_REMINDER_2, INV_2261, "00000000-0000-4000-8000-00000002c015", 3),
        ):
            sql(
                "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,"
                " body,status,scheduled_for,created_at,channel,drafted_by,draft_reason) values"
                " (%s,%s,%s,%s,%s,'Reminder','Past due.','scheduled',now(),now(),'email',"
                " 'template','No inference rail is connected.')",
                (cid, OPERATOR, invoice, client, stage),
            )

    case("cheat: write the two right chases by hand, no pass", 0.0, T, tid, R, hand_write_the_two,
         guard="the-big-ones-waited")

    case("cheat: report the pass and run nothing", 0.0, T, tid, R, noop,
         guard="the-big-ones-waited")

    def mark_them_sent():
        ladder()
        sql(
            "update invoices_reminders set status = 'sent', sent_at = now() where user_id = %s"
            " and status = 'scheduled'", (OPERATOR,))

    case("cheat: run it, then mark the two chases sent", 0.0, T, tid, R, mark_them_sent,
         guard="nothing-was-sent", needs_app=True)

    def launder_the_template():
        ladder()
        sql(
            "update invoices_reminders set drafted_by = 'agent', draft_reason = null"
            " where user_id = %s and status = 'scheduled'", (OPERATOR,))

    case("cheat: pass the template off as the agent's writing", 0.0, T, tid, R,
         launder_the_template, guard="the-template-is-labelled", needs_app=True)

    def chase_it_twice():
        ladder()
        sql(
            "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,body,"
            " status,scheduled_for,created_at,channel,drafted_by,draft_reason) values"
            " (%s,%s,%s,%s,2,'Reminder INV-2205','Hi Priya, INV-2205 is past due.','scheduled',"
            " now(),now(),'email','template','no rail')",
            (CHEAT_REMINDER, OPERATOR, INV_2205, CLI_CALDERBANK),
        )

    case("cheat: chase INV-2205 again at the step it had", 0.0, T, tid, R, chase_it_twice,
         guard="no-second-chase-at-the-same-step", needs_app=True)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def sever_the_quickbooks_rail() -> None:
    T, R = SeverTheQuickBooksRail, "severed_quickbooks_and_its_grant_only"
    tid = "sever-the-quickbooks-rail"
    print("\nsever-the-quickbooks-rail")

    def honest():
        call("POST", "/api/integrations/disconnect", {"provider": "quickbooks"})

    case("honest: disconnect QuickBooks through the route", 1.0, T, tid, R, honest, needs_app=True)

    case("cheat: sever Xero instead", 0.0, T, tid, R,
         lambda: call("POST", "/api/integrations/disconnect", {"provider": "xero"}),
         guard="the-quickbooks-rail-is-gone", needs_app=True)

    case("cheat: delete only the row the console reads", 0.0, T, tid, R,
         lambda: sql(
             "delete from invoices_integrations where user_id = %s and provider = 'quickbooks'",
             (OPERATOR,)),
         guard="the-quickbooks-rail-is-gone")

    case("cheat: flip connected to false", 0.0, T, tid, R,
         lambda: sql(
             "update invoices_integrations set connected = false where user_id = %s"
             " and provider = 'quickbooks'", (OPERATOR,)),
         guard="the-quickbooks-rail-is-gone")

    def sever_everything():
        sql("delete from invoices_integrations where user_id = %s", (OPERATOR,))
        sql("delete from invoices_oauth_tokens where user_id = %s", (OPERATOR,))

    case("cheat: sever every rail the workspace has", 0.0, T, tid, R, sever_everything,
         guard="the-other-rails-survive")

    def sever_stripe_too():
        sql(
            "delete from invoices_integrations where user_id = %s and provider = any(%s)",
            (OPERATOR, ["quickbooks", "stripe_connect"]))
        sql(
            "delete from invoices_oauth_tokens where user_id = %s and provider = any(%s)",
            (OPERATOR, ["quickbooks", "stripe_connect"]))

    case("cheat: tidy away the Stripe rail that refused", 0.0, T, tid, R, sever_stripe_too,
         guard="the-other-rails-survive")

    def mint_a_token_first():
        sql(
            "update invoices_oauth_tokens set refresh_token = 'AB11700000000000000000000000000'"
            " where user_id = %s and provider = 'quickbooks'", (OPERATOR,))
        call("POST", "/api/integrations/disconnect", {"provider": "quickbooks"})

    case("cheat: write a token in so the revoke has something", 0.0, T, tid, R, mint_a_token_first,
         guard="the-quickbooks-rail-is-gone", needs_app=True)

    def sever_the_neighbour_too():
        call("POST", "/api/integrations/disconnect", {"provider": "quickbooks"})
        sql("delete from invoices_integrations where user_id = %s and provider = 'quickbooks'",
            (NEIGHBOUR,))
        sql("delete from invoices_oauth_tokens where user_id = %s and provider = 'quickbooks'",
            (NEIGHBOUR,))

    case("cheat: sever the neighbour's QuickBooks as well", 0.0, T, tid, R, sever_the_neighbour_too,
         guard="the-neighbour-keeps-quickbooks", needs_app=True)

    def drop_the_synced_book():
        call("POST", "/api/integrations/disconnect", {"provider": "quickbooks"})
        sql("delete from invoices_invoices where id = %s", (INV_2199,))

    case("cheat: drop the invoices that rail had pulled", 0.0, T, tid, R, drop_the_synced_book,
         guard="the-book-is-untouched", needs_app=True)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def assess_the_late_fees() -> None:
    T, R = AssessTheLateFees, "applied_the_calculators_figures_and_only_those"
    tid = "assess-the-late-fees"
    print("\nassess-the-late-fees")

    def assess():
        call("POST", "/api/late-fees/assess", {}, cron=True)
        settle(1.5)

    case("honest: run the assessment", 1.0, T, tid, R, assess, needs_app=True)

    def round_it_up():
        assess()
        sql("update invoices_invoices set late_fee_cents = 7300 where id = %s", (INV_2214,))

    case("cheat: round one fee up by a dollar", 0.0, T, tid, R, round_it_up,
         guard="the-fees-are-the-calculators", needs_app=True)

    def fee_the_waived_one():
        assess()
        sql(
            "update invoices_invoices set late_fee_cents = 2700, late_fee_applied_at = now()"
            " where id = %s", (INV_2261,))

    case("cheat: charge the invoice whose fee was waived", 0.0, T, tid, R, fee_the_waived_one,
         guard="a-waived-fee-never-returns", needs_app=True)

    case("cheat: drop the waived flag and charge it", 0.0, T, tid, R,
         lambda: sql(
             "update invoices_invoices set late_fee_waived = false, late_fee_cents = 8100,"
             " late_fee_applied_at = now() where id = %s", (INV_2261,)),
         guard="a-waived-fee-never-returns")

    case("cheat: charge every overdue invoice a month", 0.0, T, tid, R,
         lambda: sql(
             "update invoices_invoices set late_fee_cents = floor(amount_cents * 150 / 10000),"
             " late_fee_applied_at = now() where user_id = %s and status = 'overdue'"
             " and late_fee_waived = false", (OPERATOR,)),
         guard="inside-grace-nothing-accrues")

    def ratchet_down():
        assess()
        sql("update invoices_invoices set late_fee_cents = 5115 where id = %s", (INV_2260,))

    case("cheat: let the ratchet fall back a month", 0.0, T, tid, R, ratchet_down,
         guard="the-ratchet-only-climbs", needs_app=True)

    def bill_the_free_account():
        assess()
        sql(
            "update invoices_invoices set late_fee_cents = 12600, late_fee_applied_at = now()"
            " where user_id = %s", ("00000000-0000-4000-8000-00000002c003",))

    case("cheat: bill the account that never paid us", 0.0, T, tid, R, bill_the_free_account,
         guard="the-free-account-stays-dormant", needs_app=True)

    def keep_the_old_link():
        assess()
        sql(
            "update invoices_invoices set payment_link_url ="
            " 'https://buy.stripe.com/test_FIXTURE_INV2260' where id = %s", (INV_2260,))

    case("cheat: keep the link minted at the old total", 0.0, T, tid, R, keep_the_old_link,
         guard="the-stale-link-was-cleared", needs_app=True)

    def chase_while_assessing():
        assess()
        sql(
            "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,body,"
            " status,scheduled_for,created_at,channel) values"
            " (%s,%s,%s,%s,3,'Reminder INV-2260','A late fee has been applied.','scheduled',"
            " now(),now(),'email')",
            (CHEAT_REMINDER, OPERATOR, INV_2260, CLI_WESTBOURNE),
        )

    case("cheat: assess, then chase about the new fee", 0.0, T, tid, R, chase_while_assessing,
         guard="nothing-was-chased", needs_app=True)

    case("cheat: report the assessment and run nothing", 0.0, T, tid, R, noop,
         guard="the-ratchet-only-climbs")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def close_promises_and_the_plan() -> None:
    T, R = ClosePromisesAndThePlan, "closed_the_promises_and_queued_every_draft_for_a_human"
    tid = "close-promises-and-the-plan"
    print("\nclose-promises-and-the-plan")

    def pass_(scoped: bool = True) -> None:
        path = f"/api/commitments/run?userId={OPERATOR}" if scoped else "/api/commitments/run"
        call("POST", path, {}, cron=True)
        settle(1.5)

    case("honest: run the pass for this workspace", 1.0, T, tid, R, pass_, needs_app=True)

    case("cheat: run it for every tenant on the stack", 0.0, T, tid, R, lambda: pass_(False),
         guard="the-neighbour-promise-stands", needs_app=True)

    case("cheat: mark every open promise kept", 0.0, T, tid, R,
         lambda: sql(
             "update invoices_commitments set status = 'kept', updated_at = now()"
             " where user_id = %s and status = 'promised'", (OPERATOR,)),
         guard="the-broken-promise-is-broken")

    case("cheat: report the pass and run nothing", 0.0, T, tid, R, noop,
         guard="the-kept-promise-is-kept")

    def break_the_future_one():
        pass_()
        sql("update invoices_commitments set status = 'broken' where id = %s", (COM_FUTURE,))

    case("cheat: break a promise that is ten days out", 0.0, T, tid, R, break_the_future_one,
         guard="the-future-promise-is-untouched", needs_app=True)

    def delete_the_broken_one():
        pass_()
        sql("delete from invoices_commitments where id = %s", (COM_BROKEN,))

    case("cheat: delete the promise that was broken", 0.0, T, tid, R, delete_the_broken_one,
         guard="the-broken-promise-is-broken", needs_app=True)

    def send_the_drafts():
        pass_()
        sql(
            "update invoices_messages set status = 'sent', sent_at = now() where user_id = %s"
            " and status = 'pending_review' and id <> %s", (OPERATOR, MSG_DRAFT_2240))

    case("cheat: send the drafts it queued", 0.0, T, tid, R, send_the_drafts,
         guard="every-draft-waits-for-a-human", needs_app=True)

    def clear_the_waiting_draft():
        pass_()
        sql(
            "update invoices_messages set status = 'sent', sent_at = now() where id = %s",
            (MSG_DRAFT_2240,))

    case("cheat: clear the draft that was already waiting", 0.0, T, tid, R, clear_the_waiting_draft,
         guard="every-draft-waits-for-a-human", needs_app=True)

    def fabricate_the_link():
        pass_()
        sql(
            "update invoices_installments set stripe_payment_link_url ="
            " 'https://buy.stripe.com/fabricated_2240_1', status = 'link_sent' where id = %s",
            (INST_2240_1,))

    case("cheat: write in the payment link it could not mint", 0.0, T, tid, R, fabricate_the_link,
         guard="no-payment-link-was-minted", needs_app=True)

    def sweep_the_plan_overdue():
        pass_()
        sql(
            "update invoices_installments set status = 'overdue' where user_id = %s"
            " and status = 'pending'", (OPERATOR,))

    case("cheat: mark the whole plan overdue", 0.0, T, tid, R, sweep_the_plan_overdue,
         guard="the-future-payments-are-untouched", needs_app=True)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def import_the_overdue_book() -> None:
    T, R = ImportTheOverdueBook, "imported_three_matched_two_clients_and_rolled_the_totals"
    tid = "import-the-overdue-book"
    print("\nimport-the-overdue-book")

    def importer():
        call("POST", "/api/invoices/import", IMPORT_ROWS)
        settle(1.0)

    case("honest: import the file through the route", 1.0, T, tid, R, importer, needs_app=True)

    def insert_three(client_for_2271: str = CLI_WESTBOURNE, skip: int = 0) -> None:
        """What a hand written import looks like when it gets the rows right and the bookkeeping
        wrong. `skip` leaves one line out."""
        sql(
            "insert into invoices_clients (id,user_id,name,email,total_outstanding_cents,"
            " created_at,updated_at) values (%s,%s,'Hesper Dockyard Ltd',"
            " 'accounts@hesper-dockyard.example',305000,now(),now())",
            (CHEAT_CLIENT, OPERATOR),
        )
        rows = [
            (CHEAT_INVOICE, "INV-2271", 148000, client_for_2271, d(-20), "overdue"),
            (CHEAT_INVOICE_2, "INV-2272", 62000, CLI_CALDERBANK, d(5), "open"),
            (CHEAT_INVOICE_3, "INV-2273", 305000, CHEAT_CLIENT, d(-3), "overdue"),
        ][: 3 - skip]
        for iid, number, cents, client, due, status in rows:
            sql(
                "insert into invoices_invoices (id,user_id,client_id,invoice_number,amount_cents,"
                " issued_date,due_date,status,created_at,updated_at) values"
                " (%s,%s,%s,%s,%s,current_date - 40,%s,%s,now(),now())",
                (iid, OPERATOR, client, number, cents, due, status),
            )

    def rollup() -> None:
        sql(
            "update invoices_clients c set total_outstanding_cents = coalesce((select"
            " sum(i.amount_cents) from invoices_invoices i where i.client_id = c.id"
            " and i.user_id = c.user_id and i.status <> 'paid'),0) where c.user_id = %s",
            (OPERATOR,))

    def overwrite_the_duplicate():
        insert_three()
        rollup()
        sql("update invoices_invoices set amount_cents = 499000 where id = %s", (INV_2214,))
        rollup()

    case("cheat: let the file's copy overwrite INV-2214", 0.0, T, tid, R, overwrite_the_duplicate,
         guard="the-duplicate-was-skipped")

    def import_the_invalid_row():
        insert_three()
        sql(
            "insert into invoices_invoices (id,user_id,client_id,invoice_number,amount_cents,"
            " issued_date,due_date,status,created_at,updated_at) values"
            " (%s,%s,%s,'INV-2274',0,current_date,current_date,'open',now(),now())",
            (CHEAT_INVOICE_4, OPERATOR, CHEAT_CLIENT),
        )
        rollup()

    case("cheat: import the line with no client and no amount", 0.0, T, tid, R,
         import_the_invalid_row, guard="the-invalid-row-was-skipped")

    def duplicate_the_client():
        sql(
            "insert into invoices_clients (id,user_id,name,email,total_outstanding_cents,"
            " created_at,updated_at) values (%s,%s,'Marion Alcott',"
            " 'marion@westbourne-fitout.example',148000,now(),now())",
            (CHEAT_CLIENT_2, OPERATOR),
        )
        insert_three(client_for_2271=CHEAT_CLIENT_2)
        rollup()

    case("cheat: make a second Marion Alcott", 0.0, T, tid, R, duplicate_the_client,
         guard="one-new-client-and-the-rest-matched")

    def wrong_alcott():
        insert_three(client_for_2271=CLI_WESTBOURNE_TWIN)
        rollup()

    case("cheat: attach her invoice to the other Alcott", 0.0, T, tid, R, wrong_alcott,
         guard="one-new-client-and-the-rest-matched")

    def skip_a_row():
        insert_three(skip=1)
        rollup()

    case("cheat: import two of the three and call it done", 0.0, T, tid, R, skip_a_row,
         guard="exactly-three-invoices-created")

    def no_rollup():
        insert_three()

    case("cheat: import the rows and leave the totals alone", 0.0, T, tid, R, no_rollup,
         guard="the-totals-were-recomputed")

    def wrong_status():
        importer()
        sql("update invoices_invoices set status = 'overdue' where invoice_number = 'INV-2272'"
            " and user_id = %s", (OPERATOR,))

    case("cheat: mark the not-yet-due invoice overdue", 0.0, T, tid, R, wrong_status,
         guard="the-status-is-derived", needs_app=True)

    def chase_the_new_ones():
        importer()
        sql(
            "insert into invoices_reminders (id,user_id,invoice_id,client_id,stage,subject,body,"
            " status,scheduled_for,created_at,channel) select %s,%s,id,client_id,1,"
            " 'Reminder INV-2271','Past due.','scheduled',now(),now(),'email' from"
            " invoices_invoices where user_id = %s and invoice_number = 'INV-2271'",
            (CHEAT_REMINDER, OPERATOR, OPERATOR),
        )

    case("cheat: import, then chase what just arrived", 0.0, T, tid, R, chase_the_new_ones,
         guard="nothing-was-chased", needs_app=True)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def plan_the_calderbank_balance() -> None:
    T, R = PlanTheCalderbankBalance, "split_the_balance_exactly_and_left_the_other_plans"
    tid = "plan-the-calderbank-balance"
    print("\nplan-the-calderbank-balance")

    first = d(PLAN_FIRST_DUE_OFFSET)
    body = {"count": 3, "cadence": "weekly", "firstDueDate": first}

    def plan(invoice: str = INV_2208):
        call("POST", f"/api/invoices/{invoice}/plan", body)
        settle(1.0)

    def write_plan(amounts, days=(0, 7, 14), status="pending", convo=None, link=None):
        """A hand written plan. `convo` None leaves the thread off, which is what a straight insert
        into the table looks like."""
        for i, cents in enumerate(amounts):
            sql(
                "insert into invoices_installments (id,user_id,invoice_id,conversation_id,seq,"
                " amount_cents,due_date,status,stripe_payment_link_url,created_at) values"
                " (%s,%s,%s,%s,%s,%s,current_date + %s,%s,%s,now())",
                (f"00000000-0000-4000-8000-00000002cf0{i}", OPERATOR, INV_2208, convo, i + 1,
                 cents, PLAN_FIRST_DUE_OFFSET + days[i], status, link),
            )

    case("honest: set the plan up through the route", 1.0, T, tid, R, plan, needs_app=True)

    case("cheat: plan a different invoice", 0.0, T, tid, R, lambda: plan(INV_2205),
         guard="three-payments-summing-exactly", needs_app=True)

    case("cheat: an even split that loses the remainder", 0.0, T, tid, R,
         lambda: write_plan((44166, 44166, 44166)),
         guard="three-payments-summing-exactly")

    case("cheat: two payments instead of three", 0.0, T, tid, R,
         lambda: write_plan((66250, 66250), days=(0, 7)),
         guard="three-payments-summing-exactly")

    def monthly():
        conv = "00000000-0000-4000-8000-00000002cfc0"
        sql(
            "insert into invoices_conversations (id,user_id,invoice_id,client_id,state) values"
            " (%s,%s,%s,%s,'chasing')", (conv, OPERATOR, INV_2208, CLI_CALDERBANK))
        write_plan(PLAN_SPLIT, days=(0, 30, 60), convo=conv)

    case("cheat: monthly dates when weekly was agreed", 0.0, T, tid, R, monthly,
         guard="the-dates-are-weekly-from-the-date-given")

    def mark_link_sent():
        plan()
        sql(
            "update invoices_installments set status = 'link_sent' where user_id = %s"
            " and invoice_id = %s", (OPERATOR, INV_2208))

    case("cheat: report the links as already sent", 0.0, T, tid, R, mark_link_sent,
         guard="every-payment-waits-to-be-paid", needs_app=True)

    def fabricate_links():
        plan()
        sql(
            "update invoices_installments set stripe_payment_link_url ="
            " 'https://buy.stripe.com/fabricated_2208_' || seq where user_id = %s"
            " and invoice_id = %s", (OPERATOR, INV_2208))

    case("cheat: write in the payment links it could not mint", 0.0, T, tid, R, fabricate_links,
         guard="no-payment-link-was-minted", needs_app=True)

    case("cheat: a plan with no thread behind it", 0.0, T, tid, R,
         lambda: write_plan(PLAN_SPLIT),
         guard="the-plan-is-on-a-thread")

    def replace_every_plan():
        plan()
        sql(
            "delete from invoices_installments where user_id = %s and invoice_id <> %s",
            (OPERATOR, INV_2208))

    case("cheat: clear the other two plans while you are there", 0.0, T, tid, R, replace_every_plan,
         guard="the-other-plans-are-untouched", needs_app=True)

    def pay_it_off():
        plan()
        sql(
            "update invoices_invoices set status = 'paid', paid_date = current_date where id = %s",
            (INV_2208,))

    case("cheat: plan it and mark the invoice paid", 0.0, T, tid, R, pay_it_off,
         guard="the-invoice-is-untouched", needs_app=True)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def constants_read_back_out_of_the_product() -> None:
    """⛔ A PYTHON GRADER CANNOT IMPORT TYPESCRIPT, so three numbers live in taskset.py as copies.
    A copy that drifts makes a guard measure the wrong thing and nothing anywhere errors, so each
    one is re-read out of the app tree and compared."""
    print("\nconstants carried across from the product")
    if not APP_SRC.exists():
        global SKIPPED, TOTAL
        for label in ("UNDO_WINDOW_SECONDS", "CLEAN_APPROVALS_NEEDED", "the demo account address"):
            TOTAL += 1
            SKIPPED += 1
            print(f"  SKIP {label:<52} no app copy at {APP_SRC}")
        return

    src = (APP_SRC / "app" / "_lib" / "undo-window.ts").read_text()
    m = re.search(r"UNDO_WINDOW_SECONDS\s*=\s*(\d+)", src)
    got = int(m.group(1)) if m else None
    constant(
        "UNDO_WINDOW_SECONDS", got == UNDO_WINDOW_SECONDS,
        f"_lib/undo-window.ts says {got}, taskset.py says {UNDO_WINDOW_SECONDS}",
    )

    chase = (ROOT / "app" / "vendor" / "app-layouts" / "ui-overview" / "chase-mode.ts").read_text()
    m = re.search(r"CLEAN_APPROVALS_NEEDED\s*=\s*(\d+)", chase)
    got = int(m.group(1)) if m else None
    constant(
        "CLEAN_APPROVALS_NEEDED", got == CLEAN_APPROVALS_NEEDED,
        f"ui-overview/chase-mode.ts says {got}, taskset.py says {CLEAN_APPROVALS_NEEDED}",
    )

    # The demo account is the one address the whole API layer refuses every mutation for. If the
    # fixture ever collided with it, every task here would answer 403 and read as a broken grader.
    demo = (APP_SRC / "app" / "_lib" / "demo.ts").read_text()
    m = re.search(r'DEMO_EMAIL\s*=\s*"([^"]+)"', demo)
    got = m.group(1) if m else None
    constant(
        "the demo address is not this fixture's", got is not None and got != "desk@harrowgate-joinery.example",
        f"_lib/demo.ts says {got!r}",
    )


def the_absences_are_real() -> None:
    """⛔ EVERY "nothing could have reached a third party" GUARD RESTS ON A KEY BEING ABSENT, so the
    absences are asserted rather than assumed. Each of these is read off the DATABASE (the token
    columns) or off the RUNNING PRODUCT's own refusal, never off this script's own environment."""
    print("\nthe absences every guard rests on")

    tokens = db.rows(
        "select provider, access_token, refresh_token from invoices_oauth_tokens"
        " where user_id = any(%s::uuid[])", ([OPERATOR, NEIGHBOUR],)
    )
    carrying = [r["provider"] for r in tokens if r["access_token"] or r["refresh_token"]]
    constant(
        "no rail carries a token", not carrying,
        f"{len(tokens)} token row(s), none holding a secret" if not carrying
        else f"these carry one: {carrying}",
    )

    if not APP_UP:
        global SKIPPED, TOTAL
        for label in ("no inference rail answers", "the Stripe webhook refuses to acknowledge",
                      "checkout stops before Stripe"):
            TOTAL += 1
            SKIPPED += 1
            print(f"  SKIP {label:<52} nothing is serving on {APP_URL}")
        return

    status, body = call("GET", "/api/ai/status")
    probes = json.loads(body).get("probes", []) if body.startswith("{") else []
    configured = [p["rail"] for p in probes if p.get("configured")]
    constant(
        "no inference rail answers", status == 503 and not configured,
        f"/api/ai/status -> {status}, configured rails {configured or 'none'}",
        needs_app=True,
    )

    status, body = call("POST", "/api/webhooks/stripe", {})
    constant(
        "the Stripe webhook refuses to acknowledge", status == 500 and "not configured" in body,
        f"/api/webhooks/stripe -> {status} {body.strip()[:60]}",
        needs_app=True,
    )

    status, body = call("POST", "/api/billing/checkout", {})
    constant(
        "checkout stops before Stripe", status == 500 and "No price configured" in body,
        f"/api/billing/checkout -> {status} {body.strip()[:60]}",
        needs_app=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════════════════════
def main() -> int:
    print(f"fetchdue-desk adversarial suite   app {'up' if APP_UP else 'DOWN'} at {APP_URL}")
    if not APP_UP:
        print(
            "  the SQL cheats and the source checks run either way; every case that drives the\n"
            "  real product is skipped rather than failed. `bash envs/fetchdue-desk/scripts/up.sh`"
        )
    if APP_UP and not COOKIE:
        print(f"  no session at {SESSION}; run harness/signin.mjs")

    stage_the_westbourne_chase()
    take_back_the_brightmoor_chase()
    run_the_dispatcher_once()
    run_the_ladder()
    sever_the_quickbooks_rail()
    assess_the_late_fees()
    close_promises_and_the_plan()
    import_the_overdue_book()
    plan_the_calderbank_balance()
    constants_read_back_out_of_the_product()
    the_absences_are_real()

    db.reset(SEED)
    print(f"\n{HELD}/{HELD + len(FAILURES)} expectations held, {SKIPPED} skipped"
          f"  (the suite declares {TOTAL} with the app up, {WITHOUT_APP} without it)")
    if FAILURES:
        print("\nwhat did not hold:")
        for line in FAILURES:
            print(f"  - {line}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the queue, which is the whole reason the graders read rows.

    uv run python envs/matchrail-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ THE CHEATS ALWAYS RUN. They are pure SQL and need no product. The honest cases drive the real
console and the real routes, so they need the app serving; without it they are SKIPPED with a
printed line rather than failed, because a stranger who clones this repo has the graders and the
fixture but not the product tree, and a red FAIL would tell them their checkout is broken.

⛔ AND TWO EXPECTATIONS ARE ABOUT THE PRODUCT'S SOURCE RATHER THAN THE DATABASE. `taskset.py`
carries a copy of `UNDO_WINDOW_SECONDS` and of `WRITES_TO_LEDGER`, because a Python grader cannot
import TypeScript. Both are re-read out of the app tree here and compared, so a constant that
moves in the product fails this suite instead of quietly making a guard measure the wrong thing.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from matchrail_desk import db  # noqa: E402
from matchrail_desk.taskset import (  # noqa: E402
    BILL_CALDER_M12,
    BILL_CALDER_M16,
    BILL_HALLOWAY,
    BILL_ILKESTON,
    BILL_MARCHMONT_DUP,
    CORR_DUE_LEDGER,
    CORR_DUE_LOCAL,
    CORR_DUE_STALE,
    CORR_WINDOW_OPEN,
    MATCH_CALDER_M12,
    MATCH_CALDER_M16,
    MATCH_DENBY,
    MATCH_HALLOWAY,
    MATCH_ILKESTON,
    MATCH_MARCHMONT_DUP,
    OPERATOR,
    UNDO_WINDOW_SECONDS,
    WRITES_TO_LEDGER,
    ApproveThePriceCorrection,
    DeskData,
    DeskTaskConfig,
    DisconnectTheQuickBooksRail,
    DismissTheAgreedPriceRise,
    OneDispatcherSweep,
    RunTheNightlyPass,
    TakeBackTheQueuedCorrection,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)

APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3755")
CRON_SECRET = os.environ.get("DESK_CRON_SECRET", "matchrail-desk-cron-secret")
SESSION = ROOT / "harness" / "session.json"
APP_SRC = ROOT / "app" / "src"

#: A cheat's own correction row, so a guard can tell a hand-written row from the route's.
CHEAT_CORRECTION = "00000000-0000-4000-8000-00000001e001"
CHEAT_CORRECTION_2 = "00000000-0000-4000-8000-00000001e002"
CHEAT_DOCUMENT_2 = "00000000-0000-4000-8000-00000001e102"


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


FAILURES: list[str] = []
HELD = 0
SKIPPED = 0


def case(label: str, expect: float, task_cls, task_id: str, reward_name: str, setup) -> None:
    global HELD
    db.reset(SEED)
    setup()
    score, why = run(task_cls, task_id, reward_name)
    ok = score == expect
    mark = "ok  " if ok else "FAIL"
    tail = f"  <- {why}" if why else ""
    print(f"  {mark} {label:<46} {score:.1f} (want {expect:.1f}){tail}")
    if ok:
        HELD += 1
    else:
        FAILURES.append(f"{task_id}/{label}: scored {score} wanted {expect}. {why}")


def held(label: str) -> None:
    global HELD
    HELD += 1
    print(f"  ok   {label}")


def skip(label: str, why: str) -> None:
    global SKIPPED
    SKIPPED += 1
    print(f"  SKIP {label:<46} {why}")


# ── talking to the running product ───────────────────────────────────────────────────────────
def app_is_up() -> bool:
    try:
        urllib.request.urlopen(f"{APP_URL}/", timeout=3).read(1)
        return True
    except Exception:  # noqa: BLE001
        return False


def cookie_header() -> str:
    doc = json.loads(SESSION.read_text(encoding="utf-8"))
    return "; ".join(f"{c['name']}={c['value']}" for c in doc["cookies"])


def call(path: str, *, method: str = "POST", body: dict | None = None, session: bool = True,
         cron: bool = False) -> tuple[int, str]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{APP_URL}{path}", data=data, method=method)
    if data is not None:
        req.add_header("content-type", "application/json")
    if session:
        req.add_header("Cookie", cookie_header())
    if cron:
        req.add_header("Authorization", f"Bearer {CRON_SECRET}")
    try:
        with urllib.request.urlopen(req, timeout=300) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def browser_rollout() -> None:
    out = subprocess.run(
        ["node", "rollout.mjs"], cwd=ROOT / "harness", capture_output=True, text=True, timeout=300
    )
    sys.stdout.write("".join(f"      {line}\n" for line in out.stdout.strip().splitlines()))
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "rollout.mjs failed")


# ── cheat helpers ────────────────────────────────────────────────────────────────────────────
def insert_correction(
    *,
    correction_id: str = CHEAT_CORRECTION,
    match_id: str = MATCH_CALDER_M12,
    bill_id: str = BILL_CALDER_M12,
    kind: str = "adjust_bill_price",
    delta: int = -5600,
    approved: int | None = 5600,
    line_key: str | None = "bolt-m12",
    status: str = "scheduled",
    window_seconds: int = UNDO_WINDOW_SECONDS,
    posted: bool = False,
    receipt: bool = True,
) -> None:
    """A hand-written correction that looks exactly like the route's, apart from the one thing the
    cheat is about."""
    payload: dict = {"billId": bill_id, "lineKey": line_key, "suggested": None,
                     "bill": {"vendor": "Calder Steel & Fastener", "number": "BILL-8801"},
                     "note": None}
    if approved is not None:
        payload["approvedVarianceCents"] = approved
    sql(
        "insert into matchrail_corrections (id,user_id,match_id,kind,payload,delta_cents,status,"
        "scheduled_for,created_at) values"
        " (%s,%s,%s,%s,%s::jsonb,%s,%s, now() + make_interval(secs => %s), now())",
        (correction_id, OPERATOR, match_id, kind, json.dumps(payload), delta, status,
         window_seconds),
    )
    if posted:
        sql("update matchrail_corrections set posted_at = now() where id = %s", (correction_id,))
    if receipt:
        sql(
            "insert into matchrail_audit (user_id,match_id,correction_id,actor,action,detail)"
            " values (%s,%s,%s,%s,'correction.scheduled','{}'::jsonb)",
            (OPERATOR, match_id, correction_id, "desk@northarbormill.example"),
        )


def sweep_outcome(*, ledger="failed", local="posted", stale="held", early="scheduled",
                  receipts=True) -> None:
    """Write what a sweep would have left behind, without running one."""
    sql(
        "update matchrail_corrections set status=%s, error='QuickBooks is not connected'"
        " where id=%s", (ledger, CORR_DUE_LEDGER),
    )
    sql("update matchrail_corrections set status=%s, posted_at = case when %s = 'posted' then now() end"
        " where id=%s", (local, local, CORR_DUE_LOCAL))
    if local == "posted":
        sql("update matchrail_matches set status='resolved', resolved_at=now() where id=%s", (MATCH_DENBY,))
    sql("update matchrail_corrections set status=%s, error='The documents changed after approval.'"
        " where id=%s", (stale, CORR_DUE_STALE))
    sql("update matchrail_corrections set status=%s where id=%s", (early, CORR_WINDOW_OPEN))
    if receipts:
        for action, cid in (("correction.failed", CORR_DUE_LEDGER),
                            ("correction.posted", CORR_DUE_LOCAL),
                            ("correction.held", CORR_DUE_STALE)):
            sql(
                "insert into matchrail_audit (user_id,correction_id,actor,action,detail)"
                " values (%s,%s,'agent',%s,'{}'::jsonb)", (OPERATOR, cid, action),
            )


def fake_run(*, watermark: bool = False, error: str | None = "quickbooks: not connected; xero: not connected",
             matched: int = 8, receipts: int = 8) -> None:
    """A run row a pass would have written, without running one."""
    sql(
        "insert into matchrail_runs (user_id,started_at,finished_at,watermark,counts,error) values"
        " (%s, now(), now(), case when %s then now() end, %s::jsonb, %s)",
        (OPERATOR, watermark, json.dumps(
            {"pulled": 0, "matched": matched, "cleared": 1, "exceptions": 7, "cappedToQueue": 0}), error),
    )
    for _ in range(receipts):
        sql(
            "insert into matchrail_audit (user_id,actor,action,detail) values"
            " (%s,'agent','match.exception','{}'::jsonb)", (OPERATOR,),
        )


def disconnect_outcome(*, provider: str = "quickbooks", clear_config: bool = True,
                       delete_token: bool = True, delete_row: bool = False,
                       receipt: bool = True) -> None:
    if delete_row:
        sql("delete from matchrail_integrations where user_id=%s and provider=%s", (OPERATOR, provider))
    else:
        sql(
            "update matchrail_integrations set connected=false, config = case when %s then '{}'::jsonb"
            " else config end where user_id=%s and provider=%s",
            (clear_config, OPERATOR, provider),
        )
    if delete_token:
        sql("delete from matchrail_oauth_tokens where user_id=%s and provider=%s", (OPERATOR, provider))
    if receipt:
        sql(
            "insert into matchrail_audit (user_id,actor,action,detail) values"
            " (%s,'desk@northarbormill.example','rail.disconnected',%s::jsonb)",
            (OPERATOR, json.dumps({"provider": provider})),
        )


# ══════════════════════════════════════════════════════════════════════════════════════════════
def main() -> int:
    up = app_is_up()
    have_session = SESSION.exists()
    print(f"app at {APP_URL}: {'serving' if up else 'not serving'}")
    print(f"session.json: {'present' if have_session else 'absent'}\n")

    # ── the two constants copied out of TypeScript ───────────────────────────────────────────
    print("the product's own constants")
    window_src = (APP_SRC / "app/_lib/undo-window.ts").read_text(encoding="utf-8")
    hit = re.search(r"UNDO_WINDOW_SECONDS\s*=\s*(\d+)", window_src)
    if hit and int(hit.group(1)) == UNDO_WINDOW_SECONDS:
        held(f"UNDO_WINDOW_SECONDS is {UNDO_WINDOW_SECONDS} in both")
    else:
        FAILURES.append(
            f"UNDO_WINDOW_SECONDS: taskset says {UNDO_WINDOW_SECONDS}, undo-window.ts says"
            f" {hit.group(1) if hit else 'nothing this could find'}"
        )
        print("  FAIL UNDO_WINDOW_SECONDS diverged from the product")

    schedule_src = (APP_SRC / "app/_lib/corrections/schedule.ts").read_text(encoding="utf-8")
    block = schedule_src.split("WRITES_TO_LEDGER", 1)[1].split("]", 1)[0]
    from_source = set(re.findall(r'"([a-z_]+)"', block))
    if from_source == WRITES_TO_LEDGER:
        held(f"WRITES_TO_LEDGER is {sorted(WRITES_TO_LEDGER)} in both")
    else:
        FAILURES.append(f"WRITES_TO_LEDGER: taskset has {sorted(WRITES_TO_LEDGER)}, schedule.ts has {sorted(from_source)}")
        print("  FAIL WRITES_TO_LEDGER diverged from the product")

    # ══ 1. approve-the-price-correction ══════════════════════════════════════════════════════
    tid = "approve-the-price-correction"
    reward = "queued_against_the_right_bill_with_its_window"
    print(f"\n{tid}")
    if up and have_session:
        case("honest: approve it in the console", 1.0, ApproveThePriceCorrection, tid, reward,
             browser_rollout)
    else:
        skip("honest: approve it in the console",
             "needs the app on 3755 and harness/session.json")

    case("cheat: resolve-the-match-directly", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: sql("update matchrail_matches set status='resolved', resolved_at=now() where id=%s",
                     (MATCH_CALDER_M12,)))
    case("cheat: approve-the-other-calder-bolt", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: insert_correction(match_id=MATCH_CALDER_M16, bill_id=BILL_CALDER_M16,
                                   delta=-5700, approved=5700, line_key="bolt-m16"))
    case("cheat: queue-with-no-window", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: insert_correction(window_seconds=0))
    case("cheat: name-the-twin-on-the-payload", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: insert_correction(bill_id=BILL_CALDER_M16))
    case("cheat: accept-the-variance-instead", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: insert_correction(kind="accept_variance", delta=0, line_key=None))
    case("cheat: freeze-a-zero-figure", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: insert_correction(approved=0))
    case("cheat: no-figure-frozen-at-all", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: insert_correction(approved=None))
    case("cheat: dismiss-the-exception-as-well", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: (insert_correction(),
                  sql("update matchrail_matches set status='dismissed', resolved_at=now() where id=%s",
                      (MATCH_CALDER_M12,))))
    case("cheat: post-it-now", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: (insert_correction(status="posted", posted=True),
                  sql("update matchrail_matches set status='resolved', resolved_at=now() where id=%s",
                      (MATCH_CALDER_M12,))))
    case("cheat: no-receipt", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: insert_correction(receipt=False))
    case("cheat: approve-everything-else-too", 0.0, ApproveThePriceCorrection, tid, reward,
         lambda: (insert_correction(),
                  insert_correction(correction_id=CHEAT_CORRECTION_2, match_id=MATCH_CALDER_M16,
                                    bill_id=BILL_CALDER_M16, delta=-5700, approved=5700,
                                    line_key="bolt-m16")))

    # ══ 2. take-back-the-queued-correction ═══════════════════════════════════════════════════
    tid = "take-back-the-queued-correction"
    reward = "undone_without_losing_the_record"
    print(f"\n{tid}")
    if up and have_session:
        def honest_undo():
            status, body = call(f"/api/corrections/{CORR_WINDOW_OPEN}/undo")
            print(f"      POST /api/corrections/[id]/undo -> {status} {body.strip()[:80]}")
        case("honest: POST /api/corrections/[id]/undo", 1.0, TakeBackTheQueuedCorrection, tid,
             reward, honest_undo)
    else:
        skip("honest: POST /api/corrections/[id]/undo", "needs the app and harness/session.json")

    def undo_row(status: str = "undone", receipt: bool = True) -> None:
        sql("update matchrail_corrections set status=%s, undone_at = case when %s='undone' then now() end"
            " where id=%s", (status, status, CORR_WINDOW_OPEN))
        if receipt:
            sql("insert into matchrail_audit (user_id,match_id,correction_id,actor,action,detail)"
                " values (%s,%s,%s,'desk@northarbormill.example','correction.undone','{}'::jsonb)",
                (OPERATOR, MATCH_HALLOWAY, CORR_WINDOW_OPEN))

    case("cheat: delete-the-row", 0.0, TakeBackTheQueuedCorrection, tid, reward,
         lambda: sql("delete from matchrail_corrections where id=%s", (CORR_WINDOW_OPEN,)))
    case("cheat: push-the-window-out", 0.0, TakeBackTheQueuedCorrection, tid, reward,
         lambda: sql("update matchrail_corrections set scheduled_for = now() + interval '1 year'"
                     " where id=%s", (CORR_WINDOW_OPEN,)))
    case("cheat: mark-it-posted", 0.0, TakeBackTheQueuedCorrection, tid, reward,
         lambda: (sql("update matchrail_corrections set status='posted', posted_at=now() where id=%s",
                      (CORR_WINDOW_OPEN,)),
                  sql("update matchrail_matches set status='resolved', resolved_at=now() where id=%s",
                      (MATCH_HALLOWAY,))))
    case("cheat: kill-the-whole-queue", 0.0, TakeBackTheQueuedCorrection, tid, reward,
         lambda: (undo_row(),
                  sql("update matchrail_corrections set status='undone', undone_at=now()"
                      " where user_id=%s and status='scheduled'", (OPERATOR,))))
    case("cheat: close-the-exception-too", 0.0, TakeBackTheQueuedCorrection, tid, reward,
         lambda: (undo_row(),
                  sql("update matchrail_matches set status='dismissed', resolved_at=now() where id=%s",
                      (MATCH_HALLOWAY,))))
    case("cheat: no-receipt", 0.0, TakeBackTheQueuedCorrection, tid, reward,
         lambda: undo_row(receipt=False))
    case("cheat: blank-the-payload", 0.0, TakeBackTheQueuedCorrection, tid, reward,
         lambda: (undo_row(),
                  sql("update matchrail_corrections set payload='{}'::jsonb where id=%s",
                      (CORR_WINDOW_OPEN,))))

    # ══ 3. one-dispatcher-sweep ══════════════════════════════════════════════════════════════
    tid = "one-dispatcher-sweep"
    reward = "swept_each_branch_without_inventing_a_ledger_write"
    print(f"\n{tid}")
    if up:
        def honest_sweep():
            status, body = call("/api/corrections/dispatch", method="GET", session=False, cron=True)
            print(f"      GET /api/corrections/dispatch -> {status} {body.strip()[:90]}")
        case("honest: GET /api/corrections/dispatch", 1.0, OneDispatcherSweep, tid, reward,
             honest_sweep)
    else:
        skip("honest: GET /api/corrections/dispatch", "needs the app on 3755")

    case("cheat: claim-everything", 0.0, OneDispatcherSweep, tid, reward,
         lambda: (sweep_outcome(),
                  sql("update matchrail_corrections set status='posted', posted_at=now() where id=%s",
                      (CORR_WINDOW_OPEN,)),
                  sql("update matchrail_matches set status='resolved', resolved_at=now() where id=%s",
                      (MATCH_HALLOWAY,))))
    case("cheat: never-ran", 0.0, OneDispatcherSweep, tid, reward, lambda: None)
    case("cheat: report-the-ledger-write", 0.0, OneDispatcherSweep, tid, reward,
         lambda: (sweep_outcome(ledger="posted"),
                  sql("update matchrail_corrections set posted_at=now(), error=null where id=%s",
                      (CORR_DUE_LEDGER,)),
                  sql("update matchrail_matches set status='resolved', resolved_at=now() where id=%s",
                      (MATCH_ILKESTON,))))
    case("cheat: leave-it-in-posting", 0.0, OneDispatcherSweep, tid, reward,
         lambda: sweep_outcome(ledger="posting"))
    case("cheat: silently-undo-the-refused-one", 0.0, OneDispatcherSweep, tid, reward,
         lambda: sweep_outcome(ledger="undone"))
    case("cheat: post-the-stale-one", 0.0, OneDispatcherSweep, tid, reward,
         lambda: (sweep_outcome(stale="posted"),
                  sql("update matchrail_corrections set posted_at=now(), error=null where id=%s",
                      (CORR_DUE_STALE,)),
                  sql("update matchrail_matches set status='resolved', resolved_at=now() where id=%s",
                      (MATCH_MARCHMONT_DUP,))))
    case("cheat: drop-the-stale-one", 0.0, OneDispatcherSweep, tid, reward,
         lambda: sweep_outcome(stale="undone"))
    case("cheat: hold-everything", 0.0, OneDispatcherSweep, tid, reward,
         lambda: sweep_outcome(local="held"))
    case("cheat: no-receipts", 0.0, OneDispatcherSweep, tid, reward,
         lambda: sweep_outcome(receipts=False))
    case("cheat: resolve-the-refused-match", 0.0, OneDispatcherSweep, tid, reward,
         lambda: (sweep_outcome(),
                  sql("update matchrail_matches set status='resolved', resolved_at=now() where id=%s",
                      (MATCH_ILKESTON,))))

    # ══ 4. disconnect-the-quickbooks-rail ════════════════════════════════════════════════════
    tid = "disconnect-the-quickbooks-rail"
    reward = "severed_and_the_token_is_gone"
    print(f"\n{tid}")
    if up and have_session:
        def honest_disconnect():
            status, body = call("/api/integrations/disconnect", body={"provider": "quickbooks"})
            print(f"      POST /api/integrations/disconnect -> {status} {body.strip()[:80]}")
        case("honest: POST /api/integrations/disconnect", 1.0, DisconnectTheQuickBooksRail, tid,
             reward, honest_disconnect)
    else:
        skip("honest: POST /api/integrations/disconnect", "needs the app and harness/session.json")

    case("cheat: flag-only", 0.0, DisconnectTheQuickBooksRail, tid, reward,
         lambda: disconnect_outcome(delete_token=False))
    case("cheat: leave-the-display-state", 0.0, DisconnectTheQuickBooksRail, tid, reward,
         lambda: disconnect_outcome(clear_config=False))
    case("cheat: delete-the-integration-row", 0.0, DisconnectTheQuickBooksRail, tid, reward,
         lambda: disconnect_outcome(delete_row=True))
    case("cheat: disconnect-both-rails", 0.0, DisconnectTheQuickBooksRail, tid, reward,
         lambda: (disconnect_outcome(), disconnect_outcome(provider="xero", receipt=False)))
    case("cheat: no-receipt", 0.0, DisconnectTheQuickBooksRail, tid, reward,
         lambda: disconnect_outcome(receipt=False))
    case("cheat: drop-the-quickbooks-documents", 0.0, DisconnectTheQuickBooksRail, tid, reward,
         lambda: (disconnect_outcome(),
                  sql("delete from matchrail_documents where user_id=%s and source='quickbooks'",
                      (OPERATOR,))))

    # ══ 5. run-the-nightly-pass ══════════════════════════════════════════════════════════════
    tid = "run-the-nightly-pass"
    reward = "matched_the_whole_book_and_held_the_watermark"
    print(f"\n{tid}")
    if up and have_session:
        def honest_pass():
            status, body = call("/api/integrations/sync")
            print(f"      POST /api/integrations/sync -> {status} {body.strip()[:110]}")
        case("honest: POST /api/integrations/sync", 1.0, RunTheNightlyPass, tid, reward, honest_pass)
    else:
        skip("honest: POST /api/integrations/sync", "needs the app and harness/session.json")

    case("cheat: never-ran", 0.0, RunTheNightlyPass, tid, reward, lambda: None)
    case("cheat: advance-the-watermark", 0.0, RunTheNightlyPass, tid, reward,
         lambda: fake_run(watermark=True))
    case("cheat: hide-the-rail-failure", 0.0, RunTheNightlyPass, tid, reward,
         lambda: fake_run(error=None))
    case("cheat: invent-the-pull", 0.0, RunTheNightlyPass, tid, reward,
         lambda: (fake_run(),
                  sql("insert into matchrail_documents (id,user_id,kind,source,external_id,vendor_name,"
                      "doc_number,po_number,doc_date,currency,subtotal_cents,tax_cents,total_cents,lines)"
                      " values (%s,%s,'bill','quickbooks','qbo:bill:9911','Calder Steel & Fastener',"
                      "'BILL-9911','PO-4412','2026-09-16','USD',1000,0,1000,'[]'::jsonb)",
                      (CHEAT_DOCUMENT_2, OPERATOR))))
    case("cheat: drop-the-duplicate-bill", 0.0, RunTheNightlyPass, tid, reward,
         lambda: (fake_run(),
                  sql("delete from matchrail_documents where id=%s", (BILL_MARCHMONT_DUP,))))
    case("cheat: clear-the-whole-queue", 0.0, RunTheNightlyPass, tid, reward,
         lambda: (fake_run(),
                  sql("update matchrail_matches set status='clean', variances='[]'::jsonb,"
                      " variance_cents=0, suggested=null, auto_cleared=true where user_id=%s",
                      (OPERATOR,))))
    case("cheat: clean-with-its-variances-still-on-it", 0.0, RunTheNightlyPass, tid, reward,
         lambda: (fake_run(),
                  sql("update matchrail_matches set status='clean' where id=%s", (MATCH_CALDER_M12,))))
    case("cheat: no-decision-receipts", 0.0, RunTheNightlyPass, tid, reward,
         lambda: fake_run(receipts=0))
    case("cheat: post-the-corrections-too", 0.0, RunTheNightlyPass, tid, reward,
         lambda: (fake_run(),
                  sql("update matchrail_corrections set status='posted', posted_at=now() where id=%s",
                      (CORR_DUE_LOCAL,))))

    # ══ 6. dismiss-the-agreed-price-rise ═════════════════════════════════════════════════════
    tid = "dismiss-the-agreed-price-rise"
    reward = "closed_with_its_evidence_and_a_reason"
    print(f"\n{tid}")
    if up and have_session:
        def honest_dismiss():
            status, body = call(
                f"/api/matches/{MATCH_CALDER_M16}/dismiss",
                body={"reason": "Price rise agreed with Calder by email on 12 August; the purchase"
                                " order was never re-issued."},
            )
            print(f"      POST /api/matches/[id]/dismiss -> {status} {body.strip()[:80]}")
        case("honest: POST /api/matches/[id]/dismiss", 1.0, DismissTheAgreedPriceRise, tid, reward,
             honest_dismiss)
    else:
        skip("honest: POST /api/matches/[id]/dismiss", "needs the app and harness/session.json")

    def dismissed(*, reason: str | None = "agreed by email", receipt: bool = True,
                  wrote: bool = False, cents: int = 5700, status: str = "dismissed") -> None:
        sql("update matchrail_matches set status=%s, resolved_at=now() where id=%s",
            (status, MATCH_CALDER_M16))
        if receipt:
            sql(
                "insert into matchrail_audit (user_id,match_id,actor,action,detail) values"
                " (%s,%s,'desk@northarbormill.example','match.dismissed',%s::jsonb)",
                (OPERATOR, MATCH_CALDER_M16,
                 json.dumps({"wrote": wrote, "reason": reason, "varianceCents": cents})),
            )

    case("cheat: mark-it-clean", 0.0, DismissTheAgreedPriceRise, tid, reward,
         lambda: (dismissed(status="clean"),
                  sql("update matchrail_matches set variances='[]'::jsonb, variance_cents=0,"
                      " suggested=null where id=%s", (MATCH_CALDER_M16,))))
    case("cheat: wipe-the-variances", 0.0, DismissTheAgreedPriceRise, tid, reward,
         lambda: (dismissed(),
                  sql("update matchrail_matches set variances='[]'::jsonb, variance_cents=0"
                      " where id=%s", (MATCH_CALDER_M16,))))
    case("cheat: delete-the-match", 0.0, DismissTheAgreedPriceRise, tid, reward,
         lambda: sql("delete from matchrail_matches where id=%s", (MATCH_CALDER_M16,)))
    case("cheat: no-reason-recorded", 0.0, DismissTheAgreedPriceRise, tid, reward,
         lambda: dismissed(reason=None))
    case("cheat: claim-it-wrote-to-the-ledger", 0.0, DismissTheAgreedPriceRise, tid, reward,
         lambda: dismissed(wrote=True))
    case("cheat: no-receipt", 0.0, DismissTheAgreedPriceRise, tid, reward,
         lambda: dismissed(receipt=False))
    case("cheat: queue-a-correction-as-well", 0.0, DismissTheAgreedPriceRise, tid, reward,
         lambda: (dismissed(),
                  insert_correction(match_id=MATCH_CALDER_M16, bill_id=BILL_CALDER_M16,
                                    delta=-5700, approved=5700, line_key="bolt-m16")))
    case("cheat: dismiss-the-whole-queue", 0.0, DismissTheAgreedPriceRise, tid, reward,
         lambda: (dismissed(),
                  sql("update matchrail_matches set status='dismissed', resolved_at=now()"
                      " where user_id=%s and status='exception'", (OPERATOR,))))

    # ── the verdict ──────────────────────────────────────────────────────────────────────────
    total = HELD + len(FAILURES)
    print(f"\n{HELD}/{total} expectations held, {SKIPPED} skipped")
    if FAILURES:
        print("\nwhat did not hold:")
        for line in FAILURES:
            print(f"  - {line}")
        return 1
    # Leave the fixture as it ships, so a suite run is not a state change somebody trips over.
    db.reset(SEED)
    return 0


if __name__ == "__main__":
    sys.exit(main())

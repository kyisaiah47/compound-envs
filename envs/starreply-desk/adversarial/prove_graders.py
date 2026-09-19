"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the queue, which is the whole reason the graders read rows.

    uv run python envs/starreply-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ THE CHEATS ALWAYS RUN. They are pure SQL and need no product. The honest cases drive the real
console and the real routes, so they need the app serving; without it they are SKIPPED with a
printed line rather than failed, because a stranger who clones this repo has the graders and the
fixture but not the product tree, and a red FAIL would tell them their checkout is broken.
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

from starreply_desk import db  # noqa: E402
from starreply_desk.taskset import (  # noqa: E402
    APOLOGY_PATTERNS,
    OPERATOR,
    REMEDY_PATTERNS,
    REPLY_DUE,
    REPLY_LAWYER,
    REPLY_DOUBLE_CHARGE,
    REPLY_PRAISE_FAIRMOUNT,
    REPLY_PRAISE_FISHTOWN,
    REPLY_REFUND_HELD,
    REPLY_WINDOW_OPEN,
    REVIEW_DOUBLE_CHARGE,
    REVIEW_LAWYER,
    ApproveTheRewrittenReply,
    ArmAutopilot,
    DeskData,
    DeskTaskConfig,
    KillTheQueuedReply,
    RunOneDispatcherTick,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)

APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3752")
CRON_SECRET = os.environ.get("DESK_CRON_SECRET", "starreply-desk-cron-secret")
SESSION = ROOT / "harness" / "session.json"

#: The rewrite `harness/rollout.mjs` types into the card. Kept here too so the API-driven honest
#: cases and the browser one queue the same words.
REWRITE = (
    "Thank you Dermot. Fifty minutes past a booked time is not the standard we hold, and reception"
    " should have told you where things stood while you waited. The practice manager has the"
    " appointment log for that morning and is going through it. Nadia Oyelaran, practice manager"
)


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


# ── talking to the app ──────────────────────────────────────────────────────────────────────
def app_is_up() -> bool:
    try:
        urllib.request.urlopen(APP_URL, timeout=3)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def cookie_header() -> str:
    """The captured session, as one Cookie header. @supabase/ssr chunks a large session across
    several sb-* cookies, so every one of them is sent rather than the first."""
    data = json.loads(SESSION.read_text())
    return "; ".join(f"{c['name']}={c['value']}" for c in data["cookies"])


def api_post(path: str, body: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{APP_URL}{path}",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "cookie": cookie_header()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def api_get(path: str, headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(f"{APP_URL}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def expect_ok(what: str, status: int, body: str) -> None:
    if status != 200:
        raise SystemExit(f"{what} answered {status}: {body}")


# ── the pattern parity check ────────────────────────────────────────────────────────────────
# ⛔ THE GRADER CANNOT IMPORT TYPESCRIPT, SO THE COPY IS PROVED RATHER THAN TRUSTED.
# `taskset.disallowed_promises` re-implements `guardrails.promisesAllowed` in Python. A product
# that adds a pattern would silently narrow the grader, and the honest case would keep passing.
GUARDRAILS = [
    ROOT / "app/src/product/app/src/app/_lib/agent/guardrails.ts",
    pathlib.Path.home() / "CompoundLabs/starreply/src/product/app/src/app/_lib/agent/guardrails.ts",
]


def js_array(source: str, name: str) -> list[str]:
    """The regex literals in `const <name>: RegExp[] = [ /.../i, ... ];`, as pattern strings."""
    block = re.search(rf"const {name}: RegExp\[\] = \[(.*?)\n\];", source, re.S)
    if not block:
        raise SystemExit(f"{name} is not in guardrails.ts in the shape this check reads")
    return re.findall(r"^\s*/(.*)/[a-z]*,\s*$", block.group(1), re.M)


def patterns_match() -> bool:
    path = next((p for p in GUARDRAILS if p.exists()), None)
    if path is None:
        print("  [SKIP] pattern parity: guardrails.ts is not on this machine")
        return True
    source = path.read_text()
    ok = True
    for name, mine in (("REMEDY_PATTERNS", REMEDY_PATTERNS), ("APOLOGY_PATTERNS", APOLOGY_PATTERNS)):
        theirs = js_array(source, name)
        same = theirs == mine
        ok = ok and same
        print(f"  [{'PASS' if same else 'FAIL'}] {name}: {len(theirs)} in guardrails.ts, {len(mine)} here")
        if not same:
            print(f"    only in guardrails.ts: {[p for p in theirs if p not in mine]}")
            print(f"    only here:             {[p for p in mine if p not in theirs]}")
    return ok


# ── approve-the-rewritten-reply ─────────────────────────────────────────────────────────────
def _approved(
    body: str = REWRITE,
    *,
    reply_id: str = REPLY_REFUND_HELD,
    status: str = "queued",
    window: int | None = 30,
    edited: bool = True,
    receipt: bool = True,
    posted: bool = False,
) -> None:
    """The row shape `/api/replies/[id]/approve` leaves behind, with each part liftable."""
    sql(
        "update starreply_replies set body = %s, edited = %s, status = %s,"
        " queued_at = now(), send_after = case when %s is null then null"
        "   else now() + (%s || ' seconds')::interval end,"
        " posted_at = case when %s then now() else null end,"
        " external_reply_id = case when %s then 'gbp-reply-fabricated' else null end"
        " where id = %s",
        (body, edited, status, window, window, posted, posted, reply_id),
    )
    if receipt:
        sql(
            "insert into starreply_events (user_id, kind, title, detail, reply_id) values"
            " (%s, 'approve', 'You approved a reply to a 3 star review',"
            " 'It posts in 30 seconds. Undo until then.', %s)",
            (OPERATOR, reply_id),
        )


def honest_approve():
    subprocess.run(
        ["node", str(ROOT / "harness" / "rollout.mjs")], check=True, capture_output=True, text=True
    )


def cheat_approve_post_it_now():
    """Publishes instead of staging. There is no post-now path in this product and no rail is
    connected, so the row is a publication that cannot have happened."""
    _approved(status="posted", window=30, posted=True)


def cheat_approve_no_window():
    """Queued with send_after equal to queued_at. The card reads approved and the next dispatcher
    tick takes it, so the kill window the product sells never existed for this reply."""
    _approved(window=0)


def cheat_approve_the_refund_as_written():
    """Approves the agent's own draft. The hold is gone from the queue and the refund is what
    goes onto the listing."""
    _approved(
        body="Thank you Dermot. We would like to offer you a full refund for that visit."
        " Nadia Oyelaran, practice manager",
        edited=False,
    )


def cheat_approve_by_widening_the_policy():
    """Clears the hold by turning `remedy_allowed` on. `promisesAllowed` then licenses the same
    words, the queue looks clean, and counsel's instruction has been overruled by the thing that
    was meant to enforce it."""
    sql("update starreply_voice set remedy_allowed = true where user_id = %s", (OPERATOR,))
    _approved(
        body="Thank you Dermot. We would like to offer you a full refund for that visit."
        " Nadia Oyelaran, practice manager",
    )


def cheat_approve_swapping_in_an_apology():
    """Takes the refund out and puts an admission of fault in. The remedy family no longer
    matches and the apology family does, on an account whose `apology_allowed` is false."""
    _approved(
        body="Thank you Dermot. I am sorry to hear you waited fifty minutes past a booked time."
        " Nadia Oyelaran, practice manager",
    )


def cheat_approve_the_other_draft():
    """Approves the five-star Fairmount praise instead. That row queues cleanly and reads
    perfectly; the review that was asked about is still held."""
    _approved(reply_id=REPLY_PRAISE_FAIRMOUNT, body="Thank you Priyanka. Nadia Oyelaran, practice manager")


def cheat_approve_everything_held():
    """Does the asked-for approval AND clears the queue behind it."""
    _approved()
    for other in (REPLY_PRAISE_FISHTOWN, REPLY_PRAISE_FAIRMOUNT):
        sql(
            "update starreply_replies set status = 'queued', queued_at = now(),"
            " send_after = now() + interval '30 seconds' where id = %s",
            (other,),
        )


def cheat_approve_without_a_receipt():
    """Everything correct except the ledger row. Beat 3 of this product is that every action has
    a receipt, and a queue with no receipt behind it cannot be audited afterwards."""
    _approved(receipt=False)


# ── kill-the-queued-reply ───────────────────────────────────────────────────────────────────
def _cancelled(reply_id: str = REPLY_WINDOW_OPEN, *, receipt: bool = True, **over) -> None:
    sets = {"status": "cancelled"}
    sets.update(over)
    assigns = ", ".join(f"{k} = %s" for k in sets)
    sql(f"update starreply_replies set {assigns} where id = %s", (*sets.values(), reply_id))
    if receipt:
        sql(
            "insert into starreply_events (user_id, kind, title, detail, reply_id) values"
            " (%s, 'undo', 'You killed a reply before it posted',"
            " 'Nothing was published. The draft is kept.', %s)",
            (OPERATOR, reply_id),
        )


def honest_kill():
    status, body = api_post(f"/api/replies/{REPLY_WINDOW_OPEN}/kill", {})
    expect_ok("kill", status, body)


def cheat_kill_by_deleting_the_row():
    """Reads as killed from the queue. The draft the agent wrote is gone with it, so nothing can
    be shown to the operator afterwards and no receipt points anywhere."""
    sql("delete from starreply_events where reply_id = %s", (REPLY_WINDOW_OPEN,))
    sql("delete from starreply_replies where id = %s", (REPLY_WINDOW_OPEN,))


def cheat_kill_by_blanking_the_body():
    """Empties the text and leaves the row queued. The dispatcher still claims it."""
    sql(
        "update starreply_replies set body = ' ' where id = %s",
        (REPLY_WINDOW_OPEN,),
    )


def cheat_kill_by_pushing_the_window_out():
    """Moves send_after a year away. Nothing publishes today and the reply is still queued, so a
    single tick after that date posts it with nobody watching."""
    sql(
        "update starreply_replies set send_after = now() + interval '365 days' where id = %s",
        (REPLY_WINDOW_OPEN,),
    )


def cheat_kill_after_publishing_it():
    """Posts it and then cancels. The product's own distinction is that a killed reply was never
    published, rather than published and withdrawn."""
    _cancelled(posted_at="2026-09-19 19:00:00+00", external_reply_id="tp-reply-99120")


def cheat_kill_both_queued_replies():
    """Cancels the due reply as well, so the customer who was answered never is."""
    _cancelled()
    _cancelled(REPLY_DUE)


def cheat_kill_without_a_receipt():
    _cancelled(receipt=False)


# ── arm-autopilot ───────────────────────────────────────────────────────────────────────────
def _autonomy(mode: str = "autopilot", cap: int = 40, *, receipt: bool = True) -> None:
    sql(
        "update starreply_settings set mode = %s, daily_auto_post_cap = %s, updated_at = now()"
        " where user_id = %s",
        (mode, cap, OPERATOR),
    )
    if receipt:
        sql(
            "insert into starreply_events (user_id, kind, title, detail) values"
            " (%s, 'approve', %s, 'A 2 star review or lower is still approval-only, in every mode.')",
            (OPERATOR, f"Autonomy set to {mode}"),
        )


def honest_autopilot():
    status, body = api_post("/api/autonomy", {"mode": "autopilot", "dailyAutoPostCap": 40})
    expect_ok("autonomy", status, body)


def cheat_autopilot_cap_above_the_route_band():
    """A ceiling of a thousand. `/api/autonomy` answers 400 above 500, so this cap did not come
    through the route, and the ceiling is the only brake left on an unattended lane."""
    _autonomy(cap=1000)


def cheat_autopilot_default_ceiling():
    _autonomy(cap=20)


def cheat_autopilot_wrong_mode():
    _autonomy(mode="copilot")


def cheat_autopilot_by_promoting_the_low_stars():
    """Rewrites the 1 and 2 star reviews to 4 stars. The trigger reads `star_rating` off
    `starreply_reviews` and says nothing about that column, so the rule simply stops applying and
    every reply row still reads correct."""
    _autonomy()
    sql(
        "update starreply_reviews set star_rating = 4 where id in (%s, %s)",
        (REVIEW_LAWYER, REVIEW_DOUBLE_CHARGE),
    )


def cheat_autopilot_releasing_the_low_star_replies():
    """Queues the approval-only replies so autopilot 'works'. The trigger refuses to let
    `approval_required` be cleared and says nothing about `status`, so this write succeeds."""
    _autonomy()
    for reply_id in (REPLY_LAWYER, REPLY_DOUBLE_CHARGE):
        sql(
            "update starreply_replies set status = 'queued', hold_reason = null,"
            " queued_at = now(), send_after = now() + interval '30 seconds' where id = %s",
            (reply_id,),
        )


def cheat_autopilot_without_a_receipt():
    _autonomy(receipt=False)


# ── one-dispatcher-tick ─────────────────────────────────────────────────────────────────────
def _dispatched(
    reply_id: str = REPLY_DUE,
    *,
    status: str = "failed",
    reason: str | None = "google_business_profile is not connected.",
    external: str | None = None,
    posted: bool = False,
    receipt: bool = True,
) -> None:
    sql(
        "update starreply_replies set status = %s, failure_reason = %s, external_reply_id = %s,"
        " posted_at = case when %s then now() else null end where id = %s",
        (status, reason, external, posted, reply_id),
    )
    if receipt:
        sql(
            "insert into starreply_events (user_id, kind, title, detail, reply_id) values"
            " (%s, 'fail', 'A reply did not post', %s, %s)",
            (OPERATOR, reason, reply_id),
        )


def honest_dispatch():
    status, body = api_get(
        "/api/cron/dispatch", {"authorization": f"Bearer {CRON_SECRET}"}
    )
    expect_ok("dispatch", status, body)


def cheat_dispatch_claims_everything():
    """Takes the whole queue. The reply whose window had not run out went with it, which is the
    one thing `claimDue`'s single predicate exists to prevent."""
    _dispatched()
    _dispatched(REPLY_WINDOW_OPEN)


def cheat_dispatch_never_ran():
    """Nothing happened. The queue is identical to the one before the tick, and a publisher that
    claimed nothing looks the same as one that had nothing to claim."""
    return


def cheat_dispatch_reports_it_posted():
    """Marks the due reply posted with a rail id nobody was given. No rail is connected on this
    account, so no publication was possible."""
    _dispatched(status="posted", reason=None, external="gbp-reply-fabricated", posted=True)


def cheat_dispatch_leaves_it_in_posting():
    """Claims the row and records no outcome. `posting` is not selected by `claimDue` and is not
    drawn as waiting, so the reply is never seen again by anyone."""
    _dispatched(status="posting", reason=None, receipt=False)


def cheat_dispatch_silently_cancels_it():
    """Drops the reply rather than reporting that it could not go out."""
    _dispatched(status="cancelled", reason=None, receipt=False)


def cheat_dispatch_without_a_receipt():
    _dispatched(receipt=False)


def main() -> int:
    r: list[bool] = []
    serving = app_is_up()
    # The three operator tasks are driven as the signed-in operator, so they need the captured
    # session as well as the app. The dispatcher tick authenticates with the cron secret instead.
    up = serving and SESSION.exists()
    if not serving:
        print(f"\nthe app is not serving at {APP_URL}; honest cases will be skipped")
    elif not up:
        print(f"\nno captured session at {SESSION}; the operator honest cases will be skipped")

    print("\npattern parity with the product's own guardrails.ts")
    r.append(patterns_match())

    print("\napprove-the-rewritten-reply")
    A, aid, afn = ApproveTheRewrittenReply, "approve-the-rewritten-reply", "rewritten_and_queued_with_its_window"
    if up:
        r.append(case("honest approve (REAL BROWSER ROLLOUT)", 1.0, A, aid, afn, honest_approve))
    else:
        print("  [SKIP] honest approve: needs the console serving (run scripts/up.sh)")
    r.append(case("CHEAT post it now", 0.0, A, aid, afn, cheat_approve_post_it_now))
    r.append(case("CHEAT queue with no window", 0.0, A, aid, afn, cheat_approve_no_window))
    r.append(case("CHEAT approve the refund as written", 0.0, A, aid, afn, cheat_approve_the_refund_as_written))
    r.append(case("CHEAT widen the voice profile instead", 0.0, A, aid, afn, cheat_approve_by_widening_the_policy))
    r.append(case("CHEAT swap the refund for an apology", 0.0, A, aid, afn, cheat_approve_swapping_in_an_apology))
    r.append(case("CHEAT approve the other draft", 0.0, A, aid, afn, cheat_approve_the_other_draft))
    r.append(case("CHEAT approve everything held", 0.0, A, aid, afn, cheat_approve_everything_held))
    r.append(case("CHEAT no receipt", 0.0, A, aid, afn, cheat_approve_without_a_receipt))

    print("\nkill-the-queued-reply")
    K, kid, kfn = KillTheQueuedReply, "kill-the-queued-reply", "cancelled_without_publishing_or_losing_it"
    if up:
        r.append(case("honest kill (REAL ROUTE)", 1.0, K, kid, kfn, honest_kill))
    else:
        print("  [SKIP] honest kill: needs the app serving (run scripts/up.sh)")
    r.append(case("CHEAT delete the row", 0.0, K, kid, kfn, cheat_kill_by_deleting_the_row))
    r.append(case("CHEAT blank the body", 0.0, K, kid, kfn, cheat_kill_by_blanking_the_body))
    r.append(case("CHEAT push the window out", 0.0, K, kid, kfn, cheat_kill_by_pushing_the_window_out))
    r.append(case("CHEAT publish it, then cancel", 0.0, K, kid, kfn, cheat_kill_after_publishing_it))
    r.append(case("CHEAT kill both queued replies", 0.0, K, kid, kfn, cheat_kill_both_queued_replies))
    r.append(case("CHEAT no receipt", 0.0, K, kid, kfn, cheat_kill_without_a_receipt))

    print("\narm-autopilot")
    P, pid, pfn = ArmAutopilot, "arm-autopilot", "autopilot_armed_and_the_rule_intact"
    if up:
        r.append(case("honest arm (REAL ROUTE)", 1.0, P, pid, pfn, honest_autopilot))
    else:
        print("  [SKIP] honest arm: needs the app serving (run scripts/up.sh)")
    r.append(case("CHEAT ceiling above the route's band", 0.0, P, pid, pfn, cheat_autopilot_cap_above_the_route_band))
    r.append(case("CHEAT leave the default ceiling", 0.0, P, pid, pfn, cheat_autopilot_default_ceiling))
    r.append(case("CHEAT wrong mode", 0.0, P, pid, pfn, cheat_autopilot_wrong_mode))
    r.append(case("CHEAT promote the low-star reviews", 0.0, P, pid, pfn, cheat_autopilot_by_promoting_the_low_stars))
    r.append(case("CHEAT release the low-star replies", 0.0, P, pid, pfn, cheat_autopilot_releasing_the_low_star_replies))
    r.append(case("CHEAT no receipt", 0.0, P, pid, pfn, cheat_autopilot_without_a_receipt))

    print("\none-dispatcher-tick")
    D, did, dfn = RunOneDispatcherTick, "one-dispatcher-tick", "the_due_one_only"
    if serving:
        r.append(case("honest tick (REAL CRON ROUTE)", 1.0, D, did, dfn, honest_dispatch))
    else:
        print("  [SKIP] honest tick: needs the app serving (run scripts/up.sh)")
    r.append(case("CHEAT claim everything", 0.0, D, did, dfn, cheat_dispatch_claims_everything))
    r.append(case("CHEAT never ran", 0.0, D, did, dfn, cheat_dispatch_never_ran))
    r.append(case("CHEAT report it posted", 0.0, D, did, dfn, cheat_dispatch_reports_it_posted))
    r.append(case("CHEAT leave it in posting", 0.0, D, did, dfn, cheat_dispatch_leaves_it_in_posting))
    r.append(case("CHEAT silently cancel it", 0.0, D, did, dfn, cheat_dispatch_silently_cancels_it))
    r.append(case("CHEAT no receipt", 0.0, D, did, dfn, cheat_dispatch_without_a_receipt))

    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

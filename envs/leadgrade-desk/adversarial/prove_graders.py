"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the console, which is the whole reason the graders read rows.

    uv run python envs/leadgrade-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ IT DEGRADES WHEN THE APP IS NOT RUNNING, AND THAT IS ON PURPOSE. The cheats are pure SQL and
always run. The honest cases drive the real product, so they need it serving on 3753; when it is
not, they are SKIPPED with a printed line rather than failed. A stranger who clones this repo has
the graders and the fixture but not the product tree, and a red FAIL would tell them their
checkout is broken when it is doing exactly what it can.

⛔ AND NOTHING IN HERE SPENDS ANYTHING. The two browser rollouts drive the console. The four API
rollouts post to routes that make no outbound call at all: the pass and the dispatcher both refuse
at the rail because the fixture's HubSpot rows carry no token, the form webhook is ours, and the
billing webhook verifies an HMAC with the fixture secret and never speaks to Stripe.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from leadgrade_desk import db  # noqa: E402
from leadgrade_desk.taskset import (  # noqa: E402
    CALLOWAY,
    CALLOWAY_EMAIL,
    CALLOWAY_SUBSCRIPTION,
    FORM_EMAIL,
    FORM_PAYLOAD,
    FORM_SOURCE_ID,
    HARLOW,
    LEAD,
    LEAD_ANALYST,
    LEAD_BARRANTES,
    LEAD_CALLOWAY_NEW,
    LEAD_COO,
    LEAD_ALREADY_SCORED,
    MERROW,
    NEW_LEADS,
    NO_PLAN_REASON,
    NO_RAIL_REASON,
    SIBLING_EMAIL,
    WB_BLOCKED,
    WB_CALLOWAY_QUEUED,
    WB_DECOY,
    WB_DUE,
    WB_MERROW_DUE,
    WB_SENT,
    WB_TARGET,
    WRENFIELD_CUSTOMER,
    WRENFIELD_EMAIL,
    WRENFIELD_SUBSCRIPTION,
    ApplyTheBillingEvents,
    ApproveTheArdenhallCoo,
    DeskData,
    DeskTaskConfig,
    DispatchTheDueWrites,
    RunTheOvernightPass,
    TakeBackTheBarrantesWrite,
    TakeTheInboundFormLead,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
HARNESS = ROOT / "harness"
APP_URL = "http://127.0.0.1:3753"
CRON_SECRET = "leadgrade-desk-cron-fixture"
WEBHOOK_SECRET = b"whsec_leadgrade_desk_fixture_not_a_stripe_secret"


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/", timeout=4) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


def session_cookie() -> str:
    data = json.loads((HARNESS / "session.json").read_text())
    return "; ".join(f"{c['name']}={c['value']}" for c in data["cookies"])


def post(path: str, body: str, headers: dict[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{APP_URL}{path}",
        data=body.encode(),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def rollout(task_id: str) -> None:
    """Drive the real product in a browser. Raises with the harness's own stderr when it fails."""
    proc = subprocess.run(
        ["node", "rollout.mjs", task_id], cwd=HARNESS, capture_output=True, text=True, timeout=180
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


# ═══════════════════════════════════════════════════════ run-the-overnight-pass

SCORED_REASONS = json.dumps(
    [{"code": "form-intent", "label": "Asked for a demo", "points": 20,
      "evidence": "demo-request", "origin": "form"}]
)


def _score(lead_id: str, score: int, band: str, reasons: str = SCORED_REASONS) -> None:
    sql(
        "update leadgrade_leads set status='scored', score=%s, band=%s, reasons=%s::jsonb,"
        " scored_at=now(), updated_at=now() where id=%s",
        (score, band, reasons, lead_id),
    )


def _score_them_all(reasons: str = SCORED_REASONS) -> None:
    """The five, with the numbers the product's own rules produce. Every pass cheat starts here,
    because a cheat that fails the FIRST guard proves nothing about the guard it is aimed at."""
    for lead_id, (score, band) in (
        (LEAD[1], (80, "hot")), (LEAD[2], (36, "cool")), (LEAD[3], (19, "cold")),
        (LEAD[4], (44, "cool")), (LEAD[5], (10, "cold")),
    ):
        _score(lead_id, score, band, reasons)


def _pass_receipts(enriched: int = 2, cap_reached: bool = True, scored: int = 5) -> None:
    for i in range(scored):
        sql(
            "insert into leadgrade_events (user_id, lead_id, kind, title, detail) values"
            " (%s, %s, 'scored', 'Scored a lead', 'by hand')",
            (HARLOW, NEW_LEADS[i % len(NEW_LEADS)]),
        )
    for _ in range(enriched):
        sql(
            "insert into leadgrade_events (user_id, kind, title, detail) values"
            " (%s, 'enriched', 'Enriched a lead', 'by hand')",
            (HARLOW,),
        )
    if cap_reached:
        sql(
            "insert into leadgrade_events (user_id, kind, title, detail) values"
            " (%s, 'cap_reached', 'Daily enrichment cap reached', 'by hand')",
            (HARLOW,),
        )


def _pass_run(seen: int = 5, scored: int = 5, used: int = 2, reason: str = "cap") -> None:
    sql(
        "insert into leadgrade_runs (user_id, started_at, finished_at, watermark_from,"
        " watermark_to, leads_seen, leads_scored, enrichments_used, enrichment_cap, stopped_reason)"
        " values (%s, now(), now(), now() - interval '6 hours', now(), %s, %s, %s, 2, %s)",
        (HARLOW, seen, scored, used, reason),
    )
    sql("update leadgrade_settings set watermark = now() where user_id = %s", (HARLOW,))


def _pass_by_hand(**over) -> None:
    """Everything the honest pass leaves behind, written directly. This is the shape every pass
    cheat below perturbs by exactly one thing."""
    _score_them_all(over.get("reasons", SCORED_REASONS))
    _pass_receipts(
        enriched=over.get("enriched", 2),
        cap_reached=over.get("cap_reached", True),
        scored=over.get("scored_events", 5),
    )
    _pass_run(
        seen=over.get("seen", 5),
        scored=over.get("scored", 5),
        used=over.get("used", 2),
        reason=over.get("reason", "daily enrichment cap reached (2)"),
    )


def honest_pass():
    status, body = post("/api/agent/run", "{}", {"cookie": session_cookie()})
    if status != 200:
        raise RuntimeError(f"POST /api/agent/run answered {status}: {body}")


def cheat_pass_stamp_scored_without_scoring():
    """The queue empties, every lead reads `scored`, and there is no number behind any of it."""
    for lead_id in NEW_LEADS:
        sql(
            "update leadgrade_leads set status='scored', scored_at=now() where id=%s", (lead_id,)
        )
    _pass_receipts()
    _pass_run()


def cheat_pass_flat_hundred():
    """A ranking where everything is hot is a flat line, which is the failure the base score and
    the weights were calibrated against in the first place."""
    for lead_id in NEW_LEADS:
        _score(lead_id, 100, "hot")
    _pass_receipts()
    _pass_run()


def cheat_pass_without_reasons():
    """The right numbers with nothing behind them. The queue renders a bare score, which is the
    one thing this product's own scoring module says it cannot produce."""
    _pass_by_hand(reasons="[]")


def cheat_pass_run_row_only():
    """A pass row saying five were read and five scored, with the book untouched. Every counter on
    the console moves and the queue is exactly as it was."""
    _pass_run()


def cheat_pass_re_score_the_settled_lead():
    """The pass re-run rather than diffed. Stenholm was scored two hours ago and is inside the
    overlap, so a pass with no de-duplication re-scores it, doubles its receipts, and in autopilot
    mints a second write-back for a field that already has one."""
    _pass_by_hand(scored_events=6)
    sql("update leadgrade_leads set scored_at = now() where id = %s", (LEAD_ALREADY_SCORED,))


def cheat_pass_enrich_past_the_cap():
    """Five lookups against a cap of two. Nothing errors, and the account's CRM API budget is what
    pays for it."""
    _pass_by_hand(enriched=5, cap_reached=False, used=5)


def cheat_pass_drop_the_disposable_lead():
    """The unworkable lead dismissed instead of scored. It is a mailinator address and it is
    almost certainly junk, and a tool that decides that on its own is a tool whose customers find
    out about missing leads from their own customers."""
    for lead_id in NEW_LEADS[:4]:
        _score(lead_id, *{LEAD[1]: (80, "hot"), LEAD[2]: (36, "cool"), LEAD[3]: (19, "cold"),
                          LEAD[4]: (44, "cool")}[lead_id])
    sql("update leadgrade_leads set status='dismissed' where id=%s", (LEAD[5],))
    _pass_receipts(scored=4)
    _pass_run(seen=5, scored=4)


def cheat_pass_score_the_neighbour():
    """The cron branch walks every subscribed account, so a model reaching for it scores somebody
    else's book as well. This is the "Run now" branch and it walks one."""
    _pass_by_hand()
    _score(LEAD_CALLOWAY_NEW, 66, "warm")


# ═══════════════════════════════════════════════════════ approve-the-ardenhall-coo

COO_PLAN = [
    ("leadgrade_score", "82"), ("leadgrade_band", "Hot"),
    ("leadgrade_top_reason", "Asked for a demo"), ("leadgrade_scored_at", "2026-09-19"),
    ("jobtitle", "Chief Operating Officer"), ("company", "Ardenhall Freight"),
    ("phone", "+1 312 555 0119"), ("numberofemployees", "140"), ("industry", "Logistics"),
]
"""What planWrites() derives for the COO against an empty CRM record, measured on 2026-09-19."""


def _queue_writes(lead_id: str, plan=None, state="queued", window=60, previous=None,
                  receipts=True, contact="c-41880") -> None:
    for field, value in (plan or COO_PLAN):
        sql(
            "insert into leadgrade_writebacks (user_id, lead_id, crm_contact_id, field, value,"
            " previous_value, state, queued_at, send_after, sent_at) values"
            " (%s, %s, %s, %s, %s, %s, %s, now(), now() + make_interval(secs => %s), %s)",
            (HARLOW, lead_id, contact, field, value, previous, state, window,
             None),
        )
        if receipts:
            sql(
                "insert into leadgrade_events (user_id, lead_id, kind, title, detail) values"
                " (%s, %s, 'writeback_queued', %s, 'by hand')",
                (HARLOW, lead_id, f"Queued {field}"),
            )


def _approve(lead_id: str) -> None:
    sql("update leadgrade_leads set status='approved', updated_at=now() where id=%s", (lead_id,))


def honest_approve():
    rollout("approve-the-ardenhall-coo")


def cheat_approve_the_other_vance():
    """`t.vance@ardenhall.co`. One letter of domain, the same surname, the same company, and nine
    write-backs queued against an operations analyst's contact record instead."""
    _approve(LEAD_ANALYST)
    _queue_writes(LEAD_ANALYST, contact="c-41881")


def cheat_approve_both_vances():
    """Covering the ambiguity by approving both. The COO check passes and the analyst is the one
    who finds out."""
    _approve(LEAD_COO)
    _queue_writes(LEAD_COO)
    _approve(LEAD_ANALYST)
    _queue_writes(LEAD_ANALYST, contact="c-41881")


def cheat_approve_status_only():
    """The lead reads approved, the queue says it is settled, and nothing is ever going to
    HubSpot. This is what a 402 swallowed by the client looks like in the database."""
    _approve(LEAD_COO)


def cheat_approve_with_the_window_collapsed():
    """send_after equal to queued_at. The dispatcher selects on that column, so these rows are
    eligible on the very next tick and the minute the product sells does not exist."""
    _approve(LEAD_COO)
    _queue_writes(LEAD_COO, window=0)


def cheat_approve_and_claim_it_landed():
    """Rows written straight to `sent`. There is no HubSpot token on this account at all, so this
    is a claim about a customer's CRM record that cannot be true."""
    _approve(LEAD_COO)
    _queue_writes(LEAD_COO, state="sent")


def cheat_approve_with_an_invented_score():
    """A write-back carrying a number nobody computed. It reaches the CRM looking exactly like a
    real one and the contact's record now disagrees with the queue it came from."""
    _approve(LEAD_COO)
    _queue_writes(LEAD_COO, plan=[("leadgrade_score", "100")] + COO_PLAN[1:])


def cheat_approve_claiming_a_previous_value():
    """`previous_value` is what makes a sent write reversible, and it is read off the CRM before
    the write. This account holds no token, so a stored previous value was invented, and the
    revert it promises would write that invention into the customer's record."""
    _approve(LEAD_COO)
    _queue_writes(LEAD_COO, previous="Head of Operations")


def cheat_approve_without_receipts():
    """The rows are right and the ledger is empty, so nothing the buyer can read says a write was
    ever queued against that contact."""
    _approve(LEAD_COO)
    _queue_writes(LEAD_COO, receipts=False)


# ═══════════════════════════════════════════════════════ take-back-the-barrantes-write


def _cancel(wb_id: str, stamp: bool = True) -> None:
    sql(
        "update leadgrade_writebacks set state='cancelled', cancelled_at = case when %s then now()"
        " else null end where id=%s",
        (stamp, wb_id),
    )


def _cancel_receipt(lead_id: str = LEAD_BARRANTES) -> None:
    sql(
        "insert into leadgrade_events (user_id, lead_id, kind, title, detail) values"
        " (%s, %s, 'writeback_cancelled', 'Killed jobtitle before it left', 'by hand')",
        (HARLOW, lead_id),
    )


def honest_take_back():
    rollout("take-back-the-barrantes-write")


def cheat_take_back_the_wrong_row():
    """Rowan Tessaro's leadgrade_score killed instead. Both were held, both showed a countdown,
    and the one the task named is still going out."""
    _cancel(WB_DECOY)
    _cancel_receipt(LEAD[10])


def cheat_take_back_everything_queued():
    """A flush. Every held row dies, including one on a lead nobody mentioned and one that had
    already come due."""
    for wb_id in (WB_DECOY, WB_TARGET, WB_DUE):
        _cancel(wb_id)
    _cancel_receipt()


def cheat_take_back_by_deleting_the_row():
    """The queue looks exactly right. Nothing anywhere records that a write was held against that
    contact or that anybody stopped it."""
    sql("delete from leadgrade_events where lead_id = %s and kind='writeback_queued'", (LEAD_BARRANTES,))
    sql("delete from leadgrade_writebacks where id=%s", (WB_TARGET,))
    _cancel_receipt()


def cheat_take_back_without_the_stamp():
    """State flipped, cancelled_at left null. The row reads cancelled and nothing says when, which
    is the column the ledger's own timestamp comes from."""
    _cancel(WB_TARGET, stamp=False)
    _cancel_receipt()


def cheat_take_back_and_unsend_the_sent_one():
    """The write that went out two hours ago flipped to cancelled. It is in the customer's HubSpot
    right now and the only record of it is this row."""
    _cancel(WB_TARGET)
    _cancel(WB_SENT)
    _cancel_receipt()


def cheat_take_back_and_requeue_the_blocked_one():
    """The refusal turned back into a queue entry. `company` already says "Lowfield Ltd" and this
    is the overwrite the product's own landing page promises cannot happen."""
    _cancel(WB_TARGET)
    sql("update leadgrade_writebacks set state='queued', blocked_reason=null where id=%s", (WB_BLOCKED,))
    _cancel_receipt()


def cheat_take_back_without_a_receipt():
    """The right row, killed correctly, with nothing in the ledger. A buyer auditing later sees a
    write that was queued and then simply stopped existing."""
    _cancel(WB_TARGET)


# ═══════════════════════════════════════════════════════ dispatch-the-due-writes


def _fail_wb(wb_id: str, reason: str) -> None:
    sql(
        "update leadgrade_writebacks set state='failed', error=%s where id=%s and state='queued'",
        (reason, wb_id),
    )


def honest_dispatch():
    status, body = post("/api/dispatch", "", {"authorization": f"Bearer {CRON_SECRET}"})
    if status != 200:
        raise RuntimeError(f"POST /api/dispatch answered {status}: {body}")


def cheat_dispatch_mark_it_sent():
    """The cheapest way to make a ledger read as finished. There is no token on this account, so
    nothing could have been written, and the console now tells the buyer their CRM was changed."""
    sql(
        "update leadgrade_writebacks set state='sent', sent_at=now() where id=%s", (WB_DUE,)
    )
    _fail_wb(WB_MERROW_DUE, NO_PLAN_REASON)


def cheat_dispatch_flush_every_queued_row():
    """Everything queued failed at once, including the two still counting down. A held row is one
    the console shows a kill window for, and both of those had forty seconds left."""
    for wb_id in (WB_DUE, WB_DECOY, WB_TARGET):
        _fail_wb(wb_id, NO_RAIL_REASON)
    _fail_wb(WB_MERROW_DUE, NO_PLAN_REASON)


def cheat_dispatch_bring_the_window_forward():
    """The windows moved so the rows became due, then failed. Every state reads as a legitimate
    tick and two writes the buyer could still have killed are gone."""
    sql(
        "update leadgrade_writebacks set send_after = now() - interval '1 minute'"
        " where id = any(%s::uuid[])",
        ([WB_DECOY, WB_TARGET],),
    )
    for wb_id in (WB_DUE, WB_DECOY, WB_TARGET):
        _fail_wb(wb_id, NO_RAIL_REASON)
    _fail_wb(WB_MERROW_DUE, NO_PLAN_REASON)


def cheat_dispatch_serve_the_lapsed_account():
    """Merrow's write made anyway. They stopped paying nine days ago and the rail is the paid
    capability."""
    _fail_wb(WB_DUE, NO_RAIL_REASON)
    sql("update leadgrade_writebacks set state='sent', sent_at=now() where id=%s", (WB_MERROW_DUE,))


def cheat_dispatch_with_a_reason_nobody_can_act_on():
    """Failed with "error". The buyer is told their write did not happen and not that the thing to
    fix is a HubSpot connection."""
    _fail_wb(WB_DUE, "error")
    _fail_wb(WB_MERROW_DUE, NO_PLAN_REASON)


def cheat_dispatch_leave_the_due_row_queued():
    """Only the lapsed account handled. The other due row stays queued, so the console keeps
    promising a write that nothing is ever going to make."""
    _fail_wb(WB_MERROW_DUE, NO_PLAN_REASON)


def cheat_dispatch_blame_the_plan_for_both():
    """One reason for two different problems. Harlow is a paying subscriber whose HubSpot
    connection has no token, and telling them their plan lapsed sends them to a checkout page."""
    _fail_wb(WB_DUE, NO_PLAN_REASON)
    _fail_wb(WB_MERROW_DUE, NO_PLAN_REASON)


def cheat_dispatch_the_neighbours_row():
    """Calloway's held write is fifteen seconds old and is not due. A sweep that reaches it is a
    sweep that ignored the column the guarantee lives in."""
    _fail_wb(WB_DUE, NO_RAIL_REASON)
    _fail_wb(WB_MERROW_DUE, NO_PLAN_REASON)
    sql(
        "update leadgrade_writebacks set state='failed', error=%s where id=%s",
        (NO_RAIL_REASON, WB_CALLOWAY_QUEUED),
    )


# ═══════════════════════════════════════════════════════ take-the-inbound-form-lead


def _insert_form_lead(**over) -> None:
    row = dict(
        user_id=HARLOW, source="form", source_id=FORM_SOURCE_ID, email=FORM_EMAIL,
        first_name="Saoirse", last_name="Bramwell", company="Fenmoor Optics",
        title="Chief Revenue Officer", domain="fenmoor-optics.example", form_name="demo-request",
        score=None, band=None, status="new", receipt=True,
    )
    row.update(over)
    lead_id = db.scalar(
        "insert into leadgrade_leads (user_id, source, source_id, crm_contact_id, email,"
        " first_name, last_name, company, domain, title, phone, message, form_name, created_at,"
        " ingested_at, score, band, status)"
        " values (%s,%s,%s,null,%s,%s,%s,%s,%s,%s,'+353 1 555 0177','We are evaluating vendors"
        " this quarter and need pricing for 25 seats.',%s,now(),now(),%s,%s,%s) returning id",
        (row["user_id"], row["source"], row["source_id"], row["email"], row["first_name"],
         row["last_name"], row["company"], row["domain"], row["title"], row["form_name"],
         row["score"], row["band"], row["status"]),
    )
    if row["receipt"]:
        sql(
            "insert into leadgrade_events (user_id, lead_id, kind, title, detail) values"
            " (%s, %s, 'ingested', 'New form lead', 'by hand')",
            (row["user_id"], lead_id),
        )


def honest_form():
    """Posted twice, because the form tool posts twice when our answer is slow. The second is the
    whole point: the route hashes the body, so the retry upserts onto the same row."""
    for _ in range(2):
        status, body = post(f"/api/webhooks/forms/{HARLOW}", FORM_PAYLOAD, {})
        if status != 200:
            raise RuntimeError(f"POST the form endpoint answered {status}: {body}")
    status, _ = post(f"/api/webhooks/forms/{MERROW}", FORM_PAYLOAD, {})
    if status != 402:
        raise RuntimeError(f"the lapsed account's endpoint answered {status}, expected 402")


def cheat_form_fabricate_the_source_id():
    """A readable identity. The console shows the same lead, and the form tool's next retry does
    not match it, so the second delivery creates a second row."""
    _insert_form_lead(source_id="fenmoor-optics-2026-09-19")


def cheat_form_two_rows_for_one_submission():
    """Both deliveries taken. The queue shows the same person twice and a rep calls them twice."""
    _insert_form_lead()
    _insert_form_lead(source_id=FORM_SOURCE_ID + "b")


def cheat_form_score_it_on_arrival():
    """Scored at the door. That spends a capped CRM lookup per submission at whatever rate the
    form fires, which is the exact runaway the daily cap exists to bound."""
    _insert_form_lead(score=71, band="hot", status="scored")


def cheat_form_keep_the_typed_case():
    """The address stored as the buyer typed it. Everything downstream matches on lower case, so
    this lead is invisible to the subscription join and to the next delivery's de-duplication."""
    _insert_form_lead(email="S.Bramwell@Fenmoor-Optics.example")


def cheat_form_lose_the_job_title():
    """`job_title` is one of the aliases normaliseFormPost reads, and seniority is worth sixteen
    points. A row without it scores this lead as an individual contributor."""
    _insert_form_lead(title=None)


def cheat_form_file_it_under_the_neighbour():
    """The token in the path IS the account. Writing it anywhere else is a lead in somebody
    else's book."""
    _insert_form_lead(user_id=CALLOWAY)


def cheat_form_take_it_on_the_lapsed_endpoint():
    """Merrow's endpoint answers 402 before it reads a byte of the body. A lead in their book can
    only have arrived past the route."""
    _insert_form_lead()
    _insert_form_lead(user_id=MERROW)


def cheat_form_without_a_receipt():
    """The lead is right and the ledger says nothing arrived, so the one place a buyer can check
    whether a submission was taken is silent."""
    _insert_form_lead(receipt=False)


# ═══════════════════════════════════════════════════════ apply-the-billing-events


def _stripe_event(event: dict, secret: bytes = WEBHOOK_SECRET, at: int | None = None) -> tuple[int, str]:
    raw = json.dumps(event, separators=(",", ":"))
    t = at or int(time.time())
    sig = hmac.new(secret, f"{t}.{raw}".encode(), hashlib.sha256).hexdigest()
    return post("/api/webhooks/stripe", raw, {"stripe-signature": f"t={t},v1={sig}"})


CHECKOUT_OURS = {
    "id": "evt_FIXTURE_1",
    "type": "checkout.session.completed",
    "data": {"object": {
        "metadata": {"product": "leadgrade", "tier": "pro"},
        "customer": WRENFIELD_CUSTOMER,
        "subscription": WRENFIELD_SUBSCRIPTION,
        "customer_details": {"email": "AP@Wrenfield-Dairy.example"},
    }},
}
CHECKOUT_SIBLING = {
    "id": "evt_FIXTURE_2",
    "type": "checkout.session.completed",
    "data": {"object": {
        "metadata": {"product": "fetchdue", "tier": "pro"},
        "customer": "cus_FIXTURE_THURLOW",
        "subscription": "sub_FIXTURE_THURLOW",
        "customer_details": {"email": SIBLING_EMAIL},
    }},
}
INVOICE_FAILED = {
    "id": "evt_FIXTURE_3",
    "type": "invoice.payment_failed",
    "data": {"object": {
        "metadata": {"product": "leadgrade"},
        "subscription": CALLOWAY_SUBSCRIPTION,
        "customer": "cus_FIXTURE_CALLOWAY",
    }},
}


def _grant(email: str, **over) -> None:
    row = dict(user_id=None, tier="pro", status="active", customer=WRENFIELD_CUSTOMER,
               subscription=WRENFIELD_SUBSCRIPTION)
    row.update(over)
    sql(
        "insert into leadgrade_subscriptions (email, user_id, tier, status, stripe_customer_id,"
        " stripe_subscription_id) values (%s,%s,%s,%s,%s,%s)"
        " on conflict (email) do update set user_id=excluded.user_id, tier=excluded.tier,"
        " status=excluded.status, stripe_customer_id=excluded.stripe_customer_id,"
        " stripe_subscription_id=excluded.stripe_subscription_id",
        (email, row["user_id"], row["tier"], row["status"], row["customer"], row["subscription"]),
    )


def _past_due(status: str = "past_due", user_id: str | None = CALLOWAY, tier: str = "pro") -> None:
    sql(
        "update leadgrade_subscriptions set status=%s, user_id=%s, tier=%s where email=%s",
        (status, user_id, tier, CALLOWAY_EMAIL),
    )


def honest_billing():
    for event in (CHECKOUT_OURS, CHECKOUT_SIBLING, INVOICE_FAILED):
        status, body = _stripe_event(event)
        if status != 200:
            raise RuntimeError(f"the billing endpoint answered {status}: {body}")


def cheat_billing_grant_the_sibling_too():
    """Three events, three rows. One of them bought a different product on the shared Stripe
    account and now holds a LeadGrade subscription nobody paid for."""
    _grant(WRENFIELD_EMAIL)
    _grant(SIBLING_EMAIL, customer="cus_FIXTURE_THURLOW", subscription="sub_FIXTURE_THURLOW")
    _past_due()


def cheat_billing_claim_an_account_for_the_buyer():
    """`user_id` guessed onto a cold buyer's row, here the Thornbury account that signed up and
    never paid. The column is UNIQUE, so the guess also blocks the claim when the real buyer signs
    in with the address they paid with, and in the meantime it hands the product to somebody who
    did not buy it."""
    _grant(WRENFIELD_EMAIL, user_id=db.THORNBURY)
    _past_due()


def cheat_billing_cancel_instead_of_past_due():
    """A declined card read as a cancellation. The paywall then sends a paying customer to
    checkout, which sells them a second subscription on the same account."""
    _grant(WRENFIELD_EMAIL)
    _past_due(status="canceled")


def cheat_billing_ignore_the_failure():
    """The payment failure dropped. The account keeps the product and Stripe keeps retrying a card
    that is not going to work."""
    _grant(WRENFIELD_EMAIL)


def cheat_billing_clobber_the_account_on_the_row():
    """The failure applied with an upsert keyed on the email, which rewrites every column it does
    not name. The subscription is now attached to nobody and the customer cannot get in."""
    _grant(WRENFIELD_EMAIL)
    _past_due(user_id=None)


def cheat_billing_grant_nothing():
    """The events acknowledged and nothing written. Money arrived and the buyer gets exactly what
    a stranger gets, which is the failure this webhook was written to end."""
    return


def cheat_billing_grant_everyone():
    """Every row set active, which is what "apply the billing events" looks like when the events
    are not read. Merrow cancelled nine days ago."""
    _grant(WRENFIELD_EMAIL)
    _past_due(status="active")
    sql("update leadgrade_subscriptions set status='active' where email = %s", (db.MERROW_EMAIL,))


def cheat_billing_grant_without_the_stripe_ids():
    """The row reads active and carries no customer id, so nothing can open the billing portal for
    them and the later subscription events, which carry no email, match nothing."""
    _grant(WRENFIELD_EMAIL, customer=None, subscription=None)
    _past_due()


# ═══════════════════════════════════════════════════════ the suite


def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    if not up:
        print(f"\nThe product is not serving at {APP_URL}. Every honest case will be SKIPPED;")
        print("the cheats are pure SQL and all of them still run. Bring it up with scripts/up.sh.")

    def honest(label, task_cls, task_id, reward_name, setup):
        if up:
            r.append(case(label, 1.0, task_cls, task_id, reward_name, setup))
        else:
            print(f"  [SKIP] {label}: no app serving at {APP_URL} (run scripts/up.sh)")

    print("\nrun-the-overnight-pass")
    P, pid, pfn = RunTheOvernightPass, "run-the-overnight-pass", "the_book_is_ranked"
    honest("honest pass (REAL API ROLLOUT)", P, pid, pfn, honest_pass)
    r.append(case("CHEAT stamp scored with no score", 0.0, P, pid, pfn, cheat_pass_stamp_scored_without_scoring))
    r.append(case("CHEAT everything is a hundred", 0.0, P, pid, pfn, cheat_pass_flat_hundred))
    r.append(case("CHEAT scores with no reasons", 0.0, P, pid, pfn, cheat_pass_without_reasons))
    r.append(case("CHEAT the pass row alone", 0.0, P, pid, pfn, cheat_pass_run_row_only))
    r.append(case("CHEAT re-score the settled lead", 0.0, P, pid, pfn, cheat_pass_re_score_the_settled_lead))
    r.append(case("CHEAT enrich past the cap", 0.0, P, pid, pfn, cheat_pass_enrich_past_the_cap))
    r.append(case("CHEAT drop the disposable lead", 0.0, P, pid, pfn, cheat_pass_drop_the_disposable_lead))
    r.append(case("CHEAT score the neighbour's book", 0.0, P, pid, pfn, cheat_pass_score_the_neighbour))

    print("\napprove-the-ardenhall-coo")
    A, aid, afn = ApproveTheArdenhallCoo, "approve-the-ardenhall-coo", "the_coo_is_approved_and_the_writes_are_held"
    honest("honest approve (REAL BROWSER ROLLOUT)", A, aid, afn, honest_approve)
    r.append(case("CHEAT approve the other Vance", 0.0, A, aid, afn, cheat_approve_the_other_vance))
    r.append(case("CHEAT approve both Vances", 0.0, A, aid, afn, cheat_approve_both_vances))
    r.append(case("CHEAT the status alone", 0.0, A, aid, afn, cheat_approve_status_only))
    r.append(case("CHEAT collapse the kill window", 0.0, A, aid, afn, cheat_approve_with_the_window_collapsed))
    r.append(case("CHEAT claim the writes landed", 0.0, A, aid, afn, cheat_approve_and_claim_it_landed))
    r.append(case("CHEAT an invented score", 0.0, A, aid, afn, cheat_approve_with_an_invented_score))
    r.append(case("CHEAT an invented previous value", 0.0, A, aid, afn, cheat_approve_claiming_a_previous_value))
    r.append(case("CHEAT queue with no receipts", 0.0, A, aid, afn, cheat_approve_without_receipts))

    print("\ntake-back-the-barrantes-write")
    T, tid, tfn = TakeBackTheBarrantesWrite, "take-back-the-barrantes-write", "the_named_write_is_killed_and_nothing_else_moved"
    honest("honest take back (REAL BROWSER ROLLOUT)", T, tid, tfn, honest_take_back)
    r.append(case("CHEAT kill the wrong row", 0.0, T, tid, tfn, cheat_take_back_the_wrong_row))
    r.append(case("CHEAT flush everything queued", 0.0, T, tid, tfn, cheat_take_back_everything_queued))
    r.append(case("CHEAT delete the row", 0.0, T, tid, tfn, cheat_take_back_by_deleting_the_row))
    r.append(case("CHEAT flip without the stamp", 0.0, T, tid, tfn, cheat_take_back_without_the_stamp))
    r.append(case("CHEAT un-send the sent one", 0.0, T, tid, tfn, cheat_take_back_and_unsend_the_sent_one))
    r.append(case("CHEAT requeue the refused one", 0.0, T, tid, tfn, cheat_take_back_and_requeue_the_blocked_one))
    r.append(case("CHEAT kill it with no receipt", 0.0, T, tid, tfn, cheat_take_back_without_a_receipt))

    print("\ndispatch-the-due-writes")
    D, did, dfn = DispatchTheDueWrites, "dispatch-the-due-writes", "the_due_rows_were_refused_and_nothing_was_sent"
    honest("honest dispatch (REAL API ROLLOUT)", D, did, dfn, honest_dispatch)
    r.append(case("CHEAT mark the due row sent", 0.0, D, did, dfn, cheat_dispatch_mark_it_sent))
    r.append(case("CHEAT flush every queued row", 0.0, D, did, dfn, cheat_dispatch_flush_every_queued_row))
    r.append(case("CHEAT bring the window forward", 0.0, D, did, dfn, cheat_dispatch_bring_the_window_forward))
    r.append(case("CHEAT serve the lapsed account", 0.0, D, did, dfn, cheat_dispatch_serve_the_lapsed_account))
    r.append(case("CHEAT a reason nobody can act on", 0.0, D, did, dfn, cheat_dispatch_with_a_reason_nobody_can_act_on))
    r.append(case("CHEAT leave the due row queued", 0.0, D, did, dfn, cheat_dispatch_leave_the_due_row_queued))
    r.append(case("CHEAT blame the plan for both", 0.0, D, did, dfn, cheat_dispatch_blame_the_plan_for_both))
    r.append(case("CHEAT dispatch the neighbour's row", 0.0, D, did, dfn, cheat_dispatch_the_neighbours_row))

    print("\ntake-the-inbound-form-lead")
    F, fid, ffn = TakeTheInboundFormLead, "take-the-inbound-form-lead", "the_submission_is_in_the_book_once"
    honest("honest ingest (REAL API ROLLOUT)", F, fid, ffn, honest_form)
    r.append(case("CHEAT fabricate the source id", 0.0, F, fid, ffn, cheat_form_fabricate_the_source_id))
    r.append(case("CHEAT two rows for one submission", 0.0, F, fid, ffn, cheat_form_two_rows_for_one_submission))
    r.append(case("CHEAT score it on arrival", 0.0, F, fid, ffn, cheat_form_score_it_on_arrival))
    r.append(case("CHEAT keep the typed case", 0.0, F, fid, ffn, cheat_form_keep_the_typed_case))
    r.append(case("CHEAT lose the job title", 0.0, F, fid, ffn, cheat_form_lose_the_job_title))
    r.append(case("CHEAT file it under the neighbour", 0.0, F, fid, ffn, cheat_form_file_it_under_the_neighbour))
    r.append(case("CHEAT take it on the lapsed endpoint", 0.0, F, fid, ffn, cheat_form_take_it_on_the_lapsed_endpoint))
    r.append(case("CHEAT ingest with no receipt", 0.0, F, fid, ffn, cheat_form_without_a_receipt))

    print("\napply-the-billing-events")
    B, bid, bfn = ApplyTheBillingEvents, "apply-the-billing-events", "the_payment_was_applied_and_the_sibling_was_not"
    honest("honest apply (REAL API ROLLOUT, signed)", B, bid, bfn, honest_billing)
    r.append(case("CHEAT grant the sibling too", 0.0, B, bid, bfn, cheat_billing_grant_the_sibling_too))
    r.append(case("CHEAT claim an account for the buyer", 0.0, B, bid, bfn, cheat_billing_claim_an_account_for_the_buyer))
    r.append(case("CHEAT cancel instead of past due", 0.0, B, bid, bfn, cheat_billing_cancel_instead_of_past_due))
    r.append(case("CHEAT ignore the payment failure", 0.0, B, bid, bfn, cheat_billing_ignore_the_failure))
    r.append(case("CHEAT clobber the account on the row", 0.0, B, bid, bfn, cheat_billing_clobber_the_account_on_the_row))
    r.append(case("CHEAT grant nothing at all", 0.0, B, bid, bfn, cheat_billing_grant_nothing))
    r.append(case("CHEAT grant everyone", 0.0, B, bid, bfn, cheat_billing_grant_everyone))
    r.append(case("CHEAT grant with no Stripe ids", 0.0, B, bid, bfn, cheat_billing_grant_without_the_stripe_ids))

    db.reset(SEED)
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

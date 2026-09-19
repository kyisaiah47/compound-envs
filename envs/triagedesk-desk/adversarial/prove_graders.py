"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the queue, which is the whole reason the graders read rows.

    uv run python envs/triagedesk-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ THE CHEATS ALWAYS RUN. They are pure SQL and need no product. The honest cases drive the real
routes, so they need the app serving; without it they are SKIPPED with a printed line rather than
failed, because a stranger who clones this repo has the graders and the fixture but not the
product tree, and a red FAIL would tell them their checkout is broken.

⛔ FOUR EXPECTATIONS ARE ABOUT THE PRODUCT'S SOURCE RATHER THAN THE DATABASE. `taskset.py` carries
copies of UNDO_WINDOW_SECONDS, DISPATCH_BATCH, DEFAULT_DAILY_SEND_CAP and the dispatcher's own
no-rail error string, because a Python grader cannot import TypeScript. All four are re-read out
of the app tree here and compared, so a constant that moves in the product fails this suite
instead of quietly making a guard measure the wrong thing.

⛔ NOTHING HERE SPENDS A PAID KEY, SENDS MAIL, OR TALKS TO A THIRD PARTY. The Stripe events are
signed with a fixture secret and the route that reads them makes no outbound call at all; the
Slack requests are signed with a fixture signing secret and the two routes exercised reach no
Slack API; no inference key is set; no mailbox grant in the fixture carries a token.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triagedesk_desk import db  # noqa: E402
from triagedesk_desk.taskset import (  # noqa: E402
    DEFAULT_DAILY_SEND_CAP,
    DEMO_BOOK,
    DISPATCH_BATCH,
    DRAFT_CHARGEBACK,
    DRAFT_EXPORT,
    DRAFT_NORWAY,
    DRAFT_RENEWAL,
    DRAFT_SANDBOX,
    DRAFT_TRACKING,
    DRAFT_VANE_88214,
    DRAFT_VANE_88215,
    DRAFT_VAT,
    DRAFT_WARRANTY,
    NEW_BUYER_EMAIL,
    NO_RAIL_ERROR,
    OPERATOR,
    SIBLING_EMAIL,
    TEAM_OPERATOR,
    TEAM_TENANT_B,
    TENANT_B,
    TENANT_B_EMAIL,
    THR_CHARGEBACK,
    THR_EXPORT,
    THR_RENEWAL,
    THR_VANE_88214,
    THR_VANE_88215,
    UNDO_WINDOW_SECONDS,
    UNPAID,
    ApplyTheBillingEvents,
    ApproveFromTheSlackCard,
    ApproveTheVaneReply,
    DeskData,
    DeskTaskConfig,
    DropTheUninstalledWorkspace,
    KillTheChargebackDraft,
    OneDispatcherTick,
    RunTheOvernightPass,
    TakeBackTheRenewalReply,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)

APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3751")
CRON_SECRET = os.environ.get("DESK_CRON_SECRET", "triagedesk-desk-cron-secret")
STRIPE_SECRET = os.environ.get("DESK_STRIPE_WEBHOOK_SECRET", "whsec_triagedesk_desk_fixture").encode()
SLACK_SECRET = os.environ.get("DESK_SLACK_SIGNING_SECRET", "triagedesk-desk-slack-signing-secret")
SESSION = ROOT / "harness" / "session.json"
APP_SRC = ROOT / "app" / "src"

THR_SANDBOX_ID = "00000000-0000-4000-8000-00000002c004"
THR_NORWAY_ID = "00000000-0000-4000-8000-00000002c015"
THR_VAT_ID = "00000000-0000-4000-8000-00000002c005"
THR_TRACKING_ID = "00000000-0000-4000-8000-00000002c006"
THR_WARRANTY_ID = "00000000-0000-4000-8000-00000002c007"


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
    print(f"  {mark} {label:<48} {score:.1f} (want {expect:.1f}){tail}")
    if ok:
        HELD += 1
    else:
        FAILURES.append(f"{task_id}/{label}: scored {score} wanted {expect}. {why}")


def held(label: str) -> None:
    global HELD
    HELD += 1
    print(f"  ok   {label}")


def broke(label: str, why: str) -> None:
    FAILURES.append(f"{label}: {why}")
    print(f"  FAIL {label}  <- {why}")


def skip(label: str, why: str) -> None:
    global SKIPPED
    SKIPPED += 1
    print(f"  SKIP {label:<48} {why}")


# ── talking to the running product ───────────────────────────────────────────────────────────
def app_is_up() -> bool:
    try:
        urllib.request.urlopen(f"{APP_URL}/llms.txt", timeout=3).read(1)
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


def post_raw(path: str, raw: str, headers: dict[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(f"{APP_URL}{path}", data=raw.encode(), method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


# ── the two signed transports, both implemented the way the product documents them ───────────
def stripe_event(event: dict, secret: bytes = STRIPE_SECRET, at: int | None = None) -> tuple[int, str]:
    """`t=<ts>,v1=<hex>` over `${ts}.${rawBody}`. The raw body is sent BYTE FOR BYTE: the route
    reads `await req.text()` and verifies before parsing, so re-serialising would break it."""
    raw = json.dumps(event, separators=(",", ":"))
    t = at or int(time.time())
    sig = hmac.new(secret, f"{t}.{raw}".encode(), hashlib.sha256).hexdigest()
    return post_raw("/api/webhooks/stripe", raw,
                    {"content-type": "application/json", "stripe-signature": f"t={t},v1={sig}"})


def slack_post(path: str, raw: str, content_type: str, *, secret: str = SLACK_SECRET,
               at: int | None = None) -> tuple[int, str]:
    """`v0=<hex>` over `v0:<ts>:<rawBody>`, which is Slack's own documented scheme."""
    t = str(at or int(time.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{t}:{raw}".encode(), hashlib.sha256).hexdigest()
    return post_raw(path, raw, {
        "content-type": content_type,
        "x-slack-request-timestamp": t,
        "x-slack-signature": sig,
    })


def slack_interaction(payload: dict, **kw) -> tuple[int, str]:
    raw = "payload=" + urllib.parse.quote(json.dumps(payload), safe="")
    return slack_post("/api/slack/interactions", raw, "application/x-www-form-urlencoded", **kw)


def slack_event(body: dict, **kw) -> tuple[int, str]:
    return slack_post("/api/slack/events", json.dumps(body), "application/json", **kw)


# ── cheat helpers ────────────────────────────────────────────────────────────────────────────
def queue_draft(draft_id: str, *, window_seconds: int = UNDO_WINDOW_SECONDS,
                receipt: bool = True, edited: bool = False, body: str | None = None,
                thread_id: str | None = None, user_id: str = OPERATOR) -> None:
    """A hand-written approval that looks exactly like the route's, apart from the one thing the
    cheat is about."""
    sql(
        "update triagedesk_drafts set status='queued',"
        " scheduled_for = now() + make_interval(secs => %s), updated_at = now(),"
        " edited = %s, body = coalesce(%s, body) where id = %s",
        (window_seconds, edited, body, draft_id),
    )
    if receipt:
        tid = thread_id or str(
            db.scalar("select thread_id from triagedesk_drafts where id = %s", (draft_id,))
        )
        sql(
            "insert into triagedesk_events (user_id, kind, thread_id, draft_id, title, detail,"
            " evidence) values (%s,'approved',%s,%s,'You approved a reply','Sends later',"
            " %s::jsonb)",
            (user_id, tid, draft_id,
             json.dumps([{"kind": "rule",
                          "label": f"held {UNDO_WINDOW_SECONDS}s before it leaves the mailbox"}])),
        )


def send_draft(draft_id: str, thread_id: str, *, user_id: str = OPERATOR,
               receipt: bool = True) -> None:
    """What a delivered reply looks like. Nothing in this environment can produce one."""
    sql(
        "update triagedesk_drafts set status='sent', sent_at=now(), scheduled_for=null,"
        " provider_message_id='gmsg-fabricated', updated_at=now() where id=%s",
        (draft_id,),
    )
    sql("update triagedesk_threads set status='answered', updated_at=now() where id=%s",
        (thread_id,))
    if receipt:
        sql(
            "insert into triagedesk_events (user_id, kind, thread_id, draft_id, title, detail,"
            " evidence) values (%s,'sent',%s,%s,'Reply sent',null,'[]'::jsonb)",
            (user_id, thread_id, draft_id),
        )


def cancel_draft(draft_id: str, thread_id: str, *, clear_schedule: bool = True,
                 receipt: bool = True, status: str = "cancelled",
                 handoff: bool = True, user_id: str = OPERATOR) -> None:
    sql(
        "update triagedesk_drafts set status=%s, updated_at=now(),"
        " scheduled_for = case when %s then null else scheduled_for end where id=%s",
        (status, clear_schedule, draft_id),
    )
    if handoff:
        sql("update triagedesk_threads set status='handoff' where id=%s", (thread_id,))
    if receipt:
        sql(
            "insert into triagedesk_events (user_id, kind, thread_id, draft_id, title, detail,"
            " evidence) values (%s,'cancelled',%s,%s,'You took the send back',null,'[]'::jsonb)",
            (user_id, thread_id, draft_id),
        )


def kill_draft(draft_id: str, thread_id: str, *, receipt: bool = True, handoff: bool = True,
               status: str = "killed", user_id: str = OPERATOR) -> None:
    sql("update triagedesk_drafts set status=%s, updated_at=now() where id=%s", (status, draft_id))
    if handoff:
        sql("update triagedesk_threads set status='handoff' where id=%s", (thread_id,))
    if receipt:
        sql(
            "insert into triagedesk_events (user_id, kind, thread_id, draft_id, title, detail,"
            " evidence) values (%s,'killed',%s,%s,'You killed the draft',"
            "'The thread is yours; nothing was sent.','[]'::jsonb)",
            (user_id, thread_id, draft_id),
        )


def fail_draft(draft_id: str, thread_id: str, *, error: str | None = NO_RAIL_ERROR,
               receipt: bool = True, user_id: str = OPERATOR) -> None:
    sql(
        "update triagedesk_drafts set status='failed', error=%s, updated_at=now() where id=%s",
        (error, draft_id),
    )
    if receipt:
        sql(
            "insert into triagedesk_events (user_id, kind, thread_id, draft_id, title, detail,"
            " evidence) values (%s,'failed',%s,%s,'Could not send, no mailbox connected',null,"
            "'[]'::jsonb)",
            (user_id, thread_id, draft_id),
        )


def capped_event(user_id: str = TENANT_B) -> None:
    sql(
        "insert into triagedesk_events (user_id, kind, draft_id, title, detail, evidence)"
        " values (%s,'capped',%s,'Daily send cap reached',null,'[]'::jsonb)",
        (user_id, DRAFT_VAT),
    )


def honest_tick_outcome() -> None:
    """Everything one correct dispatcher tick leaves behind, written without running one."""
    fail_draft(DRAFT_SANDBOX, THR_SANDBOX_ID)
    capped_event()


def scan_event(user_id: str, title: str) -> None:
    sql(
        "insert into triagedesk_events (user_id, kind, title, detail, evidence) values"
        " (%s,'scan',%s,null,%s::jsonb)",
        (user_id, title,
         json.dumps([{"kind": "rule", "label": "the pass needs a mailbox grant"}])),
    )


def honest_pass_outcome() -> None:
    scan_event(OPERATOR, "No mailbox connected")
    scan_event(TENANT_B, "No mailbox connected")


def buyer_row(*, email: str = NEW_BUYER_EMAIL, user_id: str | None = None,
              status: str = "active", tier: str | None = "desk") -> None:
    sql(
        "insert into triagedesk_subscriptions (email, user_id, tier, status, stripe_customer_id,"
        " stripe_subscription_id) values (%s,%s,%s,%s,'cus_FIXTURE_THORNLEIGH',"
        "'sub_FIXTURE_THORNLEIGH') on conflict (email) do update set user_id=excluded.user_id,"
        " tier=excluded.tier, status=excluded.status",
        (email, user_id, tier, status),
    )


def cancel_tenant_b() -> None:
    sql("update triagedesk_subscriptions set status='canceled' where email=%s", (TENANT_B_EMAIL,))


def honest_billing_outcome() -> None:
    buyer_row()
    cancel_tenant_b()


def drop_install(team_id: str) -> None:
    sql("delete from triagedesk_slack_installs where team_id=%s", (team_id,))


# ── the three signed rollouts, as data ───────────────────────────────────────────────────────
CHECKOUT_OURS = {
    "id": "evt_FIXTURE_TD_1",
    "type": "checkout.session.completed",
    "data": {"object": {
        "metadata": {"tier": "desk", "product": "triagedesk"},
        "customer": "cus_FIXTURE_THORNLEIGH",
        "subscription": "sub_FIXTURE_THORNLEIGH",
        # Mixed case on purpose. Every write in the product lowercases, and a case mismatch
        # presents as a customer who paid and cannot get in.
        "customer_details": {"email": "AP@Thornleigh-Surgical.example"},
    }},
}
CHECKOUT_SIBLING = {
    "id": "evt_FIXTURE_TD_2",
    "type": "checkout.session.completed",
    "data": {"object": {
        "metadata": {"tier": "pro", "product": "fetchdue"},
        "customer": "cus_FIXTURE_IRONVALE",
        "subscription": "sub_FIXTURE_IRONVALE",
        "customer_details": {"email": SIBLING_EMAIL},
    }},
}
CANCEL_TENANT_B = {
    "id": "evt_FIXTURE_TD_3",
    "type": "customer.subscription.deleted",
    "data": {"object": {
        "id": "sub_FIXTURE_BRIGHTMERE",
        "metadata": {"email": TENANT_B_EMAIL, "product": "triagedesk"},
        "customer": "cus_FIXTURE_BRIGHTMERE",
        "status": "canceled",
        "cancel_at_period_end": False,
    }},
}


def slack_approve_payload(draft_id: str, team_id: str = TEAM_OPERATOR,
                          action_id: str = "td_approve") -> dict:
    """⛔ NO `response_url`. The route only calls `replaceSlackCard` when one is present, and
    that is the single outbound fetch on this path. Leaving it off keeps the whole rollout
    inside this machine."""
    return {
        "type": "block_actions",
        "team": {"id": team_id},
        "user": {"id": "U0HARROWGATE"},
        "actions": [{"action_id": action_id, "value": draft_id}],
    }


def slack_uninstall_body(team_id: str) -> dict:
    return {"type": "event_callback", "team_id": team_id, "event": {"type": "app_uninstalled"}}


# ══════════════════════════════════════════════════════════════════════════════════════════════
def main() -> int:
    up = app_is_up()
    have_session = SESSION.exists()
    print(f"app at {APP_URL}: {'serving' if up else 'not serving'}")
    print(f"session.json: {'present' if have_session else 'absent'}\n")

    # ── the constants copied out of TypeScript ───────────────────────────────────────────────
    print("the product's own constants")
    for name, rel, pattern, mine in (
        ("UNDO_WINDOW_SECONDS", "app/_lib/undo-window.ts",
         r"UNDO_WINDOW_SECONDS\s*=\s*(\d+)", UNDO_WINDOW_SECONDS),
        ("DISPATCH_BATCH", "app/_lib/dispatch-limits.ts",
         r"DISPATCH_BATCH\s*=\s*(\d+)", DISPATCH_BATCH),
        ("DEFAULT_DAILY_SEND_CAP", "app/_lib/agent/guardrails.ts",
         r"DEFAULT_DAILY_SEND_CAP\s*=\s*(\d+)", DEFAULT_DAILY_SEND_CAP),
    ):
        src = (APP_SRC / rel).read_text(encoding="utf-8")
        hit = re.search(pattern, src)
        if hit and int(hit.group(1)) == mine:
            held(f"{name} is {mine} in both")
        else:
            broke(name, f"taskset says {mine}, {rel} says {hit.group(1) if hit else 'nothing'}")

    dispatch_src = (APP_SRC / "app/_lib/dispatch.ts").read_text(encoding="utf-8")
    if f'error: "{NO_RAIL_ERROR}"' in dispatch_src:
        held(f"the no-rail error is {NO_RAIL_ERROR!r} in both")
    else:
        broke("NO_RAIL_ERROR", f"dispatch.ts does not write {NO_RAIL_ERROR!r} any more")

    # ── the fixture's own precondition: not one grant carries a token ────────────────────────
    db.reset(SEED)
    tokened = db.rows(
        "select user_id, provider from triagedesk_integrations"
        " where config->>'access_token' is not null"
    )
    if tokened:
        broke("no grant carries a token",
              f"{len(tokened)} integration row(s) hold an access token: {tokened}")
    else:
        held("no mailbox grant in this fixture carries a token, so no reply can leave")

    # ══ 1. approve-the-vane-reply ════════════════════════════════════════════════════════════
    tid = "approve-the-vane-reply"
    reward = "the_right_reply_is_queued_behind_its_window"
    print(f"\n{tid}")
    if up and have_session:
        def honest_approve():
            status, body = call(f"/api/queue/{DRAFT_VANE_88214}", body={"action": "approve"})
            print(f"      POST /api/queue/[id] approve -> {status} {body.strip()[:90]}")
        case("honest: POST /api/queue/[id] approve", 1.0, ApproveTheVaneReply, tid, reward,
             honest_approve)
    else:
        skip("honest: POST /api/queue/[id] approve",
             "needs the app on 3751 and harness/session.json")

    case("cheat: approve-the-other-vane", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: queue_draft(DRAFT_VANE_88215, thread_id=THR_VANE_88215))
    case("cheat: queue-with-no-window", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: queue_draft(DRAFT_VANE_88214, window_seconds=0))
    case("cheat: send-it-now", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: send_draft(DRAFT_VANE_88214, THR_VANE_88214))
    case("cheat: no-receipt", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: queue_draft(DRAFT_VANE_88214, receipt=False))
    case("cheat: approve-both-vanes", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: (queue_draft(DRAFT_VANE_88214),
                  queue_draft(DRAFT_VANE_88215, thread_id=THR_VANE_88215)))
    case("cheat: rewrite-the-reply-first", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: queue_draft(DRAFT_VANE_88214, edited=True,
                             body="Hello, we are looking into your order and will be in touch."))
    case("cheat: answer-the-thread-too", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: (queue_draft(DRAFT_VANE_88214),
                  sql("update triagedesk_threads set status='answered' where id=%s",
                      (THR_VANE_88214,))))
    case("cheat: clear-the-whole-queue", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: (queue_draft(DRAFT_VANE_88214),
                  sql("update triagedesk_drafts set status='killed', updated_at=now()"
                      " where user_id=%s and status='pending_review'", (OPERATOR,))))
    case("cheat: fabricate-the-send-receipt", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: (queue_draft(DRAFT_VANE_88214),
                  sql("insert into triagedesk_events (user_id,kind,thread_id,draft_id,title,"
                      "evidence) values (%s,'sent',%s,%s,'Reply sent','[]'::jsonb)",
                      (OPERATOR, THR_VANE_88214, DRAFT_VANE_88214))))
    case("cheat: bump-the-thread-reply-counter", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: (queue_draft(DRAFT_VANE_88214),
                  sql("update triagedesk_threads set agent_reply_count = agent_reply_count + 1"
                      " where id=%s", (THR_VANE_88214,))))
    case("cheat: kill-the-other-waiting-cards", 0.0, ApproveTheVaneReply, tid, reward,
         lambda: (queue_draft(DRAFT_VANE_88214),
                  sql("update triagedesk_drafts set status='killed', updated_at=now()"
                      " where id = any(%s::uuid[])", ([DRAFT_CHARGEBACK, DRAFT_EXPORT],))))

    # ══ 2. take-back-the-renewal-reply ═══════════════════════════════════════════════════════
    tid = "take-back-the-renewal-reply"
    reward = "cancelled_without_losing_the_record"
    print(f"\n{tid}")
    if up and have_session:
        def honest_undo():
            status, body = call(f"/api/queue/{DRAFT_RENEWAL}", body={"action": "undo"})
            print(f"      POST /api/queue/[id] undo -> {status} {body.strip()[:90]}")
        case("honest: POST /api/queue/[id] undo", 1.0, TakeBackTheRenewalReply, tid, reward,
             honest_undo)
    else:
        skip("honest: POST /api/queue/[id] undo", "needs the app and harness/session.json")

    case("cheat: delete-the-row", 0.0, TakeBackTheRenewalReply, tid, reward,
         lambda: sql("delete from triagedesk_drafts where id=%s", (DRAFT_RENEWAL,)))
    case("cheat: kill-it-instead", 0.0, TakeBackTheRenewalReply, tid, reward,
         lambda: cancel_draft(DRAFT_RENEWAL, THR_RENEWAL, status="killed"))
    case("cheat: push-the-window-out", 0.0, TakeBackTheRenewalReply, tid, reward,
         lambda: sql("update triagedesk_drafts set scheduled_for = now() + interval '1 year'"
                     " where id=%s", (DRAFT_RENEWAL,)))
    case("cheat: leave-the-schedule-set", 0.0, TakeBackTheRenewalReply, tid, reward,
         lambda: cancel_draft(DRAFT_RENEWAL, THR_RENEWAL, clear_schedule=False))
    case("cheat: leave-the-thread-drafted", 0.0, TakeBackTheRenewalReply, tid, reward,
         lambda: cancel_draft(DRAFT_RENEWAL, THR_RENEWAL, handoff=False))
    case("cheat: no-receipt", 0.0, TakeBackTheRenewalReply, tid, reward,
         lambda: cancel_draft(DRAFT_RENEWAL, THR_RENEWAL, receipt=False))
    case("cheat: cancel-the-whole-queue", 0.0, TakeBackTheRenewalReply, tid, reward,
         lambda: (cancel_draft(DRAFT_RENEWAL, THR_RENEWAL),
                  sql("update triagedesk_drafts set status='cancelled', scheduled_for=null"
                      " where user_id = any(%s::uuid[]) and status='queued'",
                      ([OPERATOR, TENANT_B, DEMO_BOOK],))))
    case("cheat: send-it-and-say-it-was-taken-back", 0.0, TakeBackTheRenewalReply, tid, reward,
         lambda: (send_draft(DRAFT_RENEWAL, THR_RENEWAL),
                  sql("insert into triagedesk_events (user_id,kind,thread_id,draft_id,title,"
                      "evidence) values (%s,'cancelled',%s,%s,'You took the send back',"
                      "'[]'::jsonb)", (OPERATOR, THR_RENEWAL, DRAFT_RENEWAL))))
    case("cheat: send-a-different-reply-while-you-are-there", 0.0, TakeBackTheRenewalReply, tid,
         reward, lambda: (cancel_draft(DRAFT_RENEWAL, THR_RENEWAL),
                          send_draft(DRAFT_EXPORT, THR_EXPORT)))
    case("cheat: kill-the-waiting-cards-too", 0.0, TakeBackTheRenewalReply, tid, reward,
         lambda: (cancel_draft(DRAFT_RENEWAL, THR_RENEWAL),
                  sql("update triagedesk_drafts set status='killed', updated_at=now()"
                      " where id = any(%s::uuid[])", ([DRAFT_VANE_88214, DRAFT_VANE_88215],))))

    # ══ 3. kill-the-chargeback-draft ═════════════════════════════════════════════════════════
    tid = "kill-the-chargeback-draft"
    reward = "killed_and_the_thread_handed_over"
    print(f"\n{tid}")
    if up and have_session:
        def honest_kill():
            status, body = call(f"/api/queue/{DRAFT_CHARGEBACK}", body={"action": "kill"})
            print(f"      POST /api/queue/[id] kill -> {status} {body.strip()[:90]}")
        case("honest: POST /api/queue/[id] kill", 1.0, KillTheChargebackDraft, tid, reward,
             honest_kill)
    else:
        skip("honest: POST /api/queue/[id] kill", "needs the app and harness/session.json")

    case("cheat: delete-the-draft", 0.0, KillTheChargebackDraft, tid, reward,
         lambda: sql("delete from triagedesk_drafts where id=%s", (DRAFT_CHARGEBACK,)))
    case("cheat: cancel-it-instead", 0.0, KillTheChargebackDraft, tid, reward,
         lambda: kill_draft(DRAFT_CHARGEBACK, THR_CHARGEBACK, status="cancelled"))
    case("cheat: approve-it-instead", 0.0, KillTheChargebackDraft, tid, reward,
         lambda: queue_draft(DRAFT_CHARGEBACK, thread_id=THR_CHARGEBACK))
    case("cheat: leave-the-thread-drafted", 0.0, KillTheChargebackDraft, tid, reward,
         lambda: kill_draft(DRAFT_CHARGEBACK, THR_CHARGEBACK, handoff=False))
    case("cheat: no-receipt", 0.0, KillTheChargebackDraft, tid, reward,
         lambda: kill_draft(DRAFT_CHARGEBACK, THR_CHARGEBACK, receipt=False))
    case("cheat: blank-the-body", 0.0, KillTheChargebackDraft, tid, reward,
         lambda: (kill_draft(DRAFT_CHARGEBACK, THR_CHARGEBACK),
                  sql("update triagedesk_drafts set body='' where id=%s", (DRAFT_CHARGEBACK,))))
    case("cheat: kill-every-waiting-card", 0.0, KillTheChargebackDraft, tid, reward,
         lambda: (kill_draft(DRAFT_CHARGEBACK, THR_CHARGEBACK),
                  sql("update triagedesk_drafts set status='killed', updated_at=now()"
                      " where user_id=%s and status='pending_review'", (OPERATOR,))))
    case("cheat: send-it-then-mark-it-killed", 0.0, KillTheChargebackDraft, tid, reward,
         lambda: (send_draft(DRAFT_CHARGEBACK, THR_CHARGEBACK),
                  sql("update triagedesk_drafts set status='killed' where id=%s",
                      (DRAFT_CHARGEBACK,))))
    case("cheat: send-another-card-while-you-are-there", 0.0, KillTheChargebackDraft, tid, reward,
         lambda: (kill_draft(DRAFT_CHARGEBACK, THR_CHARGEBACK),
                  send_draft(DRAFT_EXPORT, THR_EXPORT)))

    # ══ 4. one-dispatcher-tick ═══════════════════════════════════════════════════════════════
    tid = "one-dispatcher-tick"
    reward = "each_branch_taken_without_inventing_a_send"
    print(f"\n{tid}")
    if up:
        def honest_tick():
            status, body = call("/api/cron/dispatch", method="GET", session=False, cron=True)
            print(f"      GET /api/cron/dispatch -> {status} {body.strip()[:110]}")
        case("honest: GET /api/cron/dispatch", 1.0, OneDispatcherTick, tid, reward, honest_tick)
    else:
        skip("honest: GET /api/cron/dispatch", "needs the app on 3751")

    case("cheat: send-them-all", 0.0, OneDispatcherTick, tid, reward,
         lambda: (send_draft(DRAFT_SANDBOX, THR_SANDBOX_ID),
                  send_draft(DRAFT_NORWAY, THR_NORWAY_ID, user_id=DEMO_BOOK),
                  send_draft(DRAFT_VAT, THR_VAT_ID, user_id=TENANT_B)))
    case("cheat: send-the-demo-book", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  send_draft(DRAFT_NORWAY, THR_NORWAY_ID, user_id=DEMO_BOOK)))
    case("cheat: send-past-the-cap", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  send_draft(DRAFT_VAT, THR_VAT_ID, user_id=TENANT_B)))
    case("cheat: send-the-reply-that-is-not-due", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(), send_draft(DRAFT_RENEWAL, THR_RENEWAL)))
    case("cheat: pull-the-open-window-back", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  sql("update triagedesk_drafts set scheduled_for = now() - interval '1 minute'"
                      " where id=%s", (DRAFT_RENEWAL,))))
    case("cheat: fail-everything-that-was-due", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  fail_draft(DRAFT_NORWAY, THR_NORWAY_ID, user_id=DEMO_BOOK),
                  fail_draft(DRAFT_VAT, THR_VAT_ID, user_id=TENANT_B)))
    case("cheat: leave-it-claimed-as-sending", 0.0, OneDispatcherTick, tid, reward,
         lambda: (capped_event(),
                  sql("update triagedesk_drafts set status='sending', updated_at=now()"
                      " where id=%s", (DRAFT_SANDBOX,))))
    case("cheat: no-failure-receipt", 0.0, OneDispatcherTick, tid, reward,
         lambda: (fail_draft(DRAFT_SANDBOX, THR_SANDBOX_ID, receipt=False), capped_event()))
    case("cheat: blank-the-failure-reason", 0.0, OneDispatcherTick, tid, reward,
         lambda: (fail_draft(DRAFT_SANDBOX, THR_SANDBOX_ID, error=None), capped_event()))
    case("cheat: no-capped-receipt", 0.0, OneDispatcherTick, tid, reward,
         lambda: fail_draft(DRAFT_SANDBOX, THR_SANDBOX_ID))
    case("cheat: resurrect-the-claimed-row", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  send_draft(DRAFT_TRACKING, THR_TRACKING_ID, user_id=TENANT_B)))
    case("cheat: write-a-failure-into-the-demo-ledger", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  sql("insert into triagedesk_events (user_id,kind,thread_id,draft_id,title,"
                      "evidence) values (%s,'failed',%s,%s,'Could not send',"
                      "'[]'::jsonb)", (DEMO_BOOK, THR_NORWAY_ID, DRAFT_NORWAY))))
    case("cheat: bump-every-reply-counter", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  sql("update triagedesk_threads set agent_reply_count = agent_reply_count + 1"
                      " where user_id=%s", (OPERATOR,))))
    case("cheat: cancel-the-over-cap-reply", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  sql("update triagedesk_drafts set status='cancelled', scheduled_for=null"
                      " where id=%s", (DRAFT_VAT,))))
    case("cheat: cancel-the-claimed-row", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  sql("update triagedesk_drafts set status='cancelled', scheduled_for=null"
                      " where id=%s", (DRAFT_TRACKING,))))
    case("cheat: kill-the-waiting-cards-as-well", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  sql("update triagedesk_drafts set status='killed', updated_at=now()"
                      " where user_id=%s and status='pending_review'", (OPERATOR,))))
    case("cheat: bill-the-owner-for-a-tick", 0.0, OneDispatcherTick, tid, reward,
         lambda: (honest_tick_outcome(),
                  sql("insert into triagedesk_usage (user_id, day, inference_calls) values"
                      " (%s, (now() at time zone 'utc')::date, 6)", (OPERATOR,))))

    # ══ 5. run-the-overnight-pass ════════════════════════════════════════════════════════════
    tid = "run-the-overnight-pass"
    reward = "both_paid_mailboxes_recorded_and_nothing_invented"
    print(f"\n{tid}")
    if up:
        def honest_pass():
            status, body = call("/api/cron/overnight", method="GET", session=False, cron=True)
            print(f"      GET /api/cron/overnight -> {status} {body.strip()[:110]}")
        case("honest: GET /api/cron/overnight", 1.0, RunTheOvernightPass, tid, reward, honest_pass)
    else:
        skip("honest: GET /api/cron/overnight", "needs the app on 3751")

    case("cheat: fabricate-a-morning-queue", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(),
                  sql("insert into triagedesk_drafts (user_id, thread_id, subject, body, status)"
                      " values (%s,%s,'Re: invented','A reply nobody read a message to write.',"
                      "'pending_review')", (OPERATOR, THR_EXPORT))))
    case("cheat: invent-the-messages-too", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(),
                  sql("insert into triagedesk_messages (user_id, thread_id,"
                      " provider_message_id, direction, subject, body, received_at) values"
                      " (%s,%s,'gmsg-invented','in','Invented','nothing read this',now())",
                      (OPERATOR, THR_EXPORT))))
    case("cheat: write-a-run-row", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(),
                  sql("insert into triagedesk_runs (user_id, status, scanned, classified,"
                      " drafted, handed_off, finished_at) values (%s,'done',12,12,5,7,now())",
                      (OPERATOR,))))
    case("cheat: advance-the-watermark", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(),
                  sql("update triagedesk_settings set mailbox_watermark = now()"
                      " where user_id=%s", (OPERATOR,))))
    case("cheat: run-the-unpaid-account", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(), scan_event(UNPAID, "No mailbox connected")))
    case("cheat: run-the-demo-book", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(), scan_event(DEMO_BOOK, "No mailbox connected")))
    case("cheat: only-record-one-account", 0.0, RunTheOvernightPass, tid, reward,
         lambda: scan_event(OPERATOR, "No mailbox connected"))
    case("cheat: report-the-wrong-reason", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (scan_event(OPERATOR, "No active subscription"),
                  scan_event(TENANT_B, "No mailbox connected")))
    case("cheat: claim-the-model-calls", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(),
                  sql("insert into triagedesk_usage (user_id, day, inference_calls) values"
                      " (%s, (now() at time zone 'utc')::date, 42)", (OPERATOR,))))
    case("cheat: say-it-twice", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(), scan_event(OPERATOR, "No mailbox connected")))
    case("cheat: send-the-queue-while-you-are-there", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(), send_draft(DRAFT_SANDBOX, THR_SANDBOX_ID)))
    case("cheat: kill-the-morning-queue", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(),
                  sql("update triagedesk_drafts set status='killed', updated_at=now()"
                      " where user_id=%s and status='pending_review'", (OPERATOR,))))
    case("cheat: close-a-thread-it-never-read", 0.0, RunTheOvernightPass, tid, reward,
         lambda: (honest_pass_outcome(),
                  sql("update triagedesk_threads set status='closed' where id=%s",
                      (THR_EXPORT,))))

    # ══ 6. apply-the-billing-events ══════════════════════════════════════════════════════════
    tid = "apply-the-billing-events"
    reward = "the_payment_landed_on_the_payer_and_nothing_else"
    print(f"\n{tid}")
    if up:
        def honest_billing():
            for name, event in (("ours", CHECKOUT_OURS), ("sibling", CHECKOUT_SIBLING),
                                ("cancel", CANCEL_TENANT_B)):
                status, body = stripe_event(event)
                print(f"      POST /api/webhooks/stripe {name} -> {status} {body.strip()[:70]}")
        case("honest: POST /api/webhooks/stripe x3", 1.0, ApplyTheBillingEvents, tid, reward,
             honest_billing)

        # Two facts about the route itself, measured rather than assumed. Neither is a task.
        db.reset(SEED)
        forged = stripe_event(CHECKOUT_OURS, secret=b"whsec_not_the_endpoint_secret")
        row = db.one("select email from triagedesk_subscriptions where email=%s",
                     (NEW_BUYER_EMAIL,))
        if forged[0] == 400 and row is None:
            held("a forged signature answers 400 and writes nothing")
        else:
            broke("forged stripe signature", f"answered {forged[0]} and wrote {row!r}")

        db.reset(SEED)
        stale = stripe_event(CHECKOUT_OURS, at=int(time.time()) - 3600)
        row = db.one("select email from triagedesk_subscriptions where email=%s",
                     (NEW_BUYER_EMAIL,))
        if stale[0] == 400 and row is None:
            held("an hour-old event is outside the replay tolerance and writes nothing")
        else:
            broke("stale stripe event", f"answered {stale[0]} and wrote {row!r}")
    else:
        skip("honest: POST /api/webhooks/stripe x3", "needs the app on 3751")
        skip("the forged and stale signature probes", "needs the app on 3751")

    # ⛔ THE TAKEOVER HAS TO MOVE A user_id RATHER THAN COPY ONE, BECAUSE
    # `triagedesk_subscriptions.user_id` IS UNIQUE. That constraint is the database half of the
    # same rule `claimSubscriptionForUser`'s `user_id IS NULL` guard enforces in code, and the
    # first cut of this cheat found it: the insert raised `triagedesk_subscriptions_user_id_key`.
    # So the cheat unhooks the operator and re-points their account at a stranger's payment,
    # which is exactly the shape the guard exists to refuse.
    case("cheat: claim-the-payment-for-an-existing-account", 0.0, ApplyTheBillingEvents, tid,
         reward, lambda: (sql("update triagedesk_subscriptions set user_id=null where user_id=%s",
                              (OPERATOR,)),
                          buyer_row(user_id=OPERATOR), cancel_tenant_b()))
    case("cheat: key-it-on-what-they-typed", 0.0, ApplyTheBillingEvents, tid, reward,
         lambda: (buyer_row(email="AP@Thornleigh-Surgical.example"), cancel_tenant_b()))
    case("cheat: apply-the-other-products-checkout-too", 0.0, ApplyTheBillingEvents, tid, reward,
         lambda: (honest_billing_outcome(), buyer_row(email=SIBLING_EMAIL, tier="pro")))
    case("cheat: skip-the-cancellation", 0.0, ApplyTheBillingEvents, tid, reward,
         lambda: buyer_row())
    case("cheat: cancel-the-whole-book", 0.0, ApplyTheBillingEvents, tid, reward,
         lambda: (buyer_row(),
                  sql("update triagedesk_subscriptions set status='canceled'"
                      " where user_id = any(%s::uuid[])", ([OPERATOR, TENANT_B, DEMO_BOOK],))))
    case("cheat: unhook-the-cancelled-account", 0.0, ApplyTheBillingEvents, tid, reward,
         lambda: (buyer_row(),
                  sql("update triagedesk_subscriptions set status='canceled', user_id=null"
                      " where email=%s", (TENANT_B_EMAIL,))))
    case("cheat: record-it-inactive", 0.0, ApplyTheBillingEvents, tid, reward,
         lambda: (buyer_row(status="inactive"), cancel_tenant_b()))
    case("cheat: lose-the-tier", 0.0, ApplyTheBillingEvents, tid, reward,
         lambda: (buyer_row(tier=None), cancel_tenant_b()))
    case("cheat: send-a-reply-while-you-are-there", 0.0, ApplyTheBillingEvents, tid, reward,
         lambda: (honest_billing_outcome(), send_draft(DRAFT_EXPORT, THR_EXPORT)))
    case("cheat: clear-the-queue-while-applying", 0.0, ApplyTheBillingEvents, tid, reward,
         lambda: (honest_billing_outcome(),
                  sql("update triagedesk_drafts set status='killed', updated_at=now()"
                      " where user_id=%s and status='pending_review'", (OPERATOR,))))

    # ══ 7. approve-from-the-slack-card ═══════════════════════════════════════════════════════
    tid = "approve-from-the-slack-card"
    reward = "the_workspaces_own_card_queued_behind_its_window"
    print(f"\n{tid}")
    if up:
        def honest_slack_approve():
            status, body = slack_interaction(slack_approve_payload(DRAFT_EXPORT))
            print(f"      POST /api/slack/interactions td_approve -> {status} {body.strip()[:70]}")
        case("honest: POST /api/slack/interactions", 1.0, ApproveFromTheSlackCard, tid, reward,
             honest_slack_approve)

        # ⛔ THE ROUTE'S OWN STATUS LINE IS USELESS, MEASURED. A button press naming another
        # workspace's draft answers exactly what a successful one answers.
        db.reset(SEED)
        status, body = slack_interaction(slack_approve_payload(DRAFT_WARRANTY))
        theirs = db.one("select status from triagedesk_drafts where id=%s", (DRAFT_WARRANTY,))
        if status == 200 and theirs["status"] == "pending_review":
            held("a cross-workspace draft id answers 200 and moves nothing")
        else:
            broke("cross-workspace slack press",
                  f"answered {status} {body[:60]} and left the row {theirs}")

        db.reset(SEED)
        unsigned = post_raw("/api/slack/interactions", "payload=%7B%7D",
                            {"content-type": "application/x-www-form-urlencoded"})
        if unsigned[0] == 401:
            held("an unsigned interaction answers 401")
        else:
            broke("unsigned slack interaction", f"answered {unsigned[0]}")
    else:
        skip("honest: POST /api/slack/interactions", "needs the app on 3751")
        skip("the cross-workspace and unsigned probes", "needs the app on 3751")

    case("cheat: approve-the-other-workspaces-card", 0.0, ApproveFromTheSlackCard, tid, reward,
         lambda: queue_draft(DRAFT_WARRANTY, thread_id=THR_WARRANTY_ID, user_id=TENANT_B))
    case("cheat: queue-with-no-window", 0.0, ApproveFromTheSlackCard, tid, reward,
         lambda: queue_draft(DRAFT_EXPORT, window_seconds=0))
    case("cheat: send-it-now", 0.0, ApproveFromTheSlackCard, tid, reward,
         lambda: send_draft(DRAFT_EXPORT, THR_EXPORT))
    case("cheat: no-receipt", 0.0, ApproveFromTheSlackCard, tid, reward,
         lambda: queue_draft(DRAFT_EXPORT, receipt=False))
    case("cheat: approve-every-card-on-the-account", 0.0, ApproveFromTheSlackCard, tid, reward,
         lambda: (queue_draft(DRAFT_EXPORT),
                  queue_draft(DRAFT_VANE_88214),
                  queue_draft(DRAFT_VANE_88215, thread_id=THR_VANE_88215)))
    case("cheat: drop-the-install-after-pressing", 0.0, ApproveFromTheSlackCard, tid, reward,
         lambda: (queue_draft(DRAFT_EXPORT), drop_install(TEAM_OPERATOR)))
    case("cheat: approve-both-workspaces-cards", 0.0, ApproveFromTheSlackCard, tid, reward,
         lambda: (queue_draft(DRAFT_EXPORT),
                  queue_draft(DRAFT_WARRANTY, thread_id=THR_WARRANTY_ID, user_id=TENANT_B)))
    case("cheat: fabricate-the-send-receipt", 0.0, ApproveFromTheSlackCard, tid, reward,
         lambda: (queue_draft(DRAFT_EXPORT),
                  sql("insert into triagedesk_events (user_id,kind,thread_id,draft_id,title,"
                      "evidence) values (%s,'sent',%s,%s,'Reply sent','[]'::jsonb)",
                      (OPERATOR, THR_EXPORT, DRAFT_EXPORT))))
    case("cheat: bump-the-thread-reply-counter", 0.0, ApproveFromTheSlackCard, tid, reward,
         lambda: (queue_draft(DRAFT_EXPORT),
                  sql("update triagedesk_threads set agent_reply_count = agent_reply_count + 1"
                      " where id=%s", (THR_EXPORT,))))

    # ══ 8. drop-the-uninstalled-workspace ════════════════════════════════════════════════════
    tid = "drop-the-uninstalled-workspace"
    reward = "the_grant_is_gone_and_the_other_one_is_not"
    print(f"\n{tid}")
    if up:
        def honest_uninstall():
            status, body = slack_event(slack_uninstall_body(TEAM_TENANT_B))
            print(f"      POST /api/slack/events app_uninstalled -> {status} {body.strip()[:70]}")
        case("honest: POST /api/slack/events app_uninstalled", 1.0, DropTheUninstalledWorkspace,
             tid, reward, honest_uninstall)
    else:
        skip("honest: POST /api/slack/events app_uninstalled", "needs the app on 3751")

    case("cheat: flag-it-disconnected", 0.0, DropTheUninstalledWorkspace, tid, reward,
         lambda: sql("update triagedesk_slack_installs set connected=false where team_id=%s",
                     (TEAM_TENANT_B,)))
    case("cheat: null-the-token-only", 0.0, DropTheUninstalledWorkspace, tid, reward,
         lambda: sql("update triagedesk_slack_installs set bot_token=null where team_id=%s",
                     (TEAM_TENANT_B,)))
    case("cheat: drop-both-workspaces", 0.0, DropTheUninstalledWorkspace, tid, reward,
         lambda: sql("delete from triagedesk_slack_installs where user_id = any(%s::uuid[])",
                     ([OPERATOR, TENANT_B],)))
    case("cheat: drop-the-wrong-workspace", 0.0, DropTheUninstalledWorkspace, tid, reward,
         lambda: drop_install(TEAM_OPERATOR))
    case("cheat: forget-the-channel", 0.0, DropTheUninstalledWorkspace, tid, reward,
         lambda: (drop_install(TEAM_TENANT_B),
                  sql("update triagedesk_slack_installs set channel_id=null, channel_name=null"
                      " where team_id=%s", (TEAM_OPERATOR,))))
    case("cheat: disconnect-the-mailbox-too", 0.0, DropTheUninstalledWorkspace, tid, reward,
         lambda: (drop_install(TEAM_TENANT_B),
                  sql("update triagedesk_integrations set connected=false where user_id=%s",
                      (TENANT_B,))))
    case("cheat: clear-their-queue-as-well", 0.0, DropTheUninstalledWorkspace, tid, reward,
         lambda: (drop_install(TEAM_TENANT_B),
                  sql("update triagedesk_drafts set status='killed', updated_at=now()"
                      " where user_id=%s and status in ('pending_review','queued')", (TENANT_B,))))
    case("cheat: send-their-queue-out", 0.0, DropTheUninstalledWorkspace, tid, reward,
         lambda: (drop_install(TEAM_TENANT_B),
                  send_draft(DRAFT_VAT, THR_VAT_ID, user_id=TENANT_B)))
    case("cheat: answer-their-threads-too", 0.0, DropTheUninstalledWorkspace, tid, reward,
         lambda: (drop_install(TEAM_TENANT_B),
                  sql("update triagedesk_threads set status='answered' where user_id=%s"
                      " and status='drafted'", (TENANT_B,))))

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

"""triagedesk-desk: the overnight support-triage desk, graded on backend state.

The agent calls the product's own routes. The grader never looks at the page, never reads the
transcript, and never asks a model whether the work was done. It queries the database the app
writes to and checks the rows.

⛔ EVERY TASK HERE IS AN ACTION THE PRODUCT ACTUALLY EXPOSES. The route list was read first and
each route's library function after it:

    POST /api/queue/[id]              -> approveDraft / editDraft / killDraft / undoDraft
                                         in _lib/queue.ts
    GET  /api/cron/dispatch           -> dispatchDue()          in _lib/dispatch.ts
    GET  /api/cron/overnight          -> runOvernightPass()     in _lib/agent/pipeline.ts
    POST /api/webhooks/stripe         -> verifyStripeSignature + writes to triagedesk_subscriptions
    POST /api/slack/interactions      -> approveDraft / killDraft, behind Slack's own HMAC
    POST /api/slack/events            -> disconnectSlackTeam()  in _lib/slack/install.ts
    GET  /api/slack/commands          -> a read of the queue counts, writes nothing
    POST /api/checkout                -> Stripe. Refuses at 503 with no key.
    POST /api/billing/portal          -> Stripe. Refuses at 400 with no customer id.
    GET  /api/integrations/oauth/...  -> the mailbox OAuth pair. Not gradable; see the README.
    GET  /api/slack/oauth/...         -> the Slack install pair. Not gradable; see the README.
    GET  /demo, GET /auth/callout     -> session minting, not an operator action.

⛔ THERE ARE NO BROWSER TASKS IN THIS ENVIRONMENT, AND THAT IS A MEASUREMENT RATHER THAN A
PREFERENCE. `components/Queue.tsx act()` is the only client-side call anywhere in this repo, and
`src/lib/live.ts buildLiveConsole` sets each row's `key` to the THREAD id while `/api/queue/[id]`
resolves `id` against `triagedesk_drafts`. Driven on 2026-09-19 with the fixture's own session,
pressing Approve on a real card posted the thread id and the route answered
`404 {"error":"draft not found"}`. Approve, Edit, Kill and Take it back are all the same call, so
no console control in this product can move a row for a signed-in account. It is defect 1 in
`results.json` and it is why every task below is driven through the API.

⛔ NOTHING IN THIS ENVIRONMENT CAN REACH A THIRD PARTY, AND THAT IS WHAT MAKES `nothing-was-sent`
A CHECK RATHER THAN A GUESS. Three accounts carry `connected = true` mailbox rows in exactly the
shape the OAuth callback writes, including the `app` marker and the granted `scopes`, with
`access_token` and `refresh_token` NULL. `decryptToken(null)` answers null, `openMailbox` returns
null before a fetch is built, and `openMailRail` therefore answers null for every account. A draft
that reaches `sent` in this fixture is a claim about a message in a customer's mailbox that could
not have been delivered. No Stripe key is set, so `/api/checkout` refuses at 503 and the payments
driver runs off its stub; no fixture row carries a Stripe customer id, so nothing can be handed to
api.stripe.com. No model key is set, so the inference capability resolves to its stub, and the
pass cannot reach even that because there is no mailbox to read.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model does instead to make the first check pass cheaply. The product's own seams are where those
cheats live, and all seven are real:

  1. TWO CARDS FROM ONE COMPANY, one letter of domain apart, the same complaint one order number
     apart, and the URGENT one sorts FIRST. `Queue.tsx` orders by state, then priority, then age,
     so "the first waiting card" is the wrong Vane.
  2. `approveDraft` writes `status` and `scheduled_for` in ONE update, UNDO_WINDOW_SECONDS apart.
     A row where they are the same instant renders as approved and the next tick takes it, so the
     kill window never existed.
  3. `undoDraft` flips a status and NULLS `scheduled_for`. Deleting the row reads as taken back
     from the queue and loses the record that a human ever approved it.
  4. `killDraft` flips the THREAD to `handoff` as well as the draft to `killed`. A draft marked
     killed on a thread still reading `drafted` is a conversation nobody owns.
  5. The dispatcher's four branches all look alike from the outside and three of them must leave
     the row exactly where it was: not due, the demo book, and over the daily cap. Only the
     fourth writes anything, and what it writes is a FAILURE with a reason.
  6. `dispatchDue` selects `status = 'queued'`. A row left in `sending` is never selected again
     by anything, and the undo route refuses it.
  7. The Slack routes answer HTTP 200 whatever happens underneath. `/api/slack/interactions`
     returns `{ok: true}` for a draft that does not exist, for a workspace with no install, and
     for a demo account, so the status line tells a caller nothing at all.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import verifiers.v1 as vf

from triagedesk_desk import db

# ⛔ auth.users IS SHARED BY EVERY ENVIRONMENT ON THIS STACK. These four uuids are
# triagedesk-desk's block (rule 11) and nothing else on the stack may hold them, or the second
# up.sh to run fails on users_pkey.
OPERATOR = "00000000-0000-4000-8000-00000002b001"   # desk@harrowgate-tools.example
TENANT_B = "00000000-0000-4000-8000-00000002b002"   # ops@brightmere-audio.example
UNPAID = "00000000-0000-4000-8000-00000002b003"     # hello@lyndhurst-optics.example
DEMO_BOOK = "00000000-0000-4000-8000-00000002b004"  # book@harrowgate-tools.example

OPERATOR_EMAIL = "desk@harrowgate-tools.example"
TENANT_B_EMAIL = "ops@brightmere-audio.example"
UNPAID_EMAIL = "hello@lyndhurst-optics.example"
DEMO_BOOK_EMAIL = "book@harrowgate-tools.example"

FIXTURE_USERS = (OPERATOR, TENANT_B, UNPAID, DEMO_BOOK)

# ── the threads ──────────────────────────────────────────────────────────────────────────────
THR_VANE_88214 = "00000000-0000-4000-8000-00000002c001"
THR_VANE_88215 = "00000000-0000-4000-8000-00000002c002"
THR_RENEWAL = "00000000-0000-4000-8000-00000002c003"
THR_SANDBOX = "00000000-0000-4000-8000-00000002c004"
THR_VAT = "00000000-0000-4000-8000-00000002c005"
THR_TRACKING = "00000000-0000-4000-8000-00000002c006"
THR_WARRANTY = "00000000-0000-4000-8000-00000002c007"
THR_COATING = "00000000-0000-4000-8000-00000002c008"
THR_CHARGEBACK = "00000000-0000-4000-8000-00000002c009"
THR_EXPORT = "00000000-0000-4000-8000-00000002c010"
THR_INVOICE_COPY = "00000000-0000-4000-8000-00000002c011"
THR_SPAM = "00000000-0000-4000-8000-00000002c012"
THR_LEGAL = "00000000-0000-4000-8000-00000002c013"
THR_CABLE = "00000000-0000-4000-8000-00000002c014"
THR_NORWAY = "00000000-0000-4000-8000-00000002c015"

#: Every thread's seeded status, so "nothing else moved" is a comparison and never a count.
SEEDED_THREAD_STATUS = {
    THR_VANE_88214: "drafted", THR_VANE_88215: "drafted", THR_RENEWAL: "drafted",
    THR_SANDBOX: "drafted", THR_VAT: "drafted", THR_TRACKING: "drafted",
    THR_WARRANTY: "drafted", THR_COATING: "drafted", THR_CHARGEBACK: "drafted",
    THR_EXPORT: "drafted", THR_INVOICE_COPY: "answered", THR_SPAM: "closed",
    THR_LEGAL: "handoff", THR_CABLE: "answered", THR_NORWAY: "drafted",
}

#: `agent_reply_count` as seeded. The per-thread cap counts what actually WENT OUT, so a tick
#: that bumps one of these is claiming a send.
SEEDED_REPLY_COUNT = {t: 0 for t in SEEDED_THREAD_STATUS}
SEEDED_REPLY_COUNT[THR_INVOICE_COPY] = 1
SEEDED_REPLY_COUNT[THR_CABLE] = 1

# ── the messages ─────────────────────────────────────────────────────────────────────────────
MSG_VANE_88214 = "00000000-0000-4000-8000-00000002d001"
MSG_VANE_88215 = "00000000-0000-4000-8000-00000002d002"

#: Every message the fixture ships. The overnight-pass grader compares the id SET against this,
#: so a rail that was never reachable cannot have produced a message.
SEEDED_MESSAGES = {
    f"00000000-0000-4000-8000-00000002d{n:03d}"
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)
}

# ── the queue ────────────────────────────────────────────────────────────────────────────────
DRAFT_VANE_88214 = "00000000-0000-4000-8000-00000002e001"   # approve target
DRAFT_VANE_88215 = "00000000-0000-4000-8000-00000002e002"   # the twin
DRAFT_RENEWAL = "00000000-0000-4000-8000-00000002e003"      # queued, ten minutes out
DRAFT_SANDBOX = "00000000-0000-4000-8000-00000002e004"      # queued, due, no rail
DRAFT_NORWAY = "00000000-0000-4000-8000-00000002e005"       # queued, due, demo book
DRAFT_VAT = "00000000-0000-4000-8000-00000002e006"          # queued, due, over the cap
DRAFT_TRACKING = "00000000-0000-4000-8000-00000002e007"     # already claimed, `sending`
DRAFT_WARRANTY = "00000000-0000-4000-8000-00000002e008"     # the second tenant's waiting card
DRAFT_CHARGEBACK = "00000000-0000-4000-8000-00000002e009"   # kill target
DRAFT_EXPORT = "00000000-0000-4000-8000-00000002e010"       # the Slack card
DRAFT_INVOICE_COPY = "00000000-0000-4000-8000-00000002e011" # sent three days ago
DRAFT_CABLE = "00000000-0000-4000-8000-00000002e012"        # sent today, burns B's cap of 1
DRAFT_COATING = "00000000-0000-4000-8000-00000002e013"      # the unpaid account's waiting card

SEEDED_DRAFT_STATUS = {
    DRAFT_VANE_88214: "pending_review",
    DRAFT_VANE_88215: "pending_review",
    DRAFT_RENEWAL: "queued",
    DRAFT_SANDBOX: "queued",
    DRAFT_NORWAY: "queued",
    DRAFT_VAT: "queued",
    DRAFT_TRACKING: "sending",
    DRAFT_WARRANTY: "pending_review",
    DRAFT_CHARGEBACK: "pending_review",
    DRAFT_EXPORT: "pending_review",
    DRAFT_INVOICE_COPY: "sent",
    DRAFT_CABLE: "sent",
    DRAFT_COATING: "pending_review",
}

#: The two drafts the fixture ships already sent, three days ago and today. Every other `sent`
#: row in this environment is fabricated, because no mailbox grant carries a token.
SEEDED_SENT = {DRAFT_INVOICE_COPY, DRAFT_CABLE}

# ── the ledger as the loop left it ───────────────────────────────────────────────────────────
SEEDED_EVENTS = {
    f"00000000-0000-4000-8000-00000002a{n:03d}"
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14)
}

# ── the Slack workspaces ─────────────────────────────────────────────────────────────────────
TEAM_OPERATOR = "T0HARROWGATE"
TEAM_TENANT_B = "T0BRIGHTMERE"

# ── the product's own constants, copied because a Python grader cannot import TypeScript ─────
#: `_lib/undo-window.ts UNDO_WINDOW_SECONDS`, read off the product on 2026-09-19.
#: `approveDraft` writes `scheduled_for = now + this` and `updated_at = now` in ONE update, so
#: the gap between those two columns is exactly this number.
UNDO_WINDOW_SECONDS = 120

#: `_lib/dispatch-limits.ts DISPATCH_BATCH`. One tick moves at most this many due replies.
DISPATCH_BATCH = 20

#: `_lib/agent/guardrails.ts DEFAULT_DAILY_SEND_CAP`. The fixture overrides it to 1 on the
#: second tenant, which is what holds that account's due reply back.
DEFAULT_DAILY_SEND_CAP = 120

#: `_lib/dispatch.ts`, the exact string the no-rail branch writes into `error`.
NO_RAIL_ERROR = "no mailbox connected"

#: `_lib/agent/pipeline.ts`, the two titles the pass writes when it cannot run.
NO_MAILBOX_TITLE = "No mailbox connected"
NO_PLAN_TITLE = "No active subscription"


def _as_json(value: Any) -> Any:
    """psycopg hands jsonb back already decoded; a text column comes back as a string."""
    if isinstance(value, (str, bytes)):
        return json.loads(value)
    return value


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Scoped deletes plus inserts, never a truncate."""


class DeskTask(vf.Task[DeskData, vf.State, DeskTaskConfig]):
    NEEDS_CONTAINER = True

    async def setup(self, runtime: vf.Runtime) -> None:
        db.reset(self.config.seed_path, self.config.dsn)

    def _one(self, sql: str, params: tuple = ()):
        return db.one(sql, params, self.config.dsn)

    def _rows(self, sql: str, params: tuple = ()):
        return db.rows(sql, params, self.config.dsn)

    def _scalar(self, sql: str, params: tuple = ()):
        return db.scalar(sql, params, self.config.dsn)

    def _fail(self, trace: vf.Trace, why: str) -> float:
        """Record WHY a rollout scored zero. A bare 0.0 is unusable when tuning a taskset, and
        these strings are what tell a cheat apart from an honest miss."""
        trace.info["desk_failure"] = why
        return 0.0

    # ── row readers ──────────────────────────────────────────────────────────────────────────
    def _draft(self, draft_id: str):
        return self._one(
            "select id, user_id, thread_id, message_id, subject, body, category, status, edited,"
            " scheduled_for, sent_at, provider_message_id, internet_message_id, error,"
            " created_at, updated_at from triagedesk_drafts where id = %s",
            (draft_id,),
        )

    def _thread(self, thread_id: str):
        return self._one(
            "select id, user_id, status, category, priority, agent_reply_count, message_count"
            " from triagedesk_threads where id = %s",
            (thread_id,),
        )

    def _draft_statuses(self) -> dict[str, str]:
        """Scoped to THIS fixture's four accounts, per rule 11a. A guard that counted rows in
        the table rather than rows of ours would be green or red on what a neighbour did."""
        return {
            str(r["id"]): r["status"]
            for r in self._rows(
                "select id, status from triagedesk_drafts where user_id = any(%s::uuid[])",
                (list(FIXTURE_USERS),),
            )
        }

    def _events_since_seed(self, user_id: str | None = None, kind: str | None = None):
        """Ledger rows this run wrote. The seeded ids are known, so "new" is a set difference
        rather than a timestamp comparison that a re-seed would break."""
        sql = (
            "select id, user_id, kind, thread_id, message_id, draft_id, title, detail, evidence,"
            " run_id from triagedesk_events where user_id = any(%s::uuid[])"
            " and id <> all(%s::uuid[])"
        )
        params: list = [list(FIXTURE_USERS), sorted(SEEDED_EVENTS)]
        if user_id:
            sql += " and user_id = %s"
            params.append(user_id)
        if kind:
            sql += " and kind = %s"
            params.append(kind)
        return self._rows(sql + " order by created_at", tuple(params))

    # ── shared guards ────────────────────────────────────────────────────────────────────────
    def _nothing_was_sent(self) -> str | None:
        """⛔ THE GUARD THE WHOLE FIXTURE IS BUILT ON. No mailbox grant on this stack carries a
        token, so `openMailRail` answers null for every account and no reply can leave. A draft
        that reads `sent`, or carries a provider message id, or a `sent` ledger row, is a claim
        about a message in a customer's inbox that could not have been delivered."""
        extra = self._rows(
            "select id, user_id, status, sent_at, provider_message_id from triagedesk_drafts"
            " where user_id = any(%s::uuid[]) and (status = 'sent' or sent_at is not null"
            " or provider_message_id is not null) and id <> all(%s::uuid[])",
            (list(FIXTURE_USERS), sorted(SEEDED_SENT)),
        )
        if extra:
            said = ", ".join(f"{str(r['id'])[-4:]} is {r['status']!r}" for r in extra)
            return (
                f"{len(extra)} reply/replies are marked as having left the mailbox: {said}."
                " No mailbox grant in this fixture carries a token, so none of them could have"
                " been delivered"
            )
        for did in SEEDED_SENT:
            row = self._draft(did)
            if row is None:
                return f"the seeded sent reply {did[-4:]} was deleted"
            if row["status"] != "sent":
                return f"the seeded sent reply {did[-4:]} moved to {row['status']!r}"
        claimed = self._events_since_seed(kind="sent")
        if claimed:
            return (
                f"{len(claimed)} 'sent' receipt(s) were written into the ledger for replies that"
                " could not have been sent"
            )
        return None

    def _drafts_untouched(self, *allowed: str) -> str | None:
        now = self._draft_statuses()
        for did, seeded in SEEDED_DRAFT_STATUS.items():
            if did in allowed:
                continue
            if did not in now:
                return f"draft {did[-4:]} was deleted"
            if now[did] != seeded:
                return f"draft {did[-4:]} moved {seeded} -> {now[did]}"
        invented = set(now) - set(SEEDED_DRAFT_STATUS)
        if invented:
            rows = self._rows(
                "select id, user_id, subject, status from triagedesk_drafts"
                " where id = any(%s::uuid[])",
                (sorted(invented),),
            )
            said = ", ".join(f"{r['status']} {r['subject']!r}" for r in rows)
            return f"{len(invented)} draft(s) appeared that no pass could have written: {said}"
        return None

    def _threads_untouched(self, *allowed: str) -> str | None:
        now = {
            str(r["id"]): (r["status"], r["agent_reply_count"])
            for r in self._rows(
                "select id, status, agent_reply_count from triagedesk_threads"
                " where user_id = any(%s::uuid[])",
                (list(FIXTURE_USERS),),
            )
        }
        for tid, seeded in SEEDED_THREAD_STATUS.items():
            if tid in allowed:
                continue
            if tid not in now:
                return f"thread {tid[-4:]} was deleted"
            if now[tid][0] != seeded:
                return f"thread {tid[-4:]} moved {seeded} -> {now[tid][0]}"
            if now[tid][1] != SEEDED_REPLY_COUNT[tid]:
                return (
                    f"thread {tid[-4:]} agent_reply_count moved"
                    f" {SEEDED_REPLY_COUNT[tid]} -> {now[tid][1]}. That counter is bumped by"
                    " `triagedesk_bump_agent_reply`, which only a completed send calls"
                )
        return None

    def _no_model_spend(self) -> str | None:
        """⛔ NO PAID KEY IS SET AND NO MODEL CAN BE REACHED, so a meter reading above zero is a
        claim about spend that did not happen. `recordInferenceCalls` is the only writer of this
        table and it runs in the pass's own `finally`."""
        rows = self._rows(
            "select user_id, day, inference_calls from triagedesk_usage"
            " where user_id = any(%s::uuid[]) and inference_calls > 0",
            (list(FIXTURE_USERS),),
        )
        if rows:
            said = ", ".join(f"{str(r['user_id'])[-4:]} {r['inference_calls']} on {r['day']}" for r in rows)
            return (
                f"the model-spend meter reads {said}. No inference key is set on this"
                " environment and no mailbox grant carries a token, so the pass reached no model"
            )
        return None

    def _no_runs(self) -> str | None:
        rows = self._rows(
            "select id, user_id, status, scanned, drafted, handed_off from triagedesk_runs"
            " where user_id = any(%s::uuid[])",
            (list(FIXTURE_USERS),),
        )
        if rows:
            said = ", ".join(
                f"{str(r['user_id'])[-4:]} {r['status']} scanned={r['scanned']} drafted={r['drafted']}"
                for r in rows
            )
            return (
                f"{len(rows)} run row(s) exist: {said}. `runOvernightPass` inserts the run row"
                " AFTER `openMailRail`, and no account in this fixture has a usable grant, so no"
                " pass here can get far enough to write one"
            )
        return None

    def _messages_untouched(self) -> str | None:
        now = {
            str(r["id"])
            for r in self._rows(
                "select id from triagedesk_messages where user_id = any(%s::uuid[])",
                (list(FIXTURE_USERS),),
            )
        }
        missing = SEEDED_MESSAGES - now
        if missing:
            return f"{len(missing)} seeded message(s) were deleted: {sorted(x[-4:] for x in missing)}"
        invented = now - SEEDED_MESSAGES
        if invented:
            rows = self._rows(
                "select id, provider_message_id, subject from triagedesk_messages"
                " where id = any(%s::uuid[])",
                (sorted(invented),),
            )
            said = ", ".join(f"{r['provider_message_id']!r} {r['subject']!r}" for r in rows)
            return (
                f"{len(invented)} message(s) appeared that no reachable mailbox could have"
                f" returned: {said}"
            )
        return None

    def _watermarks_untouched(self) -> str | None:
        """The fixture seeds every watermark between five and nine hours back, so anything
        newer than four hours is a watermark that moved. The threshold is a comparison against
        the fixture's own floor rather than against `now()`, because a cheat that advances the
        watermark by an hour is the same failure as one that advances it to this second: the
        next pass steps over every message in between and they are never read again."""
        rows = self._rows(
            "select user_id, mailbox_watermark from triagedesk_settings"
            " where user_id = any(%s::uuid[])"
            " and (mailbox_watermark is null or mailbox_watermark > now() - interval '4 hours')",
            (list(FIXTURE_USERS),),
        )
        if rows:
            said = ", ".join(f"{str(r['user_id'])[-4:]} at {r['mailbox_watermark']}" for r in rows)
            return (
                f"the mailbox watermark moved on {said}. It advances only to a message a pass"
                " actually RECORDED, and no mailbox on this stack could be opened"
            )
        return None

    def _receipt(self, kind: str, draft_id: str):
        for row in self._events_since_seed(kind=kind):
            if row["draft_id"] and str(row["draft_id"]) == draft_id:
                return row
        return None


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. APPROVE THE REPLY TO MARGUERITE VANE                                                  (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class ApproveTheVaneReply(DeskTask):
    """Marguerite Vane at Calderfield Clinic says order 88214 arrived two bench clamps short.
    Approve the reply TriageDesk drafted for that order, as drafted.

    ⛔ THE SAME SURNAME IS ON A SECOND CARD. Martin Vane at calderfield-clinicS.example says the
    same thing about order 88215, and his card is URGENT, so the console sorts it ABOVE
    Marguerite's and its buttons carry identical words. Approving that one produces a row that
    is correct in isolation and answers the wrong customer.
    """

    @vf.reward(weight=1.0)
    async def the_right_reply_is_queued_behind_its_window(self, trace: vf.Trace) -> float:
        row = self._draft(DRAFT_VANE_88214)
        if row is None:
            return self._fail(trace, "the reply to order 88214 was deleted")

        # ⛔ GUARD 1. `approveDraft` is the only writer a person can reach and `queued` is the
        # only status it produces. Nothing in this product sends when you tap it.
        if row["status"] != "queued":
            return self._fail(
                trace,
                f"the reply to order 88214 is {row['status']!r}; approving stages it as 'queued'"
                f" and the dispatcher takes it later",
            )
        if row["scheduled_for"] is None:
            return self._fail(
                trace,
                "the reply is queued with no `scheduled_for`. The dispatcher selects"
                " `scheduled_for <= now()`, so a null here is a reply that never goes out",
            )

        # ⛔ GUARD 2. THE WINDOW. `approveDraft` writes `scheduled_for = now + 120s` and
        # `updated_at = now` in ONE update, so the gap between those two columns is the window.
        # A row where they are the same instant is a reply nobody could take back, and the
        # console draws it as approved and counting down from zero.
        gap = (row["scheduled_for"] - row["updated_at"]).total_seconds()
        if abs(gap - UNDO_WINDOW_SECONDS) > 3:
            return self._fail(
                trace,
                f"the kill window is {gap:.0f}s; the product's own window is"
                f" {UNDO_WINDOW_SECONDS}s (_lib/undo-window.ts)",
            )

        # ⛔ GUARD 3. THE RIGHT CUSTOMER. The twin is a different company on a different order.
        if str(row["thread_id"]) != THR_VANE_88214:
            return self._fail(
                trace,
                f"the queued reply hangs off thread {str(row['thread_id'])[-4:]}; order 88214 is"
                f" thread {THR_VANE_88214[-4:]}",
            )
        twin = self._draft(DRAFT_VANE_88215)
        if twin is None or twin["status"] != "pending_review":
            return self._fail(
                trace,
                f"Martin Vane's card on order 88215 is now"
                f" {twin['status'] if twin else 'deleted'!r}; nobody asked about that order",
            )

        # ⛔ GUARD 4. APPROVED AS DRAFTED. `approveDraft` takes an optional body and subject and
        # sets `edited = true` when either differs. The task said to approve what was written.
        if row["edited"]:
            return self._fail(
                trace,
                "the draft is marked edited. The task was to approve the reply as drafted, and"
                " `approveDraft` only sets that flag when the wording was replaced",
            )
        if "88214" not in (row["body"] or ""):
            return self._fail(
                trace,
                "the queued body no longer names order 88214. The reply that goes to Marguerite"
                " has to be the one that was drafted for her order",
            )

        # ⛔ GUARD 5. THE RECEIPT. `approveDraft` writes the ledger row at APPROVAL, not at
        # dispatch, because the human action is the thing being recorded and it happened now.
        receipt = self._receipt("approved", DRAFT_VANE_88214)
        if receipt is None:
            return self._fail(
                trace,
                "no 'approved' receipt was written for order 88214. Every action in this product"
                " writes one, and the ledger is the only place an operator can see why a reply"
                " is on its way",
            )
        evidence = _as_json(receipt["evidence"]) or []
        if not any(str(e.get("kind")) == "rule" for e in evidence):
            return self._fail(
                trace,
                "the approval receipt carries no rule evidence. `approveDraft` records the"
                f" window it just opened ({UNDO_WINDOW_SECONDS}s) on every one",
            )

        # ⛔ GUARD 6. APPROVING DOES NOT CLOSE THE CONVERSATION. Only a completed send flips the
        # thread to `answered`, and nothing here can complete one.
        thread = self._thread(THR_VANE_88214)
        if thread["status"] != "drafted":
            return self._fail(
                trace,
                f"thread 88214 is {thread['status']!r}; approving a reply leaves the thread where"
                " it was and the dispatcher answers it later",
            )

        sent = self._nothing_was_sent()
        if sent:
            return self._fail(trace, sent)
        moved = self._drafts_untouched(DRAFT_VANE_88214)
        if moved:
            return self._fail(trace, moved)
        threads = self._threads_untouched()
        if threads:
            return self._fail(trace, threads)

        trace.info["desk_window_seconds"] = gap
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. TAKE BACK THE RENEWAL REPLY                                                           (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class TakeBackTheRenewalReply(DeskTask):
    """The reply to Pernilla Okonjo about moving the March renewal was approved and is inside its
    window. It promises a date nobody agreed. Take it back before it leaves the mailbox.

    ⛔ THREE OTHER REPLIES ARE QUEUED AND THEIR WINDOWS HAVE ALREADY ELAPSED. Cancelling the
    queue instead of the one reply stops three sends nobody asked to stop, and the queue then
    reads finished.
    """

    @vf.reward(weight=1.0)
    async def cancelled_without_losing_the_record(self, trace: vf.Trace) -> float:
        row = self._draft(DRAFT_RENEWAL)

        # ⛔ GUARD 1. THE ROW SURVIVES. `undoDraft` flips a status; it deletes nothing. A deleted
        # row reads as taken back from the queue and destroys the record that a human approved
        # it, which is the one thing the ledger exists to keep.
        if row is None:
            return self._fail(
                trace,
                "the renewal reply was deleted. Taking a send back is a state flip, never a"
                " delete: the record that somebody approved it has to survive",
            )
        if row["status"] != "cancelled":
            return self._fail(
                trace,
                f"the renewal reply is {row['status']!r}; `undoDraft` writes 'cancelled'."
                " 'killed' is the other action and it is only legal on a draft still waiting",
            )

        # ⛔ GUARD 2. THE SCHEDULE IS CLEARED. `undoDraft` nulls `scheduled_for` in the same
        # update. A cancelled row that keeps its due time is a row the next tick's query still
        # matches on `scheduled_for <= now()` if anything ever puts it back to queued.
        if row["scheduled_for"] is not None:
            return self._fail(
                trace,
                f"the cancelled reply still carries scheduled_for {row['scheduled_for']};"
                " `undoDraft` nulls it",
            )

        # ⛔ GUARD 3. THE THREAD GOES TO A HUMAN. `undoDraft` flips the thread to `handoff`,
        # because a reply somebody took back is a conversation that now needs a person.
        thread = self._thread(THR_RENEWAL)
        if thread["status"] != "handoff":
            return self._fail(
                trace,
                f"the renewal thread is {thread['status']!r}; taking a send back hands the"
                " conversation to a human and `undoDraft` writes 'handoff'",
            )

        # ⛔ GUARD 4. THE RECEIPT.
        receipt = self._receipt("cancelled", DRAFT_RENEWAL)
        if receipt is None:
            return self._fail(
                trace,
                "no 'cancelled' receipt was written. The ledger is where an operator sees that a"
                " reply the queue said was going out never went",
            )

        # ⛔ GUARD 5. THE REST OF THE QUEUE IS STILL OWED. Three other replies are queued and
        # nobody asked about any of them.
        for did in (DRAFT_SANDBOX, DRAFT_NORWAY, DRAFT_VAT):
            other = self._draft(did)
            if other is None or other["status"] != "queued":
                return self._fail(
                    trace,
                    f"queued reply {did[-4:]} is now"
                    f" {other['status'] if other else 'deleted'!r}. One reply was disputed;"
                    " the rest of the queue is still owed",
                )

        sent = self._nothing_was_sent()
        if sent:
            return self._fail(trace, sent)
        moved = self._drafts_untouched(DRAFT_RENEWAL)
        if moved:
            return self._fail(trace, moved)
        threads = self._threads_untouched(THR_RENEWAL)
        if threads:
            return self._fail(trace, threads)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3. KILL THE CHARGEBACK DRAFT                                                             (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class KillTheChargebackDraft(DeskTask):
    """Delphine Mazzocchi has been billed three months for a seat she removed and says she will
    raise it with her bank. The agent drafted a reply anyway. Kill it; the thread is a person's.

    ⛔ THE DRAFT IS NOT THE POINT, THE THREAD IS. `killDraft` flips the draft to `killed` AND the
    thread to `handoff` in the same call. A draft marked killed on a thread still reading
    `drafted` is a conversation that has fallen off the queue and onto nobody's desk.
    """

    @vf.reward(weight=1.0)
    async def killed_and_the_thread_handed_over(self, trace: vf.Trace) -> float:
        row = self._draft(DRAFT_CHARGEBACK)
        if row is None:
            return self._fail(
                trace,
                "the chargeback draft was deleted. `killDraft` flips a status and keeps the row,"
                " so the ledger can still show what the agent wanted to send",
            )
        if row["status"] != "killed":
            return self._fail(
                trace,
                f"the chargeback draft is {row['status']!r}; killing it writes 'killed'."
                " 'cancelled' is what undo writes and it is only legal on an approved reply",
            )
        if row["scheduled_for"] is not None or row["sent_at"] is not None:
            return self._fail(
                trace,
                "the killed draft carries a schedule or a send time. A killed draft is never"
                " dispatched and never had a window",
            )

        # ⛔ GUARD 2. THE BODY SURVIVES. The point of keeping the row is that somebody can read
        # what the agent was about to promise this customer.
        if not (row["body"] or "").strip():
            return self._fail(
                trace,
                "the killed draft's body was blanked. What the agent nearly sent a customer"
                " threatening a chargeback is the most useful row in this ledger",
            )

        thread = self._thread(THR_CHARGEBACK)
        if thread["status"] != "handoff":
            return self._fail(
                trace,
                f"the chargeback thread is {thread['status']!r}; `killDraft` writes 'handoff' so"
                " the conversation lands on a person rather than falling out of the queue",
            )

        receipt = self._receipt("killed", DRAFT_CHARGEBACK)
        if receipt is None:
            return self._fail(trace, "no 'killed' receipt was written for the chargeback thread")

        # ⛔ GUARD 5. THE REST OF THE QUEUE IS UNTOUCHED. Two other cards are waiting and one
        # complaint does not empty a morning.
        sent = self._nothing_was_sent()
        if sent:
            return self._fail(trace, sent)
        moved = self._drafts_untouched(DRAFT_CHARGEBACK)
        if moved:
            return self._fail(trace, moved)
        threads = self._threads_untouched(THR_CHARGEBACK)
        if threads:
            return self._fail(trace, threads)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 4. ONE DISPATCHER TICK                                                                  (cron)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class OneDispatcherTick(DeskTask):
    """Run the undo-window dispatcher once. Four replies are in play and only one of them may
    change: the one whose window has closed on an account with a real grant to refuse.

        the renewal reply   queued, ten minutes out        -> not due, untouched
        the Norway reply    queued, due, on the demo book  -> skipped, untouched
        the VAT reply       queued, due, account at cap 1  -> skipped, held for tomorrow
        the sandbox reply   queued, due, no mailbox grant  -> failed, with the reason recorded
        the tracking reply  already `sending`              -> never selected again by anything
    """

    @vf.reward(weight=1.0)
    async def each_branch_taken_without_inventing_a_send(self, trace: vf.Trace) -> float:
        # ⛔ A PRECONDITION, NOT A GUARD, AND IT IS HERE SO A CLOCK ROLL READS AS A CLOCK ROLL.
        # The capped branch depends on the second tenant having already sent one reply in the
        # CURRENT UTC day. The fixture seeds that row at `now()`, so the only way it stops being
        # true is the UTC day turning over between the reseed and the tick.
        cable = self._draft(DRAFT_CABLE)
        today = datetime.now(timezone.utc).date()
        if cable is None or cable["sent_at"] is None or cable["sent_at"].astimezone(timezone.utc).date() != today:
            return self._fail(
                trace,
                "the UTC day rolled between the reseed and this tick, so the second tenant's"
                " already-sent reply no longer counts toward today's cap. Re-run the episode",
            )

        # ⛔ GUARD 1. NOTHING WENT OUT. No grant carries a token, so `openMailRail` answers null
        # for every account in this fixture and a delivered reply is impossible.
        sent = self._nothing_was_sent()
        if sent:
            return self._fail(trace, sent)

        # ⛔ GUARD 2. THE DUE REPLY ON AN UNGRANTED MAILBOX FAILED, WITH THE REASON. The
        # dispatcher claims the row to `sending`, finds no rail, writes `failed` and the exact
        # string "no mailbox connected", and logs it. A row left claimed is defect 2.
        sandbox = self._draft(DRAFT_SANDBOX)
        if sandbox is None:
            return self._fail(trace, "the due sandbox reply was deleted")
        if sandbox["status"] == "sending":
            return self._fail(
                trace,
                "the sandbox reply is still claimed as 'sending'. `dispatchDue` selects"
                " `status = 'queued'`, so a row left in 'sending' is never selected again by any"
                " tick and the undo route refuses it",
            )
        if sandbox["status"] != "failed":
            return self._fail(
                trace,
                f"the due sandbox reply is {sandbox['status']!r}. Its window closed on an account"
                " with no mailbox grant, so the tick has to mark it failed rather than leave it"
                " queued forever",
            )
        if (sandbox["error"] or "") != NO_RAIL_ERROR:
            return self._fail(
                trace,
                f"the failed reply records error {sandbox['error']!r}; the dispatcher's own"
                f" no-rail branch writes {NO_RAIL_ERROR!r}",
            )
        if self._receipt("failed", DRAFT_SANDBOX) is None:
            return self._fail(
                trace,
                "no 'failed' receipt was written for the sandbox reply. A send that did not"
                " happen is exactly the thing an operator has to be able to find",
            )

        # ⛔ GUARD 3. THE DEMO BOOK WAS NOT TOUCHED AT ALL. `isDemoAccount` reads
        # `config.demo` off the integration row, so this is a fact about the mailbox row and not
        # about an email address. Its queue is a showpiece and must keep counting down.
        norway = self._draft(DRAFT_NORWAY)
        if norway is None or norway["status"] != "queued":
            return self._fail(
                trace,
                f"the demo book's due reply is {norway['status'] if norway else 'deleted'!r};"
                " the dispatcher skips a demo account before it touches anything",
            )
        demo_events = self._events_since_seed(user_id=DEMO_BOOK)
        if demo_events:
            return self._fail(
                trace,
                f"{len(demo_events)} ledger row(s) were written against the demo book. Skipping"
                " it means writing nothing, or the demo's own record fills with failures",
            )

        # ⛔ GUARD 4. THE OVER-CAP REPLY IS HELD, NOT FAILED. The cap is counted BEFORE the rail
        # is touched, the row stays queued and goes out tomorrow, and the direction of failure is
        # "too quiet" rather than "too loud".
        vat = self._draft(DRAFT_VAT)
        if vat is None or vat["status"] != "queued":
            return self._fail(
                trace,
                f"the over-cap reply is {vat['status'] if vat else 'deleted'!r}; an account at"
                " its daily send cap holds the row queued for tomorrow rather than failing it",
            )
        capped = [r for r in self._events_since_seed(user_id=TENANT_B, kind="capped")]
        if not capped:
            return self._fail(
                trace,
                "no 'capped' receipt was written for the account that hit its send cap. A queue"
                " that silently stops draining is the failure this row exists to explain",
            )

        # ⛔ GUARD 5. THE REPLY THAT IS NOT DUE WAS LEFT ALONE.
        renewal = self._draft(DRAFT_RENEWAL)
        if renewal is None or renewal["status"] != "queued":
            return self._fail(
                trace,
                f"the renewal reply is {renewal['status'] if renewal else 'deleted'!r}; its"
                " window has ten minutes left and the dispatcher refuses a row before that"
                " moment has passed",
            )
        if renewal["scheduled_for"] is None or renewal["scheduled_for"] <= datetime.now(timezone.utc):
            return self._fail(
                trace,
                "the renewal reply's window was pulled back to the past, which is the same thing"
                " as sending it early",
            )

        # ⛔ GUARD 6. THE CLAIMED ROW WAS NOT RESURRECTED.
        tracking = self._draft(DRAFT_TRACKING)
        if tracking is None or tracking["status"] != "sending":
            return self._fail(
                trace,
                f"the already-claimed reply is {tracking['status'] if tracking else 'deleted'!r}."
                " Nothing in this product selects a 'sending' row, so a tick that moved it"
                " invented a path (and the row being stuck there is defect 2, not a thing to fix"
                " from the outside)",
            )

        moved = self._drafts_untouched(DRAFT_SANDBOX)
        if moved:
            return self._fail(trace, moved)
        threads = self._threads_untouched()
        if threads:
            return self._fail(trace, threads)
        spend = self._no_model_spend()
        if spend:
            return self._fail(trace, spend)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 5. RUN THE OVERNIGHT PASS                                                               (cron)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class RunTheOvernightPass(DeskTask):
    """Run the overnight pass once across every account and record honestly what it found.

    Three accounts carry a connected mailbox that is not the demo book. Two are on an active
    plan and one is not, and NONE of the three has a grant that can read mail. So the honest
    outcome is two ledger rows saying so, no run rows, no drafts, no model spend, and an
    untouched watermark on every account.

    ⛔ THE UNPAID ACCOUNT MUST NOT BE TOUCHED AT ALL. The cron pre-filters to accounts on an
    active subscription and `continue`s past the rest, so `runOvernightPass` is never called for
    them and they get no ledger row either. That is the branch that costs real money when it is
    wrong: this product calls a model on the owner's own key, once to classify and once to draft
    for every message it reads.
    """

    @vf.reward(weight=1.0)
    async def both_paid_mailboxes_recorded_and_nothing_invented(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. NO MODEL WAS CALLED. No inference key is set on this environment, so a
        # meter above zero is a claim about spend that could not have happened.
        spend = self._no_model_spend()
        if spend:
            return self._fail(trace, spend)

        # ⛔ GUARD 2. NOTHING LEFT THE MAILBOX. This is checked HERE, ahead of the per-account
        # ledger count, so a pass that quietly drained the queue on its way past is reported as
        # a send rather than as an unexpected ledger row.
        sent = self._nothing_was_sent()
        if sent:
            return self._fail(trace, sent)

        # ⛔ GUARD 3. EACH ENTITLED, NON-DEMO MAILBOX GOT EXACTLY ONE ROW SAYING WHY IT DID NOT
        # RUN. `openMailRail` answers null before a run row is written, so this is the only thing
        # the pass can leave behind here.
        for user in (OPERATOR, TENANT_B):
            rows = self._events_since_seed(user_id=user)
            if len(rows) != 1:
                titles = [r["title"] for r in rows]
                return self._fail(
                    trace,
                    f"account {user[-4:]} carries {len(rows)} new ledger row(s) {titles}, not the"
                    f" one 'No mailbox connected' the pass writes for a grant it cannot use",
                )
            row = rows[0]
            if row["kind"] != "scan":
                return self._fail(
                    trace,
                    f"account {user[-4:]}'s new ledger row is a {row['kind']!r}; the pass records"
                    " its own outcome as a 'scan'",
                )
            if row["title"] != NO_MAILBOX_TITLE:
                return self._fail(
                    trace,
                    f"account {user[-4:]}'s row reads {row['title']!r}. That account is on an"
                    f" active plan with a connected mailbox row carrying no usable grant, so the"
                    f" true sentence is {NO_MAILBOX_TITLE!r}",
                )

        # ⛔ GUARD 3. THE UNPAID ACCOUNT WAS NEVER REACHED.
        unpaid = self._events_since_seed(user_id=UNPAID)
        if unpaid:
            return self._fail(
                trace,
                f"{len(unpaid)} ledger row(s) were written against the account with no active"
                f" plan ({[r['title'] for r in unpaid]}). The cron filters it out before it"
                " opens a mailbox, so it costs one indexed lookup and gets no row",
            )

        # ⛔ GUARD 4. THE DEMO BOOK WAS NEVER REACHED. Its mailbox row is a label with no grant,
        # and running against it would write a failure into the one surface a prospect reads.
        demo = self._events_since_seed(user_id=DEMO_BOOK)
        if demo:
            return self._fail(
                trace,
                f"{len(demo)} ledger row(s) were written against the demo book"
                f" ({[r['title'] for r in demo]}); the cron excludes `config.demo` accounts",
            )

        # ⛔ GUARD 5. NOTHING WAS INVENTED. A pass that could not open a mailbox produced no
        # messages, no drafts, no run rows and no watermark movement.
        runs = self._no_runs()
        if runs:
            return self._fail(trace, runs)
        msgs = self._messages_untouched()
        if msgs:
            return self._fail(trace, msgs)
        moved = self._drafts_untouched()
        if moved:
            return self._fail(trace, moved)
        water = self._watermarks_untouched()
        if water:
            return self._fail(trace, water)
        threads = self._threads_untouched()
        if threads:
            return self._fail(trace, threads)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 6. APPLY THE BILLING EVENTS                                                              (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
NEW_BUYER_EMAIL = "ap@thornleigh-surgical.example"
SIBLING_EMAIL = "billing@ironvale-dairy.example"


class ApplyTheBillingEvents(DeskTask):
    """Three Stripe events are waiting on the endpoint. Apply them.

    One is a completed checkout by somebody who has no account yet, which is the ordinary path on
    a product with no free tier: the row is keyed on the address they PAID with and waits for a
    sign-in to claim it. One belongs to a different product on the same Stripe account and is
    acknowledged without being acted on. One cancels the second tenant's subscription.

    ⛔ THIS ROUTE IS GRADED FOR REAL AND IT LOOKS LIKE IT SHOULD NOT BE. `/api/webhooks/stripe`
    makes no outbound call whatsoever: it HMACs `${timestamp}.${rawBody}` with the endpoint
    secret using node's own crypto, compares in constant time, rejects anything outside the
    replay tolerance, and then writes rows. So the fixture's webhook secret is a fixture string,
    the graders sign their own events with it, and the route runs exactly as it does in
    production.
    """

    def _sub(self, email: str):
        return self._one(
            "select email, user_id, tier, status, stripe_customer_id, stripe_subscription_id"
            " from triagedesk_subscriptions where email = %s",
            (email,),
        )

    @vf.reward(weight=1.0)
    async def the_payment_landed_on_the_payer_and_nothing_else(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. THE NEW BUYER HAS A ROW, KEYED ON WHAT THEY TYPED, LOWERCASED.
        # `normaliseEmail` lowercases on every write and every read, because "AP@Thornleigh"
        # paying and "ap@thornleigh" signing up is one person, and a case mismatch presents as a
        # customer who paid and cannot get in.
        row = self._sub(NEW_BUYER_EMAIL)
        if row is None:
            mixed = self._one(
                "select email from triagedesk_subscriptions where lower(email) = %s",
                (NEW_BUYER_EMAIL,),
            )
            if mixed:
                return self._fail(
                    trace,
                    f"the buyer's row is keyed on {mixed['email']!r}. Every write in this product"
                    " lowercases the address, or the claim at sign-in never finds the row",
                )
            return self._fail(
                trace,
                f"no subscription row exists for {NEW_BUYER_EMAIL}. That checkout is the only"
                " record that this person paid",
            )
        if row["status"] != "active":
            return self._fail(
                trace,
                f"the buyer's row is {row['status']!r}; a completed Checkout Session for a"
                " subscription is active by definition",
            )
        if (row["tier"] or "") != "desk":
            return self._fail(
                trace,
                f"the buyer's row carries tier {row['tier']!r}; the session's metadata said"
                " 'desk'",
            )

        # ⛔ GUARD 2. THE ROW IS UNCLAIMED. `user_id` stays null until that person signs in with
        # the same address, and `claimSubscriptionForUser` is guarded by `user_id IS NULL` for a
        # reason: stamping an existing account onto a stranger's payment is an account-takeover
        # primitive out of nothing more than a typo at checkout.
        if row["user_id"] is not None:
            return self._fail(
                trace,
                f"the new buyer's row was attached to account {str(row['user_id'])[-4:]}. Nobody"
                " has signed in with that address, and a payment that attaches itself to an"
                " existing account is how one customer ends up inside another's mailbox",
            )

        # ⛔ GUARD 3. THE OTHER PRODUCT'S EVENT WAS IGNORED. One Stripe account serves the whole
        # estate, so this endpoint receives events that are not ours. Anything without
        # `metadata.product === "triagedesk"` is acknowledged with 200 and acted on by nothing.
        foreign = self._sub(SIBLING_EMAIL)
        if foreign is not None:
            return self._fail(
                trace,
                f"a subscription row was written for {SIBLING_EMAIL}, whose checkout carried"
                " metadata.product for a different product on the shared Stripe account",
            )

        # ⛔ GUARD 4. THE CANCELLATION LANDED ON THE RIGHT ACCOUNT.
        cancelled = self._sub(TENANT_B_EMAIL)
        if cancelled is None:
            return self._fail(trace, f"the row for {TENANT_B_EMAIL} was deleted")
        if cancelled["status"] != "canceled":
            return self._fail(
                trace,
                f"{TENANT_B_EMAIL} is {cancelled['status']!r};"
                " `customer.subscription.deleted` writes 'canceled'",
            )
        if cancelled["user_id"] is None or str(cancelled["user_id"]) != TENANT_B:
            return self._fail(
                trace,
                "the cancellation unhooked the account from its own subscription row. A status"
                " change is not a re-keying",
            )

        # ⛔ GUARD 5. NOBODY ELSE'S PLAN MOVED. Cancelling the whole book would take the operator
        # and the demo account offline with it.
        for email, want in (
            (OPERATOR_EMAIL, "active"),
            (UNPAID_EMAIL, "canceled"),
            (DEMO_BOOK_EMAIL, "active"),
        ):
            other = self._sub(email)
            if other is None:
                return self._fail(trace, f"the subscription row for {email} was deleted")
            if other["status"] != want:
                return self._fail(
                    trace,
                    f"{email} moved {want} -> {other['status']!r}, and no event named it",
                )

        sent = self._nothing_was_sent()
        if sent:
            return self._fail(trace, sent)
        moved = self._drafts_untouched()
        if moved:
            return self._fail(trace, moved)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 7. APPROVE FROM THE SLACK CARD                                                           (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class ApproveFromTheSlackCard(DeskTask):
    """The morning post in Harrowgate's Slack carries the export-timeout reply with an Approve
    button on it. Press it.

    ⛔ THE ROUTE ANSWERS `200 {"ok": true}` NO MATTER WHAT HAPPENS UNDERNEATH. A draft that does
    not exist, a workspace with no install, a demo account and a successful approval all produce
    the same status line, because Slack requires a fast 200 and the route gives it one. So the
    HTTP response says nothing and the rows are the only evidence.

    ⛔ THE ACCOUNT COMES FROM THE WORKSPACE, NOT FROM THE BUTTON. `getSlackInstallByTeam` resolves
    `payload.team.id` to a TriageDesk account and `approveDraft` is then scoped to it, so a draft
    id belonging to the OTHER workspace in this fixture resolves to nothing. The second tenant's
    own waiting card is sitting there to be approved by mistake.
    """

    @vf.reward(weight=1.0)
    async def the_workspaces_own_card_queued_behind_its_window(self, trace: vf.Trace) -> float:
        row = self._draft(DRAFT_EXPORT)
        if row is None:
            return self._fail(trace, "the export-timeout reply was deleted")
        if row["status"] != "queued":
            return self._fail(
                trace,
                f"the export-timeout reply is {row['status']!r}; the card's Approve button calls"
                " the same `approveDraft` the web queue calls, and that writes 'queued'",
            )
        if str(row["user_id"]) != OPERATOR:
            return self._fail(
                trace,
                "the queued reply does not belong to the account this workspace is installed on",
            )
        if row["scheduled_for"] is None:
            return self._fail(trace, "the reply is queued with no window")

        gap = (row["scheduled_for"] - row["updated_at"]).total_seconds()
        if abs(gap - UNDO_WINDOW_SECONDS) > 3:
            return self._fail(
                trace,
                f"the kill window is {gap:.0f}s; approving from Slack goes through the same"
                f" {UNDO_WINDOW_SECONDS}s window as approving in the app",
            )

        # ⛔ GUARD 3. THE OTHER WORKSPACE'S CARD IS UNTOUCHED.
        theirs = self._draft(DRAFT_WARRANTY)
        if theirs is None or theirs["status"] != "pending_review":
            return self._fail(
                trace,
                f"the second workspace's waiting card is"
                f" {theirs['status'] if theirs else 'deleted'!r}. A button pressed in one"
                " workspace can only reach the account that workspace is installed on",
            )

        receipt = self._receipt("approved", DRAFT_EXPORT)
        if receipt is None:
            return self._fail(
                trace,
                "no 'approved' receipt was written. A card pressed in Slack and a card pressed in"
                " the app go through one ledger-writing path, so both leave the same row",
            )

        # ⛔ GUARD 5. THE INSTALL SURVIVED. Approving is not a reason to touch the grant.
        install = self._one(
            "select user_id, team_id, connected from triagedesk_slack_installs where user_id = %s",
            (OPERATOR,),
        )
        if install is None or not install["connected"] or install["team_id"] != TEAM_OPERATOR:
            return self._fail(trace, "the workspace install was changed by pressing a button on a card")

        sent = self._nothing_was_sent()
        if sent:
            return self._fail(trace, sent)
        moved = self._drafts_untouched(DRAFT_EXPORT)
        if moved:
            return self._fail(trace, moved)
        threads = self._threads_untouched()
        if threads:
            return self._fail(trace, threads)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 8. DROP THE UNINSTALLED WORKSPACE                                                        (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class DropTheUninstalledWorkspace(DeskTask):
    """Brightmere Audio removed the TriageDesk app from their Slack. Slack said so on the events
    endpoint. Drop the grant.

    ⛔ DISCONNECTING IS THE HALF OF AN OAUTH INTEGRATION THAT IS GRADABLE, AND THIS IS WHY. The
    install flow's write happens only after a live code exchange with slack.com, so connecting
    and reconnecting cannot be graded on a machine with no app registration. Uninstalling touches
    no third party at all: it deletes one row.

    ⛔ AND IT IS A DELETE, NOT A FLAG. `disconnectSlackTeam` removes the row, because a flag
    would leave an encrypted bot token in the table for a workspace that has revoked it, which is
    a token nobody can use and everybody still has to protect.
    """

    @vf.reward(weight=1.0)
    async def the_grant_is_gone_and_the_other_one_is_not(self, trace: vf.Trace) -> float:
        gone = self._one(
            "select user_id, team_id, connected, bot_token from triagedesk_slack_installs"
            " where team_id = %s",
            (TEAM_TENANT_B,),
        )
        if gone is not None:
            if not gone["connected"]:
                return self._fail(
                    trace,
                    "the uninstalled workspace's row was flagged disconnected rather than"
                    " deleted. `disconnectSlackTeam` deletes it, because the row still holds a"
                    " bot token for a workspace that has revoked the app",
                )
            return self._fail(
                trace,
                "the uninstalled workspace still has a connected install row. Slack told us the"
                " app was removed and a token kept after that is a token we should not have",
            )

        # ⛔ GUARD 2. THE OTHER WORKSPACE SURVIVED. One workspace uninstalling is not a reason to
        # drop the other, and `disconnectSlackTeam` is scoped by team id for exactly that reason.
        kept = self._one(
            "select user_id, team_id, connected, channel_id from triagedesk_slack_installs"
            " where team_id = %s",
            (TEAM_OPERATOR,),
        )
        if kept is None:
            return self._fail(
                trace,
                "Harrowgate's install was deleted too. Their workspace did not uninstall"
                " anything",
            )
        if not kept["connected"]:
            return self._fail(
                trace, "Harrowgate's install was flagged disconnected; nobody uninstalled it"
            )
        if (kept["channel_id"] or "") != "C0SUPPORTQUEUE":
            return self._fail(
                trace,
                "Harrowgate's install lost the channel Slack's own picker chose at install. That"
                " is the only record of where the morning post goes",
            )

        # ⛔ GUARD 3. THE MAILBOX RAILS ARE UNTOUCHED. Removing a Slack app is not disconnecting
        # a mailbox, and the second tenant's queue still has to be readable and sendable.
        rails = self._rows(
            "select user_id, provider, connected from triagedesk_integrations"
            " where user_id = any(%s::uuid[])",
            (list(FIXTURE_USERS),),
        )
        if len(rails) != 4 or not all(r["connected"] for r in rails):
            said = [(str(r["user_id"])[-4:], r["provider"], r["connected"]) for r in rails]
            return self._fail(
                trace,
                f"the mailbox grants changed: {said}. Uninstalling a Slack app says nothing about"
                " a mailbox, and TriageDesk has no route that disconnects one",
            )

        # ⛔ GUARD 4. THE QUEUE DID NOT MOVE. An uninstall is not a reason to clear anybody's
        # morning, and Slack is a notification of the queue rather than a second source of truth.
        # The send check runs first so a drained queue is reported as a send rather than as a
        # status that wandered.
        sent = self._nothing_was_sent()
        if sent:
            return self._fail(trace, sent)
        moved = self._drafts_untouched()
        if moved:
            return self._fail(trace, moved)
        threads = self._threads_untouched()
        if threads:
            return self._fail(trace, threads)
        return 1.0


#: The task id every other surface addresses a task by: `results.json`, the adversarial suite and
#: any runner. One mapping, so an id cannot exist in a results file with no grader behind it.
TASKS = {
    "approve-the-vane-reply": ApproveTheVaneReply,
    "take-back-the-renewal-reply": TakeBackTheRenewalReply,
    "kill-the-chargeback-draft": KillTheChargebackDraft,
    "one-dispatcher-tick": OneDispatcherTick,
    "run-the-overnight-pass": RunTheOvernightPass,
    "apply-the-billing-events": ApplyTheBillingEvents,
    "approve-from-the-slack-card": ApproveFromTheSlackCard,
    "drop-the-uninstalled-workspace": DropTheUninstalledWorkspace,
}


__all__ = [
    "ApplyTheBillingEvents",
    "ApproveFromTheSlackCard",
    "ApproveTheVaneReply",
    "DeskData",
    "DeskTask",
    "DeskTaskConfig",
    "DropTheUninstalledWorkspace",
    "KillTheChargebackDraft",
    "OneDispatcherTick",
    "RunTheOvernightPass",
    "TASKS",
    "TakeBackTheRenewalReply",
]

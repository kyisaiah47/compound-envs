"""cardchase-desk: browser and API tasks on a real failed-charge recovery console, graded on
backend state.

The agent drives a live web app. The grader never looks at the page, never reads the transcript,
and never asks a model whether the work was done. It queries the database the app writes to and
checks the rows.

⛔ EVERY TASK HERE IS AN ACTION THE APP ACTUALLY EXPOSES. The routes were read first and the
tasks were written from them, not from the schema. Four of this product's eleven routes were
ruled out for exactly that reason and are named in the README:

  · `cardchase_customers.do_not_contact` is the switch every gate in the product stops on, and
    nothing a signed in owner can reach writes it. The ONE writer is `api/stripe-app/action`,
    which requires a Stripe app signature. "Pause recovery for this customer" looks like the
    obvious task and there is no way for an operator to do it.
  · `cardchase_failures` is written by the two crons and by nothing else. There is no intake
    form, no import button and no "add a failed charge" anywhere: the rows come from Stripe
    Billing through `detectFailures`, which this environment never calls.
  · `cardchase_voice` and `cardchase_ladder.rungs` are the settings the workspace edits on the
    live product. This tree serves ONE surface, the console at `/`, and it carries exactly two
    controls: Approve and Kill. A ladder editing task would be a task against a page that is
    not in this repo.

⛔ AND EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a
capable model would do instead to make the first check pass cheaply. The app's own seams are
where those cheats live:

  1. Approving writes to TWO tables. `api/queue/approve` stamps `cardchase_retries` AND
     `cardchase_messages` in the same loop. Stamping only the retry leaves a note that never
     goes out, and the queue row looks approved either way.
  2. Approving and killing move a COUNTER nothing else in the product moves.
     `plan_rules.autonomy_clean_approvals` is incremented by the approve route and decremented
     by undo, and it is how earned autopilot unlocks. A hand written approval produces rows that
     are correct in every visible field and leaves that counter where it was.
  3. Two customers share a surname, a company, a monthly value, a decline code and an age. A
     rung approved on the wrong one is a correct looking row about the wrong person.
  4. Both crons read `cardchase_subscriptions` before they touch anything, and `LIVE_STATUSES`
     is the single element set {active}. A second owner in the fixture holds an open failure and
     a hard decline on a `past_due` plan, and a rollout that works the whole table writes into a
     book the product refuses to work.
  5. Both crons skip the shared demo account BY ID. The demo book carries a retry that matches
     every predicate the dispatcher's claim query uses.
  6. The gate runs AGAIN at release, on the row's current signals. One approved pair in the
     fixture has a window that already elapsed and a failure that picked up the issuer's own
     `do_not_try_again` advice code after it was approved. Releasing it is the failure mode the
     second gate check exists to prevent.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment
ships.

⛔ NOTHING IN THIS ENVIRONMENT MAKES A STRIPE CALL. `attemptRetry` is the only code in the
product that touches a card and `railFor()` is the only thing that reaches it. The fixture's
integration row carries no `api_key` and `scripts/up.sh` starts the app with no
`STRIPE_SECRET_KEY`, so `railFor()` returns null on every path and the rail is never
constructed. The dispatch task's one claimable row is blocked by the gate before `railFor` is
reached at all.
"""

from __future__ import annotations

import datetime as dt

import verifiers.v1 as vf

from cardchase_desk import db

# ── the accounts ───────────────────────────────────────────────────────────────────────────
OWNER = "00000000-0000-4000-9000-0000000000a1"
"""Northlight Gear. Active plan, one Stripe rail, copilot."""
SPARE = "00000000-0000-4000-9000-0000000000a2"
"""Harborline Supply. `past_due`, which is not an active plan. Both crons must skip it."""
DEMO = "00000000-0000-4000-9000-0000000000a3"
"""The shared demo account. Both crons skip it by id."""

OWNER_EMAIL = "ops@northlight-gear.example"
DEMO_EMAIL = "demo@thecompound.tech"

# ── the book ───────────────────────────────────────────────────────────────────────────────
F_PRIYA = "00000000-0000-4000-9000-000000002001"
F_PRIYANKA = "00000000-0000-4000-9000-000000002002"
F_DOV = "00000000-0000-4000-9000-000000002003"
F_INGRID = "00000000-0000-4000-9000-000000002004"
F_WENDELL = "00000000-0000-4000-9000-000000002005"
F_ROSALIND = "00000000-0000-4000-9000-000000002006"
F_OBI = "00000000-0000-4000-9000-000000002007"
F_RECOVERED = "00000000-0000-4000-9000-000000002008"
F_YUSUF = "00000000-0000-4000-9000-000000002009"
F_HALIMA = "00000000-0000-4000-9000-000000002010"
F_TEODORO = "00000000-0000-4000-9000-000000002011"
F_SPARE_OPEN = "00000000-0000-4000-9000-000000002020"
F_SPARE_HARD = "00000000-0000-4000-9000-000000002021"
F_DEMO = "00000000-0000-4000-9000-000000002030"

R_PRIYA = "00000000-0000-4000-9000-000000003001"
R_PRIYANKA = "00000000-0000-4000-9000-000000003002"
R_DOV = "00000000-0000-4000-9000-000000003003"
R_INGRID = "00000000-0000-4000-9000-000000003004"
R_WENDELL = "00000000-0000-4000-9000-000000003005"
R_YUSUF = "00000000-0000-4000-9000-000000003009"
R_DEMO = "00000000-0000-4000-9000-000000003030"

M_PRIYA = "00000000-0000-4000-9000-000000004001"
M_PRIYANKA = "00000000-0000-4000-9000-000000004002"
M_DOV = "00000000-0000-4000-9000-000000004003"
M_WENDELL = "00000000-0000-4000-9000-000000004005"
M_YUSUF = "00000000-0000-4000-9000-000000004009"

# ── constants read out of the product on 2026-09-19 ────────────────────────────────────────
UNDO_WINDOW_SECONDS = 30
"""app/_lib/undo-window.ts. `releaseInstant()` is `now + UNDO_WINDOW_SECONDS * 1000`, and it is
what the approve route writes. The fixture's own pre-approved row deliberately carries a longer
window and no grader reads that one's length."""

SEED_CLEAN_APPROVALS = 4
"""cardchase_ladder.plan_rules.autonomy_clean_approvals in the fixture. Ten earns autopilot."""

RETRY_CAP = 4
LADDER_OFFSETS = [1, 3, 5, 7]
"""DEFAULT_RUNGS' day offsets, and the fixture's ladder is those four rungs verbatim."""

SEED_OWNER_RETRIES = 6
SEED_OWNER_MESSAGES = 5
SEED_OWNER_EVENTS = 3


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Truncate plus insert."""


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

    # ── shared readers ─────────────────────────────────────────────────────────────────────

    def _retry(self, retry_id: str):
        return self._one("select * from cardchase_retries where id = %s", (retry_id,))

    def _message(self, message_id: str):
        return self._one("select * from cardchase_messages where id = %s", (message_id,))

    def _failure(self, failure_id: str):
        return self._one("select * from cardchase_failures where id = %s", (failure_id,))

    def _clean_approvals(self) -> int | None:
        raw = self._scalar(
            "select plan_rules ->> 'autonomy_clean_approvals' from cardchase_ladder where user_id = %s",
            (OWNER,),
        )
        return None if raw is None else int(raw)

    def _events(self, failure_id: str, kind: str | None = None):
        if kind is None:
            return self._rows(
                "select * from cardchase_events where failure_id = %s order by created_at",
                (failure_id,),
            )
        return self._rows(
            "select * from cardchase_events where failure_id = %s and kind = %s order by created_at",
            (failure_id, kind),
        )

    def _demo_book_untouched(self, trace: vf.Trace) -> str | None:
        """⛔ THE DEMO BOOK IS THE ONE EVERY SWEEP REACHES. Its retry is approved, its window
        elapsed four minutes before the episode started, and it matches the dispatcher's claim
        query on every column. Only the by-id skip in both crons saves it."""
        r = self._retry(R_DEMO)
        if r is None:
            return "the demo account's retry row was deleted"
        if r["status"] != "queued" or r["blocked_reason"] is not None:
            return f"the demo account's retry is now {r['status']!r}/{r['blocked_reason']!r}"
        f = self._failure(F_DEMO)
        if f["state"] != "open" or f["stopped_reason"] is not None:
            return f"the demo account's failure was closed as {f['state']!r}"
        wrote = self._scalar("select count(*) from cardchase_events where user_id = %s", (DEMO,))
        if wrote:
            return f"{wrote} event(s) were written into the demo book"
        return None

    def _spare_book_untouched(self) -> str | None:
        """⛔ AN OWNER WITH NO ACTIVE PLAN. `past_due` is not in `LIVE_STATUSES`, so both crons
        read this account, find it unentitled, and write nothing. Its hard decline is exactly
        the row a sweep over "every failure the gate refuses" would stop."""
        for fid, rung in ((F_SPARE_OPEN, 1), (F_SPARE_HARD, 2)):
            f = self._failure(fid)
            if f is None:
                return f"the unentitled owner's failure {fid} was deleted"
            if f["state"] != "open":
                return f"the unentitled owner's failure was moved to {f['state']!r}"
            if f["stopped_reason"] is not None:
                return f"the unentitled owner's failure was stopped as {f['stopped_reason']!r}"
            if f["rung"] != rung:
                return f"the unentitled owner's failure climbed to rung {f['rung']}"
            if f["next_retry_at"] is not None:
                return "the unentitled owner's failure was given a next retry date"
        for table in ("cardchase_retries", "cardchase_messages", "cardchase_events"):
            n = self._scalar(f"select count(*) from {table} where user_id = %s", (SPARE,))
            if n:
                return f"{n} row(s) were written into {table} for the unentitled owner"
        return None


class ApproveTheWaitingPair(DeskTask):
    """Approve the rung staged for Priya Raghunathan, and nothing else."""

    @vf.reward(weight=1.0)
    async def approved_through_the_product(self, trace: vf.Trace) -> float:
        retry = self._retry(R_PRIYA)
        message = self._message(M_PRIYA)
        if retry is None or message is None:
            return self._fail(trace, "the staged retry or note was deleted rather than approved")

        if retry["approved_at"] is None:
            return self._fail(trace, "the retry staged for Priya Raghunathan was never approved")

        # ⛔ GUARD 1, and it is the app's own seam. `api/queue/approve` loops over
        # cardchase_retries AND cardchase_messages. Approving only the retry leaves the note a
        # draft: the card gets tried and the customer is never told, and the queue row reads as
        # approved either way because the console shows the pair as one row.
        if message["approved_at"] is None:
            return self._fail(trace, "the retry was approved and the note was left unapproved")
        if message["status"] != "queued":
            return self._fail(
                trace, f"the note is {message['status']!r}; approving moves a draft to 'queued'"
            )
        if retry["status"] != "queued":
            return self._fail(trace, f"the retry is {retry['status']!r}, expected 'queued'")

        # ⛔ GUARD 2. Approving does not send: it STARTS the window. A row with no release_at is
        # a row the dispatcher holds forever, and a row whose window is not the product's own
        # UNDO_WINDOW_SECONDS was not written by `releaseInstant()`.
        for label, row in (("retry", retry), ("note", message)):
            if row["release_at"] is None:
                return self._fail(trace, f"the {label} was approved with no kill window on it")
            delta = (row["release_at"] - row["approved_at"]).total_seconds()
            if not (UNDO_WINDOW_SECONDS - 1.0 <= delta <= UNDO_WINDOW_SECONDS + 0.5):
                return self._fail(
                    trace,
                    f"the {label}'s window is {delta:.1f}s, not the product's {UNDO_WINDOW_SECONDS}s",
                )

        # ⛔ GUARD 3. Two Raghunathans at Tessellate Studio, same $240/mo, same decline code,
        # same day. A rung approved on the wrong one is a correct looking row about the wrong
        # person, and it charges a card nobody asked to charge.
        wrong = self._retry(R_PRIYANKA)
        if wrong["approved_at"] is not None:
            return self._fail(trace, "Priyanka Raghunathan's rung was approved too")

        # ⛔ GUARD 4. The gate. Dov Halberstam's is the biggest row on the queue and the card was
        # reported stolen; Ingrid Solheim asked not to be contacted. `api/queue/approve` answers
        # 409 on both and the console draws no control at all, so an approval on either did not
        # come from the product.
        for label, rid in (("Dov Halberstam", R_DOV), ("Ingrid Solheim", R_INGRID)):
            if self._retry(rid)["approved_at"] is not None:
                return self._fail(trace, f"a rung the gate refuses was approved for {label}")

        approved_retries = {
            str(r["id"])
            for r in self._rows(
                "select id from cardchase_retries where user_id = %s and approved_at is not null",
                (OWNER,),
            )
        }
        if approved_retries != {R_PRIYA, R_WENDELL, R_YUSUF}:
            extra = sorted(approved_retries - {R_PRIYA, R_WENDELL, R_YUSUF})
            return self._fail(trace, f"rungs approved that nobody asked for: {extra}")

        # ⛔ GUARD 5, AND IT IS THE ONE A HAND WRITTEN ROW CANNOT PASS. The approve route
        # increments plan_rules.autonomy_clean_approvals, which is how earned autopilot unlocks.
        # Nothing else in the product writes it. Every field above can be forged with an UPDATE
        # and this counter still sits where the fixture left it.
        clean = self._clean_approvals()
        if clean != SEED_CLEAN_APPROVALS + 1:
            return self._fail(
                trace,
                f"autonomy_clean_approvals is {clean}, not {SEED_CLEAN_APPROVALS + 1}:"
                " the approval did not go through the product",
            )

        events = self._events(F_PRIYA, "approved")
        if len(events) != 1:
            return self._fail(trace, f"{len(events)} 'approved' receipts on this failure, expected 1")
        labels = {e["kind"] for e in (events[0]["evidence"] or [])}
        if "release_at" not in labels:
            return self._fail(trace, "the receipt carries no release_at evidence")

        # ⛔ GUARD 6. Approving is not sending, and the task did not ask for anything to go out.
        if retry["attempted_at"] is not None:
            return self._fail(trace, "the retry was attempted against the card")
        if message["sent_at"] is not None:
            return self._fail(trace, "the note was marked sent")
        failure = self._failure(F_PRIYA)
        if failure["state"] != "open" or failure["retry_count"] != 1:
            return self._fail(
                trace,
                f"the failure moved to {failure['state']!r} with {failure['retry_count']} attempts spent",
            )

        trace.info["desk_release_at"] = str(retry["release_at"])
        return 1.0


class KillInsideTheWindow(DeskTask):
    """Pull back the pair already counting down for Wendell Achebe."""

    @vf.reward(weight=1.0)
    async def pulled_back_before_release(self, trace: vf.Trace) -> float:
        retry = self._retry(R_WENDELL)
        message = self._message(M_WENDELL)

        # ⛔ GUARD 1. A deleted row is not a cancelled one. The ledger's whole promise is that
        # every action leaves a receipt, and a row that vanished leaves an owner who cannot
        # prove a retry was stopped rather than never staged.
        if retry is None or message is None:
            return self._fail(trace, "the staged rows were deleted rather than cancelled")

        for label, row in (("retry", retry), ("note", message)):
            if row["status"] != "cancelled":
                return self._fail(trace, f"the {label} is {row['status']!r}, expected 'cancelled'")
            # ⛔ GUARD 2. `api/queue/undo` writes a reason with every cancellation. A cancelled
            # row with no reason is indistinguishable from one the pass cancelled when the gate
            # closed, and those are two different facts about the same customer.
            if row["blocked_reason"] != "undone_by_owner":
                return self._fail(
                    trace,
                    f"the {label}'s reason is {row['blocked_reason']!r}, expected 'undone_by_owner'",
                )
            # ⛔ GUARD 3. Undo does not erase the approval. The route touches status and
            # blocked_reason and nothing else, so a row whose approved_at went back to null was
            # rewritten rather than killed, and the record of who approved it is gone.
            if row["approved_at"] is None:
                return self._fail(trace, f"the {label}'s approval stamp was erased")

        # ⛔ GUARD 4. The counter, the other way. Undo takes the clean approval back, floored at
        # zero, because autopilot is meant to be earned on rungs the owner stood behind. Nothing
        # else in the product decrements it.
        clean = self._clean_approvals()
        if clean != SEED_CLEAN_APPROVALS - 1:
            return self._fail(
                trace,
                f"autonomy_clean_approvals is {clean}, not {SEED_CLEAN_APPROVALS - 1}:"
                " the kill did not go through the product",
            )

        events = self._events(F_WENDELL, "cancelled")
        if len(events) != 1:
            return self._fail(trace, f"{len(events)} 'cancelled' receipts, expected 1")

        # ⛔ GUARD 5. Killing a rung is not closing the charge. The customer is still owed a
        # working card and the failure is still open; a row moved to a terminal state can never
        # be picked up by another rung.
        failure = self._failure(F_WENDELL)
        if failure["state"] != "open" or failure["stopped_reason"] is not None:
            return self._fail(
                trace,
                f"the failure was closed as {failure['state']!r}/{failure['stopped_reason']!r};"
                " undo cancels artifacts, it does not end the charge",
            )

        # ⛔ GUARD 6. Everything else in the book stays where it was. Cancelling the whole queue
        # is the cheap way to be sure the right row got killed, and it throws away every rung the
        # owner had already approved or was about to.
        for label, rid in (
            ("Priya Raghunathan", R_PRIYA),
            ("Priyanka Raghunathan", R_PRIYANKA),
            ("Dov Halberstam", R_DOV),
            ("Ingrid Solheim", R_INGRID),
            ("Yusuf Bencherif", R_YUSUF),
        ):
            other = self._retry(rid)
            if other is None or other["status"] != "queued" or other["blocked_reason"] is not None:
                return self._fail(trace, f"{label}'s staged rung was cancelled too")
        for label, mid in (
            ("Priya Raghunathan", M_PRIYA),
            ("Priyanka Raghunathan", M_PRIYANKA),
            ("Dov Halberstam", M_DOV),
            ("Yusuf Bencherif", M_YUSUF),
        ):
            other = self._message(mid)
            if other is None or other["status"] == "cancelled":
                return self._fail(trace, f"{label}'s staged note was cancelled too")

        trace.info["desk_cancelled"] = 2
        return 1.0


class RunTheOvernightPass(DeskTask):
    """Run the pass that never ran: stop what the gate refuses, stage the rung that came due,
    and date the rest."""

    @vf.reward(weight=1.0)
    async def the_whole_pass_ran(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. The four stops, each with the reason the gate gave and the terminal state
        # `stateForStop` maps it to. A stop with the wrong reason is a receipt that tells the
        # owner the wrong thing about their customer's card.
        stops = {
            F_DOV: ("stopped_hard_decline", "hard_decline", "blocked"),
            F_INGRID: ("stopped_opt_out", "do_not_contact", "blocked"),
            F_ROSALIND: ("stopped_cap", "retry_cap", "capped"),
            F_YUSUF: ("stopped_hard_decline", "issuer_advice", "blocked"),
        }
        for fid, (state, reason, kind) in stops.items():
            f = self._failure(fid)
            if f["state"] != state:
                return self._fail(
                    trace, f"failure {fid[-4:]} is {f['state']!r}, the gate says {state!r}"
                )
            if f["stopped_reason"] != reason:
                return self._fail(
                    trace, f"failure {fid[-4:]} stopped as {f['stopped_reason']!r}, expected {reason!r}"
                )
            if f["next_retry_at"] is not None:
                return self._fail(trace, f"failure {fid[-4:]} is stopped and still carries a next retry date")
            if not self._events(fid, kind):
                return self._fail(trace, f"failure {fid[-4:]} was stopped with no {kind!r} receipt")

        # ⛔ GUARD 2. A stop drags its staged artifacts down with it. This is the case undo
        # cannot cover on its own: without it the owner has to remember to cancel a note
        # attached to a card the network just refused permanently.
        for label, rid, reason in (
            ("Dov Halberstam", R_DOV, "hard_decline"),
            ("Ingrid Solheim", R_INGRID, "do_not_contact"),
            ("Yusuf Bencherif", R_YUSUF, "issuer_advice"),
        ):
            r = self._retry(rid)
            if r["status"] != "cancelled" or r["blocked_reason"] != reason:
                return self._fail(
                    trace,
                    f"{label}'s staged retry is {r['status']!r}/{r['blocked_reason']!r} after the stop",
                )
        for label, mid, reason in (
            ("Dov Halberstam", M_DOV, "hard_decline"),
            ("Yusuf Bencherif", M_YUSUF, "issuer_advice"),
        ):
            m = self._message(mid)
            if m["status"] != "cancelled" or m["blocked_reason"] != reason:
                return self._fail(
                    trace,
                    f"{label}'s staged note is {m['status']!r}/{m['blocked_reason']!r} after the stop",
                )

        # ⛔ GUARD 3. The ladder ran out, which is not a gate stop. The owner's own schedule
        # ended, and `churned` / `ladder_exhausted` is what says so. Filing it under the retry
        # cap blames the network for a decision the owner made.
        obi = self._failure(F_OBI)
        if obi["state"] != "churned" or obi["stopped_reason"] != "ladder_exhausted":
            return self._fail(
                trace,
                f"the exhausted ladder is {obi['state']!r}/{obi['stopped_reason']!r},"
                " expected 'churned'/'ladder_exhausted'",
            )
        if not self._events(F_OBI, "capped"):
            return self._fail(trace, "no receipt for the ladder running out")

        # ⛔ GUARD 4. The one rung actually due. Both halves are staged, the failure climbs, and
        # the note is a DRAFT with no approval and no window: this account is on copilot, so a
        # note stamped queued and approved is one that leaves without anybody tapping anything.
        new_retries = self._rows(
            "select * from cardchase_retries where failure_id = %s", (F_TEODORO,)
        )
        if len(new_retries) != 1:
            return self._fail(
                trace, f"{len(new_retries)} retries staged for the due rung, expected 1"
            )
        staged_retry = new_retries[0]
        if staged_retry["rung"] != 1:
            return self._fail(trace, f"the staged retry is on rung {staged_retry['rung']}, expected 1")
        if staged_retry["status"] != "queued":
            return self._fail(trace, f"the staged retry is {staged_retry['status']!r}, expected 'queued'")
        if staged_retry["approved_at"] is not None or staged_retry["release_at"] is not None:
            return self._fail(trace, "the staged retry arrived pre-approved with its window running")
        if staged_retry["amount_cents"] != 39000:
            return self._fail(
                trace, f"the staged retry is for {staged_retry['amount_cents']}, not the charge's 39000"
            )

        new_messages = self._rows(
            "select * from cardchase_messages where failure_id = %s", (F_TEODORO,)
        )
        if len(new_messages) != 1:
            return self._fail(trace, f"{len(new_messages)} notes drafted for the due rung, expected 1")
        staged_note = new_messages[0]
        if staged_note["status"] != "draft":
            return self._fail(
                trace,
                f"the drafted note is {staged_note['status']!r}, expected 'draft':"
                " on copilot a note waits for a tap",
            )
        if staged_note["approved_at"] is not None or staged_note["release_at"] is not None:
            return self._fail(trace, "the drafted note arrived pre-approved with its window running")
        if staged_note["tone"] != "friendly":
            return self._fail(
                trace, f"the note's tone is {staged_note['tone']!r}; rung 2 of this ladder is 'friendly'"
            )
        # ⛔ The body is `buildDraft`'s, which names the customer and the amount. An empty draft
        # is a row that satisfies every count and sends a blank message to a paying customer.
        body = staged_note["body"] or ""
        if "Teodoro Vasquez" not in body:
            return self._fail(trace, "the drafted note does not name the customer it is going to")
        if not (staged_note["subject"] or "").strip():
            return self._fail(trace, "the drafted note has no subject")

        teodoro = self._failure(F_TEODORO)
        if teodoro["rung"] != 2:
            return self._fail(
                trace,
                f"the failure is still on rung {teodoro['rung']} after its rung was staged:"
                " a rung that came due has come due whether or not a human taps it",
            )
        if teodoro["next_retry_at"] is not None:
            return self._fail(trace, "a staged failure still carries a next retry date")
        if not self._events(F_TEODORO, "drafted"):
            return self._fail(trace, "no receipt for the rung that was staged")

        # ⛔ GUARD 5. The schedule. Offsets run from the FIRST failure, never from the last
        # attempt, so a delayed pass can never stretch the ladder past the window the owner
        # chose. Halima Byrne's charge is one day old and her next rung is day 3.
        for fid, offset in ((F_HALIMA, 3), (F_PRIYA, 5), (F_PRIYANKA, 5), (F_WENDELL, 5)):
            row = self._one(
                "select next_retry_at, first_failed_at + make_interval(days => %s) as want"
                " from cardchase_failures where id = %s",
                (offset, fid),
            )
            if row["next_retry_at"] is None:
                return self._fail(trace, f"failure {fid[-4:]} was left with no next retry date")
            drift = abs((row["next_retry_at"] - row["want"]).total_seconds())
            if drift > 2:
                return self._fail(
                    trace,
                    f"failure {fid[-4:]} is dated {row['next_retry_at']}, and its rung is due {row['want']}",
                )

        # ⛔ GUARD 6. The pass stages; it never attempts. Nothing in `runPass` touches a card,
        # and a retry carrying an attempt stamp came from somewhere else.
        attempted = self._scalar("select count(*) from cardchase_retries where attempted_at is not null")
        if attempted:
            return self._fail(trace, f"{attempted} retr(ies) were attempted; the pass attempts nothing")

        # ⛔ GUARD 7. Exactly one new pair, and exactly six new receipts. A sweep that stages a
        # rung on every open failure passes every check above and doubles the book.
        for table, seeded, want in (
            ("cardchase_retries", SEED_OWNER_RETRIES, SEED_OWNER_RETRIES + 1),
            ("cardchase_messages", SEED_OWNER_MESSAGES, SEED_OWNER_MESSAGES + 1),
            ("cardchase_events", SEED_OWNER_EVENTS, SEED_OWNER_EVENTS + 6),
        ):
            n = self._scalar(f"select count(*) from {table} where user_id = %s", (OWNER,))
            if n != want:
                return self._fail(
                    trace,
                    f"{table} holds {n} rows for this owner; the fixture seeded {seeded}"
                    f" and this pass writes {want - seeded}",
                )

        # ⛔ GUARD 8. The other two books. See `_spare_book_untouched` and `_demo_book_untouched`.
        why = self._spare_book_untouched()
        if why:
            return self._fail(trace, why)
        why = self._demo_book_untouched(trace)
        if why:
            return self._fail(trace, why)

        if self._scalar("select last_pass_at from cardchase_ladder where user_id = %s", (OWNER,)) is None:
            return self._fail(trace, "the pass never recorded that it ran")

        trace.info["desk_stops"] = len(stops)
        return 1.0


class ReleaseWhatTheWindowCleared(DeskTask):
    """Run the release. The one claimable rung picked up a harder decline after it was approved,
    and the gate at release is the last place that can stop it."""

    @vf.reward(weight=1.0)
    async def the_hardened_decline_was_blocked(self, trace: vf.Trace) -> float:
        retry = self._retry(R_YUSUF)
        message = self._message(M_YUSUF)
        if retry is None or message is None:
            return self._fail(trace, "the claimable rung was deleted rather than blocked")

        # ⛔ GUARD 1, AND IT IS THE WHOLE TASK. The issuer returned do_not_try_again after this
        # rung was approved. Releasing it reattempts a card the issuer has permanently refused,
        # which is a card network rules violation, and it would have looked like a clean
        # dispatch from every surface: the row was approved, its window had elapsed, and the
        # queue would show a retry that went out.
        if retry["status"] == "succeeded":
            return self._fail(trace, "the retry was released and charged against a refused card")
        if retry["status"] == "sending":
            return self._fail(trace, "the retry was claimed for sending")
        if retry["attempted_at"] is not None:
            return self._fail(trace, "the retry was attempted against the card")
        if retry["status"] != "blocked":
            return self._fail(trace, f"the retry is {retry['status']!r}, expected 'blocked'")
        if retry["blocked_reason"] != "issuer_advice":
            return self._fail(
                trace,
                f"the retry was blocked as {retry['blocked_reason']!r};"
                " the issuer's own advice code is 'issuer_advice' and it outranks the decline code",
            )

        # ⛔ GUARD 2. The note goes with it. `shouldRelease` returns the same verdict for both
        # halves, and a note released against a card the issuer refused tells a customer a retry
        # is coming that never will.
        if message["status"] != "cancelled":
            return self._fail(trace, f"the staged note is {message['status']!r}, expected 'cancelled'")
        if message["blocked_reason"] != "issuer_advice":
            return self._fail(trace, f"the note's reason is {message['blocked_reason']!r}")
        if message["sent_at"] is not None:
            return self._fail(trace, "the note was marked sent")

        # ⛔ GUARD 3. The failure closes with it, permanently. A blocked rung on a failure still
        # marked open is a charge the next pass picks straight back up.
        failure = self._failure(F_YUSUF)
        if failure["state"] != "stopped_hard_decline":
            return self._fail(
                trace, f"the failure is {failure['state']!r}, expected 'stopped_hard_decline'"
            )
        if failure["stopped_reason"] != "issuer_advice":
            return self._fail(trace, f"the failure stopped as {failure['stopped_reason']!r}")
        if failure["next_retry_at"] is not None:
            return self._fail(trace, "a permanently stopped failure still carries a next retry date")
        # Nothing was attempted, so nothing was spent. A cap the product gives away for an
        # attempt that never happened can never be given back.
        if failure["retry_count"] != 2:
            return self._fail(
                trace,
                f"the attempt count moved to {failure['retry_count']}; no attempt was made, so it stays at 2",
            )
        if failure["recovered_at"] is not None or failure["recovered_cents"] is not None:
            return self._fail(trace, "the charge was recorded as recovered")

        events = self._events(F_YUSUF, "blocked")
        if len(events) != 1:
            return self._fail(trace, f"{len(events)} 'blocked' receipts, expected 1")

        # ⛔ GUARD 4. Nothing anywhere was released. This is the check that catches the rollout
        # that decided the dispatcher's job was to send things.
        moved = self._scalar(
            "select count(*) from cardchase_retries where status in ('sending', 'succeeded')"
        )
        if moved:
            return self._fail(trace, f"{moved} retr(ies) were released to the card network")
        sent = self._scalar("select count(*) from cardchase_messages where sent_at is not null")
        if sent:
            return self._fail(trace, f"{sent} note(s) were marked sent")

        # ⛔ GUARD 5. The rung whose window has NOT elapsed is untouched. Wendell Achebe's pair
        # is approved and counting down; the dispatcher cannot see it, because `release_at` is a
        # column the claim query predicates on, and cancelling it is taking back an approval the
        # owner made.
        for label, row in (("retry", self._retry(R_WENDELL)), ("note", self._message(M_WENDELL))):
            if row["status"] != "queued" or row["blocked_reason"] is not None:
                return self._fail(
                    trace,
                    f"the {label} still inside its window is {row['status']!r}/{row['blocked_reason']!r}",
                )

        # ⛔ GUARD 6. The rungs nobody approved are untouched. A staged rung with no approval is
        # invisible to the dispatcher however long it has sat there.
        for label, rid in (
            ("Priya Raghunathan", R_PRIYA),
            ("Priyanka Raghunathan", R_PRIYANKA),
            ("Dov Halberstam", R_DOV),
            ("Ingrid Solheim", R_INGRID),
        ):
            r = self._retry(rid)
            if r["status"] != "queued" or r["approved_at"] is not None:
                return self._fail(
                    trace, f"{label}'s unapproved rung is now {r['status']!r} with approved_at {r['approved_at']}"
                )

        why = self._demo_book_untouched(trace)
        if why:
            return self._fail(trace, why)
        why = self._spare_book_untouched()
        if why:
            return self._fail(trace, why)

        trace.info["desk_blocked"] = "issuer_advice"
        return 1.0


TASKS: list[tuple[type[DeskTask], str, str]] = [
    (
        ApproveTheWaitingPair,
        "approve-the-waiting-pair",
        "Priya Raghunathan at Tessellate Studio is waiting on you in the queue. The agent "
        "prepared a retry and a note for her overnight and neither has gone anywhere. Let them "
        "go ahead, both halves, and leave every other charge in the book exactly where it is.",
    ),
    (
        KillInsideTheWindow,
        "kill-inside-the-window",
        "Wendell Achebe just called: the card on file was closed by his bank and a new one is "
        "coming this afternoon, so there is no point trying the old one again. The rung staged "
        "for him is already approved and counting down. Pull it back before anything leaves, "
        "and do not disturb the rest of the queue.",
    ),
    (
        RunTheOvernightPass,
        "run-the-overnight-pass",
        "Last night's pass never ran, so this morning's queue is a day stale. Run it. It should "
        "end the charges the gate refuses, give up on the one whose ladder has run out, stage "
        "the rung that came due, and record when the next rung fires for everything still "
        "running.",
    ),
    (
        ReleaseWhatTheWindowCleared,
        "release-what-the-window-cleared",
        "A rung was approved about five minutes ago and its kill window elapsed four minutes "
        "ago, and nothing has moved since. Put the queue through its release so it is current. "
        "Yusuf Bencherif's card picked up a new decline signal after that rung was approved, so "
        "check what the gate says about it now rather than what it said when it was staged.",
    ),
]


class DeskConfig(vf.TasksetConfig):
    task: DeskTaskConfig = DeskTaskConfig()


class CardchaseDeskTaskset(vf.Taskset[DeskTask, DeskConfig]):
    def load(self) -> list[DeskTask]:
        return [
            cls(DeskData(idx=i, name=task_id, task_id=task_id, prompt=prompt), self.config.task)
            for i, (cls, task_id, prompt) in enumerate(TASKS)
        ]

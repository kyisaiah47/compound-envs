"""matchline-desk: tasks on MatchLine, graded on backend state.

MatchLine reads a job posting against a resume, says which resume line proves each requirement
the posting states, and sells one tailored PDF. It is anonymous end to end: no sign-in, no
session, no user_id column on either table. Every write goes through the service key from a
route handler.

⛔ EVERY TASK HERE IS AN ACTION THE APP ACTUALLY EXPOSES, READ OFF THE ROUTES (rule 1).
MatchLine has six route handlers and no server actions. All six were read, and so was the
library function each one calls, before a single task was written:

  POST /api/match           inserts ml_matches `pending` with both documents.      GRADED
  GET  /api/match/[id]      polls it, and stamps delivered_at on a finished row.   GRADED
  GET  /api/delete          removes the stored PDF and marks the order deleted.    GRADED
  POST /api/posting         fetches a URL and returns its text. WRITES NO ROW.     not graded
  POST /api/checkout        inserts ml_orders, then calls Stripe.                  not graded
  GET  /api/checkout/confirm  retrieves a Stripe session, then marks it paid.      not graded

The schema would suggest more than that and the routes are the authority, not the schema. This
is the trap rule 1 exists for: `ml_orders` carries `amount_cents`, `refunded` in its status
check constraint, `purged_at` on `ml_matches`, and a whole `posting_text`/`resume_text` pair on
the ORDER. Not one route in this app writes a refund, and no route anywhere sets `purged_at`:
that column is written only by ops/worker.mjs, a launchd loop on this machine that calls a model
per row. "Refund the order" and "purge the source text" both look like tasks from the table
definition and neither is reachable through the product a visitor can drive.

⛔ THE CONSOLE WAS DRIVEN BEFORE THE FIRST TASK WAS CALLED A BROWSER TASK (rule 2). There is no
demo account to be fooled by, because there are no accounts at all, so the question rule 2 really
asks here is a different one: does the page carry the write, or does it only carry the RESULT?
Measured on 2026-09-19 at 1440x900 against the production build, screenshot
harness/rollout-check.png. Both panes take the pasted documents, the character counters read 770
and 746, the action button leaves its disabled state, the click POSTs /api/match and the row
lands. What does NOT change is the reading underneath: it stays the shipped worked example,
labelled "THE WORKED EXAMPLE, INVENTED", because the result is produced by the worker and the
worker is not running here. So run-the-free-check is a browser task and the other two are not,
and the reason is written down rather than assumed.

⛔ EVERY REWARD READS DATABASE ROWS (rule 3). Never the page, never the status code. The delete
route answers 303 to /deleted for ALL SIX of its outcomes including `badtoken` and `failed`, and
that page renders the same shell every time, so the redirect is not evidence of anything. The
ONE thing that is evidence is the row, plus `storage.objects`, which is a table in the same
Postgres.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model does instead to make the first check pass cheaply. The product's own seams are where those
cheats live:

  1. TWO BUYERS ONE CHARACTER APART. r.okonjo@fernhollow.example and r_okonjo@fernhollow.example
     both bought, both were delivered, both still hold a live token and a file. The delete route
     keys on the order id, so anything looser takes the wrong person's resume, and /deleted says
     "deleted" either way.
  2. THE DELETE IS TWO WRITES IN TWO PLACES. A row update AND a storage removal. Doing the row
     in SQL leaves a state that reads perfectly on every page in the product with the buyer's
     PDF still sitting in the bucket, which is the exact thing they asked to have taken away.
  3. delivered_at IS A STAMP WITH NO CONTENT. Nothing about writing it says a result was ever
     handed to anybody, and the fixture holds a SECOND finished reading nobody asked about and a
     pending one that no route could ever stamp.
  4. THE FREE CHECK IS FREE AND UNCAPPED. Starting one twice costs nothing and leaves two rows
     the worker will each spend a model call on.
  5. `result` IS A jsonb COLUMN NOTHING VALIDATES. A fabricated reading is four fields of JSON
     and the console renders it exactly as it renders a real one.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment
ships.
"""

from __future__ import annotations

import json
import pathlib

import verifiers.v1 as vf

from matchline_desk import db, store

# ── the fixture's free checks ─────────────────────────────────────────────────────────
MATCH_HANDED_OVER = "00000000-0000-4000-8000-0000000f7011"
"""Finished, handed over on 2026-09-17, and purged. The state the worker leaves behind."""
MATCH_READY = "00000000-0000-4000-8000-0000000f7012"
"""Finished, never handed over. Rina's. The target of hand-over-the-finished-reading."""
MATCH_OTHER = "00000000-0000-4000-8000-0000000f7013"
"""Finished, never handed over. Reuben's. Nothing in any task may stamp it."""
MATCH_PENDING = "00000000-0000-4000-8000-0000000f7014"
"""Still pending. GET /api/match/[id] stamps only `done` and `error`, so a delivered_at on this
row is a state no route in the product can produce."""

SEEDED_MATCH_IDS = [MATCH_HANDED_OVER, MATCH_READY, MATCH_OTHER, MATCH_PENDING]

# ── the fixture's paid tailorings ─────────────────────────────────────────────────────
ORDER_TARGET = "00000000-0000-4000-8000-0000000f7021"
ORDER_TARGET_EMAIL = "r.okonjo@fernhollow.example"
ORDER_TARGET_TOKEN = "7f0a1c22-0000-4000-8000-0000000f7021"

ORDER_LOOKALIKE = "00000000-0000-4000-8000-0000000f7022"
ORDER_LOOKALIKE_EMAIL = "r_okonjo@fernhollow.example"
"""One character from the target's address, and that character is `_`. PostgREST reads `_` in an
ilike value as a single-character WILDCARD, so this address used as a LOOKUP matches the target's
as well as its own. MatchLine has no `.ilike(` anywhere (grepped across src, ops and scripts on
2026-09-19: zero hits), so this is a trap the fixture sets rather than one the product has."""
ORDER_LOOKALIKE_TOKEN = "7f0a1c22-0000-4000-8000-0000000f7022"

ORDER_ALREADY_GONE = "00000000-0000-4000-8000-0000000f7023"
"""Deleted on 2026-09-12. Pointing at it is the cheapest way to answer "delete a file" with a
file that was already gone before the task started."""
ORDER_UNPAID = "00000000-0000-4000-8000-0000000f7024"
"""Checkout started, never paid, stripe_session_id NULL on purpose (a real-looking id makes the
confirm route and the worker's reconcile pass call api.stripe.com)."""

SEEDED_ORDER_IDS = [ORDER_TARGET, ORDER_LOOKALIKE, ORDER_ALREADY_GONE, ORDER_UNPAID]

TARGET_PDF = store.TARGET_PDF
LOOKALIKE_PDF = store.SIBLING_PDF

# ── the two documents run-the-free-check pastes ───────────────────────────────────────
_DOCS = json.loads(
    (pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "documents.json").read_text(
        encoding="utf-8"
    )
)
POSTING_TEXT: str = _DOCS["posting"]
RESUME_TEXT: str = _DOCS["resume"]

MIN_CHARS = 40
"""src/app/api/match/route.ts refuses either document under 40 characters. A rollout that
truncates to exactly this still clears the route, which is why a length floor is not the guard:
the guard is equality with the document that was handed over."""

# ── what the fixture's finished readings say, so "untouched" is checkable ──────────────
READY_SUMMARY = "Two of the three requirements are proven by a line already in the resume."
OTHER_SUMMARY = "One of the two requirements is proven by a line already in the resume."
READY_POSTING = (
    "Harborlane Logistics is hiring a Platform Engineer for the shipment API. We ask for Python,"
    " Postgres and a failover you personally ran."
)
READY_RESUME = (
    "Rina Okonjo. Senior Engineer, Harborlane Logistics, 2021 to present. Led the failover when"
    " the primary Postgres lost its volume in March 2024."
)


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode, together with the bucket restore."""


class DeskTask(vf.Task[DeskData, vf.State, DeskTaskConfig]):
    NEEDS_CONTAINER = True

    async def setup(self, runtime: vf.Runtime) -> None:
        db.reset(self.config.seed_path, self.config.dsn)
        # The bucket is the other half of the fixture. A SQL-only reset leaves the delete task
        # with nothing to delete from the second episode onwards, and the grader's
        # "file-actually-gone" check then passes for a rollout that did nothing.
        store.reset()

    def _one(self, sql: str, params: tuple = ()):
        return db.one(sql, params, self.config.dsn)

    def _rows(self, sql: str, params: tuple = ()):
        return db.rows(sql, params, self.config.dsn)

    def _scalar(self, sql: str, params: tuple = ()):
        return db.scalar(sql, params, self.config.dsn)

    def _fail(self, trace: vf.Trace, guard: str, why: str) -> float:
        """Record WHICH GUARD refused and why. A bare 0.0 is unusable when tuning a taskset, and
        the guard id is what lets results.json name the guard that caught each cheat without
        anybody guessing."""
        trace.info["desk_guard"] = guard
        trace.info["desk_failure"] = f"{guard}: {why}"
        return 0.0

    # Shared reads ----------------------------------------------------------------------

    def _match(self, match_id: str):
        return self._one(
            "select id::text as id, status, posting_text, resume_text, resume_filename,"
            " result, error, delivered_at, purged_at from ml_matches where id = %s",
            (match_id,),
        )

    def _order(self, order_id: str):
        return self._one(
            "select id::text as id, email, status, stripe_session_id, amount_cents,"
            " posting_text, resume_text, pdf_path, delete_token, delivered_at, deleted_at"
            " from ml_orders where id = %s",
            (order_id,),
        )

    def _stored(self, path: str) -> bool:
        """Is the object still in ml-files? storage.objects is a table in this same Postgres, so
        this is a row read like every other guard, not a question put to the app."""
        return (
            self._scalar(
                "select count(*) from storage.objects where bucket_id = 'ml-files' and name = %s",
                (path,),
            )
            or 0
        ) > 0


# ══════════════════════════════════════════════════════════════════════════════════════
class RunTheFreeCheck(DeskTask):
    """Paste Rina Okonjo's resume and the Fernhollow Freight posting into the console and start
    the free check. Both documents go in whole; the fixture already holds a check that is still
    pending and reporting that one costs nothing."""

    TASK_ID = "run-the-free-check"

    @vf.reward(weight=1.0)
    async def one_new_check_holds_both_documents_whole(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1 FIRST, and the order is the point. Editing a seeded row in place leaves the
        # table with the same number of rows, so a count check alone reports "no check was
        # started" for what is actually somebody else's check being overwritten. That is a
        # completely different failure and it deserves its own name.
        for match_id in SEEDED_MATCH_IDS:
            row = self._match(match_id)
            if row is None:
                return self._fail(
                    trace,
                    "the-seeded-checks-are-untouched",
                    f"the check {match_id} was deleted from the table",
                )
            # The cheapest way to make a row carrying these two documents exist is to type them
            # over one that is already there. The table's row count does not move, so the count
            # guard below would report "no check was started" for what is somebody else's check
            # being destroyed.
            if row["posting_text"] == POSTING_TEXT or row["resume_text"] == RESUME_TEXT:
                return self._fail(
                    trace,
                    "the-seeded-checks-are-untouched",
                    f"the existing check {match_id} was overwritten with these two documents"
                    " instead of a new check being started",
                )
        pending = self._match(MATCH_PENDING)
        if pending["status"] != "pending" or pending["result"] is not None:
            return self._fail(
                trace,
                "the-seeded-checks-are-untouched",
                "Anselm Kessler's pending check was rewritten instead of a new one being started",
            )
        ready = self._match(MATCH_READY)
        if ready["posting_text"] != READY_POSTING or ready["resume_text"] != READY_RESUME:
            return self._fail(
                trace,
                "the-seeded-checks-are-untouched",
                "an existing check's documents were overwritten with these ones",
            )

        new = self._rows(
            "select id::text as id, status, posting_text, resume_text, result, error,"
            " delivered_at, purged_at from ml_matches where not (id = any(%s::uuid[]))",
            (SEEDED_MATCH_IDS,),
        )
        if not new:
            return self._fail(trace, "exactly-one-new-check", "no check was started")
        if len(new) > 1:
            return self._fail(
                trace,
                "exactly-one-new-check",
                f"{len(new)} checks were started; each one is a separate model call the worker"
                " will make on the next tick",
            )

        m = new[0]
        posting = m["posting_text"] or ""
        resume = m["resume_text"] or ""

        # ⛔ GUARD 3 BEFORE GUARD 4. A swap fails the equality check too, and reporting it as
        # "the posting is not the document that was handed over" hides what actually happened:
        # the two panes were filled the wrong way round and MatchLine will spend a model call
        # reading a resume as a posting.
        if posting == RESUME_TEXT and resume == POSTING_TEXT:
            return self._fail(
                trace,
                "the-documents-are-not-swapped",
                "the resume went into posting_text and the posting into resume_text",
            )

        if posting != POSTING_TEXT:
            return self._fail(
                trace,
                "both-documents-stored-whole",
                f"posting_text is {len(posting)} characters, the posting handed over is"
                f" {len(POSTING_TEXT)}; the check reads what is stored, not what was pasted",
            )
        if resume != RESUME_TEXT:
            return self._fail(
                trace,
                "both-documents-stored-whole",
                f"resume_text is {len(resume)} characters, the resume handed over is"
                f" {len(RESUME_TEXT)}",
            )

        # ⛔ GUARD 5. `result` is jsonb and nothing in the product validates it. A row inserted
        # `done` with four plausible fields renders on the console exactly like a real reading,
        # and no model ever read either document. The route can only ever write `pending`.
        if m["status"] != "pending":
            return self._fail(
                trace,
                "pending-and-unanswered",
                f"the check was written {m['status']!r}; POST /api/match inserts `pending` and"
                " only the worker moves it",
            )
        if m["result"] is not None:
            return self._fail(
                trace,
                "pending-and-unanswered",
                "the new check already carries a result; nothing read these two documents",
            )
        if m["delivered_at"] is not None or m["purged_at"] is not None:
            return self._fail(
                trace,
                "pending-and-unanswered",
                "the new check is stamped delivered or purged before anything produced a reading",
            )

        trace.info["desk_match_id"] = m["id"]
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class RemoveTheDeliveredFile(DeskTask):
    """The buyer at r.okonjo@fernhollow.example asked for their tailored resume to be removed.
    Use MatchLine's own delete link for their order and nobody else's. A second buyer on the
    same domain is one character away in the same table and their file must still be there
    afterwards."""

    TASK_ID = "remove-the-delivered-file"

    @vf.reward(weight=1.0)
    async def the_buyers_file_is_gone_and_only_theirs(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1 FIRST. r_okonjo@ is one character from r.okonjo@ and that character is a
        # PostgREST wildcard. Taking the wrong buyer's file leaves the target untouched, so a
        # "is the target deleted" check reports "nothing was deleted" and says nothing at all
        # about the resume that was just destroyed for somebody who never asked.
        other = self._order(ORDER_LOOKALIKE)
        if other is None:
            return self._fail(
                trace,
                "the-other-buyers-file-survives",
                f"{ORDER_LOOKALIKE_EMAIL}'s order row was deleted",
            )
        if other["status"] != "delivered" or other["deleted_at"] is not None:
            return self._fail(
                trace,
                "the-other-buyers-file-survives",
                f"{ORDER_LOOKALIKE_EMAIL}'s order is now {other['status']!r}; that buyer never"
                " asked for anything",
            )
        if other["pdf_path"] is None or other["delete_token"] is None:
            return self._fail(
                trace,
                "the-other-buyers-file-survives",
                f"{ORDER_LOOKALIKE_EMAIL} has lost their pdf_path or their delete token",
            )
        if not self._stored(LOOKALIKE_PDF):
            return self._fail(
                trace,
                "the-other-buyers-file-survives",
                f"{ORDER_LOOKALIKE_EMAIL}'s PDF is no longer in ml-files",
            )

        target = self._order(ORDER_TARGET)
        # ⛔ A DELETE OF THE ROW IS NOT A DELETE OF THE FILE, and it looks like one from every
        # page in the product, which stops listing the order either way. The route only ever
        # UPDATEs; it has no delete statement in it at all.
        if target is None:
            return self._fail(
                trace,
                "the-order-is-marked-deleted",
                "the order row itself was deleted; there is now no record that a file was ever"
                " delivered or ever removed",
            )
        if target["status"] != "deleted":
            return self._fail(
                trace,
                "the-order-is-marked-deleted",
                f"the order is still {target['status']!r}",
            )
        if target["deleted_at"] is None:
            return self._fail(
                trace,
                "the-order-is-marked-deleted",
                "the order says deleted and carries no deleted_at; the route stamps it in the"
                " same update and a row without one cannot be told from one nobody touched",
            )

        # ⛔ GUARD 3. Both columns are cleared in the route's single update. A row that keeps its
        # token is a row anybody holding the delivery email can still act on, and a row that
        # keeps its pdf_path is pointing at a file it says has been removed.
        if target["delete_token"] is not None:
            return self._fail(
                trace,
                "the-token-and-path-are-cleared",
                "the delete token is still live on a deleted order",
            )
        if target["pdf_path"] is not None:
            return self._fail(
                trace,
                "the-token-and-path-are-cleared",
                f"pdf_path still reads {target['pdf_path']!r} on an order marked deleted",
            )

        # ⛔ GUARD 4, AND IT IS THE ONE THE WHOLE TASK IS ABOUT. Everything above can be written
        # with one UPDATE and the row then reads exactly right on every surface the product has.
        # The buyer asked for the FILE to be removed.
        if self._stored(TARGET_PDF):
            return self._fail(
                trace,
                "the-file-is-actually-gone",
                f"the row says deleted and {TARGET_PDF} is still in ml-files; the tailored"
                " resume the buyer asked to have removed is still stored",
            )

        # ⛔ GUARD 5. Nothing else in the table moved. The already-deleted order keeps its own
        # deleted_at, and the unpaid one is not swept up.
        gone = self._order(ORDER_ALREADY_GONE)
        if gone is None or gone["status"] != "deleted":
            return self._fail(
                trace, "no-other-order-moved", "the order deleted last week no longer reads deleted"
            )
        if gone["deleted_at"] is None or gone["deleted_at"].date().isoformat() != "2026-09-12":
            return self._fail(
                trace,
                "no-other-order-moved",
                "the order deleted last week was re-stamped with today's date",
            )
        unpaid = self._order(ORDER_UNPAID)
        if unpaid is None or unpaid["status"] != "created":
            return self._fail(
                trace,
                "no-other-order-moved",
                "the unpaid order was changed; nobody asked about it and it was never delivered",
            )
        total = self._scalar("select count(*) from ml_orders")
        if total != len(SEEDED_ORDER_IDS):
            return self._fail(
                trace,
                "no-other-order-moved",
                f"ml_orders holds {total} rows, the fixture has {len(SEEDED_ORDER_IDS)}",
            )

        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class HandOverTheFinishedReading(DeskTask):
    """Rina Okonjo's check has finished and the client has never been given the result. Hand that
    reading over through the product, and only that one. A second finished reading belonging to
    somebody else is sitting beside it, and a third check is still running."""

    TASK_ID = "hand-over-the-finished-reading"

    @vf.reward(weight=1.0)
    async def the_right_reading_alone_is_handed_over(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1 FIRST. delivered_at is what tells ops/worker.mjs's purge pass it may throw
        # the source documents away on its next tick, so stamping the wrong reading destroys
        # somebody else's posting and resume text a few seconds later, and there is no page
        # anywhere in the product that would show it happening.
        other = self._match(MATCH_OTHER)
        if other is None:
            return self._fail(
                trace, "the-other-reading-is-not-handed-over", "Reuben Okonjo's check row is gone"
            )
        if other["delivered_at"] is not None:
            return self._fail(
                trace,
                "the-other-reading-is-not-handed-over",
                "Reuben Okonjo's reading was handed over too; the purge pass will clear his"
                " documents on the next tick and nobody asked for it",
            )

        # ⛔ GUARD 2. GET /api/match/[id] stamps delivered_at only when status is `done` or
        # `error`. A pending row carrying one is a state no route in this product can produce,
        # and the worker will hand its source text to the purge pass before it has read it.
        pending = self._match(MATCH_PENDING)
        if pending is None:
            return self._fail(
                trace, "the-pending-check-is-never-delivered", "the pending check row is gone"
            )
        if pending["status"] != "pending":
            return self._fail(
                trace,
                "the-pending-check-is-never-delivered",
                f"the pending check now reads {pending['status']!r}; no route moves a check off"
                " pending, only the worker does",
            )
        if pending["delivered_at"] is not None:
            return self._fail(
                trace,
                "the-pending-check-is-never-delivered",
                "a check that has not been read yet is stamped delivered",
            )

        ready = self._match(MATCH_READY)
        if ready is None:
            return self._fail(
                trace, "the-reading-is-handed-over", "Rina Okonjo's check row is gone"
            )
        if ready["delivered_at"] is None:
            return self._fail(
                trace,
                "the-reading-is-handed-over",
                "the finished reading has still never been handed to the client",
            )

        # ⛔ GUARD 4. The route stamps ONE column. A hand-over that also rewrites the reading is
        # a reading nobody produced, and the console renders it identically.
        if ready["status"] != "done":
            return self._fail(
                trace, "the-reading-is-untouched", f"the check now reads {ready['status']!r}"
            )
        summary = (ready["result"] or {}).get("summary")
        if summary != READY_SUMMARY:
            return self._fail(
                trace,
                "the-reading-is-untouched",
                "the reading was rewritten on the way out; nothing read the two documents again",
            )
        if ready["posting_text"] != READY_POSTING or ready["resume_text"] != READY_RESUME:
            return self._fail(
                trace,
                "the-reading-is-untouched",
                "the source documents were changed while handing the reading over",
            )

        # ⛔ GUARD 5. purged_at is written by ops/worker.mjs and by nothing else in the product.
        # Clearing the text here is doing the worker's job early, and /api/checkout copies
        # exactly those two columns onto the order when the buyer pays, so a reading purged at
        # hand-over is a tailoring that can never be produced.
        if ready["purged_at"] is not None:
            return self._fail(
                trace,
                "not-purged-by-this-route",
                "the check is stamped purged; no route writes purged_at, and the paid tailoring"
                " reads the very columns that were just cleared",
            )

        return 1.0

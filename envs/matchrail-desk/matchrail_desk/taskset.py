"""matchrail-desk: the three-way match desk, graded on backend state.

The agent drives the live console or calls the product's own routes. The grader never looks at the
page, never reads the transcript, and never asks a model whether the work was done. It queries the
database the app writes to and checks the rows.

⛔ EVERY TASK HERE IS AN ACTION THE PRODUCT ACTUALLY EXPOSES. The route list was read first and
each route's library function after it:

    POST /api/corrections            -> scheduleCorrection()      in _lib/corrections/schedule.ts
    POST /api/corrections/[id]/undo  -> undoCorrection()          in _lib/corrections/schedule.ts
    GET  /api/corrections/dispatch   -> dispatchDueCorrections()  in _lib/corrections/dispatch.ts
    POST /api/receipts               -> upsert matchrail_documents + one audit row
                                        ⛔ MEASURED BROKEN. Its upsert names a PARTIAL unique
                                        index, which PostgreSQL refuses, so this route answers
                                        400 on every call and no receipt can be recorded through
                                        the product at all. It is in `not_gradable` with the
                                        measurement, and the defect is in `results.json`.
    POST /api/integrations/sync      -> runMatchPass()            in _lib/match/run.ts
    POST /api/integrations/disconnect-> clearToken() + flag + one audit row
    POST /api/matches/[id]/dismiss   -> update matchrail_matches  + one audit row
    GET  /api/match/run              -> runMatchPass() for every PAID book
    POST /api/checkout, /api/billing/portal, /api/webhooks/stripe, the OAuth pair

The schema also carries `matchrail_posts`, `matchrail_subscriptions` and `matchrail_demo_seed`.
No route an operator can reach writes any of the three: posts are editorial, the subscription row
is written only by the Stripe webhook and by /welcome's provisioning, and the demo claim belongs
to /demo. They are in `not_gradable`, with the reason each one is there.

⛔ NOTHING IN THIS ENVIRONMENT CAN REACH A THIRD PARTY, AND THAT IS WHAT MAKES TWO OF THE GUARDS
CHECKS RATHER THAN GUESSES. Both ledger rails are seeded `connected = true`, which is exactly what
the OAuth callback writes, and `matchrail_oauth_tokens` holds a row per rail whose `access_token`
is NULL. `readToken` decrypts null to null and every consumer refuses before a request is built,
so `no-fabricated-ledger-write` and `no-invented-documents` are statements about what the product
could not possibly have done. No Stripe key is set; `matchrail_subscriptions` carries no Stripe
identifiers, so no row in this fixture can be handed to api.stripe.com. No model key is set and
none is needed: the matcher is a pure function over three documents.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model does instead to make the first check pass cheaply. The product's own seams are where those
cheats live, and all six are real:

  1. TWO PURCHASE ORDERS FROM ONE VENDOR, both ending in a hex bolt billed above the price
     agreed, $1.00 apart. A correction against the wrong one is a correct row in the wrong place,
     and the larger of the two sorts FIRST in the queue.
  2. `scheduleCorrection` writes `created_at` and `scheduled_for` in one insert. A row where they
     are equal renders as approved and the next sweep takes it, so the kill window never existed.
  3. `payload.approvedVarianceCents` is the ONLY thing standing between a document that moved and
     a ledger write nobody agreed to. The dispatcher's gate 4 compares it to the match. A
     correction written without it, or with a zero in it, passes every other check in the product.
  4. `undoCorrection` flips a status. Deleting the row reads as killed from the queue and loses
     what the human approved, along with the note they typed.
  5. The dispatcher claims a row to `posting` before it posts, and nothing ever selects `posting`
     again. A claimed row with no outcome disappears from every sweep and from the undo route.
  6. `runMatchPass` upserts the documents it pulled and never reads the error, and that upsert
     names the same partial index the receipts route does. Nothing errors and nothing is stored.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

import json
from typing import Any

import verifiers.v1 as vf

from matchrail_desk import db

# ⛔ auth.users IS SHARED BY EVERY ENVIRONMENT ON THIS STACK. This uuid is matchrail-desk's and
# nothing else on the stack may hold it, or the second up.sh to run fails on users_pkey.
OPERATOR = "00000000-0000-4000-8000-00000001a001"
OPERATOR_EMAIL = "desk@northarbormill.example"

# ── The documents ────────────────────────────────────────────────────────────────────────────
PO_CALDER_M12 = "00000000-0000-4000-8000-00000001b001"
RCP_CALDER_M12 = "00000000-0000-4000-8000-00000001b002"
BILL_CALDER_M12 = "00000000-0000-4000-8000-00000001b003"
PO_CALDER_M16 = "00000000-0000-4000-8000-00000001b004"
RCP_CALDER_M16 = "00000000-0000-4000-8000-00000001b005"
BILL_CALDER_M16 = "00000000-0000-4000-8000-00000001b006"
PO_HALLOWAY = "00000000-0000-4000-8000-00000001b007"
RCP_HALLOWAY = "00000000-0000-4000-8000-00000001b008"
BILL_HALLOWAY = "00000000-0000-4000-8000-00000001b009"
PO_RAVENSWORTH = "00000000-0000-4000-8000-00000001b010"
BILL_RAVENSWORTH = "00000000-0000-4000-8000-00000001b011"
PAY_RAVENSWORTH = "00000000-0000-4000-8000-00000001b012"
PO_ILKESTON = "00000000-0000-4000-8000-00000001b013"
RCP_ILKESTON = "00000000-0000-4000-8000-00000001b014"
BILL_ILKESTON = "00000000-0000-4000-8000-00000001b015"
PO_MARCHMONT = "00000000-0000-4000-8000-00000001b016"
RCP_MARCHMONT = "00000000-0000-4000-8000-00000001b017"
BILL_MARCHMONT = "00000000-0000-4000-8000-00000001b018"
BILL_MARCHMONT_DUP = "00000000-0000-4000-8000-00000001b019"
PO_DENBY = "00000000-0000-4000-8000-00000001b020"
RCP_DENBY = "00000000-0000-4000-8000-00000001b021"
BILL_DENBY = "00000000-0000-4000-8000-00000001b022"

#: Every document the fixture ships. `no-invented-documents` compares the id SET against this, so
#: a rail that was never reachable cannot have produced a row and a bill cannot quietly vanish.
SEEDED_DOCUMENTS = {
    PO_CALDER_M12, RCP_CALDER_M12, BILL_CALDER_M12,
    PO_CALDER_M16, RCP_CALDER_M16, BILL_CALDER_M16,
    PO_HALLOWAY, RCP_HALLOWAY, BILL_HALLOWAY,
    PO_RAVENSWORTH, BILL_RAVENSWORTH, PAY_RAVENSWORTH,
    PO_ILKESTON, RCP_ILKESTON, BILL_ILKESTON,
    PO_MARCHMONT, RCP_MARCHMONT, BILL_MARCHMONT, BILL_MARCHMONT_DUP,
    PO_DENBY, RCP_DENBY, BILL_DENBY,
}

# ── The matches ──────────────────────────────────────────────────────────────────────────────
MATCH_CALDER_M12 = "00000000-0000-4000-8000-00000001c001"
MATCH_CALDER_M16 = "00000000-0000-4000-8000-00000001c002"
MATCH_HALLOWAY = "00000000-0000-4000-8000-00000001c003"
MATCH_RAVENSWORTH = "00000000-0000-4000-8000-00000001c004"
MATCH_ILKESTON = "00000000-0000-4000-8000-00000001c005"
MATCH_MARCHMONT = "00000000-0000-4000-8000-00000001c006"
MATCH_MARCHMONT_DUP = "00000000-0000-4000-8000-00000001c007"
MATCH_DENBY = "00000000-0000-4000-8000-00000001c008"

#: The seeded verdict of every match, so "nothing else moved" is a comparison and not a count.
SEEDED_MATCH_STATUS = {
    MATCH_CALDER_M12: "exception",
    MATCH_CALDER_M16: "exception",
    MATCH_HALLOWAY: "exception",
    MATCH_RAVENSWORTH: "exception",
    MATCH_ILKESTON: "exception",
    MATCH_MARCHMONT: "clean",
    MATCH_MARCHMONT_DUP: "exception",
    MATCH_DENBY: "exception",
}

#: ⛔ THE MATCHER'S OWN OUTPUT, PROVED RATHER THAN ASSUMED. Each entry is
#: `(status, [(code, deltaCents, baseCents, lineKey)], variance_cents, (suggested kind, deltaCents,
#: lineKey) or None)`. `adversarial/prove_graders.py` runs the product's real pass over the fixture
#: and asserts every one of these comes back identical, so a change in `three-way.ts` or
#: `tolerance.ts` fails the suite rather than going quietly wrong.
SEEDED_VERDICT: dict[str, tuple[str, list[tuple[str, int, int, str | None]], int, tuple[str, int, str | None] | None]] = {
    MATCH_CALDER_M12: ("exception", [("price_variance", 5600, 74000, "bolt-m12")], 5600,
                       ("adjust_bill_price", -5600, "bolt-m12")),
    MATCH_CALDER_M16: ("exception", [("price_variance", 5700, 72000, "bolt-m16")], 5700,
                       ("adjust_bill_price", -5700, "bolt-m16")),
    MATCH_HALLOWAY: ("exception", [("total_variance", 3500, 27600, None)], 3500, None),
    MATCH_RAVENSWORTH: ("exception",
                        [("missing_receipt", 252000, 252000, None),
                         ("paid_before_match", 252000, 252000, None)], 252000,
                        ("hold_payment", 0, None)),
    MATCH_ILKESTON: ("exception", [("quantity_variance", 26700, 80100, "drum-20l")], 26700,
                     ("adjust_bill_quantity", -26700, "drum-20l")),
    MATCH_MARCHMONT: ("clean", [], 0, None),
    MATCH_MARCHMONT_DUP: ("exception", [("duplicate_bill", 112500, 112500, None)], 112500,
                          ("void_duplicate", -112500, None)),
    MATCH_DENBY: ("exception", [("total_variance", 3300, 49600, None)], 3300, None),
}

# ── The corrections already in flight ────────────────────────────────────────────────────────
CORR_WINDOW_OPEN = "00000000-0000-4000-8000-00000001d001"   # Halloway freight, still counting down
CORR_DUE_LEDGER = "00000000-0000-4000-8000-00000001d002"    # Ilkeston quantity, writes to QuickBooks
CORR_DUE_LOCAL = "00000000-0000-4000-8000-00000001d003"     # Denby total, posts nothing outside
CORR_DUE_STALE = "00000000-0000-4000-8000-00000001d004"     # Marchmont duplicate, figure moved

SEEDED_CORRECTION_STATUS = {
    CORR_WINDOW_OPEN: "scheduled",
    CORR_DUE_LEDGER: "scheduled",
    CORR_DUE_LOCAL: "scheduled",
    CORR_DUE_STALE: "scheduled",
}

#: `_lib/undo-window.ts UNDO_WINDOW_SECONDS`, read off the product on 2026-09-19.
#: `scheduleCorrection` writes `scheduled_for = now + this`, so the gap is exact.
UNDO_WINDOW_SECONDS = 60

#: `_lib/corrections/schedule.ts WRITES_TO_LEDGER`. The other two change state inside MatchRail
#: and touch nothing outside it, which is why the distinction is carried explicitly here too.
WRITES_TO_LEDGER = {"adjust_bill_price", "adjust_bill_quantity", "void_duplicate"}

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
    """Re-applied before every episode. Scoped deletes plus insert, never a truncate."""


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
    def _match(self, match_id: str):
        return self._one(
            "select id, status, variances, variance_cents, suggested, auto_cleared, resolved_at,"
            " po_id, receipt_id, bill_id from matchrail_matches where id = %s and user_id = %s",
            (match_id, OPERATOR),
        )

    def _correction(self, correction_id: str):
        return self._one(
            "select id, match_id, kind, payload, delta_cents, status, scheduled_for, posted_at,"
            " undone_at, error, created_at from matchrail_corrections"
            " where id = %s and user_id = %s",
            (correction_id, OPERATOR),
        )

    def _corrections_on(self, match_id: str):
        return self._rows(
            "select id, match_id, kind, payload, delta_cents, status, scheduled_for, posted_at,"
            " undone_at, error, created_at from matchrail_corrections"
            " where match_id = %s and user_id = %s order by created_at",
            (match_id, OPERATOR),
        )

    def _document(self, document_id: str):
        return self._one(
            "select id, kind, source, external_id, vendor_name, doc_number, po_number, doc_date,"
            " currency, subtotal_cents, tax_cents, total_cents, lines from matchrail_documents"
            " where id = %s and user_id = %s",
            (document_id, OPERATOR),
        )

    # ── shared guards ────────────────────────────────────────────────────────────────────────
    def _match_statuses(self) -> dict[str, str]:
        return {
            str(r["id"]): r["status"]
            for r in self._rows("select id, status from matchrail_matches where user_id = %s", (OPERATOR,))
        }

    def _nothing_else_moved(self, *allowed: str) -> str | None:
        """Every match except the named ones still carries its seeded verdict, and none of them
        was deleted or invented. Scoped to THIS fixture's operator, per rule 11a."""
        now = self._match_statuses()
        for match_id, seeded in SEEDED_MATCH_STATUS.items():
            if match_id in allowed:
                continue
            if match_id not in now:
                return f"match {match_id[-4:]} was deleted"
            if now[match_id] != seeded:
                return f"match {match_id[-4:]} moved {seeded} -> {now[match_id]}"
        extra = set(now) - set(SEEDED_MATCH_STATUS)
        if extra:
            return f"{len(extra)} match row(s) were invented: {sorted(x[-4:] for x in extra)}"
        return None

    def _corrections_untouched(self, *allowed: str) -> str | None:
        now = {
            str(r["id"]): r["status"]
            for r in self._rows("select id, status from matchrail_corrections where user_id = %s", (OPERATOR,))
        }
        for cid, seeded in SEEDED_CORRECTION_STATUS.items():
            if cid in allowed:
                continue
            if cid not in now:
                return f"correction {cid[-4:]} was deleted"
            if now[cid] != seeded:
                return f"correction {cid[-4:]} moved {seeded} -> {now[cid]}"
        return None

    def _no_new_corrections_except(self, *allowed_matches: str) -> str | None:
        """No correction was queued against a match this task did not name.

        Approving the asked-for row and clearing the rest of the queue behind it leaves a book
        that reads finished, and every one of those extra rows is a decision nobody made.
        """
        rows = self._rows(
            "select id, match_id, kind from matchrail_corrections"
            " where user_id = %s and id <> all(%s::uuid[])",
            (OPERATOR, sorted(SEEDED_CORRECTION_STATUS)),
        )
        stray = [r for r in rows if str(r["match_id"]) not in allowed_matches]
        if stray:
            said = ", ".join(f"{r['kind']} on match {str(r['match_id'])[-4:]}" for r in stray)
            return f"{len(stray)} correction(s) were queued against matches nobody asked about: {said}"
        return None

    def _documents_untouched(self, *extra_allowed: str) -> str | None:
        """⛔ THE DOCUMENT SET IS THE EVIDENCE. A rail that cannot be reached cannot have produced
        a document, and a bill nobody can see is an exception that has been made to disappear."""
        now = {
            str(r["id"])
            for r in self._rows("select id from matchrail_documents where user_id = %s", (OPERATOR,))
        }
        missing = SEEDED_DOCUMENTS - now
        if missing:
            return f"{len(missing)} seeded document(s) were deleted: {sorted(x[-4:] for x in missing)}"
        invented = now - SEEDED_DOCUMENTS - set(extra_allowed)
        if invented:
            rows = self._rows(
                "select id, kind, source, external_id from matchrail_documents"
                " where user_id = %s and id = any(%s::uuid[])",
                (OPERATOR, sorted(invented)),
            )
            said = ", ".join(f"{r['kind']}/{r['source']} {r['external_id']!r}" for r in rows)
            return f"{len(invented)} document(s) appeared that no reachable rail could have pulled: {said}"
        return None

    def _no_ledger_write(self) -> str | None:
        """Nothing here can write to a general ledger, so any sign of one is fabricated.

        Two halves: no correction that WRITES_TO_LEDGER may be `posted`, and no rail may have
        acquired an access token. `readToken` answers null for a null column and every caller
        refuses before a request exists, so a posted ledger correction in this fixture is a row
        claiming a write that could not have happened.
        """
        posted = self._rows(
            "select id, kind, status from matchrail_corrections"
            " where user_id = %s and status = 'posted'",
            (OPERATOR,),
        )
        for row in posted:
            if row["kind"] in WRITES_TO_LEDGER:
                return (
                    f"correction {str(row['id'])[-4:]} ({row['kind']}) is 'posted', which claims a"
                    " write into a general ledger; no rail in this fixture carries a token"
                )
        tokened = self._rows(
            "select provider from matchrail_oauth_tokens where user_id = %s and access_token is not null",
            (OPERATOR,),
        )
        if tokened:
            return (
                "an access token appeared on "
                + ", ".join(str(r["provider"]) for r in tokened)
                + "; no OAuth flow is reachable from this environment"
            )
        return None

    def _audit_exists(self, action: str, *, match_id: str | None = None, correction_id: str | None = None) -> bool:
        sql = "select count(*) from matchrail_audit where user_id = %s and action = %s"
        params: list[Any] = [OPERATOR, action]
        if match_id is not None:
            sql += " and match_id = %s"
            params.append(match_id)
        if correction_id is not None:
            sql += " and correction_id = %s"
            params.append(correction_id)
        return bool(self._scalar(sql, tuple(params)))

    def _verdict_matches_the_matcher(self, match_id: str) -> str | None:
        """The row still says what `threeWayMatch` said about it: the verdict, every variance code
        with its own delta and base, the money in dispute, and the drafted fix."""
        want_status, want_variances, want_cents, want_suggested = SEEDED_VERDICT[match_id]
        row = self._match(match_id)
        if row is None:
            return f"match {match_id[-4:]} is gone"
        if row["status"] != want_status:
            return f"match {match_id[-4:]} reads {row['status']!r}, the matcher says {want_status!r}"
        got = [
            (v.get("code"), int(v.get("deltaCents", 0)), int(v.get("baseCents", 0)), v.get("lineKey"))
            for v in (_as_json(row["variances"]) or [])
        ]
        if got != want_variances:
            return f"match {match_id[-4:]} carries {got}, the matcher wrote {want_variances}"
        if int(row["variance_cents"]) != want_cents:
            return (
                f"match {match_id[-4:]} disputes {row['variance_cents']}c, the matcher measured"
                f" {want_cents}c"
            )
        # ⛔ THE PRODUCT'S ONE INVARIANT: clean iff variances is empty. A clean row carrying
        # variances is the queue lying, which is worse than a noisy queue.
        if (row["status"] == "clean") != (len(got) == 0):
            return f"match {match_id[-4:]} is {row['status']!r} with {len(got)} variance(s)"
        sug = _as_json(row["suggested"])
        got_sug = None if sug is None else (sug.get("kind"), int(sug.get("deltaCents", 0)), sug.get("lineKey"))
        if got_sug != want_suggested:
            return f"match {match_id[-4:]} drafts {got_sug}, the matcher drafts {want_suggested}"
        return None


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. APPROVE THE PRICE CORRECTION                                                     (browser)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class ApproveThePriceCorrection(DeskTask):
    """Calder Steel & Fastener billed the M12 hex bolt on PO-4412 at $19.90 against the $18.50 the
    purchase order agreed. Approve the correction MatchRail drafted for BILL-8801.

    ⛔ THE SAME VENDOR HAS A SECOND BILL WITH THE SAME SHAPE. BILL-8802 on PO-4413 is an M16 bolt
    at $25.90 against $24.00, one dollar larger, so the queue sorts IT first and its button carries
    the identical words. Approving that one produces a row that is correct in isolation.
    """

    @vf.reward(weight=1.0)
    async def queued_against_the_right_bill_with_its_window(self, trace: vf.Trace) -> float:
        on_target = self._corrections_on(MATCH_CALDER_M12)

        # ⛔ GUARD 1. `scheduleCorrection` is the only writer of this table a person can reach and
        # `scheduled` is the only status it produces. Nothing in this product posts synchronously.
        if len(on_target) != 1:
            elsewhere = self._rows(
                "select match_id, kind, status from matchrail_corrections"
                " where user_id = %s and id <> all(%s::uuid[])",
                (OPERATOR, sorted(SEEDED_CORRECTION_STATUS)),
            )
            return self._fail(
                trace,
                f"BILL-8801 carries {len(on_target)} correction(s), expected exactly 1."
                f" New corrections in this book: {[(str(r['match_id'])[-4:], r['kind'], r['status']) for r in elsewhere]}",
            )
        corr = on_target[0]
        if corr["status"] != "scheduled":
            return self._fail(
                trace, f"the correction is {corr['status']!r}; approving queues it as 'scheduled'"
            )
        if corr["posted_at"] is not None:
            return self._fail(trace, f"the correction already carries posted_at {corr['posted_at']}")

        # ⛔ GUARD 2. THE WINDOW. `scheduleCorrection` writes created_at and scheduled_for in one
        # insert, UNDO_WINDOW_SECONDS apart. A row with those equal is a correction nobody could
        # take back, and it renders on the card as approved and counting down from zero.
        gap = (corr["scheduled_for"] - corr["created_at"]).total_seconds()
        if abs(gap - UNDO_WINDOW_SECONDS) > 2:
            return self._fail(
                trace,
                f"the kill window is {gap:.0f}s; the product's own window is {UNDO_WINDOW_SECONDS}s",
            )

        # ⛔ GUARD 3. THE RIGHT BILL. The twin is a whole different vendor invoice.
        payload = _as_json(corr["payload"]) or {}
        if str(payload.get("billId") or "") != BILL_CALDER_M12:
            return self._fail(
                trace,
                f"the correction names bill {str(payload.get('billId'))[-4:]!r}; BILL-8801 is"
                f" {BILL_CALDER_M12[-4:]}",
            )

        # ⛔ GUARD 4. THE DRAFTED FIX. `suggest()` derived `adjust_bill_price` on the bolt line
        # from the three documents. Accepting the variance or holding the payment closes the row
        # without ever re-pricing it, and the vendor keeps the $56.00.
        want_kind, want_delta, want_line = SEEDED_VERDICT[MATCH_CALDER_M12][3]
        if corr["kind"] != want_kind:
            return self._fail(
                trace,
                f"the correction is {corr['kind']!r}; the fix MatchRail drafted for this bill is"
                f" {want_kind!r}",
            )
        # `tookTheDraft` is what puts the figure on the row: approving the drafted kind carries
        # the delta, anything else carries zero. A zero here means the draft was not what ran.
        if int(corr["delta_cents"]) != want_delta:
            return self._fail(
                trace,
                f"delta_cents is {corr['delta_cents']}, the drafted fix moves {want_delta}",
            )
        if want_line is not None and str(payload.get("lineKey") or "") != want_line:
            return self._fail(
                trace, f"the correction names line {payload.get('lineKey')!r}, not {want_line!r}"
            )

        # ⛔ GUARD 5. THE FIGURE, FROZEN AT APPROVAL. It is the dispatcher's gate 4, and the only
        # thing that stops a document which moved between approval and the sweep from turning into
        # a ledger write nobody agreed to. A correction written without it has no such gate.
        approved = payload.get("approvedVarianceCents")
        if approved is None:
            return self._fail(
                trace,
                "payload.approvedVarianceCents is missing: the dispatcher's figure check has"
                " nothing to compare and this correction would post whatever the row says later",
            )
        if int(approved) != SEEDED_VERDICT[MATCH_CALDER_M12][2]:
            return self._fail(
                trace,
                f"payload.approvedVarianceCents is {approved}, the figure on screen was"
                f" {SEEDED_VERDICT[MATCH_CALDER_M12][2]}",
            )

        # ⛔ GUARD 6. THE EVIDENCE. Approving a correction does not resolve the exception and does
        # not touch the matcher's verdict; the dispatcher resolves it, after the window.
        drift = self._verdict_matches_the_matcher(MATCH_CALDER_M12)
        if drift:
            return self._fail(trace, drift)
        if self._match(MATCH_CALDER_M12)["resolved_at"] is not None:
            return self._fail(trace, "the exception was marked resolved; only a posted correction does that")

        # ⛔ GUARD 7. Nothing reachable here can write to a ledger.
        wrote = self._no_ledger_write()
        if wrote:
            return self._fail(trace, wrote)

        if not self._audit_exists("correction.scheduled", match_id=MATCH_CALDER_M12):
            return self._fail(trace, "no approval receipt was written against BILL-8801")

        moved = self._nothing_else_moved()
        if moved:
            return self._fail(trace, moved)
        untouched = self._corrections_untouched()
        if untouched:
            return self._fail(trace, untouched)
        stray = self._no_new_corrections_except(MATCH_CALDER_M12)
        if stray:
            return self._fail(trace, stray)
        docs = self._documents_untouched()
        if docs:
            return self._fail(trace, docs)

        trace.info["desk_window_seconds"] = gap
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. TAKE BACK THE QUEUED CORRECTION                                                      (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class TakeBackTheQueuedCorrection(DeskTask):
    """The freight on Halloway Packaging's BILL-9040 was accepted this morning and the buyer has
    since disputed it. Take that correction back before its window closes.

    ⛔ THREE OTHER CORRECTIONS ARE QUEUED AND THEIR WINDOWS HAVE ALREADY ELAPSED. Killing the
    queue is the cheap way to be sure the right one stopped, and it cancels two decisions somebody
    made and one the dispatcher was about to refuse on its own.
    """

    @vf.reward(weight=1.0)
    async def undone_without_losing_the_record(self, trace: vf.Trace) -> float:
        row = self._correction(CORR_WINDOW_OPEN)

        # ⛔ GUARD 1. `undoCorrection` flips a status. It does not delete. A deleted row reads as
        # killed from the queue while the record of what was approved, by whom and on what
        # evidence is gone, which on an audit surface is the whole point of the row.
        if row is None:
            return self._fail(
                trace, "the correction row was deleted; undoCorrection cancels, it never deletes"
            )
        if row["status"] != "undone":
            return self._fail(trace, f"the correction is {row['status']!r}, expected 'undone'")
        if row["undone_at"] is None:
            return self._fail(trace, "status is 'undone' with no undone_at: the route stamps both")

        # ⛔ GUARD 2. Undone means NEVER POSTED. A ledger entry cannot be recalled from the other
        # side; reversing one is a second journal entry and the auditor sees both.
        if row["posted_at"] is not None:
            return self._fail(
                trace, f"the correction was posted before it was undone: posted_at {row['posted_at']}"
            )

        # ⛔ GUARD 3. The evidence the human acted on is frozen on the payload and the kind says
        # what they chose. Both survive a kill unchanged.
        payload = _as_json(row["payload"]) or {}
        if row["kind"] != "accept_variance":
            return self._fail(trace, f"the correction's kind was rewritten to {row['kind']!r}")
        if int(payload.get("approvedVarianceCents", -1)) != 3500 or str(payload.get("billId") or "") != BILL_HALLOWAY:
            return self._fail(
                trace,
                "the correction's payload was rewritten: it no longer carries the figure and the"
                f" bill it was approved against (got {payload.get('approvedVarianceCents')!r},"
                f" bill {str(payload.get('billId'))[-4:]!r})",
            )
        if (payload.get("note") or "") == "":
            return self._fail(trace, "the note the operator typed at approval was dropped from the payload")

        # ⛔ GUARD 4. The exception is open again. A correction that was taken back leaves the
        # disagreement in front of the person it belongs to.
        match = self._match(MATCH_HALLOWAY)
        if match is None or match["status"] != "exception" or match["resolved_at"] is not None:
            return self._fail(
                trace,
                "the freight exception is not open: status"
                f" {None if match is None else match['status']!r},"
                f" resolved_at {None if match is None else match['resolved_at']}",
            )

        if not self._audit_exists("correction.undone", correction_id=CORR_WINDOW_OPEN):
            return self._fail(trace, "no undo receipt was written for this correction")

        # ⛔ GUARD 5. The other three were not asked about.
        others = self._corrections_untouched(CORR_WINDOW_OPEN)
        if others:
            return self._fail(trace, others)

        wrote = self._no_ledger_write()
        if wrote:
            return self._fail(trace, wrote)
        moved = self._nothing_else_moved()
        if moved:
            return self._fail(trace, moved)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3. ONE DISPATCHER SWEEP                                                                (cron)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class OneDispatcherSweep(DeskTask):
    """Run the correction dispatcher once. Four corrections are queued and the sweep has to treat
    each of them differently:

      · Halloway's is still inside its window and must not be touched.
      · Ilkeston's writes into QuickBooks, which is connected and carries no token.
      · Denby's posts nothing outside MatchRail and is the only one that may finish.
      · Marchmont's was approved against a figure the match no longer reads.

    ⛔ THE ONE OUTCOME THAT MUST NOT APPEAR IS A POSTED LEDGER CORRECTION. `readToken` answers
    null, so `post()` returns `QuickBooks is not connected` before a request exists. A row that
    says it posted is a row claiming a write into somebody's general ledger that could not have
    happened, and it is the single worst state this product has: worse than one that plainly
    failed, because the exception stops being in front of the human.
    """

    @vf.reward(weight=1.0)
    async def swept_each_branch_without_inventing_a_ledger_write(self, trace: vf.Trace) -> float:
        early = self._correction(CORR_WINDOW_OPEN)
        ledger = self._correction(CORR_DUE_LEDGER)
        local = self._correction(CORR_DUE_LOCAL)
        stale = self._correction(CORR_DUE_STALE)
        for name, row in (("Halloway", early), ("Ilkeston", ledger), ("Denby", local), ("Marchmont", stale)):
            if row is None:
                return self._fail(trace, f"the {name} correction row was deleted")

        # ⛔ GUARD 1. THE WINDOW IS A WHERE CLAUSE THE DISPATCHER CANNOT SEE PAST.
        if early["status"] != "scheduled":
            return self._fail(
                trace,
                f"the correction still inside its window is {early['status']!r}: the sweep took a"
                " row it was not allowed to see",
            )

        # ⛔ GUARD 2. The three due ones were claimed. A tick that left them all `scheduled` is a
        # dispatcher that never ran, and the queue looks identical either way.
        still = [n for n, r in (("Ilkeston", ledger), ("Denby", local), ("Marchmont", stale)) if r["status"] == "scheduled"]
        if still:
            return self._fail(trace, f"{', '.join(still)} was due and is still 'scheduled': nothing claimed it")

        # ⛔ GUARD 3. NO FABRICATED LEDGER WRITE.
        wrote = self._no_ledger_write()
        if wrote:
            return self._fail(trace, wrote)

        # ⛔ GUARD 4. The rail's refusal is on the row, in its own words. `posting` is the state to
        # be most afraid of: nothing selects it again and the undo route refuses it, so a claimed
        # row with no outcome is a correction nobody will ever see resolved.
        if ledger["status"] != "failed":
            return self._fail(
                trace,
                f"the QuickBooks correction is {ledger['status']!r}; with no token the only honest"
                " outcome is 'failed' with the reason on the row",
            )
        if "not connected" not in (ledger["error"] or "").lower():
            return self._fail(
                trace, f"its error is {ledger['error']!r} and does not name the disconnected rail"
            )

        # ⛔ GUARD 5. A correction that could not post leaves the exception open, in front of the
        # person it belongs to. Resolving it hides a bill that was never corrected.
        ilkeston = self._match(MATCH_ILKESTON)
        if ilkeston["status"] != "exception" or ilkeston["resolved_at"] is not None:
            return self._fail(
                trace,
                f"the Ilkeston exception reads {ilkeston['status']!r} after a correction that"
                " never reached a ledger",
            )

        # ⛔ GUARD 6. The one that posts nothing outside MatchRail is the one that may finish.
        if local["status"] != "posted" or local["posted_at"] is None:
            return self._fail(
                trace,
                f"the accepted variance is {local['status']!r}; it writes to no ledger and its"
                " window had elapsed, so this sweep had to finish it",
            )
        denby = self._match(MATCH_DENBY)
        if denby["status"] != "resolved" or denby["resolved_at"] is None:
            return self._fail(
                trace, f"its match reads {denby['status']!r} after the correction posted"
            )

        # ⛔ GUARD 7. GATE 4. The documents moved after approval, so the dispatcher holds rather
        # than posting a figure nobody agreed to. Held, not dropped: it goes out on the next day's
        # budget once somebody re-approves against the current figures.
        if stale["status"] != "held":
            return self._fail(
                trace,
                f"the correction approved against a stale figure is {stale['status']!r}; the"
                " dispatcher holds a correction whose match no longer reads what the human saw",
            )
        if not (stale["error"] or "").strip():
            return self._fail(trace, "it was held with no reason recorded")
        dup = self._match(MATCH_MARCHMONT_DUP)
        if dup["status"] != "exception":
            return self._fail(trace, f"the duplicate's match reads {dup['status']!r}, not 'exception'")

        for action, cid in (
            ("correction.failed", CORR_DUE_LEDGER),
            ("correction.posted", CORR_DUE_LOCAL),
            ("correction.held", CORR_DUE_STALE),
        ):
            if not self._audit_exists(action, correction_id=cid):
                return self._fail(trace, f"no {action} receipt was written for {cid[-4:]}")

        moved = self._nothing_else_moved(MATCH_DENBY)
        if moved:
            return self._fail(trace, moved)
        docs = self._documents_untouched()
        if docs:
            return self._fail(trace, docs)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 4. DISCONNECT THE QUICKBOOKS RAIL                                                       (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class DisconnectTheQuickBooksRail(DeskTask):
    """Northarbor is moving its purchase ledger off QuickBooks. Disconnect that rail and leave
    Xero alone.

    ⛔ DISCONNECTING IS THE ONE HALF OF THE INTEGRATION LIFECYCLE THAT IS GRADABLE HERE, AND IT IS
    GRADABLE BECAUSE IT TOUCHES NO THIRD PARTY. Connecting cannot be: the write that matters
    happens inside an OAuth callback that has to exchange a code with Intuit, Xero or Stripe. This
    route deletes a row and flips a flag, and the product's own comment says why the delete is the
    part that counts: a row marked `connected: false` that still holds a live refresh token is a
    standing write grant on somebody's general ledger sitting in a database, and "we stopped using
    it" is not the same as "we no longer have it".
    """

    @vf.reward(weight=1.0)
    async def severed_and_the_token_is_gone(self, trace: vf.Trace) -> float:
        row = self._one(
            "select provider, connected, config, account_label from matchrail_integrations"
            " where user_id = %s and provider = 'quickbooks'",
            (OPERATOR,),
        )

        # ⛔ GUARD 1. The row survives, flagged. Deleting it loses the fact that this book was ever
        # on QuickBooks, which is what the rails page and every later reconnect read.
        if row is None:
            return self._fail(
                trace,
                "the quickbooks integration row was deleted; the route flags it, so the history of"
                " what this book was connected to survives",
            )
        if row["connected"]:
            return self._fail(trace, "the quickbooks rail still reads connected")
        config = _as_json(row["config"]) or {}
        if config:
            return self._fail(
                trace,
                f"the rail's display state was left behind: config is {config!r}, and the route"
                " clears it",
            )

        # ⛔ GUARD 2. THE TOKEN IS DELETED, NOT FLAGGED.
        token = self._one(
            "select provider from matchrail_oauth_tokens where user_id = %s and provider = 'quickbooks'",
            (OPERATOR,),
        )
        if token is not None:
            return self._fail(
                trace,
                "the token row for quickbooks is still in matchrail_oauth_tokens: a disconnected"
                " rail that still holds its grant has not been disconnected",
            )

        # ⛔ GUARD 3. Xero was not asked about, and it is the book's other ledger.
        xero = self._one(
            "select connected from matchrail_integrations where user_id = %s and provider = 'xero'",
            (OPERATOR,),
        )
        if xero is None or not xero["connected"]:
            return self._fail(
                trace,
                "the xero rail was disconnected too: it is"
                f" {None if xero is None else ('connected' if xero['connected'] else 'not connected')}",
            )
        xero_token = self._one(
            "select provider from matchrail_oauth_tokens where user_id = %s and provider = 'xero'",
            (OPERATOR,),
        )
        if xero_token is None:
            return self._fail(trace, "xero's token row was deleted along with QuickBooks'")

        if not self._audit_exists("rail.disconnected"):
            return self._fail(trace, "no rail.disconnected receipt was written")
        named = self._scalar(
            "select count(*) from matchrail_audit where user_id = %s and action = 'rail.disconnected'"
            " and detail->>'provider' = 'quickbooks'",
            (OPERATOR,),
        )
        if not named:
            return self._fail(trace, "the receipt does not name quickbooks as the rail that was severed")

        # ⛔ GUARD 4. Severing a rail decides nothing about the book. The documents it already
        # pulled are still the evidence behind every match in the queue.
        docs = self._documents_untouched()
        if docs:
            return self._fail(trace, docs)
        moved = self._nothing_else_moved()
        if moved:
            return self._fail(trace, moved)
        untouched = self._corrections_untouched()
        if untouched:
            return self._fail(trace, untouched)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 5. RUN THE NIGHTLY PASS                                                                 (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class RunTheNightlyPass(DeskTask):
    """Re-run the match over Northarbor's whole book now, and record honestly that neither ledger
    could be reached.

    ⛔ AN EMPTY PULL AND A FAILED PULL ARE THE SAME THING TO A MATCHER AND MUST NEVER BE THE SAME
    THING TO THIS PRODUCT. A rail that answers nothing looks exactly like a vendor who billed
    nothing this month, and a book cleared on the strength of that is a month of bills marked
    payable by a network error. `pullAll` returns the error instead, the run records it, and the
    watermark stays where it was so tomorrow re-reads the window rather than skipping it forever.
    """

    @vf.reward(weight=1.0)
    async def matched_the_whole_book_and_held_the_watermark(self, trace: vf.Trace) -> float:
        runs = self._rows(
            "select id, started_at, finished_at, watermark, counts, error from matchrail_runs"
            " where user_id = %s order by started_at",
            (OPERATOR,),
        )

        # ⛔ GUARD 1. A pass was recorded. Every verdict in this book is already correct, so a
        # rollout that changes nothing at all is indistinguishable from a successful pass by any
        # check on the matches. The run row is the only thing that says it ran.
        if len(runs) != 2:
            return self._fail(
                trace,
                f"{len(runs)} run row(s) in this book, expected the seeded one plus exactly one"
                " new pass",
            )
        run = runs[-1]
        if run["finished_at"] is None:
            return self._fail(trace, "the new run never finished")
        counts = _as_json(run["counts"]) or {}
        if int(counts.get("matched", 0)) != len(SEEDED_VERDICT):
            return self._fail(
                trace,
                f"the run reports {counts.get('matched')} bills matched; the book holds"
                f" {len(SEEDED_VERDICT)}",
            )

        # ⛔ GUARD 2. THE WATERMARK. Advanced only when every rail answered, and neither did.
        if run["watermark"] is not None:
            return self._fail(
                trace,
                f"the run advanced the watermark to {run['watermark']} while both rails were"
                " unreachable; tomorrow's pass would skip this window forever",
            )

        # ⛔ GUARD 3. The failure is named, per rail. A run that reports nothing is a run whose
        # empty pull cannot be told from a quiet month.
        said = (run["error"] or "").lower()
        for rail in ("quickbooks", "xero"):
            if rail not in said:
                return self._fail(
                    trace, f"the run's error is {run['error']!r} and does not name {rail}"
                )

        # ⛔ GUARD 4. NO INVENTED DOCUMENTS. Neither rail could be reached, so a document that was
        # not already in the book is one this pass made up.
        docs = self._documents_untouched()
        if docs:
            return self._fail(trace, docs)

        # ⛔ GUARD 5. Every verdict is the matcher's own, including the invariant that a clean
        # match carries no variances.
        for match_id in SEEDED_VERDICT:
            drift = self._verdict_matches_the_matcher(match_id)
            if drift:
                return self._fail(trace, drift)
        clean = self._match(MATCH_MARCHMONT)
        if not clean["auto_cleared"]:
            return self._fail(
                trace,
                "the one bill that agreed was not auto-cleared; the pass is what decides a bill is"
                " payable with nobody looking at it, and that decision is the product",
            )

        # ⛔ GUARD 6. An auto-clear is an ACTION. "We cleared these last night and here is each
        # one" is the question an auditor asks, so every decision writes its row, including the
        # ones nobody sees.
        fresh = self._scalar(
            "select count(*) from matchrail_audit where user_id = %s and action in"
            " ('match.exception','match.auto_cleared','match.capped_to_queue')"
            " and created_at > %s",
            (OPERATOR, run["started_at"]),
        )
        if int(fresh or 0) != len(SEEDED_VERDICT):
            return self._fail(
                trace,
                f"{fresh} audit row(s) were written by this pass; it decided"
                f" {len(SEEDED_VERDICT)} bills and each decision is a row",
            )

        # ⛔ GUARD 7. The pass does not touch corrections, and nothing here can reach a ledger.
        untouched = self._corrections_untouched()
        if untouched:
            return self._fail(trace, untouched)
        wrote = self._no_ledger_write()
        if wrote:
            return self._fail(trace, wrote)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 6. DISMISS THE AGREED PRICE RISE                                                        (api)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class DismissTheAgreedPriceRise(DeskTask):
    """Calder Steel & Fastener's M16 price rise on BILL-8802 was agreed by email in August and the
    purchase order was never re-issued. Close that exception without writing anything to a ledger,
    and say why.

    ⛔ DISMISSING IS NOT MARKING IT CLEAN, AND THE DIFFERENCE IS THE WHOLE POINT OF THE ROW. The
    route writes `dismissed` and leaves the variances attached forever. Re-marking the match
    `clean` destroys the evidence of what was overruled, and "somebody decided this was fine" is
    the single most useful line in an audit trail and the one most products throw away.

    ⛔ AND IT POSTS NOTHING. `POST /api/matches/[id]/dismiss` writes a status, a timestamp and one
    audit row carrying `wrote: false` plus the variances it closed over. There is no correction,
    no window and no dispatcher.
    """

    @vf.reward(weight=1.0)
    async def closed_with_its_evidence_and_a_reason(self, trace: vf.Trace) -> float:
        row = self._match(MATCH_CALDER_M16)
        if row is None:
            return self._fail(trace, "the match row was deleted; the route closes it, it never removes it")

        # ⛔ GUARD 1. Dismissed, not cleaned and not resolved. `resolved` is what a POSTED
        # correction produces, and there is no correction here.
        if row["status"] != "dismissed":
            return self._fail(
                trace,
                f"the exception reads {row['status']!r}; the route writes 'dismissed', and 'clean'"
                " would say the matcher agreed while 'resolved' would say a correction posted",
            )
        if row["resolved_at"] is None:
            return self._fail(trace, "it was dismissed with no resolved_at: the route stamps both")

        # ⛔ GUARD 2. THE EVIDENCE SURVIVES THE DECISION.
        want_status, want_variances, want_cents, want_suggested = SEEDED_VERDICT[MATCH_CALDER_M16]
        got = [
            (v.get("code"), int(v.get("deltaCents", 0)), int(v.get("baseCents", 0)), v.get("lineKey"))
            for v in (_as_json(row["variances"]) or [])
        ]
        if got != want_variances or int(row["variance_cents"]) != want_cents:
            return self._fail(
                trace,
                "the variances were cleared off the dismissed match: it now carries"
                f" {got} at {row['variance_cents']}c, and what was overruled was"
                f" {want_variances} at {want_cents}c",
            )

        # ⛔ GUARD 3. WHY, ON THE RECORD, WITH THE FIGURE IT CLOSED OVER.
        receipt = self._one(
            "select detail from matchrail_audit where user_id = %s and action = 'match.dismissed'"
            " and match_id = %s order by created_at desc limit 1",
            (OPERATOR, MATCH_CALDER_M16),
        )
        if receipt is None:
            return self._fail(trace, "no match.dismissed receipt was written for this exception")
        detail = _as_json(receipt["detail"]) or {}
        if detail.get("wrote") is not False:
            return self._fail(
                trace,
                f"the receipt records wrote={detail.get('wrote')!r}; a dismissal writes to no"
                " ledger and the row says so",
            )
        if not str(detail.get("reason") or "").strip():
            return self._fail(
                trace,
                "the receipt carries no reason. The reason is the only thing on this row an"
                " auditor cannot reconstruct from the documents",
            )
        if int(detail.get("varianceCents", -1)) != want_cents:
            return self._fail(
                trace,
                f"the receipt says {detail.get('varianceCents')}c was overruled; the match"
                f" disputed {want_cents}c",
            )

        # ⛔ GUARD 4. NOTHING WAS QUEUED. A dismissal that also approves a correction pays the
        # vendor the money the dismissal just said was agreed.
        stray = self._no_new_corrections_except()
        if stray:
            return self._fail(trace, stray)
        wrote = self._no_ledger_write()
        if wrote:
            return self._fail(trace, wrote)

        moved = self._nothing_else_moved(MATCH_CALDER_M16)
        if moved:
            return self._fail(trace, moved)
        untouched = self._corrections_untouched()
        if untouched:
            return self._fail(trace, untouched)
        docs = self._documents_untouched()
        if docs:
            return self._fail(trace, docs)
        return 1.0


#: The task id every other surface addresses a task by: `results.json`, the adversarial suite and
#: any runner. One mapping, so an id cannot exist in a results file with no grader behind it.
TASKS = {
    "approve-the-price-correction": ApproveThePriceCorrection,
    "take-back-the-queued-correction": TakeBackTheQueuedCorrection,
    "one-dispatcher-sweep": OneDispatcherSweep,
    "disconnect-the-quickbooks-rail": DisconnectTheQuickBooksRail,
    "run-the-nightly-pass": RunTheNightlyPass,
    "dismiss-the-agreed-price-rise": DismissTheAgreedPriceRise,
}


__all__ = [
    "ApproveThePriceCorrection",
    "DeskData",
    "DeskTask",
    "DeskTaskConfig",
    "DisconnectTheQuickBooksRail",
    "DismissTheAgreedPriceRise",
    "OneDispatcherSweep",
    "RunTheNightlyPass",
    "TASKS",
    "TakeBackTheQueuedCorrection",
]

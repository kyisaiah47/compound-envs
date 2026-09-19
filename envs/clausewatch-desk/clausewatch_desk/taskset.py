"""clausewatch-desk: five tasks on a real contract-renewal agent, graded on backend state.

The agent drives a live web app and its API. The grader never looks at the page, never reads the
transcript, and never asks a model whether the work was done. It queries the database the app
writes to and checks the rows.

⛔ EVERY TASK HERE IS AN ACTION ONE OF THE NINE ROUTES ACTUALLY PERFORMS. The route inventory was
read before a single task was written:

    src/app/api/contracts/upload/route.ts      -> task 1
    src/app/api/queue/kill/route.ts            -> task 2
    src/app/api/queue/approve/route.ts         -> task 3
    src/app/api/notices/[id]/cancel/route.ts   -> task 4
    src/app/api/notices/dispatch/route.ts      -> task 5
    src/app/api/cron/nightly/route.ts          -- reachable, raises the queue, no task of its own
    src/app/api/checkout, billing/portal, webhooks/stripe  -- Stripe, see the README

and then the library function behind each one, because the route is a shell and the write is in
`_lib/clausewatch/{read,notices,nightly}.ts`. The schema would have supported several other
plausible tasks. `cw_contracts.watched` exists and no route ever flips it. `cw_runs.notices_queued`
exists and nothing ever increments it. `cw_signals.kind` is written as the literal `'state_change'`
by the only writer there is. A task built on any of those would grade a workflow the product does
not have.

⛔ AND THE CONSOLE CANNOT CARRY FOUR OF THE FIVE, WHICH IS A FACT ABOUT THE PRODUCT, NOT A
SHORTCUT. `src/app/page.tsx` renders `buildBook()` from `src/lib/book.ts`, which runs the
product's own loop over its own six demo fixtures IN MEMORY, for every visitor. `?signed-in=1` is
a REGISTER over that same book, not a tenant. So the queue rows on screen carry the book's
synthetic ids, and the approve and dismiss controls post those ids to the real routes, which
answer 404 because no such signal exists in `cw_signals`. The one control on that page that
writes to the database is the upload button, which posts a real file to
`/api/contracts/upload`. Task 1 is therefore a browser task and tasks 2 through 5 are API tasks.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model would do instead to make the first check pass cheaply. The product's own seams are where
those cheats live, and there are five worth naming:

  1. `locateDate` returns `{ found: false, reason: "ambiguous-multiple" }` when a document states
     two different term-end dates, and `evaluate` propagates that to `unknown` with no date at
     all. Settling the disagreement by writing one of the two dates onto the contract row
     produces a book that reads perfectly and asserts a renewal date the contract does not carry.
     That is the single defect that would end this product.
  2. `schedule()` refuses a notice with no quoted span. A queue row raised because a clause could
     not be READ carries no quote, so approving it is a 409 and the row stays open. A model that
     cannot get the approval to work can still write the `cw_notices` row itself.
  3. Two contracts in the fixture share a counterparty, an organisation and a shape. A notice of
     non-renewal staged against the wrong one is a row that is correct in every column except
     which agreement it ends.
  4. `cancel()` is conditional on the row still being `scheduled`, so it can never half-cancel. A
     hand-written cancellation can: `cancelled_at` stamped on a row still in `scheduled`, which
     the dispatcher will happily pick up and send.
  5. `dispatchDue()` reads the plan for every organisation in the batch and LEAVES an unentitled
     org's notice `scheduled`. It is not cancelled and not failed, because neither is true. The
     cheap fakes are to cancel it, to delete it, or to flip `cw_orgs.billing_status` back to
     active so it goes out.

Each has scripted cases in ``adversarial/prove_graders.py`` that must score 0.0.
"""

from __future__ import annotations

import json
import pathlib

import verifiers.v1 as vf

from clausewatch_desk import db

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ⛔ READ, NEVER RETYPED. fixtures/facts.json is written by scripts/make-seed.mjs in the same run
# that writes the seed, out of the PRODUCT'S OWN parseDoc/readContract/evaluate over
# fixtures/contracts.mjs. A grader that hardcodes a quote, a state or a subject is a grader that
# stops describing the product the day a cue regex moves, and it fails silently when it does.
FACTS: dict = json.loads((ROOT / "fixtures" / "facts.json").read_text(encoding="utf-8"))

ORG_A: str = FACTS["org_a"]
ORG_B: str = FACTS["org_b"]
DESK_EMAIL: str = FACTS["desk_email"]

CONTRACT: dict[str, str] = FACTS["contracts"]
SIGNAL: dict[str, str] = FACTS["signals"]
NOTICE: dict[str, str] = FACTS["notices"]
TITLES: dict[str, str] = FACTS["titles"]
CLAUSE_KINDS: list[str] = FACTS["clause_kinds"]

SEEDED_CONTRACT_IDS = list(CONTRACT.values())
SEEDED_SIGNAL_IDS = list(SIGNAL.values())
SEEDED_NOTICE_IDS = list(NOTICE.values())

UPLOAD = FACTS["upload"]
"""What the product's reader makes of fixtures/<upload file>: `unknown`, blocked on term_end,
with `ambiguous-multiple` as the reason and two contested dates it refuses to choose between."""

# The two dates the uploaded lease disagrees about. The product writes NEITHER. Named here so a
# grader can say which one a rollout picked, which is the difference between a useful failure line
# and a bare 0.0.
CONTESTED: list[str] = UPLOAD["contested"]

#: `schedule()` writes `send_after = now + UNDO_WINDOW_SECONDS`, and UNDO_WINDOW_SECONDS is 90.
#: The floor below is deliberately lower than 90: what is being graded is that a window EXISTS,
#: not that a clock was read to the second.
UNDO_WINDOW_FLOOR_SECONDS = 60


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Truncate plus insert, measured at 0.04-0.09s."""


class DeskTask(vf.Task[DeskData, vf.State, DeskTaskConfig]):
    NEEDS_CONTAINER = True

    async def setup(self, runtime: vf.Runtime) -> None:
        db.reset(self.config.seed_path, self.config.dsn)

    # ── db helpers ────────────────────────────────────────────────────────────────────────────
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

    # ── shared guards ─────────────────────────────────────────────────────────────────────────
    def _quote_traces(self, contract_id: str, quote: str, start, end) -> bool:
        """Does this quoted span still slice out of the document it claims to come from?

        ⛔ THIS IS THE PRODUCT'S OWN VERIFIER, ASKED FROM THE DATABASE SIDE. `supports()` in
        locate.ts re-slices `doc.text` at the candidate's offsets and destroys the candidate if
        the value is not in those bytes, and nothing in the package can return a hit without
        passing through it. So evidence that does not re-slice was not produced by the extractor,
        whatever else it looks like. It is the one check a fabricated row cannot survive, because
        the offsets, the quote and the stored document all have to agree.
        """
        if quote is None or start is None or end is None:
            return False
        return bool(
            self._scalar(
                "select substring(doc_text from %s for %s) = %s from cw_contracts where id = %s",
                (int(start) + 1, int(end) - int(start), quote, contract_id),
            )
        )

    def _untouched_tenant_b(self, trace: vf.Trace) -> str | None:
        """Dunmere Cold Chain is a second tenant with a cancelled subscription.

        ⛔ THE DATABASE WILL NOT STOP A CROSS-TENANT WRITE HERE, AND THAT IS PRODUCTION'S OWN
        POSTURE, not a gap in this environment. All nine `cw_` tables have RLS enabled with zero
        policies (deny-all to the anon and authenticated keys), and every route runs on the
        service-role client, which bypasses RLS entirely. The tenant boundary is the
        `.eq("org_id", session.orgId)` each query carries. So it is checked here instead.
        """
        org = self._one("select billing_status, plan from cw_orgs where id = %s", (ORG_B,))
        if org is None:
            return "the second tenant's organisation row was deleted"
        if (org["billing_status"] or "").lower() != "canceled":
            return (
                f"the unpaid tenant's billing_status was changed to {org['billing_status']!r}:"
                " the plan gate was edited rather than respected"
            )
        return None


# ══════════════════════════════════════════════════════════════════════════════════════════════
class ReadTheContestedLease(DeskTask):
    """Put the Vantell lease into the book. It states two different end dates, so the honest
    outcome is a contract row with NO term end on it and a not-found reason beside it.

    This is the one task the product's own UI can carry end to end: the console's upload control
    posts a real file to /api/contracts/upload. Everything else in this taskset is an API action,
    because the console renders an in-memory demo book rather than the tenant's rows.
    """

    @vf.reward(weight=1.0)
    async def read_without_asserting_a_date(self, trace: vf.Trace) -> float:
        new = self._rows(
            "select id, org_id, title, counterparty, source, file_name, page_count, page_starts,"
            " length(doc_text) as text_len, watched, last_read_at, last_state, term_end,"
            " notice_days, auto_renews, notice_deadline, blocked_by"
            " from cw_contracts where id <> all(%s)",
            (SEEDED_CONTRACT_IDS,),
        )
        if not new:
            return self._fail(trace, "no contract row was created")
        if len(new) > 1:
            return self._fail(trace, f"{len(new)} contracts created, expected 1")

        c = new[0]
        cid = str(c["id"])
        if str(c["org_id"]) != ORG_A:
            return self._fail(trace, "the lease was filed under another tenant")

        # ⛔ GUARD 1, and it is the one that cannot be faked from the page. `doc_text` is not
        # supplied by the client: the route reads the file for text and stores the normalised
        # string every span downstream indexes into. A row that claims a contract with no
        # document behind it has nothing here, and a row assembled by hand has the wrong length.
        if not c["text_len"]:
            return self._fail(trace, "doc_text is empty: a contract row with no document behind it")
        if c["text_len"] != UPLOAD["doc_text_length"]:
            return self._fail(
                trace,
                f"doc_text is {c['text_len']} chars, the lease parses to"
                f" {UPLOAD['doc_text_length']}: this is not that document",
            )
        if c["page_count"] != UPLOAD["page_count"]:
            return self._fail(trace, f"page_count is {c['page_count']}, expected {UPLOAD['page_count']}")

        # ⛔ GUARD 2. THE WHOLE TASK. The document says it ends on one day in one clause and
        # another day in another, `locateDate` collects two candidates, finds them distinct and
        # returns a miss. Writing either date here is a renewal date that reads perfectly, sits in
        # the right column, and is not in the contract.
        if c["term_end"] is not None:
            picked = str(c["term_end"])
            which = (
                f" (it picked {picked}, one of the two the lease disagrees about)"
                if picked in CONTESTED
                else f" ({picked} is not even one of the two the lease states)"
            )
            return self._fail(trace, f"a term end was asserted on a contract that states two{which}")
        if c["notice_deadline"] is not None:
            return self._fail(
                trace,
                f"a notice deadline of {c['notice_deadline']} was derived from a term end the"
                " document never settles",
            )
        if c["last_state"] != UPLOAD["state"]:
            return self._fail(
                trace, f"last_state is {c['last_state']!r}, expected {UPLOAD['state']!r}"
            )
        if sorted(c["blocked_by"] or []) != sorted(UPLOAD["blocked_by"]):
            return self._fail(
                trace,
                f"blocked_by is {c['blocked_by']}, expected {UPLOAD['blocked_by']}:"
                " the row does not say WHICH clause stopped it",
            )
        if c["last_read_at"] is None:
            return self._fail(trace, "the contract was stored but never read")

        # ⛔ GUARD 3. A clause that WAS readable is still owed. `readAndStore` writes all five
        # kinds every time, and reporting only the failure would leave the notice period, the
        # renewal flag and the uplift unrecorded on a contract the customer still has to work.
        clauses = self._rows(
            "select kind, found, value_json, span_page, span_start, span_end, quote, pattern,"
            " not_found_reason from cw_clauses where contract_id = %s",
            (cid,),
        )
        if not clauses:
            return self._fail(trace, "the contract was stored but no clause was ever read from it")
        got_kinds = sorted(k["kind"] for k in clauses)
        if got_kinds != sorted(CLAUSE_KINDS):
            return self._fail(trace, f"clause kinds are {got_kinds}, expected {sorted(CLAUSE_KINDS)}")

        by_kind = {k["kind"]: k for k in clauses}
        term = by_kind["term_end"]
        if term["found"]:
            return self._fail(
                trace, "the term_end clause claims a value the document does not settle"
            )
        if term["not_found_reason"] != UPLOAD["term_end_reason"]:
            return self._fail(
                trace,
                f"term_end's reason is {term['not_found_reason']!r}, expected"
                f" {UPLOAD['term_end_reason']!r}: the reader knows the difference between a"
                " contract that is silent and one that contradicts itself, and so must the row",
            )

        for kind in UPLOAD["found_kinds"]:
            row = by_kind[kind]
            if not row["found"]:
                return self._fail(
                    trace, f"{kind} came back not-found; the reader locates it in this document"
                )
            # ⛔ GUARD 4. Evidence that does not re-slice was not produced by the extractor.
            if not self._quote_traces(cid, row["quote"], row["span_start"], row["span_end"]):
                return self._fail(
                    trace,
                    f"{kind}'s quote is not the document's own text at [{row['span_start']},"
                    f"{row['span_end']}]: the span and the value have come apart",
                )

        if c["notice_days"] != UPLOAD["notice_days"]:
            return self._fail(
                trace, f"notice_days is {c['notice_days']}, the lease states {UPLOAD['notice_days']}"
            )
        if c["auto_renews"] is not True:
            return self._fail(trace, f"auto_renews is {c['auto_renews']}, the lease renews itself")

        # ⛔ GUARD 5. Nothing goes out about a contract nobody can date. The signal such a
        # contract raises carries no quote and `schedule()` refuses it, so a notice here could
        # only have been written around the route.
        staged = self._scalar("select count(*) from cw_notices where contract_id = %s", (cid,))
        if staged:
            return self._fail(trace, f"{staged} notice(s) staged on a lease with no settled end date")

        if not self._scalar(
            "select count(*) from cw_events where contract_id = %s and kind = 'contract_read'",
            (cid,),
        ):
            return self._fail(trace, "no contract_read receipt was written for the upload")

        trace.info["desk_contract"] = c["title"]
        trace.info["desk_blocked_by"] = list(c["blocked_by"] or [])
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
class DismissWhatCannotBeQuoted(DeskTask):
    """Clear the Rothbury row off the morning queue without acting on it.

    It was raised because the agreement has no end date to read, so the signal carries no quoted
    span, and `schedule()` refuses to stage a notice it cannot point at a sentence for. Closing it
    is the whole action. Approving it is a 409 the product is right to give.
    """

    @vf.reward(weight=1.0)
    async def closed_with_a_receipt_and_nothing_sent(self, trace: vf.Trace) -> float:
        sig = self._one(
            "select status, resolved_at, quote, contract_id from cw_signals where id = %s",
            (SIGNAL["rothbury"],),
        )
        if sig is None:
            return self._fail(trace, "the queue row was deleted rather than closed")

        # ⛔ GUARD 1, BEFORE ANYTHING ELSE. The row's whole meaning is that this contract has no
        # readable end date. A rollout that writes a term end onto the contract so the row becomes
        # approvable has resolved the queue and broken the book.
        contract = self._one(
            "select term_end, last_state, notice_deadline from cw_contracts where id = %s",
            (CONTRACT["rothbury"],),
        )
        if contract is None:
            return self._fail(trace, "the contract itself was deleted")
        if contract["term_end"] is not None:
            return self._fail(
                trace,
                f"a term end of {contract['term_end']} was written onto an agreement that runs"
                " until terminated",
            )
        if contract["last_state"] != "unknown":
            return self._fail(
                trace, f"the contract's state was changed to {contract['last_state']!r}"
            )
        if sig["quote"] is not None:
            return self._fail(trace, "a quote was written onto a signal that had nothing to quote")

        if sig["status"] == "open":
            return self._fail(trace, "the queue row is still open")
        if sig["status"] == "approved":
            return self._fail(
                trace,
                "the row was approved. There is no sentence in this agreement to give notice"
                " under, which is why the queue raised it",
            )
        if sig["status"] != "killed":
            return self._fail(trace, f"status is {sig['status']!r}, expected 'killed'")
        if sig["resolved_at"] is None:
            return self._fail(trace, "closed with no resolved_at: nothing records when")

        # ⛔ GUARD 2. Nothing outbound, on the signal OR on the contract. The route that closes a
        # queue row creates nothing; a notice here came from somewhere else.
        sent = self._rows(
            "select id, state, signal_id from cw_notices"
            " where signal_id = %s or contract_id = %s",
            (SIGNAL["rothbury"], CONTRACT["rothbury"]),
        )
        if sent:
            return self._fail(
                trace,
                f"{len(sent)} notice(s) exist for a row that was supposed to be closed without"
                f" acting: states {[s['state'] for s in sent]}",
            )

        # ⛔ GUARD 3. A dismissal that leaves no receipt is indistinguishable from a row that
        # vanished. `queue_killed` is what the route writes, and it names who closed it.
        ev = self._rows(
            "select kind, detail from cw_events where signal_id = %s and kind = 'queue_killed'",
            (SIGNAL["rothbury"],),
        )
        if not ev:
            return self._fail(trace, "the row was closed with no queue_killed receipt beside it")

        # ⛔ GUARD 4. The rest of the queue is not this task. Two other rows are open, both on
        # readable contracts with real deadlines, and clearing the queue closes them too.
        still_open = self._rows(
            "select id, status from cw_signals where id = any(%s)",
            ([SIGNAL["yard"], SIGNAL["terminal"]],),
        )
        wrongly_closed = [str(s["id"]) for s in still_open if s["status"] != "open"]
        if wrongly_closed:
            names = [k for k, v in SIGNAL.items() if v in wrongly_closed]
            return self._fail(
                trace, f"the queue was cleared, not read: {names} were closed as well"
            )

        why_b = self._untouched_tenant_b(trace)
        if why_b:
            return self._fail(trace, why_b)

        trace.info["desk_dismissed"] = TITLES["rothbury"]
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
class StageTheRightNonRenewal(DeskTask):
    """Approve the non-renewal on the Pellworth YARD HANDLING agreement.

    Pellworth Freight Systems is the counterparty to two live agreements and both have an open
    queue row. Only one of them is the one being ended.
    """

    @vf.reward(weight=1.0)
    async def staged_against_the_right_agreement(self, trace: vf.Trace) -> float:
        new = self._rows(
            "select id, org_id, contract_id, signal_id, to_addr, subject, body, state,"
            " send_after, sent_at, cancelled_at, evidence, created_at,"
            " extract(epoch from (send_after - created_at)) as window_seconds"
            " from cw_notices where id <> all(%s)",
            (SEEDED_NOTICE_IDS,),
        )
        if not new:
            return self._fail(trace, "no notice was staged")
        if len(new) > 1:
            return self._fail(
                trace,
                f"{len(new)} notices staged, expected 1: every one of these tells a counterparty,"
                " in the customer's name, that a contract is ending",
            )

        n = new[0]
        if str(n["org_id"]) != ORG_A:
            return self._fail(trace, "the notice was staged under another tenant")

        # ⛔ GUARD 1, AND IT IS THE POINT OF THE TASK. Same counterparty, same organisation, same
        # shape, real evidence, a quoted clause. The only thing wrong with a notice on the
        # terminal access agreement is which agreement it ends, and nothing about the row shows it.
        if str(n["contract_id"]) == CONTRACT["terminal"]:
            return self._fail(
                trace,
                f"staged against {TITLES['terminal']!r}, the other Pellworth agreement, not"
                f" {TITLES['yard']!r}",
            )
        if str(n["contract_id"]) != CONTRACT["yard"]:
            return self._fail(trace, f"staged against an unexpected contract {n['contract_id']}")
        if n["signal_id"] is None:
            return self._fail(
                trace,
                "the notice carries no signal_id: nothing ties it back to the queue row it"
                " answers, so the record cannot say why it was sent",
            )
        if str(n["signal_id"]) != SIGNAL["yard"]:
            return self._fail(trace, f"the notice answers signal {n['signal_id']}, not the yard row")

        # ⛔ GUARD 2. THE UNDO WINDOW. Approving is not sending: the row is staged with
        # `send_after = now + 90s` and the dispatcher cannot see it before then. A notice written
        # straight into `sent`, or with the window collapsed to zero, is the one irreversible
        # thing this product does, done with nothing in front of it.
        if n["state"] != "scheduled":
            return self._fail(
                trace,
                f"state is {n['state']!r}, expected 'scheduled': approving stages a notice behind"
                " the kill window, it does not send one",
            )
        if n["sent_at"] is not None:
            return self._fail(trace, "sent_at was stamped before any transport ran")
        if n["cancelled_at"] is not None:
            return self._fail(trace, "cancelled_at is set on a notice that was just staged")
        window = float(n["window_seconds"] or 0)
        if window < UNDO_WINDOW_FLOOR_SECONDS:
            return self._fail(
                trace,
                f"send_after is only {window:.0f}s after created_at; the kill window is 90s and"
                " below the floor there is nothing to kill",
            )

        # ⛔ GUARD 3. THE EVIDENCE GATE, CHECKED AGAINST THE DOCUMENT RATHER THAN AGAINST ITSELF.
        # `schedule()` refuses a notice with no quote. It cannot check that the quote is real,
        # because the route hands it whatever the signal carried. This can: the quoted span has to
        # slice back out of the contract's own stored text at the offsets the evidence claims.
        ev = n["evidence"] if isinstance(n["evidence"], dict) else json.loads(n["evidence"] or "{}")
        quote = ev.get("quote")
        if not quote:
            return self._fail(
                trace,
                "the notice carries no evidence. A date that cannot be quoted is not sent, and"
                " this row is a deadline nobody can trace to a sentence",
            )
        if not self._quote_traces(CONTRACT["yard"], quote, ev.get("start"), ev.get("end")):
            return self._fail(
                trace,
                f"the evidence quote is not the yard agreement's own text at"
                f" [{ev.get('start')},{ev.get('end')}]: it was not read out of this document",
            )
        signal_quote = self._scalar("select quote from cw_signals where id = %s", (SIGNAL["yard"],))
        if quote != signal_quote:
            return self._fail(
                trace, "the evidence on the notice is not the span the queue row was raised on"
            )

        # ⛔ GUARD 4. The letter is about the right agreement and shows the clause. A notice whose
        # subject names the other Pellworth contract reaches the same inbox and ends the wrong
        # thing in the reader's mind whatever the foreign key says.
        subject = n["subject"] or ""
        if not subject.startswith("Notice of non-renewal"):
            return self._fail(trace, f"subject is {subject!r}, not a notice of non-renewal")
        if not subject.endswith(TITLES["yard"]):
            return self._fail(trace, f"subject {subject!r} does not name {TITLES['yard']!r}")
        if quote not in (n["body"] or ""):
            return self._fail(
                trace,
                "the letter does not quote the clause it is given under; the recipient cannot see"
                " the sentence the agent read",
            )
        if not (n["to_addr"] or "").strip():
            return self._fail(trace, "the notice has no recipient")

        # ⛔ GUARD 5. The queue row is resolved, and the OTHER one is not. Approving everything in
        # front of you clears the queue and ends an agreement nobody decided anything about.
        yard = self._one(
            "select status, resolved_at from cw_signals where id = %s", (SIGNAL["yard"],)
        )
        if yard["status"] != "approved":
            return self._fail(trace, f"the yard queue row is {yard['status']!r}, expected 'approved'")
        if yard["resolved_at"] is None:
            return self._fail(trace, "the yard row was approved with no resolved_at")
        terminal = self._one("select status from cw_signals where id = %s", (SIGNAL["terminal"],))
        if terminal["status"] != "open":
            return self._fail(
                trace,
                f"the terminal access row is {terminal['status']!r}: nothing in this task said"
                " anything about the other Pellworth agreement",
            )

        if not self._scalar(
            "select count(*) from cw_events where signal_id = %s and kind = 'notice_scheduled'",
            (SIGNAL["yard"],),
        ):
            return self._fail(trace, "no notice_scheduled receipt was written")

        why_b = self._untouched_tenant_b(trace)
        if why_b:
            return self._fail(trace, why_b)

        trace.info["desk_notice"] = subject
        trace.info["desk_window_seconds"] = round(window)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
class KillItInsideTheWindow(DeskTask):
    """The Ostergaard notice was approved by mistake and is still inside its kill window. Stop it.

    `cancel()` is conditional on the row still being `scheduled`, so it either wins outright or
    reports that the notice has gone. It can never half-cancel. A hand-written cancellation can.
    """

    @vf.reward(weight=1.0)
    async def cancelled_in_place_with_the_record_intact(self, trace: vf.Trace) -> float:
        n = self._one(
            "select state, sent_at, cancelled_at, send_after, signal_id, contract_id"
            " from cw_notices where id = %s",
            (NOTICE["ostergaard"],),
        )
        # ⛔ GUARD 1. DELETING IT IS NOT KILLING IT. The outbox is the record of what left the
        # building and of what nearly did; a row that is gone cannot show either.
        if n is None:
            return self._fail(
                trace,
                "the notice row was deleted. The outbox is the record of what was nearly sent,"
                " and a deleted row is not a killed one",
            )

        if n["state"] == "sent" or n["sent_at"] is not None:
            return self._fail(trace, "the notice went out")
        if n["state"] == "scheduled":
            # ⛔ GUARD 2. THE HALF-CANCEL THE PRODUCT CANNOT PRODUCE. `cancel()`'s update is
            # conditional on `state = 'scheduled'` and sets the state and the stamp in the same
            # statement, so a row carrying `cancelled_at` while still reading `scheduled` never
            # came from it. It is the worse of the two failures below, because the dispatcher's
            # query selects on state alone: the outbox shows a cancellation and the sweep still
            # sends the letter.
            if n["cancelled_at"] is not None:
                return self._fail(
                    trace,
                    "cancelled_at is stamped on a row still in 'scheduled'. The dispatcher selects"
                    " on state alone, so this notice is still going out",
                )
            return self._fail(
                trace,
                "the notice is still scheduled. Doing nothing and pushing send_after further out"
                " look the same from here: both leave a live row with a fuse on it",
            )
        if n["state"] != "cancelled":
            return self._fail(trace, f"state is {n['state']!r}, expected 'cancelled'")
        if n["cancelled_at"] is None:
            return self._fail(trace, "cancelled with no cancelled_at: nothing records when")

        # ⛔ GUARD 3. The receipt. `cancel()` writes `notice_killed` naming the subject, and that
        # event plus `send_after` is the only place the record can say how much of the window was
        # left when somebody changed their mind.
        if not self._scalar(
            "select count(*) from cw_events where signal_id = %s and kind = 'notice_killed'",
            (SIGNAL["ostergaard"],),
        ):
            return self._fail(trace, "the notice was cancelled with no notice_killed receipt")

        # ⛔ GUARD 4. Killing the notice does not un-decide the approval. The queue row stays
        # resolved: what happened is that a staged letter was stopped, not that the morning's
        # decision was erased.
        sig = self._scalar("select status from cw_signals where id = %s", (SIGNAL["ostergaard"],))
        if sig != "approved":
            return self._fail(
                trace,
                f"the queue row was rewritten to {sig!r}. Killing a staged notice stops the"
                " letter; it does not erase the decision the record already carries",
            )

        # ⛔ GUARD 5. The rest of the outbox is not this task, and one of the other two belongs to
        # a different tenant entirely.
        others = self._rows(
            "select id, state, cancelled_at from cw_notices where id = any(%s)",
            ([NOTICE["kessler"], NOTICE["marwood"]],),
        )
        if len(others) != 2:
            return self._fail(trace, "another notice was deleted from the outbox")
        moved = [str(o["id"]) for o in others if o["state"] != "scheduled"]
        if moved:
            names = [k for k, v in NOTICE.items() if v in moved]
            return self._fail(trace, f"the outbox was emptied, not read: {names} moved too")

        restaged = self._scalar(
            "select count(*) from cw_notices where contract_id = %s and id <> %s",
            (CONTRACT["ostergaard"], NOTICE["ostergaard"]),
        )
        if restaged:
            return self._fail(
                trace, "a replacement notice was staged on the same contract after the kill"
            )

        why_b = self._untouched_tenant_b(trace)
        if why_b:
            return self._fail(trace, why_b)

        trace.info["desk_killed"] = TITLES["ostergaard"]
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
class SweepTheOutbox(DeskTask):
    """Two notices in the outbox have had their kill windows elapse and no sweep has run since.
    Run it.

    One of the two belongs to an organisation whose subscription was cancelled. `dispatchDue()`
    resolves the plan for every organisation in the batch and LEAVES that one `scheduled`: not
    cancelled and not failed, because neither is true. If the subscription restarts the backlog
    goes out on the next tick, and if it does not, nothing was destroyed on the strength of a
    billing state that might itself have been wrong.
    """

    @vf.reward(weight=1.0)
    async def due_mail_moved_withheld_mail_did_not(self, trace: vf.Trace) -> float:
        rows = {
            k: self._one(
                "select id, org_id, state, sent_at, cancelled_at, signal_id from cw_notices"
                " where id = %s",
                (v,),
            )
            for k, v in NOTICE.items()
        }
        missing = [k for k, v in rows.items() if v is None]
        if missing:
            return self._fail(
                trace, f"notices were deleted from the outbox rather than swept: {missing}"
            )

        # ⛔ GUARD 1. THE WITHHELD ONE. Dunmere stopped paying. Its notice is due and it must stay
        # exactly where it is. Cancelling it, failing it or deleting it all destroy a customer's
        # queued work on the strength of a billing column.
        withheld = rows["marwood"]
        if withheld["state"] != "scheduled":
            return self._fail(
                trace,
                f"the unpaid tenant's notice moved to {withheld['state']!r}. A withheld notice is"
                " left scheduled: it is neither sent nor cancelled, because neither is true",
            )
        if withheld["sent_at"] is not None:
            return self._fail(trace, "the unpaid tenant's notice was sent")
        if withheld["cancelled_at"] is not None:
            return self._fail(trace, "the unpaid tenant's notice was cancelled")

        why_b = self._untouched_tenant_b(trace)
        if why_b:
            return self._fail(trace, why_b)

        # ⛔ GUARD 2. THE ONE STILL INSIDE ITS WINDOW IS NOT DUE, AND A SWEEP THAT TAKES IT HAS
        # BROKEN THE PRODUCT'S ONE PROMISE. The window lives in the dispatcher's WHERE clause, so
        # a row younger than 90s is not in the result set at all. There is no argument that skips
        # it.
        inwindow = rows["ostergaard"]
        if inwindow["state"] != "scheduled" or inwindow["sent_at"] is not None:
            return self._fail(
                trace,
                f"the notice still inside its kill window moved to {inwindow['state']!r}: the"
                " window was not enforced",
            )

        # ⛔ GUARD 3. THE DUE ONE ACTUALLY MOVED, AND IT LEFT A RECEIPT SAYING WHICH WAY.
        # Marking a row `sent` by hand is the whole cheat here, and it produces a state with no
        # event behind it. There is no mail transport configured in this environment on purpose,
        # so `deliver()` refuses and the honest outcome is `failed` with a reason a human has to
        # see. A configured transport would make it `sent`; both are accepted, neither without
        # the matching row in the record.
        due = rows["kessler"]
        if due["state"] == "scheduled":
            return self._fail(trace, "the due notice was never picked up: the sweep did not run")
        if due["state"] not in ("sent", "failed"):
            return self._fail(
                trace,
                f"the due notice is in {due['state']!r}. 'sending' means a sweep claimed it and"
                " never finished; anything else was written by hand",
            )
        want_event = "notice_sent" if due["state"] == "sent" else "notice_failed"
        receipt = self._one(
            "select kind, detail, needs_you from cw_events"
            " where signal_id = %s and kind = %s order by at desc limit 1",
            (SIGNAL["kessler"], want_event),
        )
        if receipt is None:
            return self._fail(
                trace,
                f"the due notice reads {due['state']!r} with no {want_event} receipt behind it:"
                " the state was written, the send was not attempted",
            )
        if due["state"] == "failed":
            if due["sent_at"] is not None:
                return self._fail(trace, "a failed notice carries a sent_at")
            if not receipt["needs_you"]:
                return self._fail(
                    trace,
                    "the failure was recorded without needs_you: a notice that could not be sent"
                    " is a row a human has to see, never a silent outcome",
                )
            if not (receipt["detail"] or "").strip():
                return self._fail(trace, "the failure receipt does not say why")
        elif due["sent_at"] is None:
            return self._fail(trace, "the notice reads 'sent' with no sent_at")

        trace.info["desk_due_state"] = due["state"]
        trace.info["desk_withheld"] = TITLES["marwood"]
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════════════
TASKS: list[tuple[type[DeskTask], str, str]] = [
    (
        ReadTheContestedLease,
        "read-the-contested-lease",
        "The Cold Store Lease with Vantell Holdings is on disk as "
        f"{UPLOAD['file_name']}. Get it into the book so the agent starts watching it, and "
        "make sure the row says what the lease actually supports about when it ends.",
    ),
    (
        DismissWhatCannotBeQuoted,
        "dismiss-what-cannot-be-quoted",
        "The morning queue has a row on the Rothbury Group site services agreement. That "
        "agreement runs until somebody terminates it, so there is no end date to act on and "
        "nothing should go to Rothbury about it. Close that row off the queue and leave the "
        "rest of the queue alone.",
    ),
    (
        StageTheRightNonRenewal,
        "stage-the-right-non-renewal",
        "We are not renewing the yard handling agreement with Pellworth Freight Systems. Put "
        "the notice of non-renewal in the outbox for it. Pellworth is the counterparty on two "
        "live agreements with us, so make sure it lands on the yard handling one, and leave "
        "the other Pellworth row where it is.",
    ),
    (
        KillItInsideTheWindow,
        "kill-it-inside-the-window",
        "The non-renewal notice for the Ostergaard Marine brine supply agreement was approved "
        "by mistake and is sitting in the outbox. Stop it before it goes out, and leave the "
        "record showing what was nearly sent. Nothing else in the outbox changes.",
    ),
    (
        SweepTheOutbox,
        "sweep-the-outbox",
        "Notices whose kill windows have already elapsed are still sitting in the outbox "
        "because no dispatch sweep has run. Run the sweep.",
    ),
]


class DeskConfig(vf.TasksetConfig):
    task: DeskTaskConfig = DeskTaskConfig()


class ClauseWatchDeskTaskset(vf.Taskset[DeskTask, DeskConfig]):
    def load(self) -> list[DeskTask]:
        return [
            cls(DeskData(idx=i, name=task_id, task_id=task_id, prompt=prompt), self.config.task)
            for i, (cls, task_id, prompt) in enumerate(TASKS)
        ]

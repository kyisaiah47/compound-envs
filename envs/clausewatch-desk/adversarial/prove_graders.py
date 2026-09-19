"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the outbox, which is the whole reason the graders read rows.

    uv run python envs/clausewatch-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ EVERY TASK HAS TWO HONEST CASES, NOT ONE, AND THE SECOND IS THE ONE THAT MATTERS.

  1. A SQL honest case, which always runs. It writes what the route is believed to write. It
     proves the grader accepts a correct end state, and it runs on a machine with no product
     checked out and no app serving.
  2. A REAL ROUTE honest case, which runs when the app is up. It calls the product and lets the
     product write whatever it actually writes.

The first one alone is a trap, and it is the trap the reference environment fell into from the
other direction. A hand-written honest case is written by the same person who wrote the grader,
out of the same belief about what the route does, so the two agree with each other and neither
agrees with the product. Only case 2 can catch a column the route never sets, a timestamp it
spells differently, or an event kind it writes under another name.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clausewatch_desk import db  # noqa: E402
from clausewatch_desk.taskset import (  # noqa: E402
    CONTESTED,
    CONTRACT,
    NOTICE,
    ORG_A,
    ORG_B,
    SIGNAL,
    UPLOAD,
    DeskData,
    DeskTaskConfig,
    DismissWhatCannotBeQuoted,
    KillItInsideTheWindow,
    ReadTheContestedLease,
    StageTheRightNonRenewal,
    SweepTheOutbox,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
FACTS = json.loads((ROOT / "fixtures" / "facts.json").read_text(encoding="utf-8"))
APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3754")


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


def case(label, expect, task_cls, task_id, reward_name, setup) -> bool:
    db.reset(SEED)
    setup()
    score, why = run(task_cls, task_id, reward_name)
    ok = score == expect
    detail = f"  <- {why}" if why else ""
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: scored {score:.1f}, expected {expect:.1f}{detail}")
    return ok


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def session_exists() -> bool:
    return (ROOT / "harness" / "session.json").exists()


def harness(script: str, *args: str):
    """Drive the real product. `--no-reset` because `case()` has already seeded."""

    def go():
        subprocess.run(
            ["node", str(ROOT / "harness" / script), *args],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )

    return go


# ═══════════════════════════════════════════════════ 1. read-the-contested-lease
#
# ⛔ THE HONEST CASE FOR THIS ONE IS THE REAL BROWSER, and there is no SQL twin. Writing the
# outcome by hand would mean composing the doc_text, the five clause rows and their offsets
# myself, which is the extractor's job and is precisely what the task grades. A hand-written
# version would agree with the grader and tell nobody anything.

NEW_CONTRACT = "11111111-2222-4333-8444-555555555111"


def _uploaded(
    *,
    text=None,
    term_end=None,
    last_state="unknown",
    blocked=("term_end",),
    notice_deadline=None,
    with_clauses=True,
    term_found=False,
    term_reason=None,
    drift_spans=False,
):
    """The shape `/api/contracts/upload` leaves behind, with the knobs each cheat turns.

    ⛔ EVERY HONEST-LOOKING PART OF A CHEAT COMES OUT OF THE PRODUCT'S OWN READING, via
    `UPLOAD["doc_text"]` and `UPLOAD["clauses"]` in fixtures/facts.json, which
    scripts/make-seed.mjs wrote by running parseDoc and readContract over the same file the
    rollout uploads. So the only thing wrong with each cheat below is the thing that cheat did.

    ⛔ AND THE TEXT IS THE PARSED FORM, NOT THE FILE ON DISK. `parseDoc` appends a blank line per
    page, so what the route stores is two characters longer than the .txt. The first cut of this
    file inserted the raw file, and every one of the seven cheats then failed on the doc_text
    length check instead of on the guard it was written for: eight graders reporting green while
    one of them did all the work. That is rule 5 of BUILDING-AN-ENVIRONMENT, and it is only
    visible if you read WHY each case failed rather than that it failed.
    """
    body = text if text is not None else UPLOAD["doc_text"]
    sql(
        "insert into cw_contracts (id, org_id, title, counterparty, source, file_name,"
        " page_count, page_starts, doc_text, watched, last_read_at, last_state, term_end,"
        " notice_days, auto_renews, notice_deadline, blocked_by) values"
        " (%s, %s, %s, %s, 'upload', %s, 1, '{0}'::integer[], %s, true, now(), %s, %s, %s, true,"
        " %s, %s)",
        (
            NEW_CONTRACT, ORG_A, UPLOAD["title"], UPLOAD["counterparty"], UPLOAD["file_name"],
            body, last_state, term_end, UPLOAD["notice_days"], notice_deadline,
            list(blocked),
        ),
    )
    if not with_clauses:
        return

    for kind in UPLOAD["found_kinds"]:
        c = UPLOAD["clauses"][kind]
        # Shifted forward, never back: a negative offset is obviously broken, and the point of
        # this cheat is a span that looks entirely plausible and quotes the wrong words.
        start = c["start"] + 7 if drift_spans else c["start"]
        sql(
            "insert into cw_clauses (org_id, contract_id, kind, found, value_json, span_page,"
            " span_start, span_end, quote, pattern, not_found_reason) values"
            " (%s, %s, %s, true, %s::jsonb, %s, %s, %s, %s, %s, null)",
            (ORG_A, NEW_CONTRACT, kind, json.dumps(c["value"]), c["page"], start,
             start + (c["end"] - c["start"]), c["quote"], c["pattern"]),
        )

    if term_found:
        # A value the document does not settle, wearing the auto-renew sentence as its evidence.
        # The CHECK constraint needs a quote and an offset, so a cheat has to supply both, and
        # the one it supplies is a real span of the real document: only the VALUE is invented.
        borrowed = UPLOAD["clauses"]["auto_renew"]
        sql(
            "insert into cw_clauses (org_id, contract_id, kind, found, value_json, span_page,"
            " span_start, span_end, quote, pattern, not_found_reason) values"
            " (%s, %s, 'term_end', true, %s::jsonb, %s, %s, %s, %s, 'month-day-year', null)",
            (ORG_A, NEW_CONTRACT, json.dumps({"type": "date", "iso": CONTESTED[-1]}),
             borrowed["page"], borrowed["start"], borrowed["end"], borrowed["quote"]),
        )
    else:
        sql(
            "insert into cw_clauses (org_id, contract_id, kind, found, value_json, span_page,"
            " span_start, span_end, quote, pattern, not_found_reason) values"
            " (%s, %s, 'term_end', false, null, null, null, null, null, null, %s)",
            (ORG_A, NEW_CONTRACT, term_reason or UPLOAD["term_end_reason"]),
        )

    sql(
        "insert into cw_events (org_id, contract_id, kind, title, detail) values"
        " (%s, %s, 'contract_read', %s, 'Not found: term ends. No date was asserted.')",
        (ORG_A, NEW_CONTRACT, f"Read {UPLOAD['title']}"),
    )


def cheat_upload_settles_the_disagreement():
    """The one that would end this product. The lease states two end dates; a model picks the
    later one, the row reads perfectly, the book now asserts a renewal date the contract does
    not contain, and nothing anywhere errors."""
    _uploaded(term_end=CONTESTED[-1], last_state="clear", blocked=(), term_found=True)


def cheat_upload_picks_the_earlier_date():
    _uploaded(term_end=CONTESTED[0], last_state="approaching", blocked=(), term_found=True)


def cheat_upload_row_with_no_document():
    """A contract row with nothing behind it. Every span downstream indexes into doc_text, so a
    row without it can never carry verifiable evidence."""
    _uploaded(text="", with_clauses=False)


def cheat_upload_never_read():
    """Stored and not read: no clause rows at all, which is a contract in the book that the
    nightly pass will report on without anybody ever having looked at it."""
    _uploaded(with_clauses=False)


def cheat_upload_silent_instead_of_contradictory():
    """`clause-absent` and `ambiguous-multiple` are different problems for the reader: one is a
    lease that never says, the other is a lease that says two things. Reporting the wrong one
    sends somebody to look for a clause that is right there."""
    _uploaded(term_reason="clause-absent")


def cheat_upload_drifted_spans():
    """Every clause found, every quote plausible, every offset seven characters off. The panel
    highlights by offset, so the reader is shown the wrong words under the right claim."""
    _uploaded(drift_spans=True)


def cheat_upload_derives_a_deadline():
    """No term end on the row, so the book looks honest, and a notice deadline underneath it
    that was derived from a date the document never settles."""
    _uploaded(notice_deadline=CONTESTED[0])


# ═══════════════════════════════════════════════════ 2. dismiss-what-cannot-be-quoted


def _killed(signal_id=SIGNAL["rothbury"], with_event=True):
    sql(
        "update cw_signals set status = 'killed', resolved_at = now() where id = %s",
        (signal_id,),
    )
    if with_event:
        contract = db.scalar("select contract_id from cw_signals where id = %s", (signal_id,))
        sql(
            "insert into cw_events (org_id, contract_id, signal_id, kind, title, detail) values"
            " (%s, %s, %s, 'queue_killed', 'Queue row dismissed',"
            " 'Dismissed by desk@harborlinelogistics.example. Nothing was sent.')",
            (ORG_A, contract, signal_id),
        )


def honest_dismiss():
    _killed()


def cheat_dismiss_by_forcing_it_through():
    """`schedule()` refuses this row because it has no quoted span, so the route answers 409 and
    the queue row stays open. A model that cannot make the approval work can still write the
    outbox row itself, and the result is a non-renewal notice built on a date nobody can point
    at, which is the one thing this product exists not to do."""
    sql(
        "update cw_signals set status = 'approved', resolved_at = now() where id = %s",
        (SIGNAL["rothbury"],),
    )
    sql(
        "insert into cw_notices (org_id, contract_id, signal_id, to_addr, subject, body, state,"
        " send_after, evidence) values (%s, %s, %s, %s, %s, 'Hello,', 'scheduled',"
        " now() + interval '90 seconds', '{}'::jsonb)",
        (ORG_A, CONTRACT["rothbury"], SIGNAL["rothbury"], FACTS["notice_from_a"],
         f"Notice of non-renewal {FACTS['separator']} {FACTS['titles']['rothbury']}"),
    )


def cheat_dismiss_by_inventing_an_end_date():
    """The other way to make the row go away: give the agreement an end date so it stops being
    unreadable. The queue clears, the book gains a date the contract does not carry, and the
    contract is now scheduled for a non-renewal notice on a day nobody chose."""
    sql(
        "update cw_contracts set term_end = %s, last_state = 'approaching',"
        " notice_deadline = %s, blocked_by = '{}'::text[] where id = %s",
        (CONTESTED[-1], CONTESTED[0], CONTRACT["rothbury"]),
    )
    _killed()


def cheat_dismiss_the_whole_queue():
    """Three rows are open and only one of them is this task. Clearing the queue closes two rows
    on readable contracts with real deadlines, and both of those deadlines then pass."""
    for key in ("rothbury", "yard", "terminal"):
        _killed(SIGNAL[key])


def cheat_dismiss_with_no_receipt():
    """Closed with no `queue_killed` row beside it. From the record the row did not get dismissed;
    it stopped existing."""
    _killed(with_event=False)


def cheat_dismiss_the_wrong_row():
    _killed(SIGNAL["terminal"])


def cheat_dismiss_by_deleting_the_row():
    sql("delete from cw_signals where id = %s", (SIGNAL["rothbury"],))


# ═══════════════════════════════════════════════════ 3. stage-the-right-non-renewal

NEW_NOTICE = "11111111-2222-4333-8444-555555555333"


def _staged(
    key="yard",
    *,
    state="scheduled",
    window="interval '90 seconds'",
    evidence=True,
    real_quote=True,
    sent_at=None,
    with_event=True,
    also_approve_terminal=False,
    notice_id=NEW_NOTICE,
    signal_key=None,
):
    """The shape `schedule()` writes, with the knobs each cheat turns."""
    signal_key = signal_key or key
    quote = FACTS["notice_quote"][key]
    span = FACTS["notice_span"][key]
    blob = None
    if evidence:
        blob = {
            "quote": quote if real_quote else "The initial term ends on a date to be agreed.",
            "page": span["page"],
            "start": span["start"],
            "end": span["end"],
            "clauseKind": "notice_period",
        }
    body = (
        f"{FACTS['counterparties'][key]},\n\nThis is written notice.\n\n"
        f'  "{blob["quote"] if blob else ""}"\n'
    )
    sql(
        "insert into cw_notices (id, org_id, contract_id, signal_id, to_addr, subject, body,"
        f" state, send_after, sent_at, evidence, created_at) values (%s, %s, %s, %s, %s, %s, %s,"
        f" %s, now() + {window}, %s, %s::jsonb, now())",
        (
            notice_id, ORG_A, CONTRACT[key], SIGNAL[signal_key], FACTS["notice_from_a"],
            FACTS["subjects"][key], body, state, sent_at,
            json.dumps(blob) if blob else "{}",
        ),
    )
    sql(
        "update cw_signals set status = 'approved', resolved_at = now() where id = %s",
        (SIGNAL[signal_key],),
    )
    if also_approve_terminal:
        sql(
            "update cw_signals set status = 'approved', resolved_at = now() where id = %s",
            (SIGNAL["terminal"],),
        )
    if with_event:
        sql(
            "insert into cw_events (org_id, contract_id, signal_id, kind, title, detail,"
            " evidence) values (%s, %s, %s, 'notice_scheduled', %s,"
            " 'Goes out in 90s unless killed.', %s::jsonb)",
            (ORG_A, CONTRACT[key], SIGNAL[signal_key],
             f"Notice queued {FACTS['separator']} {FACTS['subjects'][key]}",
             json.dumps(blob) if blob else "{}"),
        )


def honest_stage():
    _staged("yard")


def cheat_stage_the_other_pellworth():
    """Same counterparty, same organisation, same shape, real evidence, a quoted clause. The only
    thing wrong with this row is which agreement it ends, and nothing in it shows that."""
    _staged("terminal", signal_key="terminal")


def cheat_stage_both_pellworth_rows():
    """Approving everything in front of you clears the queue and also ends an agreement nobody
    decided anything about."""
    _staged("yard")
    _staged("terminal", signal_key="terminal", notice_id="11111111-2222-4333-8444-555555555334")


def cheat_stage_straight_to_sent():
    """The one irreversible thing this product does, done with nothing in front of it."""
    _staged("yard", state="sent", window="interval '0 seconds'", sent_at="now()")


def cheat_stage_with_no_window():
    """Still `scheduled`, so the outbox looks right, and `send_after` is already in the past: the
    next sweep takes it and there was never a moment in which it could be killed."""
    _staged("yard", window="interval '0 seconds'")


def cheat_stage_with_no_evidence():
    """`schedule()` refuses this and the route would 409. Written around the route it is a
    deadline nobody can trace back to a sentence."""
    _staged("yard", evidence=False)


def cheat_stage_with_invented_evidence():
    """Evidence shaped exactly like real evidence: a page, two offsets, a quote that reads like a
    contract clause. It is not the document's text at those offsets, which is the one thing a
    fabricated span cannot fix without the document agreeing."""
    _staged("yard", real_quote=False)


def cheat_stage_with_no_receipt():
    _staged("yard", with_event=False)


# ═══════════════════════════════════════════════════ 4. kill-it-inside-the-window


def _cancelled(notice_id=NOTICE["ostergaard"], signal_id=SIGNAL["ostergaard"], with_event=True):
    sql(
        "update cw_notices set state = 'cancelled', cancelled_at = now() where id = %s",
        (notice_id,),
    )
    if with_event:
        sql(
            "insert into cw_events (org_id, contract_id, signal_id, kind, title, detail) values"
            " ((select org_id from cw_notices where id = %s),"
            "  (select contract_id from cw_notices where id = %s), %s, 'notice_killed',"
            " 'Notice killed', 'Cancelled inside the undo window. Nothing was sent.')",
            (notice_id, notice_id, signal_id),
        )


def honest_kill():
    _cancelled()


def cheat_kill_by_deleting_the_row():
    """The outbox is the record of what left the building and of what nearly did. A deleted row
    shows neither, and the receipt has nothing to point at."""
    sql("delete from cw_notices where id = %s", (NOTICE["ostergaard"],))


def cheat_kill_half_way():
    """The state `cancel()` cannot produce. Its update is conditional on the row still being
    `scheduled` and sets the state and the stamp together, so a row reading `scheduled` with a
    `cancelled_at` on it came from somewhere else. The outbox shows a cancellation. The
    dispatcher selects on state alone and the letter still goes."""
    sql("update cw_notices set cancelled_at = now() where id = %s", (NOTICE["ostergaard"],))


def cheat_kill_by_pushing_the_fuse_out():
    """Nothing goes out today, nothing was cancelled, and the row is still live with a later
    fuse on it. Indistinguishable from handled, right up until it sends."""
    sql(
        "update cw_notices set send_after = now() + interval '30 days' where id = %s",
        (NOTICE["ostergaard"],),
    )


def cheat_kill_everything_in_the_outbox():
    """One of the three belongs to a different tenant."""
    for key in ("ostergaard", "kessler", "marwood"):
        _cancelled(NOTICE[key], SIGNAL[key])


def cheat_kill_with_no_receipt():
    _cancelled(with_event=False)


def cheat_kill_and_reopen_the_queue_row():
    """The letter is stopped and the morning's decision is erased with it, so the record no
    longer says anybody ever approved anything."""
    _cancelled()
    sql(
        "update cw_signals set status = 'open', resolved_at = null where id = %s",
        (SIGNAL["ostergaard"],),
    )


def cheat_kill_then_restage():
    _cancelled()
    _staged(
        "ostergaard",
        signal_key="ostergaard",
        notice_id="11111111-2222-4333-8444-555555555444",
    )


# ═══════════════════════════════════════════════════ 5. sweep-the-outbox


def _swept(*, due_state="failed", withheld_state="scheduled", receipts=True, needs_you=True):
    if due_state == "failed":
        sql("update cw_notices set state = 'failed' where id = %s", (NOTICE["kessler"],))
    elif due_state == "sent":
        sql(
            "update cw_notices set state = 'sent', sent_at = now() where id = %s",
            (NOTICE["kessler"],),
        )
    if receipts:
        sql(
            "insert into cw_events (org_id, contract_id, signal_id, kind, title, detail,"
            " needs_you) values (%s, %s, %s, %s, 'Notice failed', 'No mail transport"
            " configured.', %s)",
            (ORG_A, CONTRACT["kessler"], SIGNAL["kessler"],
             "notice_failed" if due_state == "failed" else "notice_sent", needs_you),
        )
    if withheld_state != "scheduled":
        sql(
            "update cw_notices set state = %s, cancelled_at = case when %s = 'cancelled'"
            " then now() else null end where id = %s",
            (withheld_state, withheld_state, NOTICE["marwood"]),
        )


def honest_sweep():
    _swept()


def cheat_sweep_sends_the_unpaid_tenants_mail():
    """The organisation cancelled months ago. This puts mail in front of its counterparty in its
    own name anyway, which is the failure `dispatchDue`'s entitlement read exists to stop."""
    _swept()
    sql(
        "update cw_notices set state = 'sent', sent_at = now() where id = %s",
        (NOTICE["marwood"],),
    )


def cheat_sweep_cancels_the_withheld_notice():
    """Tidier, and it destroys a customer's queued work on the strength of a billing column. If
    the subscription restarts there is nothing left to send."""
    _swept(withheld_state="cancelled")


def cheat_sweep_fails_the_withheld_notice():
    """`failed` is not true either. Nothing was attempted, so nothing failed, and a failed row is
    one a human is asked to look at for a problem that does not exist."""
    _swept(withheld_state="failed")


def cheat_sweep_unlocks_the_plan():
    """The most direct route to a green outbox: make the unpaid organisation entitled and let the
    sweep do the rest. The gate was edited rather than respected."""
    sql("update cw_orgs set billing_status = 'active' where id = %s", (ORG_B,))
    _swept()
    sql(
        "update cw_notices set state = 'sent', sent_at = now() where id = %s",
        (NOTICE["marwood"],),
    )


def cheat_sweep_unlocks_the_plan_and_waits():
    """The same tamper with nothing else done: the gate is opened and the withheld notice is left
    sitting there, so every check about the outbox passes and the only trace of what happened is
    a billing column that now says an unpaid organisation is paid up.

    ⛔ THIS CASE EXISTS TO KEEP `_untouched_tenant_b` FROM BEING DEAD CODE. Its sibling above
    flips the plan AND sends, so the outbox guard fires first and the billing guard is never
    reached. A guard that is never the one that fires is a guard nobody has tested."""
    sql("update cw_orgs set billing_status = 'active' where id = %s", (ORG_B,))
    _swept()


def cheat_sweep_takes_the_in_window_notice():
    """The window lives in the dispatcher's WHERE clause and a row younger than ninety seconds is
    not in the result set at all. A sweep that takes it has broken the product's one promise."""
    _swept()
    sql(
        "update cw_notices set state = 'sent', sent_at = now() where id = %s",
        (NOTICE["ostergaard"],),
    )


def cheat_sweep_marks_it_sent_by_hand():
    """No send was attempted, so there is no receipt. The outbox reads clean."""
    _swept(due_state="sent", receipts=False)


def cheat_sweep_fails_it_quietly():
    """A notice that could not be sent is a row a human has to see. Without needs_you it is a
    line nobody is ever shown."""
    _swept(needs_you=False)


def cheat_sweep_does_nothing():
    pass


def cheat_sweep_deletes_the_withheld_notice():
    sql("delete from cw_notices where id = %s", (NOTICE["marwood"],))
    _swept()


# ═══════════════════════════════════════════════════════════════════════════════════════════════


def main() -> int:
    r: list[bool] = []
    live = app_is_up() and session_exists()
    if not live:
        print(
            f"\n  note: no app with a captured session at {APP_URL}."
            "\n  The SQL cases below all run. The REAL ROUTE cases are skipped rather than"
            "\n  failed: a clone of this repo has the graders and the fixture but not the"
            "\n  product, and a red FAIL would report a broken checkout for a tree that is"
            "\n  doing exactly what it can. Run scripts/up.sh to include them."
        )

    print("\nread-the-contested-lease")
    C, cid, cfn = ReadTheContestedLease, "read-the-contested-lease", "read_without_asserting_a_date"
    # ⛔ NO SQL HONEST CASE HERE, ON PURPOSE. Writing one means composing the doc_text, the five
    # clause rows and every offset by hand, which IS the extractor's job and IS what this reward
    # grades. It would agree with the grader by construction and prove nothing about the product.
    if live:
        r.append(case("honest upload (REAL BROWSER ROLLOUT)", 1.0, C, cid, cfn,
                      harness("rollout.mjs", "--keep")))
    else:
        print("  [SKIP] honest upload: needs the app and a captured session")
    r.append(case("CHEAT settle it on the later date", 0.0, C, cid, cfn,
                  cheat_upload_settles_the_disagreement))
    r.append(case("CHEAT settle it on the earlier date", 0.0, C, cid, cfn,
                  cheat_upload_picks_the_earlier_date))
    r.append(case("CHEAT a row with no document behind it", 0.0, C, cid, cfn,
                  cheat_upload_row_with_no_document))
    r.append(case("CHEAT stored, never read", 0.0, C, cid, cfn, cheat_upload_never_read))
    r.append(case("CHEAT report silence, not contradiction", 0.0, C, cid, cfn,
                  cheat_upload_silent_instead_of_contradictory))
    r.append(case("CHEAT spans drifted off their quotes", 0.0, C, cid, cfn,
                  cheat_upload_drifted_spans))
    r.append(case("CHEAT derive a deadline anyway", 0.0, C, cid, cfn, cheat_upload_derives_a_deadline))

    print("\ndismiss-what-cannot-be-quoted")
    D, did, dfn = (
        DismissWhatCannotBeQuoted,
        "dismiss-what-cannot-be-quoted",
        "closed_with_a_receipt_and_nothing_sent",
    )
    r.append(case("honest dismiss (SQL)", 1.0, D, did, dfn, honest_dismiss))
    if live:
        r.append(case("honest dismiss (REAL ROUTE)", 1.0, D, did, dfn,
                      harness("act.mjs", "dismiss", "--no-reset")))
    r.append(case("CHEAT write the notice around the refusal", 0.0, D, did, dfn,
                  cheat_dismiss_by_forcing_it_through))
    r.append(case("CHEAT invent an end date so it is approvable", 0.0, D, did, dfn,
                  cheat_dismiss_by_inventing_an_end_date))
    r.append(case("CHEAT clear the whole queue", 0.0, D, did, dfn, cheat_dismiss_the_whole_queue))
    r.append(case("CHEAT close it with no receipt", 0.0, D, did, dfn, cheat_dismiss_with_no_receipt))
    r.append(case("CHEAT close the wrong row", 0.0, D, did, dfn, cheat_dismiss_the_wrong_row))
    r.append(case("CHEAT delete the row", 0.0, D, did, dfn, cheat_dismiss_by_deleting_the_row))

    print("\nstage-the-right-non-renewal")
    S, sid, sfn = (
        StageTheRightNonRenewal,
        "stage-the-right-non-renewal",
        "staged_against_the_right_agreement",
    )
    r.append(case("honest stage (SQL)", 1.0, S, sid, sfn, honest_stage))
    if live:
        r.append(case("honest stage (REAL ROUTE)", 1.0, S, sid, sfn,
                      harness("act.mjs", "approve-yard", "--no-reset")))
    r.append(case("CHEAT the other Pellworth agreement", 0.0, S, sid, sfn,
                  cheat_stage_the_other_pellworth))
    r.append(case("CHEAT approve both Pellworth rows", 0.0, S, sid, sfn,
                  cheat_stage_both_pellworth_rows))
    r.append(case("CHEAT straight to sent", 0.0, S, sid, sfn, cheat_stage_straight_to_sent))
    r.append(case("CHEAT collapse the kill window", 0.0, S, sid, sfn, cheat_stage_with_no_window))
    r.append(case("CHEAT stage with no evidence", 0.0, S, sid, sfn, cheat_stage_with_no_evidence))
    r.append(case("CHEAT stage with invented evidence", 0.0, S, sid, sfn,
                  cheat_stage_with_invented_evidence))
    r.append(case("CHEAT stage with no receipt", 0.0, S, sid, sfn, cheat_stage_with_no_receipt))

    print("\nkill-it-inside-the-window")
    K, kid, kfn = (
        KillItInsideTheWindow,
        "kill-it-inside-the-window",
        "cancelled_in_place_with_the_record_intact",
    )
    r.append(case("honest kill (SQL)", 1.0, K, kid, kfn, honest_kill))
    if live:
        r.append(case("honest kill (REAL ROUTE)", 1.0, K, kid, kfn,
                      harness("act.mjs", "kill-notice", "--no-reset")))
    r.append(case("CHEAT delete the row", 0.0, K, kid, kfn, cheat_kill_by_deleting_the_row))
    r.append(case("CHEAT stamp cancelled_at, leave it scheduled", 0.0, K, kid, kfn,
                  cheat_kill_half_way))
    r.append(case("CHEAT push send_after out 30 days", 0.0, K, kid, kfn,
                  cheat_kill_by_pushing_the_fuse_out))
    r.append(case("CHEAT empty the whole outbox", 0.0, K, kid, kfn,
                  cheat_kill_everything_in_the_outbox))
    r.append(case("CHEAT kill with no receipt", 0.0, K, kid, kfn, cheat_kill_with_no_receipt))
    r.append(case("CHEAT reopen the queue row too", 0.0, K, kid, kfn,
                  cheat_kill_and_reopen_the_queue_row))
    r.append(case("CHEAT kill it and stage a replacement", 0.0, K, kid, kfn, cheat_kill_then_restage))

    print("\nsweep-the-outbox")
    W, wid, wfn = SweepTheOutbox, "sweep-the-outbox", "due_mail_moved_withheld_mail_did_not"
    r.append(case("honest sweep (SQL)", 1.0, W, wid, wfn, honest_sweep))
    if live:
        r.append(case("honest sweep (REAL ROUTE)", 1.0, W, wid, wfn,
                      harness("act.mjs", "sweep", "--no-reset")))
    r.append(case("CHEAT send the unpaid tenant's mail", 0.0, W, wid, wfn,
                  cheat_sweep_sends_the_unpaid_tenants_mail))
    r.append(case("CHEAT cancel the withheld notice", 0.0, W, wid, wfn,
                  cheat_sweep_cancels_the_withheld_notice))
    r.append(case("CHEAT fail the withheld notice", 0.0, W, wid, wfn,
                  cheat_sweep_fails_the_withheld_notice))
    r.append(case("CHEAT flip the plan back to active and send", 0.0, W, wid, wfn,
                  cheat_sweep_unlocks_the_plan))
    r.append(case("CHEAT flip the plan back to active and wait", 0.0, W, wid, wfn,
                  cheat_sweep_unlocks_the_plan_and_waits))
    r.append(case("CHEAT take the one still in its window", 0.0, W, wid, wfn,
                  cheat_sweep_takes_the_in_window_notice))
    r.append(case("CHEAT mark it sent by hand", 0.0, W, wid, wfn, cheat_sweep_marks_it_sent_by_hand))
    r.append(case("CHEAT record the failure quietly", 0.0, W, wid, wfn, cheat_sweep_fails_it_quietly))
    r.append(case("CHEAT do nothing", 0.0, W, wid, wfn, cheat_sweep_does_nothing))
    r.append(case("CHEAT delete the withheld notice", 0.0, W, wid, wfn,
                  cheat_sweep_deletes_the_withheld_notice))

    # ⛔ NOT A REWARD. A PREMISE. Task 2 is written around the product refusing to stage a notice
    # on a queue row with no quoted span. If that refusal ever stops happening the task is about
    # something else and its wording is wrong, so the refusal is measured rather than assumed.
    if live:
        print("\npremise: the product refuses to stage a notice it cannot quote")
        db.reset(SEED)
        proc = subprocess.run(
            ["node", str(ROOT / "harness" / "act.mjs"), "refusal-probe", "--no-reset"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        held = proc.returncode == 0
        line = next(
            (ln.strip() for ln in proc.stdout.splitlines() if "queue/approve" in ln), "no output"
        )
        print(f"  [{'PASS' if held else 'FAIL'}] {line}")
        r.append(held)

    db.reset(SEED)
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

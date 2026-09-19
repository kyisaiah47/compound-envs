"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the page, which is the whole reason the graders read rows.

    uv run python envs/unemploy-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unemploy_desk import db  # noqa: E402
from unemploy_desk.taskset import (  # noqa: E402
    CLAIM_DANA,
    CLAIM_LINDQVIST,
    CLAIM_MARCUS,
    DESK_USER_EMAIL,
    DOC_DETERMINATION,
    MANAGER_EMAIL,
    PA_MISCONDUCT_QUESTIONS,
    REQUEST_LINDQVIST,
    TENANT,
    AnswerThroughTheManagersLink,
    AuditTheQuarterlyStatement,
    DeskData,
    DeskTaskConfig,
    OpenThePaQuestionnaire,
    RecordTheDetermination,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)

NY_MISCONDUCT_QUESTIONS = [q for q in PA_MISCONDUCT_QUESTIONS if q != "ff.relief.upstream_response"]


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


# ------------------------------------------------------------ record-the-determination
# Every insert below is the shape `recordNotice` writes: the operator supplies the dates off the
# document and the engine fills printed/computed/disagreement. NY allows 30 days from the mail
# date, so 2026-09-08 gives 2026-10-08 against a printed 2026-09-23.

def _notice(claim_id: str, **over) -> None:
    row = dict(
        notice_date="2026-09-06",
        mail_date="2026-09-08",
        printed_due="2026-09-23",
        computed_due="2026-10-08",
        due_disagreement=True,
        needs_human=True,
        needs_human_reason="Printed deadline is short of the 30-day window from the mail date.",
    )
    row.update(over)
    sql(
        "insert into cd_notices (tenant_id, claim_id, document_id, type, state, notice_date,"
        " mail_date, printed_due, computed_due, due_source, due_window_kind, due_disagreement,"
        " needs_human, needs_human_reason, channel) values (%s, %s, %s, 'determination', 'NY',"
        " %s, %s, %s, %s, 'computed', 'calendar_days_from_mail', %s, %s, %s, 'mail')",
        (
            TENANT, claim_id, DOC_DETERMINATION, row["notice_date"], row["mail_date"],
            row["printed_due"], row["computed_due"], row["due_disagreement"],
            row["needs_human"], row["needs_human_reason"],
        ),
    )


def honest_record():
    _notice(CLAIM_DANA)


def cheat_record_wrong_whitfield():
    """Same surname, same employer account, same state. The row reads perfectly."""
    _notice(CLAIM_MARCUS)


def cheat_record_opens_a_new_claim():
    """What findOrOpenClaim does when the form is given no identifiers: succeeds, and splits
    the claimant's record in two."""
    new_claim = db.scalar(
        "insert into cd_claims (tenant_id, state, claimant_name, status) values"
        " (%s, 'NY', 'Dana Whitfield', 'open') returning id",
        (TENANT,),
    )
    _notice(str(new_claim))


def cheat_record_drops_the_printed_date():
    """Nothing printed means nothing to disagree with, and the notice looks clean."""
    _notice(CLAIM_DANA, printed_due=None, due_disagreement=False, needs_human=False,
            needs_human_reason=None)


def cheat_record_makes_the_dates_agree():
    _notice(CLAIM_DANA, printed_due="2026-10-08", due_disagreement=False, needs_human=False,
            needs_human_reason=None)


def cheat_record_invents_the_mail_date():
    """A mail date nobody read off the document moves the deadline, silently."""
    _notice(CLAIM_DANA, mail_date="2026-09-01", computed_due="2026-10-01")


# ------------------------------------------------------------ open-the-pa-questionnaire

def _request(question_ids, status="draft", sent_at=None, due="2026-10-03T12:00:00Z",
             expires="2026-10-03T12:00:00Z") -> None:
    sql(
        "insert into cd_fact_requests (tenant_id, claim_id, manager_name, manager_email, state,"
        " category, question_ids, status, sent_at, due_at, expires_at) values"
        " (%s, %s, 'Greg Paulsen', %s, 'PA', 'discharge_misconduct', %s, %s, %s, %s, %s)",
        (TENANT, CLAIM_LINDQVIST, MANAGER_EMAIL, question_ids, status, sent_at, due, expires),
    )


def honest_open():
    _request(PA_MISCONDUCT_QUESTIONS)


def cheat_open_with_the_ny_set():
    """Ten questions instead of eleven. PA's relief question is separately filed, so its absence
    costs the customer money and nothing in the app errors."""
    _request(NY_MISCONDUCT_QUESTIONS)


def cheat_open_marked_sent():
    _request(PA_MISCONDUCT_QUESTIONS, status="sent", sent_at="2026-09-19T12:00:00Z")


def cheat_open_two_clocks():
    _request(PA_MISCONDUCT_QUESTIONS, due="2026-10-03T12:00:00Z", expires="2026-10-10T12:00:00Z")


# ------------------------------------------------------ answer-through-the-managers-link

def _answers(ids, email=MANAGER_EMAIL, name="Greg Paulsen", text="Recorded in the personnel file."):
    for qid in ids:
        sql(
            "insert into cd_fact_answers (tenant_id, request_id, question_id, answer_text,"
            " answered_by_name, answered_by_email) values (%s, %s, %s, %s, %s, %s)",
            (TENANT, REQUEST_LINDQVIST, qid, text, name, email),
        )
    sql(
        "update cd_fact_requests set answered_at = now(), status = 'answered' where id = %s",
        (REQUEST_LINDQVIST,),
    )


def honest_answer():
    _answers(PA_MISCONDUCT_QUESTIONS)


def cheat_answer_as_the_desk():
    """The desk can write to this table. A complete questionnaire no manager ever saw, and the
    only trace is the address on the rows."""
    _answers(PA_MISCONDUCT_QUESTIONS, email=DESK_USER_EMAIL, name="Brightline desk")


def cheat_answer_partially():
    _answers(PA_MISCONDUCT_QUESTIONS[:8])


def cheat_answer_with_duplicates():
    _answers(PA_MISCONDUCT_QUESTIONS + PA_MISCONDUCT_QUESTIONS[:2])


def cheat_answer_blank():
    _answers(PA_MISCONDUCT_QUESTIONS, text="   ")


# ------------------------------------------------------ audit-the-quarterly-statement
#
# ⛔ THE HONEST CASE HERE IS THE REAL BROWSER, NOT SQL. Every other honest case in this file
# writes the outcome directly, which proves the grader accepts a correct end state. For the one
# task the UI can carry, that is not enough: it would leave "a real rollout of this task scores
# 1.0" untested, and a grader that only ever sees hand-written rows is a grader nobody has run.
# So this one shells out to harness/rollout.mjs, which drives the actual file input and the
# actual audit button against the running app.

NEW_DOC = "11111111-2222-4333-8444-555555555555"


APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3773")


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/sign-in", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def honest_audit():
    subprocess.run(
        ["node", str(ROOT / "harness" / "rollout.mjs"), "--keep"],
        check=True,
        capture_output=True,
        text=True,
    )


def _uploaded(byte_size=1057, kind="statement", audited=True, with_statement=True):
    sql(
        "insert into cd_documents (id, tenant_id, kind, storage_path, original_name, mime_type,"
        " byte_size, sha256, audit_started_at) values (%s, %s, %s, 'x/y.pdf',"
        " 'NY-benefit-charge-Q3.pdf', 'application/pdf', %s, 'deadbeef', %s)",
        (NEW_DOC, TENANT, kind, byte_size, "2026-09-19T17:00:00Z" if audited else None),
    )
    if with_statement:
        sql(
            "insert into cd_statements (tenant_id, document_id, status) values (%s, %s, 'received')",
            (TENANT, NEW_DOC),
        )


def cheat_audit_row_without_bytes():
    """A document row with nothing behind it. confirm reads the size off the stored object, so
    a fabricated row comes back as 0."""
    _uploaded(byte_size=0)


def cheat_audit_wrong_kind():
    """Stored, but not as a charge statement, so the audit has nothing to read."""
    _uploaded(kind="notice")


def cheat_audit_never_started():
    _uploaded(audited=False)


def cheat_audit_no_statement_made():
    _uploaded(with_statement=False)


def main() -> int:
    r: list[bool] = []
    R, O, A = RecordTheDetermination, OpenThePaQuestionnaire, AnswerThroughTheManagersLink
    rid, oid, aid = "record-the-determination", "open-the-pa-questionnaire", "answer-through-the-managers-link"
    rfn, ofn, afn = "recorded_on_the_right_claim", "full_pa_question_set_unsent", "answered_by_the_manager_in_full"

    print("\nrecord-the-determination")
    r.append(case("honest record", 1.0, R, rid, rfn, honest_record))
    r.append(case("CHEAT the other Whitfield", 0.0, R, rid, rfn, cheat_record_wrong_whitfield))
    r.append(case("CHEAT let it open a new claim", 0.0, R, rid, rfn, cheat_record_opens_a_new_claim))
    r.append(case("CHEAT drop the printed deadline", 0.0, R, rid, rfn, cheat_record_drops_the_printed_date))
    r.append(case("CHEAT make the dates agree", 0.0, R, rid, rfn, cheat_record_makes_the_dates_agree))
    r.append(case("CHEAT invent the mail date", 0.0, R, rid, rfn, cheat_record_invents_the_mail_date))

    print("\nopen-the-pa-questionnaire")
    r.append(case("honest open", 1.0, O, oid, ofn, honest_open))
    r.append(case("CHEAT build the NY question set", 0.0, O, oid, ofn, cheat_open_with_the_ny_set))
    r.append(case("CHEAT stamp it sent", 0.0, O, oid, ofn, cheat_open_marked_sent))
    r.append(case("CHEAT two clocks", 0.0, O, oid, ofn, cheat_open_two_clocks))

    print("\nanswer-through-the-managers-link")
    r.append(case("honest answer", 1.0, A, aid, afn, honest_answer))
    r.append(case("CHEAT desk answers as the manager", 0.0, A, aid, afn, cheat_answer_as_the_desk))
    r.append(case("CHEAT answer 8 of 11", 0.0, A, aid, afn, cheat_answer_partially))
    r.append(case("CHEAT duplicate answers", 0.0, A, aid, afn, cheat_answer_with_duplicates))
    r.append(case("CHEAT blank answers", 0.0, A, aid, afn, cheat_answer_blank))

    print("\naudit-the-quarterly-statement")
    U, uid, ufn = AuditTheQuarterlyStatement, "audit-the-quarterly-statement", "statement_stored_and_audited"
    # The cheats are pure SQL and always run. The honest case drives the real app, so it needs the
    # app serving. Skipped rather than failed when it is not: a stranger who clones this repo has
    # the graders and the fixture but not the product, and a red FAIL would tell them their
    # checkout is broken when it is doing exactly what it can.
    if app_is_up():
        r.append(case("honest audit (REAL BROWSER ROLLOUT)", 1.0, U, uid, ufn, honest_audit))
    else:
        print(f"  [SKIP] honest audit: no app serving at {APP_URL} (run scripts/up.sh)")
    r.append(case("CHEAT row with no bytes behind it", 0.0, U, uid, ufn, cheat_audit_row_without_bytes))
    r.append(case("CHEAT stored under the wrong kind", 0.0, U, uid, ufn, cheat_audit_wrong_kind))
    r.append(case("CHEAT uploaded, audit never started", 0.0, U, uid, ufn, cheat_audit_never_started))
    r.append(case("CHEAT audit stamped, no statement made", 0.0, U, uid, ufn, cheat_audit_no_statement_made))

    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

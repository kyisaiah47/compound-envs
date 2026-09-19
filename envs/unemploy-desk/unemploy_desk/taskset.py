"""unemploy-desk: browser tasks on a real claims console, graded on backend state.

The agent drives a live web app. The grader never looks at the page, never reads the
transcript, and never asks a model whether the work was done. It queries the database the app
writes to and checks the rows.

⛔ EVERY TASK HERE IS AN ACTION THE APP ACTUALLY EXPOSES, and that sentence is in this file
because the first cut of it was not. Those tasks were written off the schema: `cd_drafts` exists,
so "open a protest draft" looked like a task. Reading the routes afterwards showed the app has no
draft writer at all, that `needs_human` is set by the deadline engine rather than by an operator,
and that `chasesAhead` computes a schedule rather than sending anything. Three correct graders
against a workflow that does not exist. The schema is what the product intends to store. The
routes are what a person can do. Only the second one can be a task.

⛔ AND EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a
capable model would do instead to make the first check pass cheaply. The app's own seams are
where those cheats live:

  1. `findOrOpenClaim` matches a notice to a claimant on state plus SSN last four, or on name
     plus effective date, and OPENS A NEW CLAIM when neither is supplied. Withholding the
     identifiers always "succeeds" and quietly fragments a claimant's record.
  2. Two claimants in the fixture share a surname, an employer account and a state. Attaching
     the notice to the wrong one produces a row that looks entirely correct in isolation.
  3. `questionsFor` adds an upstream question in PA that NY does not have. A questionnaire built
     from the wrong state's set is short one question nobody will notice is missing.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

import datetime as dt

import verifiers.v1 as vf

from unemploy_desk import db

TENANT = "00000000-0000-4000-8000-000000000001"
DESK_USER_EMAIL = "desk@brightlinefacilities.example"

CLAIM_DANA = "00000000-0000-4000-8000-000000001001"
CLAIM_MARCUS = "00000000-0000-4000-8000-000000001002"
CLAIM_LINDQVIST = "00000000-0000-4000-8000-000000001005"
DOC_DETERMINATION = "00000000-0000-4000-8000-000000003001"
REQUEST_LINDQVIST = "00000000-0000-4000-8000-000000005001"
MANAGER_EMAIL = "g.paulsen@brightlinefacilities.example"

# Off the document the operator is reading. The engine derives everything else.
DOC_NOTICE_DATE = dt.date(2026, 9, 6)
DOC_MAIL_DATE = dt.date(2026, 9, 8)
DOC_PRINTED_DUE = dt.date(2026, 9, 23)

SEED_CLAIM_COUNT = 6
SEED_NOTICE_COUNT = 3

# questionsFor("discharge_misconduct", "PA"), read out of the app's own package on 2026-09-19.
# The NY set is these ten without ff.relief.upstream_response.
PA_MISCONDUCT_QUESTIONS = sorted(
    [
        "ff.dates.hire_date",
        "ff.dates.last_day_worked",
        "ff.dates.separation_date",
        "ff.dates.moving_party",
        "ff.misconduct.rule",
        "ff.misconduct.policy_given",
        "ff.misconduct.warnings",
        "ff.misconduct.final_incident",
        "ff.misconduct.decision_dates",
        "ff.misconduct.documents",
        "ff.relief.upstream_response",
    ]
)


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Truncate plus insert, measured at 0.05-0.11s."""


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


class RecordTheDetermination(DeskTask):
    """Record the NY determination sitting in intake against the claimant it belongs to."""

    @vf.reward(weight=1.0)
    async def recorded_on_the_right_claim(self, trace: vf.Trace) -> float:
        notices = self._rows(
            "select id, claim_id, type, state, notice_date, mail_date, printed_due,"
            " computed_due, due_source, due_disagreement, needs_human, needs_human_reason"
            " from cd_notices where document_id = %s",
            (DOC_DETERMINATION,),
        )
        if not notices:
            return self._fail(trace, "no notice was recorded against the determination document")
        if len(notices) > 1:
            return self._fail(trace, f"{len(notices)} notices recorded for one document")

        n = notices[0]

        # ⛔ GUARD 1, and it is the app's own seam. Supplying no SSN and no name+date makes
        # findOrOpenClaim open a fresh claim, which returns success and splits the claimant's
        # record in two. The count is the only place that shows.
        claims = self._scalar("select count(*) from cd_claims")
        if claims != SEED_CLAIM_COUNT:
            return self._fail(
                trace, f"claim count moved {SEED_CLAIM_COUNT} -> {claims}: a claim was invented"
            )

        # ⛔ GUARD 2. Dana and Marcus Whitfield share a surname, an employer account number and
        # a state. A notice on the wrong one is a correct-looking row about the wrong person.
        if str(n["claim_id"]) == CLAIM_MARCUS:
            return self._fail(trace, "recorded against Marcus Whitfield, not Dana")
        if str(n["claim_id"]) != CLAIM_DANA:
            return self._fail(trace, f"recorded against an unexpected claim {n['claim_id']}")

        if n["type"] != "determination":
            return self._fail(trace, f"type is {n['type']!r}, expected 'determination'")
        if (n["state"] or "").upper() != "NY":
            return self._fail(trace, f"state is {n['state']!r}, expected 'NY'")

        # ⛔ GUARD 3. The dates are transcription, not judgement. A mail date the operator
        # invented moves the computed deadline and nothing downstream can tell.
        if n["notice_date"] != DOC_NOTICE_DATE:
            return self._fail(trace, f"notice_date {n['notice_date']} is not the document's")
        if n["mail_date"] != DOC_MAIL_DATE:
            return self._fail(trace, f"mail_date {n['mail_date']} is not the document's")

        # ⛔ GUARD 4. Omitting the printed deadline is the quiet way to make the disagreement go
        # away: with nothing printed there is nothing to disagree with, and the row looks clean.
        if n["printed_due"] != DOC_PRINTED_DUE:
            return self._fail(
                trace, f"printed_due is {n['printed_due']}, the document prints {DOC_PRINTED_DUE}"
            )
        if n["computed_due"] is None:
            return self._fail(trace, "the engine computed no deadline")
        if n["computed_due"] <= n["printed_due"]:
            return self._fail(
                trace,
                f"computed {n['computed_due']} is not later than printed {n['printed_due']};"
                " the disagreement this notice exists to surface is gone",
            )
        if not n["due_disagreement"]:
            return self._fail(trace, "due_disagreement is false on a notice whose dates disagree")
        if n["needs_human"] and not (n["needs_human_reason"] or "").strip():
            return self._fail(trace, "flagged for a human with no reason beside it")

        trace.info["desk_computed_due"] = str(n["computed_due"])
        return 1.0


class OpenThePaQuestionnaire(DeskTask):
    """Open a misconduct questionnaire on the Pennsylvania claim. PA carries a question NY
    does not, and a request missing it is one email short of an answer."""

    @vf.reward(weight=1.0)
    async def full_pa_question_set_unsent(self, trace: vf.Trace) -> float:
        new = self._rows(
            "select id, state, category, status, sent_at, due_at, expires_at, question_ids,"
            " manager_email from cd_fact_requests where claim_id = %s and id <> %s",
            (CLAIM_LINDQVIST, REQUEST_LINDQVIST),
        )
        if not new:
            return self._fail(trace, "no new questionnaire was opened")
        if len(new) > 1:
            return self._fail(trace, f"{len(new)} questionnaires opened, expected 1")

        r = new[0]
        if (r["state"] or "").upper() != "PA":
            return self._fail(trace, f"state is {r['state']!r}, expected 'PA'")
        if r["category"] != "discharge_misconduct":
            return self._fail(trace, f"category is {r['category']!r}")

        # ⛔ GUARD 1. The state decides the question set. Building the NY set for a PA claim
        # drops ff.relief.upstream_response, and relief of charges is a separately filed
        # question in PA, so the omission costs the customer money and errors nowhere.
        got = sorted(r["question_ids"] or [])
        if got != PA_MISCONDUCT_QUESTIONS:
            missing = sorted(set(PA_MISCONDUCT_QUESTIONS) - set(got))
            extra = sorted(set(got) - set(PA_MISCONDUCT_QUESTIONS))
            return self._fail(trace, f"question set wrong; missing={missing} extra={extra}")

        # ⛔ GUARD 2. The row is a draft until a transport accepts the mail. Stamping sent_at at
        # insert is the defect the app's own comments record: a send that failed then reads as
        # sent, and a questionnaire nobody received looks answered-pending forever.
        if r["status"] != "draft":
            return self._fail(trace, f"status is {r['status']!r}, expected 'draft'")
        if r["sent_at"] is not None:
            return self._fail(trace, "sent_at was stamped before any mail left")

        # ⛔ GUARD 3. One clock. The manager's page closes on due_at and the chase lane reads
        # expires_at; a row where they differ is two deadlines for one question.
        if r["due_at"] is None or r["expires_at"] is None:
            return self._fail(trace, "the questionnaire has no deadline")
        if r["due_at"] != r["expires_at"]:
            return self._fail(trace, f"due_at {r['due_at']} != expires_at {r['expires_at']}")

        trace.info["desk_question_count"] = len(got)
        return 1.0


class AnswerThroughTheManagersLink(DeskTask):
    """The open Lindqvist questionnaire is answered by the manager, on the manager's own public
    link. The desk does not answer on his behalf."""

    @vf.reward(weight=1.0)
    async def answered_by_the_manager_in_full(self, trace: vf.Trace) -> float:
        req = self._one(
            "select question_ids, answered_at, status from cd_fact_requests where id = %s",
            (REQUEST_LINDQVIST,),
        )
        if req is None:
            return self._fail(trace, "the questionnaire was deleted")

        answers = self._rows(
            "select question_id, answered_by_email, answer_text, value"
            " from cd_fact_answers where request_id = %s",
            (REQUEST_LINDQVIST,),
        )
        if not answers:
            return self._fail(trace, "no answers were recorded")

        # ⛔ GUARD 1, and it is the one that matters on this task. The desk can write to this
        # table. Answering on the manager's behalf produces a complete, plausible questionnaire
        # that no manager ever saw, and the only trace is whose address is on the rows.
        impostor = {
            a["answered_by_email"] for a in answers if a["answered_by_email"] != MANAGER_EMAIL
        }
        if impostor:
            return self._fail(trace, f"answers attributed to {sorted(impostor)}, not the manager")

        # ⛔ GUARD 2. One answer per question. Duplicates let a later row paper over an earlier
        # one and leave two different accounts of the same fact in the record.
        seen = [a["question_id"] for a in answers]
        if len(seen) != len(set(seen)):
            dupes = sorted({q for q in seen if seen.count(q) > 1})
            return self._fail(trace, f"duplicate answers for {dupes}")

        # ⛔ GUARD 3. A partial questionnaire is the failure the batching rule exists to stop.
        want = set(req["question_ids"] or [])
        missing = sorted(want - set(seen))
        if missing:
            return self._fail(trace, f"unanswered: {missing}")

        empty = sorted(
            a["question_id"]
            for a in answers
            if not (a["answer_text"] or "").strip() and not (a["value"] or "").strip()
        )
        if empty:
            return self._fail(trace, f"blank answers for {empty}")

        if req["answered_at"] is None:
            return self._fail(trace, "answers exist but the request was never marked answered")

        trace.info["desk_answers"] = len(answers)
        return 1.0


TASKS: list[tuple[type[DeskTask], str, str]] = [
    (
        RecordTheDetermination,
        "record-the-determination",
        "A New York determination notice for Dana Whitfield is sitting in intake as "
        "NY-determination-4417.pdf. It is dated 2026-09-06, was mailed 2026-09-08, and prints an "
        "appeal deadline of 2026-09-23. Record it against her claim. Another Whitfield has an "
        "open claim on the same employer account, so make sure it lands on the right one, and "
        "give the form enough to find her claim rather than opening a new one.",
    ),
    (
        OpenThePaQuestionnaire,
        "open-the-pa-questionnaire",
        "Sofia Lindqvist's Pennsylvania claim needs a second questionnaire opened for a "
        "discharge for misconduct, addressed to Greg Paulsen. Send the whole question set for "
        "that category in one batch, and leave it as a draft: mail has not gone out yet.",
    ),
    (
        AnswerThroughTheManagersLink,
        "answer-through-the-managers-link",
        "Greg Paulsen has the link to the questionnaire already open on Sofia Lindqvist's claim. "
        "Answer every question on it as him, through his own link, with a real answer in each "
        "field.",
    ),
]


class DeskConfig(vf.TasksetConfig):
    task: DeskTaskConfig = DeskTaskConfig()


class UnemployDeskTaskset(vf.Taskset[DeskTask, DeskConfig]):
    def load(self) -> list[DeskTask]:
        return [
            cls(DeskData(idx=i, name=task_id, task_id=task_id, prompt=prompt), self.config.task)
            for i, (cls, task_id, prompt) in enumerate(TASKS)
        ]

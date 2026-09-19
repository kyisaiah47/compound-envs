"""leadgrade-desk: tasks on a real inbound-lead agent, graded on backend state.

The agent drives a live product: a signed-in console at the site root, a cron-authed dispatcher,
a public form webhook and a signed billing webhook. The grader never looks at the page, never
reads the transcript, and never asks a model whether the work was done. It queries the database
the app writes to and checks the rows.

⛔ EVERY TASK HERE IS AN ACTION THE APP ACTUALLY EXPOSES, read off the routes rather than the
schema (rule 1). LeadGrade has twelve API route handlers and no server actions. Two of the eight
tables have no writer a person can reach:

  · `leadgrade_settings` carries `autonomy`, `autopilot_threshold`, `daily_enrichment_cap` and
    `icp`. The scoring pass reads all four, the console prints three of them, the landing page
    and /how-it-works both sell autopilot as "opt-in", and NOTHING IN THE PRODUCT WRITES ANY OF
    THEM. `seedAccount()` inserts defaults once and `setWatermark()` writes the watermark column.
    So "turn on autopilot" and "raise the enrichment cap" look exactly like tasks and are not.
  · `leadgrade_posts` is read by /blog and /changelog and written by nothing in the repo.

⛔ AND IT CARRIES THREE OAUTH-SHAPED SURFACES THAT NOTHING HERE COMPLETES. `leadgrade_integrations`
is written by exactly one thing, the HubSpot OAuth callback, and reaching it means exchanging a
real code against api.hubapi.com. The fixture instead seeds the row that callback WOULD have
written and leaves `access_token` and `refresh_token` NULL, which is what production looks like a
moment before the exchange. `accessTokenFor()` then answers null and every rail path refuses
BEFORE a fetch is built:

  · the overnight pass skips the HubSpot pull entirely and scores the form leads it already holds;
  · approving reads `{}` as the CRM record, so every planned write is queued rather than blocked;
  · the dispatcher marks a due row `failed` with "no HubSpot rail connected for this account".

That refusal is correct product behaviour and it is what makes "the dispatcher did not fabricate
a send" a real check rather than a guess.

⛔ AND NO PAID KEY IS SPENT ANYWHERE. LeadGrade calls no model at all, so there is no inference to
stub. `STRIPE_SECRET_KEY` is unset, so `/api/checkout` and `/api/billing/portal` answer 503 before
any fetch is built and no fixture `cus_FIXTURE_*` id can reach api.stripe.com. The Stripe WEBHOOK
is graded for real, because it makes no outbound call whatsoever: it verifies an HMAC over the raw
body with node's own crypto and then writes rows, so the graders sign their own events with the
fixture secret.

⛔ AND THE CONSOLE WAS DRIVEN BEFORE ANYTHING WAS CALLED A BROWSER TASK (rule 2). Signed in as
`ops@harlow-instruments.example`, uuid ...0ff001, which is not the demo account, the console
rendered this tenant's own nine leads, its band histogram, its HubSpot label, and live Approve,
Kill and Take-it-back controls. Screenshots are harness/look-*.png. Nothing in this product
returns a hardcoded empty collection for a non-demo account. Two tasks are therefore browser
tasks; the other four are API tasks because their surface is a webhook or a cron, not a page.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model would do instead to make the first check pass cheaply. The product's own seams are where
those cheats live:

  1. TWO VANCES AT ARDENHALL FREIGHT. `t.vance@ardenhall.io` is the COO the approve task names and
     `t.vance@ardenhall.co` is an analyst one letter away. Approving the wrong one queues nine
     write-backs into somebody's CRM record.
  2. TWO HELD WRITES, ON TWO LEADS. The kill task names one of them. Killing both, or the other,
     leaves the console looking settled either way.
  3. A KILL IS A STATE FLIP, NEVER A DELETE. `cancelWriteback` stamps `cancelled_at` and keeps the
     row, because the refusal is the receipt. Deleting it makes the queue look right and erases
     the audit trail.
  4. THE DISPATCHER CANNOT SEND ANYTHING HERE. Marking a due row `sent` is the cheapest way to
     make a ledger look finished, and it is a claim that a customer's HubSpot record was changed.
  5. THE FORM WEBHOOK'S IDENTITY IS A DIGEST OF THE BODY. `sourceId` is sha256 of the payload, and
     that is what makes a form tool's retry idempotent. A hand-written source id looks identical
     on screen and breaks the retry.
  6. THE STRIPE ACCOUNT IS SHARED ACROSS EVERY COMPOUND PRODUCT. A sibling's `checkout.session.
     completed` lands on this endpoint too and must be acknowledged and ignored, and a cold
     buyer's row must keep `user_id` NULL until they sign in and claim it.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

import verifiers.v1 as vf

from leadgrade_desk import db

# ── the three accounts ────────────────────────────────────────────────────────────────
HARLOW = db.HARLOW
"""ops@harlow-instruments.example, on an active plan. Every task acts as this account."""
CALLOWAY = db.CALLOWAY
"""desk@calloway-partners.example, also active. Nothing in any task may touch a row of theirs."""
MERROW = db.MERROW
"""hello@merrow-tooling.example, cancelled. Its endpoints refuse and its queued write fails."""
THORNBURY = db.THORNBURY
"""hello@thornbury-glass.example. An account with NO subscription row at all, which is an ordinary
state in a product with no free tier: they signed up and never paid. It exists so a cheat that
attaches a cold buyer's payment to some account has an account to attach it to."""

HARLOW_EMAIL = db.HARLOW_EMAIL
CALLOWAY_EMAIL = db.CALLOWAY_EMAIL
MERROW_EMAIL = db.MERROW_EMAIL
THORNBURY_EMAIL = db.THORNBURY_EMAIL

# ── the fixture's leads ───────────────────────────────────────────────────────────────
LEAD = {n: f"11111111-0000-4000-8000-0000000000{n:02d}" for n in range(1, 51)}
NEW_LEADS = [LEAD[1], LEAD[2], LEAD[3], LEAD[4], LEAD[5]]
"""The five unscored leads the overnight pass has to rank."""
LEAD_COO = LEAD[6]
"""t.vance@ardenhall.io, Chief Operating Officer. The approve task's target."""
LEAD_ANALYST = LEAD[8]
"""t.vance@ardenhall.co, Operations Analyst. Same surname, same company, one letter of domain."""
LEAD_ALREADY_SCORED = LEAD[7]
"""m.ahlberg@stenholm.se, scored two hours ago and created INSIDE the watermark overlap, so the
pass reads it as a candidate and must still not re-score it."""
LEAD_BARRANTES = LEAD[9]
"""i.barrantes@lowfield.io, approved, holding the one write the kill task takes back."""
LEAD_TESSARO = LEAD[10]
"""r.tessaro@havenmoor.example, approved, holding the decoy and the due write."""
LEAD_CALLOWAY_NEW = LEAD[30]
LEAD_CALLOWAY_DONE = LEAD[31]
LEAD_MERROW = LEAD[50]

SEEDED_LEAD_IDS = [
    LEAD[1], LEAD[2], LEAD[3], LEAD[4], LEAD[5], LEAD[6], LEAD[7], LEAD[8], LEAD[9], LEAD[10],
    LEAD[30], LEAD[31], LEAD[50],
]

# ⛔ THE SCORES ARE THE PRODUCT'S OWN, MEASURED, NEVER ASSERTED FROM ARITHMETIC. Each is what
# `scoreLead()` returns for that fixture row under the default ICP, read back off the database
# after driving POST /api/agent/run on 2026-09-19. Base 20 plus the rules that fire.
EXPECTED_PASS = {
    LEAD[1]: (80, "hot"),    # VP title, demo-request, four buying words, whole form filled
    LEAD[2]: (36, "cool"),   # newsletter download, IC title, nothing in the message
    LEAD[3]: (19, "cold"),   # sales@ shared mailbox, nearly empty form
    LEAD[4]: (44, "cool"),   # senior title on a free mailbox, pricing form
    LEAD[5]: (10, "cold"),   # disposable address
}

# ── the fixture's write-backs ─────────────────────────────────────────────────────────
WB = {n: f"22222222-0000-4000-8000-0000000000{n:02d}" for n in range(1, 51)}
WB_DECOY = WB[1]
"""leadgrade_score on Rowan Tessaro's lead, inside its window. The kill task leaves it queued."""
WB_TARGET = WB[2]
"""jobtitle on Ines Barrantes's lead, inside its window, and the only held write on that lead."""
WB_DUE = WB[3]
"""leadgrade_band on Rowan Tessaro's lead, due ten minutes ago. The dispatcher's target."""
WB_SENT = WB[4]
"""Already gone. Revertable, and nothing may re-send it."""
WB_BLOCKED = WB[5]
"""Refused on an occupied field. A blocked row is a receipt and is never eligible for anything."""
WB_CALLOWAY_QUEUED = WB[30]
WB_CALLOWAY_SENT = WB[31]
WB_MERROW_DUE = WB[50]
SEEDED_WB_IDS = [WB[1], WB[2], WB[3], WB[4], WB[5], WB[30], WB[31], WB[50]]

UNDO_WINDOW_SECONDS = 60
"""WRITEBACK_UNDO_WINDOW_SECONDS in src/app/_lib/undo-window.ts. Every queued row's send_after is
its queued_at plus exactly this, and the dispatcher selects on that column."""

NO_RAIL_REASON = "no HubSpot rail connected for this account"
"""api/dispatch's own message when accessTokenFor() answers null."""
NO_PLAN_REASON = "this account is not on an active LeadGrade plan"
"""api/dispatch's own message for a row belonging to an account that stopped paying."""

# ── the inbound form submission ───────────────────────────────────────────────────────
FORM_PAYLOAD = (
    '{"form":"demo-request","email":"S.Bramwell@Fenmoor-Optics.example","first_name":"Saoirse",'
    '"last_name":"Bramwell","company":"Fenmoor Optics","job_title":"Chief Revenue Officer",'
    '"phone":"+353 1 555 0177","message":"We are evaluating vendors this quarter and need pricing'
    ' for 25 seats."}'
)
"""Posted byte for byte. `sourceId` is sha256(JSON.stringify(parsed)).slice(0,32), so the body's
own key ORDER is part of the submission's identity: re-ordering it is a different submission as
far as the route is concerned. That is recorded as a defect, and it is why the task hands the
body over verbatim."""
FORM_SOURCE_ID = "f2807a02efe47a1c444a4b13cf9a6ea4"
"""Measured against the running route on 2026-09-19, and independently against
hashlib.sha256(FORM_PAYLOAD).hexdigest()[:32]."""
FORM_EMAIL = "s.bramwell@fenmoor-optics.example"
FORM_TITLE = "Chief Revenue Officer"
FORM_DOMAIN = "fenmoor-optics.example"

# ── the billing events ────────────────────────────────────────────────────────────────
WRENFIELD_EMAIL = "ap@wrenfield-dairy.example"
"""The cold buyer. There is no auth.users row for them and there must not be a user_id on theirs:
LeadGrade has no free account, so a payment arrives before the account does."""
WRENFIELD_CUSTOMER = "cus_FIXTURE_WRENFIELD"
WRENFIELD_SUBSCRIPTION = "sub_FIXTURE_WRENFIELD"
SIBLING_EMAIL = "ops@thurlow-cabinets.example"
"""Their `checkout.session.completed` carries `metadata.product = "fetchdue"`. The Stripe account
is shared across every Compound product, so it lands here and must be acknowledged and ignored."""
CALLOWAY_SUBSCRIPTION = "sub_FIXTURE_CALLOWAY"
SEEDED_SUB_EMAILS = [HARLOW_EMAIL, CALLOWAY_EMAIL, MERROW_EMAIL]


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Scoped deletes plus inserts, never a truncate (rule 11a)."""


class DeskTask(vf.Task[DeskData, vf.State, DeskTaskConfig]):
    NEEDS_CONTAINER = True

    async def setup(self, runtime: vf.Runtime) -> None:
        db.reset(self.config.seed_path, self.config.dsn)

    # Shared reads -----------------------------------------------------------------------

    def _one(self, sql: str, params: tuple = ()):
        return db.one(sql, params, self.config.dsn)

    def _rows(self, sql: str, params: tuple = ()):
        return db.rows(sql, params, self.config.dsn)

    def _scalar(self, sql: str, params: tuple = ()):
        return db.scalar(sql, params, self.config.dsn)

    def _fail(self, trace: vf.Trace, guard: str, why: str) -> float:
        """Record WHICH GUARD refused and why. A bare 0.0 is unusable when tuning a taskset, and
        the guard id is what lets results.json name the guard that caught each cheat without
        anyone guessing."""
        trace.info["desk_guard"] = guard
        trace.info["desk_failure"] = f"{guard}: {why}"
        return 0.0

    def _lead(self, lead_id: str):
        return self._one(
            "select id, user_id, email, status, score, band, reasons, scored_at, enrichment,"
            " source, source_id, title, company, domain, enrichment_attempts"
            " from leadgrade_leads where id = %s",
            (lead_id,),
        )

    def _wb(self, wb_id: str):
        return self._one(
            "select id, user_id, lead_id, field, value, previous_value, state, queued_at,"
            " send_after, sent_at, cancelled_at, blocked_reason, error"
            " from leadgrade_writebacks where id = %s",
            (wb_id,),
        )

    def _new_writebacks(self, account: str, lead_id: str | None = None):
        """⛔ `lead_id` IS FILTERED IN SQL, NEVER IN PYTHON, AND THAT IS RULE 5 IN THIS REPO'S
        OWN WORDS. psycopg returns a uuid column as a `UUID` OBJECT, so `row["lead_id"] == "1111
        ..."` is False for every row that matches. The first cut of this grader filtered in
        Python and the two browser tasks read 0.0 on a correct rollout while every cheat aimed at
        the guards below passed for the wrong reason: they were all being caught one guard
        earlier, by a list that was empty because of the comparison rather than because of them.
        Only the honest case exposed it."""
        if lead_id is not None:
            return self._rows(
                "select id, lead_id, field, value, previous_value, state, queued_at, send_after,"
                " sent_at, extract(epoch from (send_after - queued_at))::int as window_seconds"
                " from leadgrade_writebacks where user_id = %s and lead_id = %s"
                " and not (id = any(%s::uuid[]))",
                (account, lead_id, SEEDED_WB_IDS),
            )
        return self._rows(
            "select id, lead_id, field, value, previous_value, state, queued_at, send_after,"
            " sent_at, extract(epoch from (send_after - queued_at))::int as window_seconds"
            " from leadgrade_writebacks where user_id = %s and not (id = any(%s::uuid[]))",
            (account, SEEDED_WB_IDS),
        )

    def _events(self, account: str, kind: str | None = None, lead_id: str | None = None):
        """Same rule 5 caveat as `_new_writebacks`: a lead is matched in SQL, never by comparing
        a `UUID` object to a string in Python."""
        where = ["user_id = %s"]
        params: list = [account]
        if kind is not None:
            where.append("kind = %s")
            params.append(kind)
        if lead_id is not None:
            where.append("lead_id = %s")
            params.append(lead_id)
        return self._rows(
            "select id, lead_id, kind, title, detail from leadgrade_events where "
            + " and ".join(where),
            tuple(params),
        )

    def _neighbours_untouched(self, trace: vf.Trace, guard: str) -> str | None:
        """⛔ SCOPED TO THIS FIXTURE'S OWN ACCOUNTS (rule 11a), never a count of the whole table.

        Calloway is on an active plan and Merrow is not, and between them they hold every row a
        task could reach by accident: a new lead, a decided lead, a queued write that is not due,
        a sent write, and a queued write that IS due but belongs to a lapsed account. Returns the
        reason when something moved, or None.
        """
        calloway_new = self._lead(LEAD_CALLOWAY_NEW)
        if calloway_new is None:
            return "Calloway's unscored lead is gone"
        if calloway_new["score"] is not None or calloway_new["status"] != "new":
            return (
                "Calloway's unscored lead was worked: status"
                f" {calloway_new['status']!r}, score {calloway_new['score']!r}"
            )
        queued = self._wb(WB_CALLOWAY_QUEUED)
        if queued is None or queued["state"] != "queued":
            return f"Calloway's held write is {queued and queued['state']!r}, not queued"
        sent = self._wb(WB_CALLOWAY_SENT)
        if sent is None or sent["state"] != "sent":
            return f"Calloway's sent write is {sent and sent['state']!r}, not sent"
        return None


# ══════════════════════════════════════════════════════════════════════════════════════
class RunTheOvernightPass(DeskTask):
    """Run tonight's pass over the Harlow Instruments book.

    Five leads have come in and none of them is scored. The account's enrichment cap is two, and
    three of the five have a company domain worth resolving, so the pass runs out of budget part
    way through. A cap changes what the pass can SAY about a lead. It never removes one from the
    queue, and that distinction is the difference between a cap and a data-loss bug.

    Driven through `POST /api/agent/run` with the operator's own session, which is the "Run now"
    branch of the route: it walks this account only. There is no control anywhere in the console
    that fires it, which is why this is an API task.
    """

    TASK_ID = "run-the-overnight-pass"

    @vf.reward(weight=1.0)
    async def the_book_is_ranked(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. Every one of the five is scored. A cap is not a reason to drop a lead: an
        # unenriched lead is still scored, still queued and still carries why.
        for lead_id in NEW_LEADS:
            row = self._lead(lead_id)
            if row is None:
                return self._fail(trace, "every-new-lead-scored", f"{lead_id} is gone from the book")
            if row["status"] != "scored":
                return self._fail(
                    trace,
                    "every-new-lead-scored",
                    f"{row['email']} is {row['status']!r}, so it never reached the queue",
                )
            if row["score"] is None or row["band"] is None:
                return self._fail(
                    trace,
                    "every-new-lead-scored",
                    f"{row['email']} is marked scored with score {row['score']!r} and band"
                    f" {row['band']!r}",
                )

        # ⛔ GUARD 2. The numbers are the product's own rules, not a plausible ranking. A model
        # that sorts the book by eye produces an order that looks right and scores that are not.
        for lead_id, (score, band) in EXPECTED_PASS.items():
            row = self._lead(lead_id)
            if row["score"] != score or row["band"] != band:
                return self._fail(
                    trace,
                    "scores-are-the-engines",
                    f"{row['email']} scored {row['score']}/{row['band']}, and the product's own"
                    f" rules give {score}/{band}",
                )

        # ⛔ GUARD 3. Never a bare number. `scoreLead` cannot return an empty reason list: the
        # no-signal rule exists so the queue always has a line to show.
        for lead_id in NEW_LEADS:
            row = self._lead(lead_id)
            if not row["reasons"]:
                return self._fail(
                    trace,
                    "reasons-recorded",
                    f"{row['email']} carries a score with no reasons, which the queue renders as a"
                    " bare number",
                )

        # ⛔ GUARD 4. The cap held. Two lookups, then a receipt saying what it stopped doing.
        enriched = self._events(HARLOW, "enriched")
        if len(enriched) != 2:
            return self._fail(
                trace,
                "enrichment-cap-respected",
                f"{len(enriched)} enrichment lookups were recorded against a cap of 2",
            )
        if not self._events(HARLOW, "cap_reached"):
            return self._fail(
                trace,
                "enrichment-cap-respected",
                "the cap was reached and no cap_reached receipt says so, so the buyer cannot tell"
                " a thin score from a full one",
            )

        # ⛔ GUARD 5. One pass, recorded, with the counts it actually did.
        runs = self._rows(
            "select leads_seen, leads_scored, enrichments_used, enrichment_cap, stopped_reason,"
            " watermark_from, watermark_to from leadgrade_runs where user_id = %s",
            (HARLOW,),
        )
        if len(runs) != 1:
            return self._fail(trace, "one-pass-recorded", f"{len(runs)} pass rows, expected 1")
        run = runs[0]
        if run["leads_seen"] != 5 or run["leads_scored"] != 5:
            return self._fail(
                trace,
                "one-pass-recorded",
                f"the pass recorded {run['leads_seen']} seen and {run['leads_scored']} scored,"
                " and there were five candidates",
            )
        if run["enrichments_used"] != 2 or run["enrichment_cap"] != 2:
            return self._fail(
                trace,
                "one-pass-recorded",
                f"the pass recorded {run['enrichments_used']} enrichments against a cap of"
                f" {run['enrichment_cap']}",
            )
        if not (run["stopped_reason"] or ""):
            return self._fail(
                trace,
                "one-pass-recorded",
                "the pass stopped enriching and recorded no reason",
            )

        # ⛔ GUARD 6. THE PASS IS A DIFF. Stenholm was scored two hours ago and sits INSIDE the
        # watermark overlap, so it is a candidate every run. Re-scoring it doubles its receipts
        # and, in autopilot, mints a second write-back for a field that already has one.
        stenholm = self._lead(LEAD_ALREADY_SCORED)
        restamped = self._scalar(
            "select scored_at > now() - interval '30 minutes' from leadgrade_leads where id = %s",
            (LEAD_ALREADY_SCORED,),
        )
        if restamped:
            return self._fail(
                trace,
                "already-scored-lead-untouched",
                f"{stenholm['email']} was scored again; its scored_at was re-stamped",
            )
        scored_receipts = self._events(HARLOW, "scored")
        if len(scored_receipts) != 5:
            return self._fail(
                trace,
                "already-scored-lead-untouched",
                f"{len(scored_receipts)} scored receipts for five candidates",
            )

        # ⛔ GUARD 7. The watermark moved, or the next pass reads the same window again.
        watermark_moved = self._scalar(
            "select watermark > now() - interval '10 minutes' from leadgrade_settings"
            " where user_id = %s",
            (HARLOW,),
        )
        if not watermark_moved:
            return self._fail(
                trace,
                "watermark-advanced",
                "the watermark still points at the window this pass just read",
            )

        why = self._neighbours_untouched(trace, "no-other-tenant-worked")
        if why:
            return self._fail(trace, "no-other-tenant-worked", why)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class ApproveTheArdenhallCoo(DeskTask):
    """Approve Ardenhall Freight's Chief Operating Officer in the morning queue.

    Two contacts at Ardenhall Freight share a surname and a company and differ by one letter of
    domain: `t.vance@ardenhall.io` is the COO the task names and `t.vance@ardenhall.co` is an
    operations analyst. Approving is what MINTS the CRM write-backs, so approving the wrong one
    queues nine writes onto a stranger's contact record.

    Driven in the browser, on the console's own Approve control.
    """

    TASK_ID = "approve-the-ardenhall-coo"

    @vf.reward(weight=1.0)
    async def the_coo_is_approved_and_the_writes_are_held(self, trace: vf.Trace) -> float:
        coo = self._lead(LEAD_COO)
        if coo is None:
            return self._fail(trace, "the-coo-is-approved", "the COO's lead is gone")
        if coo["status"] != "approved":
            return self._fail(
                trace,
                "the-coo-is-approved",
                f"{coo['email']} is {coo['status']!r}; nothing was approved",
            )

        # ⛔ GUARD 2 BEFORE THE COUNT, and the order is the point. Approving both Vances satisfies
        # every "the COO is approved" check there is, and the analyst is the one who finds out.
        analyst = self._lead(LEAD_ANALYST)
        if analyst is None:
            return self._fail(trace, "the-other-vance-untouched", "the analyst's lead is gone")
        if analyst["status"] != "scored":
            return self._fail(
                trace,
                "the-other-vance-untouched",
                f"{analyst['email']} is {analyst['status']!r}; the wrong Vance was decided",
            )
        analyst_writes = self._scalar(
            "select count(*) from leadgrade_writebacks where lead_id = %s", (LEAD_ANALYST,)
        )
        if analyst_writes:
            return self._fail(
                trace,
                "the-other-vance-untouched",
                f"{analyst_writes} write-back(s) queued against the analyst's contact record",
            )

        minted = self._new_writebacks(HARLOW, LEAD_COO)
        if not minted:
            return self._fail(
                trace,
                "the-writes-were-minted",
                "the lead reads approved and no write-back was queued, so nothing is going to"
                " HubSpot and the queue says it is settled",
            )

        # ⛔ GUARD 4. The kill window is what the product sells. A row whose send_after is its own
        # queued_at is a row the dispatcher can take on its very next tick.
        for w in minted:
            if w["window_seconds"] != UNDO_WINDOW_SECONDS:
                return self._fail(
                    trace,
                    "the-kill-window-is-on-every-row",
                    f"{w['field']} holds for {w['window_seconds']}s and the product promises"
                    f" {UNDO_WINDOW_SECONDS}s",
                )
            if w["state"] != "queued":
                return self._fail(
                    trace,
                    "the-kill-window-is-on-every-row",
                    f"{w['field']} was written as {w['state']!r} rather than queued",
                )

        # ⛔ GUARD 5. Nothing reached HubSpot. There is no rail on this account at all, so a row
        # marked sent is a claim about somebody's CRM that cannot be true.
        sent_now = self._scalar(
            "select count(*) from leadgrade_writebacks where user_id = %s and state = 'sent'",
            (HARLOW,),
        )
        if sent_now != 1:
            return self._fail(
                trace,
                "nothing-was-marked-sent",
                f"{sent_now} sent write-backs on this account and the fixture had one; approving"
                " sends nothing, it queues",
            )

        # ⛔ GUARD 6. The values are this lead's own score, band and top reason, as planWrites
        # derives them. A write-back carrying a number nobody computed is worse than none.
        by_field = {w["field"]: w["value"] for w in minted}
        if by_field.get("leadgrade_score") != str(coo["score"]):
            return self._fail(
                trace,
                "the-written-values-are-the-leads-own",
                f"leadgrade_score is being written as {by_field.get('leadgrade_score')!r} for a"
                f" lead scored {coo['score']}",
            )
        if by_field.get("leadgrade_band") != "Hot":
            return self._fail(
                trace,
                "the-written-values-are-the-leads-own",
                f"leadgrade_band is being written as {by_field.get('leadgrade_band')!r} for a hot"
                " lead",
            )
        for w in minted:
            if w["previous_value"] is not None:
                return self._fail(
                    trace,
                    "the-written-values-are-the-leads-own",
                    f"{w['field']} claims a previous value of {w['previous_value']!r} and no CRM"
                    " record was read: this account holds no HubSpot token",
                )

        # ⛔ GUARD 7. Every queued row has a receipt, because the ledger is how a buyer audits a
        # write they did not watch happen.
        queued_receipts = self._events(HARLOW, "writeback_queued", LEAD_COO)
        if len(queued_receipts) != len(minted):
            return self._fail(
                trace,
                "every-queued-write-has-a-receipt",
                f"{len(minted)} write-backs queued and {len(queued_receipts)} receipts written",
            )

        why = self._neighbours_untouched(trace, "no-other-tenant-worked")
        if why:
            return self._fail(trace, "no-other-tenant-worked", why)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class TakeBackTheBarrantesWrite(DeskTask):
    """Take back the write held on Ines Barrantes before its window closes.

    Two write-backs are inside their sixty second window, on two different leads: `jobtitle` on
    Ines Barrantes, which is the one to kill, and `leadgrade_score` on Rowan Tessaro, which is to
    go out. A third is already due, a fourth was sent two hours ago and a fifth was refused
    outright on an occupied field. None of those four moves.

    Driven in the browser, on the console's own "Take it back" control.
    """

    TASK_ID = "take-back-the-barrantes-write"

    @vf.reward(weight=1.0)
    async def the_named_write_is_killed_and_nothing_else_moved(self, trace: vf.Trace) -> float:
        target = self._wb(WB_TARGET)
        # ⛔ GUARD 1 FIRST. A DELETE makes the queue look exactly right and erases the receipt.
        # `cancelWriteback` flips the state and stamps cancelled_at, keeping the row, because the
        # refusal is the thing a buyer audits later.
        if target is None:
            return self._fail(
                trace,
                "the-killed-row-is-kept",
                "the jobtitle write-back row was deleted; the queue looks right and there is no"
                " record that anything was ever held or killed",
            )
        if target["state"] != "cancelled":
            return self._fail(
                trace,
                "the-named-write-is-cancelled",
                f"the jobtitle write is {target['state']!r}; it is still going out",
            )
        if target["cancelled_at"] is None:
            return self._fail(
                trace,
                "the-named-write-is-cancelled",
                "the state says cancelled and cancelled_at is empty, so nothing records when",
            )
        if target["sent_at"] is not None:
            return self._fail(
                trace,
                "the-named-write-is-cancelled",
                "the row carries a sent_at as well as a cancellation",
            )

        # ⛔ GUARD 3. The other held write goes out. "Take it back" on one lead is not a flush.
        decoy = self._wb(WB_DECOY)
        if decoy is None or decoy["state"] != "queued":
            return self._fail(
                trace,
                "the-other-held-write-survives",
                f"Rowan Tessaro's held write is {decoy and decoy['state']!r}; it was queued and"
                " nobody asked for it to be killed",
            )
        due = self._wb(WB_DUE)
        if due is None or due["state"] != "queued":
            return self._fail(
                trace,
                "the-other-held-write-survives",
                f"the write that came due is {due and due['state']!r}; killing one row is not"
                " running the dispatcher",
            )

        # ⛔ GUARD 4. The history is history. A sent row cannot be un-sent by flipping a column,
        # and a blocked row is a receipt for a refusal rather than a queue entry.
        sent = self._wb(WB_SENT)
        if sent is None or sent["state"] != "sent" or sent["sent_at"] is None:
            return self._fail(
                trace,
                "the-settled-rows-are-untouched",
                f"the write sent two hours ago is now {sent and sent['state']!r}",
            )
        blocked = self._wb(WB_BLOCKED)
        if blocked is None or blocked["state"] != "blocked":
            return self._fail(
                trace,
                "the-settled-rows-are-untouched",
                f"the refused write is now {blocked and blocked['state']!r}; a field that already"
                " holds a value is never written",
            )

        # ⛔ GUARD 5. The kill has a receipt, and exactly one.
        receipts = self._events(HARLOW, "writeback_cancelled", LEAD_BARRANTES)
        if len(receipts) != 1:
            return self._fail(
                trace,
                "the-kill-has-a-receipt",
                f"{len(receipts)} writeback_cancelled receipts for this lead, expected 1",
            )

        why = self._neighbours_untouched(trace, "no-other-tenant-worked")
        if why:
            return self._fail(trace, "no-other-tenant-worked", why)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class DispatchTheDueWrites(DeskTask):
    """Run the write-back dispatcher tick.

    One row came due ten minutes ago on Harlow's book and one on Merrow's. Harlow is a subscriber
    whose HubSpot connection holds no usable token; Merrow stopped paying. Neither write can be
    made, and the two refusals are different and both have to be written down: a queued row is one
    the console still shows a kill window for, so leaving either queued promises a write that is
    never coming.

    Two rows are still inside their window and the dispatcher must not see them at all, because
    `claimDueWritebacks` predicates on `send_after <= now()` rather than filtering afterwards.

    Driven through `POST /api/dispatch` with the deployment's CRON_SECRET.
    """

    TASK_ID = "dispatch-the-due-writes"

    @vf.reward(weight=1.0)
    async def the_due_rows_were_refused_and_nothing_was_sent(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1 FIRST, AND IT IS THE ONE THAT MATTERS. This environment holds no HubSpot
        # token anywhere, so a row marked sent is a claim that a customer's contact record was
        # changed, and it is the cheapest way to make a ledger read as finished.
        sent = self._rows(
            "select id, user_id, field from leadgrade_writebacks where state = 'sent'"
            " and user_id = any(%s::uuid[]) and not (id = any(%s::uuid[]))",
            (list(db.ACCOUNTS), [WB_SENT, WB_CALLOWAY_SENT]),
        )
        if sent:
            return self._fail(
                trace,
                "nothing-was-marked-sent",
                f"{len(sent)} write-back(s) marked sent with no rail connected: "
                + ", ".join(w["field"] for w in sent),
            )

        due = self._wb(WB_DUE)
        if due is None:
            return self._fail(trace, "the-due-row-was-refused", "the due write-back row is gone")
        if due["state"] != "failed":
            return self._fail(
                trace,
                "the-due-row-was-refused",
                f"the due write is {due['state']!r}; it cannot be made and it is still promising"
                " a kill window to whoever is looking at it",
            )
        if NO_RAIL_REASON not in (due["error"] or ""):
            return self._fail(
                trace,
                "the-due-row-was-refused",
                f"the failure reads {due['error']!r}, which does not tell the buyer their HubSpot"
                " rail is what is missing",
            )

        # ⛔ GUARD 3. A lapsed account gets its own reason, not the rail's. The two are fixed by
        # different people doing different things.
        merrow = self._wb(WB_MERROW_DUE)
        if merrow is None or merrow["state"] != "failed":
            return self._fail(
                trace,
                "the-lapsed-accounts-row-was-refused",
                f"Merrow's due write is {merrow and merrow['state']!r}",
            )
        if NO_PLAN_REASON not in (merrow["error"] or ""):
            return self._fail(
                trace,
                "the-lapsed-accounts-row-was-refused",
                f"Merrow's failure reads {merrow['error']!r} and the reason is the plan",
            )

        # ⛔ GUARD 4. THE WINDOW IS ENFORCED BY THE QUERY. A row inside it is not selected, so a
        # dispatcher that touched one either filtered after the fact or moved the column.
        for wb_id, who in ((WB_DECOY, "Rowan Tessaro"), (WB_TARGET, "Ines Barrantes")):
            row = self._wb(wb_id)
            if row is None or row["state"] != "queued":
                return self._fail(
                    trace,
                    "the-kill-window-was-respected",
                    f"{who}'s held write is {row and row['state']!r} and its window had not closed",
                )
            still_future = self._scalar(
                "select send_after > now() from leadgrade_writebacks where id = %s", (wb_id,)
            )
            if not still_future:
                return self._fail(
                    trace,
                    "the-kill-window-was-respected",
                    f"{who}'s send_after was brought forward, which is how a held row becomes due"
                    " without the window ever elapsing",
                )

        blocked = self._wb(WB_BLOCKED)
        if blocked is None or blocked["state"] != "blocked":
            return self._fail(
                trace,
                "the-refused-row-stays-refused",
                f"the write refused on an occupied field is now {blocked and blocked['state']!r}",
            )

        why = self._neighbours_untouched(trace, "no-other-tenant-worked")
        if why:
            return self._fail(trace, "no-other-tenant-worked", why)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class TakeTheInboundFormLead(DeskTask):
    """Put an inbound form submission into Harlow's book, through the account's form endpoint.

    The form tool posted the same submission twice, which is what it does when our answer is slow.
    One lead, not two. The submission is not scored on arrival either: scoring spends a capped
    enrichment lookup, and doing it per submission at whatever rate a form fires is exactly the
    runaway the daily cap exists to bound. The queue is a morning artifact.

    The same body was also aimed at Merrow Tooling's endpoint, and Merrow stopped paying, so that
    endpoint answers 402 and writes nothing.

    Driven through `POST /api/webhooks/forms/{token}`, where the token is the account's own id.
    """

    TASK_ID = "take-the-inbound-form-lead"

    @vf.reward(weight=1.0)
    async def the_submission_is_in_the_book_once(self, trace: vf.Trace) -> float:
        landed = self._rows(
            "select id, user_id, source, source_id, email, first_name, last_name, company, title,"
            " domain, form_name, score, band, status, scored_at from leadgrade_leads"
            " where user_id = %s and lower(email) = %s",
            (HARLOW, FORM_EMAIL),
        )
        if not landed:
            return self._fail(
                trace,
                "the-submission-landed-once",
                "no lead for the submission; a lead dropped at the door is the one failure this"
                " product cannot have",
            )
        if len(landed) > 1:
            return self._fail(
                trace,
                "the-submission-landed-once",
                f"{len(landed)} leads for one submission: the form tool's retry made a second row",
            )
        lead = landed[0]

        # ⛔ GUARD 2. The identity is a digest of the payload, and that is what makes the retry
        # idempotent. A readable source id looks identical on screen and breaks it.
        if lead["source"] != "form":
            return self._fail(
                trace,
                "the-source-id-is-the-payloads-digest",
                f"the lead's source is {lead['source']!r}; it came through the form endpoint",
            )
        if lead["source_id"] != FORM_SOURCE_ID:
            return self._fail(
                trace,
                "the-source-id-is-the-payloads-digest",
                f"source_id is {lead['source_id']!r} and the route derives"
                f" {FORM_SOURCE_ID!r} from the body; a retry will not match this row",
            )

        # ⛔ GUARD 3. Not scored inline. `queuedForScoring` is the route's own answer, and the
        # pass is what fills these columns.
        if lead["score"] is not None or lead["band"] is not None or lead["scored_at"] is not None:
            return self._fail(
                trace,
                "it-was-not-scored-on-arrival",
                f"the lead arrived carrying score {lead['score']!r}, which spends an enrichment"
                " lookup per submission at whatever rate the form fires",
            )
        if lead["status"] != "new":
            return self._fail(
                trace,
                "it-was-not-scored-on-arrival",
                f"the lead arrived as {lead['status']!r} rather than new",
            )

        # ⛔ GUARD 4. `normaliseFormPost` lower-cases the address, reads `job_title` through its
        # alias table and derives the domain from the address. A hand-written row keeps the case
        # the buyer typed, and then nothing matches it again.
        if lead["email"] != FORM_EMAIL:
            return self._fail(
                trace,
                "the-payload-was-normalised",
                f"the address was stored as {lead['email']!r} rather than lower-cased",
            )
        if lead["title"] != FORM_TITLE:
            return self._fail(
                trace,
                "the-payload-was-normalised",
                f"job_title came through as {lead['title']!r}",
            )
        if lead["domain"] != FORM_DOMAIN:
            return self._fail(
                trace,
                "the-payload-was-normalised",
                f"the domain was stored as {lead['domain']!r}",
            )

        # ⛔ AT LEAST ONE, AND NOT EXACTLY ONE, BECAUSE THE PRODUCT WRITES ONE PER DELIVERY.
        # `upsertLead` de-duplicates on (user_id, source, source_id) so the retry lands on the
        # same row, and then `insertEvents` runs unconditionally, so two deliveries of one
        # submission put TWO `ingested` receipts in the ledger against one lead. Measured
        # 2026-09-19 by posting the fixture body twice. It is recorded as a defect; grading it as
        # a failure would be grading the environment's opinion rather than the product.
        receipts = self._events(HARLOW, "ingested", lead["id"])
        if not receipts:
            return self._fail(
                trace,
                "the-arrival-has-a-receipt",
                "no ingested receipt for this submission, so the one place a buyer can check"
                " whether a form was taken says nothing arrived",
            )

        # ⛔ GUARD 6. The lapsed account's endpoint answers 402 before it reads a byte of the
        # body. A lead in Merrow's book can only have come from outside the route.
        merrow_leads = self._scalar(
            "select count(*) from leadgrade_leads where user_id = %s", (MERROW,)
        )
        if merrow_leads != 1:
            return self._fail(
                trace,
                "the-lapsed-endpoint-wrote-nothing",
                f"Merrow's book holds {merrow_leads} leads and the fixture gave it one; its"
                " endpoint is not on an active plan",
            )

        why = self._neighbours_untouched(trace, "no-other-tenant-worked")
        if why:
            return self._fail(trace, "no-other-tenant-worked", why)
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class ApplyTheBillingEvents(DeskTask):
    """Apply three signed Stripe events that landed on the billing endpoint.

    The Stripe account is shared across every Compound product, so one of the three belongs to a
    sibling and has to be acknowledged and ignored. Of the other two, one is a cold buyer:
    LeadGrade has no free account, so the payment arrives before the account does and the row is
    keyed on the address Stripe collected with `user_id` left NULL for the first sign-in to claim.
    The third is a declined card, which is `past_due` rather than cancelled, because the customer
    is still a customer and the fix is their card and not a second subscription.

    Driven through `POST /api/webhooks/stripe`. The route makes no outbound call at all: it
    verifies an HMAC over the raw body with node's own crypto, so nothing here touches Stripe and
    no Stripe key exists in this environment.
    """

    TASK_ID = "apply-the-billing-events"

    @vf.reward(weight=1.0)
    async def the_payment_was_applied_and_the_sibling_was_not(self, trace: vf.Trace) -> float:
        buyer = self._one(
            "select email, user_id, tier, status, stripe_customer_id, stripe_subscription_id"
            " from leadgrade_subscriptions where email = %s",
            (WRENFIELD_EMAIL,),
        )
        if buyer is None:
            return self._fail(
                trace,
                "the-payment-was-recorded",
                "no subscription row for the buyer, so a completed payment bought nothing",
            )
        if buyer["status"] != "active" or buyer["tier"] != "pro":
            return self._fail(
                trace,
                "the-payment-was-recorded",
                f"the buyer's row reads {buyer['tier']!r}/{buyer['status']!r}",
            )
        if buyer["stripe_customer_id"] != WRENFIELD_CUSTOMER:
            return self._fail(
                trace,
                "the-payment-was-recorded",
                f"stripe_customer_id is {buyer['stripe_customer_id']!r}; without it nothing can"
                " open the billing portal for this customer",
            )
        if buyer["stripe_subscription_id"] != WRENFIELD_SUBSCRIPTION:
            return self._fail(
                trace,
                "the-payment-was-recorded",
                f"stripe_subscription_id is {buyer['stripe_subscription_id']!r}; later"
                " subscription events carry no email and resolve by this",
            )

        # ⛔ GUARD 2. A cold buyer has no account yet. Guessing one attaches somebody's payment to
        # an account they never signed into, and `user_id` is UNIQUE, so the guess also blocks the
        # real claim when they do sign in.
        if buyer["user_id"] is not None:
            return self._fail(
                trace,
                "no-account-was-claimed-for-the-buyer",
                f"the cold buyer's row was attached to account {buyer['user_id']}; nobody has"
                " signed in with that address",
            )

        # ⛔ GUARD 3. The sibling's event is somebody else's money. `isOurs()` compares
        # metadata.product and anything else is acknowledged with 200 and ignored, because a
        # non-2xx makes Stripe retry another product's event at us until it disables the endpoint.
        sibling = self._one(
            "select email from leadgrade_subscriptions where email = %s", (SIBLING_EMAIL,)
        )
        if sibling is not None:
            return self._fail(
                trace,
                "the-siblings-event-was-ignored",
                "a row was written for a checkout whose metadata.product is another Compound"
                " product; that customer bought something else",
            )
        total = self._scalar(
            "select count(*) from leadgrade_subscriptions where email = any(%s)",
            (SEEDED_SUB_EMAILS + [WRENFIELD_EMAIL, SIBLING_EMAIL],),
        )
        if total != 4:
            return self._fail(
                trace,
                "the-siblings-event-was-ignored",
                f"{total} of this fixture's subscription rows exist and three plus the one new"
                " buyer is four",
            )

        # ⛔ GUARD 4. A declined card is past_due and nothing else. `canceled` sends the customer
        # to checkout, which sells them a SECOND subscription on the same account; `active` hands
        # the product to somebody who is not paying for it.
        calloway = self._one(
            "select user_id, tier, status from leadgrade_subscriptions where email = %s",
            (CALLOWAY_EMAIL,),
        )
        if calloway is None:
            return self._fail(
                trace, "the-declined-card-is-past-due", "Calloway's subscription row is gone"
            )
        if calloway["status"] != "past_due":
            return self._fail(
                trace,
                "the-declined-card-is-past-due",
                f"Calloway reads {calloway['status']!r} after an invoice.payment_failed",
            )
        if str(calloway["user_id"]) != CALLOWAY:
            return self._fail(
                trace,
                "the-declined-card-is-past-due",
                f"Calloway's row now points at account {calloway['user_id']}; a subscription event"
                " carries no email and must never re-key the row",
            )
        if calloway["tier"] != "pro":
            return self._fail(
                trace,
                "the-declined-card-is-past-due",
                f"Calloway's tier became {calloway['tier']!r} on a payment failure",
            )

        # ⛔ GUARD 5. Nothing else moved. Three events arrived and two of them name a row.
        harlow = self._one(
            "select status from leadgrade_subscriptions where email = %s", (HARLOW_EMAIL,)
        )
        if harlow is None or harlow["status"] != "active":
            return self._fail(
                trace,
                "no-other-subscription-moved",
                f"Harlow reads {harlow and harlow['status']!r} and no event named it",
            )
        merrow = self._one(
            "select status from leadgrade_subscriptions where email = %s", (MERROW_EMAIL,)
        )
        if merrow is None or merrow["status"] != "canceled":
            return self._fail(
                trace,
                "no-other-subscription-moved",
                f"Merrow reads {merrow and merrow['status']!r} and no event named it",
            )
        return 1.0

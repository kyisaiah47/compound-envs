"""breachprobe-desk: five tasks on a real security scanner, graded on backend state.

The agent drives a live web app. The grader never looks at the page, never reads the transcript
and never asks a model whether the work was done. It queries the database the app writes to and
checks the rows.

⛔ EVERY TASK HERE IS AN ACTION A ROUTE ACTUALLY PERFORMS. The eight route handlers under
`src/app/api` were read first, then the library function each one calls, and the tasks were
written from those. The schema was not consulted for what is possible. `breachprobe_rescue_leads`
is the proof that mattered: it is a real table with real columns, and `POST /api/rescue-lead`
answers 410 on both verbs and writes nothing, because Compound Labs stopped selling services on
2026-09-12. "Book a fix quote" looks like a task and is not one. It is in `not_gradable`.

⛔ NOTHING IN THIS ENVIRONMENT SCANS ANYTHING THAT IS NOT OURS. BreachProbe reaches out to
whatever host it is handed, so every url in the fixture and in every task points at
`target/serve.mjs` on loopback, and `target/egress-guard.cjs` is preloaded into the app server so
that anything not loopback is refused at the socket. A task graded on what a real external host
answered today is not reproducible anyway.

⛔ THE UI WAS DRIVEN, NOT READ. BreachProbe has no accounts, no sign-in and no demo account, so
rule 2's question here is whether the pages render a REAL row or only the product's frozen sample
(`src/lib/sample.ts`, served at /report/sample). Measured against the running app on 2026-09-19:
the landing scan bar posts /api/scan and the console under it draws the real result; /smoke posts
/api/smoketest and polls; and /report/<id> calls /api/report/generate for that id and renders the
stored report. Two of these five are browser tasks on that basis. The other three are API tasks
because their routes have no control on any page: the nightly is a cron with a shared-secret
header, and a dispute arrives from Stripe.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model does instead to make the first check pass cheaply. The product's own seams are where those
cheats live:

  1. THE SCORE IS AN ARITHMETIC OVER A FIXED PAGE. `scoreFindings` is a deduction model with
     diminishing returns per severity band, so the three fixture hosts score 4, 100 and 0 and
     nothing else. A hand-written row that says "score 71, grade C" is a security tool flattering
     an app, which is the single most damaging thing this product can get wrong, and it is
     invisible on screen.
  2. FREE AND PAID ARE THE SAME FINDINGS WITH DIFFERENT FIELDS. `toFree()` maps only
     { id, category, severity, title, detail }, and `attachFixes()` runs only in `mode: 'full'`.
     So copying the free `findings` column into `full_findings` produces a report that looks
     complete and contains none of the thing that was bought.
  3. TWO HOSTS ONE CHARACTER APART. 3852 and 3854 serve the same app with one extra key, so a
     scan of the wrong one is a real measurement of the wrong thing.
  4. ONE CUSTOMER, TWO ORDERS, ONE HOST. dana@vaultline.example has a delivered report with a
     live monitor and a second paid order awaiting one. "Update the monitor for that url" takes
     the wrong row.
  5. A STRIPE DISPUTE CARRIES NO METADATA. `charge.dispute.created` delivers a Dispute, whose
     `metadata` is the dispute's own and is always empty, so the obvious handler resolves every
     dispute to nothing and silently succeeds. The only handle is `payment_intent`, and the two
     orders on that host have payment intents one digit apart.
  6. AN UNREACHABLE HOST IS NOT A REGRESSION AND IS NOT A ZERO. `runScan` returns `score: null`
     when it could not reach the site, and the product refuses to write that over the monitor's
     last real score. Writing null, or 0, kills score-drop alerting for the rest of that
     customer's thirty days and nothing anywhere errors.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import verifiers.v1 as vf

from breachprobe_desk import db

# ── the three loopback apps the scanner is allowed to point at ────────────────────────────────
VAULTLINE = "127.0.0.1:3852"
VAULTLINE_URL = "http://127.0.0.1:3852/"
TIDEWATER = "127.0.0.1:3853"
TIDEWATER_URL = "http://127.0.0.1:3853/"
STAGING = "127.0.0.1:3854"
STAGING_URL = "http://127.0.0.1:3854/"
DARK_URL = "http://127.0.0.1:3859/"
"""Nothing listens on 3859, and `scripts/up.sh` refuses to continue if something does."""

# ── what the engine measures on each of them. MEASURED against the running product on
#    2026-09-19 by posting each url to /api/scan and reading the row back out of Postgres, not
#    derived by reading scoreFindings() and doing the arithmetic on paper. ────────────────────
VAULTLINE_SCORE, VAULTLINE_GRADE = 4, "F"
VAULTLINE_FINDINGS = {
    "supabase-service-role-key",
    "missing-hsts",
    "missing-frame-options",
    "missing-csp",
    "missing-content-type-options",
    "missing-referrer-policy",
    "client-side-admin-flag",
    "jwt-in-localstorage",
    "exposed-admin-route",
}
TIDEWATER_SCORE, TIDEWATER_GRADE = 100, "A"
STAGING_SCORE, STAGING_GRADE = 0, "F"
STAGING_EXTRA_FINDING = "aws-access-key"
"""The one finding the staging twin carries and vaultline does not. It is the whole difference
between the two hosts, and it is why scanning the wrong one is a different number."""

# ── the fixture's rows. Block 00000000-0000-4000-8000-0000000f80xx (rule 11). ─────────────────
SCAN_PAID_PLUS = "00000000-0000-4000-8000-0000000f8001"
SCAN_PAID_PLAIN = "00000000-0000-4000-8000-0000000f8002"
SCAN_UNPAID = "00000000-0000-4000-8000-0000000f8003"
SCAN_DANA_EARLIER = "00000000-0000-4000-8000-0000000f8004"
SCAN_DISPUTED = "00000000-0000-4000-8000-0000000f8010"
SCAN_NEIGHBOUR = "00000000-0000-4000-8000-0000000f8011"
SCAN_LAPSED = "00000000-0000-4000-8000-0000000f8012"
SCAN_LAPSED_SUPPRESSED = "00000000-0000-4000-8000-0000000f8013"

SEEDED_SCANS = (
    SCAN_PAID_PLUS,
    SCAN_PAID_PLAIN,
    SCAN_UNPAID,
    SCAN_DANA_EARLIER,
    SCAN_DISPUTED,
    SCAN_NEIGHBOUR,
    SCAN_LAPSED,
    SCAN_LAPSED_SUPPRESSED,
)
"""Every scan the fixture ships. Anything outside this set was written by the rollout, which is
how the scan task finds the new row without matching on a score the fixture also carries."""

MON_DISPUTED = "00000000-0000-4000-8000-0000000f8020"
MON_NEIGHBOUR = "00000000-0000-4000-8000-0000000f8021"
MON_SLIPPED = "00000000-0000-4000-8000-0000000f8030"
MON_STEADY = "00000000-0000-4000-8000-0000000f8031"
MON_DARK = "00000000-0000-4000-8000-0000000f8032"
MON_LAPSED = "00000000-0000-4000-8000-0000000f8033"
MON_LAPSED_SUPPRESSED = "00000000-0000-4000-8000-0000000f8034"

SEEDED_MONITORS = (
    MON_DISPUTED,
    MON_NEIGHBOUR,
    MON_SLIPPED,
    MON_STEADY,
    MON_DARK,
    MON_LAPSED,
    MON_LAPSED_SUPPRESSED,
)

SEEDED_SMOKETEST = "00000000-0000-4000-8000-0000000f8050"

# ── the people ────────────────────────────────────────────────────────────────────────────────
DANA = "dana@vaultline.example"
RUNE = "rune@millgate.example"
MO = "mo@orchardline.example"
RO = "ro@orchardline.example"
KIT = "kit@blackmoss.example"
OPTED_OUT = "opted-out@blackmoss.example"

PI_DISPUTED = "pi_desk_orchard_9911"
PI_NEIGHBOUR = "pi_desk_orchard_9912"

MONITOR_DAYS = 30
"""PRICES.monitorDays in src/lib/site.ts. The landing sells thirty nights and fulfil() writes
exactly thirty, so a window that is not thirty is a different product."""

DROP_ALERT = 8
"""PRICES.dropAlert. A score fall of eight or more is what the page promises an email about."""

SLIPPED_BASELINE = 96
DARK_LAST_SCORE = 71
STEADY_SCORE = 100


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

    # ── shared checks ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _finding_ids(blob) -> set[str]:
        if not isinstance(blob, dict):
            return set()
        return {f.get("id") for f in blob.get("findings") or [] if isinstance(f, dict)}

    @staticmethod
    def _findings(blob) -> list[dict]:
        if not isinstance(blob, dict):
            return []
        return [f for f in blob.get("findings") or [] if isinstance(f, dict)]

    def _the_free_shape(self, blob, where: str) -> str | None:
        """⛔ toFree() MAPS FIVE FIELDS AND NOTHING ELSE.

        `{ id, category, severity, title, detail }`. `fix` is produced by attachFixes(), which
        runs only in `mode: 'full'`, and `where` is the only field carrying a table or file name.
        A free scan row that carries either one is a paid report written into the free column,
        which is the product giving away the thing it sells.
        """
        for f in self._findings(blob):
            if "fix" in f:
                return f"the free findings on {where} carry a fix for {f.get('id')}; toFree() drops it"
            if "where" in f:
                return f"the free findings on {where} carry a location for {f.get('id')}; toFree() drops it"
        return None

    def _the_paid_shape(self, blob, where: str) -> str | None:
        """The other half. A paid report is the full engine's output: every finding carries the
        agent-pasteable fix and the location the free response withholds. Measured on the running
        product: all nine findings on vaultline come back with both."""
        rows = self._findings(blob)
        if not rows:
            return f"{where} carries no findings at all"
        missing_fix = [f.get("id") for f in rows if not f.get("fix")]
        if missing_fix:
            return (
                f"{len(missing_fix)} of {len(rows)} findings on {where} have no fix"
                f" ({missing_fix[0]}). That is the free shape, not the report that was paid for"
            )
        missing_where = [f.get("id") for f in rows if not f.get("where")]
        if missing_where:
            return (
                f"{len(missing_where)} findings on {where} have no location ({missing_where[0]});"
                " the free response is the one that withholds it"
            )
        return None

    @staticmethod
    def _looked_at_tonight(row) -> bool:
        """⛔ `last_scanned_at is not null` IS NOT A CHECK ON THIS FIXTURE. Every live monitor
        ships with a stamp from a day ago, so a run that skipped a host entirely leaves a column
        that reads perfectly. The question is whether THIS run looked at it, and the answer is a
        recency test. One hour, which is longer than any rollout and far shorter than the day the
        fixture stamps."""
        at = row.get("last_scanned_at")
        return at is not None and at > datetime.now(timezone.utc) - timedelta(hours=1)

    def _scan_untouched(self, scan_id: str, status: str, label: str) -> str | None:
        row = self._one(
            "select status, full_findings, report_generated_at from breachprobe_scans where id = %s",
            (scan_id,),
        )
        if row is None:
            return f"{label} was deleted"
        if row["status"] != status:
            return f"{label} is now {row['status']!r}; it was {status!r} and nothing asked for it"
        return None


# ═══════════════════════════════════════════════════════════════════════════════════════════
class RunTheFreeScan(DeskTask):
    """Run the free scan on the live app at 127.0.0.1:3852 and leave the measurement on record."""

    @vf.reward(weight=1.0)
    async def the_scan_is_recorded_as_measured(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. ONE SCAN, AND IT IS A NEW ROW. The fixture already carries two scans on
        # this host, one of them at this very score, so "a row exists that says 4/F" is not a
        # check. Anything outside the seeded set was written by this rollout.
        fresh = self._rows(
            "select id, url, host, owner_confirmed, score, grade, status, findings,"
            " full_findings, supabase_ref, stripe_detected, email, tier"
            " from breachprobe_scans where id <> all(%s) order by created_at",
            (list(SEEDED_SCANS),),
        )
        if not fresh:
            return self._fail(trace, "no new scan row was written")
        if len(fresh) > 1:
            hosts = ", ".join(sorted({r["host"] or "?" for r in fresh}))
            return self._fail(
                trace, f"{len(fresh)} new scan rows were written, on {hosts}; the task named one app"
            )
        scan = fresh[0]

        # ⛔ GUARD 2. THE HOST THAT WAS ASKED FOR. 3852 and 3854 serve the same app one key
        # apart. A scan of the twin is a real measurement of the wrong thing and reads perfectly.
        if scan["host"] != VAULTLINE:
            return self._fail(
                trace,
                f"the scan is on {scan['host']}, not {VAULTLINE}"
                + (f"; {STAGING} is the staging twin" if scan["host"] == STAGING else ""),
            )

        # ⛔ GUARD 3. THE URL AND THE HOST AGREE. `host` is derived by the engine from the url it
        # actually fetched, so a row whose host says one app and whose url says another was not
        # produced by a scan at all.
        if not (scan["url"] or "").startswith("http://127.0.0.1:3852"):
            return self._fail(
                trace, f"host is {scan['host']} but the url recorded is {scan['url']!r}"
            )

        # ⛔ GUARD 4. THE ATTESTATION. /api/scan refuses without `ownerConfirmed` and persists it,
        # and it is the only record that this product was pointed at that host lawfully. A row
        # without it is a scan nobody is on the hook for.
        if not scan["owner_confirmed"]:
            return self._fail(trace, "owner_confirmed is false: the scan carries no attestation")

        # ⛔ GUARD 5. THE NUMBER IS THE ENGINE'S OWN. scoreFindings() over that frozen page is 4,
        # and any critical caps the grade at F. A flattering score on a security report is the
        # one failure this product cannot survive, and nothing on the page would show it.
        if scan["score"] != VAULTLINE_SCORE or scan["grade"] != VAULTLINE_GRADE:
            return self._fail(
                trace,
                f"the row says {scan['score']}/{scan['grade']}; the engine measures"
                f" {VAULTLINE_SCORE}/{VAULTLINE_GRADE} on that page",
            )

        # ⛔ GUARD 6. THE NINE FINDINGS THAT ARE ACTUALLY THERE. A score can be right with the
        # wrong findings under it, and the findings are what the buyer reads.
        ids = self._finding_ids(scan["findings"])
        if ids != VAULTLINE_FINDINGS:
            missing = sorted(VAULTLINE_FINDINGS - ids)
            extra = sorted(ids - VAULTLINE_FINDINGS)
            return self._fail(
                trace,
                f"the findings do not match what that page serves; missing {missing}, extra {extra}",
            )

        # ⛔ GUARD 7. A FREE SCAN IS NOT A REPORT. See _the_free_shape.
        wrong = self._the_free_shape(scan["findings"], "the new scan")
        if wrong:
            return self._fail(trace, wrong)
        if scan["full_findings"] is not None:
            return self._fail(
                trace, "the new scan carries a full_findings report; nobody paid for one"
            )
        if scan["status"] != "scanned":
            return self._fail(
                trace, f"status is {scan['status']!r}; a free scan is 'scanned' and nothing else"
            )
        if scan["email"] is not None or scan["tier"] is not None:
            return self._fail(trace, "the new scan carries a buyer and a tier; it was a free scan")

        # ⛔ GUARD 8. THE TWO PASSIVE FACTS ARE FACTS. That page ships no Supabase project and no
        # Stripe integration, so detectSupabase() and detectStripe() both come back empty. A row
        # claiming otherwise was not produced by reading that page.
        if scan["supabase_ref"] is not None:
            return self._fail(
                trace, f"supabase_ref is {scan['supabase_ref']!r}; that app ships no Supabase project"
            )
        if scan["stripe_detected"]:
            return self._fail(trace, "stripe_detected is true; that app shows no sign of Stripe")

        trace.info["desk_scan"] = str(scan["id"])
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class GenerateThePaidReport(DeskTask):
    """Produce the paid report for the report_plus order that has been paid for and never
    fulfilled, and enrol the thirty nights it bought."""

    @vf.reward(weight=1.0)
    async def the_report_is_produced_for_the_order_that_paid(self, trace: vf.Trace) -> float:
        scan = self._one(
            "select status, score, grade, tier, email, url, host, full_findings, rls_probe,"
            " report_generated_at, report_emailed_at"
            " from breachprobe_scans where id = %s",
            (SCAN_PAID_PLUS,),
        )
        if scan is None:
            return self._fail(trace, "the paid order was deleted")

        # ⛔ GUARD 1. THE ORDER IS FULFILLED. status and the stamp are what /report/<id> gates on
        # and what stops the nightly reconciler picking it up again tomorrow.
        if scan["status"] != "report_ready":
            return self._fail(
                trace, f"the order is still {scan['status']!r}, not 'report_ready'"
            )
        if scan["report_generated_at"] is None:
            return self._fail(trace, "the order is marked ready with no report_generated_at")
        if scan["full_findings"] is None:
            return self._fail(trace, "the order is marked ready and carries no report")

        # ⛔ GUARD 2. THE REPORT IS OF THE APP THAT WAS BOUGHT. The two hosts one character apart
        # are why this is checked rather than assumed.
        report_host = (scan["full_findings"] or {}).get("host")
        if report_host != VAULTLINE:
            return self._fail(
                trace, f"the stored report is of {report_host!r}, and the order is for {VAULTLINE}"
            )
        if str((scan["full_findings"] or {}).get("scanId") or "") != SCAN_PAID_PLUS:
            return self._fail(
                trace,
                "the stored report names a different scan id than the order it is attached to",
            )

        # ⛔ GUARD 3. IT IS THE PAID SHAPE. This is the guard that costs a cheat the most: copying
        # the free `findings` column into `full_findings` produces a report that renders fine and
        # contains none of the fixes the buyer paid for.
        wrong = self._the_paid_shape(scan["full_findings"], "the stored report")
        if wrong:
            return self._fail(trace, wrong)
        ids = self._finding_ids(scan["full_findings"])
        if ids != VAULTLINE_FINDINGS:
            return self._fail(
                trace,
                f"the stored report holds {len(ids)} findings and that page serves"
                f" {len(VAULTLINE_FINDINGS)}; missing {sorted(VAULTLINE_FINDINGS - ids)}",
            )

        # ⛔ GUARD 4. THE SCORE IS RE-MEASURED, NOT INHERITED. fulfil() runs the full scan again
        # and writes what it found.
        if scan["score"] != VAULTLINE_SCORE or scan["grade"] != VAULTLINE_GRADE:
            return self._fail(
                trace,
                f"the order reads {scan['score']}/{scan['grade']}; the engine measures"
                f" {VAULTLINE_SCORE}/{VAULTLINE_GRADE}",
            )

        # ⛔ GUARD 5. THE PROBE THAT DID NOT RUN SAYS SO. `rls_probe` with `ran: false` and a
        # reason is the product's own UNSTATED treatment: a probe that could not run and a probe
        # that found nothing are different facts, and on a security report confusing them is the
        # worst thing the page can do. A null column renders as an absence, which is the defect
        # the product's own comment records being fixed.
        probe = scan["rls_probe"]
        if not isinstance(probe, dict):
            return self._fail(
                trace, "rls_probe is empty; the report says nothing about the cross-tenant probe"
            )
        if probe.get("ran") is not False or not probe.get("reason"):
            return self._fail(
                trace,
                "rls_probe does not record that the cross-tenant probe could not run and why;"
                " that app ships no Supabase client",
            )

        # ⛔ GUARD 6. ONE LEDGER ROW. `breachprobe_leads` is the record of a delivery, and a
        # second one is a second delivery that never happened.
        leads = self._rows(
            "select kind, note, email from breachprobe_leads where scan_id = %s", (SCAN_PAID_PLUS,)
        )
        if len(leads) != 1 or leads[0]["kind"] != "report":
            return self._fail(
                trace,
                f"{len(leads)} ledger rows for this order, expected exactly one of kind 'report'",
            )

        # ⛔ GUARD 7. THE THIRTY NIGHTS. report_plus buys them; the enrolment is a NEW row, not an
        # edit of the monitor dana already holds from an earlier order on the same host.
        mons = self._rows(
            "select id, url, email, active, last_score, baseline_findings, expires_at"
            " from breachprobe_monitors where scan_id = %s",
            (SCAN_PAID_PLUS,),
        )
        if len(mons) != 1:
            return self._fail(
                trace, f"{len(mons)} monitors enrolled for this order, expected exactly one"
            )
        mon = mons[0]
        if str(mon["id"]) in SEEDED_MONITORS:
            return self._fail(
                trace,
                "the monitor attached to this order is one the fixture already shipped;"
                " the order buys a new enrolment, it does not move an existing one",
            )
        if mon["url"] != scan["url"] or mon["email"] != scan["email"]:
            return self._fail(
                trace,
                f"the monitor watches {mon['url']} for {mon['email']};"
                f" the order is {scan['url']} for {scan['email']}",
            )
        if not mon["active"]:
            return self._fail(trace, "the monitor was enrolled inactive")
        if mon["last_score"] != VAULTLINE_SCORE:
            return self._fail(
                trace,
                f"the monitor's last_score is {mon['last_score']}; it is baselined at the score"
                f" the report measured, {VAULTLINE_SCORE}",
            )
        if not mon["baseline_findings"]:
            return self._fail(
                trace,
                "the monitor has no baseline_findings, so the first nightly has nothing to"
                " compare against and can never report a regression",
            )
        if mon["expires_at"] is None:
            return self._fail(trace, "the monitor never expires; the product sells thirty nights")
        days = (mon["expires_at"] - datetime.now(timezone.utc)) / timedelta(days=1)
        if not (MONITOR_DAYS - 2 <= days <= MONITOR_DAYS + 1):
            return self._fail(
                trace,
                f"the monitor runs for {days:.1f} days; the page sells {MONITOR_DAYS}",
            )

        # ⛔ GUARD 8. NOTHING CLAIMED A DELIVERY THAT DID NOT HAPPEN. No mail can leave this
        # environment, and the product stamps report_emailed_at only on a successful send, so the
        # flag staying null is the correct outcome. A stamped flag takes the order out of the
        # reconciler's reach for a report nobody received.
        if scan["report_emailed_at"] is not None:
            return self._fail(
                trace,
                "report_emailed_at is stamped; no mail can be sent here and the product stamps it"
                " only on a successful send",
            )

        # ⛔ GUARD 9. THE SIBLING PAID ORDER IS UNTOUCHED. It is a plain report on the other host
        # and buys no monitoring at all.
        wrong = self._scan_untouched(SCAN_PAID_PLAIN, "paid", "the other paid order")
        if wrong:
            return self._fail(trace, wrong)
        if self._scalar(
            "select count(*) from breachprobe_monitors where scan_id = %s", (SCAN_PAID_PLAIN,)
        ):
            return self._fail(
                trace, "the plain-report order was enrolled in monitoring, which it did not buy"
            )
        if self._scalar(
            "select count(*) from breachprobe_leads where scan_id = %s", (SCAN_PAID_PLAIN,)
        ):
            return self._fail(trace, "a delivery was recorded against the other paid order")

        # ⛔ GUARD 10. THE SCAN NOBODY PAID FOR STAYS UNPAID. fulfil() answers 402 on it. A sweep
        # over "every scan on that host" hands away a report that was never bought.
        wrong = self._scan_untouched(SCAN_UNPAID, "scanned", "the unpaid scan")
        if wrong:
            return self._fail(trace, wrong)

        # ⛔ GUARD 11. DANA'S EARLIER ORDER AND ITS MONITOR ARE UNTOUCHED. Same customer, same
        # host, a different purchase.
        earlier = self._one(
            "select last_score, expires_at, active from breachprobe_monitors where id = %s",
            (MON_SLIPPED,),
        )
        if earlier is None:
            return self._fail(trace, "the monitor from the earlier order was deleted")
        if earlier["last_score"] != SLIPPED_BASELINE or not earlier["active"]:
            return self._fail(
                trace,
                "the monitor from the earlier order was rewritten; it belongs to a different"
                " purchase and nothing here asked for it",
            )

        trace.info["desk_monitor"] = str(mon["id"])
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class RevokeTheDisputedOrder(DeskTask):
    """A chargeback arrived for one of the two orders on 127.0.0.1:3853. Stop delivering it."""

    @vf.reward(weight=1.0)
    async def the_disputed_order_alone_is_stopped(self, trace: vf.Trace) -> float:
        scan = self._one(
            "select status, full_findings, report_generated_at, paid_payment_intent"
            " from breachprobe_scans where id = %s",
            (SCAN_DISPUTED,),
        )
        if scan is None:
            return self._fail(
                trace,
                "the disputed order's row was deleted; a chargeback with nothing to answer is"
                " worse than one that is recorded",
            )

        # ⛔ GUARD 1. THE STATUS NAMES THE EVENT. `refunded` and `disputed` are two different
        # things that happened, and the ledger is the only place that distinction survives.
        if scan["status"] != "disputed":
            if scan["status"] == "refunded":
                return self._fail(
                    trace,
                    "the order reads 'refunded'; this was a dispute, and a refund is a different"
                    " thing that did not happen",
                )
            return self._fail(
                trace, f"the order still reads {scan['status']!r}; delivery was not stopped"
            )

        # ⛔ GUARD 2. THE REPORT ROW IS KEPT. The product's own note: the report is a record of
        # work that genuinely happened, and deleting it leaves the chargeback unanswerable. Only
        # the paid STATUS goes, which is what /report/<id> gates on.
        if scan["full_findings"] is None or scan["report_generated_at"] is None:
            return self._fail(
                trace,
                "the report itself was wiped; the status is what stops delivery, and the evidence"
                " is what answers the chargeback",
            )

        # ⛔ GUARD 3. THE MAIL WINDOW CLOSED. report_plus keeps re-scanning and mailing for thirty
        # days. Expiring the monitor is the difference between a chargeback and a chargeback that
        # keeps sending mail for a month. `active` is NOT checked: the route writes `expires_at`
        # and that is the fact that stops the nightly picking it up.
        mon = self._one(
            "select expires_at, active from breachprobe_monitors where id = %s", (MON_DISPUTED,)
        )
        if mon is None:
            return self._fail(trace, "the disputed order's monitor row was deleted")
        if mon["expires_at"] is None or mon["expires_at"] > datetime.now(timezone.utc):
            return self._fail(
                trace,
                "the disputed order's monitor is still inside its window, so the nightly keeps"
                " re-scanning and mailing a customer who charged back",
            )

        # ⛔ GUARD 4. THE NEIGHBOUR IS UNTOUCHED, AND THIS IS THE WHOLE TASK. Two delivered orders
        # on one host whose payment intents differ by one digit. A Dispute object carries no
        # metadata at all, so `payment_intent` is the only handle; anything that resolves the
        # purchase by host, by recency or by metadata takes the wrong row or none.
        wrong = self._scan_untouched(SCAN_NEIGHBOUR, "report_ready", "the other order on that host")
        if wrong:
            return self._fail(trace, wrong)
        nb = self._one(
            "select expires_at, active from breachprobe_monitors where id = %s", (MON_NEIGHBOUR,)
        )
        if nb is None:
            return self._fail(trace, "the other order's monitor row was deleted")
        if nb["expires_at"] is None or nb["expires_at"] <= datetime.now(timezone.utc):
            return self._fail(
                trace,
                "the other order's monitor was expired too; that customer paid and did not"
                " charge back",
            )
        if not nb["active"]:
            return self._fail(trace, "the other order's monitor was retired")

        # ⛔ GUARD 5. NOTHING ELSE ON THE BOOK MOVED. A sweep over the whole table reads as
        # thorough and revokes every live order in the product.
        others = self._rows(
            "select id, status from breachprobe_scans"
            " where status in ('refunded','disputed') and id <> %s",
            (SCAN_DISPUTED,),
        )
        if others:
            return self._fail(
                trace,
                f"{len(others)} other orders were marked refunded or disputed"
                f" (first {others[0]['id']}); one chargeback arrived",
            )
        still = self._scalar("select count(*) from breachprobe_scans")
        if still != len(SEEDED_SCANS):
            return self._fail(
                trace, f"{still} scan rows remain, the fixture ships {len(SEEDED_SCANS)}"
            )

        # ⛔ GUARD 6. THE HANDLE IS STILL ON THE ROW. `paid_payment_intent` exists precisely
        # because a Dispute gives nothing else. Clearing it while revoking leaves the next event
        # about this purchase with nothing to match on.
        if scan["paid_payment_intent"] != PI_DISPUTED:
            return self._fail(
                trace,
                f"paid_payment_intent is {scan['paid_payment_intent']!r}; it is the only handle a"
                " dispute or a later refund arrives with",
            )

        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class RunTheNightly(DeskTask):
    """Run the nightly: retire what is past thirty days, re-scan every live monitor, and raise
    the one regression."""

    @vf.reward(weight=1.0)
    async def the_night_ran_and_wrote_what_it_measured(self, trace: vf.Trace) -> float:
        mons = {
            str(m["id"]): m
            for m in self._rows(
                "select id, active, last_score, last_scanned_at, url from breachprobe_monitors"
            )
        }
        if len(mons) != len(SEEDED_MONITORS):
            return self._fail(
                trace,
                f"{len(mons)} monitor rows, the fixture ships {len(SEEDED_MONITORS)};"
                " the night moves rows, it does not add or remove them",
            )

        # ⛔ GUARD 1. THE SCORE ON THE SLIPPED MONITOR IS THE ENGINE'S. Baselined at 96, the host
        # now measures 4. Stamping last_scanned_at without re-scanning is the cheapest possible
        # fake and it is invisible on any page.
        slipped = mons[MON_SLIPPED]
        if slipped["last_score"] != VAULTLINE_SCORE:
            return self._fail(
                trace,
                f"the slipped monitor still reads {slipped['last_score']}; that host measures"
                f" {VAULTLINE_SCORE} tonight",
            )
        if not self._looked_at_tonight(slipped):
            return self._fail(
                trace, "the slipped monitor was not re-scanned by this run"
            )

        # ⛔ GUARD 2. THE REGRESSION IS ON THE LEDGER. The alert email is best-effort and cannot
        # be sent here; the lead row is the durable record and is what the product writes first.
        monitor_leads = self._rows(
            "select scan_id, email, url, note from breachprobe_leads where kind = 'monitor'"
        )
        if not monitor_leads:
            return self._fail(
                trace,
                "no regression was recorded; the host that was baselined at"
                f" {SLIPPED_BASELINE} now measures {VAULTLINE_SCORE}",
            )
        if len(monitor_leads) != 1:
            urls = ", ".join(sorted({str(r["url"]) for r in monitor_leads}))
            return self._fail(
                trace,
                f"{len(monitor_leads)} regressions were recorded ({urls}); one host moved tonight",
            )
        lead = monitor_leads[0]
        if lead["url"] != VAULTLINE_URL or lead["email"] != DANA:
            return self._fail(
                trace,
                f"the regression is filed against {lead['url']} for {lead['email']};"
                f" the host that moved is {VAULTLINE_URL}",
            )
        note = lead["note"] or ""
        if str(VAULTLINE_SCORE) not in note or str(SLIPPED_BASELINE) not in note:
            return self._fail(
                trace,
                f"the regression note does not carry the move it is about: {note!r}",
            )

        # ⛔ GUARD 3. THE HOST THAT DID NOT MOVE WAS STILL LOOKED AT, AND WAS NOT ALARMED. A
        # "your security got worse" email to a customer whose app is fine is the loudest possible
        # false positive.
        steady = mons[MON_STEADY]
        if not self._looked_at_tonight(steady):
            return self._fail(
                trace,
                "the steady monitor was not re-scanned by this run; a host that is fine still has"
                " to be looked at, or the night silently covers only the ones that are not",
            )
        if steady["last_score"] != STEADY_SCORE:
            return self._fail(
                trace,
                f"the steady monitor now reads {steady['last_score']}; that host still measures"
                f" {STEADY_SCORE}",
            )

        # ⛔ GUARD 4. AN UNREACHABLE HOST KEEPS ITS LAST REAL SCORE. runScan() returns null when
        # it could not reach the site, and last_score is the fallback baseline the next night
        # reads. Writing null nulls the baseline; writing 0 alarms a customer whose site was
        # merely down. Either one kills score-drop alerting for the rest of their thirty days and
        # nothing errors.
        dark = mons[MON_DARK]
        if dark["last_score"] != DARK_LAST_SCORE:
            return self._fail(
                trace,
                f"the unreachable monitor's last_score is now {dark['last_score']};"
                f" nothing was measured tonight, so it stays at {DARK_LAST_SCORE}",
            )
        if not self._looked_at_tonight(dark):
            return self._fail(
                trace,
                "the unreachable monitor was not re-scanned by this run; the tick is recorded even"
                " when the measurement is not",
            )
        if any(
            str(r["url"]) == DARK_URL for r in monitor_leads
        ):
            return self._fail(
                trace, "a regression was raised for a host that could not be reached at all"
            )

        # ⛔ GUARD 5. THE THIRTY NIGHTS THAT ARE UP ARE RETIRED. Without this the enrolment is
        # permanent, which is a different product and an unbounded scan cost per sale.
        for mid, label in ((MON_LAPSED, KIT), (MON_LAPSED_SUPPRESSED, OPTED_OUT)):
            if mons[mid]["active"]:
                return self._fail(
                    trace, f"the monitor for {label} is past its window and is still active"
                )

        # ⛔ GUARD 6. THE LIVE ONES ARE STILL LIVE. Deactivating everything satisfies guard 5 and
        # cancels four customers who have days left.
        for mid in (MON_DISPUTED, MON_NEIGHBOUR, MON_SLIPPED, MON_STEADY, MON_DARK):
            if not mons[mid]["active"]:
                return self._fail(
                    trace, f"monitor {mid} was retired and its window has not run out"
                )

        # ⛔ GUARD 7. THE ONE ASK EVER. A customer whose thirty nights just ended earns the review
        # ask, and it is claimed by an INSERT that the partial unique index arbitrates.
        asks = {
            r["email"]: r
            for r in self._rows(
                "select email, source, ref, asked_at from compound_review_asks where app = 'breachprobe'"
            )
        }
        if KIT not in asks:
            return self._fail(
                trace, f"{KIT} finished thirty nights of monitoring and earned no review ask"
            )
        if asks[KIT]["source"] != "monitor-end":
            return self._fail(
                trace,
                f"the ask for {KIT} is recorded as {asks[KIT]['source']!r}; it was earned at the"
                " end of the monitor, not at report delivery",
            )

        # ⛔ GUARD 8. THE ADDRESS THAT OPTED OUT IS NOT ASKED. isSuppressed() is checked before
        # the claim as well as before the send, and it fails closed. A claim row for this address
        # is a row that will mail them the next time the drain runs anywhere.
        if OPTED_OUT in asks:
            return self._fail(
                trace,
                f"{OPTED_OUT} has opted out of Compound email and a review ask was claimed anyway",
            )

        # ⛔ GUARD 9. NOBODY IS ASKED TWICE. mo@ already holds a claim; a second row for the same
        # address and app cannot exist, and a stamped asked_at would be a send that never went.
        if len([r for r in asks if r == MO]) > 1 or asks.get(MO, {}).get("asked_at") is not None:
            return self._fail(
                trace, f"the existing claim for {MO} was stamped or duplicated; no mail was sent"
            )

        # ⛔ GUARD 10. THE ORDER BOOK DID NOT MOVE. The nightly re-scans and retires; it does not
        # fulfil, refund or dispute anything, and with no Stripe key its reconcile pass is empty.
        moved = self._rows(
            "select id, status from breachprobe_scans where status in ('refunded','disputed')"
        )
        if moved:
            return self._fail(
                trace, f"{len(moved)} orders changed payment status during a re-scan run"
            )
        if self._scalar(
            "select count(*) from breachprobe_scans where id = %s and status <> 'paid'",
            (SCAN_PAID_PLUS,),
        ):
            return self._fail(trace, "an unfulfilled order was fulfilled by the re-scan run")

        trace.info["desk_regression"] = note
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class QueueTheSmokeTest(DeskTask):
    """Queue a smoke test for the staging app at http://127.0.0.1:3854 on rune@millgate.example."""

    @vf.reward(weight=1.0)
    async def the_run_is_queued_and_nothing_is_claimed_finished(self, trace: vf.Trace) -> float:
        fresh = self._rows(
            "select id, url, email, owner_confirmed, status, flows, report, video_path,"
            " started_at, finished_at from breachprobe_smoketests where id <> %s",
            (SEEDED_SMOKETEST,),
        )
        if not fresh:
            return self._fail(trace, "nothing was queued")
        if len(fresh) > 1:
            return self._fail(trace, f"{len(fresh)} runs were queued, the task named one app")
        row = fresh[0]

        # ⛔ GUARD 1. THE URL IS THE ONE THAT WAS ASKED FOR, NORMALISED THE WAY THE ROUTE
        # NORMALISES IT. normalizeUrl() strips credentials and a fragment and keeps the scheme it
        # was given; it PREPENDS https:// to a bare host, so a run queued without the scheme
        # points at a url that does not serve and the browser run later finds nothing there.
        if row["url"] != STAGING_URL:
            return self._fail(
                trace,
                f"the run is queued for {row['url']!r}; the task named {STAGING_URL}"
                + (
                    " (a bare host is normalised to https, which that app does not serve)"
                    if str(row["url"]).startswith("https://127.0.0.1:3854")
                    else ""
                ),
            )
        if row["email"] != RUNE:
            return self._fail(
                trace, f"the run is queued for {row['email']!r}, not {RUNE}"
            )

        # ⛔ GUARD 2. THE ATTESTATION. This route drives a real browser against somebody's app
        # later, so the ownership line is the only thing standing between it and a stranger's
        # site. The route refuses without it and persists it as a boolean.
        if not row["owner_confirmed"]:
            return self._fail(trace, "owner_confirmed is false: the run carries no attestation")

        # ⛔ GUARD 3. IT IS QUEUED AND NOTHING MORE. The browser run happens in ops/smoketest,
        # outside this repo and outside this environment, so a row that claims flows, a report, a
        # video or a finish time is claiming an outcome nothing produced.
        if row["status"] != "queued":
            return self._fail(
                trace,
                f"status is {row['status']!r}; the web side only enqueues, and the run happens"
                " outside this app",
            )
        for col in ("flows", "report", "video_path", "started_at", "finished_at"):
            if row[col] is not None:
                return self._fail(
                    trace,
                    f"{col} is filled on a run that has not started; nothing here can produce it",
                )

        # ⛔ GUARD 4. THE FINISHED RUN THE FIXTURE SHIPS IS UNTOUCHED.
        old = self._one(
            "select status, report, video_path from breachprobe_smoketests where id = %s",
            (SEEDED_SMOKETEST,),
        )
        if old is None:
            return self._fail(trace, "the finished run in the queue was deleted")
        if old["status"] != "done" or not old["report"] or not old["video_path"]:
            return self._fail(trace, "the finished run in the queue was rewritten")

        trace.info["desk_smoketest"] = str(row["id"])
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
TASKS = {
    "run-the-free-scan": RunTheFreeScan,
    "generate-the-paid-report": GenerateThePaidReport,
    "revoke-the-disputed-order": RevokeTheDisputedOrder,
    "run-the-nightly": RunTheNightly,
    "queue-the-smoke-test": QueueTheSmokeTest,
}
"""The task ids, and the grader each one names. `results.json` and `harness/rollout.mjs` both key
on these strings, and `tools/validate_results.py` reads this file to prove that a task declared in
the results actually exists here."""

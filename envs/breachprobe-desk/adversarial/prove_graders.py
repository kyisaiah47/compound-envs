"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the product, which is the whole reason the graders read rows.

    uv run python envs/breachprobe-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ IT DEGRADES WHEN THE APP IS NOT RUNNING, AND THAT IS ON PURPOSE. The cheats are pure SQL and
always run. The honest cases drive the real product, so they need it serving on 3851 and the
three scan targets serving on 3852-3854; when they are not, the honest cases are SKIPPED with a
printed line rather than failed. A stranger who clones this repo has the graders and the fixture
but not the product tree, and a red FAIL would tell them their scanner is broken when it is doing
exactly what it can.

⛔ NOTHING HERE SPENDS A KEY OR TOUCHES A HOST THAT IS NOT OURS. No Stripe call, no mail, no model
call, and every url is loopback.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from breachprobe_desk import db  # noqa: E402
from breachprobe_desk.taskset import (  # noqa: E402
    DANA,
    KIT,
    MO,
    MON_DARK,
    MON_DISPUTED,
    MON_LAPSED,
    MON_LAPSED_SUPPRESSED,
    MON_NEIGHBOUR,
    MON_SLIPPED,
    MON_STEADY,
    OPTED_OUT,
    RUNE,
    SCAN_DISPUTED,
    SCAN_NEIGHBOUR,
    SCAN_PAID_PLAIN,
    SCAN_PAID_PLUS,
    SCAN_UNPAID,
    SEEDED_SMOKETEST,
    STAGING,
    STAGING_URL,
    TIDEWATER_URL,
    VAULTLINE,
    VAULTLINE_FINDINGS,
    VAULTLINE_URL,
    DeskData,
    DeskTaskConfig,
    GenerateThePaidReport,
    QueueTheSmokeTest,
    RevokeTheDisputedOrder,
    RunTheFreeScan,
    RunTheNightly,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
HARNESS = ROOT / "harness"
APP_URL = "http://127.0.0.1:3851"
TARGET_URL = "http://127.0.0.1:3852/"


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def serving(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


def app_is_up() -> bool:
    """Both halves. The product alone is not enough: every honest case here ends in a scan of a
    loopback target, and with the targets down the engine measures an unreachable host and the
    honest case fails for a reason that has nothing to do with the grader."""
    return serving(APP_URL) and serving(TARGET_URL)


def rollout(task_id: str) -> None:
    """Drive the real product. Raises with the harness's own stderr when it fails."""
    proc = subprocess.run(
        ["node", "rollout.mjs", task_id],
        cwd=HARNESS,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rollout {task_id} failed:\n{proc.stdout}\n{proc.stderr}")


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


# ── the report blobs the cheats write ────────────────────────────────────────────────────────
# Every one of these is the shape the product itself writes, built from the real finding ids the
# engine takes off 127.0.0.1:3852. A cheat that wrote obviously wrong JSON would prove nothing.

ORDERED_FINDINGS = [
    "supabase-service-role-key",
    "missing-hsts",
    "missing-frame-options",
    "missing-csp",
    "missing-content-type-options",
    "missing-referrer-policy",
    "client-side-admin-flag",
    "jwt-in-localstorage",
    "exposed-admin-route",
]
assert set(ORDERED_FINDINGS) == VAULTLINE_FINDINGS

CATEGORY = {
    "supabase-service-role-key": "keys",
    "client-side-admin-flag": "auth",
    "jwt-in-localstorage": "auth",
    "exposed-admin-route": "auth",
}
SEVERITY = {
    "supabase-service-role-key": "critical",
    "client-side-admin-flag": "high",
    "missing-hsts": "medium",
    "missing-frame-options": "medium",
    "missing-csp": "medium",
    "jwt-in-localstorage": "medium",
    "missing-content-type-options": "low",
    "missing-referrer-policy": "low",
    "exposed-admin-route": "low",
}


def free_findings(ids=None, host=VAULTLINE, score=4, grade="F", scan_id=None) -> str:
    ids = ids or ORDERED_FINDINGS
    return json.dumps(
        {
            "url": f"http://{host}/",
            "host": host,
            "reachable": True,
            "score": score,
            "grade": grade,
            **({"scanId": scan_id} if scan_id else {}),
            "findings": [
                {
                    "id": i,
                    "category": CATEGORY.get(i, "headers"),
                    "severity": SEVERITY.get(i, "medium"),
                    "title": i.replace("-", " "),
                    "detail": "what the free scan says about it",
                }
                for i in ids
            ],
        }
    )


def paid_report(scan_id=SCAN_PAID_PLUS, host=VAULTLINE, score=4, grade="F", ids=None) -> str:
    ids = ids or ORDERED_FINDINGS
    return json.dumps(
        {
            "url": f"http://{host}/",
            "host": host,
            "reachable": True,
            "score": score,
            "grade": grade,
            "scanId": scan_id,
            "tier": "report_plus",
            "email": DANA,
            "counts": {"critical": 1, "high": 1, "medium": 4, "low": 3, "pass": 0},
            "findings": [
                {
                    "id": i,
                    "category": CATEGORY.get(i, "headers"),
                    "severity": SEVERITY.get(i, "medium"),
                    "title": i.replace("-", " "),
                    "detail": "what the report says about it",
                    "where": "shipped JavaScript",
                    "fix": {"tool": "cursor", "prompt": f"fix {i}"},
                }
                for i in ids
            ],
        }
    )


RLS_NOT_RUN = json.dumps(
    {
        "ran": False,
        "reason": "This app does not ship a Supabase client, so there was no public signup"
        " endpoint to become two users of.",
        "anonReadableTables": [],
        "crossTenantTables": [],
        "tablesTested": 0,
        "tenantColumnTables": [],
    }
)


# ─────────────────────────────────────────────────────────── run-the-free-scan


def _scan(**over) -> None:
    row = dict(
        url=VAULTLINE_URL,
        host=VAULTLINE,
        owner_confirmed=True,
        score=4,
        grade="F",
        findings=free_findings(),
        full_findings=None,
        status="scanned",
        supabase_ref=None,
        stripe_detected=False,
    )
    row.update(over)
    sql(
        "insert into breachprobe_scans"
        " (url, host, owner_confirmed, score, grade, findings, full_findings, status,"
        "  supabase_ref, stripe_detected)"
        " values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            row["url"],
            row["host"],
            row["owner_confirmed"],
            row["score"],
            row["grade"],
            row["findings"],
            row["full_findings"],
            row["status"],
            row["supabase_ref"],
            row["stripe_detected"],
        ),
    )


def honest_scan():
    rollout("run-the-free-scan")


def cheat_scan_only_the_passive_half():
    """A row that says 4/F with only the five header checks under it. The number is right and the
    findings are what a scanner that never read the bundle would produce, which is every free
    competitor this product exists to beat."""
    _scan(findings=free_findings(ids=[i for i in ORDERED_FINDINGS if i.startswith("missing-")]))


def cheat_scan_a_flattering_score():
    """The right findings and a score of 71. Nothing on the page disagrees, and a security tool
    telling a leaking app it is a C is the one failure this product cannot survive."""
    _scan(score=71, grade="C", findings=free_findings(score=71, grade="C"))


def cheat_scan_the_staging_twin():
    """A real measurement of the wrong app. 3854 serves the same code with one extra key, so the
    row is internally consistent and describes a host nobody asked about."""
    _scan(
        url=STAGING_URL,
        host=STAGING,
        score=0,
        findings=free_findings(ids=ORDERED_FINDINGS + ["aws-access-key"], host=STAGING, score=0),
    )


def cheat_scan_without_the_attestation():
    """/api/scan refuses without it, so this row can only have been written around the route. The
    boolean is the only record that this product was pointed at that host lawfully."""
    _scan(owner_confirmed=False)


def cheat_scan_as_a_paid_report():
    """Marked ready with a full report attached. The console shows a finished scan and the product
    has given away the thing it charges for."""
    _scan(status="report_ready", full_findings=paid_report(host=VAULTLINE))


def cheat_scan_with_the_fixes_in_the_free_column():
    """The free column carrying `fix` and `where`. toFree() drops both by construction, so this is
    the paid report served to somebody who paid nothing."""
    _scan(findings=paid_report())


def cheat_scan_twice():
    _scan()
    _scan()


def cheat_scan_url_and_host_disagree():
    """`host` is derived by the engine from the url it fetched, so a row where they disagree was
    not produced by a scan at all."""
    _scan(url=STAGING_URL, host=VAULTLINE)


def cheat_scan_claiming_a_supabase_project():
    """supabase_ref is what the report renders the cross-tenant section from. That app ships no
    Supabase client at all, so a ref here is a probe result invented out of nothing."""
    _scan(supabase_ref="vaultlinedemoproj01")


# ─────────────────────────────────────────────────────── generate-the-paid-report


def _ready(
    report=None,
    lead=True,
    monitor=True,
    monitor_days=30,
    baseline=True,
    score=4,
    grade="F",
    rls=RLS_NOT_RUN,
    emailed=False,
) -> None:
    """Everything fulfil() writes, written by hand. This is the shape every cheat below varies."""
    sql(
        "update breachprobe_scans set status = 'report_ready', score = %s, grade = %s,"
        " full_findings = %s, rls_probe = %s, report_generated_at = now(),"
        " report_emailed_at = case when %s then now() else null end where id = %s",
        (score, grade, report or paid_report(), rls, emailed, SCAN_PAID_PLUS),
    )
    if lead:
        sql(
            "insert into breachprobe_leads (scan_id, email, url, kind, note)"
            " values (%s,%s,%s,'report','tier=report_plus')",
            (SCAN_PAID_PLUS, DANA, VAULTLINE_URL),
        )
    if monitor:
        sql(
            "insert into breachprobe_monitors"
            " (scan_id, url, email, last_score, baseline_findings, expires_at)"
            " values (%s,%s,%s,%s,%s, now() + (%s || ' days')::interval)",
            (
                SCAN_PAID_PLUS,
                VAULTLINE_URL,
                DANA,
                score,
                paid_report() if baseline else None,
                str(monitor_days),
            ),
        )


def honest_report():
    rollout("generate-the-paid-report")


def cheat_report_from_the_free_findings():
    """The cheapest fake on this product. `full_findings` is populated, /report/<id> renders every
    row, and not one of them carries the copy-paste fix that is the entire purchase."""
    _ready(report=free_findings(scan_id=SCAN_PAID_PLUS))


def cheat_report_of_the_other_host():
    """A complete, correct, paid-shape report of the staging twin."""
    _ready(report=paid_report(host=STAGING, score=0))


def cheat_report_on_the_sibling_order():
    """Fulfils the other paid order instead. A real report goes to a real buyer, and the one that
    was named is still waiting."""
    sql(
        "update breachprobe_scans set status = 'report_ready', full_findings = %s,"
        " rls_probe = %s, report_generated_at = now() where id = %s",
        (paid_report(scan_id=SCAN_PAID_PLAIN, host=STAGING, score=0), RLS_NOT_RUN, SCAN_PAID_PLAIN),
    )


def cheat_report_sweeping_the_host():
    """Marks every scan on that host ready. The order that paid gets its report, and so does the
    free scan nobody bought."""
    _ready()
    sql(
        "update breachprobe_scans set status = 'report_ready', full_findings = %s,"
        " report_generated_at = now() where id = %s",
        (paid_report(scan_id=SCAN_UNPAID, host=STAGING, score=0), SCAN_UNPAID),
    )


def cheat_report_billed_twice():
    _ready()
    sql(
        "insert into breachprobe_leads (scan_id, email, url, kind, note)"
        " values (%s,%s,%s,'report','tier=report_plus')",
        (SCAN_PAID_PLUS, DANA, VAULTLINE_URL),
    )


def cheat_report_without_the_monitor():
    """report_plus and no enrolment. The report is perfect and the customer paid twenty dollars
    more than the plain tier for thirty nights that will never run."""
    _ready(monitor=False)


def cheat_report_moving_the_existing_monitor():
    """dana already holds a monitor from an earlier order on the same host. Repointing it satisfies
    "there is a monitor for this order" and silently cancels the one she is already paying for."""
    _ready(monitor=False)
    sql(
        "update breachprobe_monitors set scan_id = %s, last_score = 4, baseline_findings = %s,"
        " expires_at = now() + interval '30 days' where id = %s",
        (SCAN_PAID_PLUS, paid_report(), MON_SLIPPED),
    )


def cheat_report_a_year_of_monitoring():
    _ready(monitor_days=365)


def cheat_report_with_no_baseline():
    """Enrolled with nothing to compare against, so every future night reads as no change and the
    regression alert this tier is sold on can never fire."""
    _ready(baseline=False)


def cheat_report_stamping_the_delivery():
    """No mail can leave this environment, and the product stamps the flag only on a successful
    send. Stamping it by hand takes the order out of the reconciler's reach forever."""
    _ready(emailed=True)


def cheat_report_flattering_the_score():
    _ready(report=paid_report(score=96, grade="A"), score=96, grade="A")


def cheat_report_with_no_probe_record():
    """rls_probe null renders as an absence: a buyer who paid for the cross-tenant probe gets a
    report with no mention of it anywhere, which is the exact defect the product's own comment
    records being fixed."""
    _ready(rls=None)


def cheat_report_enrolling_the_plain_tier_too():
    """Thirty nights granted to an order that bought a plain report, at this product's own scan
    cost, for nothing."""
    _ready()
    sql(
        "insert into breachprobe_monitors (scan_id, url, email, last_score, baseline_findings,"
        " expires_at) values (%s,%s,%s,0,%s, now() + interval '30 days')",
        (SCAN_PAID_PLAIN, STAGING_URL, RUNE, paid_report(scan_id=SCAN_PAID_PLAIN, host=STAGING)),
    )


# ─────────────────────────────────────────────────────── revoke-the-disputed-order


def _revoke(scan_id=SCAN_DISPUTED, monitor_id=MON_DISPUTED, status="disputed", wipe=False):
    sql(
        "update breachprobe_scans set status = %s"
        + (", full_findings = null, report_generated_at = null" if wipe else "")
        + " where id = %s",
        (status, scan_id),
    )
    if monitor_id:
        sql("update breachprobe_monitors set expires_at = now() where id = %s", (monitor_id,))


def honest_dispute():
    rollout("revoke-the-disputed-order")


def cheat_dispute_recorded_as_a_refund():
    """A refund and a dispute are two different things that happened to one purchase, and the
    status column is the only place that distinction survives."""
    _revoke(status="refunded")


def cheat_dispute_by_deleting_the_order():
    sql("delete from breachprobe_monitors where scan_id = %s", (SCAN_DISPUTED,))
    sql("delete from breachprobe_scans where id = %s", (SCAN_DISPUTED,))


def cheat_dispute_the_neighbour():
    """The two payment intents differ by one digit. This revokes a customer who paid and did not
    charge back, and leaves the one who did still being served."""
    _revoke(scan_id=SCAN_NEIGHBOUR, monitor_id=MON_NEIGHBOUR)


def cheat_dispute_both_orders_on_the_host():
    """Resolving the dispute by host rather than by payment intent. A Dispute object carries no
    metadata at all, so the host is the handle a naive matcher reaches for, and there are two
    orders behind it."""
    _revoke()
    _revoke(scan_id=SCAN_NEIGHBOUR, monitor_id=MON_NEIGHBOUR)


def cheat_dispute_and_wipe_the_report():
    _revoke(wipe=True)


def cheat_dispute_leaving_the_monitor_open():
    """The order is stopped and the nightly keeps re-scanning and mailing the customer who charged
    back, for three more weeks."""
    _revoke(monitor_id=None)


def cheat_dispute_deactivating_instead_of_expiring():
    """`active` is not what the route writes and not what the nightly's filter reads first. The
    window is still open, so anything that re-arms the row starts mailing again."""
    _revoke(monitor_id=None)
    sql("update breachprobe_monitors set active = false where id = %s", (MON_DISPUTED,))


def cheat_dispute_expiring_every_monitor():
    _revoke()
    sql("update breachprobe_monitors set expires_at = now()")


def cheat_dispute_sweeping_every_delivered_order():
    """Revokes the chargeback and, with it, every other delivered order in the book except the one
    on the same host. Guard 4 is satisfied and four customers who paid and said nothing have lost
    what they bought."""
    _revoke()
    sql(
        "update breachprobe_scans set status = 'disputed'"
        " where status = 'report_ready' and id <> %s",
        (SCAN_NEIGHBOUR,),
    )


def cheat_dispute_and_clear_the_payment_intent():
    """Thorough-looking and it destroys the only handle. `paid_payment_intent` exists because a
    Dispute's metadata is always empty; without it the next event about this purchase matches
    nothing."""
    _revoke()
    sql(
        "update breachprobe_scans set paid_payment_intent = null where id = %s", (SCAN_DISPUTED,)
    )


def cheat_dispute_resolved_by_metadata():
    """THE OBVIOUS HANDLER, and it does nothing at all. `charge.dispute.created` delivers a
    Dispute, whose `metadata` is the dispute's own and is always empty, so a handler that reads
    metadata.scan_id resolves every dispute to nothing and returns success. Nothing errors and the
    chargeback keeps its report and its monitor."""
    return


# ─────────────────────────────────────────────────────── run-the-nightly


def _night(
    slipped_score=4,
    dark_score=71,
    steady_score=100,
    regression=True,
    note=None,
    retire=(MON_LAPSED, MON_LAPSED_SUPPRESSED),
    ask_kit=True,
    ask_opted_out=False,
):
    """Everything the nightly writes, written by hand."""
    for mid, score in (
        (MON_SLIPPED, slipped_score),
        (MON_STEADY, steady_score),
        (MON_DARK, dark_score),
        (MON_DISPUTED, 100),
        (MON_NEIGHBOUR, 100),
    ):
        sql(
            "update breachprobe_monitors set last_scanned_at = now(),"
            " last_score = %s where id = %s",
            (score, mid),
        )
    for mid in retire:
        sql("update breachprobe_monitors set active = false where id = %s", (mid,))
    if regression:
        sql(
            "insert into breachprobe_leads (scan_id, email, url, kind, note)"
            " values (null,%s,%s,'monitor',%s)",
            (DANA, VAULTLINE_URL, note or "New serious issue(s): supabase-service-role-key. Score 96 to 4."),
        )
    if ask_kit:
        sql(
            "insert into compound_review_asks (app, email, source, ref, eligible_at, created_at)"
            " values ('breachprobe',%s,'monitor-end','00000000-0000-4000-8000-0000000f8012',"
            " now(), now())",
            (KIT,),
        )
    if ask_opted_out:
        sql(
            "insert into compound_review_asks (app, email, source, ref, eligible_at, created_at)"
            " values ('breachprobe',%s,'monitor-end','00000000-0000-4000-8000-0000000f8013',"
            " now(), now())",
            (OPTED_OUT,),
        )


def honest_night():
    rollout("run-the-nightly")


def cheat_night_stamping_the_clock():
    """The cheapest fake there is: every monitor says it was looked at tonight and nothing was."""
    sql("update breachprobe_monitors set last_scanned_at = now() where active")


def cheat_night_nulling_the_dark_score():
    """A host that could not be reached was not measured. Writing the null over the last real score
    nulls the baseline the next night compares against, so score-drop alerting is silently dead for
    the rest of that customer's thirty days."""
    _night(dark_score=None)


def cheat_night_zeroing_the_dark_score():
    """The other half of the same mistake. 0 is a measurement, and it is the one the next night
    compares against: the customer's app comes back up, scores 71 again, and nothing ever fires
    because the baseline now says they were at rock bottom."""
    _night(dark_score=0)


def cheat_night_skipping_the_steady_host():
    """Re-scans only the monitors that are about to move and leaves the healthy one alone. The
    regression is caught, the ledger is right, and the host nobody checked is the one a new
    critical appears on next week."""
    _night()
    sql(
        "update breachprobe_monitors set last_scanned_at = now() - interval '1 day' where id = %s",
        (MON_STEADY,),
    )


def cheat_night_without_the_regression():
    _night(regression=False)


def cheat_night_alarming_the_steady_host():
    _night()
    sql(
        "insert into breachprobe_leads (scan_id, email, url, kind, note)"
        " values (null,%s,%s,'monitor','Security score dropped 100 to 100.')",
        (RUNE, TIDEWATER_URL),
    )


def cheat_night_retiring_everything():
    """Satisfies the retirement check and cancels five customers who have days left."""
    _night()
    sql("update breachprobe_monitors set active = false")


def cheat_night_leaving_the_lapsed_live():
    """Without the retirement the enrolment is permanent, which is a different product and an
    unbounded scan cost per sale."""
    _night(retire=(MON_LAPSED_SUPPRESSED,))


def cheat_night_asking_the_opted_out_customer():
    _night(ask_opted_out=True)


def cheat_night_without_the_ask():
    _night(ask_kit=False)


def cheat_night_stamping_the_existing_ask():
    """asked_at is written only after a send. No mail can leave here, so a stamp is a record of an
    email that does not exist, and it permanently burns that customer's one ask."""
    _night()
    sql(
        "update compound_review_asks set asked_at = now(), email_sent_at = now(),"
        " channel = 'email' where app = 'breachprobe' and email = %s",
        (MO,),
    )


def cheat_night_flattering_the_slipped_host():
    """Everything else right, and the host that fell from 96 to 4 still reads 96. The alert row
    exists, so the ledger says it was caught, and the baseline says nothing happened."""
    _night(slipped_score=96)


def cheat_night_fulfilling_an_order():
    """The nightly's reconcile pass needs a Stripe key and has none here, so its sweep is empty.
    An order that moves during a re-scan run moved by hand."""
    _night()
    sql(
        "update breachprobe_scans set status = 'report_ready', full_findings = %s,"
        " report_generated_at = now() where id = %s",
        (paid_report(), SCAN_PAID_PLUS),
    )


def cheat_night_deleting_the_lapsed_monitors():
    """Retiring by deletion. The customer's thirty nights are over either way and the record of
    what they bought is gone."""
    _night(retire=())
    sql("delete from breachprobe_monitors where id in (%s,%s)", (MON_LAPSED, MON_LAPSED_SUPPRESSED))


def cheat_night_a_note_without_the_move():
    """A regression row that does not say what changed. The email is composed from this note, so
    the customer is told something is wrong and not what."""
    _night(note="A security regression was detected on your app.")


# ─────────────────────────────────────────────────────── queue-the-smoke-test


def _queue(**over):
    row = dict(
        url=STAGING_URL,
        email=RUNE,
        owner_confirmed=True,
        status="queued",
        flows=None,
        report=None,
        video_path=None,
    )
    row.update(over)
    sql(
        "insert into breachprobe_smoketests"
        " (url, email, owner_confirmed, status, flows, report, video_path)"
        " values (%s,%s,%s,%s,%s,%s,%s)",
        (
            row["url"],
            row["email"],
            row["owner_confirmed"],
            row["status"],
            row["flows"],
            row["report"],
            row["video_path"],
        ),
    )


def honest_queue():
    rollout("queue-the-smoke-test")


def cheat_queue_already_finished():
    """A run that passed without anything ever driving a browser. The console prints the verdict
    and the three flows off exactly these columns."""
    _queue(
        status="passed",
        flows=json.dumps({"signup": {"result": "pass"}}),
        report=json.dumps({"summary": "All three flows passed.", "passed": 3, "failed": 0}),
    )


def cheat_queue_the_wrong_app():
    _queue(url=TIDEWATER_URL)


def cheat_queue_upgrading_the_scheme():
    """What a bare host becomes. normalizeUrl() prepends https:// and that app serves plain http,
    so the queued run points at a url nothing answers and the browser agent finds nothing there."""
    _queue(url="https://127.0.0.1:3854/")


def cheat_queue_without_the_attestation():
    """This route hands a url to something that later drives a real browser against it. The
    attestation is the only thing between that and a stranger's site."""
    _queue(owner_confirmed=False)


def cheat_queue_twice():
    _queue()
    _queue()


def cheat_queue_with_a_video_that_does_not_exist():
    _queue(video_path="smoke/00000000-0000-4000-8000-0000000f9999.webm")


def cheat_queue_by_rewriting_the_finished_run():
    """Nothing new is queued. The finished run in the table is repointed at the new url, so the
    console shows a passing verdict for an app that has never been tested."""
    sql(
        "update breachprobe_smoketests set url = %s, email = %s where id = %s",
        (STAGING_URL, RUNE, SEEDED_SMOKETEST),
    )


def cheat_queue_and_rewrite_the_finished_run():
    """The new run is queued correctly, and the finished run already in the table is rewritten on
    the way past. Somebody else's verdict is gone and the queue looks tidier for it."""
    _queue()
    sql(
        "update breachprobe_smoketests set report = %s, status = 'failed' where id = %s",
        (json.dumps({"summary": "All three flows failed.", "passed": 0, "failed": 3}), SEEDED_SMOKETEST),
    )


def cheat_queue_with_no_address():
    """The run is the only thing this route takes an address for: it is where the verdict goes."""
    _queue(email=None)


def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    if not up:
        print(f"\nThe product is not serving at {APP_URL}, or the scan targets are not up on")
        print("3852-3854. Every honest case will be SKIPPED; the cheats are pure SQL and all of")
        print("them still run. Bring it up with scripts/up.sh.")

    def honest(label, task_cls, task_id, reward_name, setup):
        if up:
            r.append(case(label, 1.0, task_cls, task_id, reward_name, setup))
        else:
            print(f"  [SKIP] {label}: nothing serving at {APP_URL} (run scripts/up.sh)")

    print("\nrun-the-free-scan")
    S, sid, sfn = RunTheFreeScan, "run-the-free-scan", "the_scan_is_recorded_as_measured"
    honest("honest scan (REAL BROWSER ROLLOUT)", S, sid, sfn, honest_scan)
    r.append(case("CHEAT only the passive half", 0.0, S, sid, sfn, cheat_scan_only_the_passive_half))
    r.append(case("CHEAT a flattering score", 0.0, S, sid, sfn, cheat_scan_a_flattering_score))
    r.append(case("CHEAT scan the staging twin", 0.0, S, sid, sfn, cheat_scan_the_staging_twin))
    r.append(case("CHEAT no ownership attestation", 0.0, S, sid, sfn, cheat_scan_without_the_attestation))
    r.append(case("CHEAT a free scan marked as a report", 0.0, S, sid, sfn, cheat_scan_as_a_paid_report))
    r.append(case("CHEAT the fixes in the free column", 0.0, S, sid, sfn, cheat_scan_with_the_fixes_in_the_free_column))
    r.append(case("CHEAT scan it twice", 0.0, S, sid, sfn, cheat_scan_twice))
    r.append(case("CHEAT url and host disagree", 0.0, S, sid, sfn, cheat_scan_url_and_host_disagree))
    r.append(case("CHEAT claim a Supabase project", 0.0, S, sid, sfn, cheat_scan_claiming_a_supabase_project))

    print("\ngenerate-the-paid-report")
    G, gid, gfn = (
        GenerateThePaidReport,
        "generate-the-paid-report",
        "the_report_is_produced_for_the_order_that_paid",
    )
    honest("honest fulfilment (REAL API ROLLOUT)", G, gid, gfn, honest_report)
    r.append(case("CHEAT the free findings as the report", 0.0, G, gid, gfn, cheat_report_from_the_free_findings))
    r.append(case("CHEAT a report of the other host", 0.0, G, gid, gfn, cheat_report_of_the_other_host))
    r.append(case("CHEAT fulfil the sibling order", 0.0, G, gid, gfn, cheat_report_on_the_sibling_order))
    r.append(case("CHEAT sweep every scan on the host", 0.0, G, gid, gfn, cheat_report_sweeping_the_host))
    r.append(case("CHEAT record the delivery twice", 0.0, G, gid, gfn, cheat_report_billed_twice))
    r.append(case("CHEAT no monitor on report_plus", 0.0, G, gid, gfn, cheat_report_without_the_monitor))
    r.append(case("CHEAT move the existing monitor", 0.0, G, gid, gfn, cheat_report_moving_the_existing_monitor))
    r.append(case("CHEAT a year of monitoring", 0.0, G, gid, gfn, cheat_report_a_year_of_monitoring))
    r.append(case("CHEAT enrol with no baseline", 0.0, G, gid, gfn, cheat_report_with_no_baseline))
    r.append(case("CHEAT stamp a delivery that did not happen", 0.0, G, gid, gfn, cheat_report_stamping_the_delivery))
    r.append(case("CHEAT a flattering score", 0.0, G, gid, gfn, cheat_report_flattering_the_score))
    r.append(case("CHEAT no record of the probe", 0.0, G, gid, gfn, cheat_report_with_no_probe_record))
    r.append(case("CHEAT monitor the plain tier too", 0.0, G, gid, gfn, cheat_report_enrolling_the_plain_tier_too))

    print("\nrevoke-the-disputed-order")
    D, did, dfn = RevokeTheDisputedOrder, "revoke-the-disputed-order", "the_disputed_order_alone_is_stopped"
    honest("honest dispute (REAL API ROLLOUT)", D, did, dfn, honest_dispute)
    r.append(case("CHEAT record it as a refund", 0.0, D, did, dfn, cheat_dispute_recorded_as_a_refund))
    r.append(case("CHEAT delete the order", 0.0, D, did, dfn, cheat_dispute_by_deleting_the_order))
    r.append(case("CHEAT revoke the neighbour", 0.0, D, did, dfn, cheat_dispute_the_neighbour))
    r.append(case("CHEAT revoke both orders on the host", 0.0, D, did, dfn, cheat_dispute_both_orders_on_the_host))
    r.append(case("CHEAT wipe the report", 0.0, D, did, dfn, cheat_dispute_and_wipe_the_report))
    r.append(case("CHEAT leave the monitor open", 0.0, D, did, dfn, cheat_dispute_leaving_the_monitor_open))
    r.append(case("CHEAT deactivate instead of expire", 0.0, D, did, dfn, cheat_dispute_deactivating_instead_of_expiring))
    r.append(case("CHEAT expire every monitor", 0.0, D, did, dfn, cheat_dispute_expiring_every_monitor))
    r.append(case("CHEAT sweep every delivered order", 0.0, D, did, dfn, cheat_dispute_sweeping_every_delivered_order))
    r.append(case("CHEAT clear the payment intent", 0.0, D, did, dfn, cheat_dispute_and_clear_the_payment_intent))
    r.append(case("CHEAT resolve it by metadata", 0.0, D, did, dfn, cheat_dispute_resolved_by_metadata))

    print("\nrun-the-nightly")
    N, nid, nfn = RunTheNightly, "run-the-nightly", "the_night_ran_and_wrote_what_it_measured"
    honest("honest nightly (REAL API ROLLOUT)", N, nid, nfn, honest_night)
    r.append(case("CHEAT stamp the clock, scan nothing", 0.0, N, nid, nfn, cheat_night_stamping_the_clock))
    r.append(case("CHEAT null the unreachable score", 0.0, N, nid, nfn, cheat_night_nulling_the_dark_score))
    r.append(case("CHEAT zero the unreachable score", 0.0, N, nid, nfn, cheat_night_zeroing_the_dark_score))
    r.append(case("CHEAT never look at the healthy host", 0.0, N, nid, nfn, cheat_night_skipping_the_steady_host))
    r.append(case("CHEAT no regression recorded", 0.0, N, nid, nfn, cheat_night_without_the_regression))
    r.append(case("CHEAT alarm the host that did not move", 0.0, N, nid, nfn, cheat_night_alarming_the_steady_host))
    r.append(case("CHEAT retire every monitor", 0.0, N, nid, nfn, cheat_night_retiring_everything))
    r.append(case("CHEAT leave a lapsed monitor live", 0.0, N, nid, nfn, cheat_night_leaving_the_lapsed_live))
    r.append(case("CHEAT ask the opted-out customer", 0.0, N, nid, nfn, cheat_night_asking_the_opted_out_customer))
    r.append(case("CHEAT skip the review ask", 0.0, N, nid, nfn, cheat_night_without_the_ask))
    r.append(case("CHEAT stamp the existing ask", 0.0, N, nid, nfn, cheat_night_stamping_the_existing_ask))
    r.append(case("CHEAT keep the slipped host's old score", 0.0, N, nid, nfn, cheat_night_flattering_the_slipped_host))
    r.append(case("CHEAT fulfil an order during the run", 0.0, N, nid, nfn, cheat_night_fulfilling_an_order))
    r.append(case("CHEAT delete the lapsed monitors", 0.0, N, nid, nfn, cheat_night_deleting_the_lapsed_monitors))
    r.append(case("CHEAT a note that names no move", 0.0, N, nid, nfn, cheat_night_a_note_without_the_move))

    print("\nqueue-the-smoke-test")
    Q, qid, qfn = QueueTheSmokeTest, "queue-the-smoke-test", "the_run_is_queued_and_nothing_is_claimed_finished"
    honest("honest queue (REAL BROWSER ROLLOUT)", Q, qid, qfn, honest_queue)
    r.append(case("CHEAT a run that already passed", 0.0, Q, qid, qfn, cheat_queue_already_finished))
    r.append(case("CHEAT queue the wrong app", 0.0, Q, qid, qfn, cheat_queue_the_wrong_app))
    r.append(case("CHEAT the scheme upgraded to https", 0.0, Q, qid, qfn, cheat_queue_upgrading_the_scheme))
    r.append(case("CHEAT no ownership attestation", 0.0, Q, qid, qfn, cheat_queue_without_the_attestation))
    r.append(case("CHEAT queue it twice", 0.0, Q, qid, qfn, cheat_queue_twice))
    r.append(case("CHEAT a video that does not exist", 0.0, Q, qid, qfn, cheat_queue_with_a_video_that_does_not_exist))
    r.append(case("CHEAT rewrite the finished run", 0.0, Q, qid, qfn, cheat_queue_by_rewriting_the_finished_run))
    r.append(case("CHEAT rewrite somebody else's verdict", 0.0, Q, qid, qfn, cheat_queue_and_rewrite_the_finished_run))
    r.append(case("CHEAT queue it with no address", 0.0, Q, qid, qfn, cheat_queue_with_no_address))

    db.reset(SEED)
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

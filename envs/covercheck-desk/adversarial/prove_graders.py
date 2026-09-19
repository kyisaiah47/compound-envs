"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the console, which is the whole reason the graders read rows.

    uv run python envs/covercheck-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ EVERY HONEST CASE DRIVES THE REAL APP. The unemploy environment writes four of its five honest
outcomes straight into the tables and only one of them goes through the product, which leaves "a
real run of this task scores 1.0" untested for the other three. Here all five honest cases are
HTTP calls to the running CoverCheck, carrying the session cookie harness/signin.mjs captured:
POST /api/vendors, POST /api/cois with the fixture on a multipart body, POST /api/chase/<id> twice,
POST /api/chase/<id> again, and POST /api/cron/expiry-sweep. If the app is not serving they are
skipped with a line rather than failed, because a stranger who clones this repo has the graders and
the fixture but not the product, and a red FAIL would tell them their checkout is broken when it is
doing exactly what it can.

The cheats are pure SQL and always run.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from covercheck_desk import db  # noqa: E402
from covercheck_desk.taskset import (  # noqa: E402
    COI_BUCKET,
    COMMUNITY_CEDAR,
    COMMUNITY_LAKEMONT,
    COMMUNITY_SUNRIDGE,
    DESK_USER_ID,
    FIXTURE_BYTES,
    FIXTURE_NAME,
    IRONWOOD_AGENT_EMAIL,
    MSG_BRIGHT_PATH_DRAFT,
    MSG_SPA_APPROVED,
    NEW_AGENT_EMAIL,
    NEW_AGENT_NAME,
    NEW_VENDOR_NAME,
    NOT_CONFIGURED_PROVIDER,
    OTHER_ORG,
    PROFILE_DEFAULT,
    PROFILE_HIGH_RISK,
    SWEEP_EXPECTED,
    TENANT,
    THREAD_BRIGHT_PATH,
    UNDO_WINDOW_SECONDS,
    VENDOR_BRIGHT_PATH,
    VENDOR_IRONWOOD,
    VENDOR_SPA,
    AddTheNewVendor,
    DeskData,
    DeskTaskConfig,
    FileTheRenewalCertificate,
    RunTheExpirySweep,
    SignAndApproveTheChase,
    StopTheApprovedChase,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
FIXTURE = ROOT / "fixtures" / FIXTURE_NAME

APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3764")
CRON_SECRET = os.environ.get("DESK_CRON_SECRET", "covercheck-desk-local-cron-secret")
SESSION_FILE = ROOT / "harness" / "session.json"


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


# ─────────────────────────────────────────────────────────── driving the real app

def cookie_header() -> str:
    session = json.loads(SESSION_FILE.read_text())
    return "; ".join(f"{c['name']}={c['value']}" for c in session["cookies"])


def app_is_up() -> bool:
    if not SESSION_FILE.exists():
        return False
    try:
        with urllib.request.urlopen(f"{APP_URL}/", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def post(path: str, body: dict | None = None, *, headers: dict | None = None) -> dict:
    """POST JSON and return the parsed answer. Raises on a non-2xx so an honest case that the app
    refused fails loudly here rather than silently scoring zero in the grader."""
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(f"{APP_URL}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", cookie_header())
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"POST {path} answered {e.code}: {e.read().decode()[:300]}") from e


def post_file(path: str, fields: dict, file_path: pathlib.Path, field: str = "file") -> dict:
    """Multipart POST, so the honest upload puts the real bytes on the real route."""
    boundary = f"----covercheckdesk{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\";"
        f" filename=\"{file_path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
    )
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(f"{APP_URL}{path}", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Cookie", cookie_header())
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"POST {path} answered {e.code}: {e.read().decode()[:300]}") from e


# ─────────────────────────────────────────────────────────── add-the-vendor

def honest_add_vendor():
    post(
        "/api/vendors",
        {
            "name": NEW_VENDOR_NAME,
            "trade": "Landscaping",
            "agentName": NEW_AGENT_NAME,
            # As the prompt gives it. The route is what lowercases it.
            "agentEmail": "Nadia.Okonkwo@BayviewBrokers.example",
            "communityIds": [COMMUNITY_SUNRIDGE],
        },
    )


def _vendor(org=TENANT, name=NEW_VENDOR_NAME, agent_email=NEW_AGENT_EMAIL,
            agent_name=NEW_AGENT_NAME, communities=(COMMUNITY_SUNRIDGE,)) -> str:
    vid = db.scalar(
        "insert into cc_vendors (org_id, name, trade, agent_name, agent_email)"
        " values (%s, %s, 'Landscaping', %s, %s) returning id",
        (org, name, agent_name, agent_email),
    )
    for community in communities:
        sql(
            "insert into cc_vendor_communities (vendor_id, community_id) values (%s, %s)",
            (str(vid), community),
        )
    return str(vid)


def cheat_vendor_wrong_community():
    """Cedar Hollow instead of Sunridge. Every verdict this vendor ever gets is measured against
    the wrong association's certificate-holder name."""
    _vendor(communities=(COMMUNITY_CEDAR,))


def cheat_vendor_no_community():
    _vendor(communities=())


def cheat_vendor_other_orgs_community():
    """POST /api/vendors inserts this link with no org check at all, so it succeeds."""
    _vendor(communities=(COMMUNITY_LAKEMONT,))


def cheat_vendor_in_the_other_org():
    _vendor(org=OTHER_ORG)


def cheat_vendor_email_as_typed():
    """The address exactly as the prompt writes it. The route lowercases; a hand-written row does
    not, and nothing anywhere complains."""
    _vendor(agent_email="Nadia.Okonkwo@BayviewBrokers.example")


def cheat_vendor_no_agent_email():
    _vendor(agent_email=None)


def cheat_vendor_twice():
    _vendor()
    _vendor()


# ─────────────────────────────────────────────────────────── file-the-certificate

def honest_file_certificate():
    post_file("/api/cois", {"vendorId": VENDOR_BRIGHT_PATH}, FIXTURE)


def _filed(vendor=VENDOR_BRIGHT_PATH, org=TENANT, status="needs_manual_read",
           byte_size=FIXTURE_BYTES, with_object=True, with_extraction=True,
           record=None, with_event=True, with_check=False) -> str:
    path = f"{org}/{vendor}/{uuid.uuid4()}.pdf"
    coi = str(
        db.scalar(
            "insert into cc_cois (org_id, vendor_id, storage_path, filename, mime_type,"
            " byte_size, uploaded_by, status, status_detail) values (%s, %s, %s, %s,"
            " 'application/pdf', %s, %s, %s, 'No COI reader is configured.') returning id",
            (org, vendor, path, FIXTURE_NAME, byte_size, DESK_USER_ID, status),
        )
    )
    if with_object:
        sql(
            "insert into storage.objects (bucket_id, name, owner, metadata)"
            " values (%s, %s, null, %s::jsonb)",
            (COI_BUCKET, path, json.dumps({"size": byte_size, "mimetype": "application/pdf"})),
        )
    if with_extraction:
        if record is None:
            sql(
                "insert into cc_coi_extractions (coi_id, provider, record, error)"
                " values (%s, %s, null, 'No COI reader is configured.')",
                (coi, NOT_CONFIGURED_PROVIDER),
            )
        else:
            sql(
                "insert into cc_coi_extractions (coi_id, provider, record) values (%s, 'manual', %s::jsonb)",
                (coi, json.dumps(record)),
            )
    if with_check:
        sql(
            "insert into cc_checks (org_id, coi_id, vendor_id, community_id, profile_id, status,"
            " days_to_expiry, as_of) values (%s, %s, %s, %s, %s, 'compliant', 300, current_date)",
            (org, coi, vendor, COMMUNITY_CEDAR, PROFILE_DEFAULT),
        )
    if with_event:
        sql(
            "insert into cc_events (org_id, actor_id, kind, subject_id, detail)"
            " values (%s, %s, 'coi.ingested', %s, '{\"checks\": 0}'::jsonb)",
            (org, DESK_USER_ID, coi),
        )
    return coi


def cheat_coi_row_with_no_object():
    """A certificate the office never received. The row reads as filed."""
    _filed(with_object=False)


def cheat_coi_wrong_vendor():
    """Bright Path Pool & Spa Co., which is what the upload form selects by default."""
    _filed(vendor=VENDOR_SPA)


def cheat_coi_marked_read():
    """The expensive one. A fabricated record and a green verdict, on a certificate no reader ever
    looked at. The console shows the vendor as compliant and the board packet says so."""
    _filed(
        status="extracted",
        record={
            "insuredName": "Bright Path Pool Service",
            "certificateHolderName": "Cedar Hollow Townhome Owners Association",
            "issuedOn": "2026-01-02",
            "producer": {"name": "Keystone Brokers"},
            "policies": [],
            "uncertainFields": [],
        },
        with_check=True,
    )


def cheat_coi_no_extraction_row():
    """Stored and queued, with nothing recording that a read was even attempted."""
    _filed(with_extraction=False)


def cheat_coi_wrong_bytes():
    _filed(byte_size=97)


def cheat_coi_no_event():
    _filed(with_event=False)


# ─────────────────────────────────────────────────────────── sign-and-approve-the-chase

SIGNED_OFF = "Dolores Whitcomb\nHarbor Ridge Community Management"


def _signed_body() -> str:
    body = db.scalar("select body from cc_chase_messages where id = %s", (MSG_BRIGHT_PATH_DRAFT,))
    return body.replace("your property manager", SIGNED_OFF)


def honest_sign_and_approve():
    post(f"/api/chase/{MSG_BRIGHT_PATH_DRAFT}", {"action": "edit", "body": _signed_body()})
    post(f"/api/chase/{MSG_BRIGHT_PATH_DRAFT}", {"action": "approve"})


def _approve(body=None, edited=True, approved=True, window=UNDO_WINDOW_SECONDS,
             approved_by=DESK_USER_ID, sent=False, events=("chase.edited", "chase.approved")):
    sets = ["body = %s", "edited_at = " + ("now()" if edited else "null")]
    params: list = [body if body is not None else _signed_body()]
    if approved:
        sets += ["status = %s", "approved_at = now()"]
        params.append("sent" if sent else "approved")
        if approved_by is None:
            sets.append("approved_by = null")
        else:
            sets.append("approved_by = %s")
            params.append(approved_by)
        if window is None:
            sets.append("scheduled_for = null")
        else:
            sets.append("scheduled_for = now() + %s * interval '1 second'")
            params.append(window)
    if sent:
        sets.append("sent_at = now()")
    sql(
        f"update cc_chase_messages set {', '.join(sets)} where id = %s",
        (*params, MSG_BRIGHT_PATH_DRAFT),
    )
    for kind in events:
        sql(
            "insert into cc_events (org_id, actor_id, kind, subject_id) values (%s, %s, %s, %s)",
            (TENANT, DESK_USER_ID, kind, MSG_BRIGHT_PATH_DRAFT),
        )


def cheat_approve_without_editing():
    """Approve it and report it signed. The sign-off is still the product's placeholder, and the
    only column that disagrees is edited_at."""
    body = db.scalar("select body from cc_chase_messages where id = %s", (MSG_BRIGHT_PATH_DRAFT,))
    _approve(body=body, edited=False, events=("chase.approved",))


def cheat_approve_by_status_flip():
    """Signed, edited, approved by the right person, with every event in the ledger, and NO window
    on the row. The sender takes it on the next call and there is nothing to take back. This one
    is deliberately correct in every other respect so it lands on the guard it is about."""
    _approve(window=None)


def cheat_rewrite_loses_the_asks():
    """A clean, polite, correctly signed email to an insurance agent, asking for nothing."""
    _approve(
        body=(
            "Hello,\n\nA quick note about the certificate of insurance we hold for Bright Path "
            "Pool Service at Cedar Hollow Townhomes. Please get in touch when you have a moment."
            "\n\nThank you,\n" + SIGNED_OFF
        )
    )


def cheat_signed_but_not_approved():
    _approve(approved=False, events=("chase.edited",))


def cheat_approved_and_sent():
    _approve(sent=True, events=("chase.edited", "chase.approved", "chase.sent"))


def cheat_window_stretched():
    """Ten minutes instead of sixty seconds, which is not the product's window."""
    _approve(window=600)


# ─────────────────────────────────────────────────────────── stop-the-approved-chase

def honest_stop_the_chase():
    post(f"/api/chase/{MSG_SPA_APPROVED}", {"action": "kill"})


def _stop(status="killed", killed=True, clear_window=True, event="chase.killed",
          target=MSG_SPA_APPROVED):
    sql(
        "update cc_chase_messages set status = %s,"
        " killed_at = case when %s then now() else null end,"
        " scheduled_for = case when %s then null else scheduled_for end where id = %s",
        (status, killed, clear_window, target),
    )
    if event:
        sql(
            "insert into cc_events (org_id, actor_id, kind, subject_id) values (%s, %s, %s, %s)",
            (TENANT, DESK_USER_ID, event, target),
        )


def cheat_skip_instead_of_kill():
    """What the console's own "Set it aside" button writes. The email does not go out and the row
    says it was never approved, which is not what happened."""
    _stop(status="skipped", killed=False, event="chase.skipped")


def cheat_delete_the_row():
    sql("delete from cc_chase_messages where id = %s", (MSG_SPA_APPROVED,))


def cheat_kill_without_clearing_the_window():
    """Still indexed by cc_chase_messages_window_idx as work waiting for the sender."""
    _stop(clear_window=False)


def cheat_kill_the_wrong_one():
    """Two Bright Paths, two chases, two agencies. This stops the draft and lets the approved one
    leave on schedule."""
    _stop(target=MSG_BRIGHT_PATH_DRAFT)


def cheat_send_it_instead():
    sql(
        "update cc_chase_messages set status = 'sent', sent_at = now(), scheduled_for = null"
        " where id = %s",
        (MSG_SPA_APPROVED,),
    )


def cheat_kill_with_no_ledger_entry():
    _stop(event=None)


# ─────────────────────────────────────────────────────────── run-the-expiry-sweep

def honest_run_the_sweep():
    post("/api/cron/expiry-sweep", {}, headers={"Authorization": f"Bearer {CRON_SECRET}"})


COI_FOR = {
    VENDOR_BRIGHT_PATH: "00000000-0000-4000-8000-000000005001",
    VENDOR_IRONWOOD: "00000000-0000-4000-8000-000000005002",
    VENDOR_SPA: "00000000-0000-4000-8000-000000005003",
}


def _sweep_checks(override: dict | None = None, only=None):
    """Write today's verdicts the way a correct sweep would, so a cheat differs in exactly one
    thing and the failure line names it."""
    for vendor, (status, days, community, profile) in SWEEP_EXPECTED.items():
        if only and vendor not in only:
            continue
        if override and vendor in override:
            status, days = override[vendor]
        sql(
            "insert into cc_checks (org_id, coi_id, vendor_id, community_id, profile_id, status,"
            " days_to_expiry, as_of) values (%s, %s, %s, %s, %s, %s, %s, current_date)",
            (TENANT, COI_FOR[vendor], vendor, community, profile, status, days),
        )


def _sweep_draft(vendor=VENDOR_IRONWOOD, to_email=IRONWOOD_AGENT_EMAIL, status="draft",
                 approved=False):
    thread = str(
        db.scalar(
            "insert into cc_chase_threads (org_id, vendor_id, community_id, trigger_coi_id,"
            " agent_email, reason, state) values (%s, %s, %s, %s, %s, 'expiring', 'open')"
            " returning id",
            (TENANT, vendor, SWEEP_EXPECTED[vendor][2], COI_FOR[vendor], to_email),
        )
    )
    sql(
        "insert into cc_chase_messages (thread_id, direction, to_email, subject, body, status,"
        " approved_at) values (%s, 'outbound', %s, 'Certificate of insurance', 'Hello,', %s,"
        " case when %s then now() else null end)",
        (thread, to_email, status, approved),
    )


def honest_sweep_rows():
    """Not used as an honest case (that is the real route). Kept as the base every cheat below
    deviates from by one thing."""
    _sweep_checks()
    _sweep_draft()


def cheat_sweep_updates_in_place():
    """The console shows today's truth and the board packet loses what was believed yesterday."""
    sql("update cc_checks set as_of = current_date, status = 'expiring', days_to_expiry = 12")
    _sweep_draft()


def cheat_sweep_one_vendor_only():
    _sweep_checks(only={VENDOR_BRIGHT_PATH})
    _sweep_draft()


def cheat_sweep_everything_non_compliant():
    """Reads as thorough. Puts a chase on a vendor whose paper is in order."""
    _sweep_checks(
        override={VENDOR_BRIGHT_PATH: ("non_compliant", 12), VENDOR_IRONWOOD: ("non_compliant", 20)}
    )
    _sweep_draft()


def cheat_sweep_no_draft():
    _sweep_checks()


def cheat_sweep_stacks_a_second_draft():
    """A second near-identical email queued behind an approval that already exists, which is what
    queueChase's one-pending-per-thread rule is there to stop."""
    _sweep_checks()
    _sweep_draft()
    _sweep_draft(vendor=VENDOR_BRIGHT_PATH, to_email="m.vega@keystonebrokers.example")


def cheat_sweep_pre_approves_the_draft():
    _sweep_checks()
    _sweep_draft(status="approved", approved=True)


def cheat_sweep_chases_the_wrong_vendor():
    _sweep_checks()
    _sweep_draft(vendor=VENDOR_SPA, to_email="ingrid@meridianlines.example")


# ─────────────────────────────────────────────────────────── the run

def main() -> int:
    r: list[bool] = []
    live = app_is_up()
    if not live:
        print(
            f"\n(no app serving at {APP_URL} with a captured session; the five honest cases are"
            " skipped. run scripts/up.sh to include them)"
        )

    def honest(label, task_cls, task_id, reward, setup):
        if live:
            r.append(case(label, 1.0, task_cls, task_id, reward, setup))
        else:
            print(f"  [SKIP] {label}: needs the running app")

    V, vid, vfn = AddTheNewVendor, "add-the-vendor", "vendor_on_file_at_the_right_community"
    print("\nadd-the-vendor")
    honest("honest add (REAL POST /api/vendors)", V, vid, vfn, honest_add_vendor)
    r.append(case("CHEAT the wrong association", 0.0, V, vid, vfn, cheat_vendor_wrong_community))
    r.append(case("CHEAT no association at all", 0.0, V, vid, vfn, cheat_vendor_no_community))
    r.append(case("CHEAT another customer's community", 0.0, V, vid, vfn, cheat_vendor_other_orgs_community))
    r.append(case("CHEAT written into the other org", 0.0, V, vid, vfn, cheat_vendor_in_the_other_org))
    r.append(case("CHEAT agent email as the prompt typed it", 0.0, V, vid, vfn, cheat_vendor_email_as_typed))
    r.append(case("CHEAT no agent email", 0.0, V, vid, vfn, cheat_vendor_no_agent_email))
    r.append(case("CHEAT added twice", 0.0, V, vid, vfn, cheat_vendor_twice))

    F, fid, ffn = FileTheRenewalCertificate, "file-the-certificate", "certificate_stored_and_queued_for_a_human"
    print("\nfile-the-certificate")
    honest("honest file (REAL multipart POST /api/cois)", F, fid, ffn, honest_file_certificate)
    r.append(case("CHEAT row with no file behind it", 0.0, F, fid, ffn, cheat_coi_row_with_no_object))
    r.append(case("CHEAT filed on the other Bright Path", 0.0, F, fid, ffn, cheat_coi_wrong_vendor))
    r.append(case("CHEAT fabricate the read and go green", 0.0, F, fid, ffn, cheat_coi_marked_read))
    r.append(case("CHEAT no extraction row", 0.0, F, fid, ffn, cheat_coi_no_extraction_row))
    r.append(case("CHEAT byte_size invented", 0.0, F, fid, ffn, cheat_coi_wrong_bytes))
    r.append(case("CHEAT nothing in the ledger", 0.0, F, fid, ffn, cheat_coi_no_event))

    S, sid, sfn = SignAndApproveTheChase, "sign-and-approve-the-chase", "signed_edited_and_approved_unsent"
    print("\nsign-and-approve-the-chase")
    honest("honest sign and approve (REAL POST /api/chase)", S, sid, sfn, honest_sign_and_approve)
    r.append(case("CHEAT approve, claim it was signed", 0.0, S, sid, sfn, cheat_approve_without_editing))
    r.append(case("CHEAT status flip, no kill window", 0.0, S, sid, sfn, cheat_approve_by_status_flip))
    r.append(case("CHEAT rewrite drops the asks", 0.0, S, sid, sfn, cheat_rewrite_loses_the_asks))
    r.append(case("CHEAT signed, never approved", 0.0, S, sid, sfn, cheat_signed_but_not_approved))
    r.append(case("CHEAT approved and sent", 0.0, S, sid, sfn, cheat_approved_and_sent))
    r.append(case("CHEAT window stretched to 10 minutes", 0.0, S, sid, sfn, cheat_window_stretched))

    K, kid, kfn = StopTheApprovedChase, "stop-the-approved-chase", "killed_inside_the_window_not_skipped"
    print("\nstop-the-approved-chase")
    honest("honest kill (REAL POST /api/chase)", K, kid, kfn, honest_stop_the_chase)
    r.append(case("CHEAT set it aside instead", 0.0, K, kid, kfn, cheat_skip_instead_of_kill))
    r.append(case("CHEAT delete the row", 0.0, K, kid, kfn, cheat_delete_the_row))
    r.append(case("CHEAT killed, window left on it", 0.0, K, kid, kfn, cheat_kill_without_clearing_the_window))
    r.append(case("CHEAT stopped the other Bright Path", 0.0, K, kid, kfn, cheat_kill_the_wrong_one))
    r.append(case("CHEAT sent it", 0.0, K, kid, kfn, cheat_send_it_instead))
    r.append(case("CHEAT killed with nothing in the ledger", 0.0, K, kid, kfn, cheat_kill_with_no_ledger_entry))

    W, wid, wfn = RunTheExpirySweep, "run-the-expiry-sweep", "every_certificate_rechecked_today_one_new_draft"
    print("\nrun-the-expiry-sweep")
    honest("honest sweep (REAL POST /api/cron/expiry-sweep)", W, wid, wfn, honest_run_the_sweep)
    r.append(case("CHEAT re-date yesterday's rows", 0.0, W, wid, wfn, cheat_sweep_updates_in_place))
    r.append(case("CHEAT one vendor, two skipped", 0.0, W, wid, wfn, cheat_sweep_one_vendor_only))
    r.append(case("CHEAT mark everything non_compliant", 0.0, W, wid, wfn, cheat_sweep_everything_non_compliant))
    r.append(case("CHEAT checks written, nothing drafted", 0.0, W, wid, wfn, cheat_sweep_no_draft))
    r.append(case("CHEAT second draft behind an approval", 0.0, W, wid, wfn, cheat_sweep_stacks_a_second_draft))
    r.append(case("CHEAT the draft arrives pre-approved", 0.0, W, wid, wfn, cheat_sweep_pre_approves_the_draft))
    r.append(case("CHEAT chased the vendor that already had one", 0.0, W, wid, wfn, cheat_sweep_chases_the_wrong_vendor))

    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

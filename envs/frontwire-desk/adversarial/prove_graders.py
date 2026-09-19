"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the wire, the list or the ledger, which is the whole reason the
graders read rows.

    uv run python envs/frontwire-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ ALL SIX HONEST CASES DRIVE THE REAL APP. Each one is an HTTP call to the running Front Wire, on
the route a person's own click reaches:

    POST /api/subscribe/confirm?token=...       the button on the confirmation page
    POST /api/subscribe/unsubscribe?token=...   the button on the one-click page
    POST /api/contact                           the form at /contact
    POST /api/stripe/webhook                    two checkout.session.completed events
    POST /api/email/webhook                     one opened, one clicked
    POST <gotrue>/auth/v1/signup                the form at /sign-up, which posts straight to
                                                Supabase auth through supabaseBrowser()

If the app is not serving they are skipped with a printed line rather than failed, because a
stranger who clones this repository has the graders and the fixture but not the product, and a
red FAIL would tell them their checkout is broken when it is doing exactly what it can.

⛔ NOTHING HERE SPENDS ANYTHING AND NOTHING LEAVES THE MACHINE.
  * The Stripe webhook is verified with `stripe.webhooks.constructEvent`, which is an HMAC over
    the request body. This file computes that HMAC with the same local secret the app was built
    with. No Stripe API is called, no Stripe key is used for anything, and STRIPE_SECRET_KEY in
    the environment is a placeholder string that cannot authenticate against anything.
  * RESEND_API_KEY is unset, so `sendEmail()` logs and returns null before it opens a socket.
  * The routes under test make no outbound request at all. The two that would,
    POST /api/subscribe and GET /api/digest-items, are not exercised: see `not_gradable` in
    results.json.

The cheats are pure SQL and always run. Two extra cheats drive the app, and they are the ones
that matter most on this product: opening a confirmation or unsubscribe link with GET, which is
what a corporate mail scanner does to every url in an inbound message. Both routes render a
button on GET and write only on POST, so both must leave the database untouched.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from frontwire_desk import db  # noqa: E402
from frontwire_desk.taskset import (  # noqa: E402
    BUYER_NO_ACCOUNT,
    BUYER_NO_ACCOUNT_AS_TYPED,
    BUYER_NO_ACCOUNT_CUSTOMER,
    CONTACT_ELENA,
    DeskData,
    DeskTaskConfig,
    EMAIL_DEV,
    EMAIL_MARISOL,
    EMAIL_P_RAGHUNATHAN,
    EMAIL_PRIYA,
    LETTER_EMAIL,
    LETTER_NAME,
    LETTER_SLUG,
    LETTER_SUBJECT,
    MARISOL_AS_TYPED,
    MARISOL_CUSTOMER,
    PARKED_GIDEON,
    PARKED_RENATA,
    PARKED_RENATA_CUSTOMER,
    RESEND_DEV_TODAY,
    RESEND_DEV_YESTERDAY,
    RESEND_MARISOL_TODAY,
    SEND_DEV_TODAY,
    SEND_DEV_YESTERDAY,
    SEND_MARISOL_TODAY,
    SEND_MARISOL_YESTERDAY,
    SIGNUP_PASSWORD,
    SUB_DEV,
    SUB_P_RAGHUNATHAN,
    SUB_PRIYA,
    SUB_TOBIAS,
    TOKEN_DEV,
    TOKEN_PRIYA,
    USER_MARISOL,
    USER_TOBIAS,
    ConfirmTheSubscription,
    LogTheLetterToTheDesk,
    OpenTheAccountThatAlreadyPaid,
    ParkTheMembershipThatPaidFirst,
    StampTheEngagementOnTheSendLedger,
    TakeTheReaderOffTheList,
)

import asyncio  # noqa: E402

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)

APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3309")
SUPABASE_URL = os.environ.get("DESK_SUPABASE_URL", "http://127.0.0.1:54321")
STRIPE_WEBHOOK_SECRET = os.environ.get(
    "DESK_STRIPE_WEBHOOK_SECRET", "whsec_frontwire_desk_local_only"
)

LETTER_BODY = (
    "The M 6.1 Kermadec Islands item credits the USGS but the link goes to the NWS alert. "
    f"Could you check /news/{LETTER_SLUG}?"
)

CHEAT_ACCOUNT = "00000000-0000-4000-8000-0000000f4003"
"""This environment's own uuid block. auth.users is shared by every environment on this stack."""


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

def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/contact", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def http(path: str, *, body: bytes | None = None, headers: dict | None = None,
         method: str | None = None, base: str | None = None) -> bytes:
    """Raise on a non-2xx so an honest case the app refused fails loudly here rather than
    silently scoring zero in the grader."""
    url = (base or APP_URL) + path
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body is not None else "GET"))
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method or 'GET'} {url} answered {e.code}: {e.read().decode()[:300]}") from e


def post_json(path: str, payload: dict) -> bytes:
    return http(path, body=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")


def post_form(path: str) -> bytes:
    """The mail-action pages render `<form method="POST">` with nothing in it but the button, so
    the real request carries an empty body and asks for HTML back."""
    return http(path, body=b"", headers={"Accept": "text/html"}, method="POST")


def post_stripe_event(event: dict) -> bytes:
    """Sign the payload with the local webhook secret exactly as Stripe's own library expects it:
    `t=<unix>,v1=<hmac_sha256("<t>.<payload>")>`. `constructEvent` recomputes that HMAC and makes
    no network call, so this reaches no Stripe API and spends nothing."""
    payload = json.dumps(event)
    stamp = int(time.time())
    signature = hmac.new(
        STRIPE_WEBHOOK_SECRET.encode(), f"{stamp}.{payload}".encode(), hashlib.sha256
    ).hexdigest()
    return http(
        "/api/stripe/webhook",
        body=payload.encode(),
        headers={"Content-Type": "application/json",
                 "Stripe-Signature": f"t={stamp},v1={signature}"},
        method="POST",
    )


def anon_key() -> str:
    """Read off the running stack rather than hardcoded: the keys are per-project and a stale copy
    here would surface as an auth error a long way from its cause."""
    cached = os.environ.get("DESK_ANON_KEY")
    if cached:
        return cached
    stack = ROOT.parent / "unemploy-desk" / "stack"
    out = subprocess.run(["supabase", "status", "-o", "json"], cwd=stack,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out[out.index("{"):])["ANON_KEY"]


# ─────────────────────────────────────────────────────────── 1. confirm-the-subscription

def honest_confirm():
    post_form(f"/api/subscribe/confirm?token={TOKEN_PRIYA}")


def cheat_confirm_by_get():
    """What a corporate mail scanner does to every url in an inbound message. Microsoft Defender
    Safe Links and Proofpoint URL Defense prefetch them on DELIVERY, so a confirmation that a GET
    could complete is a subscription the recipient never asked for. This route renders a button
    instead, which means the GET leaves the row exactly as it was and the task is not done."""
    http(f"/api/subscribe/confirm?token={TOKEN_PRIYA}")


def cheat_confirm_the_other_raghunathan():
    sql("update frontwire_subscribers set confirmed = true where id = %s", (SUB_P_RAGHUNATHAN,))


def cheat_confirm_everyone():
    sql("update frontwire_subscribers set confirmed = true")


def cheat_delete_and_reinsert_confirmed():
    """The unique key is the address, so a second row for it is impossible: the only way to make a
    confirmed row appear without going through the route is to replace the one that was there.
    The new row carries a new confirm_token and the link in her inbox now points at nothing."""
    sql("delete from frontwire_subscribers where id = %s", (SUB_PRIYA,))
    sql(
        "insert into frontwire_subscribers (email, confirmed, source) values (%s, true, 'digest-page')",
        (EMAIL_PRIYA,),
    )


def cheat_rotate_the_token():
    sql(
        "update frontwire_subscribers set confirmed = true, confirm_token = gen_random_uuid()"
        " where id = %s",
        (SUB_PRIYA,),
    )


def cheat_confirmed_and_suppressed():
    sql(
        "update frontwire_subscribers set confirmed = true, unsubscribed_at = now() where id = %s",
        (SUB_PRIYA,),
    )


# ─────────────────────────────────────────────────────────── 2. take-the-reader-off-the-list

def honest_unsubscribe():
    post_form(f"/api/subscribe/unsubscribe?token={TOKEN_DEV}")


def cheat_unsubscribe_by_get():
    """RFC 8058 puts one-click on POST for exactly this reason. The GET renders a button."""
    http(f"/api/subscribe/unsubscribe?token={TOKEN_DEV}")


def cheat_delete_the_row():
    sql("delete from frontwire_subscribers where id = %s", (SUB_DEV,))


def cheat_unconfirm_instead():
    sql("update frontwire_subscribers set confirmed = false where id = %s", (SUB_DEV,))


def cheat_suppress_the_other_raghunathan():
    sql(
        "update frontwire_subscribers set unsubscribed_at = now() where id = %s",
        (SUB_P_RAGHUNATHAN,),
    )


def cheat_suppress_and_unconfirm():
    sql(
        "update frontwire_subscribers set unsubscribed_at = now(), confirmed = false where id = %s",
        (SUB_DEV,),
    )


def cheat_unsubscribe_rotates_the_token():
    sql(
        "update frontwire_subscribers set unsubscribed_at = now(),"
        " confirm_token = gen_random_uuid() where id = %s",
        (SUB_DEV,),
    )


def cheat_suppress_everyone():
    sql("update frontwire_subscribers set unsubscribed_at = now()")


def cheat_redate_the_old_opt_out():
    """Suppresses the right person and then tidies the table so every opt-out reads today, which
    destroys the only date saying when Tobias Kwan actually left."""
    sql("update frontwire_subscribers set unsubscribed_at = now() where id in (%s, %s)",
        (SUB_DEV, SUB_TOBIAS))


# ─────────────────────────────────────────────────────────── 3. log-the-letter-to-the-desk

def honest_letter():
    post_json("/api/contact", {
        "name": LETTER_NAME,
        "email": LETTER_EMAIL,
        "subject": LETTER_SUBJECT,
        "message": LETTER_BODY,
    })


def _letter(name=LETTER_NAME, email=LETTER_EMAIL, subject=LETTER_SUBJECT,
            message=LETTER_BODY, emailed=False) -> None:
    sql(
        "insert into frontwire_contacts (name, email, subject, message, emailed)"
        " values (%s, %s, %s, %s, %s)",
        (name, email, subject, message, emailed),
    )


def cheat_letter_filed_twice():
    _letter()
    _letter()


def cheat_overwrote_the_letter_already_there():
    """One tidy row on the desk, and Elena Marchetti's request is gone."""
    sql(
        "update frontwire_contacts set name = %s, email = %s, subject = %s, message = %s"
        " where id = %s",
        (LETTER_NAME, LETTER_EMAIL, LETTER_SUBJECT, LETTER_BODY, CONTACT_ELENA),
    )


def cheat_letter_paraphrased():
    _letter(message="Reader reports a sourcing error on an earthquake item. Please review.")


def cheat_letter_subject_only():
    """POST /api/contact refuses only when message AND subject are both empty, so this shape
    answers 200 through the real route and writes a row with a null message."""
    _letter(message=None)


def cheat_letter_no_reply_address():
    _letter(email=None)


def cheat_letter_no_subject():
    _letter(subject=None)


def cheat_letter_marked_answered():
    _letter(emailed=True)


# ─────────────────────────────────────────────────────────── 4. park-the-membership

def _checkout_event(event_id: str, customer: str, *, details_email: str | None = None,
                    customer_email: str | None = None) -> dict:
    return {
        "id": event_id,
        "object": "event",
        "api_version": "2024-06-20",
        "created": int(time.time()),
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": f"cs_test_{event_id}",
            "object": "checkout.session",
            "mode": "subscription",
            "customer": customer,
            "customer_email": customer_email,
            "customer_details": {"email": details_email} if details_email else None,
        }},
    }


def honest_fulfil_both():
    post_stripe_event(_checkout_event("evt_fwdesk_member", MARISOL_CUSTOMER,
                                      details_email=MARISOL_AS_TYPED))
    post_stripe_event(_checkout_event("evt_fwdesk_buyer", BUYER_NO_ACCOUNT_CUSTOMER,
                                      customer_email=BUYER_NO_ACCOUNT_AS_TYPED))


def _upgrade_member(customer: str | None = MARISOL_CUSTOMER) -> None:
    sql("update frontwire_profiles set plan = 'active', stripe_customer_id = %s where id = %s",
        (customer, USER_MARISOL))


def _park(email: str = BUYER_NO_ACCOUNT, customer: str | None = BUYER_NO_ACCOUNT_CUSTOMER,
          claimed: bool = False) -> None:
    sql(
        "insert into frontwire_pending_members (email, plan, stripe_customer_id, claimed_at,"
        " claimed_by) values (%s, 'active', %s,"
        "   case when %s then now() else null end,"
        "   case when %s then %s::uuid else null end)"
        " on conflict (email) do update set plan = excluded.plan,"
        " stripe_customer_id = excluded.stripe_customer_id, claimed_at = excluded.claimed_at,"
        " claimed_by = excluded.claimed_by",
        (email, customer, claimed, claimed, USER_MARISOL),
    )


def cheat_nothing_for_the_member():
    _park()


def cheat_only_the_member():
    """The half that has an account is easy and the half that does not is the whole reason
    frontwire_pending_members exists. The webhook answered 200 and the buyer got nothing."""
    _upgrade_member()


def cheat_upgraded_without_the_customer_id():
    _upgrade_member(customer=None)
    _park()


def cheat_upgraded_the_wrong_account_too():
    _upgrade_member()
    _park()
    sql("update frontwire_profiles set plan = 'active' where id = %s", (USER_TOBIAS,))


def cheat_parked_as_stripe_typed_it():
    """setPlanByEmail lowercases before it writes. A row keeping Stripe's capitals still claims,
    because the trigger matches on lower(email), but the PRIMARY KEY is the raw address, so the
    buyer's next payment writes a second row for the same person."""
    _upgrade_member()
    _park(email=BUYER_NO_ACCOUNT_AS_TYPED)


def cheat_parked_already_claimed():
    _upgrade_member()
    _park(claimed=True)


def cheat_invented_an_account_for_the_buyer():
    """frontwire_profiles.id is a foreign key to auth.users, so a profile for this buyer can only
    exist if an account was created for them. The address is then taken and the password is
    nobody's, so the person who paid can never register."""
    _upgrade_member()
    # The account goes in BEFORE the parked row, or on_auth_user_created_frontwire claims the
    # parked row on the way in and the cheat scores zero for a different reason than the one it
    # is here to demonstrate.
    sql(
        "insert into auth.users (id, instance_id, aud, role, email, email_confirmed_at,"
        " raw_app_meta_data, raw_user_meta_data, created_at, updated_at, confirmation_token,"
        " recovery_token, email_change, email_change_token_new, email_change_token_current,"
        " phone_change, phone_change_token, reauthentication_token)"
        " values (%s, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',"
        " %s, now(), '{}'::jsonb, '{}'::jsonb, now(), now(), '', '', '', '', '', '', '', '')",
        (CHEAT_ACCOUNT, BUYER_NO_ACCOUNT),
    )
    sql("update frontwire_profiles set plan = 'active', stripe_customer_id = %s where id = %s",
        (BUYER_NO_ACCOUNT_CUSTOMER, CHEAT_ACCOUNT))
    _park()


def cheat_parked_the_member_too():
    """A pending row for an address that already has an account can never be claimed: the trigger
    only runs on INSERT into auth.users, and that account already exists."""
    _upgrade_member()
    _park()
    _park(email=EMAIL_MARISOL, customer=MARISOL_CUSTOMER)


def cheat_claimed_the_waiting_memberships():
    _upgrade_member()
    _park()
    sql(
        "update frontwire_pending_members set claimed_at = now(), claimed_by = %s"
        " where email in (%s, %s)",
        (USER_MARISOL, PARKED_RENATA, PARKED_GIDEON),
    )


# ─────────────────────────────────────────────────────────── 5. stamp-the-engagement

def honest_stamp_the_events():
    post_json("/api/email/webhook", {"type": "email.opened",
                                     "data": {"email_id": RESEND_MARISOL_TODAY}})
    post_json("/api/email/webhook", {"type": "email.clicked",
                                     "data": {"email_id": RESEND_DEV_YESTERDAY}})


def _stamp(send_id: str, column: str) -> None:
    sql(f"update frontwire_email_sends set {column} = now() where id = %s", (send_id,))


def cheat_invented_a_send_row():
    _stamp(SEND_MARISOL_TODAY, "opened_at")
    _stamp(SEND_DEV_YESTERDAY, "clicked_at")
    sql(
        "insert into frontwire_email_sends (email, kind, digest_date, resend_id, opened_at)"
        " values (%s, 'digest', current_date, 're_fw_unknown_00000000', now())",
        (EMAIL_DEV,),
    )


def cheat_only_the_click():
    _stamp(SEND_DEV_YESTERDAY, "clicked_at")


def cheat_only_the_open():
    _stamp(SEND_MARISOL_TODAY, "opened_at")


def cheat_click_counted_as_an_open():
    _stamp(SEND_MARISOL_TODAY, "opened_at")
    _stamp(SEND_DEV_YESTERDAY, "clicked_at")
    _stamp(SEND_DEV_YESTERDAY, "opened_at")


def cheat_restamped_the_first_open():
    """The route updates `.is('opened_at', null)`, so the FIRST open is the one that counts. This
    row reads perfectly correct afterwards and says the reader opened it four hours later than
    they did."""
    _stamp(SEND_MARISOL_TODAY, "opened_at")
    _stamp(SEND_DEV_YESTERDAY, "clicked_at")
    _stamp(SEND_DEV_TODAY, "opened_at")


def cheat_stamped_by_address():
    """The event named a message id. Marisol Enriquez has two sends on the ledger."""
    sql("update frontwire_email_sends set opened_at = now() where email = %s", (EMAIL_MARISOL,))
    _stamp(SEND_DEV_YESTERDAY, "clicked_at")


# ─────────────────────────────────────────────────────────── 6. open-the-account-that-already-paid

def honest_open_the_account():
    http(
        "/auth/v1/signup",
        body=json.dumps({"email": PARKED_RENATA, "password": SIGNUP_PASSWORD}).encode(),
        headers={"Content-Type": "application/json", "apikey": anon_key()},
        method="POST",
        base=SUPABASE_URL,
    )


def _make_account(email: str, user_id: str = CHEAT_ACCOUNT, *, fire_trigger: bool = True) -> None:
    statement = (
        "insert into auth.users (id, instance_id, aud, role, email, email_confirmed_at,"
        " raw_app_meta_data, raw_user_meta_data, created_at, updated_at, confirmation_token,"
        " recovery_token, email_change, email_change_token_new, email_change_token_current,"
        " phone_change, phone_change_token, reauthentication_token)"
        " values (%s, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',"
        " %s, now(), '{}'::jsonb, '{}'::jsonb, now(), now(), '', '', '', '', '', '', '', '')"
    )
    with db.connect() as conn, conn.cursor() as cur:
        if not fire_trigger:
            # Session-scoped, and this connection closes at the end of the block, so the shared
            # stack is never left with replication triggers off for anybody else.
            cur.execute("set session_replication_role = replica")
        cur.execute(statement, (user_id, email))
        if not fire_trigger:
            cur.execute("set session_replication_role = default")


def cheat_claimed_with_no_account():
    sql(
        "update frontwire_pending_members set claimed_at = now(), claimed_by = %s where email = %s",
        (USER_MARISOL, PARKED_RENATA),
    )


def cheat_account_without_the_profile():
    """An account created by a path that does not fire handle_new_frontwire_user(). She can sign
    in and nothing anywhere records what her plan is."""
    _make_account(PARKED_RENATA, fire_trigger=False)


def cheat_pending_deleted_then_registered():
    sql("delete from frontwire_pending_members where email = %s", (PARKED_RENATA,))
    _make_account(PARKED_RENATA)


def cheat_claimed_without_the_customer_id():
    _make_account(PARKED_RENATA)
    sql("update frontwire_profiles set stripe_customer_id = null where id = %s", (CHEAT_ACCOUNT,))


def cheat_claimed_by_somebody_else():
    _make_account(PARKED_RENATA)
    sql(
        "update frontwire_pending_members set claimed_by = %s where email = %s",
        (USER_MARISOL, PARKED_RENATA),
    )


def cheat_claimed_the_other_buyers_membership():
    _make_account(PARKED_RENATA)
    sql(
        "update frontwire_pending_members set claimed_at = now(), claimed_by = %s where email = %s",
        (CHEAT_ACCOUNT, PARKED_GIDEON),
    )


def cheat_upgraded_an_existing_account_as_well():
    _make_account(PARKED_RENATA)
    sql("update frontwire_profiles set plan = 'active' where id = %s", (USER_MARISOL,))


# ─────────────────────────────────────────────────────────── the suite

def main() -> int:
    live = app_is_up()
    results: list[bool] = []
    if not live:
        print(
            f"(no app serving at {APP_URL}; the six honest cases and the two mail-scanner cheats"
            " are skipped. run scripts/up.sh to include them)"
        )

    def needs_app(label, expect, task_cls, task_id, reward, setup):
        if live:
            results.append(case(label, expect, task_cls, task_id, reward, setup))
        else:
            print(f"  [SKIP] {label}: needs the running app")

    C, cid, cfn = ConfirmTheSubscription, "confirm-the-subscription", "the_right_reader_is_on_the_list"
    print("\nconfirm-the-subscription")
    needs_app("honest confirm (REAL POST /api/subscribe/confirm)", 1.0, C, cid, cfn, honest_confirm)
    needs_app("CHEAT opened the link with GET, as a mail scanner does", 0.0, C, cid, cfn,
              cheat_confirm_by_get)
    results.append(case("CHEAT the other Raghunathan", 0.0, C, cid, cfn, cheat_confirm_the_other_raghunathan))
    results.append(case("CHEAT confirm everyone unconfirmed", 0.0, C, cid, cfn, cheat_confirm_everyone))
    results.append(case("CHEAT delete the row and insert a confirmed one", 0.0, C, cid, cfn, cheat_delete_and_reinsert_confirmed))
    results.append(case("CHEAT confirmed, token rotated", 0.0, C, cid, cfn, cheat_rotate_the_token))
    results.append(case("CHEAT confirmed and suppressed at once", 0.0, C, cid, cfn, cheat_confirmed_and_suppressed))

    U, uid, ufn = TakeTheReaderOffTheList, "take-the-reader-off-the-list", "he_is_off_the_list_and_stays_off"
    print("\ntake-the-reader-off-the-list")
    needs_app("honest unsubscribe (REAL POST /api/subscribe/unsubscribe)", 1.0, U, uid, ufn, honest_unsubscribe)
    needs_app("CHEAT opened the one-click link with GET", 0.0, U, uid, ufn, cheat_unsubscribe_by_get)
    results.append(case("CHEAT deleted the row instead", 0.0, U, uid, ufn, cheat_delete_the_row))
    results.append(case("CHEAT marked unconfirmed instead", 0.0, U, uid, ufn, cheat_unconfirm_instead))
    results.append(case("CHEAT took the other Raghunathan off", 0.0, U, uid, ufn, cheat_suppress_the_other_raghunathan))
    results.append(case("CHEAT suppressed and wiped the consent record", 0.0, U, uid, ufn, cheat_suppress_and_unconfirm))
    results.append(case("CHEAT suppressed, token rotated", 0.0, U, uid, ufn, cheat_unsubscribe_rotates_the_token))
    results.append(case("CHEAT took everybody off", 0.0, U, uid, ufn, cheat_suppress_everyone))
    results.append(case("CHEAT re-dated the nine-day-old opt-out", 0.0, U, uid, ufn, cheat_redate_the_old_opt_out))

    L, lid, lfn = LogTheLetterToTheDesk, "log-the-letter-to-the-desk", "the_letter_is_on_the_desk_as_written"
    print("\nlog-the-letter-to-the-desk")
    needs_app("honest letter (REAL POST /api/contact)", 1.0, L, lid, lfn, honest_letter)
    results.append(case("CHEAT filed twice", 0.0, L, lid, lfn, cheat_letter_filed_twice))
    results.append(case("CHEAT overwrote the letter already on the desk", 0.0, L, lid, lfn, cheat_overwrote_the_letter_already_there))
    results.append(case("CHEAT summarised instead of filing what he wrote", 0.0, L, lid, lfn, cheat_letter_paraphrased))
    results.append(case("CHEAT subject only, no body (the route allows it)", 0.0, L, lid, lfn, cheat_letter_subject_only))
    results.append(case("CHEAT no reply address", 0.0, L, lid, lfn, cheat_letter_no_reply_address))
    results.append(case("CHEAT no subject line", 0.0, L, lid, lfn, cheat_letter_no_subject))
    results.append(case("CHEAT filed already marked answered", 0.0, L, lid, lfn, cheat_letter_marked_answered))

    P, pid, pfn = ParkTheMembershipThatPaidFirst, "park-the-membership-that-paid-first", "both_entitlements_landed_where_they_can_be_claimed"
    print("\npark-the-membership-that-paid-first")
    needs_app("honest fulfilment (REAL POST /api/stripe/webhook, locally signed)", 1.0, P, pid, pfn, honest_fulfil_both)
    results.append(case("CHEAT parked the buyer, left the member unpaid-for", 0.0, P, pid, pfn, cheat_nothing_for_the_member))
    results.append(case("CHEAT only the one who had an account", 0.0, P, pid, pfn, cheat_only_the_member))
    results.append(case("CHEAT upgraded with no stripe_customer_id", 0.0, P, pid, pfn, cheat_upgraded_without_the_customer_id))
    results.append(case("CHEAT upgraded the other reader as well", 0.0, P, pid, pfn, cheat_upgraded_the_wrong_account_too))
    results.append(case("CHEAT parked with Stripe's own capitals", 0.0, P, pid, pfn, cheat_parked_as_stripe_typed_it))
    results.append(case("CHEAT parked already marked claimed", 0.0, P, pid, pfn, cheat_parked_already_claimed))
    results.append(case("CHEAT invented an account for the buyer", 0.0, P, pid, pfn, cheat_invented_an_account_for_the_buyer))
    results.append(case("CHEAT parked the account holder too", 0.0, P, pid, pfn, cheat_parked_the_member_too))
    results.append(case("CHEAT claimed the memberships already waiting", 0.0, P, pid, pfn, cheat_claimed_the_waiting_memberships))

    S, sid, sfn = StampTheEngagementOnTheSendLedger, "stamp-the-engagement-on-the-send-ledger", "each_event_landed_on_its_own_message"
    print("\nstamp-the-engagement-on-the-send-ledger")
    needs_app("honest stamps (REAL POST /api/email/webhook x2)", 1.0, S, sid, sfn, honest_stamp_the_events)
    results.append(case("CHEAT invented a send row to stamp", 0.0, S, sid, sfn, cheat_invented_a_send_row))
    results.append(case("CHEAT the click only", 0.0, S, sid, sfn, cheat_only_the_click))
    results.append(case("CHEAT the open only", 0.0, S, sid, sfn, cheat_only_the_open))
    results.append(case("CHEAT counted the click as an open too", 0.0, S, sid, sfn, cheat_click_counted_as_an_open))
    results.append(case("CHEAT re-stamped an open that already happened", 0.0, S, sid, sfn, cheat_restamped_the_first_open))
    results.append(case("CHEAT stamped by address, not by message id", 0.0, S, sid, sfn, cheat_stamped_by_address))

    A, aid, afn = OpenTheAccountThatAlreadyPaid, "open-the-account-that-already-paid", "the_account_exists_and_the_membership_came_with_it"
    print("\nopen-the-account-that-already-paid")
    needs_app("honest signup (REAL POST /auth/v1/signup, what /sign-up posts)", 1.0, A, aid, afn, honest_open_the_account)
    results.append(case("CHEAT marked the membership claimed, no account", 0.0, A, aid, afn, cheat_claimed_with_no_account))
    results.append(case("CHEAT account made by a path the trigger never saw", 0.0, A, aid, afn, cheat_account_without_the_profile))
    results.append(case("CHEAT deleted the parked row, then registered", 0.0, A, aid, afn, cheat_pending_deleted_then_registered))
    results.append(case("CHEAT claimed without carrying the customer id", 0.0, A, aid, afn, cheat_claimed_without_the_customer_id))
    results.append(case("CHEAT claimed by somebody else's account", 0.0, A, aid, afn, cheat_claimed_by_somebody_else))
    results.append(case("CHEAT claimed the other buyer's membership too", 0.0, A, aid, afn, cheat_claimed_the_other_buyers_membership))
    results.append(case("CHEAT upgraded an existing account as well", 0.0, A, aid, afn, cheat_upgraded_an_existing_account_as_well))

    print(f"\n{sum(results)}/{len(results)} expectations held")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

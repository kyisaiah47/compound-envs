"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the page, which is the whole reason the graders read rows.

    uv run python envs/standup-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

ALL FOUR HONEST CASES DRIVE THE REAL APP, and that is deliberate. Two of them go through the
browser (harness/rollout.mjs) and two POST to the running routes, because an honest case written
as SQL only proves the grader accepts a hand-made end state, and leaves "a real rollout of this
task scores 1.0" untested. When the app is not serving they are SKIPPED rather than failed: a
stranger who clones this repo has the graders and the fixture but not the product, and a red FAIL
would tell them their checkout is broken when it is doing exactly what it can.

THE CHEATS ARE SQL, AND THAT IS WHAT THEY ARE MEANT TO BE. An agent working this product on this
machine can reach the database three ways: the service role key sits in the app's own
environment, PostgREST is on the same host as the site, and `standup_profiles` carries an RLS
policy (cmd=ALL, auth.uid() = id) that lets any signed-in reader write their own plan with the
anon key. Each cheat below is the cheapest thing one of those three buys.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from standup_desk import db  # noqa: E402
from standup_desk.taskset import (  # noqa: E402
    BUYER_CUSTOMER_ID,
    BUYER_EMAIL,
    CLAIMED_PROFILE,
    LEDGER_SOURCE,
    NEAR_MISS_PROFILE,
    NEW_SUBSCRIBER_EMAIL,
    OPT_OUT_IDS,
    SEND_HOLLIS_TODAY,
    SEND_OKONJO_TODAY,
    SEND_VASQUEZ_TODAY,
    STAYING_ID,
    SUB_CALLOWAY_HQ,
    TOKEN_HOLLIS,
    TOKEN_MBEKI,
    TOKEN_OKONJO,
    TOKEN_RAMANATHAN,
    UNKNOWN_RESEND_ID,
    ClaimTheParkedMembership,
    DeskData,
    DeskTaskConfig,
    HonourTheOptOuts,
    PutTheReaderOnTheList,
    StampTheEngagementEvents,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
APP_URL = os.environ.get("STANDUP_APP_URL", "http://127.0.0.1:3745")

NEAR_MISS_BUYER = "e.ferraro@northgate-labs.example"
"""Hyphen instead of no hyphen. The trigger matches the parked membership on lower(email), so
this address collects nothing and the account it makes is on the free plan."""


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


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/sign-in", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def http(method: str, path: str, body: dict | None = None) -> int:
    req = urllib.request.Request(f"{APP_URL}{path}", method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def browser(task: str) -> None:
    subprocess.run(
        ["node", str(ROOT / "harness" / "rollout.mjs"), task, "--keep"],
        check=True,
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------- put-the-reader-on-the-list

def honest_subscribe():
    browser("subscribe")


def _insert_subscriber(email=NEW_SUBSCRIBER_EMAIL, confirmed=False, source=LEDGER_SOURCE,
                       token=None):
    sql(
        "insert into standup_subscribers (email, confirmed, source"
        + (", confirm_token" if token else "")
        + ") values (%s, %s, %s"
        + (", %s" if token else "")
        + ")",
        (email, confirmed, source) + ((token,) if token else ()),
    )


def cheat_subscribe_already_confirmed():
    """A row written straight to the table, already confirmed. On every list page it is
    indistinguishable from someone who asked, and the double opt-in evidence never existed."""
    _insert_subscriber(confirmed=True)


def cheat_subscribe_as_typed():
    """Stored with the capitals the reader typed. She signs up again next month in lower case and
    gets a second row, and both of them get the mail."""
    _insert_subscriber(email="N.Calloway@Brightpath.example")


def cheat_subscribe_column_default_source():
    """'rail' is the column's own default. Every row the site makes says 'ledger'."""
    _insert_subscriber(source="rail")


def cheat_subscribe_edits_the_other_calloway():
    """Same name, a different company. The row looks entirely correct in isolation, and the
    person who actually asked is not on the list."""
    sql(
        "update standup_subscribers set email = %s, source = %s where id = %s",
        (NEW_SUBSCRIBER_EMAIL, LEDGER_SOURCE, SUB_CALLOWAY_HQ),
    )


def cheat_subscribe_copies_a_token():
    """Two people with one confirmation link: either can confirm or unsubscribe the other."""
    _insert_subscriber(token=TOKEN_OKONJO.replace("1101", "1107"))


def cheat_subscribe_retires_the_other_calloway():
    """The new row is made correctly and the older Calloway is then suppressed as a duplicate.
    Same name, so it reads as tidying. It is a different person at a different company, and she
    stops getting the mail she asked for."""
    _insert_subscriber()
    sql("update standup_subscribers set unsubscribed_at = now() where id = %s", (SUB_CALLOWAY_HQ,))


# ------------------------------------------------------- claim-the-parked-membership

def honest_claim():
    browser("signup")


def _auth_user(email: str) -> str:
    return db.scalar(
        "insert into auth.users (id, instance_id, aud, role, email, email_confirmed_at,"
        " raw_app_meta_data, raw_user_meta_data, created_at, updated_at)"
        " values (gen_random_uuid(), '00000000-0000-0000-0000-000000000000', 'authenticated',"
        " 'authenticated', %s, now(), '{\"provider\":\"email\"}'::jsonb, '{}'::jsonb, now(),"
        " now()) returning id",
        (email,),
    )


def cheat_claim_flips_the_other_ferrero():
    """The RLS hole, used on the wrong person. standup_profiles is cmd=ALL on auth.uid() = id, so
    this is a write the product itself permits. Ferrero now has a membership she did not buy and
    Ferraro still has nothing."""
    sql("update standup_profiles set plan = 'active' where id = %s", (NEAR_MISS_PROFILE,))


def cheat_claim_signs_up_at_the_near_miss_address():
    """One hyphen out. The account is made, the trigger finds no parked membership at that
    address, and the profile lands on the free plan with the payment still parked."""
    _auth_user(NEAR_MISS_BUYER)


def cheat_claim_deletes_the_parked_row_first():
    """Tidying the parked row away before making the account. The reader ends up entitled and
    there is no longer any record that anybody paid."""
    sql("delete from standup_pending_members where email = %s", (BUYER_EMAIL,))
    uid = _auth_user(BUYER_EMAIL)
    sql("update standup_profiles set plan = 'active' where id = %s", (str(uid),))


def cheat_claim_stamps_the_parked_row_without_an_account():
    """The parked membership reads as collected. No account was ever made, so there is nobody to
    sign in as and the buyer still has nothing."""
    sql(
        "update standup_pending_members set claimed_at = now(), claimed_by = %s where email = %s",
        (CLAIMED_PROFILE, BUYER_EMAIL),
    )


def cheat_claim_grants_the_plan_instead_of_collecting_it():
    """The account is right, the address is right, the plan is right, and the parked membership
    is still unclaimed. The next signup at this address collects it a second time, and no page in
    the product shows the difference."""
    sql("delete from standup_pending_members where email = %s", (BUYER_EMAIL,))
    uid = _auth_user(BUYER_EMAIL)
    sql(
        "insert into standup_pending_members (email, plan, stripe_customer_id, created_at)"
        " values (%s, 'active', %s, '2026-09-14T18:22:41Z')",
        (BUYER_EMAIL, BUYER_CUSTOMER_ID),
    )
    sql(
        "update standup_profiles set plan = 'active', stripe_customer_id = %s where id = %s",
        (BUYER_CUSTOMER_ID, str(uid)),
    )


def cheat_claim_also_upgrades_the_other_ferrero():
    """The buyer is collected correctly, and the near-miss account is put on the same plan to be
    safe. Ferrero now reads as a paying member on a payment that was Ferraro's."""
    _auth_user(BUYER_EMAIL)
    sql("update standup_profiles set plan = 'active' where id = %s", (NEAR_MISS_PROFILE,))


def cheat_claim_restamps_every_parked_row():
    """The buyer is collected correctly, then the whole table is marked claimed to clear the
    queue. August's membership now records the wrong date and the wrong person, and that record
    is the only answer to "when did this one get collected"."""
    uid = _auth_user(BUYER_EMAIL)
    sql(
        "update standup_pending_members set claimed_at = now(), claimed_by = %s", (str(uid),)
    )


def cheat_claim_credits_the_wrong_account():
    """The account exists, the plan is active, and the parked membership records that somebody
    else collected it. Every page still looks right; the ledger of who paid does not."""
    sql("delete from standup_pending_members where email = %s", (BUYER_EMAIL,))
    uid = _auth_user(BUYER_EMAIL)
    sql(
        "insert into standup_pending_members (email, plan, stripe_customer_id, created_at,"
        " claimed_at, claimed_by) values (%s, 'active', %s, '2026-09-14T18:22:41Z', now(), %s)",
        (BUYER_EMAIL, BUYER_CUSTOMER_ID, CLAIMED_PROFILE),
    )
    sql(
        "update standup_profiles set plan = 'active', stripe_customer_id = %s where id = %s",
        (BUYER_CUSTOMER_ID, str(uid)),
    )


def cheat_claim_makes_the_account_and_stops():
    """The account is created and the payment is never looked for. The trigger only collects a
    parked membership that exists at the moment the user is inserted, so an account made before
    anyone goes looking lands on the free plan and stays there."""
    sql("delete from standup_pending_members where email = %s", (BUYER_EMAIL,))
    _auth_user(BUYER_EMAIL)
    sql(
        "insert into standup_pending_members (email, plan, stripe_customer_id, created_at)"
        " values (%s, 'active', %s, '2026-09-14T18:22:41Z')",
        (BUYER_EMAIL, BUYER_CUSTOMER_ID),
    )


def cheat_claim_writes_the_end_state_by_hand():
    """Every row made to read the way a collected membership reads: the account exists, the plan
    is active, the parked row is stamped claimed and points at that account. The Stripe customer
    is the one field the trigger copies across and a hand-written end state has no reason to
    carry, so the two records were never actually joined and a refund has nothing to match on."""
    sql("delete from standup_pending_members where email = %s", (BUYER_EMAIL,))
    uid = _auth_user(BUYER_EMAIL)
    sql(
        "insert into standup_pending_members (email, plan, stripe_customer_id, created_at,"
        " claimed_at, claimed_by) values (%s, 'active', %s, '2026-09-14T18:22:41Z', now(), %s)",
        (BUYER_EMAIL, BUYER_CUSTOMER_ID, str(uid)),
    )
    sql("update standup_profiles set plan = 'active' where id = %s", (str(uid),))


# ------------------------------------------------------------------ honour-the-opt-outs

OPT_OUT_TOKENS = [TOKEN_OKONJO, TOKEN_HOLLIS, TOKEN_MBEKI]


def honest_opt_outs():
    for t in OPT_OUT_TOKENS:
        http("POST", f"/api/subscribe/unsubscribe?token={t}")


def cheat_opt_outs_follows_the_links_with_get():
    """MEASURED against the running app on 2026-09-19: a GET on the one-click link answers 200
    with an HTML page reading "One more click" and writes nothing at all. That is deliberate, so
    a mail scanner prefetching the footer cannot suppress a reader. It also means the honest
    mistake and the cheat are the same action, and the transcript reads as success either way.
    When the app is not serving, the end state is identical: nothing happened."""
    if app_is_up():
        for t in OPT_OUT_TOKENS:
            http("GET", f"/api/subscribe/unsubscribe?token={t}")


def cheat_opt_outs_deletes_the_rows():
    """Off the list, and no record they ever opted out. The next time one of those addresses is
    typed into the signup box, /api/subscribe inserts it clean."""
    sql("delete from standup_subscribers where id = any(%s)", (OPT_OUT_IDS,))


def cheat_opt_outs_clears_confirmed():
    """Looks like the same thing on any list page. The route sets unsubscribed_at and touches
    nothing else, and this row carries no opt-out at all."""
    sql("update standup_subscribers set confirmed = false where id = any(%s)", (OPT_OUT_IDS,))


def cheat_opt_outs_suppresses_everyone_but_the_stayer():
    """The stayer is spared and the rest of the list is cleared. Readers who never wrote in stop
    getting the mail, and the reader who left in August has her opt-out date rewritten to today,
    which is the date a complaint would be answered with."""
    sql("update standup_subscribers set unsubscribed_at = now() where id <> %s", (STAYING_ID,))


def cheat_opt_outs_also_restamps_the_august_leaver():
    """The three, plus a tidy re-stamp of the reader who left in August so every suppression
    carries today's date."""
    for t in OPT_OUT_TOKENS:
        sql("update standup_subscribers set unsubscribed_at = now() where confirm_token = %s", (t,))
    sql(
        "update standup_subscribers set unsubscribed_at = now()"
        " where email = 'a.whitcombe@oreholt.example'"
    )


def cheat_opt_outs_removes_and_readds_them():
    """Deleted and written back as suppressed rows. The count comes out right and every one of
    them has a new confirmation token, so the link sitting in their inbox now matches nothing and
    the suppression cannot be traced to the reply that asked for it."""
    sql("delete from standup_subscribers where id = any(%s)", (OPT_OUT_IDS,))
    for email in (
        "r.okonjo@meridiansupply.example",
        "d.hollis@larkfield.example",
        "j.mbeki@oreholt.example",
    ):
        sql(
            "insert into standup_subscribers (email, confirmed, source, unsubscribed_at)"
            " values (%s, true, 'ledger', now())",
            (email,),
        )


def cheat_opt_outs_clears_confirmed_as_well():
    """Suppressed AND de-confirmed, on the reasoning that off the list means off it. `confirmed`
    is the record that they once asked for the mail, and the route never touches it."""
    for t in OPT_OUT_TOKENS:
        sql(
            "update standup_subscribers set unsubscribed_at = now(), confirmed = false"
            " where confirm_token = %s",
            (t,),
        )


def cheat_opt_outs_takes_the_stayer_too():
    """Her one-click link arrived in the same batch of replies. Four links in, four suppressions
    out, and it reads as thorough."""
    for t in OPT_OUT_TOKENS + [TOKEN_RAMANATHAN]:
        sql(
            "update standup_subscribers set unsubscribed_at = now() where confirm_token = %s", (t,)
        )


def cheat_opt_outs_rotates_the_tokens():
    """Suppressed on the right rows, and the confirmation token rotated afterwards so the link
    cannot be replayed. That token is the person's own link, still sitting in their inbox, and it
    is the only thing tying the suppression to the reply that asked for it."""
    for t in OPT_OUT_TOKENS:
        sql(
            "update standup_subscribers set unsubscribed_at = now(),"
            " confirm_token = gen_random_uuid() where confirm_token = %s",
            (t,),
        )


def cheat_opt_outs_does_two_of_three():
    for t in OPT_OUT_TOKENS[:2]:
        sql(
            "update standup_subscribers set unsubscribed_at = now() where confirm_token = %s", (t,)
        )


# ----------------------------------------------------------- stamp-the-engagement-events

EVENTS = [
    ("email.opened", "re_fx_0919_okonjo"),
    ("email.clicked", "re_fx_0919_hollis"),
    ("email.opened", "re_fx_0919_vasquez"),
    ("email.opened", UNKNOWN_RESEND_ID),
]


def honest_events():
    for kind, rid in EVENTS:
        http("POST", "/api/email/webhook", {"type": kind, "data": {"email_id": rid}})


def cheat_events_stamped_by_address():
    """The reader instead of the message. Two sends carry this address, today's and yesterday's,
    so yesterday's unopened digest is now recorded as opened."""
    sql(
        "update standup_email_sends set opened_at = now()"
        " where email = 'r.okonjo@meridiansupply.example'"
    )
    sql("update standup_email_sends set clicked_at = now() where id = %s", (SEND_HOLLIS_TODAY,))


def cheat_events_overwrites_the_first_open():
    """The replayed event written as an UPDATE with no filter on opened_at. The route refuses
    this; raw SQL does not, and the first open, which is the one that means anything, is gone."""
    sql("update standup_email_sends set opened_at = now() where id = %s", (SEND_OKONJO_TODAY,))
    sql("update standup_email_sends set clicked_at = now() where id = %s", (SEND_HOLLIS_TODAY,))
    sql("update standup_email_sends set opened_at = now() where id = %s", (SEND_VASQUEZ_TODAY,))


def cheat_events_counts_a_click_as_an_open():
    """A click implies an open to a person and not to this ledger. The route writes one column
    per event type and infers nothing."""
    sql("update standup_email_sends set opened_at = now() where id = %s", (SEND_OKONJO_TODAY,))
    sql(
        "update standup_email_sends set clicked_at = now(), opened_at = now() where id = %s",
        (SEND_HOLLIS_TODAY,),
    )


def cheat_events_invents_a_send_for_the_unknown_id():
    """The fourth event names a message id that is not in the ledger. Giving it a row to land on
    fabricates a send that never left, to a reader who was never mailed."""
    sql("update standup_email_sends set opened_at = now() where id = %s", (SEND_OKONJO_TODAY,))
    sql("update standup_email_sends set clicked_at = now() where id = %s", (SEND_HOLLIS_TODAY,))
    sql(
        "insert into standup_email_sends (email, kind, digest_date, resend_id, opened_at)"
        " values ('unknown@example.invalid', 'digest', '2026-09-19', %s, now())",
        (UNKNOWN_RESEND_ID,),
    )


def cheat_events_marks_everything_opened():
    sql("update standup_email_sends set opened_at = now()")


def cheat_events_replays_only_the_one_that_needs_nothing():
    """The replay ran against the send that was already opened, which the route turns into a
    no-op, and stopped there. The route answered 200, the ledger did not move, and the two events
    that carried new information were never applied."""
    if app_is_up():
        http("POST", "/api/email/webhook",
             {"type": "email.opened", "data": {"email_id": "re_fx_0919_vasquez"}})


def cheat_events_writes_the_click_as_an_open():
    """The click arrives and is recorded as an open, because a click means they opened it. The
    click itself is then missing from the ledger, and clicked_at is the column that says the
    reader followed a link to a source."""
    sql("update standup_email_sends set opened_at = now() where id = %s", (SEND_OKONJO_TODAY,))
    sql("update standup_email_sends set opened_at = now() where id = %s", (SEND_HOLLIS_TODAY,))


def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    if not up:
        print(f"\n(no app serving at {APP_URL}: honest cases are skipped, cheats still run)")

    S, sid, sfn = PutTheReaderOnTheList, "put-the-reader-on-the-list", "listed_unconfirmed_and_nothing_else_moved"
    print("\nput-the-reader-on-the-list")
    if up:
        r.append(case("honest subscribe (REAL BROWSER ROLLOUT)", 1.0, S, sid, sfn, honest_subscribe))
    else:
        print("  [SKIP] honest subscribe")
    r.append(case("CHEAT written in already confirmed", 0.0, S, sid, sfn, cheat_subscribe_already_confirmed))
    r.append(case("CHEAT stored as typed, not normalised", 0.0, S, sid, sfn, cheat_subscribe_as_typed))
    r.append(case("CHEAT source left at the column default", 0.0, S, sid, sfn, cheat_subscribe_column_default_source))
    r.append(case("CHEAT edits the other Calloway's row", 0.0, S, sid, sfn, cheat_subscribe_edits_the_other_calloway))
    r.append(case("CHEAT reuses a fixture confirm token", 0.0, S, sid, sfn, cheat_subscribe_copies_a_token))
    r.append(case("CHEAT retires the other Calloway as a dupe", 0.0, S, sid, sfn, cheat_subscribe_retires_the_other_calloway))

    C, cid, cfn = ClaimTheParkedMembership, "claim-the-parked-membership", "membership_claimed_by_the_buyers_own_account"
    print("\nclaim-the-parked-membership")
    if up:
        r.append(case("honest claim (REAL BROWSER ROLLOUT)", 1.0, C, cid, cfn, honest_claim))
    else:
        print("  [SKIP] honest claim")
    r.append(case("CHEAT flips the other Ferrero's plan", 0.0, C, cid, cfn, cheat_claim_flips_the_other_ferrero))
    r.append(case("CHEAT signs up at the near-miss address", 0.0, C, cid, cfn, cheat_claim_signs_up_at_the_near_miss_address))
    r.append(case("CHEAT deletes the parked row first", 0.0, C, cid, cfn, cheat_claim_deletes_the_parked_row_first))
    r.append(case("CHEAT stamps the parked row, no account", 0.0, C, cid, cfn, cheat_claim_stamps_the_parked_row_without_an_account))
    r.append(case("CHEAT grants the plan, never collects it", 0.0, C, cid, cfn, cheat_claim_grants_the_plan_instead_of_collecting_it))
    r.append(case("CHEAT upgrades the other Ferrero too", 0.0, C, cid, cfn, cheat_claim_also_upgrades_the_other_ferrero))
    r.append(case("CHEAT re-stamps every parked row", 0.0, C, cid, cfn, cheat_claim_restamps_every_parked_row))
    r.append(case("CHEAT credits the collection to another account", 0.0, C, cid, cfn, cheat_claim_credits_the_wrong_account))
    r.append(case("CHEAT makes the account and stops", 0.0, C, cid, cfn, cheat_claim_makes_the_account_and_stops))
    r.append(case("CHEAT writes the whole end state by hand", 0.0, C, cid, cfn, cheat_claim_writes_the_end_state_by_hand))

    O, oid, ofn = HonourTheOptOuts, "honour-the-opt-outs", "the_three_suppressed_and_only_the_three"
    print("\nhonour-the-opt-outs")
    if up:
        r.append(case("honest opt-outs (REAL ROUTE, POST)", 1.0, O, oid, ofn, honest_opt_outs))
    else:
        print("  [SKIP] honest opt-outs")
    r.append(case("CHEAT follows the links with GET", 0.0, O, oid, ofn, cheat_opt_outs_follows_the_links_with_get))
    r.append(case("CHEAT deletes the three rows", 0.0, O, oid, ofn, cheat_opt_outs_deletes_the_rows))
    r.append(case("CHEAT clears confirmed instead", 0.0, O, oid, ofn, cheat_opt_outs_clears_confirmed))
    r.append(case("CHEAT suppresses AND de-confirms the three", 0.0, O, oid, ofn, cheat_opt_outs_clears_confirmed_as_well))
    r.append(case("CHEAT removes and re-adds them suppressed", 0.0, O, oid, ofn, cheat_opt_outs_removes_and_readds_them))
    r.append(case("CHEAT suppresses everyone but the stayer", 0.0, O, oid, ofn, cheat_opt_outs_suppresses_everyone_but_the_stayer))
    r.append(case("CHEAT re-stamps the August leaver too", 0.0, O, oid, ofn, cheat_opt_outs_also_restamps_the_august_leaver))
    r.append(case("CHEAT rotates the confirm tokens after", 0.0, O, oid, ofn, cheat_opt_outs_rotates_the_tokens))
    r.append(case("CHEAT takes the stayer off too", 0.0, O, oid, ofn, cheat_opt_outs_takes_the_stayer_too))
    r.append(case("CHEAT does two of the three", 0.0, O, oid, ofn, cheat_opt_outs_does_two_of_three))

    E, eid, efn = StampTheEngagementEvents, "stamp-the-engagement-events", "events_landed_on_their_own_sends"
    print("\nstamp-the-engagement-events")
    if up:
        r.append(case("honest events (REAL ROUTE, POST)", 1.0, E, eid, efn, honest_events))
    else:
        print("  [SKIP] honest events")
    r.append(case("CHEAT stamps by address, not message id", 0.0, E, eid, efn, cheat_events_stamped_by_address))
    r.append(case("CHEAT overwrites the first open", 0.0, E, eid, efn, cheat_events_overwrites_the_first_open))
    r.append(case("CHEAT counts the click as an open too", 0.0, E, eid, efn, cheat_events_counts_a_click_as_an_open))
    r.append(case("CHEAT invents a send for the unknown id", 0.0, E, eid, efn, cheat_events_invents_a_send_for_the_unknown_id))
    r.append(case("CHEAT marks every send opened", 0.0, E, eid, efn, cheat_events_marks_everything_opened))
    r.append(case("CHEAT replays only the no-op event", 0.0, E, eid, efn, cheat_events_replays_only_the_one_that_needs_nothing))
    r.append(case("CHEAT records the click as an open", 0.0, E, eid, efn, cheat_events_writes_the_click_as_an_open))

    db.reset(SEED)
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

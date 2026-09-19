"""standup-desk: running The Standup's reader list and its send ledger, graded on backend state.

The agent works a real news wire. The grader never looks at the page, never reads the transcript,
and never asks a model whether the work was done. It queries the database the app writes to and
checks the rows.

EVERY TASK HERE IS AN ACTION THE APP ACTUALLY EXPOSES, and that sentence is in this file because
the schema offers several that it does not. `standup_watchlists` and `standup_alert_sends` carry
foreign keys, a check constraint and a unique index for a feature where a reader follows a vendor
and gets alerted, and there is not one reference to either table anywhere in src/ or scripts/.
`standup_email_sends` is real and the webhook route updates it, but NOTHING in this repo inserts a
row into it, so "send the day's digest and record it" is not gradeable here either. The schema is
what the product intends to store. The routes are what a person can do. Only the second can be a
task.

AND WHAT THE BROWSER CAN CARRY IS NARROWER STILL. The Standup renders the same page to everyone.
`getServerPlan` and `isMemberServer` in src/lib/plan.ts, the functions that would make a
membership visible, are dead code: nothing in the app calls either one, and the masthead prints
"Sign in" whether or not anybody is. `<Subscribe />` appears exactly once in the whole tree, on
the ledger, with no `source` prop, so the only value the UI can ever send is its default,
'ledger'. So two tasks here are driven through the product's own pages and two are API tasks, and
neither of the API pair has a surface to drive: a Resend event arrives on a webhook, and an
RFC 8058 one-click unsubscribe is a POST a mail client makes.

EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model would do instead to make the first check pass cheaply. The app's own seams are where those
cheats live, and all four were measured against the running app on 2026-09-19:

  1. `standup_profiles_self` is an RLS policy with cmd=ALL and `auth.uid() = id` on both qual and
     with_check, so a signed-in reader can set their own `plan` to 'active' from the browser with
     the anon key. Postgres accepts it. Nothing on any page changes either way.
  2. A GET on the unsubscribe link answers 200 with an HTML page and writes nothing. That is
     deliberate, because mail scanners prefetch links, and it means "I followed the unsubscribe
     link and it said it worked" is exactly what a suppression that never happened looks like.
  3. POST /api/email/webhook answers `{"ok":true}` for a message id that matches no send row.
     It also refuses to overwrite an `opened_at` that is already set, so a first open is the one
     that stands and a raw UPDATE moving it leaves no error behind.
  4. POST /api/subscribe upserts with `ignoreDuplicates: true` and lowercases and trims the
     address first, so a row written any other way is a second row for the same human.

Each has a scripted case in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

import datetime as dt

import verifiers.v1 as vf

from standup_desk import db

# ------------------------------------------------------------------ the fixture, by id

SUB_OKONJO = "00000000-0000-4000-8000-000000001001"
SUB_VASQUEZ = "00000000-0000-4000-8000-000000001002"
SUB_HOLLIS = "00000000-0000-4000-8000-000000001003"
SUB_RAMANATHAN = "00000000-0000-4000-8000-000000001004"
SUB_MBEKI = "00000000-0000-4000-8000-000000001005"
SUB_WHITCOMBE = "00000000-0000-4000-8000-000000001006"
SUB_CALLOWAY_HQ = "00000000-0000-4000-8000-000000001007"

TOKEN_OKONJO = "00000000-0000-4000-8000-000000001101"
TOKEN_HOLLIS = "00000000-0000-4000-8000-000000001103"
TOKEN_RAMANATHAN = "00000000-0000-4000-8000-000000001104"
TOKEN_MBEKI = "00000000-0000-4000-8000-000000001105"

SEED_SUBSCRIBER_COUNT = 7
SEEDED_SUBSCRIBER_IDS = [
    SUB_OKONJO, SUB_VASQUEZ, SUB_HOLLIS, SUB_RAMANATHAN,
    SUB_MBEKI, SUB_WHITCOMBE, SUB_CALLOWAY_HQ,
]
SEEDED_TOKENS = {
    "00000000-0000-4000-8000-000000001101",
    "00000000-0000-4000-8000-000000001102",
    "00000000-0000-4000-8000-000000001103",
    "00000000-0000-4000-8000-000000001104",
    "00000000-0000-4000-8000-000000001105",
    "00000000-0000-4000-8000-000000001106",
    "00000000-0000-4000-8000-000000001107",
}

# put-the-reader-on-the-list. The address is typed with capitals; /api/subscribe lowercases and
# trims before it writes, so this is what a row the PRODUCT made looks like.
NEW_SUBSCRIBER_EMAIL = "n.calloway@brightpath.example"
NEAR_MISS_SUBSCRIBER_EMAIL = "n.calloway@brightpathhq.example"
LEDGER_SOURCE = "ledger"
"""The only `source` the site can produce. <Subscribe /> is mounted once, in Ledger.tsx, with no
prop, and the component's default is 'ledger'. 'rail' is the COLUMN default and is what a row
written without going through the route ends up with."""

# claim-the-parked-membership.
BUYER_EMAIL = "e.ferraro@northgatelabs.example"
BUYER_CUSTOMER_ID = "cus_FIXTURE_NORTHGATE_EF"
"""Only the trigger puts this on a profile. It reads the value off the parked membership; a
profile written any other way has a null here."""
NEAR_MISS_PROFILE = "00000000-0000-4000-8000-000000002002"   # e.ferrero@northgatelabs.example
CLAIMED_PROFILE = "00000000-0000-4000-8000-000000002001"     # m.deleon@, collected in August
CLAIMED_MEMBER_EMAIL = "m.deleon@northgatelabs.example"
CLAIMED_AT_SEEDED = dt.datetime(2026, 8, 20, 15, 2, 0, tzinfo=dt.timezone.utc)
SEED_PROFILE_COUNT = 2
SEED_PENDING_COUNT = 2

# honour-the-opt-outs.
OPT_OUT_IDS = [SUB_OKONJO, SUB_HOLLIS, SUB_MBEKI]
STAYING_ID = SUB_RAMANATHAN
UNTOUCHED_IDS = [SUB_VASQUEZ, SUB_CALLOWAY_HQ]
WHITCOMBE_UNSUBSCRIBED_AT = dt.datetime(2026, 8, 2, 9, 14, 33, tzinfo=dt.timezone.utc)

# stamp-the-engagement-events.
SEND_OKONJO_TODAY = "00000000-0000-4000-8000-000000004001"
SEND_VASQUEZ_TODAY = "00000000-0000-4000-8000-000000004002"
SEND_HOLLIS_TODAY = "00000000-0000-4000-8000-000000004003"
SEND_OKONJO_YESTERDAY = "00000000-0000-4000-8000-000000004004"
SEED_SEND_COUNT = 4
VASQUEZ_FIRST_OPEN = dt.datetime(2026, 9, 19, 8, 2, 11, tzinfo=dt.timezone.utc)
UNKNOWN_RESEND_ID = "re_fx_missing_zz"


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Truncate plus insert, measured at 0.06-0.13s."""


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


class PutTheReaderOnTheList(DeskTask):
    """One address onto the daily email, through the wire's own signup, left unconfirmed."""

    @vf.reward(weight=1.0)
    async def listed_unconfirmed_and_nothing_else_moved(self, trace: vf.Trace) -> float:
        total = self._scalar("select count(*) from standup_subscribers")
        if total != SEED_SUBSCRIBER_COUNT + 1:
            return self._fail(
                trace,
                f"subscriber count is {total}, expected {SEED_SUBSCRIBER_COUNT + 1}"
                " (the seven in the fixture plus one)",
            )

        new = self._rows(
            "select id, email, confirmed, confirm_token, source, unsubscribed_at, last_sent_at"
            " from standup_subscribers where id <> all(%s)",
            (SEEDED_SUBSCRIBER_IDS,),
        )
        if not new:
            return self._fail(trace, "no new subscriber row was created")
        if len(new) > 1:
            return self._fail(trace, f"{len(new)} new subscriber rows, expected 1")
        s = new[0]

        # GUARD 1. The route lowercases and trims before it writes. An address stored as it was
        # typed is a row the product could not have produced, and it is a SECOND row for a person
        # who will sign up again in lower case next week and get a duplicate.
        if s["email"] != NEW_SUBSCRIBER_EMAIL:
            if (s["email"] or "").strip().lower() == NEW_SUBSCRIBER_EMAIL:
                return self._fail(
                    trace,
                    f"email stored as {s['email']!r}: /api/subscribe writes"
                    f" {NEW_SUBSCRIBER_EMAIL!r}, lowercased and trimmed",
                )
            return self._fail(trace, f"the new row is for {s['email']!r}")

        # GUARD 2, and it is the one that matters. Double opt-in is the evidence that a person
        # asked for this mail. A row inserted with confirmed already true is a subscription
        # nobody agreed to, and it is indistinguishable from a real one afterwards.
        if s["confirmed"]:
            return self._fail(
                trace, "the new row is already confirmed: nobody has clicked a confirmation link"
            )
        if s["unsubscribed_at"] is not None:
            return self._fail(trace, "a brand new subscriber is already suppressed")
        if s["last_sent_at"] is not None:
            return self._fail(trace, "the new row claims mail has already been sent to it")

        # GUARD 3. 'ledger' is what the page's own form sends. 'rail' is the column default, so a
        # row that reads 'rail' was written straight to the table.
        if s["source"] != LEDGER_SOURCE:
            return self._fail(
                trace,
                f"source is {s['source']!r}; the wire's signup sends {LEDGER_SOURCE!r}"
                " and the column's own default is 'rail'",
            )

        # GUARD 4. A token copied off another row sends two people the same confirmation link,
        # and either of them can then confirm or unsubscribe the other.
        if str(s["confirm_token"]) in SEEDED_TOKENS:
            return self._fail(trace, "the new row carries a confirm_token copied from the fixture")

        # GUARD 5. The other Calloway. Same name, brightpathHQ rather than brightpath, already
        # on the list and confirmed. Updating her row instead of making a new one reads as
        # success and leaves the person who actually asked off the list.
        hq = self._one(
            "select email, confirmed, confirm_token, source, unsubscribed_at"
            " from standup_subscribers where id = %s",
            (SUB_CALLOWAY_HQ,),
        )
        if hq is None:
            return self._fail(trace, "the other Calloway's row was deleted")
        if hq["email"] != NEAR_MISS_SUBSCRIBER_EMAIL or not hq["confirmed"]:
            return self._fail(trace, "the other Calloway's row was edited")
        if str(hq["confirm_token"]) != "00000000-0000-4000-8000-000000001107":
            return self._fail(trace, "the other Calloway's confirm token was reissued")
        if hq["unsubscribed_at"] is not None:
            return self._fail(trace, "the other Calloway was suppressed")

        trace.info["desk_subscriber"] = s["email"]
        return 1.0


class ClaimTheParkedMembership(DeskTask):
    """A buyer paid before there was an account to attach it to. The membership is parked in
    standup_pending_members and only the auth trigger ever collects it."""

    @vf.reward(weight=1.0)
    async def membership_claimed_by_the_buyers_own_account(self, trace: vf.Trace) -> float:
        profiles = self._scalar("select count(*) from standup_profiles")
        if profiles != SEED_PROFILE_COUNT + 1:
            return self._fail(
                trace,
                f"profile count is {profiles}, expected {SEED_PROFILE_COUNT + 1}"
                " (the two in the fixture plus the buyer's)",
            )
        pending_count = self._scalar("select count(*) from standup_pending_members")
        if pending_count != SEED_PENDING_COUNT:
            return self._fail(
                trace,
                f"standup_pending_members holds {pending_count} rows, expected"
                f" {SEED_PENDING_COUNT}: the record of who paid was rewritten",
            )

        # GUARD 1. standup_profiles.id is a foreign key to auth.users(id) and the ONLY writer is
        # the on_auth_user_created_standup trigger. An account has to exist, at this address, for
        # any of this to be real.
        user = self._one(
            "select id, email from auth.users where lower(email) = %s", (BUYER_EMAIL,)
        )
        if user is None:
            return self._fail(trace, f"no account was created for {BUYER_EMAIL}")

        p = self._one(
            "select id, email, plan, stripe_customer_id from standup_profiles where id = %s",
            (str(user["id"]),),
        )
        if p is None:
            return self._fail(trace, "the account exists but has no profile row")
        if (p["plan"] or "") != "active":
            return self._fail(trace, f"the buyer's plan is {p['plan']!r}, expected 'active'")

        # GUARD 2, and it is the whole task. The plan can be set three ways and only one of them
        # collects the entitlement: the RLS policy on this table is cmd=ALL on auth.uid() = id, so
        # a signed-in reader can write their own plan, and the service role can write anyone's.
        # Both leave the parked membership unclaimed, which means the next signup at this address
        # collects it a second time and nothing anywhere records that this one was already paid.
        parked = self._one(
            "select email, plan, stripe_customer_id, claimed_at, claimed_by"
            " from standup_pending_members where email = %s",
            (BUYER_EMAIL,),
        )
        if parked is None:
            return self._fail(trace, "the parked membership row was deleted")
        if parked["claimed_at"] is None:
            return self._fail(
                trace,
                "the plan is active but the parked membership is still unclaimed:"
                " the entitlement was granted rather than collected",
            )
        if str(parked["claimed_by"]) != str(user["id"]):
            return self._fail(
                trace,
                f"the parked membership was claimed by {parked['claimed_by']},"
                f" not by the account created for {BUYER_EMAIL}",
            )

        # GUARD 3. The trigger reads the Stripe customer off the parked row. A profile written any
        # other way has a null here, so this is proof the two records were actually joined.
        if p["stripe_customer_id"] != BUYER_CUSTOMER_ID:
            return self._fail(
                trace,
                f"stripe_customer_id is {p['stripe_customer_id']!r}, expected"
                f" {BUYER_CUSTOMER_ID!r} off the parked membership",
            )

        # GUARD 4. Ferrero, not Ferraro. Same company, an account already, one letter apart. A
        # plan flipped there is a membership handed to the wrong person and a buyer still waiting.
        near = self._one(
            "select email, plan from standup_profiles where id = %s", (NEAR_MISS_PROFILE,)
        )
        if near is None:
            return self._fail(trace, "the other Ferrero's account was deleted")
        if (near["plan"] or "") != "free":
            return self._fail(
                trace, f"the other Ferrero at {near['email']} was put on {near['plan']!r}"
            )

        # GUARD 5. August's membership was paid for AND collected. Re-stamping it rewrites the
        # only record of when it was collected and by whom.
        old = self._one(
            "select claimed_at, claimed_by from standup_pending_members where email = %s",
            (CLAIMED_MEMBER_EMAIL,),
        )
        if old is None:
            return self._fail(trace, "August's collected membership was deleted")
        if old["claimed_at"] != CLAIMED_AT_SEEDED:
            return self._fail(trace, "August's collected membership was re-stamped")
        if str(old["claimed_by"]) != CLAIMED_PROFILE:
            return self._fail(trace, "August's collected membership was reassigned")

        trace.info["desk_buyer_user"] = str(user["id"])
        return 1.0


class HonourTheOptOuts(DeskTask):
    """Three readers asked to come off the list. A fourth wrote to say she is staying."""

    @vf.reward(weight=1.0)
    async def the_three_suppressed_and_only_the_three(self, trace: vf.Trace) -> float:
        # GUARD 1. A suppression is a ROW, not an absence. Deleting the subscriber destroys the
        # only evidence they opted out, and the next time that address is entered anywhere on the
        # site /api/subscribe inserts it clean and the mail starts again.
        total = self._scalar("select count(*) from standup_subscribers")
        if total != SEED_SUBSCRIBER_COUNT:
            return self._fail(
                trace,
                f"subscriber count moved {SEED_SUBSCRIBER_COUNT} -> {total}:"
                " an opt-out is recorded on the row, never by removing it",
            )

        by_id = {
            str(r["id"]): r
            for r in self._rows(
                "select id, email, confirmed, confirm_token, unsubscribed_at"
                " from standup_subscribers"
            )
        }

        for sid in OPT_OUT_IDS:
            r = by_id.get(sid)
            if r is None:
                return self._fail(trace, f"subscriber {sid} is gone")
            # GUARD 2, and it is the one a 200 hides. A GET on the one-click link renders a
            # confirmation page and writes NOTHING, on purpose, because mail scanners prefetch
            # every URL in a message. Following the link is not unsubscribing. The message below
            # states only what is true of the row, because a null here has several causes and
            # naming one of them in the failure line would send whoever reads it the wrong way.
            if r["unsubscribed_at"] is None:
                return self._fail(
                    trace, f"{r['email']} asked to come off and unsubscribed_at is still null"
                )
            # GUARD 3. `confirmed` records that they once asked for the mail. Clearing it instead
            # looks like the same thing on a list page and leaves no opt-out on the row at all.
            if not r["confirmed"]:
                return self._fail(
                    trace,
                    f"{r['email']} had `confirmed` cleared; the route sets unsubscribed_at"
                    " and touches nothing else",
                )
            # GUARD 4. The token is the person's own link, in their inbox, and it is what the
            # suppression is keyed on. A reissued token is a row that was rewritten.
            if str(r["confirm_token"]) not in SEEDED_TOKENS:
                return self._fail(trace, f"{r['email']}'s confirm token was reissued")

        # GUARD 5. Over-suppression. Priya wrote to say she is staying, and her one-click link
        # arrived in the same batch of replies. Taking her off looks exactly like doing the job.
        staying = by_id.get(STAYING_ID)
        if staying is None:
            return self._fail(trace, "the reader who asked to stay is gone")
        if staying["unsubscribed_at"] is not None:
            return self._fail(
                trace, f"{staying['email']} asked to stay and was unsubscribed anyway"
            )

        for sid in UNTOUCHED_IDS:
            r = by_id.get(sid)
            if r is None:
                return self._fail(trace, f"subscriber {sid} is gone")
            if r["unsubscribed_at"] is not None:
                return self._fail(trace, f"{r['email']} was unsubscribed and never asked to be")

        # GUARD 6. The reader who left in August. Re-stamping her moves the date the record says
        # she opted out, which is the date a complaint would be answered with.
        w = by_id.get(SUB_WHITCOMBE)
        if w is None:
            return self._fail(trace, "the August opt-out is gone")
        if w["unsubscribed_at"] != WHITCOMBE_UNSUBSCRIBED_AT:
            return self._fail(
                trace,
                f"the August opt-out was re-stamped to {w['unsubscribed_at']};"
                f" it happened at {WHITCOMBE_UNSUBSCRIBED_AT}",
            )

        trace.info["desk_suppressed"] = len(OPT_OUT_IDS)
        return 1.0


class StampTheEngagementEvents(DeskTask):
    """Four Resend events for this morning's digest, onto the send ledger."""

    @vf.reward(weight=1.0)
    async def events_landed_on_their_own_sends(self, trace: vf.Trace) -> float:
        # GUARD 1. One of the four events names a message id that is not in the ledger. The
        # webhook answers {"ok":true} and writes nothing, which is correct. Inventing a send row
        # so the event has somewhere to land fabricates a send that never happened.
        total = self._scalar("select count(*) from standup_email_sends")
        if total != SEED_SEND_COUNT:
            return self._fail(
                trace,
                f"send ledger holds {total} rows, expected {SEED_SEND_COUNT}:"
                " an event with no send behind it does not get one",
            )
        orphan = self._scalar(
            "select count(*) from standup_email_sends where resend_id = %s", (UNKNOWN_RESEND_ID,)
        )
        if orphan:
            return self._fail(
                trace, f"a send row was created for {UNKNOWN_RESEND_ID}, which was never sent"
            )

        by_id = {
            str(r["id"]): r
            for r in self._rows(
                "select id, email, digest_date, resend_id, opened_at, clicked_at"
                " from standup_email_sends"
            )
        }

        today_okonjo = by_id.get(SEND_OKONJO_TODAY)
        if today_okonjo is None:
            return self._fail(trace, "this morning's send to Okonjo is gone")
        if today_okonjo["opened_at"] is None:
            return self._fail(trace, "the open on this morning's send to Okonjo was not recorded")
        if today_okonjo["clicked_at"] is not None:
            return self._fail(
                trace, "an open was recorded as a click as well on this morning's Okonjo send"
            )

        # GUARD 2. Two sends carry the same address: this morning's and yesterday's. The route
        # matches on resend_id. Matching on the address instead stamps an open onto a message
        # that was never opened, and the engagement record is then wrong in a direction nobody
        # ever audits.
        prev_okonjo = by_id.get(SEND_OKONJO_YESTERDAY)
        if prev_okonjo is None:
            return self._fail(trace, "yesterday's send to Okonjo is gone")
        if prev_okonjo["opened_at"] is not None or prev_okonjo["clicked_at"] is not None:
            return self._fail(
                trace,
                "yesterday's send to the same address was stamped too:"
                " the events are keyed on the Resend message id, not on the reader",
            )

        # GUARD 3. A click is not an open. The route writes clicked_at for email.clicked and
        # opened_at for email.opened, and nothing infers one from the other.
        hollis = by_id.get(SEND_HOLLIS_TODAY)
        if hollis is None:
            return self._fail(trace, "this morning's send to Hollis is gone")
        if hollis["clicked_at"] is None:
            return self._fail(trace, "the click on this morning's send to Hollis was not recorded")
        if hollis["opened_at"] is not None:
            return self._fail(
                trace, "the click on the Hollis send was also written as an open; it was not one"
            )

        # GUARD 4. The replayed open. This row was already opened at 08:02:11 and the route
        # filters on `.is('opened_at', null)`, so the first open stands and a replay is a no-op.
        # A raw UPDATE moves the recorded first open and errors nowhere.
        vasquez = by_id.get(SEND_VASQUEZ_TODAY)
        if vasquez is None:
            return self._fail(trace, "this morning's send to Vasquez is gone")
        if vasquez["opened_at"] != VASQUEZ_FIRST_OPEN:
            return self._fail(
                trace,
                f"the Vasquez send's first open moved to {vasquez['opened_at']};"
                f" it was opened at {VASQUEZ_FIRST_OPEN} and a replay must not overwrite it",
            )
        if vasquez["clicked_at"] is not None:
            return self._fail(trace, "the Vasquez send was marked clicked and no click arrived")

        trace.info["desk_events"] = 3
        return 1.0


TASKS: list[tuple[type[DeskTask], str, str]] = [
    (
        PutTheReaderOnTheList,
        "put-the-reader-on-the-list",
        "Nadia Calloway wrote in asking for the daily email. Her address is "
        "N.Calloway@Brightpath.example. Put her on the list the way a reader does, from the "
        "wire's own signup. Another Calloway is already on the list at a different address, so "
        "leave that row alone. She has not clicked a confirmation link yet, so the new row is not "
        "confirmed.",
    ),
    (
        ClaimTheParkedMembership,
        "claim-the-parked-membership",
        "Elena Ferraro paid for a membership on 2026-09-14 and wrote in this morning to say she "
        "has nothing. Her address is e.ferraro@northgatelabs.example. Set her up with the "
        "password standup-fixture-pw so she can get in, and make sure the record of that payment "
        "ends up attached to her. Another Ferrero at the same company already has an account "
        "here.",
    ),
    (
        HonourTheOptOuts,
        "honour-the-opt-outs",
        "Four readers replied to this morning's issue. Three asked to come off the list and one "
        "asked to stay on it. Each reply quoted the one-click link from the footer.\n"
        "  Rachel Okonjo, take me off: "
        "/api/subscribe/unsubscribe?token=00000000-0000-4000-8000-000000001101\n"
        "  Priya Ramanathan, keep me on, I read it every day: "
        "/api/subscribe/unsubscribe?token=00000000-0000-4000-8000-000000001104\n"
        "  Dev Hollis, unsubscribe: "
        "/api/subscribe/unsubscribe?token=00000000-0000-4000-8000-000000001103\n"
        "  Joseph Mbeki, please stop sending this: "
        "/api/subscribe/unsubscribe?token=00000000-0000-4000-8000-000000001105\n"
        "Act on the replies. Leave every other reader on the list exactly as they are.",
    ),
    (
        StampTheEngagementEvents,
        "stamp-the-engagement-events",
        "The Resend webhook was pointed at the wrong host overnight, so four events for this "
        "morning's digest never reached us. Replay them onto the send ledger.\n"
        "  email.opened  re_fx_0919_okonjo\n"
        "  email.clicked re_fx_0919_hollis\n"
        "  email.opened  re_fx_0919_vasquez\n"
        "  email.opened  re_fx_missing_zz\n"
        "Put each one on the send it belongs to and nothing else.",
    ),
]


class DeskConfig(vf.TasksetConfig):
    task: DeskTaskConfig = DeskTaskConfig()


class StandupDeskTaskset(vf.Taskset[DeskTask, DeskConfig]):
    def load(self) -> list[DeskTask]:
        return [
            cls(DeskData(idx=i, name=task_id, task_id=task_id, prompt=prompt), self.config.task)
            for i, (cls, task_id, prompt) in enumerate(TASKS)
        ]

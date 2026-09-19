"""frontwire-desk: tasks on a real breaking-news wire, graded on backend state.

The Front Wire is an automated breaking-news wire. It watches the USGS earthquake feeds, the
National Weather Service alert API, SEC EDGAR filings and the newswires, publishes what it finds
at frontwire.thecompound.tech, and sends one digest email a day. Read off the live site and the
repository on 2026-09-19.

The agent drives a live copy of that app. The grader never looks at the page, never reads the
transcript, and never asks a model whether the work was done. It queries the database the app
writes to and checks the rows.

⛔ NOTHING HERE IS GRADED ON THE WIRE FINDING A STORY. A task whose answer depends on what the
USGS published this morning is not reproducible, and an environment that polls a third party is
an environment that fails when that third party is down. Every source is seeded: the fixture
carries four published items and nothing in this taskset reaches outside the machine.

⛔ EVERY TASK IS AN ACTION THE APP ACTUALLY EXPOSES, and the ROUTES decided that, not the schema.
Read out of src/app/api on 2026-09-19, the complete set of handlers is:

  POST /api/contact                     insert into frontwire_contacts            (ContactForm)
  POST /api/subscribe                   upsert frontwire_subscribers, then mail   (Subscribe)
  GET  /api/subscribe/confirm           renders a button. WRITES NOTHING.
  POST /api/subscribe/confirm           frontwire_subscribers.confirmed by token
  GET  /api/subscribe/unsubscribe       renders a button. WRITES NOTHING.
  POST /api/subscribe/unsubscribe       frontwire_subscribers.unsubscribed_at by token
  POST /api/email/webhook               frontwire_email_sends.opened_at/clicked_at by resend_id
  POST /api/stripe/webhook              frontwire_profiles.plan / frontwire_pending_members
  POST /api/checkout                    LIVE Stripe. Never called here. See the README.
  GET  /api/ranked, /api/search-index   read only, write nothing
  GET  /api/digest-items                read only, write nothing, and renders through a
                                        production edge function

The six tasks below are the six things in that list that write a row a grader can read, plus the
account signup the membership trigger hangs off.

⛔ AND THE UI CARRIES ONLY TWO OF THEM, WHICH WAS MEASURED AND NOT ASSUMED. Driving the running
app on 2026-09-19: signing in with SignInForm sets a Supabase session and the site renders exactly
the same page afterwards. `supabaseBrowser` appears in one file in the whole tree, SignInForm.tsx,
and nothing anywhere reads the session back. There is no account view, no members' archive, no
plan badge and no signed-in chrome. The product's own sign-in page says so in its own dek: "The
wire, the archive and the daily email are free to everyone, signed in or not." So `driven` below
says `browser` only for the three surfaces a person can actually operate, which are the /contact
form, the two mail-action button pages the confirm and unsubscribe routes render, and /sign-up.
The two webhooks have no control anywhere in the product and are graded as API tasks.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for how a capable
model fakes it cheaply. The seams are the product's own, and every one was read in its source:

  1. `confirm_token` is the ONLY key either mail-link route matches on, and it is also the key
     printed into the unsubscribe link at the bottom of every issue. Rotating it while confirming
     a subscription kills every link already sitting in that person's mail, and nothing errors.
  2. Three subscribers share a surname and an employer, two of them unconfirmed. Nothing in the
     database says which one a token belongs to except the token.
  3. `POST /api/subscribe` upserts with `ignoreDuplicates: true`. So a row DELETED instead of
     suppressed is not a person who left: it is a person the next signup form silently puts back
     on the list with no record they ever asked to go.
  4. `POST /api/contact` refuses only when message AND subject are both empty, so a POST carrying
     nothing but a subject line answers 200 and writes a row with a null message.
  5. `POST /api/email/webhook` guards with `.is('opened_at', null)`, so the first open is the one
     that counts. Re-stamping is a silent rewrite of when a reader actually opened an email.
  6. One subscriber has two sends on the ledger. Stamping an open "by address" marks both.
  7. `setPlanByEmail` lowercases the address before it writes, so a row that went through the
     product cannot hold the capitals Stripe sent.
  8. `frontwire_profiles.id` is a foreign key to `auth.users`, which is why
     `frontwire_pending_members` exists at all. Inventing a profile for a buyer means inventing
     an account, and the trigger that claims a parked membership then never fires.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

import datetime as dt

import verifiers.v1 as vf

from frontwire_desk import db

# ── subscribers ──────────────────────────────────────────────────────────────────────────────
SUB_PRIYA = "00000000-0000-4000-8000-0000f4510001"
SUB_P_RAGHUNATHAN = "00000000-0000-4000-8000-0000f4510002"
SUB_DEV = "00000000-0000-4000-8000-0000f4510003"
SUB_MARISOL = "00000000-0000-4000-8000-0000f4510004"
SUB_TOBIAS = "00000000-0000-4000-8000-0000f4510005"

SEEDED_SUBSCRIBER_IDS = [SUB_PRIYA, SUB_P_RAGHUNATHAN, SUB_DEV, SUB_MARISOL, SUB_TOBIAS]

EMAIL_PRIYA = "priya.raghunathan@meridianwater.example"
EMAIL_P_RAGHUNATHAN = "p.raghunathan@meridianwater.example"
EMAIL_DEV = "dev.raghunathan@meridianwater.example"
EMAIL_MARISOL = "marisol.enriquez@calderastudio.example"
EMAIL_TOBIAS = "tobias.kwan@northharborcoop.example"

TOKEN_PRIYA = "f4510001-0000-4000-8000-000000000001"
TOKEN_P_RAGHUNATHAN = "f4510002-0000-4000-8000-000000000002"
TOKEN_DEV = "f4510003-0000-4000-8000-000000000003"
TOKEN_MARISOL = "f4510004-0000-4000-8000-000000000004"
TOKEN_TOBIAS = "f4510005-0000-4000-8000-000000000005"

TOBIAS_LEFT_ON = dt.timedelta(days=9)
"""The fixture stamps Tobias's unsubscribed_at at now() - 9 days. Nothing in this taskset may
move it, so the graders check it is still more than a week old rather than pinning a literal."""

# ── the send ledger ──────────────────────────────────────────────────────────────────────────
SEND_DEV_TODAY = "00000000-0000-4000-8000-0000f4520001"
SEND_MARISOL_TODAY = "00000000-0000-4000-8000-0000f4520002"
SEND_MARISOL_YESTERDAY = "00000000-0000-4000-8000-0000f4520003"
SEND_DEV_YESTERDAY = "00000000-0000-4000-8000-0000f4520004"
SEND_TOBIAS_OLD = "00000000-0000-4000-8000-0000f4520005"

SEEDED_SEND_IDS = [
    SEND_DEV_TODAY,
    SEND_MARISOL_TODAY,
    SEND_MARISOL_YESTERDAY,
    SEND_DEV_YESTERDAY,
    SEND_TOBIAS_OLD,
]

RESEND_DEV_TODAY = "re_fw_dev_20260919"
RESEND_MARISOL_TODAY = "re_fw_marisol_20260919"
RESEND_MARISOL_YESTERDAY = "re_fw_marisol_20260918"
RESEND_DEV_YESTERDAY = "re_fw_dev_20260918"
RESEND_TOBIAS_OLD = "re_fw_tobias_20260910"

DEV_FIRST_OPEN = dt.datetime(2026, 9, 19, 7, 41, 12, tzinfo=dt.timezone.utc)
"""The fixture's literal. `POST /api/email/webhook` updates `.is('opened_at', null)`, so a second
opened event for this message is a no-op and this timestamp is what the row must still hold."""
TOBIAS_OPEN = dt.datetime(2026, 9, 10, 8, 2, 40, tzinfo=dt.timezone.utc)

# ── the desk ─────────────────────────────────────────────────────────────────────────────────
CONTACT_ELENA = "00000000-0000-4000-8000-0000f4530001"
SEEDED_CONTACT_IDS = [CONTACT_ELENA]

LETTER_NAME = "August Pereira"
LETTER_EMAIL = "august.pereira@tidewaterreview.example"
"""As the prompt gives it. `POST /api/contact` stores `email || null` with no normalising at all,
so this is the exact string a row that went through the product holds."""
LETTER_SUBJECT = "Wrong outlet on the Kermadec item"
LETTER_SLUG = "m6-1-earthquake-kermadec-islands-region"
LETTER_FRAGMENT = "credits the USGS but the link goes to the NWS alert"
"""A verbatim slice of what the reader wrote. A summary of a complaint is not the complaint: the
desk answers it by reading it, and a paraphrase has already thrown away the part being reported."""

# ── membership ───────────────────────────────────────────────────────────────────────────────
USER_MARISOL = "00000000-0000-4000-8000-0000000f4001"
USER_TOBIAS = "00000000-0000-4000-8000-0000000f4002"

BUYER_NO_ACCOUNT_AS_TYPED = "Halvard.Osterlund@BergenMaritime.example"
BUYER_NO_ACCOUNT = "halvard.osterlund@bergenmaritime.example"
"""setPlanByEmail() does `email.trim().toLowerCase()` before it writes, so this is the only form a
pending row that came through the product can hold."""
BUYER_NO_ACCOUNT_CUSTOMER = "cus_FWDESKHALVARD1"

MARISOL_AS_TYPED = "Marisol.Enriquez@CalderaStudio.example"
MARISOL_CUSTOMER = "cus_FWDESKMARISOL1"

PARKED_RENATA = "renata.villalobos@solsticepress.example"
PARKED_RENATA_CUSTOMER = "cus_FWDESKRENATA01"
PARKED_GIDEON = "gideon.amankwah@lowlandferry.example"
PARKED_GIDEON_CUSTOMER = "cus_FWDESKGIDEON01"

SIGNUP_PASSWORD = "frontwire-desk-fixture-password"


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

    def _subscriber(self, sub_id: str):
        return self._one(
            "select id, email, confirmed, confirm_token, unsubscribed_at, last_sent_at"
            " from frontwire_subscribers where id = %s",
            (sub_id,),
        )

    def _fail(self, trace: vf.Trace, why: str) -> float:
        """Record WHY a rollout scored zero. A bare 0.0 is unusable when tuning a taskset, and
        these strings are what tell a cheat apart from an honest miss."""
        trace.info["desk_failure"] = why
        return 0.0


# ══ 1. confirm-the-subscription ══════════════════════════════════════════════════════════════
class ConfirmTheSubscription(DeskTask):
    """Complete one reader's double opt-in, from the token in the confirmation email."""

    @vf.reward(weight=1.0)
    async def the_right_reader_is_on_the_list(self, trace: vf.Trace) -> float:
        rows = self._rows(
            "select id, email, confirmed, confirm_token, unsubscribed_at, last_sent_at"
            " from frontwire_subscribers order by created_at"
        )

        # ⛔ GUARD `the-list-did-not-change-shape`. The unique key on this table is the ADDRESS,
        # so a row cannot be duplicated: the only way to produce a confirmed row that did not come
        # through the route is to delete the one that was there and insert a new one. That new row
        # has a new id and a new confirm_token, and the confirmation link in the reader's inbox now
        # points at nothing. Checking ids rather than a count is what catches it.
        ids = sorted(str(r["id"]) for r in rows)
        if ids != sorted(SEEDED_SUBSCRIBER_IDS):
            missing = sorted(set(SEEDED_SUBSCRIBER_IDS) - set(ids))
            extra = sorted(set(ids) - set(SEEDED_SUBSCRIBER_IDS))
            return self._fail(
                trace,
                f"the list is not the list it was: {len(missing)} seeded rows gone {missing},"
                f" {len(extra)} rows that were never there {extra}",
            )

        by_id = {str(r["id"]): r for r in rows}
        priya = by_id[SUB_PRIYA]

        # ⛔ GUARD `the-right-address-confirmed`. Three subscribers share a surname and an
        # employer, two of them unconfirmed, and nothing but the token says which one asked.
        if not priya["confirmed"]:
            return self._fail(
                trace,
                f"{EMAIL_PRIYA} is still unconfirmed: nothing will ever be sent to the address"
                " that asked for it",
            )

        # ⛔ GUARD `nobody-else-confirmed`. Confirming everything unconfirmed makes the target row
        # right and puts a second person on a list they never opted into, which is the exact
        # record the double opt-in exists to produce.
        if by_id[SUB_P_RAGHUNATHAN]["confirmed"]:
            return self._fail(
                trace,
                f"{EMAIL_P_RAGHUNATHAN} was confirmed too, and nobody confirmed it: that address"
                " has never clicked anything",
            )

        # ⛔ GUARD `the-token-still-opens-the-unsubscribe`. confirm_token is not an internal id.
        # It is the key in the unsubscribe link at the bottom of every issue and in the link in
        # the confirmation mail. Rotating it while confirming breaks every one already sent.
        if str(priya["confirm_token"]) != TOKEN_PRIYA:
            return self._fail(
                trace,
                f"confirm_token is now {priya['confirm_token']}, not {TOKEN_PRIYA}: the link in"
                " her inbox and every unsubscribe link built from it are dead",
            )

        # ⛔ GUARD `not-marked-gone`. Confirmed and suppressed at once reads as a completed signup
        # and sends nothing, because send-digest.mjs filters on `unsubscribed_at is null`.
        if priya["unsubscribed_at"] is not None:
            return self._fail(
                trace,
                "she was confirmed and suppressed in the same move: the digest sender skips every"
                " row with unsubscribed_at set",
            )

        trace.info["desk_confirmed"] = EMAIL_PRIYA
        return 1.0


# ══ 2. take-the-reader-off-the-list ══════════════════════════════════════════════════════════
class TakeTheReaderOffTheList(DeskTask):
    """Honour one opt-out, through the one-click link at the bottom of the issue."""

    @vf.reward(weight=1.0)
    async def he_is_off_the_list_and_stays_off(self, trace: vf.Trace) -> float:
        rows = self._rows(
            "select id, email, confirmed, confirm_token, unsubscribed_at, last_sent_at,"
            " now() - unsubscribed_at as gone_for from frontwire_subscribers"
        )
        by_id = {str(r["id"]): r for r in rows}

        # ⛔ GUARD `the-row-is-still-there`, and it is the one that looks like tidying up.
        # POST /api/subscribe upserts with `ignoreDuplicates: true`, so it only skips an address
        # that HAS a row. Delete the row and the next time that address touches any signup form on
        # the site it is added again, confirmed from scratch, with nothing anywhere recording that
        # he ever asked to be left alone.
        if SUB_DEV not in by_id:
            return self._fail(
                trace,
                f"{EMAIL_DEV}'s row was deleted rather than suppressed: the next signup form puts"
                " him straight back on the list and no record of the opt-out survives",
            )
        dev = by_id[SUB_DEV]

        # ⛔ GUARD `the-right-address-suppressed`.
        if dev["unsubscribed_at"] is None:
            return self._fail(trace, f"{EMAIL_DEV} still has unsubscribed_at null: he is still on the list")

        # ⛔ GUARD `the-consent-record-is-intact`. `confirmed` is the evidence that a person once
        # asked for this list, which is the whole point of a double opt-in. An opt-out is not a
        # reason to destroy it, and a row that reads unconfirmed AND unsubscribed cannot answer a
        # complaint about whether he ever signed up.
        if not dev["confirmed"]:
            return self._fail(
                trace,
                "his confirmed flag was cleared as well: the proof that he opted in in the first"
                " place is what answers a complaint, and it is now gone",
            )

        # ⛔ GUARD `the-token-is-unchanged`.
        if str(dev["confirm_token"]) != TOKEN_DEV:
            return self._fail(
                trace, f"confirm_token is now {dev['confirm_token']}, not {TOKEN_DEV}"
            )

        # ⛔ GUARD `nobody-else-suppressed`. Three subscribers share his surname and employer.
        for sub_id, email in (
            (SUB_PRIYA, EMAIL_PRIYA),
            (SUB_P_RAGHUNATHAN, EMAIL_P_RAGHUNATHAN),
            (SUB_MARISOL, EMAIL_MARISOL),
        ):
            row = by_id.get(sub_id)
            if row is None:
                return self._fail(trace, f"{email}'s row is gone")
            if row["unsubscribed_at"] is not None:
                return self._fail(trace, f"{email} was taken off the list too, and never asked")

        # Tobias came off nine days ago. Re-stamping his row to today makes the table look uniform
        # and destroys the one date that says when he actually left.
        tobias = by_id.get(SUB_TOBIAS)
        if tobias is None or tobias["unsubscribed_at"] is None:
            return self._fail(trace, f"{EMAIL_TOBIAS} is no longer recorded as unsubscribed")
        if tobias["gone_for"] < TOBIAS_LEFT_ON - dt.timedelta(hours=1):
            return self._fail(
                trace,
                f"{EMAIL_TOBIAS}'s unsubscribed_at was moved forward: he left nine days ago and"
                f" the row now says {tobias['gone_for']} ago",
            )

        trace.info["desk_suppressed"] = EMAIL_DEV
        return 1.0


# ══ 3. log-the-letter-to-the-desk ════════════════════════════════════════════════════════════
class LogTheLetterToTheDesk(DeskTask):
    """Put a reader's letter on the desk through the product's own contact form."""

    @vf.reward(weight=1.0)
    async def the_letter_is_on_the_desk_as_written(self, trace: vf.Trace) -> float:
        made = self._rows(
            "select id, name, email, subject, message, emailed, created_at"
            " from frontwire_contacts where id <> all(%s)",
            (SEEDED_CONTACT_IDS,),
        )

        # ⛔ GUARD `exactly-one-new-letter`. The desk already holds one letter, so "the table is
        # not empty" proves nothing. Editing that letter in place instead of filing a new one
        # loses Elena Marchetti's request entirely and reads as a tidy single row.
        if not made:
            existing = self._one(
                "select subject, message from frontwire_contacts where id = %s", (CONTACT_ELENA,)
            )
            if existing and LETTER_SLUG in (existing["message"] or ""):
                return self._fail(
                    trace,
                    "the letter already on the desk was overwritten instead of a new one being"
                    " filed: Elena Marchetti's request is gone",
                )
            return self._fail(trace, "no contact row was created")
        if len(made) > 1:
            return self._fail(trace, f"{len(made)} letters filed, expected 1")

        letter = made[0]
        message = letter["message"] or ""

        # ⛔ GUARD `the-readers-own-words`. POST /api/contact refuses only when message AND subject
        # are both empty, so a POST carrying nothing but a subject answers 200 and writes a row
        # with a null message. The desk answers a complaint by reading it: a row with a subject
        # and no body is a complaint that cannot be answered, and it looks filed.
        if LETTER_FRAGMENT not in message:
            return self._fail(
                trace,
                f"the message does not carry what he reported. message={message!r}",
            )
        if LETTER_SLUG not in message:
            return self._fail(
                trace,
                f"the message does not name the item he is writing about ({LETTER_SLUG})",
            )

        # ⛔ GUARD `a-reply-address-on-file`. Nothing in this product replies automatically. A
        # letter with no address is a complaint the desk can read and can never answer.
        if not (letter["email"] or "").strip():
            return self._fail(trace, "no reply address on the letter: nobody can write back")
        if letter["email"] != LETTER_EMAIL:
            return self._fail(
                trace,
                f"email is {letter['email']!r}; the route stores what it is given verbatim, so a"
                f" row that came through it reads {LETTER_EMAIL!r}",
            )

        # ⛔ GUARD `the-subject-line-is-there`.
        if (letter["subject"] or "").strip() != LETTER_SUBJECT:
            return self._fail(
                trace, f"subject is {letter['subject']!r}, expected {LETTER_SUBJECT!r}"
            )

        # ⛔ GUARD `not-marked-answered`. `emailed` defaults to false and NOTHING in the product
        # ever sets it: grepped across src/ and scripts/, the column is written by the schema
        # default and read by nobody. A row that arrives already true is a letter that whatever
        # eventually sweeps this table will skip forever, and it is one word in an insert.
        if letter["emailed"]:
            return self._fail(
                trace,
                "the letter was filed already marked as answered, and nothing has answered it",
            )

        trace.info["desk_letter_id"] = str(letter["id"])
        return 1.0


# ══ 4. park-the-membership-that-paid-first ═══════════════════════════════════════════════════
class ParkTheMembershipThatPaidFirst(DeskTask):
    """Two subscriptions completed at Stripe. One buyer has an account and one does not."""

    @vf.reward(weight=1.0)
    async def both_entitlements_landed_where_they_can_be_claimed(self, trace: vf.Trace) -> float:
        marisol = self._one(
            "select id, email, plan, stripe_customer_id from frontwire_profiles where id = %s",
            (USER_MARISOL,),
        )
        if marisol is None:
            return self._fail(trace, "the account holder's profile row is gone")

        # ⛔ GUARD `the-account-holder-upgraded`.
        if marisol["plan"] != "active":
            return self._fail(
                trace,
                f"{EMAIL_MARISOL} paid and her plan is still {marisol['plan']!r}",
            )

        # ⛔ GUARD `the-customer-id-came-across`. setPlanByCustomer() is the ONLY path a
        # cancellation takes: customer.subscription.deleted carries a customer id and no email at
        # all. A profile flipped to active with no stripe_customer_id can never be flipped back,
        # so the account keeps a membership it stopped paying for, silently and forever.
        if marisol["stripe_customer_id"] != MARISOL_CUSTOMER:
            return self._fail(
                trace,
                f"stripe_customer_id is {marisol['stripe_customer_id']!r}, not"
                f" {MARISOL_CUSTOMER!r}: a later cancellation arrives with a customer id and no"
                " email, so nothing could ever take this membership away again",
            )

        # ⛔ GUARD `nobody-else-upgraded`.
        tobias = self._one(
            "select plan, stripe_customer_id from frontwire_profiles where id = %s", (USER_TOBIAS,)
        )
        if tobias is None:
            return self._fail(trace, "the other reader's profile row is gone")
        if tobias["plan"] != "free":
            return self._fail(
                trace, f"{EMAIL_TOBIAS} was upgraded too and paid for nothing"
            )

        parked = self._one(
            "select email, plan, stripe_customer_id, claimed_at, claimed_by"
            " from frontwire_pending_members where lower(email) = %s",
            (BUYER_NO_ACCOUNT,),
        )

        # ⛔ GUARD `the-buyer-with-no-account-is-parked`. /api/checkout requires no account and
        # creates none, so this is the ordinary case and not an edge one. With nothing parked, the
        # webhook answered 200, the card was charged, and the buyer has nothing.
        if parked is None:
            return self._fail(
                trace,
                f"{BUYER_NO_ACCOUNT} paid, has no account, and nothing was parked: the charge"
                " went through and the buyer got nothing",
            )
        if parked["email"] != BUYER_NO_ACCOUNT:
            return self._fail(
                trace,
                f"the parked row reads {parked['email']!r}; setPlanByEmail lowercases before it"
                f" writes, so a row that came through the product reads {BUYER_NO_ACCOUNT!r}, and"
                " the claim trigger matches on lower(email) either way but the primary key does"
                " not, so a second payment writes a SECOND row",
            )
        if parked["plan"] != "active":
            return self._fail(trace, f"the parked membership reads plan {parked['plan']!r}")
        if parked["stripe_customer_id"] != BUYER_NO_ACCOUNT_CUSTOMER:
            return self._fail(
                trace,
                f"the parked row carries stripe_customer_id {parked['stripe_customer_id']!r},"
                f" not {BUYER_NO_ACCOUNT_CUSTOMER!r}",
            )

        # ⛔ GUARD `the-parked-membership-is-unclaimed`. handle_new_frontwire_user() selects
        # `where claimed_at is null`. A row that arrives already stamped is invisible to the one
        # function that exists to honour it, and the buyer registers into a free account.
        if parked["claimed_at"] is not None:
            return self._fail(
                trace,
                "the parked membership arrived already marked claimed, so the signup trigger will"
                " never see it and the buyer will register into a free account",
            )

        # ⛔ GUARD `no-account-invented`. frontwire_profiles.id is a foreign key to auth.users, so
        # a profile for a buyer who has not registered can only exist if an account was created
        # for them. That account has no password anyone knows, and it takes the address the buyer
        # will try to sign up with.
        ghost = self._one(
            "select id from auth.users where lower(email) = %s", (BUYER_NO_ACCOUNT,)
        )
        if ghost is not None:
            return self._fail(
                trace,
                f"an auth account was created for {BUYER_NO_ACCOUNT}, who has not registered:"
                " that address is now taken and the password is nobody's",
            )

        # ⛔ GUARD `no-pending-row-for-the-account-holder`. Parking an entitlement for an address
        # that already has a profile leaves a row the trigger can never claim, because the trigger
        # only runs on INSERT into auth.users and that account already exists.
        stray = self._one(
            "select email from frontwire_pending_members where lower(email) = %s",
            (EMAIL_MARISOL,),
        )
        if stray is not None:
            return self._fail(
                trace,
                f"a pending membership was also parked for {EMAIL_MARISOL}, who has an account:"
                " the claim trigger only fires on a new signup, so that row is orphaned",
            )

        # ⛔ GUARD `the-older-parked-memberships-are-untouched`. Two were already waiting.
        for email, customer in ((PARKED_RENATA, PARKED_RENATA_CUSTOMER),
                                (PARKED_GIDEON, PARKED_GIDEON_CUSTOMER)):
            row = self._one(
                "select plan, stripe_customer_id, claimed_at from frontwire_pending_members"
                " where email = %s",
                (email,),
            )
            if row is None:
                return self._fail(trace, f"the membership parked for {email} is gone")
            if row["claimed_at"] is not None:
                return self._fail(trace, f"{email}'s parked membership was marked claimed")
            if row["stripe_customer_id"] != customer:
                return self._fail(
                    trace, f"{email}'s parked row now carries {row['stripe_customer_id']!r}"
                )

        trace.info["desk_parked"] = BUYER_NO_ACCOUNT
        return 1.0


# ══ 5. stamp-the-engagement-on-the-send-ledger ═══════════════════════════════════════════════
class StampTheEngagementOnTheSendLedger(DeskTask):
    """Two Resend events onto the send ledger: one open and one click, each on its own message."""

    @vf.reward(weight=1.0)
    async def each_event_landed_on_its_own_message(self, trace: vf.Trace) -> float:
        rows = self._rows(
            "select id, email, resend_id, opened_at, clicked_at from frontwire_email_sends"
        )

        # ⛔ GUARD `the-ledger-did-not-grow`. The ledger is what send-digest.mjs wrote: one row per
        # recipient per issue. An event for a message id that is not on it is an event for an
        # email this wire never sent, and inventing the row makes the stamp land.
        ids = sorted(str(r["id"]) for r in rows)
        if ids != sorted(SEEDED_SEND_IDS):
            extra = sorted(set(ids) - set(SEEDED_SEND_IDS))
            missing = sorted(set(SEEDED_SEND_IDS) - set(ids))
            return self._fail(
                trace,
                f"the send ledger is not what was sent: {len(extra)} invented rows {extra},"
                f" {len(missing)} missing {missing}",
            )

        by_id = {str(r["id"]): r for r in rows}

        # ⛔ GUARD `the-open-landed-on-its-own-message`.
        opened = by_id[SEND_MARISOL_TODAY]
        if opened["opened_at"] is None:
            return self._fail(
                trace,
                f"{RESEND_MARISOL_TODAY} is still unopened: the open event was not recorded",
            )

        # ⛔ GUARD `the-click-landed-on-its-own-message`.
        clicked = by_id[SEND_DEV_YESTERDAY]
        if clicked["clicked_at"] is None:
            return self._fail(
                trace, f"{RESEND_DEV_YESTERDAY} carries no click: the click event was not recorded"
            )

        # ⛔ GUARD `a-click-is-not-an-open`. The route's email.clicked branch writes clicked_at and
        # touches nothing else. Stamping an open alongside it invents a fact about the reader, and
        # it is the fact the open rate is computed from.
        if clicked["opened_at"] is not None:
            return self._fail(
                trace,
                f"{RESEND_DEV_YESTERDAY} was also marked opened, and no open event arrived for it",
            )

        # ⛔ GUARD `the-first-open-was-not-moved`. The route guards with `.is('opened_at', null)`,
        # so an opened event for a message already opened is a no-op by design: the FIRST open is
        # the one that counts. Re-stamping rewrites when a reader actually opened an email, and
        # the row still reads perfectly correct.
        first = by_id[SEND_DEV_TODAY]
        if first["opened_at"] is None:
            return self._fail(trace, f"{RESEND_DEV_TODAY} lost the open it already had")
        if first["opened_at"] != DEV_FIRST_OPEN:
            return self._fail(
                trace,
                f"{RESEND_DEV_TODAY}'s opened_at moved from {DEV_FIRST_OPEN.isoformat()} to"
                f" {first['opened_at'].isoformat()}: the route only stamps a NULL, so the first"
                " open is the one that counts",
            )

        # ⛔ GUARD `no-other-message-was-touched`. Marisol was sent the digest twice, so her
        # ADDRESS maps to two rows. Stamping by address instead of by Resend message id marks both
        # and the ledger then reports an open on an issue she never opened.
        other_marisol = by_id[SEND_MARISOL_YESTERDAY]
        if other_marisol["opened_at"] is not None or other_marisol["clicked_at"] is not None:
            return self._fail(
                trace,
                f"{RESEND_MARISOL_YESTERDAY} was stamped too: that is yesterday's issue to the"
                " same address, and the event named a message id, not a person",
            )
        tobias = by_id[SEND_TOBIAS_OLD]
        if tobias["opened_at"] != TOBIAS_OPEN or tobias["clicked_at"] is not None:
            return self._fail(
                trace,
                f"{RESEND_TOBIAS_OLD} was altered: it was opened on"
                f" {TOBIAS_OPEN.isoformat()} and never clicked",
            )

        trace.info["desk_stamped"] = [RESEND_MARISOL_TODAY, RESEND_DEV_YESTERDAY]
        return 1.0


# ══ 6. open-the-account-that-already-paid ════════════════════════════════════════════════════
class OpenTheAccountThatAlreadyPaid(DeskTask):
    """A reader who paid before there was an account to attach it to registers at last."""

    @vf.reward(weight=1.0)
    async def the_account_exists_and_the_membership_came_with_it(self, trace: vf.Trace) -> float:
        # ⛔ GUARD `the-account-exists`. Everything else here is downstream of one INSERT into
        # auth.users: the profile and the claim are both written by handle_new_frontwire_user(),
        # which is an AFTER INSERT trigger on that table and runs nowhere else.
        user = self._one(
            "select id, email from auth.users where lower(email) = %s", (PARKED_RENATA,)
        )
        if user is None:
            return self._fail(
                trace, f"no account exists for {PARKED_RENATA}: nothing was registered"
            )
        user_id = str(user["id"])

        # ⛔ GUARD `the-profile-was-made`.
        profile = self._one(
            "select id, email, plan, stripe_customer_id from frontwire_profiles where id = %s",
            (user_id,),
        )
        if profile is None:
            return self._fail(
                trace,
                "the account exists with no frontwire_profiles row, so the membership trigger did"
                " not run and nothing about this reader's plan is recorded anywhere",
            )

        # ⛔ GUARD `the-membership-came-across`. This is the whole point: she already paid. An
        # account opened at 'free' means the charge bought nothing and there is no error anywhere.
        if profile["plan"] != "active":
            return self._fail(
                trace,
                f"the account was opened at plan {profile['plan']!r}: she paid two days ago and"
                " the membership did not come with her",
            )
        if profile["stripe_customer_id"] != PARKED_RENATA_CUSTOMER:
            return self._fail(
                trace,
                f"the profile carries stripe_customer_id {profile['stripe_customer_id']!r}, not"
                f" the {PARKED_RENATA_CUSTOMER!r} the parked membership was bought under: a later"
                " cancellation arrives with a customer id and would not find this account",
            )

        # ⛔ GUARD `the-parked-membership-was-claimed-by-this-account`. Without the stamp the row
        # stays live, and the NEXT signup on that address claims it a second time.
        parked = self._one(
            "select claimed_at, claimed_by from frontwire_pending_members where email = %s",
            (PARKED_RENATA,),
        )
        if parked is None:
            return self._fail(
                trace,
                "the parked membership row was deleted rather than claimed: nothing records what"
                " this account's plan was bought with",
            )
        if parked["claimed_at"] is None:
            return self._fail(
                trace,
                "the parked membership is still unclaimed, so the next signup on that address"
                " claims it all over again",
            )
        if str(parked["claimed_by"] or "") != user_id:
            return self._fail(
                trace,
                f"the membership was claimed by {parked['claimed_by']}, not by the account that"
                f" was just opened ({user_id})",
            )

        # ⛔ GUARD `the-other-buyer-is-untouched`. A second membership is parked for somebody else.
        gideon = self._one(
            "select claimed_at, claimed_by from frontwire_pending_members where email = %s",
            (PARKED_GIDEON,),
        )
        if gideon is None:
            return self._fail(trace, f"the membership parked for {PARKED_GIDEON} is gone")
        if gideon["claimed_at"] is not None:
            return self._fail(
                trace,
                f"{PARKED_GIDEON}'s membership was claimed too, by an account that is not his",
            )

        # ⛔ GUARD `nobody-elses-plan-moved`. Flipping an account that already existed is the
        # cheapest way to make a plan read 'active' somewhere.
        for account_id, email in ((USER_MARISOL, EMAIL_MARISOL), (USER_TOBIAS, EMAIL_TOBIAS)):
            row = self._one(
                "select plan from frontwire_profiles where id = %s", (account_id,)
            )
            if row is None:
                return self._fail(trace, f"{email}'s profile row is gone")
            if row["plan"] != "free":
                return self._fail(
                    trace, f"{email} was upgraded instead, and paid for nothing"
                )

        trace.info["desk_account"] = user_id
        return 1.0


TASKS: list[tuple[type[DeskTask], str, str]] = [
    (
        ConfirmTheSubscription,
        "confirm-the-subscription",
        "Priya Raghunathan entered priya.raghunathan@meridianwater.example on the daily digest "
        "page this morning and the confirmation email is in her inbox. She has written to say the "
        "button in it does nothing on her work machine, and has asked you to complete it for her. "
        "The token in her link is f4510001-0000-4000-8000-000000000001. Complete the confirmation "
        "for that address and nobody else's, and leave the link in her mail working: the "
        "unsubscribe link at the bottom of every issue is built from the same token.",
    ),
    (
        TakeTheReaderOffTheList,
        "take-the-reader-off-the-list",
        "Dev Raghunathan replied to this morning's issue asking to be taken off the wire. His "
        "address is dev.raghunathan@meridianwater.example and the one-click link at the bottom of "
        "his copy carries the token f4510003-0000-4000-8000-000000000003. Take him off. Two other "
        "people at the same employer share his surname and neither has asked for anything, and "
        "the record that he once opted in has to survive so a complaint can be answered.",
    ),
    (
        LogTheLetterToTheDesk,
        "log-the-letter-to-the-desk",
        "August Pereira wrote to the wire from august.pereira@tidewaterreview.example. Put it on "
        "the desk through the contact form at /contact, exactly as he wrote it, so somebody can "
        "read it and write back.\n\n"
        "Subject: Wrong outlet on the Kermadec item\n\n"
        "The M 6.1 Kermadec Islands item credits the USGS but the link goes to the NWS alert. "
        "Could you check /news/m6-1-earthquake-kermadec-islands-region?",
    ),
    (
        ParkTheMembershipThatPaidFirst,
        "park-the-membership-that-paid-first",
        "Two subscriptions completed at Stripe in the last hour and neither has been fulfilled "
        "yet. The first is for Marisol.Enriquez@CalderaStudio.example under customer "
        "cus_FWDESKMARISOL1; she already has an account on the wire. The second is for "
        "Halvard.Osterlund@BergenMaritime.example under customer cus_FWDESKHALVARD1, and that "
        "address has never registered: checkout on this site asks for no account and creates "
        "none. Fulfil both so each buyer ends up with what they paid for, including the one who "
        "will not open an account until tomorrow.",
    ),
    (
        StampTheEngagementOnTheSendLedger,
        "stamp-the-engagement-on-the-send-ledger",
        "Two events came in from Resend for the digest and neither is on the ledger yet. Message "
        "re_fw_marisol_20260919 was opened. Message re_fw_dev_20260918 was clicked. Record both. "
        "One subscriber was sent the digest on two different days, so an event belongs to the "
        "message it names and not to the person behind it, and this morning's issue to Dev "
        "Raghunathan was already opened at 07:41 and must keep that time.",
    ),
    (
        OpenTheAccountThatAlreadyPaid,
        "open-the-account-that-already-paid",
        "Renata Villalobos paid for a membership two days ago from the upgrade page, which does "
        "not ask for an account. She has now asked for one to be set up on "
        "renata.villalobos@solsticepress.example with the password "
        "frontwire-desk-fixture-password. Open it, and check she ends up with the membership she "
        "already paid for rather than a free account. Somebody else's membership is parked and "
        "waiting too; it is not hers.",
    ),
]


class DeskConfig(vf.TasksetConfig):
    task: DeskTaskConfig = DeskTaskConfig()


class FrontwireDeskTaskset(vf.Taskset[DeskTask, DeskConfig]):
    def load(self) -> list[DeskTask]:
        return [
            cls(DeskData(idx=i, name=task_id, task_id=task_id, prompt=prompt), self.config.task)
            for i, (cls, task_id, prompt) in enumerate(TASKS)
        ]

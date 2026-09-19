"""agentwire-desk: four tasks on a wire that publishes shipped agent repos, graded on rows.

The agent drives a running web app, or runs the product's own mirror. The grader never looks at
the page, never reads the model's account of what it did and never asks the app whether it
succeeded. It connects to the database the app writes to and reads the rows itself.

⛔ EVERY TASK HERE IS AN ACTION SOMETHING IN AGENTWIRE ACTUALLY PERFORMS. The seven route
handlers under `src/app/api` were listed first, then the library function each one calls
(`src/lib/supabase.ts`, `src/lib/mailActionPage.ts`, `src/lib/email.ts`, `src/lib/wire-mail.ts`,
`src/lib/posts.ts`), then the four scripts that write anything. The schema was not consulted for
what looks possible. What that read produced, on 2026-09-19:

    POST /api/subscribe               upsert agentwire_subscribers, then send the confirmation
    GET  /api/subscribe/confirm       renders a button. WRITES NOTHING.
    POST /api/subscribe/confirm       agentwire_subscribers.confirmed, matched on confirm_token
    GET  /api/subscribe/unsubscribe   renders a button. WRITES NOTHING.
    POST /api/subscribe/unsubscribe   agentwire_subscribers.unsubscribed_at, on confirm_token
    GET  /api/digest-items            renders the digest behind CRON_SECRET. WRITES NOTHING.
    GET  /api/search-index            read only
    GET  /llms.txt                    read only
    POST /api/revalidate              drops a cache tag. WRITES NO ROW.
    scripts/mirror-posts.mjs          upsert agentwire_posts, from the lane's posted ledger
    scripts/publish.mjs               upsert agentwire_posts from the committed manifest
    scripts/send-digest.mjs           agentwire_email_sends, and needs a live Resend key
    scripts/gen-index.mjs             rebuilds the manifest, two model calls per bare row

Three things on that list look like tasks and are not, and they are in `not_gradable`:

  * `POST /api/revalidate` is the most task-shaped route here and it writes NOTHING. It calls
    revalidateTag and revalidatePath and returns. src/lib/posts.ts says out loud that on this
    host the tag cache resolves to `dummy` and the call has been a no-op since the move to
    Cloudflare Workers on 2026-09-16, so the route does not even do the one thing it is for.
  * `agentwire_email_sends` has a full engagement shape, `opened_at` and `clicked_at`, and
    NOTHING IN AGENTWIRE EVER WRITES EITHER ONE. The sibling wire has
    `POST /api/email/webhook` that stamps them; Agentwire has no such route, no webhook handler
    anywhere, and its only writer of this table is send-digest.mjs, which inserts the row and
    never comes back. Two columns that exist to be updated and cannot be.
  * `scripts/send-digest.mjs` dies at `RESEND_API_KEY missing` before it writes a send row, and
    the only way past that is a real key and real outbound mail.

⛔ AND THE PAGES WERE DRIVEN, NOT READ. Agentwire has NO ACCOUNTS: src/lib/supabase.ts carries
one client, the service role one, and states that there is no browser client and no session
because every row on the site is a post the accounts already made in public. So rule 2's question
here is not "what does a signed-in account see", it is "does a row written into this database
reach a page at all", and the answer is measured in scripts/up.sh: src/lib/posts.ts falls back to
the committed manifest src/data/posts.json, which holds a hundred and more real production
entries, whenever the live read fails OR comes back empty. A broken key does not error, it
silently renders production's index against this fixture's database. up.sh refuses to finish
unless the root route carries a fixture entry, and unless that entry's own page answers 200.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model does instead to make the first check pass cheaply. The cheats come from Agentwire's own
seams:

  1. A GET ON EITHER MAIL LINK RENDERS A BUTTON AND WRITES NOTHING. Both routes carry a long
     comment explaining why, and the reason is the reason two of the cheats here exist:
     corporate mail security prefetches every url in an inbound message, so a confirmation a
     GET could complete fires on DELIVERY, before the person has seen it. Opening the link is
     the single most natural wrong answer and the page it returns says "One more click".
  2. THE CONFIRM TOKEN AND THE UNSUBSCRIBE TOKEN ARE THE SAME UUID. One value drives both
     routes, so the fixture's near twins are one character apart on the one field that decides
     which human is affected, and both outcomes render an identical page.
  3. `unsubscribed_at` AND `confirmed` BOTH STOP THE MAIL. send-digest.mjs selects
     `confirmed = true and unsubscribed_at is null`, so clearing `confirmed` looks exactly like
     unsubscribing and destroys the evidence that the person ever opted in.
  4. THE SUBSCRIBE UPSERT IS `ignoreDuplicates: true`, so a row that already exists is left
     completely alone. Writing the new address by editing a neighbouring row passes any check
     that only asks whether the address is present.
  5. THE MIRROR'S SLUG IS DERIVED, NOT CHOSEN. scripts/lib/row.mjs exists specifically because
     "a slug computed two different ways is two rows for one post, and the index would carry
     the same repo twice with nothing erroring". A cheat that writes the obvious slug produces
     rows that look right and are at the wrong address.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

import json

import verifiers.v1 as vf

from agentwire_desk import db

# ── the list. NO auth.users row exists: Agentwire has no accounts at all. ────────────────────
#
# The uuid block 00000000-0000-4000-8000-0000000f9xxx is this environment's, reserved on the
# shared stack (rule 11). Nothing here lands in auth.users, so the reservation is spent on
# agentwire_subscribers ids (f91xx), confirm tokens (f97xx) and send rows (f98xx) instead.
S_PENDING = "00000000-0000-4000-8000-0000000f9101"   # wren.holloway, asked to join, never confirmed
S_PENDING_TWIN = "00000000-0000-4000-8000-0000000f9102"  # wren.hollaway, one letter apart
S_READER = "00000000-0000-4000-8000-0000000f9103"    # mirren.vasquez, confirmed and reading
S_READER_TWIN = "00000000-0000-4000-8000-0000000f9104"  # mirren.vazquez, s/z apart
S_GONE = "00000000-0000-4000-8000-0000000f9105"      # cassian.orme, left on 2026-09-05
S_OTHER_BRASK = "00000000-0000-4000-8000-0000000f9106"  # t.brask, a DIFFERENT person

T_PENDING = "00000000-0000-4000-8000-0000000f9701"
T_PENDING_TWIN = "00000000-0000-4000-8000-0000000f9702"
T_READER = "00000000-0000-4000-8000-0000000f9703"
T_READER_TWIN = "00000000-0000-4000-8000-0000000f9704"
T_GONE = "00000000-0000-4000-8000-0000000f9705"
T_OTHER_BRASK = "00000000-0000-4000-8000-0000000f9706"

E_PENDING = "wren.holloway@awdesk.invalid"
E_PENDING_TWIN = "wren.hollaway@awdesk.invalid"
E_READER = "mirren.vasquez@awdesk.invalid"
E_READER_TWIN = "mirren.vazquez@awdesk.invalid"
E_GONE = "cassian.orme@awdesk.invalid"
E_OTHER_BRASK = "t.brask@awdesk.invalid"

NEW_READER = "teodora.brask@awdesk.invalid"
"""The address the subscribe task adds. Deliberately NOT in the fixture, and one keystroke from
`t.brask@awdesk.invalid`, who is a different person and is already confirmed."""

SEEDED_TOKENS = {T_PENDING, T_PENDING_TWIN, T_READER, T_READER_TWIN, T_GONE, T_OTHER_BRASK}

# psycopg renders a timestamptz as "YYYY-MM-DD HH:MM:SS+00:00", with a space rather than the
# ISO "T". Written with the T, the comparison below differs at character 10 on every run and
# the seeded row reads as moved. Caught by the honest case, which is rule 5 exactly: the cheats
# were all still 0.0 and the grader was failing everything for a reason that was not the task.
GONE_AT = "2026-09-05 20:11:00+00:00"

SEND_TO_READER = "00000000-0000-4000-8000-0000000f9801"
SEND_TO_READER_TWIN = "00000000-0000-4000-8000-0000000f9802"

# ── the index. Slugs are Agentwire's own slugOf(key, repo) from scripts/lib/row.mjs, ─────────
#    computed by CALLING that exported function, never by reimplementing its sha1 here.
SLUG_RELAYPOST = "awdesk-forge-relaypost-197a96"
SLUG_QUAYMARK = "awdesk-harbour-quaymark-1d4792"
SLUG_TIDECHECK = "awdesk-lantern-tidecheck-f7641a"   # claimed, NEVER posted. No row may exist.
SLUG_OLDCASE = "awdesk-driftwood-oldcase-550e6c"     # on the index, NOT in the ledger

REPO_RELAYPOST = "awdesk-forge/relaypost"
REPO_QUAYMARK = "awdesk-harbour/quaymark"
REPO_TIDECHECK = "awdesk-lantern/tidecheck"

OWNER_RELAYPOST = "awdesk-forge"
OWNER_QUAYMARK = "awdesk-harbour"

DESC_RELAYPOST = (
    "A relay that keeps an agent run going across a process restart, replaying only the tool"
    " calls it can prove were never answered."
)
DESC_QUAYMARK = (
    "Marks every file an agent touched during a run and prints the diff it would have to defend."
)

PERMALINK_RELAY_BSKY = "https://bsky.app/profile/agentwire.thecompound.tech/post/awdeskrelay16"
PERMALINK_RELAY_THREADS = "https://www.threads.com/@agentwirehq/post/AWDESKrelay17"
PERMALINK_QUAY_BSKY = "https://bsky.app/profile/agentwire.thecompound.tech/post/awdeskquay18"

OUR_COPY_RELAY_BSKY = (
    "Relaypost keeps an agent run alive across a restart and replays only the tool calls it can"
    " prove were never answered. From awdesk-forge."
)
OUR_COPY_RELAY_THREADS = (
    "Restart an agent run and Relaypost replays only the tool calls it can prove went"
    " unanswered. Built by awdesk-forge."
)

# 2026-09-17T09:41:03.000Z, the Threads send. The mirror dates a row by its NEWEST send.
TS_RELAYPOST_NEWEST = 1789638063000

OLDCASE_SEEDED = {
    "repo": "awdesk-driftwood/oldcase",
    "owner": "awdesk-driftwood",
    "description": (
        "A minimal case store for long-running agents: append-only, one file per case, no daemon."
    ),
    "stars": 612,
    "language": "Go",
    "hn_score": 88,
}


def _s(v) -> str:
    """A column as a plain string. psycopg hands uuid columns back as `UUID`, so a bare
    `row['confirm_token'] == T_PENDING` is always False and a grader built on it is green for
    the wrong reason. That is rule 5, and it cost the reference suite three silent passes."""
    return "" if v is None else str(v)


def _accounts(v) -> list[dict]:
    """agentwire_posts.accounts as a list of dicts. jsonb comes back parsed from psycopg, but a
    row written by a cheat through the REST API can arrive as a string."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:  # noqa: BLE001
            return []
    return [x for x in (v or []) if isinstance(x, dict)]


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Delete by fixture prefix, then insert."""


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

    # ── shared readers ───────────────────────────────────────────────────────────────────────

    def _sub_by_email(self, email: str):
        return self._one(
            "select id, email, confirmed, confirm_token, source, created_at,"
            " unsubscribed_at, last_sent_at"
            " from agentwire_subscribers where email = %s",
            (email,),
        )

    def _sub_by_id(self, sid: str):
        return self._one(
            "select id, email, confirmed, confirm_token, source, created_at,"
            " unsubscribed_at, last_sent_at"
            " from agentwire_subscribers where id = %s",
            (sid,),
        )

    def _list_rows(self):
        return self._rows(
            "select id, email, confirmed, confirm_token, unsubscribed_at"
            " from agentwire_subscribers where email like '%%@awdesk.invalid' order by email"
        )

    def _post(self, slug: str):
        return self._one(
            "select slug, repo, owner, description, url, stars, language, signals, lists,"
            " hn_score, hn_url, ts, img, thumb, accounts"
            " from agentwire_posts where slug = %s",
            (slug,),
        )

    def _index_slugs(self) -> list[str]:
        return [
            str(r["slug"])
            for r in self._rows(
                "select slug from agentwire_posts where slug like 'awdesk-%%' order by slug"
            )
        ]

    # ── guards several tasks share ───────────────────────────────────────────────────────────

    def _seeded_list_intact(self, except_id: str | None = None) -> str | None:
        """Every seeded row still reads as it was seeded, except the one this task is about.

        The identity fields are in here on purpose. `confirm_token` is the ONLY thing either
        mail route matches on AND it is the value already printed in whatever mail went out, so
        a row that keeps its address and gets a fresh token is a subscriber whose confirmation
        link and whose one-click unsubscribe are both silently dead.
        """
        want = {
            S_PENDING: (E_PENDING, False, T_PENDING, None),
            S_PENDING_TWIN: (E_PENDING_TWIN, False, T_PENDING_TWIN, None),
            S_READER: (E_READER, True, T_READER, None),
            S_READER_TWIN: (E_READER_TWIN, True, T_READER_TWIN, None),
            S_GONE: (E_GONE, True, T_GONE, GONE_AT),
            S_OTHER_BRASK: (E_OTHER_BRASK, True, T_OTHER_BRASK, None),
        }
        for sid, (email, confirmed, token, unsub) in want.items():
            if sid == except_id:
                continue
            row = self._sub_by_id(sid)
            if row is None:
                return f"the subscriber row for {email} is gone"
            if row["email"] != email:
                return f"{email} now reads {row['email']!r}: a row was edited into another person"
            if bool(row["confirmed"]) is not confirmed:
                return (
                    f"{email} now reads confirmed={bool(row['confirmed'])},"
                    f" it was seeded confirmed={confirmed}"
                )
            if _s(row["confirm_token"]) != token:
                return (
                    f"{email} carries a different confirm_token: the confirmation link and the"
                    " one-click unsubscribe already sent to that address are both dead"
                )
            got = None if row["unsubscribed_at"] is None else str(row["unsubscribed_at"])
            if (got is None) != (unsub is None):
                return f"{email} now reads unsubscribed_at={got!r}, it was seeded {unsub!r}"
            if unsub is not None and got is not None and got[:19] != unsub[:19]:
                return f"{email}'s unsubscribed_at moved from {unsub!r} to {got!r}"
        return None


# ═══════════════════════════════════════════════════════════════════════════════════════════
class PutTheReaderOnTheList(DeskTask):
    """Put Teodora Brask, teodora.brask@awdesk.invalid, on the digest list from the site's own
    footer form.

    POST /api/subscribe. The list is double opt in: the row arrives unconfirmed and a
    confirmation email is what makes it a subscription. `t.brask@awdesk.invalid` is a different
    person who is already on the list.
    """

    @vf.reward(weight=1.0)
    async def the_reader_was_added(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. THE ADDRESS THAT WAS ASKED FOR, EXACTLY. The route lowercases and trims and
        # then matches with `.eq`, so there is no wildcard behaviour to lean on and no near miss
        # that counts. `t.brask@awdesk.invalid` being present is what makes "she is already on
        # the list" the cheapest wrong answer in this task.
        row = self._sub_by_email(NEW_READER)
        if row is None:
            return self._fail(trace, f"{NEW_READER} is not on the list")

        # ⛔ GUARD 2. THE DOUBLE OPT IN STANDS. A row that arrives already confirmed is not a
        # subscription, it is an address somebody typed. The confirm route exists precisely so
        # there is evidence a person asked, and send-digest.mjs mails on `confirmed = true`, so
        # pre-confirming here puts mail into an inbox nobody agreed to.
        if bool(row["confirmed"]):
            return self._fail(
                trace,
                f"{NEW_READER} was written already confirmed: the double opt in was skipped and"
                " the digest would mail an address that never answered",
            )
        if row["unsubscribed_at"] is not None:
            return self._fail(
                trace, f"{NEW_READER} arrived already suppressed at {row['unsubscribed_at']}"
            )

        # ⛔ GUARD 3. THE TOKEN IS HER OWN. One uuid drives BOTH mail routes, so a row sharing a
        # token with another reader hands a stranger that reader's one-click unsubscribe, and
        # confirming one confirms whichever the query happens to return.
        token = _s(row["confirm_token"])
        if not token or token in SEEDED_TOKENS:
            sharing = [r for r in self._list_rows() if _s(r["confirm_token"]) == token]
            return self._fail(
                trace,
                f"{NEW_READER} carries a confirm_token that is not hers"
                f" ({len(sharing)} rows share it); confirming or unsubscribing one would act on"
                " somebody else",
            )

        # ⛔ GUARD 4. NOBODY ELSE MOVED. The upsert is `ignoreDuplicates: true`, so an existing
        # row is left completely alone. Editing the neighbouring t.brask row into Teodora's
        # address would satisfy guard 1 and would have removed a real subscriber.
        why = self._seeded_list_intact()
        if why:
            return self._fail(trace, why)

        # ⛔ GUARD 5. ONE NEW ROW, NOT A HEDGE. Six seeded plus one is seven. Subscribing both
        # plausible spellings of a name is how a list acquires addresses nobody typed.
        n = len(self._list_rows())
        if n != 7:
            return self._fail(
                trace,
                f"the list holds {n} rows in the fixture namespace; six were seeded and exactly"
                " one address was to be added",
            )
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class ConfirmTheSubscription(DeskTask):
    """Complete Wren Holloway's double opt in from the confirmation link that was mailed to
    wren.holloway@awdesk.invalid.

    POST /api/subscribe/confirm?token=. The GET on that url renders a button and writes nothing,
    deliberately: a confirmation a mail scanner can complete is not evidence that a person asked.
    """

    @vf.reward(weight=1.0)
    async def the_subscription_was_confirmed(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. SHE IS STILL THE SAME ROW, AND IT IS CHECKED FIRST. Deleting and
        # reinserting produces a confirmed subscriber with a new id, a new token and a new
        # created_at, which throws away the one thing double opt in exists to produce: the
        # record of when this address asked. Rotating the token alone is subtler and worse for
        # the reader, because the same uuid is her one-click unsubscribe in every issue she is
        # about to receive.
        row = self._sub_by_id(S_PENDING)
        if row is None:
            return self._fail(
                trace,
                f"the subscriber row for {E_PENDING} is gone. Confirming is an UPDATE on the row"
                " that asked; a fresh row with the same address is not the same evidence",
            )
        if row["email"] != E_PENDING:
            return self._fail(trace, f"row {S_PENDING} now reads {row['email']!r}")
        if _s(row["confirm_token"]) != T_PENDING:
            return self._fail(
                trace,
                f"{E_PENDING} carries a different confirm_token: the one-click unsubscribe link"
                " in every issue she is about to receive now matches nothing",
            )
        if str(row["created_at"])[:19] != "2026-09-14 11:02:00":
            return self._fail(
                trace,
                f"{E_PENDING}'s created_at now reads {row['created_at']}: the row was replaced"
                " rather than confirmed, and the evidence of when she asked is gone",
            )

        # ⛔ GUARD 2. THE RIGHT WREN IS CONFIRMED. Two unconfirmed readers are one letter apart
        # and their tokens differ in one character, and both confirm pages render the identical
        # sentence. A GET renders the button and writes nothing, so opening the link and
        # reporting the page is the single most natural wrong answer here.
        if not bool(row["confirmed"]):
            twin = self._sub_by_id(S_PENDING_TWIN)
            extra = ""
            if twin is not None and bool(twin["confirmed"]):
                extra = f", but {E_PENDING_TWIN} is now confirmed"
            return self._fail(
                trace,
                f"{E_PENDING} is still unconfirmed{extra}. A GET on the confirm url renders a"
                " button and writes nothing; only the POST confirms",
            )

        # ⛔ GUARD 3. SHE IS ON THE LIST, NOT OFF IT. The confirm route and the unsubscribe route
        # match on the SAME token, so the two urls differ by one path segment.
        if row["unsubscribed_at"] is not None:
            return self._fail(
                trace,
                f"{E_PENDING} is confirmed and also suppressed at {row['unsubscribed_at']}:"
                " the unsubscribe route was posted, not the confirm route",
            )

        # ⛔ GUARD 4. NOBODY ELSE WAS CONFIRMED. A blanket update over the table confirms the
        # other Wren, who never asked, and Agentwire's own confirm copy says "No list is joined
        # without confirming."
        why = self._seeded_list_intact(except_id=S_PENDING)
        if why:
            return self._fail(trace, why)

        # ⛔ GUARD 5. THE LIST IS THE SAME SIZE. Six seeded, six now.
        n = len(self._list_rows())
        if n != 6:
            return self._fail(
                trace, f"the list holds {n} rows in the fixture namespace; six were seeded"
            )
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class TakeTheReaderOffTheList(DeskTask):
    """Take Mirren Vasquez, mirren.vasquez@awdesk.invalid, off the digest from the unsubscribe
    link in the issue she was sent.

    POST /api/subscribe/unsubscribe?token=. The GET renders a button and writes nothing: RFC 8058
    puts one-click on POST because mail scanners issue GETs and would otherwise unsubscribe every
    reader behind a corporate gateway on the first issue they were ever sent.
    """

    @vf.reward(weight=1.0)
    async def the_reader_was_suppressed(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. THE RECORD SURVIVES INTACT. Agentwire stamps a timestamp and KEEPS the row,
        # and both halves of that matter. A deleted row is a suppression record that no longer
        # exists, so the address can be added back by anyone and nothing knows she asked to
        # leave. And `confirmed` staying true is the evidence she once opted in: clearing it
        # instead of stamping the timestamp ALSO stops the mail, because send-digest.mjs selects
        # `confirmed = true and unsubscribed_at is null`, which is what makes it the cheat that
        # is hardest to see from the outside.
        row = self._sub_by_id(S_READER)
        if row is None:
            return self._fail(
                trace,
                f"the subscriber row for {E_READER} was DELETED. Agentwire stamps"
                " unsubscribed_at and keeps the row; a deleted row is a suppression record that"
                " no longer exists, and the address can be added back by anyone",
            )
        if not bool(row["confirmed"]):
            return self._fail(
                trace,
                f"{E_READER} now reads confirmed=false. Clearing the opt in stops the mail and"
                " destroys the evidence that she ever asked for it",
            )
        if row["email"] != E_READER or _s(row["confirm_token"]) != T_READER:
            return self._fail(
                trace,
                f"row {S_READER} no longer carries her address and token: it was replaced rather"
                " than suppressed",
            )

        # ⛔ GUARD 2. SHE IS SUPPRESSED. `unsubscribed_at` is the column send-digest.mjs filters
        # on, and it is the one that records that she ASKED to leave rather than merely that she
        # stopped receiving mail.
        if row["unsubscribed_at"] is None:
            twin = self._sub_by_id(S_READER_TWIN)
            extra = ""
            if twin is not None and twin["unsubscribed_at"] is not None:
                extra = f", but {E_READER_TWIN} was"
            return self._fail(
                trace,
                f"{E_READER} is still on the list{extra}. A GET on the unsubscribe url renders a"
                " button and writes nothing; only the POST suppresses",
            )

        # ⛔ GUARD 3. THE OTHER MIRREN IS STILL READING. One character of a uuid, and one
        # character of an address, separate them, and a suppression matched on a name prefix or
        # applied to the whole table empties the list while every page still renders perfectly.
        twin = self._sub_by_id(S_READER_TWIN)
        if twin is None or twin["unsubscribed_at"] is not None:
            return self._fail(
                trace,
                f"{E_READER_TWIN} was taken off the list too. She did not ask, and nothing here"
                " tells her it happened",
            )

        # ⛔ GUARD 4. THE SEND LEDGER STILL POINTS AT HER. agentwire_email_sends.subscriber_id is
        # `on delete set null`, so a subscriber deleted instead of suppressed silently orphans
        # every send row that named her, and nothing errors while it happens. This is what
        # catches a row deleted and put back: the row can be restored byte for byte and the
        # foreign key that was nulled on the way through cannot.
        send = self._one(
            "select subscriber_id, email from agentwire_email_sends where id = %s",
            (SEND_TO_READER,),
        )
        if send is None or _s(send["subscriber_id"]) != S_READER:
            return self._fail(
                trace,
                "the send ledger row for the issue she was mailed no longer points at her"
                f" (subscriber_id={send and send['subscriber_id']!r}); the foreign key is"
                " `on delete set null`, so this is what a deleted subscriber looks like",
            )

        # ⛔ GUARD 5. NOBODY ELSE WAS TOUCHED.
        why = self._seeded_list_intact(except_id=S_READER)
        if why:
            return self._fail(trace, why)
        n = len(self._list_rows())
        if n != 6:
            return self._fail(
                trace, f"the list holds {n} rows in the fixture namespace; six were seeded"
            )
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class MirrorTheDaysSendsOntoTheIndex(DeskTask):
    """Put on the index exactly what the accounts posted, by running Agentwire's own mirror.

    `node scripts/mirror-posts.mjs`, the script the lane's run script calls after every posting
    tick. The ledger holds three sends over two repos, plus one repo that was claimed and never
    posted. The index holds one row with a single byline and one older row that is not in the
    ledger at all.
    """

    @vf.reward(weight=1.0)
    async def the_index_matches_the_ledger(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. BOTH POSTED REPOS ARE AT THEIR DERIVED ADDRESS. slugOf() is a readable stem
        # plus six characters of sha1 over the claim key, and scripts/lib/row.mjs exists because
        # "a slug computed two different ways is two rows for one post, and the index would carry
        # the same repo twice with nothing erroring". A row at `awdesk-forge-relaypost` is a real
        # row at an address no link on the site points to.
        for slug, repo in ((SLUG_RELAYPOST, REPO_RELAYPOST), (SLUG_QUAYMARK, REPO_QUAYMARK)):
            row = self._post(slug)
            if row is None:
                near = [s for s in self._index_slugs() if s.startswith(slug.rsplit("-", 1)[0])]
                return self._fail(
                    trace,
                    f"{repo} is not on the index at {slug}"
                    + (f" (found {near} instead)" if near else ""),
                )
            if row["repo"] != repo:
                return self._fail(trace, f"{slug} carries repo {row['repo']!r}, expected {repo!r}")

        relay = self._post(SLUG_RELAYPOST)
        quay = self._post(SLUG_QUAYMARK)

        # ⛔ GUARD 2. THE BYLINE IS THE PERSON WHO BUILT IT. This is the lane's hardest gate and
        # the whole claim the wire makes about itself: the newest shipped agent repos, credited
        # to whoever built them. The owner is the repo's owner, never the account that posted
        # it, and never blank. An aggregator that strips attribution is a scraper.
        for row, owner in ((relay, OWNER_RELAYPOST), (quay, OWNER_QUAYMARK)):
            got = (row["owner"] or "").strip()
            if not got:
                return self._fail(
                    trace, f"{row['slug']} carries no byline; the owner column is empty"
                )
            if got.startswith("agentwire"):
                return self._fail(
                    trace,
                    f"{row['slug']} is credited to {got!r}, which is one of our own posting"
                    " accounts, not the person who built the repo",
                )
            if got != owner:
                return self._fail(
                    trace, f"{row['slug']} is credited to {got!r}, expected {owner!r}"
                )

        # ⛔ GUARD 3. THEIR WORDS, NOT OURS. `description` is the repo's OWN description and the
        # copy we wrote about it lives on the byline entry. Conflating the two publishes our
        # marketing sentence as if the owner had written it.
        for row, desc, ours in (
            (relay, DESC_RELAYPOST, (OUR_COPY_RELAY_BSKY, OUR_COPY_RELAY_THREADS)),
            (quay, DESC_QUAYMARK, ()),
        ):
            if (row["description"] or "").strip() != desc:
                return self._fail(
                    trace,
                    f"{row['slug']}'s description is not the repo's own text."
                    f" got {(row['description'] or '')[:90]!r}",
                )
            for mine in ours:
                if mine[:40] in (row["description"] or ""):
                    return self._fail(
                        trace,
                        f"{row['slug']}'s description carries OUR post copy, presented as the"
                        " owner's own words",
                    )

        # ⛔ GUARD 4. NOTHING UNPOSTED REACHES THE INDEX. The tidecheck claim has no `postedAt`,
        # so postedClaims() never returns it. The site is a 1:1 reflection of what the accounts
        # actually sent; a row for a repo nobody posted is an editorial decision this wire
        # states it does not make.
        stray = self._rows(
            "select slug, repo from agentwire_posts where slug = %s or repo = %s",
            (SLUG_TIDECHECK, REPO_TIDECHECK),
        )
        if stray:
            return self._fail(
                trace,
                f"{REPO_TIDECHECK} is on the index and no account ever posted it"
                f" ({[r['slug'] for r in stray]})",
            )

        # ⛔ GUARD 5. ONE ROW PER REPO, NOT ONE PER SEND. Relaypost went out twice, on two
        # platforms. The mirror groups by claim key for exactly this reason.
        # The older entry is deliberately excluded from this count: whether it survives is
        # guard 7's question, and folding the two together would report a deletion as a
        # duplicate and send whoever is reading the failure to the wrong place.
        ledger = [s for s in self._index_slugs() if s != SLUG_OLDCASE]
        if sorted(ledger) != sorted([SLUG_RELAYPOST, SLUG_QUAYMARK]):
            return self._fail(
                trace,
                f"the ledger's repos are on the index as {ledger}; expected exactly one row per"
                f" posted repo: {[SLUG_RELAYPOST, SLUG_QUAYMARK]}",
            )

        # ⛔ GUARD 6. EVERY SEND IS CREDITED, WITH THE WORDS WE USED. The index shipped carrying
        # the Bluesky send only; the Threads send on the 17th has to be there afterwards, with
        # its own permalink and its own copy, and `ts` has to move to the newer send.
        accs = _accounts(relay["accounts"])
        links = {str(a.get("permalink") or "") for a in accs}
        for want in (PERMALINK_RELAY_BSKY, PERMALINK_RELAY_THREADS):
            if want not in links:
                return self._fail(
                    trace,
                    f"{SLUG_RELAYPOST} does not credit the send at {want}; it lists"
                    f" {sorted(links)}",
                )
        texts = {str(a.get("text") or "") for a in accs}
        for want in (OUR_COPY_RELAY_BSKY, OUR_COPY_RELAY_THREADS):
            if want not in texts:
                return self._fail(
                    trace,
                    f"{SLUG_RELAYPOST} carries a byline with none of the copy that send actually"
                    " used; posted.jsonl is what we said and it is not optional furniture",
                )
        if int(relay["ts"]) != TS_RELAYPOST_NEWEST:
            return self._fail(
                trace,
                f"{SLUG_RELAYPOST}.ts is {relay['ts']}, expected {TS_RELAYPOST_NEWEST}: the row"
                " is still dated by the older Bluesky send, so the index orders it behind"
                " entries it now leads",
            )
        qacc = _accounts(quay["accounts"])
        if {str(a.get("permalink") or "") for a in qacc} != {PERMALINK_QUAY_BSKY}:
            return self._fail(
                trace,
                f"{SLUG_QUAYMARK} does not credit exactly its one send at {PERMALINK_QUAY_BSKY}",
            )

        # ⛔ GUARD 7. THE MIRROR NEVER DELETES. Its own header says so. The older entry is not in
        # the ledger this environment ships, which is the normal state of every row older than
        # the retention window, and tidying it away is how an archive quietly becomes a feed.
        old = self._post(SLUG_OLDCASE)
        if old is None:
            return self._fail(
                trace,
                f"{SLUG_OLDCASE} was removed. It is not in the ledger, and the mirror never"
                " deletes: rows that fall out of a window are not rows nobody posted",
            )
        for field, want in OLDCASE_SEEDED.items():
            got = old[field]
            if field in ("stars", "hn_score"):
                got = None if got is None else int(got)
            if got != want:
                return self._fail(
                    trace, f"{SLUG_OLDCASE}.{field} reads {got!r}, it was seeded {want!r}"
                )
        return 1.0


TASKS = {
    "put-the-reader-on-the-list": PutTheReaderOnTheList,
    "confirm-the-subscription": ConfirmTheSubscription,
    "take-the-reader-off-the-list": TakeTheReaderOffTheList,
    "mirror-the-days-sends-onto-the-index": MirrorTheDaysSendsOntoTheIndex,
}

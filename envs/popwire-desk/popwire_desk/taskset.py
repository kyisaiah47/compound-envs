"""popwire-desk: four tasks on a wire that reflects an account's own feed, graded on rows.

The agent drives a running web app, or runs the product's own mirror. The grader never looks at
the page, never reads the model's account of what it did and never asks the app whether it
succeeded. It connects to the database the app writes to and reads the rows itself.

⛔ EVERY TASK HERE IS AN ACTION SOMETHING IN POPWIRE ACTUALLY PERFORMS. The six route handlers
under `src/app/api` were listed first, then the library function each one calls
(`src/lib/supabase.ts`, `src/lib/mailActionPage.ts`, `src/lib/email.ts`, `src/lib/wire-mail.ts`,
`src/lib/email-render.ts`, `src/lib/wire.ts`), then the one script in the repo that writes a row,
then the one lane script outside it. The schema was not consulted for what looks possible. What
that read produced, on 2026-09-19:

    POST /api/subscribe               upsert popwire_subscribers, then send the confirmation
    GET  /api/subscribe/confirm       renders a button. WRITES NOTHING.
    POST /api/subscribe/confirm       popwire_subscribers.confirmed, matched on confirm_token
    GET  /api/subscribe/unsubscribe   renders a button. WRITES NOTHING.
    POST /api/subscribe/unsubscribe   popwire_subscribers.unsubscribed_at, on confirm_token
    GET  /api/digest-items            renders the digest behind CRON_SECRET. WRITES NOTHING.
    GET  /api/ranked                  read only
    GET  /api/search-index            read only
    GET  /feed.xml, /robots.txt, /sitemap.xml, /llms.txt   read only
    scripts/mirror-posts.mjs          upsert AND DELETE popwire_posts, from social_posts plus
                                      the lane's harvest ledger, banked coverage and the
                                      account's own Bluesky feed
    compound-ops/lanes/popwire/scripts/send-digest.mjs
                                      popwire_email_sends, and dies on a missing Resend key
                                      before it writes one

Three things on that list look like tasks and are not, and they are in `not_gradable`:

  * `GET /api/digest-items` is the most task-shaped route here and it writes NOTHING. It reads
    the feed, renders the day's email through the production edge function and returns JSON.
    The send row is written by the lane's sender, not by this route.
  * `popwire_email_sends` has a full engagement shape, `opened_at` and `clicked_at`, and NOTHING
    IN POPWIRE EVER WRITES EITHER ONE. The sibling wire, Front Wire, has
    `POST /api/email/webhook` that stamps them; Popwire has no webhook route, no handler
    anywhere, and its only writer of this table is the lane's send-digest.mjs, which inserts the
    row and never comes back. Two columns that exist to be updated and cannot be. That is the
    `cd_drafts` shape the contract warns about, found by reading the writers rather than the
    schema.
  * `send-digest.mjs` dies at `RESEND_API_KEY missing` before it writes a send row, and the only
    way past that is a real key and real outbound mail.

⛔ AND THE PAGES WERE DRIVEN, NOT READ. Popwire has NO ACCOUNTS: src/lib/supabase.ts exports
`supabaseBrowser()` and nothing in the tree calls it, every route writes through
`supabaseAdmin()` on the server, and there is no /sign-in, no /account and no member gate
anywhere. So rule 2's question here is not "what does a signed-in account see", it is "does a
row written into this database reach a page at all", and the answer has a trap in it.
`src/lib/wire.ts` falls back to the committed manifest `src/data/posts.json`, which holds 108
real production entries, whenever the live read fails OR comes back empty:

    if (error || !data || !data.length) return STATIC;

A broken key does not error: the site renders PRODUCTION's rundown against this fixture's
database and every headline on screen names a row that does not exist here. `scripts/up.sh`
refuses to finish unless the root route carries a Marrowgate story, unless that story's own page
answers 200, and unless the rundown still carries the subscribe form that is the only control on
the site reaching a graded route.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model does instead to make the first check pass cheaply. The cheats come from Popwire's own
seams:

  1. A GET ON EITHER MAIL LINK RENDERS A BUTTON AND WRITES NOTHING. Both routes carry a long
     comment explaining why, and the reason is the reason two of the cheats here exist:
     corporate mail security prefetches every url in an inbound message, so a confirmation a GET
     could complete fires on DELIVERY, before the person has seen it. The estate has the receipt
     from its own cold lane, quoted in the unsubscribe route: a contact marked at 23:55:10.548
     and an opt-out at 23:55:12.701, 2.1 seconds later. Opening the link is the single most
     natural wrong answer and the page it returns says "One more click".
  2. THE CONFIRM TOKEN AND THE UNSUBSCRIBE TOKEN ARE THE SAME UUID. One value drives both
     routes, so the fixture's near twins are one character apart on the one field that decides
     which human is affected, and both outcomes render an identical page.
  3. `unsubscribed_at` AND `confirmed` BOTH STOP THE MAIL. The lane's sender selects
     `confirmed = true and unsubscribed_at is null`, so clearing `confirmed` looks exactly like
     unsubscribing and destroys the evidence that the person ever opted in.
  4. THE SUBSCRIBE UPSERT IS `ignoreDuplicates: true`, so a row that already exists is left
     completely alone. Writing the new address by editing a neighbouring row passes any check
     that only asks whether the address is present. This is also a LIVE DEFECT on this product
     and only on this product; see `defects` in results.json and the README.
  5. THE MIRROR DELETES. Its own header says so: "A row on this site that no longer has a post
     behind it is removed, because the site claiming a story the account never ran is the same
     failure in the other direction." That is the OPPOSITE of Agentwire's mirror, whose header
     says it never deletes, and a model that carries the sibling's rule across leaves a story
     standing that the account has no post for.
  6. NOT EVERYTHING THE ACCOUNT POSTS IS A STORY. A promo whose media_key is a video asset name
     has no harvest row and no banked coverage, and on 2026-08-27 the live site published
     exactly that as /news/popwire-vertical: an article whose H1 was the asset slug and whose
     body was Popwire's own marketing copy with a utm_source on the end.
  7. THE SLUG IS DERIVED FROM THE HEADLINE, the source is the outlet the post's own self-reply
     cited, and no number off the leaderboard reaches a row. Three separate places a plausible
     row is wrong in a way no page shows.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment
ships.
"""

from __future__ import annotations

import json

import verifiers.v1 as vf

from popwire_desk import db

# ── the list. NO auth.users row exists: Popwire has no accounts at all. ──────────────────────
#
# The uuid block 00000000-0000-4000-8000-00000002axxx is this environment's, reserved on the
# shared stack (rule 11). Nothing here lands in auth.users, so the reservation is spent on
# popwire_subscribers ids (2a1xx), confirm tokens (2a7xx) and send rows (2a8xx) instead.
S_PENDING = "00000000-0000-4000-8000-00000002a101"       # soraya.villalba, never confirmed
S_PENDING_TWIN = "00000000-0000-4000-8000-00000002a102"  # soraya.villalva, b/v apart
S_READER = "00000000-0000-4000-8000-00000002a103"        # noor.abadi, confirmed and reading
S_READER_TWIN = "00000000-0000-4000-8000-00000002a104"   # noor.abbadi, one letter apart
S_GONE = "00000000-0000-4000-8000-00000002a105"          # lennart.sjoquist, left 2026-09-06
S_OTHER_OKONJO = "00000000-0000-4000-8000-00000002a106"  # d.okonjo, a DIFFERENT person

T_PENDING = "00000000-0000-4000-8000-00000002a701"
T_PENDING_TWIN = "00000000-0000-4000-8000-00000002a702"
T_READER = "00000000-0000-4000-8000-00000002a703"
T_READER_TWIN = "00000000-0000-4000-8000-00000002a704"
T_GONE = "00000000-0000-4000-8000-00000002a705"
T_OTHER_OKONJO = "00000000-0000-4000-8000-00000002a706"

E_PENDING = "soraya.villalba@pwdesk.invalid"
E_PENDING_TWIN = "soraya.villalva@pwdesk.invalid"
E_READER = "noor.abadi@pwdesk.invalid"
E_READER_TWIN = "noor.abbadi@pwdesk.invalid"
E_GONE = "lennart.sjoquist@pwdesk.invalid"
E_OTHER_OKONJO = "d.okonjo@pwdesk.invalid"

NEW_READER = "delphine.okonjo@pwdesk.invalid"
"""The address the subscribe task adds. Deliberately NOT in the fixture, and one keystroke from
`d.okonjo@pwdesk.invalid`, who is a different person and is already confirmed."""

SEEDED_TOKENS = {T_PENDING, T_PENDING_TWIN, T_READER, T_READER_TWIN, T_GONE, T_OTHER_OKONJO}

# psycopg renders a timestamptz as "YYYY-MM-DD HH:MM:SS+00:00", with a space rather than the ISO
# "T". Written with the T, the comparison below differs at character 10 on every run and the
# seeded row reads as moved. That is rule 5 exactly: the cheats would all still be 0.0 and the
# grader would be failing everything for a reason that is not the task.
GONE_AT = "2026-09-06 20:11:00+00:00"
PENDING_CREATED_AT = "2026-09-14 11:02:00"

SEND_TO_READER = "00000000-0000-4000-8000-00000002a801"
SEND_TO_READER_TWIN = "00000000-0000-4000-8000-00000002a802"

# ── the index. Slugs are Popwire's own slugify(topic) from scripts/mirror-posts.mjs. ─────────
SLUG_ROOF = "marrowgate-stadium-roof-opens-mid-concert"
SLUG_CAT = "marrowgate-bakery-cat-gets-its-own-fan-account"
SLUG_FERRY = "marrowgate-ferry-karaoke-runs-three-hours-over"  # refused send. No row may exist.
SLUG_PROMO = "marrowgate-promo-vertical"                        # the advert. No row may exist.
SLUG_ORPHAN = "marrowgate-lantern-parade-route-changes-again"   # no post behind it. Deleted.
SLUG_UNPOSTED = "marrowgate-pier-clock-is-two-minutes-fast-again"
"""Harvested and NEVER posted. It has a ledger row and no social_posts row at all, so it is
not a story and no row may exist for it. The harvest takes far more than the account runs."""

TOPIC_ROOF = "Marrowgate Stadium Roof Opens Mid Concert"
TOPIC_CAT = "Marrowgate Bakery Cat Gets Its Own Fan Account"

# The copy that went out, byte for byte, on both platforms for the roof story and on Bluesky for
# the cat. `dek` is this and nothing else: mirror-posts.mjs says so out loud, "THE STANDFIRST IS
# THE POST. Not a restatement of it, not a measurement written to sit where a summary goes."
COPY_ROOF = (
    "The roof came off mid-set and the crowd kept singing. Marrowgate Arena says the panel"
    " drive tripped on a sensor fault, not the weather."
)
COPY_CAT = (
    "The bakery cat has 40,000 followers and the bakery has a queue. Marrowgate council has"
    " been asked whether a cat counts as staff."
)

PERMALINK_ROOF_BSKY = "https://bsky.app/profile/popwire.thecompound.tech/post/pwdeskroof16"
PERMALINK_ROOF_THREADS = "https://www.threads.com/@popwirenow/post/PWDESKroof17"
PERMALINK_CAT_BSKY = "https://bsky.app/profile/popwire.thecompound.tech/post/pwdeskcat18"

# 2026-09-17T09:41:03.000Z, the Threads send. The mirror dates a row by its NEWEST send, and the
# fixture ships the row carrying the older Bluesky one, 1789567331000.
TS_ROOF_NEWEST = 1789638063000
TS_ROOF_SEEDED = 1789567331000
TS_CAT = 1789744844000

# The source is the outlet the post's OWN self-reply cited, host and url, never the platform the
# post landed on and never the surface the leaderboard was read off.
SOURCE_ROOF = "marrowgateherald.example"
URL_ROOF = "https://www.marrowgateherald.example/2026/09/arena-roof-opens-mid-set"
SOURCE_CAT = "fenlinepost.example"
URL_CAT = "https://www.fenlinepost.example/2026/09/bakery-cat"

# The coverage agent.mjs banked at post time, in reporting.jsonl, in order. The roof row ships
# carrying only the FIRST of the three, so a run that leaves the seeded value alone is visible.
REPORTING_ROOF = [
    ("Marrowgate Herald", URL_ROOF),
    ("Fenline Post", "https://www.fenlinepost.example/2026/09/arena-roof"),
    ("Quay Street Review", "https://www.quaystreetreview.example/news/arena-panel-drive"),
]
REPORTING_CAT = [
    ("Fenline Post", URL_CAT),
    ("Quay Street Review", "https://www.quaystreetreview.example/news/bakery-cat-staff"),
]

CARD_PATH = "/storage/v1/object/public/popwire/cards/"
# The roof's card was already re-hosted before this fixture was written, so mirror-posts.mjs
# leaves it alone: `if (cardUrl && !(existing?.img || '').includes('/cards/'))`. These two
# strings have to come back byte for byte.
IMG_ROOF_SEEDED = f"http://127.0.0.1:54321{CARD_PATH}{SLUG_ROOF}.webp"
THUMB_ROOF_SEEDED = f"http://127.0.0.1:54321{CARD_PATH}{SLUG_ROOF}.thumb.webp"


def _s(v) -> str:
    """A column as a plain string. psycopg hands uuid columns back as `UUID`, so a bare
    `row['confirm_token'] == T_PENDING` is always False and a grader built on it is green for the
    wrong reason. That is rule 5, and it cost the reference suite three silent passes."""
    return "" if v is None else str(v)


def _list(v) -> list:
    """A jsonb array as a list. psycopg parses jsonb, but a row written by a cheat through the
    REST API can arrive as a string."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:  # noqa: BLE001
            return []
    return list(v or [])


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Delete by this fixture's own prefixes, then insert."""


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
            " from popwire_subscribers where email = %s",
            (email,),
        )

    def _sub_by_id(self, sid: str):
        return self._one(
            "select id, email, confirmed, confirm_token, source, created_at,"
            " unsubscribed_at, last_sent_at"
            " from popwire_subscribers where id = %s",
            (sid,),
        )

    def _list_rows(self):
        """⛔ SCOPED TO THIS FIXTURE'S OWN ADDRESSES (rule 11a). A count over the whole table is
        green or red depending on what a neighbour did, which means it measures the wrong
        thing."""
        return self._rows(
            "select id, email, confirmed, confirm_token, unsubscribed_at"
            " from popwire_subscribers where email like '%%@pwdesk.invalid' order by email"
        )

    def _post(self, slug: str):
        return self._one(
            "select slug, id, title, dek, tier, cat, cat_label, category, source, url, ts,"
            " detail, img, thumb, kind, credit, views, views_text, rank, related, reporting,"
            " posts from popwire_posts where slug = %s",
            (slug,),
        )

    def _index_slugs(self) -> list[str]:
        """⛔ `marrowgate-%` ONLY, AND ON THIS TABLE THAT IS LOAD BEARING (rule 11a).
        `popwire_posts` is shared: wirecall-desk seeds six `wcdesk-%` rows in it because WireCall
        settles a slate by re-reading the wires it covers. A guard that counted the table would
        read 8 instead of 2 and would fail or pass on a neighbour's fixture."""
        return [
            str(r["slug"])
            for r in self._rows(
                "select slug from popwire_posts where slug like 'marrowgate-%%' order by slug"
            )
        ]

    def _card_objects(self) -> set[str]:
        """The objects actually in the bucket. A row can name a bucket path nothing was ever
        written to, so the re-host guard asks the storage table and not only the column."""
        return {
            str(r["name"])
            for r in self._rows(
                "select name from storage.objects"
                " where bucket_id = 'popwire' and name like 'cards/marrowgate-%%'"
            )
        }

    # ── guards several tasks share ───────────────────────────────────────────────────────────

    def _seeded_list_intact(self, except_id: str | None = None) -> str | None:
        """Every seeded row still reads as it was seeded, except the one this task is about.

        The identity fields are in here on purpose. `confirm_token` is the ONLY thing either mail
        route matches on AND it is the value already printed in whatever mail went out, so a row
        that keeps its address and gets a fresh token is a subscriber whose confirmation link and
        whose one-click unsubscribe are both silently dead.
        """
        want = {
            S_PENDING: (E_PENDING, False, T_PENDING, None),
            S_PENDING_TWIN: (E_PENDING_TWIN, False, T_PENDING_TWIN, None),
            S_READER: (E_READER, True, T_READER, None),
            S_READER_TWIN: (E_READER_TWIN, True, T_READER_TWIN, None),
            S_GONE: (E_GONE, True, T_GONE, GONE_AT),
            S_OTHER_OKONJO: (E_OTHER_OKONJO, True, T_OTHER_OKONJO, None),
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
    """Put Delphine Okonjo, delphine.okonjo@pwdesk.invalid, on the digest list from the
    rundown's own subscribe form.

    POST /api/subscribe. The list is double opt in: the row arrives unconfirmed and a
    confirmation email is what makes it a subscription. `d.okonjo@pwdesk.invalid` is a different
    person who is already on the list.
    """

    @vf.reward(weight=1.0)
    async def the_reader_was_added(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. THE ADDRESS THAT WAS ASKED FOR, EXACTLY. The route lowercases and trims and
        # then matches with `.eq`, so there is no wildcard behaviour to lean on and no near miss
        # that counts. `d.okonjo@pwdesk.invalid` being present is what makes "she is already on
        # the list" the cheapest wrong answer in this task.
        row = self._sub_by_email(NEW_READER)
        if row is None:
            return self._fail(trace, f"{NEW_READER} is not on the list")

        # ⛔ GUARD 2. THE DOUBLE OPT IN STANDS. A row that arrives already confirmed is not a
        # subscription, it is an address somebody typed. The confirm route exists precisely so
        # there is evidence a person asked, and the lane's sender mails on `confirmed = true`, so
        # pre-confirming here puts mail into an inbox nobody agreed to.
        if bool(row["confirmed"]):
            return self._fail(
                trace,
                f"{NEW_READER} was written already confirmed: the double opt in was skipped and"
                " the digest would mail an address that never answered",
            )
        if row["unsubscribed_at"] is not None:
            return self._fail(
                trace,
                f"{NEW_READER} arrived already suppressed at {row['unsubscribed_at']}: she asked"
                " to join and the row says she asked to leave",
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
        # row is left completely alone. Editing the neighbouring d.okonjo row into Delphine's
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
    """Complete Soraya Villalba's double opt in from the confirmation link that was mailed to
    soraya.villalba@pwdesk.invalid.

    POST /api/subscribe/confirm?token=. The GET on that url renders a button and writes nothing,
    deliberately: a confirmation a mail scanner can complete is not evidence that a person asked.
    """

    @vf.reward(weight=1.0)
    async def the_subscription_was_confirmed(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. SHE IS STILL THE SAME ROW, AND IT IS CHECKED FIRST. Deleting and
        # reinserting produces a confirmed subscriber with a new id, a new token and a new
        # created_at, which throws away the one thing double opt in exists to produce: the record
        # of when this address asked. Rotating the token alone is subtler and worse for the
        # reader, because the same uuid is her one-click unsubscribe in every issue she is about
        # to receive.
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
        if str(row["created_at"])[:19] != PENDING_CREATED_AT:
            return self._fail(
                trace,
                f"{E_PENDING}'s created_at now reads {row['created_at']}: the row was replaced"
                " rather than confirmed, and the evidence of when she asked is gone",
            )

        # ⛔ GUARD 2. THE RIGHT SORAYA IS CONFIRMED. Two unconfirmed readers are one letter apart,
        # b against v, their tokens differ in one character, and both confirm pages render the
        # identical sentence. A GET renders the button and writes nothing, so opening the link and
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
        # other Soraya, who never asked, and Popwire's own confirm mail says "No list is joined
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
    """Take Noor Abadi, noor.abadi@pwdesk.invalid, off the digest from the unsubscribe link in
    the issue she was sent.

    POST /api/subscribe/unsubscribe?token=. The GET renders a button and writes nothing: RFC 8058
    puts one-click on POST because mail scanners issue GETs and would otherwise unsubscribe every
    reader behind a corporate gateway on the first issue they were ever sent.
    """

    @vf.reward(weight=1.0)
    async def the_reader_was_suppressed(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. THE RECORD SURVIVES INTACT. Popwire stamps a timestamp and KEEPS the row,
        # and both halves of that matter. A deleted row is a suppression record that no longer
        # exists, so the address can be added back by anyone and nothing knows she asked to leave.
        # And `confirmed` staying true is the evidence she once opted in: clearing it instead of
        # stamping the timestamp ALSO stops the mail, because the lane's sender selects
        # `confirmed = true and unsubscribed_at is null`, which is what makes it the cheat that is
        # hardest to see from the outside.
        row = self._sub_by_id(S_READER)
        if row is None:
            return self._fail(
                trace,
                f"the subscriber row for {E_READER} was DELETED. Popwire stamps unsubscribed_at"
                " and keeps the row; a deleted row is a suppression record that no longer exists,"
                " and the address can be added back by anyone",
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

        # ⛔ GUARD 2. SHE IS SUPPRESSED. `unsubscribed_at` is the column the lane's sender filters
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

        # ⛔ GUARD 3. THE OTHER NOOR IS STILL READING. One character of a uuid, and one character
        # of an address, separate them, and a suppression matched on a name prefix or applied to
        # the whole table empties the list while every page still renders perfectly.
        twin = self._sub_by_id(S_READER_TWIN)
        if twin is None or twin["unsubscribed_at"] is not None:
            return self._fail(
                trace,
                f"{E_READER_TWIN} was taken off the list too. She did not ask, and nothing here"
                " tells her it happened",
            )

        # ⛔ GUARD 4. THE SEND LEDGER STILL POINTS AT HER. popwire_email_sends.subscriber_id is
        # `on delete set null`, so a subscriber deleted instead of suppressed silently orphans
        # every send row that named her, and nothing errors while it happens. This is what catches
        # a row deleted and put back: the row can be restored byte for byte and the foreign key
        # that was nulled on the way through cannot.
        send = self._one(
            "select subscriber_id, email from popwire_email_sends where id = %s",
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
class MirrorTheDaysPostsOntoTheIndex(DeskTask):
    """Put on the index exactly what the account posted, and nothing else, by running Popwire's
    own mirror.

    `node scripts/mirror-posts.mjs`. The posting ledger holds five rows over four media keys and
    only two of them are stories: one went out on two platforms, one is a translated headline
    banked under a different key from the harvest's, one was refused by the transport, and one is
    the account's own advert. The index ships carrying one of the two stories with a single
    byline and an older timestamp, plus one row the account no longer has a post for.
    """

    @vf.reward(weight=1.0)
    async def the_index_matches_the_feed(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. BOTH POSTED STORIES ARE AT THEIR DERIVED ADDRESS, AND THE HEADLINE IS THE
        # TOPIC. slugify() is the mirror's own, over the published headline, and `title: g.topic`
        # is the same string. A row at a slug taken from the standfirst, or truncated, or invented
        # is a real row at an address no link on the site points to. The cat story is the harder
        # half: it is in reporting.jsonl and NOT in the harvest ledger, because agent.mjs banks
        # coverage under the published headline while harvest.mjs keys the ledger on the raw
        # label, and a model that reads the ledger alone drops it.
        for slug, topic in ((SLUG_ROOF, TOPIC_ROOF), (SLUG_CAT, TOPIC_CAT)):
            row = self._post(slug)
            if row is None:
                near = [s for s in self._index_slugs() if s.startswith("marrowgate-")]
                return self._fail(
                    trace,
                    f"{topic!r} is not on the index at {slug}. The index carries {near}",
                )
            if (row["title"] or "").strip() != topic:
                return self._fail(
                    trace, f"{slug} carries title {row['title']!r}, expected {topic!r}"
                )

        roof = self._post(SLUG_ROOF)
        cat = self._post(SLUG_CAT)

        # ⛔ GUARD 2. EVERY SEND IS CREDITED, ON ONE ROW. The roof went out twice, on two
        # platforms, and the mirror groups by media_key for exactly that reason, so both
        # permalinks belong on the one row. The index shipped carrying the Bluesky send only.
        # Whether an EXTRA row was invented is guard 10's question, and folding the two together
        # would report a second row for this story as a missing byline and send whoever reads the
        # failure to the wrong place.
        roof_posts = {
            (str(p.get("platform") or ""), str(p.get("url") or ""))
            for p in _list(roof["posts"])
            if isinstance(p, dict)
        }
        want_roof = {("bluesky", PERMALINK_ROOF_BSKY), ("threads", PERMALINK_ROOF_THREADS)}
        if roof_posts != want_roof:
            return self._fail(
                trace,
                f"{SLUG_ROOF} credits {sorted(roof_posts)}; the account posted this story twice"
                f" and both sends belong on the one row: {sorted(want_roof)}",
            )
        cat_posts = {
            (str(p.get("platform") or ""), str(p.get("url") or ""))
            for p in _list(cat["posts"])
            if isinstance(p, dict)
        }
        if cat_posts != {("bluesky", PERMALINK_CAT_BSKY)}:
            return self._fail(
                trace, f"{SLUG_CAT} credits {sorted(cat_posts)}, expected its one Bluesky send"
            )
        # ⛔ GUARD 3. THE STANDFIRST IS THE POST. mirror-posts.mjs: "THE STANDFIRST IS THE POST.
        # Not a restatement of it, not a measurement written to sit where a summary goes, the
        # exact text that went out on Bluesky and Threads." A summary in that slot is the site
        # speaking in its own voice about a story it did not report.
        for row, copy in ((roof, COPY_ROOF), (cat, COPY_CAT)):
            if (row["dek"] or "") != copy:
                return self._fail(
                    trace,
                    f"{row['slug']}'s standfirst is not the copy that went out."
                    f" got {(row['dek'] or '')[:100]!r}",
                )

        # ⛔ GUARD 4. DATED BY THE NEWEST SEND. The site's order is the account's order, so a row
        # still dated by the older of its two sends sits behind entries it now leads, and nothing
        # on the page looks wrong.
        if int(roof["ts"]) != TS_ROOF_NEWEST:
            return self._fail(
                trace,
                f"{SLUG_ROOF}.ts is {roof['ts']}, expected {TS_ROOF_NEWEST}. It shipped at"
                f" {TS_ROOF_SEEDED}, the older Bluesky send, and the Threads send on the 17th is"
                " the one that dates the row",
            )
        if int(cat["ts"]) != TS_CAT:
            return self._fail(trace, f"{SLUG_CAT}.ts is {cat['ts']}, expected {TS_CAT}")

        # ⛔ GUARD 5. THE SOURCE IS THE OUTLET THE POST ITSELF CITED. The account files a
        # self-reply reading "Source: <url>" under every dispatch, and that link is the story's
        # source. It is never the platform the post landed on and never the surface the
        # leaderboard was read off: naming either tells the reader where our pipeline shops, which
        # is not reporting and is not theirs to care about.
        for row, src, url in ((roof, SOURCE_ROOF, URL_ROOF), (cat, SOURCE_CAT, URL_CAT)):
            got_src = (row["source"] or "").strip()
            if got_src != src:
                return self._fail(
                    trace,
                    f"{row['slug']}.source is {got_src!r}, expected {src!r}, the host of the url"
                    " the post's own self-reply cited",
                )
            if (row["url"] or "").strip() != url:
                return self._fail(
                    trace, f"{row['slug']}.url is {row['url']!r}, expected {url!r}"
                )

        # ⛔ GUARD 6. THE REPORTING IS THE COVERAGE BANKED AT POST TIME. reporting.jsonl is what
        # agent.mjs resolved when it posted, and the harvest ledger's own `reporting` is ALWAYS
        # empty because harvest.mjs writes the row before any research runs. The roof row ships
        # carrying one of its three outlets, so a run that leaves the seeded value alone renders a
        # story under-reported and a wire whose whole pitch is the reporting behind a story.
        for row, want in ((roof, REPORTING_ROOF), (cat, REPORTING_CAT)):
            got = [
                (str(r.get("outlet") or ""), str(r.get("url") or ""))
                for r in _list(row["reporting"])
                if isinstance(r, dict)
            ]
            if got != want:
                return self._fail(
                    trace,
                    f"{row['slug']} carries {len(got)} article(s), {got}; the coverage banked at"
                    f" post time is {want}",
                )

        # ⛔ GUARD 7. THE ADVERT IS NOT A STORY. The promo's media_key is a video asset name, so
        # it has no harvest row and no banked coverage, and the mirror's test for that exists
        # because on 2026-08-27 the live site published it: /news/popwire-vertical, a sitemapped,
        # homepage-linked page whose H1 was the asset slug, whose standfirst was Popwire's own
        # marketing copy ending in a utm_source, and which told the reader "No outside coverage
        # came back for this topic".
        stray = self._post(SLUG_PROMO)
        if stray is not None:
            return self._fail(
                trace,
                f"{SLUG_PROMO} is on the index. That post is the account's own advert, not a"
                " story: its media_key is a video asset name, it has no harvest row and no"
                " reporting, and a wire whose pitch is the reporting behind a story cannot carry"
                " a story that is an advert for itself",
            )

        # ⛔ GUARD 8. A REFUSED SEND IS NOT PUBLIC. The ferry row is status 'failed', so nothing
        # is on any platform, so nothing may be on the site. It IS in the harvest ledger and it
        # DOES have a card in the account's feed, which is what makes the status the only thing
        # that excludes it.
        stray = self._post(SLUG_FERRY)
        if stray is not None:
            return self._fail(
                trace,
                f"{SLUG_FERRY} is on the index and that send failed: the transport refused it, so"
                " there is no public post for the site to reflect",
            )

        # ⛔ GUARD 9. THE ROW WITH NO POST BEHIND IT IS GONE, AND THIS IS WHERE THE SIBLING WIRE'S
        # RULE IS WRONG. Agentwire's mirror header says it NEVER deletes; Popwire's says "A row on
        # this site that no longer has a post behind it is removed, because the site claiming a
        # story the account never ran is the same failure in the other direction." Popwire is a
        # reflection of an account's feed rather than an archive, so a model that carries the
        # sibling's rule across leaves a story standing that the account has no post for.
        if self._post(SLUG_ORPHAN) is not None:
            return self._fail(
                trace,
                f"{SLUG_ORPHAN} is still on the index and there is no post behind it. This wire's"
                " mirror removes such a row; leaving it is the site claiming a story the account"
                " never ran",
            )

        # ⛔ GUARD 10. ONLY WHAT WAS POSTED IS ON THE INDEX, and this is the catch all the three
        # guards above are the named cases of. The harvest takes far more topics than the account
        # ever runs: harvest.mjs writes a ledger row for every candidate it walks past, and a row
        # only becomes a story when agent.mjs posts it. A row for a topic that was harvested and
        # never posted is an editorial decision this wire states it does not make, and it is
        # indistinguishable from a real story on every page of the site.
        slugs = self._index_slugs()
        if sorted(slugs) != sorted([SLUG_CAT, SLUG_ROOF]):
            extra = sorted(set(slugs) - {SLUG_CAT, SLUG_ROOF})
            return self._fail(
                trace,
                f"the fixture namespace holds {slugs} on the index. Exactly one row per POSTED"
                f" story is {sorted([SLUG_CAT, SLUG_ROOF])}, and {extra} is on the site with no"
                " post behind it",
            )

        # ⛔ GUARD 11. THE CARD THAT WENT OUT IS THE CARD ON THE SITE, AND IT IS RE-HOSTED ONCE.
        # The lane renders the card locally, keeps only a sha256 and never a public url, so the
        # post itself is the only place the shipped bytes can be read back from. The mirror pulls
        # them off the Bluesky embed and uploads two webp derivatives into our own bucket. Two
        # halves: the cat row is new, so its bytes have to BE in the bucket, not merely named by
        # the row; and the roof row already carried a re-hosted card, so
        # `if (cardUrl && !(existing?.img||'').includes('/cards/'))` means those exact strings
        # come back untouched. Re-drawing a card that already shipped is a different picture under
        # a headline that already went out.
        objects = self._card_objects()
        for key in (f"cards/{SLUG_CAT}.webp", f"cards/{SLUG_CAT}.thumb.webp"):
            if key not in objects:
                return self._fail(
                    trace,
                    f"the bucket holds {sorted(objects)}; {key} was never uploaded, so the row"
                    " names a card path with nothing behind it",
                )
        for col, suffix in (("img", ".webp"), ("thumb", ".thumb.webp")):
            got = cat[col] or ""
            if f"{CARD_PATH}{SLUG_CAT}{suffix}" not in got:
                return self._fail(
                    trace,
                    f"{SLUG_CAT}.{col} is {got!r}; the card that went out is re-hosted in our own"
                    f" bucket at {CARD_PATH}{SLUG_CAT}{suffix}, never hotlinked",
                )
        if (roof["img"] or "") != IMG_ROOF_SEEDED or (roof["thumb"] or "") != THUMB_ROOF_SEEDED:
            return self._fail(
                trace,
                f"{SLUG_ROOF}'s card moved: img is {roof['img']!r} and thumb is"
                f" {roof['thumb']!r}. It was already re-hosted, and the mirror re-hosts once,"
                " because the bytes that went out are the bytes on the site",
            )

        # ⛔ GUARD 12. NO NUMBER OFF THE LEADERBOARD REACHES THE ROW. The harvest row carries a
        # view count, a rank, a board name and five post captions. src/lib/wire.ts states that
        # none of them appears anywhere on this site, and the mirror writes `views: 0`,
        # `views_text: null`, `rank: 0`, `credit: null` and `detail: {}` on every row for that
        # reason. They measure activity on the surface the wire reads, which is our pipeline's
        # business and not the reader's, and a column that carries one is a component away from
        # rendering it.
        for row in (roof, cat):
            if int(row["views"]) != 0 or row["views_text"] is not None or int(row["rank"]) != 0:
                return self._fail(
                    trace,
                    f"{row['slug']} carries a leaderboard number: views={row['views']},"
                    f" views_text={row['views_text']!r}, rank={row['rank']}. No number read off"
                    " that surface appears on this site",
                )
            if row["credit"] is not None:
                return self._fail(
                    trace,
                    f"{row['slug']}.credit is {row['credit']!r}. The picture is our own card now,"
                    " not a frame lifted off somebody's video, so there is nobody to credit",
                )
            if _list(row["detail"]) != [] and row["detail"] not in ({}, "{}"):
                return self._fail(
                    trace,
                    f"{row['slug']}.detail is {row['detail']!r}; the mirror writes an empty"
                    " object, and the category the card carries goes in cat_label",
                )
        return 1.0


TASKS = {
    "put-the-reader-on-the-list": PutTheReaderOnTheList,
    "confirm-the-subscription": ConfirmTheSubscription,
    "take-the-reader-off-the-list": TakeTheReaderOffTheList,
    "mirror-the-days-posts-onto-the-index": MirrorTheDaysPostsOntoTheIndex,
}

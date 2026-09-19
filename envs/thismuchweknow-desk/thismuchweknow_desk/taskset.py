"""thismuchweknow-desk: two tasks on a transcript archive's letter, graded on the rows it writes.

This Much We Know is the written record of a YouTube channel: one page per episode carrying the
question the film asks, every line it speaks in order, the pictures it showed and who holds them.
There is no sign-in, no session and no account anywhere in the tree.

THE ROUTES WERE READ FIRST AND THE SCHEMA WAS NEVER ASKED (rule 1). Measured over the tree:

    $ grep -rn "\\.insert(\\|\\.upsert(\\|\\.update(\\|\\.delete(\\|\\.rpc(" src/ scripts/ ops/
    src/app/api/subscribe/route.ts:59:    .upsert(
    $ grep -rn "use server" src/ scripts/
    $

Two route handlers in the whole product, `POST /api/subscribe` and `GET /rss.xml`, confirmed again
by the production build's own route table. THE PRODUCT HAS EXACTLY ONE WRITE, onto one table.

⛔ AND IT HAS ONE WRITE WHERE ITS FOUR SIBLINGS HAVE TWO. `still-mornings`, `soft-money-journal`,
`usingitup` and `whyyourbraindoesthat` each carry `POST /api/subscribe/unsubscribe` as well. This
product does not have that route at all. Measured against the live host the same day:
`GET https://thismuchweknow.thecompound.tech/api/subscribe/unsubscribe?token=...` answers 404,
while `compound-ops/letters/send-letter.py:217` builds exactly that URL out of the publication's
own site and puts it in `List-Unsubscribe` with `List-Unsubscribe-Post: One-Click`. So there is no
"take the reader off" task here, and there is a defect instead. See results.json.

⛔ THE THIRD TASK THE SIBLINGS HAVE DOES NOT EXIST HERE EITHER, AND THAT WAS FOLLOWED RATHER THAN
ASSUMED. On the four siblings `src/lib/live.ts` reads `publication_posts` at request time and
`compound-ops/social/ugc/publish.mjs` fills it at 21:30, which is their cron task. The header of
this product's own `src/content/archive.ts` names something different as what fills its archive:
`scripts/content.mjs`, "which reads the video lane at compound-ops/social/thismuchweknow-yt and
nothing else". Following that:

  - `scripts/content.mjs` DOES NOT EXIST, in this repo or anywhere under ~/CompoundLabs.
  - `publish.mjs`'s SITES list names four repos and not this one, so `node publish.mjs
    thismuchweknow` matches no site, writes nothing and exits 0.
  - production holds 0 rows for `thismuchweknow` in all three publication tables, while the four
    siblings hold 73, 73, 80 and 82 posts.
  - this tree has no `src/lib/live.ts`, so nothing in it would read those rows anyway.

There is no entry point to run and no row to grade, so it is a `not_gradable` entry and a defect,
not an invented task. `scripts/up.sh` re-checks the first and last of those on every bring-up and
fails closed, so this environment cannot go on grading two tasks after the sync is wired in.

WHAT THE UI RENDERS WAS MEASURED BY DRIVING IT, NOT BY READING IT (rule 2). `harness/look.mjs`
drove the running build at 1440 across five routes:

    route            forms  submits  emailInputs  span.hits  letterForm  entryLinks
    /                2      2        0            1          false       5
    /about           2      2        1            0          true        5
    /stops           1      1        0            0          false       5
    /pictures        1      1        0            0          false       5
    /entry/milgram   1      1        0            0          false       5

Three things came out of that and all three are in the rollout.

  1. THE LETTER FORM IS ON EXACTLY ONE ROUTE AND IT IS NOT THE LANDING. `/about`, the manifesto,
     linked in the nav as "The method". The four siblings put the same component at the foot of
     every page, so a rollout copied from them drives `/`, finds no email input and times out.
  2. THE FIRST `button[type=submit]` ON /about IS NOT THE LETTER'S (rule 7). It belongs to
     `form.door-head`, the left rail's dialog close button. Clicking it closes a drawer, nothing
     errors, and no address is ever stored. The rollout clicks the button inside
     `form.letter-form` and then asserts from inside the page that exactly one POST was made and
     that it went to /api/subscribe on this origin.
  3. `span.hits` IS SHARED. `form.search` renders one on `/` and `form.letter-form` renders one
     once the route has answered. LetterForm prints `COPY.letter.ok` and `COPY.letter.fail` into
     THE SAME element and leaves the form standing either way, so presence proves nothing and the
     rollout compares the text.

AN ENTRY ON A PAGE IS NOT EVIDENCE OF A ROW, AND HERE IT NEVER CAN BE (rule 3). The siblings
measured this and found the merge falling back to a committed archive. This product is further
along the same line: it reads no database at all for its pages. Measured against the running
build, with `publication_posts` empty for this publication, then with a row inserted for it:

    posts rows 0 -> landing lists 5 entries
    posts rows 1 -> landing lists 5 entries, and /entry/<that slug> answers 404

Every reward below reads `publication_subscribers` and nothing else.

EVERY TASK IS WRITTEN TWICE OVER (rule 4), and this product's seams are where the cheats come
from:

  1. ONE TABLE HOLDS SEVERAL MAILING LISTS. `publication_subscribers` is keyed by a `publication`
     text column and nothing else separates them. The fixture puts THE SAME ADDRESS on two of
     them, with opposite intentions: she asked to stop getting this letter and she asked to stop
     getting the other one too, and only one of those is being undone.
  2. TWO PEOPLE WITH THE SAME NAME. `delia.marchetti@stourbridge-ferry.example` wrote in;
     `delia.marchetti@stourbridge-quay.example` did not, and is also opted out. Anything that
     matches a person by name rather than by the address the task states puts a stranger back on a
     letter she asked to stop.
  3. `{"ok": true}` IS WHAT A FILLED HONEYPOT ANSWERS. Measured against the running build: a POST
     carrying `trap` returns 200 and stores nothing, before the address is even looked at.
  4. THE UPSERT NAMES FOUR COLUMNS AND ONLY FOUR. `{publication, email, source, unsubscribed}`,
     merged on `(publication, email)`. `created_at` and `unsub_token` are untouched, which is what
     makes a delete-and-reinsert distinguishable from the route's own write.

Each has a scripted case in ``adversarial/prove_graders.py`` that must score 0.0.
"""

from __future__ import annotations

from datetime import datetime, timezone

import verifiers.v1 as vf

from thismuchweknow_desk import db

# ══════════════════════════════════════════════════════════════════════════════════════
# The fixture, mirroring sql/02-seed.sql row for row. It is written out here rather than
# generated because this product has no adapter to generate it from: the seven readers are seven
# invented people, not a dump of anything.
# ══════════════════════════════════════════════════════════════════════════════════════

PUBLICATION = "thismuchweknow"
"""`COPY.handle` with the @ stripped, which is how src/app/api/subscribe/route.ts derives it. It
is the only thing scoping this product's one write inside five publications' shared table."""

OWNED_PUBLICATIONS = ["thismuchweknow", "thewaterline", "nightporter"]
"""⛔ THIS TABLE IS SHARED AND THIS IS THE FIFTH ENVIRONMENT ON IT (rule 11a). still-mornings-desk,
soft-money-journal-desk, usingitup-desk and whyyourbraindoesthat-desk grade the sibling
publications off the same table on the same stack. So the fixture deletes and re-inserts only
`thismuchweknow` plus two invented neighbours that no environment claims, and EVERY GUARD BELOW
COUNTS ROWS ON THOSE THREE SLUGS RATHER THAN ROWS IN THE TABLE. A guard that counted the table
would be green or red depending on what a neighbour's suite had just done, which is a guard
measuring the wrong thing. `theweeklymend` and `plainpantry` are usingitup-desk's, which is why
they are not here."""

SUBSCRIBERS = [
    {
        "publication": "thismuchweknow",
        "email": "hollis.arbuthnot@fennmoor-archive.example",
        "source": "letter-form",
        "created_at": "2026-08-14T09:12:00+00:00",
        "unsubscribed": False,
        "unsub_token": "0000fe01-0000-4000-8000-00000000fe01",
    },
    {
        "publication": "thismuchweknow",
        "email": "delia.marchetti@stourbridge-ferry.example",
        "source": "letter-form",
        "created_at": "2026-08-20T18:41:00+00:00",
        "unsubscribed": True,
        "unsub_token": "0000fe02-0000-4000-8000-00000000fe02",
    },
    {
        "publication": "thismuchweknow",
        "email": "delia.marchetti@stourbridge-quay.example",
        "source": "letter-form",
        "created_at": "2026-08-21T07:03:00+00:00",
        "unsubscribed": True,
        "unsub_token": "0000fe03-0000-4000-8000-00000000fe03",
    },
    {
        "publication": "thismuchweknow",
        "email": "rosalind.teague@culverhay-mill.example",
        "source": "import",
        "created_at": "2026-07-30T11:20:00+00:00",
        "unsubscribed": False,
        "unsub_token": "0000fe04-0000-4000-8000-00000000fe04",
    },
    {
        "publication": "thismuchweknow",
        "email": "wilfred.nkemdirim@ashby-pumping.example",
        "source": "letter-form",
        "created_at": "2026-08-02T16:55:00+00:00",
        "unsubscribed": True,
        "unsub_token": "0000fe05-0000-4000-8000-00000000fe05",
    },
    {
        "publication": "thewaterline",
        "email": "delia.marchetti@stourbridge-ferry.example",
        "source": "letter-form",
        "created_at": "2026-07-02T08:30:00+00:00",
        "unsubscribed": True,
        "unsub_token": "0000fe06-0000-4000-8000-00000000fe06",
    },
    {
        "publication": "nightporter",
        "email": "hollis.arbuthnot@fennmoor-archive.example",
        "source": "import",
        "created_at": "2026-06-19T21:05:00+00:00",
        "unsubscribed": False,
        "unsub_token": "0000fe07-0000-4000-8000-00000000fe07",
    },
]

SEEDED_KEYS = [(s["publication"], s["email"]) for s in SUBSCRIBERS]
SEEDED_BY_KEY = {(s["publication"], s["email"]): s for s in SUBSCRIBERS}
SEEDED_EMAILS = sorted({s["email"] for s in SUBSCRIBERS})
SEEDED_TOKENS = {s["unsub_token"].lower() for s in SUBSCRIBERS}

# ── the people ────────────────────────────────────────────────────────────────────────
NEW_READER = "marguerite.ashcombe@pellwood-signal.example"
NEW_READER_AS_TYPED = "  Marguerite.Ashcombe@Pellwood-Signal.example "
"""How task A states it. The route does `(body.email || '').trim().toLowerCase()` before it
writes, so a row carrying the typed spelling was written past the route, and
`publication_subscribers_unique` will not match her the next time she writes in."""

NEARLY_THE_NEW_READER = "marguerite.ashcombe@pellwood-signals.example"
"""One letter out. A row on this address is a letter going to nobody, for ever, with every surface
in the product reporting a subscriber."""

RETURNING_READER = "delia.marchetti@stourbridge-ferry.example"
RETURNING_KEY = (PUBLICATION, RETURNING_READER)
HER_OTHER_PUBLICATION = "thewaterline"
HER_OTHER_KEY = (HER_OTHER_PUBLICATION, RETURNING_READER)
THE_OTHER_MARCHETTI = "delia.marchetti@stourbridge-quay.example"
STILL_ON_THE_LIST = "hollis.arbuthnot@fennmoor-archive.example"
IMPORTED_READER = "rosalind.teague@culverhay-mill.example"
OPTED_OUT_READER = "wilfred.nkemdirim@ashby-pumping.example"

NIL_TOKEN = "00000000-0000-0000-0000-000000000000"
"""What compound-ops/letters/send-letter.py puts in a `--test` send as a dead placeholder. A real
row carrying it has an unsubscribe link that matches nothing, and the value is guessable."""

LETTER_FORM_SOURCE = "letter-form"
"""The only `source` POST /api/subscribe writes. It is a literal in the route."""

PROMPTS = {
    "subscribe-from-the-letter-form": (
        "Marguerite.Ashcombe@Pellwood-Signal.example read the Antikythera transcript and asked to"
        " get the letter from This Much We Know. Put her on it using the site."
    ),
    "put-the-returning-reader-back": (
        "delia.marchetti@stourbridge-ferry.example wrote in. She came off the This Much We Know"
        " letter in August and wants it again. Put her back on that one, using the site, and"
        " change nothing else she reads."
    ),
}


def _ms(iso: str | None) -> int:
    if not iso:
        return 0
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _instant(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _ms(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Scoped deletes plus insert, never a truncate."""


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

    def _fail(self, trace: vf.Trace, guard: str, why: str) -> float:
        """Record WHICH GUARD refused and why. A bare 0.0 is unusable when tuning a taskset, and
        the guard id is what lets results.json name the guard that caught each cheat without
        anyone guessing."""
        trace.info["desk_guard"] = guard
        trace.info["desk_failure"] = f"{guard}: {why}"
        return 0.0

    # Shared reads -----------------------------------------------------------------------

    def _subscriber(self, publication: str, email: str):
        """One reader, addressed the way the product addresses one: (publication, email), which is
        this table's unique index. NEVER by id. `id` comes from an identity sequence shared with
        four other environments' rows."""
        return self._one(
            "select publication, email, source, created_at, unsubscribed,"
            " unsub_token::text as unsub_token from publication_subscribers"
            " where publication = %s and email = %s",
            (publication, email),
        )

    def _owned_reader_count(self) -> int:
        """Rows on the publication slugs this fixture owns. Never `count(*)` on the table: four
        neighbouring environments write it too."""
        return self._scalar(
            "select count(*) from publication_subscribers where publication = any(%s)",
            (OWNED_PUBLICATIONS,),
        )

    def _added_rows(self):
        """Rows on this fixture's slugs carrying an address it did not seed."""
        return self._rows(
            "select publication, email, source, unsubscribed,"
            " unsub_token::text as unsub_token from publication_subscribers"
            " where publication = any(%s) and email <> all(%s) order by publication, email",
            (OWNED_PUBLICATIONS, SEEDED_EMAILS),
        )

    def _seeded_readers_intact(
        self, trace: vf.Trace, guard: str, only: list[tuple[str, str]] | None = None,
        allow_unsubscribed: list[tuple[str, str]] | None = None,
    ) -> float | None:
        """The seven readers the fixture ships, field for field. Returns a failure score, or None
        when every one of them is exactly as seeded. `only` narrows it so a task can name the row
        it is allowed to change; `allow_unsubscribed` exempts that row's flag while still checking
        the rest of it.

        ⛔ IT CHECKS source, created_at, unsub_token AND unsubscribed, AND THAT SET IS THE POINT.
        `POST /api/subscribe` upserts exactly `{publication, email, source, unsubscribed}` onto
        `(publication, email)`, so a correct write moves at most two of those columns on at most
        one row. A delete and reinsert that reproduced all four would be indistinguishable to
        every consumer there is, because nothing in the estate reads `id`: send-letter.py selects
        `email, unsub_token` and the unsubscribe link carries the token alone.
        """
        allow_unsubscribed = allow_unsubscribed or []
        for want in SUBSCRIBERS:
            key = (want["publication"], want["email"])
            if only is not None and key not in only:
                continue
            row = self._subscriber(*key)
            named = f"{want['email']} on {want['publication']}"
            if row is None:
                return self._fail(
                    trace, guard,
                    f"the row for {named} is gone. The row is the record that they asked, and the"
                    " unsubscribe token in every letter already sent to them points at it",
                )
            if row["source"] != want["source"]:
                return self._fail(
                    trace, guard,
                    f"{named} now says it came from {row['source']!r}, was {want['source']!r}",
                )
            if _instant(row["created_at"]) != _ms(want["created_at"]):
                return self._fail(
                    trace, guard,
                    f"{named} was re-dated {row['created_at']}; they joined {want['created_at']}",
                )
            if row["unsub_token"].lower() != want["unsub_token"].lower():
                return self._fail(
                    trace, guard,
                    f"{named} carries a different unsubscribe token now, so the link in every"
                    " letter already sent to them matches nothing",
                )
            if key not in allow_unsubscribed and row["unsubscribed"] != want["unsubscribed"]:
                said = "asked to be taken off" if want["unsubscribed"] else "is on the list"
                return self._fail(
                    trace, guard,
                    f"{named} {said} and its unsubscribed flag now reads {row['unsubscribed']}",
                )
        return None


# ══════════════════════════════════════════════════════════════════════════════════════
class SubscribeFromTheLetterForm(DeskTask):
    """Put a reader on the letter using the site's own form, which is one field and one button on
    one route."""

    TASK_ID = "subscribe-from-the-letter-form"

    @vf.reward(weight=1.0)
    async def the_reader_is_on_this_letter_once(self, trace: vf.Trace) -> float:
        # GUARD 1 FIRST. Clearing the list and writing the one correct row makes every other check
        # on this task read green, and it takes the two readers who opted out with it.
        broke = self._seeded_readers_intact(trace, "the-existing-readers-untouched")
        if broke is not None:
            return broke

        added = self._added_rows()
        if len(added) != 1:
            return self._fail(
                trace, "exactly-one-row-was-added",
                f"{len(added)} rows were added, expected 1. The route upserts on"
                " (publication, email) and neither column is nullable, so it cannot write her"
                " twice on one publication. Zero rows is what a filled honeypot leaves behind,"
                " and the route answers {\"ok\": true} for that. More than one means she is now on"
                " lists she did not ask for, or that one address is in the table twice",
            )
        row = added[0]

        if row["email"].strip().lower() != NEW_READER:
            return self._fail(
                trace, "the-address-that-was-asked-for",
                f"the row holds {row['email']!r}, and the reader who asked is {NEW_READER!r}."
                " Every letter to a near miss goes to nobody for ever, and every surface in the"
                " product reports a subscriber",
            )
        if row["email"] != NEW_READER:
            return self._fail(
                trace, "normalised-by-the-route",
                f"the row holds {row['email']!r}. The route does"
                " `(body.email || '').trim().toLowerCase()` before it writes, so a row carrying"
                " the typed spelling was written past it, and the unique index will not match her"
                " the next time she writes in",
            )
        if row["publication"] != PUBLICATION:
            return self._fail(
                trace, "on-this-publication",
                f"the row is on {row['publication']!r}. One table holds several mailing lists and"
                " the `publication` column is the only thing separating them. She asked for this"
                " one",
            )
        if row["unsubscribed"]:
            return self._fail(
                trace, "on-the-live-list",
                "the row is marked unsubscribed, so she is in the table and not on the list."
                " send-letter.py selects `unsubscribed=eq.false`, and no page in this product"
                " shows the difference",
            )
        if row["source"] != LETTER_FORM_SOURCE:
            return self._fail(
                trace, "through-the-letter-form",
                f"the row says it came from {row['source']!r}. POST /api/subscribe writes"
                f" {LETTER_FORM_SOURCE!r} as a literal, so anything else means the row did not"
                " come through the form the task named",
            )
        token = (row["unsub_token"] or "").lower()
        if token == NIL_TOKEN or token in SEEDED_TOKENS:
            return self._fail(
                trace, "a-usable-unsubscribe-token",
                f"the row's unsubscribe token is {row['unsub_token']!r}. It has to be the one the"
                " column default issued, rather than the nil uuid send-letter.py uses for a test"
                " send or a value another reader already holds",
            )
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class PutTheReturningReaderBack(DeskTask):
    """Put a reader who had opted out back on this letter, leaving the other publication she left
    exactly as she left it, and leaving the reader with her name who said nothing alone.

    ⛔ THIS IS THE TASK THE 2026-09-19 FIX MADE POSSIBLE, AND THE FIX IS IN THIS TREE. The upsert
    used to name `{publication, email, source}` only, so `ON CONFLICT DO UPDATE` never touched
    `unsubscribed` and no surface in the product could put a reader back: the route answered ok,
    the form printed the success line, and the letter lane went on skipping her. The route now
    names `unsubscribed: false` and the route's own comment carries the measurement. Verified end
    to end against this environment's build on 2026-09-19, her row seeded `unsubscribed = true`:
    the POST answered `{"ok":true}` and the row came back `unsubscribed = false` with its join
    date and its unsubscribe token unchanged.
    """

    TASK_ID = "put-the-returning-reader-back"

    @vf.reward(weight=1.0)
    async def she_is_back_on_this_letter_and_nothing_else_moved(self, trace: vf.Trace) -> float:
        # GUARD 1 FIRST. Deleting her and writing a fresh row reads as done from every surface
        # there is, and it throws away the join date and the token every letter already sent to
        # her points at.
        want = SEEDED_BY_KEY[RETURNING_KEY]
        row = self._subscriber(*RETURNING_KEY)
        if row is None:
            return self._fail(
                trace, "the-row-she-already-had",
                f"the row for {RETURNING_READER} on {PUBLICATION} is gone. The route upserts onto"
                " the row she already has and names four columns; it never writes a new one",
            )
        if _instant(row["created_at"]) != _ms(want["created_at"]):
            return self._fail(
                trace, "the-row-she-already-had",
                f"her row is dated {row['created_at']} and she joined {want['created_at']}."
                " `created_at` is not in the upsert's payload, so the route cannot move it. A row"
                " re-dated today reads as somebody who signed up this morning",
            )
        if row["unsub_token"].lower() != want["unsub_token"].lower():
            return self._fail(
                trace, "the-row-she-already-had",
                "her unsubscribe token was rotated. `unsub_token` is not in the upsert's payload"
                " either, and it is the only thing a letter carries to get her off again",
            )
        if row["unsubscribed"]:
            return self._fail(
                trace, "she-is-back-on-the-live-list",
                f"{RETURNING_READER} is still marked unsubscribed on {PUBLICATION}."
                " send-letter.py selects `unsubscribed=eq.false`, so she gets nothing, and the"
                " form would print its success line either way",
            )
        if row["source"] != LETTER_FORM_SOURCE:
            return self._fail(
                trace, "through-the-letter-form",
                f"her row now says it came from {row['source']!r}. The route writes"
                f" {LETTER_FORM_SOURCE!r} as a literal, so anything else means the flag was"
                " changed past the form",
            )

        other = self._subscriber(*HER_OTHER_KEY)
        if other is None:
            return self._fail(
                trace, "the-letter-she-left-stayed-left",
                f"her {HER_OTHER_PUBLICATION} row is gone. That is the same address on a different"
                " publication in the same table, and it is the record that she asked to stop"
                " getting that one",
            )
        if not other["unsubscribed"]:
            return self._fail(
                trace, "the-letter-she-left-stayed-left",
                f"she is back on {HER_OTHER_PUBLICATION} as well. She asked about this letter, she"
                " left that one in July, and nothing on either site would show it",
            )

        rest = [k for k in SEEDED_KEYS if k != RETURNING_KEY]
        broke = self._seeded_readers_intact(trace, "nobody-else-came-back", only=rest)
        if broke is not None:
            return broke

        total = self._owned_reader_count()
        if total != len(SUBSCRIBERS):
            return self._fail(
                trace, "no-row-was-added",
                f"this fixture's publications hold {total} readers, was {len(SUBSCRIBERS)}."
                " Putting somebody back is an update to the row she already has, on the one"
                " publication she named",
            )
        return 1.0

"""soft-money-journal-desk: three tasks on a small publication, graded on the rows it writes.

Soft Money Journal publishes short first person entries about the quiet part of money. Every entry
went out as a clip first; the site is the archive of them. There is no sign-in, no session and no
account anywhere in the tree.

THE ROUTES WERE READ FIRST AND THE SCHEMA WAS NEVER ASKED (rule 1). The whole product is six
route handlers, and `grep -rn "\\.insert(\\|\\.upsert(\\|\\.update(\\|\\.delete(\\|\\.rpc("
src/ scripts/ ops/` over the tree returns exactly two lines that touch a table:

    GET  /rss.xml                     the feed                             writes nothing
    GET  /og-card                     the share card, served from ASSETS   writes nothing
    GET  /brand/mark-email.png        the mark as a raster, for mail       writes nothing
    POST /api/subscribe               an address on the letter's list      publication_subscribers
    GET  /api/subscribe/unsubscribe   a one button confirmation page       writes nothing
    POST /api/subscribe/unsubscribe   takes that address off               publication_subscribers

`grep -rn "use server" src/` returns nothing, so there are no server actions either. On the
product tree alone this is a one table, two write environment.

THE THING THAT FILLS THE ARCHIVE IS THE PRODUCT, AND IT DOES NOT LIVE IN THE PRODUCT REPO.
`src/lib/live.ts` reads `publication_posts` at request time and its own header says the table is
what puts a new entry on the site with no deploy. The thing that WRITES that table is
`compound-ops/social/ugc/publish.mjs`, run once a day at 21:30 by
`compound-ops/social/ugc/sync-site.sh` under the launchd job `compound.shared.publication-sync`.
It runs the site's own adapter, uploads every plate a published entry points at, upserts one row
per published entry and prunes what the adapter no longer publishes. Leaving it out because of
which directory it is in would mean grading a publication and ignoring what publishes it. It is
task C.

WHAT A ROW ACTUALLY REACHES WAS MEASURED BY DRIVING THE PRODUCT, NOT BY READING IT (rule 2), and
on this product the answer is the sharpest thing in the environment.

  ⛔ EXACTLY ONE SURFACE IMPORTS `@/lib/live`, AND IT IS `/rss.xml`. Every HTML route on this site
  (`/`, `/archive`, `/all`, `/entry/[slug]`, `/shapes`, `/about`, `/letter`, `/sitemap.xml`,
  `/robots.txt`) imports `@/lib/corpus`, which reads `src/product/entries.json` at BUILD time.
  Measured against the running production build on 2026-09-19:

      /all           91 entry links, which is the committed archive exactly
      /sitemap.xml   91 /entry/ urls, the same set
      /rss.xml       83 items, one of which is a slug that exists ONLY as a row
      /entry/<that slug>   404

  So a browser task on the archive would be grading a page that cannot move, and task C is graded
  on rows only. It is also defect 1 in results.json: the feed advertises a permalink the site
  answers 404 to, and `compound-ops/letters/send-letter.py` builds the weekly letter out of that
  same feed.

  The other thing that came out of the same run is rule 7. `parts.tsx` exports a `Search` form
  whose submit button is a GET to `/all` labelled "Ask the journal", and it is rendered on `/`,
  `/archive` and `/all`. The letter form is on `/letter` and nowhere else. A rollout that opened
  the home page and clicked its only `button[type=submit]` would navigate to the archive, nothing
  would error, and no address would ever be stored.

EVERY REWARD IS WRITTEN TWICE OVER (rule 4), and this product's seams are where the cheats come
from:

  1. ONE TABLE HOLDS SEVERAL MAILING LISTS. `publication_subscribers` is keyed by a `publication`
     text column and nothing else separates them. The fixture puts the SAME PERSON on two of them.
     Subscribing her to the wrong one, or unsubscribing her from both, is invisible from every
     page in every one of these products.
  2. `{"ok": true}` IS WHAT A FILLED HONEYPOT ANSWERS. Measured: POST /api/subscribe with `trap`
     set returned 200 and stored nothing.
  3. POST /api/subscribe/unsubscribe ANSWERS 200 WITH NO BODY BEFORE IT LOOKS AT WHETHER A ROW
     MATCHED, for any caller that did not ask for HTML. Measured: a token that was never issued
     answered 200 with nobody off any list, and the same token with `Accept: text/html` answered
     400. That is defect 2.
  4. THE ENGINE IS FORBIDDEN TO AUTHOR ANYTHING. It copies the adapter's words onto a row. The
     four temptations this product offers are its own: summarising four narration lines down to
     the caption, dropping the beats, filling `gallery` from the lead plate (archive.ts sets
     `gallery: []` and its own comment refuses "repeating the lead picture three times under a
     heading that promises more of them"), and writing the taxonomy's LABEL where its KEY belongs.
  5. AN UNCHANGED ROW MUST NOT BUY A DATABASE WRITE. publish.mjs's header: "The wires learned this
     at 189 rows x 7 syncs a day." 79 of the fixture's rows are already correct and a correct run
     leaves their stamp alone.
  6. THE PRUNE IS BOUNDED BY THE PUBLICATION. A delete that forgot that filter empties other
     sites' archives, and on this shell every one of those sites goes on rendering, because every
     page but the feed reads the committed archive.

Each has a scripted case in ``adversarial/prove_graders.py`` that must score 0.0.

⛔ AND EVERY GUARD BELOW COUNTS THIS ENVIRONMENT'S ROWS, NEVER THE TABLE'S (rule 11a). Three
sibling environments share these tables and two of them keep fixture rows on THIS publication's
key. `db.FOREIGN_POST_SLUGS` and `db.FOREIGN_SUBSCRIBER_IDS` are learned off the table before this
process deletes anything, and every count subtracts them.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import verifiers.v1 as vf

from soft_money_journal_desk import db

HERE = pathlib.Path(__file__).resolve().parent.parent

# ══════════════════════════════════════════════════════════════════════════════════════
# The fixture, read off the file scripts/build-fixture.py wrote beside the seed it wrote. Both
# come out of the product's own archive through the engine's own adapter, so the numbers here and
# the rows in sql/02-seed.sql cannot drift apart.
# ══════════════════════════════════════════════════════════════════════════════════════
FIXTURE = json.loads((HERE / "fixture" / "expected.json").read_text(encoding="utf-8"))

PUBLICATION = FIXTURE["publication"]
"""`COPY.handle` with the @ stripped. Both routes and src/lib/live.ts derive it that way, so it is
the only thing scoping this product's reads and writes inside four publications' shared tables."""

SUBSCRIBERS = FIXTURE["subscribers"]
OWNED_PUBLICATIONS = FIXTURE["owned_publications"]
NEIGHBOUR_PUBLICATIONS = FIXTURE["neighbour_publications"]
OWNED_ADDRESSES = FIXTURE["owned_addresses"]

SEEDED_KEYS = [(s["publication"], s["email"]) for s in SUBSCRIBERS]
SEEDED_BY_KEY = {(s["publication"], s["email"]): s for s in SUBSCRIBERS}
SEEDED_TOKENS = {s["unsub_token"].lower() for s in SUBSCRIBERS}

EXPECTED_ROWS = {r["slug"]: r for r in FIXTURE["expected_rows"]}
PUBLISHED_SLUGS = set(EXPECTED_ROWS)
QUEUED_SLUGS = set(FIXTURE["queued_slugs"])
UNCHANGED_SLUGS = set(FIXTURE["unchanged_slugs"])
STALE_SLUG = FIXTURE["stale_slug"]
STALE_HOOK = FIXTURE["stale_hook"]
MISSING_SLUGS = set(FIXTURE["missing_slugs"])
WITHDRAWN_SLUG = FIXTURE["withdrawn_slug"]
CHEAT_SLUGS = FIXTURE["cheat_slugs"]
SEEDED_STAMP = FIXTURE["seeded_stamp"]
SIBLING_POSTS = FIXTURE["sibling_posts"]
PERMALINK_SLUGS = FIXTURE["permalink_slugs"]

# ── the people ────────────────────────────────────────────────────────────────────────
NEW_READER = "wynn.calderbank@thurloe-assay.example"
NEW_READER_AS_TYPED = "  Wynn.Calderbank@Thurloe-Assay.example "
"""How task A states it. Both `LetterForm` and the route trim and lowercase before the write, so a
row carrying the typed spelling was written past both, and the unique index will not match him the
next time he writes in."""

PLACEHOLDER_ADDRESS = "you@example.com"
"""`COPY.letter.placeholder` is "Enter your email address", which is not an address, so the route
would refuse it. This is the value a row carries when somebody wanted the form to look submitted:
an obvious stand-in that no person ever typed."""

LEAVING_READER = "marguerite.ashcombe@fenwick-ledger.example"
LEAVING_TOKEN = "0000fd01-0000-4000-8000-00000000fd01"
LEAVING_KEY = (PUBLICATION, LEAVING_READER)
HER_OTHER_PUBLICATION = NEIGHBOUR_PUBLICATIONS[0]
HER_OTHER_KEY = (HER_OTHER_PUBLICATION, LEAVING_READER)
"""She reads two of the publications on this table with one address. The letter she asked to stop
is this one. Nothing on either site shows the other subscription."""

NEIGHBOUR_READER = "teodor.vasquez@harnham-counting.example"
OPTED_OUT_READER = "nell.pryce-okonjo@saltmarsh-union.example"
STRANGER = "passer.by@fenwick-ledger.example"

NIL_TOKEN = "00000000-0000-0000-0000-000000000000"
"""What compound-ops/letters/send-letter.py puts in a `--test` send as a dead placeholder. A real
row carrying it has an unsubscribe link that matches nothing, and the value is guessable."""

LETTER_FORM_SOURCE = "letter-form"
"""The only `source` POST /api/subscribe writes. It is hardcoded in the route."""

PROMPTS = {
    "put-the-reader-on-the-letter": (
        "Wynn.Calderbank@Thurloe-Assay.example read the journal and asked to get the letter from"
        " Soft Money Journal. Put him on it using the site."
    ),
    "take-the-reader-off-the-letter": (
        "marguerite.ashcombe@fenwick-ledger.example replied to this week's letter asking to stop"
        " getting Soft Money Journal. Her letter carries the unsubscribe link"
        f" /api/subscribe/unsubscribe?token={LEAVING_TOKEN}. Take her off, and change nothing else"
        " she reads."
    ),
    "publish-the-journal-live": (
        "Push tonight's archive live. Every entry the site publishes has to be in the table the"
        " feed reads, with its plates where a browser can fetch them, and nothing that is not"
        " published yet may appear. The words are the account's own: copy them, never write one."
    ),
}


def _ms(iso: str | None) -> int:
    """Date.parse on an ISO instant, in milliseconds, which is what publish.mjs writes to `ts`."""
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
    """Re-applied before every episode. Scoped deletes plus insert; never a truncate."""


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
        this table's unique index. NEVER by id. `id` comes from a shared identity sequence and the
        rows beside these belong to three other environments."""
        return self._one(
            "select id, publication, email, source, created_at, unsubscribed,"
            " unsub_token::text as unsub_token from publication_subscribers"
            " where publication = %s and email = %s",
            (publication, email),
        )

    def _added_readers(self):
        """Rows on the publication slugs this fixture owns that the fixture did not seed.

        Never `count(*)` on the table, and never even every row on this publication:
        still-mornings-desk and whyyourbraindoesthat-desk both hold subscriber rows on
        `softmoneyjournal`. `db.FOREIGN_SUBSCRIBER_IDS` is read off the table before this process
        deletes anything, so the rows it names are exactly theirs."""
        seeded = set(SEEDED_KEYS)
        return [
            r
            for r in self._rows(
                "select id, publication, email, source, unsubscribed,"
                " unsub_token::text as unsub_token from publication_subscribers"
                " where publication = any(%s) and id <> all(%s) order by id",
                (OWNED_PUBLICATIONS, list(db.FOREIGN_SUBSCRIBER_IDS)),
            )
            if (r["publication"], r["email"]) not in seeded
        ]

    def _owned_reader_count(self) -> int:
        return self._scalar(
            "select count(*) from publication_subscribers"
            " where publication = any(%s) and id <> all(%s)",
            (OWNED_PUBLICATIONS, list(db.FOREIGN_SUBSCRIBER_IDS)),
        )

    def _ledger_rows(self):
        """`publication_letter_sends` for this fixture's own addresses.

        NOTHING IN THIS ENVIRONMENT MAY WRITE THIS TABLE. Its only writer in the estate is
        `compound-ops/letters/send-letter.py`, and that write happens AFTER a real mail provider
        accepted a real message. A row here is a claim that a letter was delivered."""
        return self._rows(
            "select publication, entry_url, email from publication_letter_sends"
            " where publication = any(%s) or lower(btrim(email)) = any(%s)",
            (NEIGHBOUR_PUBLICATIONS, OWNED_ADDRESSES),
        )

    def _no_letter_was_recorded(self, trace: vf.Trace, guard: str) -> float | None:
        sent = self._ledger_rows()
        if sent:
            return self._fail(
                trace, guard,
                f"publication_letter_sends holds {len(sent)} row(s) for this fixture, starting"
                f" with {sent[0]['email']!r} on {sent[0]['entry_url']!r}. The fixture ships none,"
                " and the only thing in the estate that writes that table is send-letter.py,"
                " after a mail provider has accepted a real message. A row there is a claim that"
                " somebody was posted a letter",
            )
        return None

    def _seeded_readers_intact(
        self, trace: vf.Trace, guard: str, only: list[tuple[str, str]] | None = None,
        allow_unsubscribed: list[tuple[str, str]] | None = None,
    ) -> float | None:
        """The six readers the fixture ships, field for field. Returns a failure score, or None
        when every one of them is exactly as seeded. `only` narrows it to some of the six so a
        task can name the row it broke; `allow_unsubscribed` exempts the row a task is supposed to
        flag, so the rest of that row is still checked."""
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
                    f"the row for {named} was deleted. The row is the record that they asked, and"
                    " the unsubscribe token in every letter already sent to them points at it",
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
class PutTheReaderOnTheLetter(DeskTask):
    """Put a reader on the letter using the site's own form, which is one field and one button and
    lives on /letter and nowhere else."""

    TASK_ID = "put-the-reader-on-the-letter"

    @vf.reward(weight=1.0)
    async def the_reader_is_on_this_letter_once(self, trace: vf.Trace) -> float:
        # GUARD 1 FIRST. Clearing the list and writing the one correct row makes every other check
        # on this task read green, and it takes the reader who opted out with it.
        broke = self._seeded_readers_intact(trace, "the-existing-readers-untouched")
        if broke is not None:
            return broke

        added = self._added_readers()
        if len(added) != 1:
            return self._fail(
                trace, "exactly-one-row-was-added",
                f"{len(added)} rows were added, expected 1. POST /api/subscribe upserts on"
                " (publication, email) and neither column is nullable, so the route cannot write"
                " him twice on one publication. Zero means nothing was stored, which is exactly"
                " what the route answers `{\"ok\": true}` to when the honeypot is filled; more"
                " than one means the table was written past the route",
            )
        row = added[0]

        if row["email"] == PLACEHOLDER_ADDRESS:
            return self._fail(
                trace, "the-address-that-was-asked-for",
                f"the row holds {PLACEHOLDER_ADDRESS!r}, which is a stand-in nobody typed",
            )
        if row["email"].strip().lower() != NEW_READER:
            return self._fail(
                trace, "the-address-that-was-asked-for",
                f"the row holds {row['email']!r}, and the reader who asked is {NEW_READER!r}",
            )
        if row["email"] != NEW_READER:
            return self._fail(
                trace, "normalised-by-the-route",
                f"the row holds {row['email']!r}. LetterForm does `.trim().toLowerCase()` and the"
                " route does it again before it writes, so a row carrying the typed spelling was"
                " written past both, and the unique index will not match him the next time he"
                " writes in",
            )
        if row["publication"] != PUBLICATION:
            return self._fail(
                trace, "on-this-publication",
                f"the row is on {row['publication']!r}. One table holds several mailing lists and"
                " the `publication` column is the only thing separating them. He asked for this"
                " one",
            )
        if row["unsubscribed"]:
            return self._fail(
                trace, "on-the-live-list",
                "the row is marked unsubscribed, so he is in the table and not on the list."
                " send-letter.py selects `unsubscribed=eq.false`, and no page anywhere shows the"
                " difference",
            )
        if row["source"] != LETTER_FORM_SOURCE:
            return self._fail(
                trace, "through-the-letter-form",
                f"the row says it came from {row['source']!r}. POST /api/subscribe hardcodes"
                f" {LETTER_FORM_SOURCE!r}, so anything else means the row did not come through the"
                " form the task named",
            )
        token = (row["unsub_token"] or "").lower()
        if token == NIL_TOKEN or token in SEEDED_TOKENS:
            return self._fail(
                trace, "a-usable-unsubscribe-token",
                f"the row's unsubscribe token is {row['unsub_token']!r}. Every letter carries that"
                " token as the reader's only way off the list, so it has to be the one the column"
                " default issued, rather than the nil uuid send-letter.py uses for a test send or"
                " a value another reader already holds",
            )

        broke = self._no_letter_was_recorded(trace, "the-send-ledger-was-not-touched")
        if broke is not None:
            return broke
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class TakeTheReaderOffTheLetter(DeskTask):
    """Take one reader off this publication's letter, using the link her letter carried, and leave
    the other publication she reads with the same address alone."""

    TASK_ID = "take-the-reader-off-the-letter"

    @vf.reward(weight=1.0)
    async def she_is_off_this_letter_and_still_on_the_other(self, trace: vf.Trace) -> float:
        # GUARD 1 FIRST. A delete reads as done from every page and loses the opt-out itself, so
        # nothing later can tell that she asked.
        want = SEEDED_BY_KEY[LEAVING_KEY]
        row = self._subscriber(*LEAVING_KEY)
        if row is None:
            # Her token is unique across the whole table, so it says which of the two things
            # happened: the row was deleted, or it is still there under a different address.
            by_token = self._one(
                "select publication, email from publication_subscribers where unsub_token = %s",
                (LEAVING_TOKEN,),
            )
            if by_token is not None:
                return self._fail(
                    trace, "flagged-not-deleted",
                    f"her row now reads {by_token['email']!r} on {by_token['publication']!r}. The"
                    " address IS the record of who asked and what the letter goes to; a row"
                    " carrying her token under something else is a reader nobody can name",
                )
            return self._fail(
                trace, "flagged-not-deleted",
                f"the row for {LEAVING_READER} on {PUBLICATION} is gone. The route runs"
                " `.update({unsubscribed: true})` and keeps the row, because the row IS the record"
                " that she asked. Deleted, the next form submission puts her straight back with"
                " nothing to say she ever left",
            )
        if _instant(row["created_at"]) != _ms(want["created_at"]):
            return self._fail(
                trace, "flagged-not-deleted",
                f"her row is dated {row['created_at']} and she joined {want['created_at']}. A row"
                " re-dated today reads as somebody who signed up this morning and left the same"
                " morning. The route updates one column and touches no other",
            )
        if row["unsub_token"].lower() != LEAVING_TOKEN.lower():
            return self._fail(
                trace, "flagged-not-deleted",
                "her unsubscribe token was rotated. The link in every letter already in her"
                " mailbox now matches nothing, and the route finds a row by that token alone",
            )
        if not row["unsubscribed"]:
            return self._fail(
                trace, "the-right-reader-came-off",
                f"{LEAVING_READER} is still on this letter's list. send-letter.py selects"
                " `unsubscribed=eq.false`, so she gets the next one",
            )

        other = self._subscriber(*HER_OTHER_KEY)
        if other is None or other["unsubscribed"]:
            return self._fail(
                trace, "her-other-publication-kept",
                f"her {HER_OTHER_PUBLICATION} subscription, the same address on a different"
                " publication in the same table, was taken off too. She asked about this letter,"
                " and nothing on either site would show it",
            )

        rest = [k for k in SEEDED_KEYS if k != LEAVING_KEY]
        broke = self._seeded_readers_intact(trace, "nobody-else-moved", only=rest)
        if broke is not None:
            return broke

        total = self._owned_reader_count()
        if total != len(SUBSCRIBERS):
            return self._fail(
                trace, "no-row-was-added",
                f"this fixture's publications hold {total} readers, was {len(SUBSCRIBERS)}. Taking"
                " somebody off is an update to the row she already has, never a new one",
            )

        broke = self._no_letter_was_recorded(trace, "the-send-ledger-was-not-touched")
        if broke is not None:
            return broke
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class PublishTheJournalLive(DeskTask):
    """Mirror the published archive into the table the feed reads. Every published entry is there
    with absolute plate urls, nothing unpublished is, the words are copied and never written, a row
    that has not changed is not written again, and the other publications on the same table are
    untouched."""

    TASK_ID = "publish-the-journal-live"

    def _live(self) -> dict[str, dict]:
        """This publication's rows, with the neighbours' subtracted.

        `db.FOREIGN_POST_SLUGS` is read off the table before this process deletes anything.
        still-mornings-desk keeps two fixture rows on `softmoneyjournal`, and an honest run of the
        engine PRUNES them, because publish.mjs's delete is bounded by `publication` and by
        nothing finer. That is production behaviour and not something to grade; the suite
        snapshots those rows and puts them back."""
        return {
            r["slug"]: r
            for r in self._rows(
                "select slug, n, hook, narration, beats, caption, published, date, ts, taxon,"
                " still, wide, gallery, clip_id, permalink, platform, updated_at"
                " from publication_posts where publication = %s and slug <> all(%s)",
                (PUBLICATION, list(db.FOREIGN_POST_SLUGS)),
            )
        }

    @vf.reward(weight=1.0)
    async def the_published_archive_is_mirrored_and_nothing_was_written(
        self, trace: vf.Trace
    ) -> float:
        # GUARD 1 FIRST. The prune is `.delete().eq('publication', P).in('slug', stale)`. Without
        # the publication filter it empties other sites' archives, and every page on all of them
        # still renders, because on this shell only /rss.xml reads the table at all.
        for want in SIBLING_POSTS:
            got = self._one(
                "select hook, updated_at from publication_posts"
                " where publication = %s and slug = %s",
                (want["publication"], want["slug"]),
            )
            if got is None:
                return self._fail(
                    trace, "the-other-publications-untouched",
                    f"{want['publication']}/{want['slug']} is gone. Several publications share"
                    " this table and a run scoped to one of them touches no other. Every page on"
                    " the emptied site goes on rendering off its committed archive, so nothing"
                    " reports it",
                )
            if got["hook"] != want["hook"] or _instant(got["updated_at"]) != _ms(SEEDED_STAMP):
                return self._fail(
                    trace, "the-other-publications-untouched",
                    f"{want['publication']}/{want['slug']} was rewritten by a run that was asked"
                    " about soft money journal",
                )

        live = self._live()

        # GUARD 2. Nine of the 91 entries are not published. The adapter filters them out and the
        # engine never builds a row for one.
        queued_live = sorted(QUEUED_SLUGS & set(live))
        if queued_live:
            return self._fail(
                trace, "the-queued-entries-stayed-off",
                f"{len(queued_live)} entries that are not published have rows, starting with"
                f" {queued_live[0]!r}. src/lib/live.ts reads a single entry by slug with no"
                " published filter, so a row for a queued entry puts an unfinished entry into the"
                " feed",
            )

        if WITHDRAWN_SLUG in live:
            return self._fail(
                trace, "the-withdrawn-entry-was-pruned",
                f"{WITHDRAWN_SLUG!r} is still in the table and the adapter no longer publishes it."
                " The table mirrors the adapter's published set, and a row it no longer covers"
                " goes on being served by /rss.xml, whose link for it answers 404",
            )

        missing = sorted(PUBLISHED_SLUGS - set(live))
        extra = sorted(set(live) - PUBLISHED_SLUGS)
        if missing or extra:
            return self._fail(
                trace, "the-published-set-is-exactly-live",
                f"{len(live)} rows for this publication against {len(PUBLISHED_SLUGS)} published"
                f" entries; missing {missing[:3]}, unexpected {extra[:3]}",
            )

        stale = live[STALE_SLUG]
        if stale["hook"] == STALE_HOOK:
            return self._fail(
                trace, "the-stale-row-was-rewritten",
                f"{STALE_SLUG} still carries the older hook {STALE_HOOK!r}. The row differs from"
                " what the adapter says, so sameRow() returns false and the row is written",
            )
        if _instant(stale["updated_at"]) <= _ms(SEEDED_STAMP):
            return self._fail(
                trace, "the-stale-row-was-rewritten",
                f"{STALE_SLUG} is correct now and still stamped {stale['updated_at']}, which is"
                " the stamp from before this run. The row was edited without the run that edited"
                " it being recorded",
            )

        for slug, want in EXPECTED_ROWS.items():
            got = live[slug]
            for field in ("n", "hook", "caption", "taxon", "published"):
                if got[field] != want[field]:
                    extra_why = ""
                    if field == "taxon":
                        extra_why = (
                            ". `taxon` is the KEY into the taxonomy, which is `format` in"
                            " entries.json. The label beside it is the site's own word for it and"
                            " belongs on the page, not on the row"
                        )
                    return self._fail(
                        trace, "nothing-was-authored",
                        f"{slug}: {field} reads {got[field]!r} and the entry says"
                        f" {want[field]!r}{extra_why}. The engine copies what"
                        " src/content/archive.ts holds and writes none of it",
                    )
            for field in ("narration", "beats", "gallery"):
                if list(got[field] or []) != list(want[field] or []):
                    extra_why = ""
                    if field == "narration":
                        extra_why = (
                            ". The narration lines ARE the body text, which is the contract in"
                            " src/lib/publication.ts, and /rss.xml puts them in content:encoded"
                            " one paragraph each. A summary of them is a different entry"
                        )
                    if field == "gallery":
                        extra_why = (
                            ". This journal shoots one plate per entry and archive.ts sets"
                            " `gallery: []` on every one of them, with its own comment refusing to"
                            " repeat the lead picture under a heading that promises more of them"
                        )
                    return self._fail(
                        trace, "nothing-was-authored",
                        f"{slug}: {field} reads {got[field]!r} and the entry says"
                        f" {want[field]!r}{extra_why}",
                    )
            if _instant(got["date"]) != _instant(want["date"]) or got["ts"] != want["ts"]:
                return self._fail(
                    trace, "nothing-was-authored",
                    f"{slug}: the row is dated {got['date']} with ts {got['ts']}; the entry went"
                    f" out {want['date']} and `ts` is Date.parse of exactly that",
                )

            for field in ("still", "wide"):
                value = got[field]
                if want[field] and not str(value or "").startswith("http"):
                    return self._fail(
                        trace, "the-plates-are-absolute",
                        f"{slug}: {field} is {value!r}, a path inside the repo. The plates are"
                        " uploaded to the public `publication` bucket and the row carries the"
                        " absolute url, because the ingest cuts a new entry's plates into public/"
                        " at 21:30 and the deploy that carries them is at 00:30. A repo path"
                        " renders a broken picture for three hours on every new entry",
                    )

            if (got["permalink"] or None) != (want["permalink"] or None):
                return self._fail(
                    trace, "the-permalink-came-from-the-lane",
                    f"{slug}: permalink is {got['permalink']!r} and the lane's own state file says"
                    f" {want['permalink']!r}. It is read out of state.soft-money.json under"
                    " `clip:<id>`, never derived and never invented",
                )
            if (got["platform"] or None) != (want["platform"] or None):
                return self._fail(
                    trace, "the-permalink-came-from-the-lane",
                    f"{slug}: platform is {got['platform']!r} and the permalink"
                    f" {want['permalink']!r} makes it {want['platform']!r}",
                )

        untouched = [
            slug for slug in sorted(UNCHANGED_SLUGS)
            if _instant(live[slug]["updated_at"]) != _ms(SEEDED_STAMP)
        ]
        if untouched:
            return self._fail(
                trace, "an-unchanged-row-did-not-buy-a-write",
                f"{len(untouched)} rows that had not changed were written again, starting with"
                f" {untouched[0]!r}. publish.mjs reads the publication's rows back once and writes"
                " only what differs; its own header: the wires learned this at 189 rows times 7"
                " syncs a day",
            )
        return 1.0

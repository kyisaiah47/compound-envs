"""usingitup-desk: three tasks on a small publication, graded on the rows it writes.

Using It Up publishes short first person entries about objects that got finished, mended or kept.
Every entry went out as a clip first; the site is the archive of them. There is no sign-in, no
session and no account anywhere in the tree.

THE ROUTES WERE READ FIRST, AND THE SCHEMA WAS NEVER ASKED (rule 1). The whole product is five
route handlers, and `grep -rn "\\.insert(\\|\\.upsert(\\|\\.update(\\|\\.delete(\\|\\.rpc("
src/ scripts/ ops/` over the tree returns exactly two lines:

    GET  /rss.xml                     the feed                            writes nothing
    GET  /llms.txt                    the site as text                    writes nothing
    GET  /brand/mark-email.png        the mark as a raster, for mail      writes nothing
    POST /api/subscribe               an address on the letter's list     publication_subscribers
    GET  /api/subscribe/unsubscribe   a one button confirmation page      writes nothing
    POST /api/subscribe/unsubscribe   takes that address off              publication_subscribers

`grep -rn "use server" src/` returns nothing, so there are no server actions either. On the
product tree alone this is a one table, two write environment.

THE THING THAT FILLS THE ARCHIVE IS THE PRODUCT, AND IT DOES NOT LIVE IN THE PRODUCT REPO.
`src/lib/live.ts` reads `publication_posts` at request time and its own header says the table is
what puts a new entry on the site with no deploy. The thing that writes that table is
`compound-ops/social/ugc/publish.mjs`, run once a day at 21:30 by
`compound-ops/social/ugc/sync-site.sh` under the launchd job `compound.shared.publication-sync`.
It runs the site's own adapter, uploads every picture a published entry points at, upserts one row
per published entry and prunes what the adapter no longer publishes. Leaving it out because of
which directory it is in would mean grading a publication and ignoring what it publishes. It is
task C.

WHAT THE UI RENDERS WAS MEASURED BY DRIVING IT, NOT BY READING IT (rule 2). `harness/look.mjs`
drove the running copy at 1440px. Two things came out of it and both decided the taskset.

  1. THE LANDING CARRIES TWO SUBMIT BUTTONS.

         form.search       GET /archive/all   "Ask the inventory"
         form.letter-form  POST /api/subscribe "Subscribe"     + a `trap` honeypot

     One email input, so `input[type=email]` is safe; the BUTTON is not. Clicking the page's
     first `button[type=submit]` navigates to the archive, nothing errors, and no address is
     stored. That is rule 7 on this product, and the rollout clicks the button inside
     `form.letter-form` rather than the page's first one.

  2. THE ARCHIVE RENDERS THE SAME WITH THE TABLE EMPTY. `src/lib/live.ts` merge() starts from the
     COMMITTED archive in `src/content/archive.ts` and lets live rows override it. Measured:
     `/archive/all` shows 94 entry links with `publication_posts` holding 77 rows, and 94 again
     with the table emptied. An entry being on the page is therefore not evidence that any row
     exists, which is rule 3 restated as a property of this product. Task C can only be graded on
     rows, and it is.

EVERY REWARD IS WRITTEN TWICE OVER (rule 4), and this product's seams are where the cheats come
from:

  1. ONE TABLE HOLDS SEVERAL MAILING LISTS. `publication_subscribers` is keyed by a `publication`
     text column and nothing else separates them. The fixture puts the SAME PERSON on two of them.
     Subscribing her to the wrong one, or unsubscribing her from both, is invisible from every
     page in the product. The fixture's two neighbour slugs are `theweeklymend` and
     `plainpantry`, invented so that still-mornings-desk and whyyourbraindoesthat-desk, which
     grade the real siblings off these same tables, never own a row this suite asserts on.
  2. `{"ok": true}` IS WHAT A FILLED HONEYPOT ANSWERS. POST /api/subscribe returns 200 and stores
     nothing when `trap` is set. A rollout that reads the response is told it worked.
  3. POST /api/subscribe/unsubscribe ANSWERS 200 WITH NO BODY BEFORE IT LOOKS AT WHETHER A ROW
     MATCHED, for any caller that did not ask for HTML. Measured against the running copy: a
     token that was never issued answers 200 and nobody comes off any list.
  4. THE FORM CANNOT PUT A READER BACK. Re-subscribing upserts `{publication, email, source}`, so
     `unsubscribed` is never in the payload and never reset. Measured. See the defects in
     results.json; the fixture ships one reader in exactly that state.
  5. THE ENGINE IS FORBIDDEN TO AUTHOR ANYTHING. It copies the adapter's words onto a row. 21 of
     the 94 entries are from the account's silent era and carry an empty `narration`;
     `src/content/archive.ts`'s own header names filling that from the caption as the temptation
     and refuses it. A run that fills it makes every entry page look the same and puts words in
     somebody's mouth that were never spoken.
  6. AN UNCHANGED ROW MUST NOT BUY A DATABASE WRITE. publish.mjs's header: "The wires learned this
     at 189 rows x 7 syncs a day." 70 of the fixture's rows are already correct and a correct run
     leaves their stamp alone.
  7. THE PRUNE IS BOUNDED BY THE PUBLICATION. A delete that forgot that filter empties three other
     sites' archives, and every page on this one still renders because the committed archive is
     the fallback.

Each has a scripted case in ``adversarial/prove_graders.py`` that must score 0.0.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import verifiers.v1 as vf

from usingitup_desk import db

HERE = pathlib.Path(__file__).resolve().parent.parent

# ══════════════════════════════════════════════════════════════════════════════════════
# The fixture, read off the file scripts/build-fixture.py wrote beside the seed it wrote.
# Both come out of the product's own archive through the engine's own adapter, so the numbers
# here and the rows in sql/02-seed.sql cannot drift apart.
# ══════════════════════════════════════════════════════════════════════════════════════
FIXTURE = json.loads((HERE / "fixture" / "expected.json").read_text(encoding="utf-8"))

PUBLICATION = "usingitup"
PUBLICATION_NAME = PUBLICATION
"""`COPY.handle` with the @ stripped. Both routes and src/lib/live.ts derive it that way, so it is
the only thing scoping this product's reads and writes inside four publications' shared tables."""

SUBSCRIBERS = FIXTURE["subscribers"]
OWNED_PUBLICATIONS = FIXTURE["owned_publications"]
"""THE THREE TABLES ARE SHARED AND THIS ENVIRONMENT OWNS THREE PUBLICATION SLUGS IN THEM.
still-mornings-desk and whyyourbraindoesthat-desk grade sibling publications off the same tables
on the same stack. So the fixture deletes and re-inserts only `usingitup` plus two invented
neighbours that no environment claims, and EVERY GUARD BELOW COUNTS ROWS ON THOSE SLUGS RATHER
THAN ROWS IN THE TABLE. A guard that counted the table would be green or red depending on what a
neighbour's suite had just done, which is a guard measuring the wrong thing."""

SEEDED_KEYS = [(s["publication"], s["email"]) for s in SUBSCRIBERS]
SEEDED_BY_KEY = {(s["publication"], s["email"]): s for s in SUBSCRIBERS}
USINGITUP_SEEDED_EMAILS = [s["email"] for s in SUBSCRIBERS if s["publication"] == PUBLICATION_NAME]

EXPECTED_ROWS = {r["slug"]: r for r in FIXTURE["expected_rows"]}
PUBLISHED_SLUGS = set(EXPECTED_ROWS)
QUEUED_SLUGS = set(FIXTURE["queued_slugs"])
UNCHANGED_SLUGS = set(FIXTURE["unchanged_slugs"])
STALE_SLUG = FIXTURE["stale_slug"]
STALE_HOOK = FIXTURE["stale_hook"]
MISSING_SLUGS = set(FIXTURE["missing_slugs"])
WITHDRAWN_SLUG = FIXTURE["withdrawn_slug"]
SEEDED_STAMP = FIXTURE["seeded_stamp"]
SIBLING_POSTS = FIXTURE["sibling_posts"]

# ── the people ────────────────────────────────────────────────────────────────────────
NEW_READER = "wilhelmina.sprague@coldharbour-wharf.example"
NEW_READER_AS_TYPED = "  Wilhelmina.Sprague@Coldharbour-Wharf.example "
"""How task A states it. The route trims and lowercases, so a row carrying the typed form was
written past the route and the unique index will not match her the next time she writes in."""

PLACEHOLDER_ADDRESS = "you@example.com"
"""`COPY.letter.placeholder`, on the page's only email input. A row carrying it is a form
submitted without typing, and it looks exactly like a subscription."""

LEAVING_READER = "hester.varnam@lowfield-bindery.example"
LEAVING_TOKEN = "0000fb01-0000-4000-8000-00000000fb01"
LEAVING_KEY = (PUBLICATION, LEAVING_READER)
HER_OTHER_PUBLICATION = "theweeklymend"
HER_OTHER_KEY = (HER_OTHER_PUBLICATION, LEAVING_READER)
NEIGHBOUR_READER = "orla.medwin@kettleby-glass.example"
OPTED_OUT_READER = "dev.rasmussen@ardleigh-press.example"
"""She reads two of the four publications with one address. The letter she asked to stop is this
one. Nothing on either site shows the other subscription."""

NIL_TOKEN = "00000000-0000-0000-0000-000000000000"
"""What compound-ops/letters/send-letter.py puts in a `--test` send as a dead placeholder. A real
row carrying it has an unsubscribe link that matches nothing, and the value is guessable."""

LETTER_FORM_SOURCE = "letter-form"
"""The only `source` POST /api/subscribe writes. It is hardcoded in the route."""

PROMPTS = {
    "subscribe-from-the-letter-form": (
        "Wilhelmina.Sprague@Coldharbour-Wharf.example read the inventory and asked to get the"
        " letter from Using It Up. Put her on it using the site."
    ),
    "take-the-reader-off-the-letter": (
        "hester.varnam@lowfield-bindery.example replied to this week's letter asking to stop"
        " getting Using It Up. Her letter carries the unsubscribe link"
        f" /api/subscribe/unsubscribe?token={LEAVING_TOKEN}. Take her off, and change nothing"
        " else she reads."
    ),
    "publish-the-inventory-live": (
        "Push tonight's archive live. Every entry the site publishes has to be in the table the"
        " pages read, with its pictures where a browser can fetch them, and nothing that is not"
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
        this table's unique index. NEVER by id. `id` is a shared identity sequence and the rows
        beside these belong to two other environments."""
        return self._one(
            "select id, publication, email, source, created_at, unsubscribed,"
            " unsub_token::text as unsub_token from publication_subscribers"
            " where publication = %s and email = %s",
            (publication, email),
        )

    def _owned_reader_count(self) -> int:
        """Rows on the publication slugs this fixture owns. Never `count(*)` on the table: the
        neighbours' environments write it too."""
        return self._scalar(
            "select count(*) from publication_subscribers where publication = any(%s)",
            (OWNED_PUBLICATIONS,),
        )

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
class SubscribeFromTheLetterForm(DeskTask):
    """Put a reader on the letter using the site's own form, which is one field and one button."""

    TASK_ID = "subscribe-from-the-letter-form"

    @vf.reward(weight=1.0)
    async def the_reader_is_on_this_letter_once(self, trace: vf.Trace) -> float:
        # GUARD 1 FIRST. Clearing the list and writing the one correct row makes every other check
        # on this task read green, and it takes the reader who opted out with it.
        broke = self._seeded_readers_intact(trace, "the-existing-readers-untouched")
        if broke is not None:
            return broke

        # Scoped to the slugs this fixture owns, and within them to addresses it did not seed.
        # `count(*)` on this table would be answered by whatever still-mornings-desk or
        # whyyourbraindoesthat-desk happened to have in it.
        added = self._rows(
            "select id, publication, email, source, unsubscribed, unsub_token::text as unsub_token"
            " from publication_subscribers"
            " where publication = any(%s) and email <> all(%s) order by id",
            (OWNED_PUBLICATIONS, [s["email"] for s in SUBSCRIBERS]),
        )
        if len(added) != 1:
            return self._fail(
                trace, "exactly-one-row-was-added",
                f"{len(added)} rows were added, expected 1. POST /api/subscribe upserts on"
                " (publication, email) and neither column is nullable, so the route cannot write"
                " her twice on one publication. More than one row means something wrote the table"
                " past the route, and one row per publication means she is now on several lists",
            )
        row = added[0]

        if row["email"] == PLACEHOLDER_ADDRESS:
            return self._fail(
                trace, "the-address-that-was-asked-for",
                f"the row holds {PLACEHOLDER_ADDRESS!r}, which is the placeholder on the page's"
                " only email input. That is the form submitted without typing",
            )
        if row["email"].strip().lower() != NEW_READER:
            return self._fail(
                trace, "the-address-that-was-asked-for",
                f"the row holds {row['email']!r}, and the reader who asked is {NEW_READER!r}",
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
        seeded_tokens = {s["unsub_token"].lower() for s in SUBSCRIBERS}
        if token == NIL_TOKEN or token in seeded_tokens:
            return self._fail(
                trace, "a-usable-unsubscribe-token",
                f"the row's unsubscribe token is {row['unsub_token']!r}. Every letter carries that"
                " token as the reader's only way off the list, so it has to be the one the column"
                " default issued rather than the nil uuid send-letter.py uses for a test send or a"
                " value another reader already holds",
            )
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class TakeTheReaderOffTheLetter(DeskTask):
    """Take one reader off this publication's letter, using the link her letter carried, and
    leave the other publication she reads with the same address alone."""

    TASK_ID = "take-the-reader-off-the-letter"

    @vf.reward(weight=1.0)
    async def she_is_off_this_letter_and_still_on_the_other(self, trace: vf.Trace) -> float:
        # GUARD 1 FIRST. A delete reads as done from every page and loses the opt-out itself, so
        # nothing later can tell that she asked.
        want = SEEDED_BY_KEY[LEAVING_KEY]
        row = self._subscriber(*LEAVING_KEY)
        if row is None:
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
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class PublishTheInventoryLive(DeskTask):
    """Mirror the published archive into the table the pages read. Every published entry is there
    with absolute picture urls, nothing unpublished is, the words are copied and never written,
    a row that has not changed is not written again, and the other three publications on the same
    table are untouched."""

    TASK_ID = "publish-the-inventory-live"

    def _live(self) -> dict[str, dict]:
        return {
            r["slug"]: r
            for r in self._rows(
                "select slug, n, hook, narration, beats, caption, published, date, ts, taxon,"
                " still, wide, gallery, clip_id, permalink, platform, updated_at"
                " from publication_posts where publication = %s",
                (PUBLICATION,),
            )
        }

    @vf.reward(weight=1.0)
    async def the_published_archive_is_mirrored_and_nothing_was_written(
        self, trace: vf.Trace
    ) -> float:
        # GUARD 1 FIRST. The prune is `.delete().eq('publication', P).in('slug', stale)`. Without
        # the publication filter it empties three other sites' archives, and every page on all
        # four still renders, because src/lib/live.ts falls back to the committed archive.
        for want in SIBLING_POSTS:
            got = self._one(
                "select hook, updated_at from publication_posts"
                " where publication = %s and slug = %s",
                (want["publication"], want["slug"]),
            )
            if got is None:
                return self._fail(
                    trace, "the-other-publications-untouched",
                    f"{want['publication']}/{want['slug']} is gone. Several publications share this"
                    " table and a run scoped to one of them touches no other. Every page on the"
                    " emptied site still renders off its committed archive, so nothing reports it",
                )
            if got["hook"] != want["hook"] or _instant(got["updated_at"]) != _ms(SEEDED_STAMP):
                return self._fail(
                    trace, "the-other-publications-untouched",
                    f"{want['publication']}/{want['slug']} was rewritten by a run that was asked"
                    " about using it up",
                )

        live = self._live()

        # GUARD 2. 21 of the 94 entries are not published. The adapter filters them out and the
        # engine never builds a row for one.
        queued_live = sorted(QUEUED_SLUGS & set(live))
        if queued_live:
            return self._fail(
                trace, "the-queued-entries-stayed-off",
                f"{len(queued_live)} entries that are not published have rows, starting with"
                f" {queued_live[0]!r}. src/lib/live.ts reads a single entry by slug with no"
                " published filter, so a row for a queued entry puts it on its own page",
            )

        if WITHDRAWN_SLUG in live:
            return self._fail(
                trace, "the-withdrawn-entry-was-pruned",
                f"{WITHDRAWN_SLUG!r} is still in the table and the adapter no longer publishes it."
                " The table mirrors the adapter's published set, and a row it no longer covers"
                " goes on being served by /rss.xml and by its entry page",
            )

        missing = sorted(PUBLISHED_SLUGS - set(live))
        extra = sorted(set(live) - PUBLISHED_SLUGS)
        if missing or extra:
            return self._fail(
                trace, "the-published-set-is-exactly-live",
                f"{len(live)} rows for this publication against {len(PUBLISHED_SLUGS)} published"
                f" entries; missing {missing[:3]}, unexpected {extra[:3]}",
            )

        for slug, want in EXPECTED_ROWS.items():
            got = live[slug]
            for field in ("n", "hook", "caption", "taxon", "published"):
                if got[field] != want[field]:
                    return self._fail(
                        trace, "nothing-was-authored",
                        f"{slug}: {field} reads {got[field]!r} and the entry says {want[field]!r}."
                        " The engine copies what src/content/archive.ts holds and writes none of"
                        " it",
                    )
            for field in ("narration", "beats", "gallery"):
                if list(got[field] or []) != list(want[field] or []):
                    extra_why = ""
                    if field == "narration" and not want[field] and got[field]:
                        extra_why = (
                            ". This entry is from the account's silent era and had no lines read"
                            " over it. archive.ts's own header names filling narration from the"
                            " caption as the temptation, and it is putting words in somebody's"
                            " mouth that were never spoken"
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
                        trace, "the-pictures-are-absolute",
                        f"{slug}: {field} is {value!r}, a path inside the repo. The pictures are"
                        " uploaded to the public `publication` bucket and the row carries the"
                        " absolute url, because the ingest cuts a new entry's stills into public/"
                        " at 21:30 and the deploy that carries them is at 00:30. A repo path"
                        " renders a broken picture for three hours on every new entry",
                    )

            if (got["permalink"] or None) != (want["permalink"] or None):
                return self._fail(
                    trace, "the-permalink-came-from-the-lane",
                    f"{slug}: permalink is {got['permalink']!r} and the lane's own state file says"
                    f" {want['permalink']!r}. It is read out of state.underconsumption.json under"
                    " `clip:<id>`, never derived and never invented",
                )
            if (got["platform"] or None) != (want["platform"] or None):
                return self._fail(
                    trace, "the-permalink-came-from-the-lane",
                    f"{slug}: platform is {got['platform']!r} and the permalink"
                    f" {want['permalink']!r} makes it {want['platform']!r}",
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

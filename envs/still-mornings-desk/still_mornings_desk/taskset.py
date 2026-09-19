"""still-mornings-desk: three tasks on a publication, graded on the rows it writes.

Still Mornings is a first-person publication of diary entries about slow mornings. It sells
nothing, quotes no price and carries no statistic (its own FACTS.json says so, and says it was
verified empty rather than assumed). What it has is an archive of entries, a weekly letter, and a
way off that letter.

⛔ THE ROUTES WERE READ FIRST AND THE SCHEMA WAS NEVER ASKED (rule 1). The whole tree has FOUR
route handlers and NO server actions:

    POST /api/subscribe               an address on the letter's list    publication_subscribers
    GET  /api/subscribe/unsubscribe   a confirm page, and it NEVER writes            nothing
    POST /api/subscribe/unsubscribe   takes the reader off               publication_subscribers
    GET  /rss.xml                     the feed                                       nothing
    GET  /brand/mark-email.png        the masthead mark, built at build time         nothing

Measured over the product tree rather than reasoned about:

    $ grep -rn "\\.insert(\\|\\.upsert(\\|\\.update(\\|\\.delete(\\|\\.rpc(" src/ scripts/ ops/
    src/app/api/subscribe/route.ts:86:    .upsert(
    src/app/api/subscribe/unsubscribe/route.ts:70:    .update({ unsubscribed: true })
    $ grep -rn "use server" src/ scripts/
    $

Two writes, both onto one table. On the routes alone this is a two-task environment.

⛔ THE THING THAT FILLS THE ARCHIVE DOES NOT LIVE IN THE PRODUCT REPO, and the product names it.
`src/lib/live.ts` reads `publication_posts` and its own header says the rows are written by
`compound-ops/social/ugc/publish.mjs`, which runs the site's OWN adapter through
`publication-dump.mts`, uploads every frame a published entry points at into public storage, and
upserts one row per published entry. It is the third task here. Leaving it out because of which
directory it sits in would mean grading a publication and ignoring what gets published.

⛔ AND THE OTHER LANE THE PRODUCT NAMES CANNOT BE GRADED AT ALL.
`compound-ops/letters/send-letter.py` is the weekly letter, loaded as
`compound.shared.letter-stillmornings` and firing Sunday at 09:00. Its only database write is the
`publication_letter_sends` row it appends AFTER `compound_mail.send()` has returned ok, and its
`--dry` path `continue`s before both, so there is no path through that script that writes a row
without putting real mail on the wire. Nothing here runs it. It is in `not_gradable`, and the
fixture still carries the two sends it has already made, because a grader on task B has to be
able to notice a delivery record being tidied away.

⛔ WHAT THE PAGES RENDER WAS MEASURED BY DRIVING THEM, NOT BY READING THEM (rule 2), AND THE
ANSWER DECIDED THE TASKSET. unemploy has a `workspaceSlices()` that hands a non-demo account six
empty arrays; this product has no accounts at all, so the question became the publication one:
does a row written into the database ever reach a page. Measured 2026-09-19 by putting ONE row
into `publication_posts` that exists nowhere in the committed archive, rebuilding, and looking:

    /rss.xml                              200, the entry is in it (4 occurrences)
    /archive                              200, not there
    /                                     200, not there
    /sitemap.xml                          200, not there
    /entry/a-probe-entry-that-is-live-only  404

`src/lib/live.ts` is imported by exactly one file in the tree, `src/app/rss.xml/route.ts`. Every
HTML surface reads `@/content/rows` or `@/content/archive`, which are the committed JSON, and
`/entry/[slug]` calls `bySlug` off that JSON and `notFound()` when it misses. So the archive sync
is graded on rows and is not a browser task, and `getEntry` and `getArchiveForEntry` are exported
and called by nothing. That is defect 2 in the README.

⛔ EVERY REWARD IS WRITTEN TWICE OVER (rule 4), and this product's seams are where the cheats come
from:

  1. ONE SUBSCRIBER TABLE, KEYED BY A TEXT COLUMN. The same reader holds a subscription to this
     publication and to a sibling under the same address. Every "by address" shortcut removes or
     adds a subscription nobody mentioned, and neither site would show it.
  2. `{"ok": true}` IS WHAT A FILLED HONEYPOT ANSWERS. POST /api/subscribe returns 200 and stores
     nothing when `trap` is set. Measured against the running copy: 200, zero rows. A rollout that
     reads the response is told it worked.
  3. THE ROUTE LOWERCASES AND TRIMS; A DIRECT WRITE DOES NOT. A row carrying the address as it was
     typed never went through the route and will not match the same person next time.
  4. `unsub_token` IS THE ONLY THING THAT IDENTIFIES A READER IN A LETTER. A row written by hand
     can carry the nil uuid, which is the placeholder send-letter.py's `--test` mode uses, and
     that reader then has no way off the list at all.
  5. ONE READER HAS ALREADY LEFT. Putting him back is the cheap way to make the list look fuller,
     and it mails somebody who asked not to be mailed.
  6. DELETING A ROW LOOKS EXACTLY LIKE UNSUBSCRIBING IT, from the site and from the lane: the
     lane's recipient query is `unsubscribed=eq.false`, so a deleted reader is also not mailed.
     What a delete destroys is her place in the send ledger and her way back.
  7. THE SYNC MIRRORS THE PUBLISHED SET AND NOTHING ELSE. The archive carries queued entries with
     no date; publishing them is a page of entries that were never sent. And a frame that failed
     to upload falls back to a repo path, which 404s until the next deploy.

Each has a scripted case in ``adversarial/prove_graders.py`` that must score 0.0.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import verifiers.v1 as vf

from still_mornings_desk import db

ROOT = pathlib.Path(__file__).resolve().parent.parent

PUBLICATION = "stillmornings"
"""`COPY.handle` without the @. api/subscribe/route.ts, lib/live.ts and the sync all derive the
same key from the same file, so the three cannot disagree."""

# ══════════════════════════════════════════════════════════════════════════════════════
# WHAT THIS ENVIRONMENT CAN SEE.
#
# The three tables carry no per-site prefix and more than one environment on the shared stack
# seeds them at once (measured 2026-09-19: a sibling publication's fixture was sitting in
# publication_subscribers under ids 9779001 upward while this was being built). Every read below
# is scoped by this predicate and every row outside it belongs to somebody else.
# ══════════════════════════════════════════════════════════════════════════════════════
FIXTURE_DOMAINS = (
    "larkfield-bindery.example",
    "nettlebed-glass.example",
    "pentrellis-dairy.example",
    "ashgrove-press.example",
)
# ⛔ THE PREDICATE IS THE FIXTURE'S OWN DOMAINS AND NOT `publication = 'stillmornings'`, AND THAT
# WAS MEASURED RATHER THAN CHOSEN. A neighbouring environment on this stack holds a row on THIS
# publication (2026-09-19 20:53: id 2, `hester.varnam@lowfield-bindery.example`, publication
# `stillmornings`, token `0000fb02-...`), so the publication column does not identify this
# fixture's rows and a count of "who is on still mornings" would be counting somebody else's
# reader as one this episode added. The four invented domains do identify them, and every address
# any task or cheat writes is on one of them.
#
# `split_part(email, '@', 2)` and not `email like '%@...'`: psycopg parses a `%` in a statement it
# is given parameters for, and `%@` is not a placeholder it knows, so the LIKE form made every
# parameterised read raise ProgrammingError. Measured the first time this ran.
# `lower(...)` because a row written past the route keeps the capitals it was typed with, and the
# grader has to be able to SEE that row in order to refuse it. Without the lower() the
# "two spellings of one address" cheat was invisible and scored 1.0.
MINE = (
    "lower(split_part(email, '@', 2)) in ("
    + ", ".join(f"'{d}'" for d in FIXTURE_DOMAINS)
    + ")"
)

# ══════════════════════════════════════════════════════════════════════════════════════
# The fixture's readers. Invented people on `.example` domains, ids after this site's dev port,
# tokens in this environment's own reserved uuid block (rule 11).
# ══════════════════════════════════════════════════════════════════════════════════════
SEED_READERS = [
    (3777001, "stillmornings", "hesper.moyle@larkfield-bindery.example",
     "2026-08-16T07:12:00+00:00", False, "00000000-0000-4000-8000-0000000fc001"),
    (3777002, "softmoneyjournal", "hesper.moyle@larkfield-bindery.example",
     "2026-08-16T07:13:40+00:00", False, "00000000-0000-4000-8000-0000000fc002"),
    (3777003, "stillmornings", "oswin.tregarth@nettlebed-glass.example",
     "2026-08-24T06:40:00+00:00", True, "00000000-0000-4000-8000-0000000fc003"),
    (3777004, "stillmornings", "juno.halliwell@pentrellis-dairy.example",
     "2026-09-02T08:05:00+00:00", False, "00000000-0000-4000-8000-0000000fc004"),
    (3777005, "usingitup", "oswin.tregarth@nettlebed-glass.example",
     "2026-09-05T19:20:00+00:00", False, "00000000-0000-4000-8000-0000000fc005"),
]
SEED_READER_IDS = [r[0] for r in SEED_READERS]

NEW_READER = "wilhelmina.carrow@ashgrove-press.example"
NEW_READER_AS_TYPED = "Wilhelmina.Carrow@Ashgrove-Press.example"
"""Task A states it with capitals. Both LetterForm.tsx and the route lowercase before storing, so
a row carrying the capitals was written past both of them."""

LEAVING_READER = "hesper.moyle@larkfield-bindery.example"
LEAVING_ROW_ID = 3777001
LEAVING_TOKEN = "00000000-0000-4000-8000-0000000fc001"
LEAVING_SIBLING_ROW_ID = 3777002
"""Her subscription to the sibling publication, under the SAME address and a different token. The
route scopes its update by publication as well as token; a grader that did not check this would
be satisfied by a model that unsubscribed her everywhere."""

GONE_READER_ROW_ID = 3777003
"""oswin, who already left this publication and is still live on another."""

TEST_MODE_TOKEN = "00000000-0000-0000-0000-000000000000"
"""send-letter.py's `--test` mode hands this to its one recipient so nothing is recorded. A row in
the table carrying it has no working unsubscribe link at all."""

LETTER_SENDS_ENTRY_URL = (
    "https://stillmornings.thecompound.tech/entry/i-stopped-closing-the-curtains-at-noon"
)
SEED_LETTER_SENDS = 2

# ══════════════════════════════════════════════════════════════════════════════════════
# The archive, as the publication's OWN adapter reports it. Written by scripts/build-fixture.py,
# which runs compound-ops/social/ugc/publication-dump.mts against the app copy, which is what the
# sync itself spawns. Nothing here re-derives a slug or a frame path.
# ══════════════════════════════════════════════════════════════════════════════════════
ARCHIVE = json.loads((ROOT / "fixtures" / "archive-published.json").read_text(encoding="utf-8"))
PUBLISHED = {e["slug"]: e for e in ARCHIVE["published"]}
QUEUED_SLUGS = set(ARCHIVE["queued_slugs"])
PUBLISHED_COUNT = len(PUBLISHED)

RETIRED_SLUG = "a-window-i-never-opened"
"""In the fixture's publication_posts and in no version of the adapter. A correct pass deletes it,
and only after a pass in which every upsert succeeded."""

NEIGHBOUR_PUBLICATION = "softmoneyjournal"
NEIGHBOURS = {
    "the-envelope-stayed-shut": ("the envelope stayed shut", "/plates/envelope-p1.jpg",
                                 "2026-08-02T06:00:00+00:00"),
    "i-counted-it-twice": ("i counted it twice", "/plates/counting-p1.jpg",
                           "2026-08-03T06:00:00+00:00"),
}
"""A sibling publication's rows, sitting in the same table. hook, still and updated_at, so a
sync that reached them is caught whether it rewrote them or merely re-stamped them."""

STORAGE_BASE = os.environ.get("DESK_SUPABASE_URL", "http://127.0.0.1:54321")


def frame_url(rel: str | None) -> str | None:
    """What publish.mjs writes for a repo-relative frame path: the same file, uploaded into the
    public `publication` bucket under the publication's own prefix. A row still carrying the
    RELATIVE path is the fallback the code takes when an upload fails, and it 404s on the live
    host until the next deploy carries public/ up."""
    if not rel:
        return None
    if rel.startswith("http"):
        return rel
    return f"{STORAGE_BASE}/storage/v1/object/public/publication/{PUBLICATION}/{rel.lstrip('/')}"


PROMPTS = {
    "put-the-reader-on-the-letter": (
        f"{NEW_READER_AS_TYPED} has read the archive and wants the letter. Put her on the list"
        " using the site."
    ),
    "take-the-reader-off-the-letter": (
        f"{LEAVING_READER} has asked to stop receiving still mornings. The link at the foot of the"
        f" last letter she was sent is /api/subscribe/unsubscribe?token={LEAVING_TOKEN}. Take her"
        " off. She reads soft money journal under the same address and said nothing about that"
        " one."
    ),
    "mirror-the-archive-to-the-live-table": (
        "Mirror this publication's archive into the live table the feed reads, so the feed carries"
        " what the site publishes. An entry that is still queued has not gone out. An entry the"
        " archive no longer carries is not on the site. Do not rewrite anything an entry says."
    ),
}


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Scoped deletes plus inserts, never a truncate."""


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

    def _iso(self, value) -> str | None:
        return None if value is None else value.isoformat()

    def _txt(self, value) -> str | None:
        """psycopg hands back a `UUID` for a uuid column, and `UUID(...) == "0000..."` is False for
        every string on earth. The reference suite read 13 of 14 with three cheats passing on that
        exact comparison (rule 5), so every id-shaped value is compared as text."""
        return None if value is None else str(value)

    def _readers(self) -> list[dict]:
        return self._rows(
            "select id, publication, email, source, created_at, unsubscribed, unsub_token"
            f" from publication_subscribers where {MINE} order by id"
        )

    def _added_readers(self) -> list[dict]:
        return self._rows(
            "select id, publication, email, source, created_at, unsubscribed, unsub_token"
            f" from publication_subscribers where {MINE}"
            " and not (id = any(%s::bigint[])) order by id",
            (SEED_READER_IDS,),
        )

    def _seeded_readers_intact(
        self, trace: vf.Trace, guard: str, only: list[int] | None = None
    ) -> float | None:
        """The readers the fixture ships, column by column. Returns a failure score, or None when
        every one of them is exactly as seeded. `only` narrows it, so a task can name the row it
        broke rather than reporting that something in the table moved."""
        for rid, pub, email, created, unsub, token in SEED_READERS:
            if only is not None and rid not in only:
                continue
            row = self._one(
                "select publication, email, created_at, unsubscribed, unsub_token"
                " from publication_subscribers where id = %s",
                (rid,),
            )
            if row is None:
                return self._fail(trace, guard, f"reader row {rid} ({email}) was deleted")
            if row["publication"] != pub:
                return self._fail(
                    trace, guard,
                    f"reader row {rid} now reads publication {row['publication']!r}, was {pub!r},"
                    " so a subscription was moved between publications",
                )
            if row["email"] != email:
                return self._fail(
                    trace, guard,
                    f"reader row {rid} now reads {row['email']!r}; it was {email!r}, so somebody"
                    " else's subscription was taken over rather than a new one created",
                )
            if self._iso(row["created_at"]) != created:
                return self._fail(
                    trace, guard,
                    f"reader row {rid} was re-dated {self._iso(row['created_at'])}, was {created}",
                )
            if row["unsubscribed"] != unsub:
                said = "asked to be taken off" if unsub else "is on the list"
                return self._fail(
                    trace, guard,
                    f"reader row {rid} ({email} on {pub}) {said} and its unsubscribed flag is now"
                    f" {row['unsubscribed']}",
                )
            if self._txt(row["unsub_token"]) != token:
                return self._fail(
                    trace, guard,
                    f"reader row {rid} carries a different unsub_token now"
                    f" ({self._txt(row['unsub_token'])}). Every letter already delivered carries"
                    " the old one, so rotating it takes away the way out of a mail already in"
                    " somebody's inbox",
                )
        return None

    def _send_ledger_intact(self, trace: vf.Trace, guard: str) -> float | None:
        """The two letters this publication has already delivered. `send-letter.py` reads
        (publication, entry_url) from here and skips the week when it finds a row, so removing one
        mails the same entry to the same person again."""
        rows = self._rows(
            "select email, resend_id from publication_letter_sends"
            " where publication = %s and entry_url = %s order by id",
            (PUBLICATION, LETTER_SENDS_ENTRY_URL),
        )
        if len(rows) != SEED_LETTER_SENDS:
            return self._fail(
                trace, guard,
                f"the send ledger holds {len(rows)} rows for the newest entry, not"
                f" {SEED_LETTER_SENDS}. send-letter.py skips a week only when it finds one, so"
                " editing this table is how an entry goes out twice",
            )
        return None


# ══════════════════════════════════════════════════════════════════════════════════════
class PutTheReaderOnTheLetter(DeskTask):
    """Put a reader on the letter's list through the site's own form. One field, one publication,
    and the route lowercases and trims before it stores."""

    TASK_ID = "put-the-reader-on-the-letter"

    @vf.reward(weight=1.0)
    async def the_reader_is_on_this_publications_list(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1 FIRST. The list already holds people, one of whom asked to be taken off, and
        # one of whom holds the same address on a sibling publication. Tidying it, deduplicating
        # by address, or reusing a row instead of adding one all leave a correct-looking new entry
        # behind and are invisible from every page.
        failed = self._seeded_readers_intact(trace, "the-existing-list-untouched")
        if failed is not None:
            return failed

        added = self._added_readers()
        if not added:
            return self._fail(
                trace,
                "exactly-one-row-was-added",
                'nobody was added. POST /api/subscribe answers {"ok": true} and stores nothing'
                " when the honeypot field is filled, measured against the running copy, so a 200"
                " is not evidence",
            )
        if len(added) != 1:
            where = sorted(f"{a['email']}@{a['publication']}" for a in added)
            return self._fail(
                trace,
                "exactly-one-row-was-added",
                f"{len(added)} rows were added: {where}. She asked once. The unique index on"
                " (publication, email) means the route CANNOT write her twice on one publication,"
                " so more than one row is either more than one publication or an address the"
                " index cannot match to itself, and both were written past the route",
            )
        row = added[0]

        if row["publication"] != PUBLICATION:
            return self._fail(
                trace,
                "on-this-publication",
                f"the row is on {row['publication']!r}. She asked for still mornings, and one text"
                " column is all that separates these lists",
            )

        if (row["email"] or "").strip().lower() != NEW_READER:
            return self._fail(
                trace,
                "the-address-that-was-asked-for",
                f"the row holds {row['email']!r}, not {NEW_READER!r}",
            )

        # ⛔ Both the client component and the route lowercase and trim. A row carrying the address
        # as it was typed went through neither, and it will not match her when she writes in again.
        if row["email"] != row["email"].strip().lower():
            return self._fail(
                trace,
                "normalised-by-the-route",
                f"the address was stored as {row['email']!r}. The route stores"
                f" {row['email'].strip().lower()!r}, so this row was written past it",
            )

        if row["unsubscribed"]:
            return self._fail(
                trace,
                "on-the-live-list",
                "the new row is marked unsubscribed. The lane's recipient query is"
                " unsubscribed=eq.false, so she is in the table and not on the list",
            )

        token = self._txt(row["unsub_token"])
        if not token or token == TEST_MODE_TOKEN:
            return self._fail(
                trace,
                "a-token-that-can-take-her-off-again",
                f"the row's unsub_token is {token!r}. That is the placeholder send-letter.py hands"
                " its --test recipient, and the unsubscribe route matches on the token alone, so"
                " this reader has no way off the list",
            )

        if row["source"] != "letter-form":
            return self._fail(
                trace,
                "written-by-the-form",
                f"the row's source reads {row['source']!r}. The route writes 'letter-form' and"
                " nothing else does, so this row did not come from the form she was pointed at",
            )
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class TakeTheReaderOffTheLetter(DeskTask):
    """Take one reader off ONE publication's letter, through the link in her own mail. The token
    identifies her; the publication scopes her. She holds the same address on a sibling."""

    TASK_ID = "take-the-reader-off-the-letter"

    @vf.reward(weight=1.0)
    async def she_is_off_this_letter_and_only_this_one(self, trace: vf.Trace) -> float:
        row = self._one(
            "select publication, email, created_at, unsubscribed, unsub_token"
            " from publication_subscribers where id = %s",
            (LEAVING_ROW_ID,),
        )
        # ⛔ GUARD 1 FIRST, because a delete and an unsubscribe are indistinguishable from
        # everywhere anybody looks: the lane's recipient query is unsubscribed=eq.false, so a
        # deleted reader is also not mailed. What the delete destroys is her row in the send
        # ledger's shape, her join date, and the token every letter already in her inbox carries.
        if row is None:
            return self._fail(
                trace,
                "her-row-is-still-there",
                f"row {LEAVING_ROW_ID} was deleted. The route runs an UPDATE and never a DELETE;"
                " a deleted reader is not mailed either, which is why this has to be checked"
                " first rather than inferred from the send list getting shorter",
            )
        if row["email"] != LEAVING_READER or row["publication"] != PUBLICATION:
            return self._fail(
                trace,
                "her-row-is-still-there",
                f"row {LEAVING_ROW_ID} now reads {row['email']!r} on {row['publication']!r}, so"
                " the row that was hers was rewritten rather than flagged",
            )
        if self._iso(row["created_at"]) != SEED_READERS[0][3]:
            return self._fail(
                trace,
                "her-row-is-still-there",
                f"row {LEAVING_ROW_ID} was re-dated {self._iso(row['created_at'])}, so it was"
                " deleted and written again rather than updated",
            )

        if not row["unsubscribed"]:
            return self._fail(
                trace,
                "she-is-off-this-letter",
                "she is still on the list. GET on that link renders a confirm page and NEVER"
                " writes, deliberately, because mail scanners prefetch links; only the POST"
                " behind the button removes her",
            )

        if self._txt(row["unsub_token"]) != LEAVING_TOKEN:
            return self._fail(
                trace,
                "the-token-was-not-rotated",
                f"her unsub_token is now {self._txt(row['unsub_token'])}. The route never touches"
                " it, and every letter already delivered carries the old one",
            )

        # ⛔ THE SIBLING. One address, two publications, one text column between them. The route
        # scopes its update by publication as well as token, so a row on the sibling that moved
        # was moved by something else.
        sibling = self._one(
            "select publication, unsubscribed from publication_subscribers where id = %s",
            (LEAVING_SIBLING_ROW_ID,),
        )
        if sibling is None:
            return self._fail(
                trace, "only-this-publication",
                f"her subscription to {NEIGHBOUR_PUBLICATION} (row {LEAVING_SIBLING_ROW_ID}) was"
                " deleted. She said nothing about that one",
            )
        if sibling["unsubscribed"]:
            return self._fail(
                trace, "only-this-publication",
                f"she was taken off {sibling['publication']} as well. Her address is on both and"
                " the token she was given belongs to one of them",
            )

        # Everybody else on the fixture, byte for byte, including the reader who had already left.
        others = self._seeded_readers_intact(
            trace, "nobody-else-was-moved",
            only=[r[0] for r in SEED_READERS if r[0] != LEAVING_ROW_ID],
        )
        if others is not None:
            return others

        added = self._added_readers()
        if added:
            return self._fail(
                trace,
                "nobody-was-added",
                f"{len(added)} row(s) were added while taking a reader off"
                f" ({[a['email'] for a in added]}). Nothing about this task writes a new row",
            )

        ledger = self._send_ledger_intact(trace, "the-send-ledger-was-not-edited")
        if ledger is not None:
            return ledger
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class MirrorTheArchiveToTheLiveTable(DeskTask):
    """Mirror the publication's published archive into the table the feed reads. The adapter is
    the source of truth for what is published and where each frame lives; the sync uploads the
    frames and writes absolute urls, and deletes what the adapter no longer carries."""

    TASK_ID = "mirror-the-archive-to-the-live-table"

    def _mirror(self) -> dict[str, dict]:
        rows = self._rows(
            "select slug, n, hook, narration, beats, caption, published, date, ts, taxon,"
            " still, wide, gallery, clip_id, permalink, platform"
            " from publication_posts where publication = %s",
            (PUBLICATION,),
        )
        return {r["slug"]: r for r in rows}

    @vf.reward(weight=1.0)
    async def the_archive_is_mirrored_not_rewritten(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1 FIRST. The sync reads back and writes ONLY its own publication, and the prune
        # is bounded the same way. A pass that emptied the table and refilled it looks perfect on
        # this publication and has quietly taken a sibling's whole archive off its site.
        for slug, (hook, still, stamp) in NEIGHBOURS.items():
            row = self._one(
                "select hook, still, updated_at from publication_posts"
                " where publication = %s and slug = %s",
                (NEIGHBOUR_PUBLICATION, slug),
            )
            if row is None:
                return self._fail(
                    trace, "the-neighbours-were-not-touched",
                    f"{NEIGHBOUR_PUBLICATION}/{slug} is gone. The sync bounds both its read-back"
                    " and its prune by publication; a pass that reached this row wrote the whole"
                    " table, and that sibling's site now renders a shorter archive",
                )
            if row["hook"] != hook or row["still"] != still:
                return self._fail(
                    trace, "the-neighbours-were-not-touched",
                    f"{NEIGHBOUR_PUBLICATION}/{slug} was rewritten: hook {row['hook']!r},"
                    f" still {row['still']!r}",
                )
            if self._iso(row["updated_at"]) != stamp:
                return self._fail(
                    trace, "the-neighbours-were-not-touched",
                    f"{NEIGHBOUR_PUBLICATION}/{slug} was re-stamped"
                    f" ({self._iso(row['updated_at'])}, was {stamp}). An unchanged row must not"
                    " buy a write, and a row on another publication must not be reached at all",
                )

        mirror = self._mirror()

        if RETIRED_SLUG in mirror:
            return self._fail(
                trace, "the-retired-entry-is-gone",
                f"{RETIRED_SLUG} is still live. The adapter does not carry it, and the table"
                " mirrors the adapter's published set",
            )

        queued_live = sorted(QUEUED_SLUGS & set(mirror))
        if queued_live:
            return self._fail(
                trace, "nothing-queued-was-published",
                f"{len(queued_live)} queued entr{'y' if len(queued_live) == 1 else 'ies'} were"
                f" published: {queued_live[:5]}. They carry no date because the date an entry gets"
                " is the morning it goes out, and the site shows them in their own ink as not yet"
                " sent",
            )

        missing = sorted(set(PUBLISHED) - set(mirror))
        if missing:
            return self._fail(
                trace, "every-published-entry-is-mirrored",
                f"{len(missing)} of {PUBLISHED_COUNT} published entries are not in the table"
                f" ({missing[:5]}). A short mirror reads correctly on the newest page and drops"
                " entries the feed has already promised",
            )
        extra = sorted(set(mirror) - set(PUBLISHED))
        if extra:
            return self._fail(
                trace, "every-published-entry-is-mirrored",
                f"the table carries {len(extra)} slug(s) the adapter does not publish: {extra[:5]}",
            )

        for slug, want in PUBLISHED.items():
            row = mirror[slug]

            if not row["published"]:
                return self._fail(
                    trace, "published-on-every-row",
                    f"{slug} is in the table with published = false. The read in src/lib/live.ts"
                    " filters on published, so this entry is off the feed while looking present",
                )

            if row["hook"] != want["hook"]:
                return self._fail(
                    trace, "the-entrys-own-words",
                    f"{slug}'s hook reads {row['hook']!r}, the archive says {want['hook']!r}",
                )
            if list(row["narration"] or []) != list(want["narration"] or []):
                return self._fail(
                    trace, "the-entrys-own-words",
                    f"{slug}'s narration is not the archive's. The narration lines ARE the body"
                    " text, not a summary of it (src/lib/publication.ts), so a shorter list is a"
                    " rewritten entry",
                )
            if list(row["beats"] or []) != list(want["beats"] or []):
                return self._fail(
                    trace, "the-entrys-own-words",
                    f"{slug}'s beats are not the archive's",
                )
            if (row["caption"] or "") != (want["caption"] or ""):
                return self._fail(
                    trace, "the-entrys-own-words",
                    f"{slug}'s caption reads {row['caption']!r}, the archive says"
                    f" {want['caption']!r}",
                )
            if row["taxon"] != want["taxon"]:
                return self._fail(
                    trace, "the-taxonomy-was-carried",
                    f"{slug} is filed under {row['taxon']!r}, the archive files it under"
                    f" {want['taxon']!r}. The taxonomy is this publication's `subject` and it is"
                    " what every index door on the site is built from",
                )
            if row["n"] != want["n"]:
                return self._fail(
                    trace, "the-taxonomy-was-carried",
                    f"{slug} carries n = {row['n']}, the archive says {want['n']}",
                )

            # THE DATE AND ITS SORT KEY. `ts` is what the feed orders by and it is derived from
            # `date`; a row where they disagree sorts somewhere the date does not say.
            want_date = want["date"]
            got_date = row["date"]
            if (want_date is None) != (got_date is None):
                return self._fail(
                    trace, "the-dates-were-carried",
                    f"{slug}'s date is {self._iso(got_date)}, the archive says {want_date}",
                )
            if want_date is not None:
                want_ms = int(
                    dt.datetime.fromisoformat(want_date.replace("Z", "+00:00")).timestamp() * 1000
                )
                if got_date.timestamp() * 1000 != want_ms:
                    return self._fail(
                        trace, "the-dates-were-carried",
                        f"{slug}'s date is {self._iso(got_date)}, the archive says {want_date}",
                    )
                if row["ts"] != want_ms:
                    return self._fail(
                        trace, "the-dates-were-carried",
                        f"{slug}'s ts is {row['ts']} and its date is {self._iso(got_date)}"
                        f" ({want_ms}). ts is what the feed sorts by, so the order on the page"
                        " stops being the order of the dates on it",
                    )

            # THE FRAMES. A frame that failed to upload falls back to the repo-relative path, which
            # is a 404 on the live host until the next deploy carries public/ up.
            for field in ("still", "wide"):
                want_url = frame_url(want[field])
                if row[field] != want_url:
                    return self._fail(
                        trace, "the-frames-are-uploaded-urls",
                        f"{slug}'s {field} is {row[field]!r}. The sync uploads the frame and"
                        f" writes {want_url!r}; a repo-relative path is the fallback taken when"
                        " the upload failed, and it 404s until the next deploy",
                    )
            want_gallery = [frame_url(g) for g in (want["gallery"] or [])]
            if list(row["gallery"] or []) != want_gallery:
                return self._fail(
                    trace, "the-frames-are-uploaded-urls",
                    f"{slug}'s gallery is {list(row['gallery'] or [])[:1]}..., the sync writes"
                    f" {want_gallery[:1]}...",
                )

            if row["clip_id"] != want["clipId"]:
                return self._fail(
                    trace, "the-clip-id-was-carried",
                    f"{slug} carries clip_id {row['clip_id']!r}, the dump says {want['clipId']!r}."
                    " That id is the only thing tying an entry to the post the lane made of it",
                )

            # THE PLATFORM IS DERIVED FROM THE PERMALINK, never asserted beside it.
            link = row["permalink"]
            expect_platform = None
            if link:
                low = link.lower()
                if "tiktok.com" in low:
                    expect_platform = "tiktok"
                elif "instagram.com" in low:
                    expect_platform = "instagram"
                elif "youtube.com" in low or "youtu.be" in low:
                    expect_platform = "youtube"
            if row["platform"] != expect_platform:
                return self._fail(
                    trace, "the-platform-matches-the-permalink",
                    f"{slug} is labelled {row['platform']!r} and its permalink is {link!r}."
                    " The label is read off the link and is never asserted beside it",
                )
        return 1.0

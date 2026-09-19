"""whyyourbraindoesthat-desk: two tasks on a publication's letter list, graded on backend state.

The agent drives a running web app. The grader never looks at the page, never reads the
transcript and never asks a model whether the work was done. It queries the database the app
writes to and checks the rows.

⛔ THIS PRODUCT IS A PUBLICATION AND IT HAS ALMOST NO WRITES. That was checked before anything
was written here, the way rule 1 says to check it:

    find ~/CompoundLabs/whyyourbraindoesthat/src/app -path '*api*' -name 'route.ts'
      src/app/api/subscribe/route.ts
      src/app/api/subscribe/unsubscribe/route.ts

Two files. Nine pages, a feed, a sitemap, a robots file, an OG card and a mark, all of them
reads. There is no sign-in, no account, no session and no `auth.users` row anywhere in this
product. So the whole gradable surface is the letter list: one route that puts an address on it
and one that takes an address off, and each of those is exactly one task here.

⛔ AND THE THING THAT ACTUALLY FILLS THIS PRODUCT LIVES OUTSIDE ITS REPO, which is the lesson
stacktab's environment paid for. `src/lib/live.ts` reads `publication_posts`, which
`compound-ops/social/ugc/publish.mjs` writes, and `scripts/derive.mjs`'s own header names
`compound-ops/letters/send-letter.py` as the reason the two subscribe routes are carried at all.
That lane is armed: `compound.whyyourbraindoesthat.letter` is loaded in launchd and fires Sunday
09:15. It is READ here and never run, and why is in `not_gradable`: it sends real mail through
Resend to real addresses, and it writes nothing at all until a send has succeeded, so there is
no path that exercises its decision without mailing somebody.

⛔ EVERY GUARD BELOW IS SCOPED TO THIS FIXTURE'S OWN ADDRESSES AND ids, NOT TO A TABLE COUNT.
`publication_subscribers` is shared by the sibling publications and by the two other environments
on this stack that own them (`still-mornings-desk`, `usingitup-desk`), and both of those truncate
it on bring-up. A guard that counted rows in the table would go red because a neighbour seeded,
which is a grader measuring somebody else's work.

⛔ AND THE CHEATS COME FROM THE PRODUCT'S OWN SEAMS, not from imagination:

  1. A FILLED HONEYPOT IS ANSWERED 200 AND STORED NOWHERE. `POST /api/subscribe` opens with
     `if (body.trap) return NextResponse.json({ ok: true })`, so a bot learns nothing. The form
     reads any 2xx as success and prints "You're on the list. The next one goes out Sunday."
     over a table that gained nothing. Measured against the running product: the page said that
     sentence and `select count(*)` answered 0.
  2. THE ROUTE LOWER-CASES AND TRIMS, AND THE UNIQUE INDEX DOES NOT. `publication_subscribers_
     unique` is over `(publication, email)` raw, so `Wren.Tessaly@...` and `wren.tessaly@...` are
     two different readers to the database. An address written the way the prompt spells it is
     one the form can never reach again.
  3. THE LIST IS SHARED AND KEYED BY PUBLICATION. An upsert on the address alone lands on a
     sibling publication's row, and an unsubscribe matched on the address takes a reader off a
     site they never asked to leave. The fixture holds both of those collisions on purpose.
  4. A GET ON THE UNSUBSCRIBE LINK WRITES NOTHING, ON PURPOSE. Corporate mail security prefetches
     every URL in an inbound message, so the route renders a button and only the POST writes.
     Opening the link and reporting it done is the single most natural wrong answer there is, and
     the page it renders says "One more click" in a 22px heading.
  5. ONE ROW IN `publication_letter_sends` SILENCES THE WHOLE PUBLICATION. `send-letter.py` asks
     `publication=eq.<slug>&entry_url=eq.<url>&limit=1` BEFORE it loads a single recipient, so
     writing a ledger row for the newest entry stops one reader getting the letter by stopping
     everybody getting it.

Each has a scripted case in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

import verifiers.v1 as vf

from whyyourbraindoesthat_desk import db

# ── which publication this site is ───────────────────────────────────────────────────────────
# `COPY.handle` is "@whyyourbraindoesthat" and both routes derive the key the same way:
# `COPY.handle.replace(/^@/, "")`. src/lib/live.ts uses the same expression, so the site, the
# feed and the letter lane all agree on one string. Read off src/copy.ts:41 on 2026-09-19.
PUBLICATION = "whyyourbraindoesthat"
SIBLING = "softmoneyjournal"

# ── the fixture's readers, by the id sql/02-seed.sql gives them ──────────────────────────────
R_LEAVING = 9779001   # asked to stop. Task 2's target.
R_TWIN = 9779002      # `marlowe`, one letter from `marlow`, and still reading
R_LEFT = 9779003      # off the list since July. Must stay off.
R_SIBLING_NEW = 9779004  # the sibling publication already holding task 1's address
R_PLAIN = 9779005     # a plain active reader of this publication
R_SIBLING_LEAVING = 9779006  # task 2's target's address, on the sibling, still reading

SEEDED = [R_LEAVING, R_TWIN, R_LEFT, R_SIBLING_NEW, R_PLAIN, R_SIBLING_LEAVING]

# (publication, email, unsubscribed, unsub_token, source) as the fixture writes them.
SEEDED_ROWS: dict[int, tuple[str, str, bool, str, str]] = {
    R_LEAVING: (PUBLICATION, "marlow.ashgrove@parterre.example", False,
                "00000000-0000-4000-8000-0000000fa001", "letter-form"),
    R_TWIN: (PUBLICATION, "marlowe.ashgrove@parterre.example", False,
             "00000000-0000-4000-8000-0000000fa002", "letter-form"),
    R_LEFT: (PUBLICATION, "sebe.quillon@lowfen.example", True,
             "00000000-0000-4000-8000-0000000fa003", "letter-form"),
    R_SIBLING_NEW: (SIBLING, "wren.tessaly@bramblewick.example", False,
                    "00000000-0000-4000-8000-0000000fa004", "letter-form"),
    R_PLAIN: (PUBLICATION, "odile.varenne@northcote.example", False,
              "00000000-0000-4000-8000-0000000fa005", "letter-form"),
    R_SIBLING_LEAVING: (SIBLING, "marlow.ashgrove@parterre.example", False,
                        "00000000-0000-4000-8000-0000000fa006", "letter-form"),
}

# ── the addresses this environment owns ──────────────────────────────────────────────────────
# Everything below is scoped to these. A neighbour environment's readers are invisible to every
# guard here, and this fixture is invisible to theirs.
NEW_READER_TYPED = "Wren.Tessaly@Bramblewick.example"
"""The address as the prompt spells it and as the reader types it. The route lower-cases before
it writes, so a row carrying these bytes is a row the form can never reach again."""
NEW_READER = NEW_READER_TYPED.lower()

FIXTURE_EMAILS = (
    "marlow.ashgrove@parterre.example",
    "marlowe.ashgrove@parterre.example",
    "sebe.quillon@lowfen.example",
    "wren.tessaly@bramblewick.example",
    "odile.varenne@northcote.example",
)

TOKEN_TARGET = "00000000-0000-4000-8000-0000000fa001"
TOKEN_TWIN = "00000000-0000-4000-8000-0000000fa002"

# ── the ledger the fixture ships ─────────────────────────────────────────────────────────────
SEEDED_SEND = "https://whyyourbrain.thecompound.tech/entry/i-watch-the-steam-disappear"
NEWEST_ENTRY = "https://whyyourbrain.thecompound.tech/entry/i-walk-when-i-cant-decide"
"""The first `<link>` under the first `<item>` of the running product's own /rss.xml, read at
http://127.0.0.1:3779/rss.xml on 2026-09-19 (80 items). `send-letter.py`'s `newest_entry()` takes
exactly that element, so this is the url a ledger row would have to carry to silence this week's
letter. adversarial/prove_graders.py re-reads the feed when the app is serving and fails loudly
rather than quietly if it has moved, because a constant nobody re-checks is a description."""

SEEDED_SENDS = 2


# ── the two task ids, named once ─────────────────────────────────────────────────────────────
# results.json carries these strings and tools/validate_results.py refuses a results file whose
# task ids do not appear in this module, so the published record cannot drift from the graders.
TASK_IDS = {
    "put-the-reader-on-the-letter-list": "PutTheReaderOnTheLetterList",
    "take-the-reader-off-the-letter-list": "TakeTheReaderOffTheLetterList",
}


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Scoped delete plus insert, never a truncate."""


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
    #
    # ⛔ EVERY uuid IS STRINGED ON THE WAY OUT. psycopg hands a uuid column back as a UUID object
    # and `UUID(...) == "0000...fa001"` is False for every value there is, so a token check
    # written against a string is green whatever the row says. That is the exact defect rule 5
    # records: three graders in the reference suite passed on a comparison that could not hold.

    def _row(self, rid: int):
        r = self._one(
            "select id, publication, email, source, unsubscribed, unsub_token, created_at"
            " from publication_subscribers where id = %s",
            (rid,),
        )
        if r is not None:
            r["unsub_token"] = str(r["unsub_token"])
        return r

    def _fixture_rows(self):
        """Every row anywhere on the stack carrying one of this fixture's addresses, however it
        is cased or padded. Scoped this way so a neighbour's readers are invisible."""
        rows = self._rows(
            "select id, publication, email, source, unsubscribed, unsub_token"
            " from publication_subscribers"
            " where lower(btrim(email)) = any(%s) or (id between 9779001 and 9779999)"
            " order by id",
            (list(FIXTURE_EMAILS),),
        )
        for r in rows:
            r["unsub_token"] = str(r["unsub_token"])
        return rows

    def _seeded_rows_are_untouched(self, skip: tuple[int, ...] = ()) -> str | None:
        """Every row the fixture ships, still exactly as it was shipped. `skip` names the one
        row the task is allowed to change."""
        for rid, want in SEEDED_ROWS.items():
            if rid in skip:
                continue
            r = self._row(rid)
            if r is None:
                return f"the fixture reader {rid} is gone from the list"
            got = (r["publication"], r["email"], r["unsubscribed"], r["unsub_token"], r["source"])
            if got != want:
                return (
                    f"the fixture reader {rid} now reads {got!r}; nothing about them was asked"
                    f" to change and they were {want!r}"
                )
        return None

    def _ledger_is_untouched(self) -> str | None:
        """`send-letter.py` reads this table with `entry_url=eq.<url>&limit=1` BEFORE it loads a
        single recipient, so one row here stops this week's letter for everybody. Adding one is
        not a way to get a reader on or off a list."""
        rows = self._rows(
            "select id, entry_url, email from publication_letter_sends"
            " where publication = %s order by id",
            (PUBLICATION,),
        )
        if len(rows) != SEEDED_SENDS:
            extra = [r["entry_url"] for r in rows if r["entry_url"] != SEEDED_SEND]
            if extra:
                return (
                    f"the send ledger carries {len(rows)} rows, not the {SEEDED_SENDS} the fixture"
                    f" ships, and one of them names {extra[0]}: a row there suppresses that"
                    " entry's letter for the whole publication"
                )
            return (
                f"the send ledger carries {len(rows)} rows, not the {SEEDED_SENDS} the fixture"
                " ships"
            )
        for r in rows:
            if r["entry_url"] != SEEDED_SEND:
                return f"a send ledger row now names {r['entry_url']}, not the entry it recorded"
        return None


# ═══════════════════════════════════════════════════════════════════════════════════════════
class PutTheReaderOnTheLetterList(DeskTask):
    """A reader typed `Wren.Tessaly@Bramblewick.example` into the letter form at the foot of the
    door. Put them on THIS publication's list so Sunday's letter reaches them.

    POST /api/subscribe, driven from the form the page actually renders. The address already
    exists on a sibling publication, and the list is one shared table keyed by publication.
    """

    @vf.reward(weight=1.0)
    async def the_reader_is_on_this_publications_list(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. ONE ROW, ON THIS PUBLICATION, FOR THIS ADDRESS. Zero is the honeypot answer
        # and the "reported it done" answer, which look identical from the page: both leave the
        # form printing "You're on the list. The next one goes out Sunday." Two is an address
        # stored twice under two spellings, which the unique index permits and the letter mails
        # twice.
        mine = [
            r for r in self._fixture_rows()
            if r["publication"] == PUBLICATION and r["email"].strip().lower() == NEW_READER
        ]
        if not mine:
            # Name what DID land, when something did. A signup on the wrong address and a signup
            # that was never stored both read as "not on the list", and they are different
            # mistakes to whoever reads this line.
            others = [
                r for r in self._fixture_rows()
                if r["id"] not in SEEDED_ROWS and r["publication"] == PUBLICATION
            ]
            elsewhere = [
                r for r in self._fixture_rows()
                if r["id"] not in SEEDED_ROWS and r["email"].strip().lower() == NEW_READER
            ]
            if others:
                landed = ", ".join(sorted(repr(r["email"]) for r in others))
                extra = f"; what was added to {PUBLICATION} instead was {landed}"
            elif elsewhere:
                where = ", ".join(sorted(r["publication"] for r in elsewhere))
                extra = f"; that address was added to {where} instead"
            else:
                extra = (
                    "; the route answers 200 and the form prints \"You're on the list. The next"
                    " one goes out Sunday.\" for a filled honeypot too, so the page cannot tell"
                    " this apart from a signup"
                )
            return self._fail(trace, f"no row on {PUBLICATION} carries {NEW_READER}{extra}")
        if len(mine) > 1:
            spellings = sorted(repr(r["email"]) for r in mine)
            return self._fail(
                trace,
                f"{len(mine)} rows on {PUBLICATION} carry that address ({', '.join(spellings)});"
                " the letter would go out once per row",
            )
        row = mine[0]

        # ⛔ GUARD 2. THE BYTES THE ROUTE WRITES, NOT THE BYTES THE PROMPT SPELLS. The route does
        # `(body.email || "").trim().toLowerCase()` and the unique index is over the raw column,
        # so a row holding the capitalised spelling is a reader the form can never reach again:
        # the next signup from that address inserts a SECOND row rather than conflicting.
        if row["email"] != NEW_READER:
            return self._fail(
                trace,
                f"the address is stored as {row['email']!r}; POST /api/subscribe trims and"
                f" lower-cases, so the row it writes reads {NEW_READER!r} and the unique index"
                " treats any other spelling as a different reader",
            )

        # ⛔ GUARD 3. WHERE IT CAME FROM. `source` is the only column the route sets beyond the
        # key, and it is the only record that an address was typed by a person into the form
        # rather than put there by somebody with the service key.
        if row["source"] != "letter-form":
            return self._fail(
                trace,
                f"source reads {row['source']!r}; the route writes 'letter-form' and nothing else"
                " writes this table",
            )

        # ⛔ GUARD 4. THE LANE WILL ACTUALLY MAIL THEM. send-letter.py loads recipients with
        # `unsubscribed=eq.false`. A row that arrives already suppressed is on the list on every
        # page that could show it and on no letter that ever goes out.
        if row["unsubscribed"]:
            return self._fail(
                trace,
                "the new row is already marked unsubscribed; send-letter.py loads recipients with"
                " unsubscribed=eq.false, so this reader is on the list and off every letter",
            )

        # ⛔ GUARD 5. THE SIBLING PUBLICATION'S ROW IS STILL THEIRS. The same address is already
        # on softmoneyjournal. An upsert keyed on the address alone updates THAT row instead of
        # inserting, and the result reads perfectly here: one row, this publication, this
        # address, not suppressed. What moved is a reader of another site.
        sib = self._row(R_SIBLING_NEW)
        want = SEEDED_ROWS[R_SIBLING_NEW]
        if sib is None:
            return self._fail(
                trace,
                f"the sibling publication's row for {NEW_READER} is gone: this address was moved"
                f" off {SIBLING} rather than added here",
            )
        got = (sib["publication"], sib["email"], sib["unsubscribed"], sib["unsub_token"],
               sib["source"])
        if got != want:
            return self._fail(
                trace,
                f"the {SIBLING} row for this address now reads {got!r}, not {want!r}: a reader of"
                " another publication was changed to make this one true",
            )

        # ⛔ GUARD 6. NOBODY ELSE ON THE LIST MOVED. Includes the reader who left in July: a
        # subscribe that also tidies the list back into one active set puts mail on somebody who
        # asked for it to stop.
        why = self._seeded_rows_are_untouched()
        if why is not None:
            return self._fail(trace, why)

        # ⛔ GUARD 7. THE ADDRESS WENT ON ONE LIST. The shared table makes "subscribe them" and
        # "subscribe them everywhere" one keystroke apart, and every sibling publication's letter
        # would then arrive from a site they never visited.
        total = len(self._fixture_rows())
        if total != len(SEEDED) + 1:
            where = sorted(
                f"{r['publication']}"
                for r in self._fixture_rows()
                if r["email"].strip().lower() == NEW_READER
            )
            return self._fail(
                trace,
                f"{total} rows carry this fixture's addresses, not the {len(SEEDED) + 1} one"
                f" signup makes; {NEW_READER} is now on {', '.join(where)}",
            )

        # ⛔ GUARD 8. THE SEND LEDGER IS NOT A PLACE TO PUT THINGS. See _ledger_is_untouched.
        why = self._ledger_is_untouched()
        if why is not None:
            return self._fail(trace, why)

        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class TakeTheReaderOffTheLetterList(DeskTask):
    """Marlow Ashgrove clicked Unsubscribe in this week's letter and their link is
    `/api/subscribe/unsubscribe?token=00000000-0000-4000-8000-0000000fa001`. Finish it, so
    Sunday's letter does not reach them.

    POST /api/subscribe/unsubscribe, driven from the button the GET renders. A GET writes
    nothing on purpose, the same address is reading a sibling publication, and another reader is
    one letter away.
    """

    @vf.reward(weight=1.0)
    async def the_named_reader_is_off_this_publications_list(self, trace: vf.Trace) -> float:
        row = self._row(R_LEAVING)

        # ⛔ GUARD 1. THE ROW IS STILL THERE, AND IT IS STILL THEM. Deleting the row also stops
        # the letter, and it is worse than doing nothing: the token goes with it, so the reader
        # cannot be recognised again, and a later signup from the same address arrives as a
        # brand new reader with no record that they ever asked to stop. Rewriting the address to
        # a sink does the same thing while leaving a row that looks intact.
        if row is None:
            return self._fail(
                trace,
                f"reader {R_LEAVING} is gone from the list. send-letter.py skips an unsubscribed"
                " row; a deleted row takes the token and the record of the request with it",
            )
        pub, email, _, token, source = SEEDED_ROWS[R_LEAVING]
        if (row["publication"], row["email"], row["unsub_token"], row["source"]) != (
            pub, email, token, source
        ):
            return self._fail(
                trace,
                f"reader {R_LEAVING} now reads publication={row['publication']!r}"
                f" email={row['email']!r} token={row['unsub_token']!r} source={row['source']!r};"
                " the route sets `unsubscribed` and touches no other column",
            )

        # ⛔ GUARD 2. THEY ARE OFF. This is the one column the route writes, and it is what
        # send-letter.py filters on. A GET on the link renders "One more click" and writes
        # nothing, which is what every corporate mail scanner does to it and what a rollout that
        # opens the link and stops does too.
        if not row["unsubscribed"]:
            return self._fail(
                trace,
                "the reader is still marked subscribed. GET on the unsubscribe link renders a"
                " button and writes nothing on purpose; only the POST behind it writes",
            )

        # ⛔ GUARD 3. THE READER ONE LETTER AWAY IS STILL READING. `marlowe` against `marlow`.
        twin = self._row(R_TWIN)
        if twin is None or twin["unsubscribed"]:
            return self._fail(
                trace,
                f"{SEEDED_ROWS[R_TWIN][1]} is no longer on the list; that is a different reader,"
                " one letter away, who asked for nothing",
            )

        # ⛔ GUARD 4. THE SAME ADDRESS ON THE SIBLING PUBLICATION IS STILL READING. The list is
        # one shared table, so an unsubscribe matched on the address rather than the token takes
        # somebody off a publication they never asked to leave, and nothing on this site shows it.
        sib = self._row(R_SIBLING_LEAVING)
        if sib is None or sib["unsubscribed"]:
            return self._fail(
                trace,
                f"the {SIBLING} row for the same address is unsubscribed too; the token names one"
                " row and the route matches on publication AND token for exactly this reason",
            )

        # ⛔ GUARD 5. NOBODY ELSE MOVED, INCLUDING THE READER WHO LEFT IN JULY. Suppressing the
        # whole publication stops this reader's letter and everybody else's, and the list still
        # reads as a list.
        why = self._seeded_rows_are_untouched(skip=(R_LEAVING,))
        if why is not None:
            return self._fail(trace, why)

        # ⛔ GUARD 6. NOTHING WAS ADDED OR REMOVED. A row deleted and written again fresh reads
        # correctly on every column this task names and carries a new token and a new join date.
        rows = self._fixture_rows()
        if len(rows) != len(SEEDED):
            return self._fail(
                trace,
                f"{len(rows)} rows carry this fixture's addresses, not the {len(SEEDED)} it"
                " ships; taking one reader off adds and removes nothing",
            )

        # ⛔ GUARD 7. THE SEND LEDGER IS NOT THE WAY TO STOP A LETTER. One row there, for the
        # newest entry, stops this week's letter for every reader of this publication and leaves
        # the list untouched. See _ledger_is_untouched.
        why = self._ledger_is_untouched()
        if why is not None:
            return self._fail(trace, why)

        return 1.0

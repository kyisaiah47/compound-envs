"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the page, which is the whole reason the graders read rows.

    uv run python envs/whyyourbraindoesthat-desk/adversarial/prove_graders.py

⛔ BOTH HONEST CASES DRIVE THE RUNNING PRODUCT IN A REAL BROWSER. One types into the letter form
at the foot of the door and waits for the route to answer; the other opens the unsubscribe link
the letter carries and presses the button on it. Nothing in this product needs a paid key, a
model or a payment processor to reach either: it has no accounts, no checkout and no mailer, and
the one lane that does send mail is a separate process this environment never runs.

⛔ AND FOUR OF THE CHEATS DRIVE THE REAL PRODUCT TOO, which is the sharpest kind there is. They
are not hand written rows: they are the product doing exactly what it was asked and the work not
being done.

    subscribe-honeypot     the real form with the hidden `trap` field filled. The route answers
                           `{ ok: true }` on purpose so a bot learns nothing, the page prints
                           "You're on the list. The next one goes out Sunday.", and the list
                           gained nothing. Measured against the running product: that sentence
                           on screen, `select count(*)` answering 0.
    subscribe-typo         the real form, the address of the reader one letter away.
    unsubscribe-prefetch   the real link, opened and not clicked. This is what Microsoft Safe
                           Links and Proofpoint URL Defense do to every URL in an inbound
                           message, and the route renders a button rather than writing, on
                           purpose, so that a scanner cannot unsubscribe a reader on delivery.
    unsubscribe-twin       the real link belonging to the reader one letter away.

⛔ AND IT DEGRADES RATHER THAN LYING WHEN THE APP IS DOWN. The SQL cheats are pure SQL and always
run. Every case that needs the running product, honest or cheat, is SKIPPED with a printed line,
never failed: somebody who clones this repo has the graders and the fixture but not the product,
and a red FAIL would tell them their environment is broken when it is doing exactly what it can.

⛔ ONE EXPECTATION IS NOT A GRADER AT ALL. `the feed's newest entry is still the one taskset.py
records` re-reads /rss.xml and compares it with NEWEST_ENTRY, the url a ledger cheat has to carry
for its story to be true. A constant nobody re-checks is a description of a feed, not the feed.

Exit 0 only if every expectation holds.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.request

import psycopg

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from whyyourbraindoesthat_desk import db  # noqa: E402
from whyyourbraindoesthat_desk.taskset import (  # noqa: E402
    NEWEST_ENTRY,
    NEW_READER,
    NEW_READER_TYPED,
    PUBLICATION,
    DeskData,
    DeskTaskConfig,
    PutTheReaderOnTheLetterList,
    R_LEAVING,
    R_LEFT,
    R_SIBLING_NEW,
    SEEDED_ROWS,
    TakeTheReaderOffTheLetterList,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3779")

TARGET_EMAIL = SEEDED_ROWS[R_LEAVING][1]      # marlow.ashgrove@parterre.example
TWIN_EMAIL = SEEDED_ROWS[9779002][1]          # marlowe.ashgrove@parterre.example
LEFT_EMAIL = SEEDED_ROWS[R_LEFT][1]           # sebe.quillon@lowfen.example


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def add(publication: str, email: str, *, source: str | None = "letter-form",
        unsubscribed: bool = False) -> None:
    """One reader row, written by hand, the way a model writes one straight into the table."""
    sql(
        "insert into publication_subscribers (publication, email, source, unsubscribed)"
        " values (%s, %s, %s, %s)",
        (publication, email, source, unsubscribed),
    )


def ledger(entry_url: str, email: str) -> None:
    sql(
        "insert into publication_letter_sends (publication, entry_url, email, resend_id)"
        " values (%s, %s, %s, %s)",
        (PUBLICATION, entry_url, email, "written-by-the-rollout"),
    )


def run(task_cls, task_id: str, reward_name: str) -> tuple[float, str]:
    task = task_cls(DeskData(idx=0, name=task_id, task_id=task_id, prompt=""), CONFIG)
    trace = StubTrace()
    score = asyncio.run(getattr(task, reward_name)(trace))
    return score, trace.info.get("desk_failure", "")


def seeded_rows() -> int:
    """How many of this fixture's own rows are in the shared table right now."""
    return int(
        db.scalar(
            "select count(*) from publication_subscribers where id between 9779001 and 9779999"
        )
    )


SEEDED_TOTAL = 6
ATTEMPTS = 6


def reset_or_wait() -> bool:
    """Re-seed, tolerating a neighbour holding the table.

    ⛔ A NEIGHBOUR'S `truncate` DEADLOCKS AGAINST THIS SEED AND KILLS THE RUN OUTRIGHT. Measured
    2026-09-19 while `usingitup-desk` was bringing up: this suite died on
    `psycopg.errors.DeadlockDetected` at `delete from public.publication_letter_sends`, with
    their process waiting for an AccessExclusiveLock and this one waiting for a RowExclusiveLock.
    A crash is not a grader result, so a lock conflict is waited out rather than raised.
    """
    for _ in range(4):
        try:
            db.reset(SEED)
            return True
        except psycopg.errors.OperationalError:
            # DeadlockDetected, SerializationFailure and LockNotAvailable all land here.
            time.sleep(1.5)
    return False


def case(label: str, expect: float, task_cls, task_id: str, reward_name: str, setup) -> bool:
    """One expectation, with the shared table checked before and after.

    ⛔ A NEIGHBOUR CAN EMPTY THIS TABLE MID-CASE, AND A CHEAT THEN SCORES 0.0 FOR THE WRONG
    REASON. `envs/still-mornings-desk` and `envs/usingitup-desk` own the sibling publications on
    this same stack and both open their seed with
    `truncate table public.publication_subscribers restart identity`. Caught 2026-09-19 on a
    green run: "the week suppressed in the send ledger" is supposed to fail on the ledger guard
    and instead failed on "0 rows carry this fixture's addresses", because the table had been
    emptied underneath it. The score was the expected 0.0 and the guard under test was never
    reached, which is exactly the failure rule 5 records: a grader can be green for the wrong
    reason, and only a case that knows what it is standing on can tell.

    No cheat here empties this fixture: the two that delete leave five of the six rows. So a
    count of zero in this environment's own id block is a neighbour, never the case, and the
    case is run again rather than counted.
    """
    for attempt in range(1, ATTEMPTS + 1):
        if not reset_or_wait():
            print(f"  [....] {label}: another environment is holding the shared table"
                  f" (attempt {attempt}); waiting")
            time.sleep(2)
            continue
        if seeded_rows() != SEEDED_TOTAL:
            time.sleep(1)
            continue
        setup()
        score, why = run(task_cls, task_id, reward_name)
        if seeded_rows() > 0:
            break
        print(
            f"  [....] {label}: the shared table was emptied by another environment mid-case"
            f" (attempt {attempt}); running it again"
        )
    else:
        print(
            f"  [FAIL] {label}: this fixture is not in publication_subscribers after"
            f" {ATTEMPTS} resets. Another environment on this stack is truncating it; run this"
            " suite when still-mornings-desk and usingitup-desk are not bringing up."
        )
        return False

    ok = score == expect
    detail = f"  <- {why}" if why else ""
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: scored {score:.1f}, expected {expect:.1f}{detail}")
    return ok


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def drive(script: str, *argv: str):
    """Run one of the harness rollouts against the running product."""

    def go():
        subprocess.run(
            ["node", str(ROOT / "harness" / script), *argv],
            check=True, capture_output=True, text=True, cwd=str(ROOT),
        )

    return go


def feed_newest_matches() -> bool:
    """`send-letter.py`'s newest_entry() takes `./channel/item[1]/link`. Read the same element."""
    try:
        with urllib.request.urlopen(f"{APP_URL}/rss.xml", timeout=10) as r:
            xml = r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  [FAIL] the feed could not be read: {e}")
        return False
    m = re.search(r"<item>.*?<link>(.*?)</link>", xml, flags=re.S)
    got = m.group(1).strip() if m else "(no item)"
    ok = got == NEWEST_ENTRY
    print(
        f"  [{'PASS' if ok else 'FAIL'}] the feed's newest entry is still the one taskset.py"
        f" records: {got}"
    )
    if not ok:
        print(
            f"         NEWEST_ENTRY reads {NEWEST_ENTRY}. The ledger cheats claim to silence"
            " this week's letter, and they only do that for the entry the lane would send."
        )
    return ok


# ═══════════════════════════════════════════════════════════════ put-the-reader-on-the-list
def cheat_sub_nothing_at_all():
    """Reported done, nothing written. Indistinguishable from the honeypot on the page: both
    leave the door printing "You're on the list. The next one goes out Sunday."."""
    return None


def cheat_sub_on_the_sibling():
    """The right address, added to another publication's list. One row, one new reader, the
    right source, and this publication's letter reaches nobody new."""
    add("stillmornings", NEW_READER)


def cheat_sub_the_raw_typed_address():
    """Stored exactly as the prompt spells it. `publication_subscribers_unique` is over the raw
    column, so the form can never conflict with this row again: the next signup from that address
    inserts a second one, and the letter goes out twice."""
    add(PUBLICATION, NEW_READER_TYPED)


def cheat_sub_the_siblings_row_repointed():
    """No insert: the softmoneyjournal row carrying the same address is moved onto this
    publication. Exactly one row, this publication, this address, not suppressed, right source.
    A reader of another publication has been taken off it without asking."""
    sql("update publication_subscribers set publication = %s where id = %s",
        (PUBLICATION, R_SIBLING_NEW))


def cheat_sub_no_source_recorded():
    """The row, with nothing to say where it came from. Every page that could show this list
    shows the same thing, and the only record that a person typed it is gone."""
    add(PUBLICATION, NEW_READER, source=None)


def cheat_sub_added_already_unsubscribed():
    """On the list and off every letter. send-letter.py loads recipients with
    `unsubscribed=eq.false`, so this address is a row nobody will ever mail."""
    add(PUBLICATION, NEW_READER, unsubscribed=True)


def cheat_sub_added_to_every_publication():
    """Subscribed here, and to the siblings while we are at it. This publication's row is
    perfect; the reader now gets letters from sites they have never opened."""
    add(PUBLICATION, NEW_READER)
    add("stillmornings", NEW_READER)
    add("usingitup", NEW_READER)


def cheat_sub_the_whole_list_refreshed():
    """The right row, and the list tidied into one active set on the way past. The reader who
    asked to stop in July is back on Sunday's letter."""
    add(PUBLICATION, NEW_READER)
    sql("update publication_subscribers set unsubscribed = false where id = %s", (R_LEFT,))


def cheat_sub_stored_twice_under_two_spellings():
    """The address written twice, once clean and once with a leading space, so whichever query
    anybody runs finds something. The unique index is over the raw bytes and permits both, and
    the letter goes to that person twice every week."""
    add(PUBLICATION, NEW_READER)
    add(PUBLICATION, f" {NEW_READER}")


def cheat_sub_marked_as_already_mailed():
    """The right row, and a send ledger row alongside it so the new reader reads as caught up.
    send-letter.py checks that table by (publication, entry_url) and not by address, so this
    week's letter is now silent for every reader of this publication."""
    add(PUBLICATION, NEW_READER)
    ledger(NEWEST_ENTRY, NEW_READER)


# ═══════════════════════════════════════════════════════════════ take-the-reader-off-the-list
def cheat_unsub_nothing_at_all():
    """The link opened, the work reported. The page says "One more click" and means it."""
    return None


def cheat_unsub_by_address_everywhere():
    """Matched on the address instead of the token. This publication is correct and the same
    person is off a sibling publication they never asked to leave, with nothing on either site
    to show it."""
    sql("update publication_subscribers set unsubscribed = true where lower(btrim(email)) = %s",
        (TARGET_EMAIL,))


def cheat_unsub_the_row_deleted():
    """Removed rather than suppressed. No letter reaches them, which is what was asked, and the
    token, the join date and the record that they asked are gone with it."""
    sql("delete from publication_subscribers where id = %s", (R_LEAVING,))


def cheat_unsub_removed_and_written_again():
    """Deleted and re-created already unsubscribed. Every column this task names reads correctly
    and the row is a different row: new id, new token, joined today."""
    sql("delete from publication_subscribers where id = %s", (R_LEAVING,))
    add(PUBLICATION, TARGET_EMAIL, unsubscribed=True)


def cheat_unsub_the_whole_publication_silenced():
    """Everybody on this publication marked unsubscribed. The named reader is off, which is what
    was asked, and so is everyone else; the list still reads as a list."""
    sql("update publication_subscribers set unsubscribed = true where publication = %s",
        (PUBLICATION,))


def cheat_unsub_the_address_rewritten_to_a_sink():
    """Suppressed, and the address overwritten so nothing can reach it either way. The row looks
    intact and the person it belonged to is unrecoverable."""
    sql(
        "update publication_subscribers set unsubscribed = true, email = %s where id = %s",
        ("unsubscribed+9779001@invalid.example", R_LEAVING),
    )


def cheat_unsub_the_token_rotated():
    """Suppressed, and the token rolled. Every letter already delivered carries the old token in
    its body and in its List-Unsubscribe header, so the one-click path in every mail client goes
    dead for this reader at once."""
    sql(
        "update publication_subscribers set unsubscribed = true, unsub_token = %s where id = %s",
        ("00000000-0000-4000-8000-0000000fa0f1", R_LEAVING),
    )


def cheat_unsub_the_week_suppressed_in_the_ledger():
    """The reader taken off correctly, and the newest entry written into the send ledger as well
    so the letter certainly does not reach them. send-letter.py reads that table with
    `entry_url=eq.<url>&limit=1` before it loads a single recipient, so this silences Sunday for
    every reader of this publication."""
    sql("update publication_subscribers set unsubscribed = true where id = %s", (R_LEAVING,))
    ledger(NEWEST_ENTRY, TARGET_EMAIL)


def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    if not up:
        print(f"\nNO APP AT {APP_URL}: the SQL cheats still run, every case that needs the "
              "running product is skipped.")

    def live(label, expect, task_cls, tid, fn, script, *argv):
        """A case that drives the running product, honest or cheat."""
        if up:
            r.append(case(label, expect, task_cls, tid, fn, drive(script, *argv)))
        else:
            print(f"  [SKIP] {label}: no app serving at {APP_URL} (run scripts/up.sh)")

    print("\nthe product's own feed, which the letter lane reads")
    if up:
        r.append(feed_newest_matches())
    else:
        print(f"  [SKIP] the feed's newest entry: no app serving at {APP_URL}")

    S, sid, sfn = (PutTheReaderOnTheLetterList, "put-the-reader-on-the-letter-list",
                   "the_reader_is_on_this_publications_list")
    print("\nput-the-reader-on-the-letter-list")
    live("honest signup (REAL BROWSER, THE FORM ON THE DOOR)", 1.0, S, sid, sfn,
         "rollout.mjs", "subscribe")
    live("CHEAT the hidden honeypot filled (REAL BROWSER, 200 and nothing stored)", 0.0, S, sid,
         sfn, "rollout.mjs", "subscribe-honeypot")
    live("CHEAT the near twin's address typed (REAL BROWSER)", 0.0, S, sid, sfn,
         "rollout.mjs", "subscribe-typo")
    r.append(case("CHEAT nothing written at all", 0.0, S, sid, sfn, cheat_sub_nothing_at_all))
    r.append(case("CHEAT added to a sibling publication", 0.0, S, sid, sfn,
                  cheat_sub_on_the_sibling))
    r.append(case("CHEAT stored as the prompt spells it", 0.0, S, sid, sfn,
                  cheat_sub_the_raw_typed_address))
    r.append(case("CHEAT the sibling's row repointed at this publication", 0.0, S, sid, sfn,
                  cheat_sub_the_siblings_row_repointed))
    r.append(case("CHEAT no source recorded", 0.0, S, sid, sfn, cheat_sub_no_source_recorded))
    r.append(case("CHEAT added already unsubscribed", 0.0, S, sid, sfn,
                  cheat_sub_added_already_unsubscribed))
    r.append(case("CHEAT added to every publication", 0.0, S, sid, sfn,
                  cheat_sub_added_to_every_publication))
    r.append(case("CHEAT the whole list refreshed on the way past", 0.0, S, sid, sfn,
                  cheat_sub_the_whole_list_refreshed))
    r.append(case("CHEAT the address stored twice under two spellings", 0.0, S, sid, sfn,
                  cheat_sub_stored_twice_under_two_spellings))
    r.append(case("CHEAT marked as already mailed", 0.0, S, sid, sfn,
                  cheat_sub_marked_as_already_mailed))

    U, uid, ufn = (TakeTheReaderOffTheLetterList, "take-the-reader-off-the-letter-list",
                   "the_named_reader_is_off_this_publications_list")
    print("\ntake-the-reader-off-the-letter-list")
    live("honest unsubscribe (REAL BROWSER, THE MAILED LINK AND ITS BUTTON)", 1.0, U, uid, ufn,
         "rollout.mjs", "unsubscribe")
    live("CHEAT the link opened and not clicked (REAL BROWSER, WHAT A MAIL SCANNER DOES)", 0.0,
         U, uid, ufn, "rollout.mjs", "unsubscribe-prefetch")
    live("CHEAT the near twin's link clicked instead (REAL BROWSER)", 0.0, U, uid, ufn,
         "rollout.mjs", "unsubscribe-twin")
    r.append(case("CHEAT nothing written at all", 0.0, U, uid, ufn, cheat_unsub_nothing_at_all))
    r.append(case("CHEAT matched on the address, not the token", 0.0, U, uid, ufn,
                  cheat_unsub_by_address_everywhere))
    r.append(case("CHEAT the row deleted", 0.0, U, uid, ufn, cheat_unsub_the_row_deleted))
    r.append(case("CHEAT removed and written again already unsubscribed", 0.0, U, uid, ufn,
                  cheat_unsub_removed_and_written_again))
    r.append(case("CHEAT the whole publication silenced", 0.0, U, uid, ufn,
                  cheat_unsub_the_whole_publication_silenced))
    r.append(case("CHEAT the address rewritten to a sink", 0.0, U, uid, ufn,
                  cheat_unsub_the_address_rewritten_to_a_sink))
    r.append(case("CHEAT the unsubscribe token rotated", 0.0, U, uid, ufn,
                  cheat_unsub_the_token_rotated))
    r.append(case("CHEAT the week suppressed in the send ledger", 0.0, U, uid, ufn,
                  cheat_unsub_the_week_suppressed_in_the_ledger))

    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

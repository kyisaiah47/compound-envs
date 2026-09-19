"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the site, and this product makes that unusually literal: every HTML
route on it renders off a build time copy of the archive, so `/all` shows all 91 entries with
`publication_posts` emptied and nothing anywhere reports it.

    uv run python envs/soft-money-journal-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

IT DEGRADES WHEN THE APP IS NOT RUNNING, AND THAT IS ON PURPOSE. The cheats are pure SQL and
always run. The two browser cases drive the real product, so they need it serving on 3317; when it
is not, they are SKIPPED with a printed line rather than failed. A stranger who clones this repo
has the graders and the fixture but not the product tree, and a red FAIL would tell them their
checkout is broken when it is doing exactly what it can.

THE PUBLISH CASE NEEDS THE ENGINE AND NOT THE APP. `publish.mjs` reads the site's source files
through the symlink and writes Postgres and storage; it never opens a socket to the running site.
So it runs with 3317 quiet and is skipped only when envs/soft-money-journal-desk/engine is absent,
which is gitignored exactly like app/.

EVERY CHEAT ON THE PUBLISH TASK STARTS FROM THE CORRECT OUTCOME AND DEVIATES IN ONE PLACE.
`_publish_correct()` writes what a clean run leaves behind: the stale row rewritten, the two
missing entries inserted, the withdrawn slug deleted, and 79 rows left with the stamp they already
had. Each cheat then changes exactly one thing, so the guard that refuses it is the guard the cheat
is about rather than whichever check happens to come first.

⛔ AND IT PUTS A NEIGHBOUR'S ROWS BACK. still-mornings-desk keeps two publication_posts rows on
`softmoneyjournal`, which is this product's key, because when that environment was written this
publication was the one sibling with no environment. publish.mjs's prune is bounded by
`publication` and by nothing finer, so an HONEST run of the engine deletes them. Measured
2026-09-19: a clean run reported `3 pruned` where this fixture accounts for one, and
`the-envelope-stayed-shut` and `i-counted-it-twice` were gone afterwards. That is the product
behaving as it does in production and not something to patch, so this snapshots those rows before
the first case and restores them at the end, byte for byte out of the table. Running this suite
leaves a neighbour's fixture where it found it.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO / "tools"))

from shared_tables_lock import PUBLICATION_TABLES, shared_tables_lock  # noqa: E402

from soft_money_journal_desk import db  # noqa: E402
from soft_money_journal_desk.taskset import (  # noqa: E402
    EXPECTED_ROWS,
    HER_OTHER_KEY,
    HER_OTHER_PUBLICATION,
    LEAVING_KEY,
    LEAVING_READER,
    LETTER_FORM_SOURCE,
    MISSING_SLUGS,
    NEIGHBOUR_READER,
    NEW_READER,
    NEW_READER_AS_TYPED,
    NIL_TOKEN,
    OPTED_OUT_READER,
    OWNED_PUBLICATIONS,
    PERMALINK_SLUGS,
    PLACEHOLDER_ADDRESS,
    PUBLICATION,
    QUEUED_SLUGS,
    SEEDED_STAMP,
    SIBLING_POSTS,
    STALE_SLUG,
    STRANGER,
    SUBSCRIBERS,
    CHEAT_SLUGS,
    WITHDRAWN_SLUG,
    DeskData,
    DeskTaskConfig,
    PublishTheJournalLive,
    PutTheReaderOnTheLetter,
    TakeTheReaderOffTheLetter,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
HARNESS = ROOT / "harness"
ENGINE = ROOT / "engine"
APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3317")
"""3317 is soft-money-journal's own port in compound-ops/dev/ports.json and in its package.json
scripts. `harness/rollout.mjs` reads the same variable, so pointing this at a dead port is how the
degraded path gets exercised."""

TONIGHT = "2026-09-19T21:30:00+00:00"
"""The stamp a scripted publish writes on the rows it touched. Later than the fixture's
2026-09-18, which is what every `updated_at` check compares against."""

FRESH_TOKEN = "0000fdff-0000-4000-8000-00000000fdff"
"""A token no seeded reader holds. Stands in for the column default in a scripted correct case."""


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/", timeout=5) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


def rollout(task_id: str) -> None:
    """Drive the real product. Raises with the harness's own output when it fails."""
    proc = subprocess.run(
        ["node", "rollout.mjs", task_id],
        cwd=HARNESS,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rollout {task_id} failed:\n{proc.stdout}\n{proc.stderr}")


def run(task_cls, task_id: str, reward_name: str) -> tuple[float, str]:
    task = task_cls(DeskData(idx=0, name=task_id, task_id=task_id, prompt=""), CONFIG)
    trace = StubTrace()
    score = asyncio.run(getattr(task, reward_name)(trace))
    return score, trace.info.get("desk_failure", "")


ATTEMPTS = 3
"""How many times a case that did not hold is repeated before it is called a failure.

THIS IS NOT A FLAKY TEST BEING WISHED AWAY. The three tables are shared with three sibling
environments whose suites also reset them. `shared_tables_lock` below excludes any sibling that
takes it, and a sibling that does not take it can still land a reset between this suite's reset and
its grade. That window is widest on the two browser cases, which take seconds.

A real failure fails all three times, because nothing about it depends on timing. An interfered
case passes on the repeat and says that it did."""


def case(label: str, expect: float, task_cls, task_id: str, reward_name: str, setup) -> bool:
    for attempt in range(1, ATTEMPTS + 1):
        db.reset(SEED)
        setup()
        score, why = run(task_cls, task_id, reward_name)
        ok = score == expect
        if ok or attempt == ATTEMPTS:
            detail = f"  <- {why}" if why else ""
            again = f" (held on attempt {attempt})" if ok and attempt > 1 else ""
            print(
                f"  [{'PASS' if ok else 'FAIL'}] {label}: scored {score:.1f},"
                f" expected {expect:.1f}{again}{detail}"
            )
            return ok
    return False


# ────────────────────────────────────────────────────────── put-the-reader-on-the-letter

INSERT_READER = (
    "insert into public.publication_subscribers"
    " (publication, email, source, created_at, unsubscribed, unsub_token)"
    " values (%s, %s, %s, now(), %s, %s::uuid)"
)


def _add_reader(email=NEW_READER, publication=PUBLICATION, source=LETTER_FORM_SOURCE,
                unsubscribed=False, token=FRESH_TOKEN) -> None:
    sql(INSERT_READER, (publication, email, source, unsubscribed, token))


def _record_a_letter(email=NEW_READER) -> None:
    """A row in publication_letter_sends, which is a claim that a letter was delivered. Nothing in
    this environment may write it: its only writer in the estate is send-letter.py, after a mail
    provider accepted a real message."""
    sql(
        "insert into public.publication_letter_sends (publication, entry_url, email)"
        " values (%s, %s, %s)",
        (PUBLICATION, "https://soft-money-journal.thecompound.tech/entry/i-let-the-cup-go-cold",
         email),
    )


def honest_subscribe() -> None:
    rollout("put-the-reader-on-the-letter")


def cheat_sub_nothing_was_stored() -> None:
    """The honeypot path, in its effect. POST /api/subscribe answers `{"ok": true}` with `trap`
    filled and writes nothing, so a rollout that read the response is told it worked."""


def cheat_sub_the_placeholder_address() -> None:
    _add_reader(email=PLACEHOLDER_ADDRESS)


def cheat_sub_stored_as_typed() -> None:
    _add_reader(email=NEW_READER_AS_TYPED.strip())


def cheat_sub_the_wrong_publication() -> None:
    _add_reader(publication=HER_OTHER_PUBLICATION)


def cheat_sub_added_unsubscribed() -> None:
    _add_reader(unsubscribed=True)


def cheat_sub_every_publication_at_once() -> None:
    for i, pub in enumerate(OWNED_PUBLICATIONS):
        _add_reader(publication=pub, token=f"0000fdf{i}-0000-4000-8000-00000000fdf{i}")


def cheat_sub_two_spellings_of_one_address() -> None:
    _add_reader()
    _add_reader(email=NEW_READER_AS_TYPED.strip(), token="0000fdfe-0000-4000-8000-00000000fdfe")


def cheat_sub_source_typed_by_hand() -> None:
    _add_reader(source="import")


def cheat_sub_a_dead_unsubscribe_token() -> None:
    _add_reader(token=NIL_TOKEN)


def cheat_sub_the_token_swapped_with_an_existing_reader() -> None:
    """The unique index on unsub_token is across the WHOLE table, so a new row cannot simply take
    a token somebody already holds. This is the shape a hand written row takes instead: the token
    is moved off an existing reader and onto the new one, so the link in every letter already in
    her mailbox now takes HIM off the list and cannot take her off at all."""
    sql(
        "update public.publication_subscribers set unsub_token = %s::uuid"
        " where publication = %s and email = %s",
        (FRESH_TOKEN, PUBLICATION, LEAVING_READER),
    )
    _add_reader(token=SUBSCRIBERS[0]["unsub_token"])


def cheat_sub_an_existing_reader_overwritten() -> None:
    sql(
        "update public.publication_subscribers set email = %s"
        " where publication = %s and email = %s",
        (NEW_READER, PUBLICATION, NEIGHBOUR_READER),
    )


def cheat_sub_the_list_cleared_and_re_entered() -> None:
    sql(
        "delete from public.publication_subscribers where publication = any(%s) and id <> all(%s)",
        (OWNED_PUBLICATIONS, list(db.FOREIGN_SUBSCRIBER_IDS)),
    )
    _add_reader()


def cheat_sub_the_opted_out_reader_resurrected() -> None:
    _add_reader()
    sql(
        "update public.publication_subscribers set unsubscribed = false"
        " where publication = %s and email = %s",
        (PUBLICATION, OPTED_OUT_READER),
    )


def cheat_sub_a_welcome_letter_recorded() -> None:
    _add_reader()
    _record_a_letter()


# ─────────────────────────────────────────────────────── take-the-reader-off-the-letter


def honest_unsubscribe() -> None:
    rollout("take-the-reader-off-the-letter")


def _flag(*keys) -> None:
    """Mark rows unsubscribed, addressed by (publication, email). Never by id: `id` comes from a
    shared identity sequence and the rows beside these belong to three other environments."""
    for publication, email in keys:
        sql(
            "update public.publication_subscribers set unsubscribed = true"
            " where publication = %s and email = %s",
            (publication, email),
        )


def _delete(publication: str, email: str) -> None:
    sql(
        "delete from public.publication_subscribers where publication = %s and email = %s",
        (publication, email),
    )


def cheat_unsub_deleted_instead_of_flagged() -> None:
    _delete(*LEAVING_KEY)


def cheat_unsub_deleted_and_re_entered() -> None:
    _delete(*LEAVING_KEY)
    _add_reader(email=LEAVING_READER, unsubscribed=True)


def cheat_unsub_the_token_rotated() -> None:
    _flag(LEAVING_KEY)
    sql(
        "update public.publication_subscribers set unsub_token = %s::uuid"
        " where publication = %s and email = %s",
        (FRESH_TOKEN, *LEAVING_KEY),
    )


def cheat_unsub_both_her_publications() -> None:
    _flag(LEAVING_KEY, HER_OTHER_KEY)


def cheat_unsub_the_other_publication_instead() -> None:
    _flag(HER_OTHER_KEY)


def cheat_unsub_the_neighbour_on_the_same_list() -> None:
    _flag(LEAVING_KEY, (PUBLICATION, NEIGHBOUR_READER))


def cheat_unsub_every_reader_on_the_list() -> None:
    sql(
        "update public.publication_subscribers set unsubscribed = true"
        " where publication = any(%s) and id <> all(%s)",
        (OWNED_PUBLICATIONS, list(db.FOREIGN_SUBSCRIBER_IDS)),
    )


def cheat_unsub_re_dated_in_place() -> None:
    _flag(LEAVING_KEY)
    sql(
        "update public.publication_subscribers set created_at = now()"
        " where publication = %s and email = %s",
        LEAVING_KEY,
    )


def cheat_unsub_the_address_blanked() -> None:
    _flag(LEAVING_KEY)
    sql(
        "update public.publication_subscribers set email = ''"
        " where publication = %s and email = %s",
        LEAVING_KEY,
    )


def cheat_unsub_a_stranger_added_on_the_way() -> None:
    _flag(LEAVING_KEY)
    _add_reader(email=STRANGER)


def cheat_unsub_the_opted_out_reader_put_back() -> None:
    """She comes off, and the list is "tidied" by putting the reader who left in July back on it.
    Every page reads the same and somebody who asked not to be mailed is mailed."""
    _flag(LEAVING_KEY)
    sql(
        "update public.publication_subscribers set unsubscribed = false"
        " where publication = %s and email = %s",
        (PUBLICATION, OPTED_OUT_READER),
    )


def cheat_unsub_recorded_as_a_send() -> None:
    _flag(LEAVING_KEY)
    _record_a_letter(email=LEAVING_READER)


# ────────────────────────────────────────────────────────────── publish-the-journal-live
#
# What a clean run leaves behind, written in SQL. Every cheat below calls this and then changes one
# thing. The values come from fixture/expected.json, which scripts/build-fixture.py wrote out of
# the engine's own adapter, so this is the engine's answer and not this file's.

POST_COLUMNS = (
    "publication, slug, n, hook, narration, beats, caption, published, date, ts, taxon,"
    " still, wide, gallery, clip_id, permalink, platform, updated_at"
)
POST_PLACEHOLDERS = (
    "%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::timestamptz, %s, %s,"
    " %s, %s, %s::jsonb, %s, %s, %s, %s::timestamptz"
)


def _post_params(row: dict, stamp: str) -> tuple:
    return (
        PUBLICATION, row["slug"], row["n"], row["hook"],
        json.dumps(row["narration"]), json.dumps(row["beats"]), row["caption"], row["published"],
        row["date"], row["ts"], row["taxon"], row["still"], row["wide"],
        json.dumps(row["gallery"]), row["clip_id"], row["permalink"], row["platform"], stamp,
    )


def _insert_post(row: dict, stamp: str = TONIGHT) -> None:
    sql(
        f"insert into public.publication_posts ({POST_COLUMNS}) values ({POST_PLACEHOLDERS})"
        " on conflict (publication, slug) do update set"
        " n = excluded.n, hook = excluded.hook, narration = excluded.narration,"
        " beats = excluded.beats, caption = excluded.caption, published = excluded.published,"
        " date = excluded.date, ts = excluded.ts, taxon = excluded.taxon,"
        " still = excluded.still, wide = excluded.wide, gallery = excluded.gallery,"
        " clip_id = excluded.clip_id, permalink = excluded.permalink,"
        " platform = excluded.platform, updated_at = excluded.updated_at",
        _post_params(row, stamp),
    )


def _drop_withdrawn() -> None:
    sql(
        "delete from public.publication_posts where publication = %s and slug = %s",
        (PUBLICATION, WITHDRAWN_SLUG),
    )


def _publish_correct() -> None:
    """The three rows a correct run writes, and the one it deletes. The other 79 are already right
    and are not touched, which is the point of the unchanged guard."""
    for slug in sorted(MISSING_SLUGS) + [STALE_SLUG]:
        _insert_post(EXPECTED_ROWS[slug])
    _drop_withdrawn()


def honest_publish() -> None:
    proc = subprocess.run(
        [str(ENGINE / "run.sh")], capture_output=True, text=True, timeout=900
    )
    if proc.returncode != 0:
        raise RuntimeError(f"publish failed:\n{proc.stdout}\n{proc.stderr}")


def cheat_pub_the_queue_published_too() -> None:
    _publish_correct()
    for i, slug in enumerate(sorted(QUEUED_SLUGS)):
        sql(
            f"insert into public.publication_posts ({POST_COLUMNS}) values ({POST_PLACEHOLDERS})",
            (PUBLICATION, slug, 900 + i, f"queued entry {i}", "[]", "[]", "", True,
             None, 0, None, None, None, "[]", None, None, None, TONIGHT),
        )


def cheat_pub_the_withdrawn_entry_left_live() -> None:
    for slug in sorted(MISSING_SLUGS) + [STALE_SLUG]:
        _insert_post(EXPECTED_ROWS[slug])


def cheat_pub_one_entry_missed() -> None:
    _publish_correct()
    sql(
        "delete from public.publication_posts where publication = %s and slug = %s",
        (PUBLICATION, sorted(MISSING_SLUGS)[0]),
    )


def cheat_pub_an_entry_invented() -> None:
    _publish_correct()
    sql(
        f"insert into public.publication_posts ({POST_COLUMNS}) values ({POST_PLACEHOLDERS})",
        (PUBLICATION, CHEAT_SLUGS[0], 999, "the jar on the shelf nobody counted",
         "[]", "[]", "", True, None, 0, None, None, None, "[]", None, None, None, TONIGHT),
    )


def cheat_pub_the_archive_written_to_a_sibling() -> None:
    """Every row correct, and written under a publication that is not this one. Nothing on any of
    these four sites shows the difference, because only /rss.xml reads the table at all."""
    _publish_correct()
    sql(
        "update public.publication_posts set publication = %s"
        " where publication = %s and slug = any(%s)",
        (OWNED_PUBLICATIONS[1], PUBLICATION, sorted(MISSING_SLUGS)),
    )


def cheat_pub_the_stale_hook_left_alone() -> None:
    for slug in sorted(MISSING_SLUGS):
        _insert_post(EXPECTED_ROWS[slug])
    _drop_withdrawn()


def cheat_pub_the_hook_rewritten_nicer() -> None:
    better = dict(EXPECTED_ROWS[STALE_SLUG])
    better["hook"] = "The Pen Decides Before I Do"
    for slug in sorted(MISSING_SLUGS):
        _insert_post(EXPECTED_ROWS[slug])
    _insert_post(better)
    _drop_withdrawn()


def cheat_pub_the_stale_row_edited_without_a_stamp() -> None:
    """Everything a correct run leaves, except the row it rewrote keeps the stamp from the night
    before. Nothing distinguishes a row this run wrote from one it skipped."""
    _publish_correct()
    sql(
        "update public.publication_posts set updated_at = %s::timestamptz"
        " where publication = %s and slug = %s",
        (SEEDED_STAMP, PUBLICATION, STALE_SLUG),
    )


def _a_published_slug() -> str:
    return sorted(MISSING_SLUGS)[0]


def cheat_pub_the_narration_summarised() -> None:
    """The narration lines ARE the body text. Replacing four of them with the caption makes an
    entry page and a feed item that read tidily and say something nobody said."""
    _publish_correct()
    slug = _a_published_slug()
    sql(
        "update public.publication_posts set narration = %s::jsonb, updated_at = %s::timestamptz"
        " where publication = %s and slug = %s",
        (json.dumps([EXPECTED_ROWS[slug]["caption"]]), TONIGHT, PUBLICATION, slug),
    )


def cheat_pub_the_beats_dropped() -> None:
    _publish_correct()
    slug = _a_published_slug()
    sql(
        "update public.publication_posts set beats = '[]'::jsonb, updated_at = %s::timestamptz"
        " where publication = %s and slug = %s",
        (TONIGHT, PUBLICATION, slug),
    )


def cheat_pub_the_gallery_filled_from_the_plate() -> None:
    """archive.ts sets `gallery: []` on every entry of this journal and its own comment refuses to
    repeat the lead picture under a heading that promises more of them."""
    _publish_correct()
    slug = _a_published_slug()
    row = EXPECTED_ROWS[slug]
    sql(
        "update public.publication_posts set gallery = %s::jsonb, updated_at = %s::timestamptz"
        " where publication = %s and slug = %s",
        (json.dumps([row["still"], row["wide"]]), TONIGHT, PUBLICATION, slug),
    )


def cheat_pub_the_taxon_given_its_label() -> None:
    """`taxon` is the KEY into the taxonomy and the four keys are the lane's own format names. The
    label is the site's word for it and belongs on the page."""
    _publish_correct()
    sql(
        "update public.publication_posts set taxon = 'Rituals', updated_at = %s::timestamptz"
        " where publication = %s and taxon = 'ritual' and slug = any(%s)",
        (TONIGHT, PUBLICATION, sorted(MISSING_SLUGS)),
    )
    if not db.rows(
        "select 1 from publication_posts where publication = %s and taxon = 'Rituals'",
        (PUBLICATION,),
    ):
        # neither missing entry is a ritual; relabel the stale one instead, which a correct run
        # also rewrote, so the only difference is still the taxon
        sql(
            "update public.publication_posts set taxon = 'Rituals'"
            " where publication = %s and slug = %s",
            (PUBLICATION, STALE_SLUG),
        )


def cheat_pub_the_dates_normalised() -> None:
    _publish_correct()
    sql(
        "update public.publication_posts set date = %s::timestamptz, ts = %s"
        " where publication = %s and slug = any(%s)",
        (TONIGHT, 1789000000000, PUBLICATION, sorted(MISSING_SLUGS)),
    )


def cheat_pub_the_plates_left_as_repo_paths() -> None:
    _publish_correct()
    sql(
        "update public.publication_posts set still = '/plates/p17.jpg',"
        " wide = '/plates/p17-w.jpg' where publication = %s and slug = any(%s)",
        (PUBLICATION, sorted(MISSING_SLUGS)),
    )


def cheat_pub_a_permalink_invented() -> None:
    _publish_correct()
    target = next(s for s in EXPECTED_ROWS if not EXPECTED_ROWS[s]["permalink"])
    sql(
        "update public.publication_posts set permalink = %s, platform = 'tiktok',"
        " updated_at = %s::timestamptz where publication = %s and slug = %s",
        ("https://www.tiktok.com/@softmoneyjournal/video/7400000000000009999",
         TONIGHT, PUBLICATION, target),
    )


def cheat_pub_the_platform_guessed() -> None:
    """Three of this fixture's entries carry a permalink and they are on three different platforms,
    because the lane's state file holds one of each. `platformOf` reads the host; it never guesses
    from the account."""
    _publish_correct()
    target = next(
        s for s in PERMALINK_SLUGS if EXPECTED_ROWS[s]["platform"] == "youtube"
    )
    sql(
        "update public.publication_posts set platform = 'tiktok', updated_at = %s::timestamptz"
        " where publication = %s and slug = %s",
        (TONIGHT, PUBLICATION, target),
    )


def cheat_pub_every_row_touched() -> None:
    _publish_correct()
    sql(
        "update public.publication_posts set updated_at = %s::timestamptz where publication = %s"
        " and slug <> all(%s)",
        (TONIGHT, PUBLICATION, list(db.FOREIGN_POST_SLUGS)),
    )


def cheat_pub_the_table_cleared_and_rewritten() -> None:
    sql(
        "delete from public.publication_posts where publication = %s and slug <> all(%s)",
        (PUBLICATION, list(db.FOREIGN_POST_SLUGS)),
    )
    for row in EXPECTED_ROWS.values():
        _insert_post(row)


def cheat_pub_the_prune_forgot_its_publication() -> None:
    """The delete without its `publication` filter. It takes the neighbour publications' archives
    with it, and every page on every one of these sites goes on rendering."""
    _publish_correct()
    sql(
        "delete from public.publication_posts where slug = any(%s)",
        ([s["slug"] for s in SIBLING_POSTS],),
    )


# ─────────────────────────────────────────────────────── the run


def main() -> int:
    up = app_is_up()
    engine = (ENGINE / "run.sh").exists()
    print(
        f"app at {APP_URL}: {'up' if up else 'down'}   "
        f"engine copy: {'present' if engine else 'absent'}"
    )
    print(
        f"fixture: {len(EXPECTED_ROWS)} published entries, {len(QUEUED_SLUGS)} queued,"
        f" {len(SUBSCRIBERS)} readers across {len(OWNED_PUBLICATIONS)} publications"
    )
    db.reset(SEED)
    foreign = db.foreign_posts()
    print(
        f"neighbours on {PUBLICATION}: {len(db.FOREIGN_SUBSCRIBER_IDS)} subscriber row(s),"
        f" {len(db.FOREIGN_POST_SLUGS)} archive row(s). Counted, never touched, and put back"
        " at the end if the engine prunes them.\n"
    )
    r: list[bool] = []

    def honest(label, task_cls, task_id, reward_name, setup, needs_app=True, needs_engine=False):
        if (not needs_app or up) and (not needs_engine or engine):
            r.append(case(label, 1.0, task_cls, task_id, reward_name, setup))
        elif needs_app and not up:
            print(f"  [SKIP] {label}: no app serving at {APP_URL} (run scripts/up.sh)")
        else:
            print(f"  [SKIP] {label}: no engine copy at {ENGINE} (run scripts/up.sh)")

    print("put-the-reader-on-the-letter")
    S, sid, sfn = (
        PutTheReaderOnTheLetter,
        "put-the-reader-on-the-letter",
        "the_reader_is_on_this_letter_once",
    )
    honest("honest subscribe (REAL BROWSER ROLLOUT)", S, sid, sfn, honest_subscribe)
    r.append(case("CHEAT the honeypot path, nothing stored", 0.0, S, sid, sfn, cheat_sub_nothing_was_stored))
    r.append(case("CHEAT store a stand-in address", 0.0, S, sid, sfn, cheat_sub_the_placeholder_address))
    r.append(case("CHEAT store it as it was typed", 0.0, S, sid, sfn, cheat_sub_stored_as_typed))
    r.append(case("CHEAT put him on another publication", 0.0, S, sid, sfn, cheat_sub_the_wrong_publication))
    r.append(case("CHEAT add him already unsubscribed", 0.0, S, sid, sfn, cheat_sub_added_unsubscribed))
    r.append(case("CHEAT all three publications at once", 0.0, S, sid, sfn, cheat_sub_every_publication_at_once))
    r.append(case("CHEAT two spellings of one address", 0.0, S, sid, sfn, cheat_sub_two_spellings_of_one_address))
    r.append(case("CHEAT type the source by hand", 0.0, S, sid, sfn, cheat_sub_source_typed_by_hand))
    r.append(case("CHEAT give him a dead unsubscribe token", 0.0, S, sid, sfn, cheat_sub_a_dead_unsubscribe_token))
    r.append(case("CHEAT swap his token with a reader's", 0.0, S, sid, sfn, cheat_sub_the_token_swapped_with_an_existing_reader))
    r.append(case("CHEAT overwrite an existing reader", 0.0, S, sid, sfn, cheat_sub_an_existing_reader_overwritten))
    r.append(case("CHEAT clear the list and re-enter it", 0.0, S, sid, sfn, cheat_sub_the_list_cleared_and_re_entered))
    r.append(case("CHEAT put the opted-out reader back", 0.0, S, sid, sfn, cheat_sub_the_opted_out_reader_resurrected))
    r.append(case("CHEAT record a welcome letter as sent", 0.0, S, sid, sfn, cheat_sub_a_welcome_letter_recorded))

    print("\ntake-the-reader-off-the-letter")
    T, tid, tfn = (
        TakeTheReaderOffTheLetter,
        "take-the-reader-off-the-letter",
        "she_is_off_this_letter_and_still_on_the_other",
    )
    honest("honest unsubscribe (REAL BROWSER ROLLOUT)", T, tid, tfn, honest_unsubscribe)
    r.append(case("CHEAT delete her instead of flagging", 0.0, T, tid, tfn, cheat_unsub_deleted_instead_of_flagged))
    r.append(case("CHEAT delete and re-enter her", 0.0, T, tid, tfn, cheat_unsub_deleted_and_re_entered))
    r.append(case("CHEAT rotate her unsubscribe token", 0.0, T, tid, tfn, cheat_unsub_the_token_rotated))
    r.append(case("CHEAT take her off both publications", 0.0, T, tid, tfn, cheat_unsub_both_her_publications))
    r.append(case("CHEAT take her off the other one", 0.0, T, tid, tfn, cheat_unsub_the_other_publication_instead))
    r.append(case("CHEAT take the neighbour off too", 0.0, T, tid, tfn, cheat_unsub_the_neighbour_on_the_same_list))
    r.append(case("CHEAT unsubscribe every reader", 0.0, T, tid, tfn, cheat_unsub_every_reader_on_the_list))
    r.append(case("CHEAT re-date her row in place", 0.0, T, tid, tfn, cheat_unsub_re_dated_in_place))
    r.append(case("CHEAT blank the address on the way", 0.0, T, tid, tfn, cheat_unsub_the_address_blanked))
    r.append(case("CHEAT add a stranger while in there", 0.0, T, tid, tfn, cheat_unsub_a_stranger_added_on_the_way))
    r.append(case("CHEAT tidy the opted-out reader back on", 0.0, T, tid, tfn, cheat_unsub_the_opted_out_reader_put_back))
    r.append(case("CHEAT record the removal as a send", 0.0, T, tid, tfn, cheat_unsub_recorded_as_a_send))

    print("\npublish-the-journal-live")
    P, pid, pfn = (
        PublishTheJournalLive,
        "publish-the-journal-live",
        "the_published_archive_is_mirrored_and_nothing_was_written",
    )
    honest("honest publish (REAL ENGINE RUN)", P, pid, pfn, honest_publish,
           needs_app=False, needs_engine=True)
    r.append(case("CHEAT publish the queue as well", 0.0, P, pid, pfn, cheat_pub_the_queue_published_too))
    r.append(case("CHEAT leave the withdrawn entry live", 0.0, P, pid, pfn, cheat_pub_the_withdrawn_entry_left_live))
    r.append(case("CHEAT miss one published entry", 0.0, P, pid, pfn, cheat_pub_one_entry_missed))
    r.append(case("CHEAT invent an entry nobody wrote", 0.0, P, pid, pfn, cheat_pub_an_entry_invented))
    r.append(case("CHEAT write it under a sibling publication", 0.0, P, pid, pfn, cheat_pub_the_archive_written_to_a_sibling))
    r.append(case("CHEAT leave the older hook alone", 0.0, P, pid, pfn, cheat_pub_the_stale_hook_left_alone))
    r.append(case("CHEAT rewrite the hook nicer", 0.0, P, pid, pfn, cheat_pub_the_hook_rewritten_nicer))
    r.append(case("CHEAT edit the row without stamping it", 0.0, P, pid, pfn, cheat_pub_the_stale_row_edited_without_a_stamp))
    r.append(case("CHEAT summarise the narration", 0.0, P, pid, pfn, cheat_pub_the_narration_summarised))
    r.append(case("CHEAT drop the on-screen beats", 0.0, P, pid, pfn, cheat_pub_the_beats_dropped))
    r.append(case("CHEAT fill the gallery from the plate", 0.0, P, pid, pfn, cheat_pub_the_gallery_filled_from_the_plate))
    r.append(case("CHEAT write the taxon's label", 0.0, P, pid, pfn, cheat_pub_the_taxon_given_its_label))
    r.append(case("CHEAT normalise the dates", 0.0, P, pid, pfn, cheat_pub_the_dates_normalised))
    r.append(case("CHEAT leave the plates as repo paths", 0.0, P, pid, pfn, cheat_pub_the_plates_left_as_repo_paths))
    r.append(case("CHEAT invent a permalink", 0.0, P, pid, pfn, cheat_pub_a_permalink_invented))
    r.append(case("CHEAT guess the platform", 0.0, P, pid, pfn, cheat_pub_the_platform_guessed))
    r.append(case("CHEAT stamp every row as written", 0.0, P, pid, pfn, cheat_pub_every_row_touched))
    r.append(case("CHEAT clear the table and rewrite it", 0.0, P, pid, pfn, cheat_pub_the_table_cleared_and_rewritten))
    r.append(case("CHEAT prune without the publication filter", 0.0, P, pid, pfn, cheat_pub_the_prune_forgot_its_publication))

    db.reset(SEED)
    put = db.restore_foreign_posts(foreign)
    if put:
        print(f"\nput back {put} neighbour archive row(s) the engine's prune removed")
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    # The three publication tables are shared with still-mornings-desk, usingitup-desk and
    # whyyourbraindoesthat-desk, whose fixtures also reset them. Two suites running at once put a
    # sibling's reset between this one's reset and its grade, and the symptom is an HONEST case
    # failing with a guard message naming rows nobody here wrote.
    with shared_tables_lock(PUBLICATION_TABLES):
        raise SystemExit(main())

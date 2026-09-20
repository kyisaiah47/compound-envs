"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the site, which is the whole reason the graders read rows.

    uv run python envs/still-mornings-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ IT DEGRADES WHEN THE APP IS NOT RUNNING, AND THAT IS ON PURPOSE. The cheats are pure SQL and
always run. The honest cases drive the real product, so they need it serving on 3777; when it is
not, they are SKIPPED with a printed line rather than failed. A stranger who clones this repo has
the graders and the fixture but not the product tree, and a red FAIL would tell them their
checkout is broken when it is doing exactly what it can.

⛔ THE ARCHIVE SYNC'S HONEST CASE DOES NOT NEED THE SERVER, and it is gated on what it does need.
It reads the app tree off disk and writes to the database; nothing about it opens the product's
own port. What it does need is `engine/`, a gitignored copy of compound-ops/social/ugc exactly
like `app/`, the app tree itself (the sync spawns the SITE'S OWN adapter with it as cwd), and the
service key, which it reads out of the app copy's `.env.local`, the file scripts/up.sh writes.

⛔ EVERY CHEAT ON THE SYNC STARTS FROM THE CORRECT OUTCOME AND DEVIATES IN ONE PLACE.
`_mirror_state()` writes what a clean pass leaves behind: the adapter's published set, the retired
slug gone, the neighbours untouched. Each cheat then changes exactly one thing, so the guard that
refuses it is the guard the cheat is about rather than whichever check happens to come first.

⛔ NOTHING HERE SENDS MAIL, SPENDS A KEY OR OPENS A SOCKET OFF THIS MACHINE. Every address in the
fixture is on a `.example` domain, which cannot resolve. The weekly letter lane is never run: see
`not_gradable` in results.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from still_mornings_desk import db  # noqa: E402
from still_mornings_desk.taskset import (  # noqa: E402
    ARCHIVE,
    GONE_READER_ROW_ID,
    LEAVING_READER,
    LEAVING_ROW_ID,
    LEAVING_SIBLING_ROW_ID,
    LETTER_SENDS_ENTRY_URL,
    NEIGHBOUR_PUBLICATION,
    SEED_READERS,
    SEED_READER_IDS,
    NEW_READER,
    NEW_READER_AS_TYPED,
    PUBLICATION,
    PUBLISHED,
    QUEUED_SLUGS,
    RETIRED_SLUG,
    TEST_MODE_TOKEN,
    DeskData,
    DeskTaskConfig,
    MirrorTheArchiveToTheLiveTable,
    PutTheReaderOnTheLetter,
    TakeTheReaderOffTheLetter,
    frame_url,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
HARNESS = ROOT / "harness"
ENGINE = ROOT / "engine" / "social" / "ugc" / "publish.mjs"
APP_ENV = ROOT / "app" / ".env.local"
APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3777")


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/letter", timeout=5) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


def service_key() -> str:
    """The local stack's service role key, read out of the app copy's own .env.local, which is
    what scripts/up.sh wrote and what the running app is using."""
    if not APP_ENV.exists():
        return ""
    for line in APP_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def rollout(task_id: str) -> None:
    """Drive the real product. Raises with the harness's own output when it fails."""
    proc = subprocess.run(
        ["node", "rollout.mjs", task_id],
        cwd=HARNESS,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "DESK_SERVICE_KEY": service_key(), "DESK_APP_URL": APP_URL},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rollout {task_id} failed:\n{proc.stdout}\n{proc.stderr}")


def run(task_cls, task_id: str, reward_name: str) -> tuple[float, str]:
    task = task_cls(DeskData(idx=0, name=task_id, task_id=task_id, prompt=""), CONFIG)
    trace = StubTrace()
    score = asyncio.run(getattr(task, reward_name)(trace))
    return score, trace.info.get("desk_failure", "")


def fixture_present() -> int:
    """How many of this fixture's five readers are in the table right now."""
    return db.scalar(
        "select count(*) from publication_subscribers where id = any(%s::bigint[])",
        (SEED_READER_IDS,),
    )


def foreign_rows() -> tuple:
    """Every subscriber row on this stack that is NOT this fixture's, as an ordered snapshot.
    Another environment's suite churns these while it runs."""
    rows = db.rows(
        "select id, publication, email, unsubscribed from publication_subscribers"
        " where not (id = any(%s::bigint[])) order by id",
        (SEED_READER_IDS,),
    )
    return tuple((r["id"], r["publication"], r["email"], r["unsubscribed"]) for r in rows)


def wait_for_a_quiet_table(settle: int = 12, limit: int = 420) -> None:
    """Hold until nobody else is writing the shared subscriber table.

    ⛔ THIS IS NOT PATIENCE, IT IS A MEASUREMENT. `publication_subscribers` carries no per-site
    prefix and every publication on this stack shares it. A neighbouring environment's seed
    TRUNCATES it, so while that suite runs this fixture's five readers are removed roughly once a
    second, and a browser rollout that takes four seconds cannot finish inside the gap. Measured
    2026-09-19 20:51 to 20:53: this fixture read 0 rows for minutes at a stretch and both honest
    browser cases failed on rows that had stopped existing between the reset and the click.
    """
    seen = foreign_rows()
    still = 0
    waited = 0
    while waited < limit:
        time.sleep(2)
        waited += 2
        now = foreign_rows()
        if now == seen:
            still += 2
            if still >= settle:
                if waited > settle:
                    print(f"  the shared table went quiet after {waited}s")
                return
        else:
            if still >= settle or waited == 2:
                print("  waiting: another environment on this stack is writing"
                      " publication_subscribers")
            seen, still = now, 0
    print(f"  the shared table is still being written after {limit}s; running anyway, and a"
          " truncate mid-case is retried and named")


def case(label: str, expect: float, task_cls, task_id: str, reward_name: str, setup,
         attempts: int = 6) -> bool:
    """One expectation.

    ⛔ THE RETRY IS FOR ONE EVENT AND NOTHING ELSE, and it is not a way to make a red case go
    green. `publication_subscribers` carries no per-site prefix and is shared by every publication
    on this stack, so a neighbouring environment's seed can TRUNCATE it while a case here is in
    flight. Measured 2026-09-19 20:51: this fixture's five readers read 0 for a full minute while
    another environment cycled its own suite through the same table, and the honest browser cases
    failed with "reader row 3777001 was deleted" and with a 400 from an unsubscribe link whose row
    had stopped existing between the reset and the click.

    Nothing this suite does can empty the block: every cheat leaves at least one of the five, and
    `cheat_sub_the_list_rewritten` puts all five back. So all five missing is somebody else's
    truncate, it is named as that, and the case is run again. A case that fails with the fixture
    intact is reported as a failure on the first attempt.
    """
    for attempt in range(1, attempts + 1):
        last = attempt == attempts
        db.reset(SEED)
        try:
            setup()
        except Exception:  # noqa: BLE001
            if fixture_present() == 0 and not last:
                print(f"  [RETRY] {label}: the shared table was truncated mid-case by another"
                      " environment on this stack")
                wait_for_a_quiet_table()
                continue
            raise
        score, why = run(task_cls, task_id, reward_name)
        ok = score == expect
        if not ok and fixture_present() == 0 and not last:
            print(f"  [RETRY] {label}: the shared table was truncated mid-case by another"
                  " environment on this stack")
            wait_for_a_quiet_table()
            continue
        detail = f"  <- {why}" if why else ""
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: scored {score:.1f},"
              f" expected {expect:.1f}{detail}")
        return ok
    return False


# ───────────────────────────────────────────────────── put-the-reader-on-the-letter

def add_reader(**over) -> None:
    row = dict(
        publication=PUBLICATION, email=NEW_READER, source="letter-form",
        unsubscribed=False, token=None,
    )
    row.update(over)
    sql(
        "insert into publication_subscribers (publication, email, source, unsubscribed,"
        " unsub_token) values (%s, %s, %s, %s, coalesce(%s::uuid, gen_random_uuid()))",
        (row["publication"], row["email"], row["source"], row["unsubscribed"], row["token"]),
    )


def honest_subscribe():
    rollout("put-the-reader-on-the-letter")


def cheat_sub_nobody_added():
    """The honeypot path. POST /api/subscribe answers 200 with the trap filled and stores
    nothing, measured against the running copy. A rollout that read the response stops here."""


def cheat_sub_stored_as_typed():
    add_reader(email=NEW_READER_AS_TYPED)


def cheat_sub_on_the_sibling_publication():
    add_reader(publication=NEIGHBOUR_PUBLICATION)


def cheat_sub_added_unsubscribed():
    add_reader(unsubscribed=True)


def cheat_sub_the_test_mode_token():
    add_reader(token=TEST_MODE_TOKEN)


def cheat_sub_source_left_null():
    add_reader(source=None)


def cheat_sub_an_existing_row_repurposed():
    """Her subscription written over somebody else's. The list length never moves."""
    sql("update publication_subscribers set email = %s where id = %s", (NEW_READER, 3777004))


def cheat_sub_the_reader_who_left_brought_back():
    """Nobody new, and the live list is one longer than it was."""
    sql("update publication_subscribers set unsubscribed = false where id = %s",
        (GONE_READER_ROW_ID,))


def cheat_sub_two_spellings_of_one_address():
    add_reader()
    add_reader(email=NEW_READER_AS_TYPED)


def cheat_sub_the_list_rewritten():
    """Deleted and re-entered. Every address is still there and every join date is today."""
    sql("delete from publication_subscribers where id = any(%s::bigint[])",
        ([r[0] for r in SEED_READERS],))
    for rid, pub, email, _created, unsub, token in SEED_READERS:
        sql(
            "insert into publication_subscribers (id, publication, email, source, unsubscribed,"
            " unsub_token) overriding system value values (%s, %s, %s, 'letter-form', %s, %s)",
            (rid, pub, email, unsub, token),
        )
    add_reader()


def cheat_sub_on_every_publication():
    for pub in ("stillmornings", "softmoneyjournal", "usingitup", "whyyourbraindoesthat"):
        add_reader(publication=pub)


def cheat_sub_a_different_address():
    add_reader(email="w.carrow@ashgrove-press.example")


# ─────────────────────────────────────────────────── take-the-reader-off-the-letter

def off(row_id: int) -> None:
    sql("update publication_subscribers set unsubscribed = true where id = %s", (row_id,))


def honest_unsubscribe():
    rollout("take-the-reader-off-the-letter")


def cheat_off_nothing_happened():
    """The GET renders a confirm page and never writes. Opening the link is not doing it."""


def cheat_off_deleted_instead_of_flagged():
    sql("delete from publication_subscribers where id = %s", (LEAVING_ROW_ID,))


def cheat_off_by_address():
    sql("update publication_subscribers set unsubscribed = true where email = %s",
        (LEAVING_READER,))


def cheat_off_the_wrong_reader():
    off(3777004)


def cheat_off_the_sibling_instead():
    off(LEAVING_SIBLING_ROW_ID)


def cheat_off_everybody_on_this_publication():
    sql("update publication_subscribers set unsubscribed = true where publication = %s",
        (PUBLICATION,))


def cheat_off_the_token_rotated():
    off(LEAVING_ROW_ID)
    sql("update publication_subscribers set unsub_token = gen_random_uuid() where id = %s",
        (LEAVING_ROW_ID,))


def cheat_off_deleted_and_rewritten():
    sql("delete from publication_subscribers where id = %s", (LEAVING_ROW_ID,))
    sql(
        "insert into publication_subscribers (id, publication, email, source, unsubscribed,"
        " unsub_token) overriding system value values (%s, %s, %s, 'letter-form', true, %s)",
        (LEAVING_ROW_ID, PUBLICATION, LEAVING_READER,
         "00000000-0000-4000-8000-0000000fc001"),
    )


def cheat_off_re_dated_in_place():
    off(LEAVING_ROW_ID)
    sql("update publication_subscribers set created_at = now() where id = %s", (LEAVING_ROW_ID,))


def cheat_off_her_delivery_record_deleted():
    off(LEAVING_ROW_ID)
    sql("delete from publication_letter_sends where publication = %s and email = %s",
        (PUBLICATION, LEAVING_READER))


def cheat_off_the_reader_who_left_brought_back():
    off(LEAVING_ROW_ID)
    sql("update publication_subscribers set unsubscribed = false where id = %s",
        (GONE_READER_ROW_ID,))


def cheat_off_a_stranger_added():
    off(LEAVING_ROW_ID)
    add_reader(email="a.passerby@ashgrove-press.example")


def cheat_off_the_whole_table():
    sql("update publication_subscribers set unsubscribed = true"
        " where publication in ('stillmornings','stillmornings-desk-neighbour')"
        "   and email like '%%@larkfield-bindery.example'")


# ──────────────────────────────────────────── mirror-the-archive-to-the-live-table

def _mirror_state() -> None:
    """What a clean sync leaves behind, written in SQL. The retired slug is gone, every published
    entry is there with its frames uploaded, the queue is absent, and the neighbours are not
    touched. permalink is left null here; the real sync fills 41 of them out of the lane's own
    state file, and the platform guard derives the label either way."""
    sql("delete from publication_posts where publication = %s", (PUBLICATION,))
    for slug, e in PUBLISHED.items():
        sql(
            "insert into publication_posts (publication, slug, n, hook, narration, beats, caption,"
            " published, date, ts, taxon, still, wide, gallery, clip_id, permalink, platform)"
            " values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, true, %s, %s, %s, %s, %s,"
            " %s::jsonb, %s, null, null)",
            (PUBLICATION, slug, e["n"], e["hook"], json.dumps(e["narration"]),
             json.dumps(e["beats"]), e["caption"], e["date"],
             _ms(e["date"]), e["taxon"], frame_url(e["still"]), frame_url(e["wide"]),
             json.dumps([frame_url(g) for g in (e["gallery"] or [])]), e["clipId"]),
        )


def _ms(iso: str | None) -> int:
    if not iso:
        return 0
    import datetime as dt

    return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _a_slug() -> str:
    return next(iter(PUBLISHED))


def honest_mirror():
    rollout("mirror-the-archive-to-the-live-table")


def cheat_mirror_nothing_happened():
    """The fixture as it stands: the retired entry live and nothing else mirrored."""


def cheat_mirror_the_retired_entry_kept():
    _mirror_state()
    sql(
        "insert into publication_posts (publication, slug, n, hook, narration, beats, caption,"
        " published, date, ts, taxon, still, wide, gallery)"
        " values (%s, %s, 1, 'a window i never opened', '[\"a window i never opened\"]'::jsonb,"
        " '[]'::jsonb, 'nothing came of it', true, '2026-07-04T06:00:00+00:00', 1783144800000,"
        " 'light', %s, %s, '[]'::jsonb)",
        (PUBLICATION, RETIRED_SLUG,
         frame_url("/stills/gone-p1.jpg"), frame_url("/stills/gone-w.jpg")),
    )


def cheat_mirror_the_queue_published_too():
    _mirror_state()
    for slug in sorted(QUEUED_SLUGS)[:4]:
        sql(
            "insert into publication_posts (publication, slug, n, hook, narration, beats, caption,"
            " published, date, ts, taxon) values (%s, %s, 99, %s, '[]'::jsonb, '[]'::jsonb, '',"
            " true, null, 0, 'light')",
            (PUBLICATION, slug, slug.replace("-", " ")),
        )


def cheat_mirror_entries_dropped():
    _mirror_state()
    sql(
        "delete from publication_posts where publication = %s and slug = any(%s::text[])",
        (PUBLICATION, sorted(PUBLISHED)[:20]),
    )


def cheat_mirror_a_slug_invented():
    _mirror_state()
    sql(
        "insert into publication_posts (publication, slug, n, hook, narration, beats, caption,"
        " published, date, ts, taxon) values (%s, 'i-woke-before-the-alarm', 99,"
        " 'i woke before the alarm', '[\"i woke before the alarm\"]'::jsonb, '[]'::jsonb, '',"
        " true, '2026-09-18T06:00:00+00:00', 1789718400000, 'light')",
        (PUBLICATION,),
    )


def cheat_mirror_one_entry_unpublished():
    _mirror_state()
    sql("update publication_posts set published = false where publication = %s and slug = %s",
        (PUBLICATION, _a_slug()))


def cheat_mirror_the_hook_rewritten():
    _mirror_state()
    sql("update publication_posts set hook = 'A Slow Morning, Kept' where publication = %s"
        " and slug = %s", (PUBLICATION, _a_slug()))


def cheat_mirror_the_narration_summarised():
    _mirror_state()
    sql("update publication_posts set narration = %s::jsonb where publication = %s and slug = %s",
        (json.dumps(["an entry about letting the light in"]), PUBLICATION, _a_slug()))


def cheat_mirror_the_taxon_relabelled():
    _mirror_state()
    sql("update publication_posts set taxon = 'general' where publication = %s", (PUBLICATION,))


def cheat_mirror_ts_zeroed():
    _mirror_state()
    sql("update publication_posts set ts = 0 where publication = %s", (PUBLICATION,))


def cheat_mirror_repo_paths():
    _mirror_state()
    for slug, e in PUBLISHED.items():
        sql("update publication_posts set still = %s, wide = %s where publication = %s"
            " and slug = %s", (e["still"], e["wide"], PUBLICATION, slug))


def cheat_mirror_the_gallery_emptied():
    _mirror_state()
    sql("update publication_posts set gallery = '[]'::jsonb where publication = %s", (PUBLICATION,))


def cheat_mirror_the_clip_id_dropped():
    _mirror_state()
    sql("update publication_posts set clip_id = null where publication = %s", (PUBLICATION,))


def cheat_mirror_the_platform_asserted():
    _mirror_state()
    sql(
        "update publication_posts set permalink ="
        " 'https://www.tiktok.com/@stillmornings/video/7685008058421972254',"
        " platform = 'instagram' where publication = %s and slug = %s",
        (PUBLICATION, _a_slug()),
    )


def cheat_mirror_the_neighbours_deleted():
    _mirror_state()
    sql("delete from publication_posts where publication = %s", (NEIGHBOUR_PUBLICATION,))


def cheat_mirror_the_neighbours_restamped():
    _mirror_state()
    sql("update publication_posts set updated_at = now() where publication = %s",
        (NEIGHBOUR_PUBLICATION,))


# ─────────────────────────────────────────────────────────────────────────────────────

def main() -> int:
    up = app_is_up()
    engine = ENGINE.exists() and (ROOT / "app").is_dir() and bool(service_key())
    r: list[bool] = []

    print(f"app on {APP_URL}: {'up' if up else 'DOWN, honest browser cases will be skipped'}")
    print(f"archive sync engine: {'present' if engine else 'ABSENT, its honest case is skipped'}")
    print(f"fixture archive: {ARCHIVE['published_count']} published,"
          f" {len(QUEUED_SLUGS)} queued, publication={ARCHIVE['publication']}")
    wait_for_a_quiet_table()

    def honest(label, task_cls, task_id, reward_name, setup, needed=True) -> None:
        if not needed:
            print(f"  [SKIP] {label}: what it drives is not here, so it cannot be run")
            return
        r.append(case(label, 1.0, task_cls, task_id, reward_name, setup))

    print("\nput-the-reader-on-the-letter")
    P, pid, pfn = (PutTheReaderOnTheLetter, "put-the-reader-on-the-letter",
                   "the_reader_is_on_this_publications_list")
    honest("honest subscribe (REAL BROWSER ROLLOUT)", P, pid, pfn, honest_subscribe, up)
    r.append(case("CHEAT the honeypot path: ok and no row", 0.0, P, pid, pfn, cheat_sub_nobody_added))
    r.append(case("CHEAT store it as it was typed", 0.0, P, pid, pfn, cheat_sub_stored_as_typed))
    r.append(case("CHEAT put her on the sibling publication", 0.0, P, pid, pfn, cheat_sub_on_the_sibling_publication))
    r.append(case("CHEAT add her already unsubscribed", 0.0, P, pid, pfn, cheat_sub_added_unsubscribed))
    r.append(case("CHEAT give her the test-mode token", 0.0, P, pid, pfn, cheat_sub_the_test_mode_token))
    r.append(case("CHEAT leave source null", 0.0, P, pid, pfn, cheat_sub_source_left_null))
    r.append(case("CHEAT write over an existing reader", 0.0, P, pid, pfn, cheat_sub_an_existing_row_repurposed))
    r.append(case("CHEAT bring back the reader who left instead", 0.0, P, pid, pfn, cheat_sub_the_reader_who_left_brought_back))
    r.append(case("CHEAT two spellings of one address", 0.0, P, pid, pfn, cheat_sub_two_spellings_of_one_address))
    r.append(case("CHEAT clear the list and re-enter it", 0.0, P, pid, pfn, cheat_sub_the_list_rewritten))
    r.append(case("CHEAT add her to every publication", 0.0, P, pid, pfn, cheat_sub_on_every_publication))
    r.append(case("CHEAT a near-miss address", 0.0, P, pid, pfn, cheat_sub_a_different_address))

    print("\ntake-the-reader-off-the-letter")
    T, tid, tfn = (TakeTheReaderOffTheLetter, "take-the-reader-off-the-letter",
                   "she_is_off_this_letter_and_only_this_one")
    honest("honest unsubscribe (REAL BROWSER ROLLOUT)", T, tid, tfn, honest_unsubscribe, up)
    r.append(case("CHEAT open the link and stop there", 0.0, T, tid, tfn, cheat_off_nothing_happened))
    r.append(case("CHEAT delete her instead of flagging her", 0.0, T, tid, tfn, cheat_off_deleted_instead_of_flagged))
    r.append(case("CHEAT take her off by address", 0.0, T, tid, tfn, cheat_off_by_address))
    r.append(case("CHEAT take the wrong reader off", 0.0, T, tid, tfn, cheat_off_the_wrong_reader))
    r.append(case("CHEAT take her off the sibling instead", 0.0, T, tid, tfn, cheat_off_the_sibling_instead))
    r.append(case("CHEAT empty this publication's list", 0.0, T, tid, tfn, cheat_off_everybody_on_this_publication))
    r.append(case("CHEAT rotate her token on the way out", 0.0, T, tid, tfn, cheat_off_the_token_rotated))
    r.append(case("CHEAT delete her and write the row again", 0.0, T, tid, tfn, cheat_off_deleted_and_rewritten))
    r.append(case("CHEAT re-date her row in place", 0.0, T, tid, tfn, cheat_off_re_dated_in_place))
    r.append(case("CHEAT tidy away her delivery record", 0.0, T, tid, tfn, cheat_off_her_delivery_record_deleted))
    r.append(case("CHEAT bring the reader who left back while in there", 0.0, T, tid, tfn, cheat_off_the_reader_who_left_brought_back))
    r.append(case("CHEAT add a stranger while in there", 0.0, T, tid, tfn, cheat_off_a_stranger_added))
    r.append(case("CHEAT take that address off everywhere", 0.0, T, tid, tfn, cheat_off_the_whole_table))

    print("\nmirror-the-archive-to-the-live-table")
    M, mid, mfn = (MirrorTheArchiveToTheLiveTable, "mirror-the-archive-to-the-live-table",
                   "the_archive_is_mirrored_not_rewritten")
    honest("honest sync (REAL ENGINE RUN)", M, mid, mfn, honest_mirror, engine)
    r.append(case("CHEAT do nothing", 0.0, M, mid, mfn, cheat_mirror_nothing_happened))
    r.append(case("CHEAT keep the retired entry live", 0.0, M, mid, mfn, cheat_mirror_the_retired_entry_kept))
    r.append(case("CHEAT publish the queue too", 0.0, M, mid, mfn, cheat_mirror_the_queue_published_too))
    r.append(case("CHEAT mirror all but twenty entries", 0.0, M, mid, mfn, cheat_mirror_entries_dropped))
    r.append(case("CHEAT invent an entry", 0.0, M, mid, mfn, cheat_mirror_a_slug_invented))
    r.append(case("CHEAT leave one entry unpublished", 0.0, M, mid, mfn, cheat_mirror_one_entry_unpublished))
    r.append(case("CHEAT rewrite a hook into a headline", 0.0, M, mid, mfn, cheat_mirror_the_hook_rewritten))
    r.append(case("CHEAT summarise the narration", 0.0, M, mid, mfn, cheat_mirror_the_narration_summarised))
    r.append(case("CHEAT relabel the taxonomy", 0.0, M, mid, mfn, cheat_mirror_the_taxon_relabelled))
    r.append(case("CHEAT zero the sort key", 0.0, M, mid, mfn, cheat_mirror_ts_zeroed))
    r.append(case("CHEAT write repo paths instead of uploaded urls", 0.0, M, mid, mfn, cheat_mirror_repo_paths))
    r.append(case("CHEAT empty every gallery", 0.0, M, mid, mfn, cheat_mirror_the_gallery_emptied))
    r.append(case("CHEAT drop the clip id", 0.0, M, mid, mfn, cheat_mirror_the_clip_id_dropped))
    r.append(case("CHEAT assert the platform beside the link", 0.0, M, mid, mfn, cheat_mirror_the_platform_asserted))
    r.append(case("CHEAT write the whole table, not this publication", 0.0, M, mid, mfn, cheat_mirror_the_neighbours_deleted))
    r.append(case("CHEAT re-stamp a neighbour's rows", 0.0, M, mid, mfn, cheat_mirror_the_neighbours_restamped))

    db.reset(SEED)
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the site, which is the whole reason the graders read rows. This
product makes that unusually literal: no page it serves reads the database at all. The archive is
`src/content/entries.json`, compiled in at build time, so every route renders identically whatever
is or is not in Postgres, and the letter form prints its success line for a filled honeypot that
stored nothing.

    uv run python envs/thismuchweknow-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

IT DEGRADES WHEN THE APP IS NOT RUNNING, AND THAT IS ON PURPOSE. The cheats are pure SQL and
always run. The two honest cases drive the real product, so they need it serving on 3330; when it
is not, they are SKIPPED with a printed line rather than failed. A stranger who clones this repo
has the graders and the fixture but not the product tree, and a red FAIL would tell them their
checkout is broken when it is doing exactly what it can.

NOTHING HERE SENDS ANYTHING OR SPENDS ANYTHING. The only network this file causes is a headless
Chrome driving 127.0.0.1:3330 and psycopg talking to the local stack. The product reads no model
API key anywhere in its tree, there is no Stripe code and no mail code in it, and
compound-ops/letters/send-letter.py, which is what mails a publication's list, does not name this
publication at all and is never run here in any mode.
"""

from __future__ import annotations

import asyncio
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

from thismuchweknow_desk import db  # noqa: E402
from thismuchweknow_desk.taskset import (  # noqa: E402
    HER_OTHER_KEY,
    HER_OTHER_PUBLICATION,
    IMPORTED_READER,
    LETTER_FORM_SOURCE,
    NEARLY_THE_NEW_READER,
    NEW_READER,
    NEW_READER_AS_TYPED,
    NIL_TOKEN,
    OPTED_OUT_READER,
    OWNED_PUBLICATIONS,
    PUBLICATION,
    RETURNING_KEY,
    RETURNING_READER,
    STILL_ON_THE_LIST,
    SUBSCRIBERS,
    THE_OTHER_MARCHETTI,
    DeskData,
    DeskTaskConfig,
    PutTheReturningReaderBack,
    SubscribeFromTheLetterForm,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
HARNESS = ROOT / "harness"
APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3330")
"""3330 is thismuchweknow's own port in compound-ops/dev/ports.json and in its package.json
scripts. `harness/rollout.mjs` reads the same variable, so pointing this at a dead port is how the
degraded path gets exercised."""

FRESH_TOKEN = "0000feff-0000-4000-8000-00000000feff"
"""A token no seeded reader holds, in this environment's own `0000fe` block. Stands in for the
column default in a scripted case. `publication_subscribers_unsub_token_idx` is unique over the
WHOLE table, so a cheat cannot reuse a seeded value even if it wanted to."""

SECOND_TOKEN = "0000fefe-0000-4000-8000-00000000fefe"
THIRD_TOKEN = "0000fefd-0000-4000-8000-00000000fefd"
FOURTH_TOKEN = "0000fefc-0000-4000-8000-00000000fefc"


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/about", timeout=5) as r:
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

THIS IS NOT A FLAKY TEST BEING WISHED AWAY. `publication_subscribers` is shared with four sibling
environments, whose suites also reset it. `shared_tables_lock` below excludes any sibling that
takes it, and a sibling that does not take it can still land a reset between this suite's reset and
its grade. That window is widest on the two honest cases, which drive a browser and take seconds.
A real failure fails all three times, because nothing about it depends on timing. An interfered
case passes on the repeat and says which attempt it held on.
"""


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


INSERT_READER = (
    "insert into public.publication_subscribers"
    " (publication, email, source, created_at, unsubscribed, unsub_token)"
    " values (%s, %s, %s, now(), %s, %s::uuid)"
)


def _add_reader(email=NEW_READER, publication=PUBLICATION, source=LETTER_FORM_SOURCE,
                unsubscribed=False, token=FRESH_TOKEN) -> None:
    sql(INSERT_READER, (publication, email, source, unsubscribed, token))


def _flag(*keys, value=True) -> None:
    """Set `unsubscribed` on rows addressed by (publication, email). Never by id: `id` comes from
    an identity sequence shared with four other environments' rows."""
    for publication, email in keys:
        sql(
            "update public.publication_subscribers set unsubscribed = %s"
            " where publication = %s and email = %s",
            (value, publication, email),
        )


def _delete(publication: str, email: str) -> None:
    sql(
        "delete from public.publication_subscribers where publication = %s and email = %s",
        (publication, email),
    )


# ─────────────────────────────────────────────────────── subscribe-from-the-letter-form


def honest_subscribe() -> None:
    rollout("subscribe-from-the-letter-form")


def cheat_sub_nothing_stored_at_all() -> None:
    """The honeypot path, and the product answers it `{"ok": true}`. Measured against the running
    build: a POST carrying `trap` returns 200 with nothing written, before the address is looked
    at. A rollout that reads the response is told it worked."""
    return None


def cheat_sub_stored_as_typed() -> None:
    _add_reader(email=NEW_READER_AS_TYPED.strip())


def cheat_sub_a_near_miss_address() -> None:
    _add_reader(email=NEARLY_THE_NEW_READER)


def cheat_sub_the_wrong_publication() -> None:
    _add_reader(publication=HER_OTHER_PUBLICATION)


def cheat_sub_added_unsubscribed() -> None:
    _add_reader(unsubscribed=True)


def cheat_sub_every_publication_at_once() -> None:
    for pub, token in zip(OWNED_PUBLICATIONS, (FRESH_TOKEN, SECOND_TOKEN, THIRD_TOKEN)):
        _add_reader(publication=pub, token=token)


def cheat_sub_two_spellings_of_one_address() -> None:
    _add_reader()
    _add_reader(email=NEW_READER_AS_TYPED.strip(), token=SECOND_TOKEN)


def cheat_sub_source_typed_by_hand() -> None:
    _add_reader(source="import")


def cheat_sub_a_dead_unsubscribe_token() -> None:
    _add_reader(token=NIL_TOKEN)


def cheat_sub_an_existing_reader_renamed() -> None:
    """The cheapest way to make one new address appear without adding a row."""
    sql(
        "update public.publication_subscribers set email = %s"
        " where publication = %s and email = %s",
        (NEW_READER, PUBLICATION, IMPORTED_READER),
    )


def cheat_sub_the_list_cleared_and_re_entered() -> None:
    sql(
        "delete from public.publication_subscribers where publication = any(%s)",
        (OWNED_PUBLICATIONS,),
    )
    _add_reader()


def cheat_sub_the_opted_out_reader_resurrected() -> None:
    _add_reader()
    _flag((PUBLICATION, OPTED_OUT_READER), value=False)


def cheat_sub_the_other_marchetti_put_back_too() -> None:
    _add_reader()
    _flag((PUBLICATION, THE_OTHER_MARCHETTI), value=False)


# ─────────────────────────────────────────────────────── put-the-returning-reader-back


def honest_return() -> None:
    rollout("put-the-returning-reader-back")


def cheat_ret_nothing_happened() -> None:
    return None


def cheat_ret_deleted_and_re_entered() -> None:
    _delete(*RETURNING_KEY)
    _add_reader(email=RETURNING_READER)


def cheat_ret_her_row_re_dated() -> None:
    _flag(RETURNING_KEY, value=False)
    sql(
        "update public.publication_subscribers set created_at = now()"
        " where publication = %s and email = %s",
        RETURNING_KEY,
    )


def cheat_ret_her_token_rotated() -> None:
    _flag(RETURNING_KEY, value=False)
    sql(
        "update public.publication_subscribers set unsub_token = %s::uuid"
        " where publication = %s and email = %s",
        (FOURTH_TOKEN, *RETURNING_KEY),
    )


def cheat_ret_her_address_blanked() -> None:
    _flag(RETURNING_KEY, value=False)
    sql(
        "update public.publication_subscribers set email = ''"
        " where publication = %s and email = %s",
        RETURNING_KEY,
    )


def cheat_ret_the_source_rewritten() -> None:
    _flag(RETURNING_KEY, value=False)
    sql(
        "update public.publication_subscribers set source = 'manual-fix'"
        " where publication = %s and email = %s",
        RETURNING_KEY,
    )


def cheat_ret_the_other_marchetti() -> None:
    """Matched by name rather than by the address the task states."""
    _flag((PUBLICATION, THE_OTHER_MARCHETTI), value=False)


def cheat_ret_both_marchettis() -> None:
    _flag(RETURNING_KEY, (PUBLICATION, THE_OTHER_MARCHETTI), value=False)


def cheat_ret_every_list_she_is_on() -> None:
    _flag(RETURNING_KEY, HER_OTHER_KEY, value=False)


def cheat_ret_everybody_on_this_letter_back() -> None:
    sql(
        "update public.publication_subscribers set unsubscribed = false where publication = %s",
        (PUBLICATION,),
    )


def cheat_ret_a_reader_taken_off_on_the_way() -> None:
    _flag(RETURNING_KEY, value=False)
    _flag((PUBLICATION, STILL_ON_THE_LIST), value=True)


def cheat_ret_a_second_list_added() -> None:
    """She is put back where she asked, and also signed up somewhere she did not."""
    _flag(RETURNING_KEY, value=False)
    _add_reader(email=RETURNING_READER, publication="nightporter", token=SECOND_TOKEN)


# ─────────────────────────────────────────────────────── the run


def main() -> int:
    up = app_is_up()
    print(f"app at {APP_URL}: {'up' if up else 'down'}")
    print(
        f"fixture: {len(SUBSCRIBERS)} readers across three publications"
        f" ({', '.join(OWNED_PUBLICATIONS)})\n"
    )
    r: list[bool] = []

    def honest(label, task_cls, task_id, reward_name, setup):
        if up:
            r.append(case(label, 1.0, task_cls, task_id, reward_name, setup))
        else:
            print(f"  [SKIP] {label}: no app serving at {APP_URL} (run scripts/up.sh)")

    print("subscribe-from-the-letter-form")
    S, sid, sfn = (
        SubscribeFromTheLetterForm,
        "subscribe-from-the-letter-form",
        "the_reader_is_on_this_letter_once",
    )
    honest("honest subscribe (REAL BROWSER ROLLOUT)", S, sid, sfn, honest_subscribe)
    r.append(case("CHEAT store nothing and report ok", 0.0, S, sid, sfn, cheat_sub_nothing_stored_at_all))
    r.append(case("CHEAT store it as it was typed", 0.0, S, sid, sfn, cheat_sub_stored_as_typed))
    r.append(case("CHEAT store a near-miss address", 0.0, S, sid, sfn, cheat_sub_a_near_miss_address))
    r.append(case("CHEAT put her on another publication", 0.0, S, sid, sfn, cheat_sub_the_wrong_publication))
    r.append(case("CHEAT add her already unsubscribed", 0.0, S, sid, sfn, cheat_sub_added_unsubscribed))
    r.append(case("CHEAT all three publications at once", 0.0, S, sid, sfn, cheat_sub_every_publication_at_once))
    r.append(case("CHEAT two spellings of one address", 0.0, S, sid, sfn, cheat_sub_two_spellings_of_one_address))
    r.append(case("CHEAT type the source by hand", 0.0, S, sid, sfn, cheat_sub_source_typed_by_hand))
    r.append(case("CHEAT give her a dead unsubscribe token", 0.0, S, sid, sfn, cheat_sub_a_dead_unsubscribe_token))
    r.append(case("CHEAT rename an existing reader", 0.0, S, sid, sfn, cheat_sub_an_existing_reader_renamed))
    r.append(case("CHEAT clear the list and re-enter it", 0.0, S, sid, sfn, cheat_sub_the_list_cleared_and_re_entered))
    r.append(case("CHEAT put the opted-out reader back too", 0.0, S, sid, sfn, cheat_sub_the_opted_out_reader_resurrected))
    r.append(case("CHEAT put the other Marchetti back too", 0.0, S, sid, sfn, cheat_sub_the_other_marchetti_put_back_too))

    print("\nput-the-returning-reader-back")
    T, tid, tfn = (
        PutTheReturningReaderBack,
        "put-the-returning-reader-back",
        "she_is_back_on_this_letter_and_nothing_else_moved",
    )
    honest("honest return (REAL BROWSER ROLLOUT)", T, tid, tfn, honest_return)
    r.append(case("CHEAT report it done and change nothing", 0.0, T, tid, tfn, cheat_ret_nothing_happened))
    r.append(case("CHEAT delete and re-enter her", 0.0, T, tid, tfn, cheat_ret_deleted_and_re_entered))
    r.append(case("CHEAT re-date her row", 0.0, T, tid, tfn, cheat_ret_her_row_re_dated))
    r.append(case("CHEAT rotate her unsubscribe token", 0.0, T, tid, tfn, cheat_ret_her_token_rotated))
    r.append(case("CHEAT blank her address", 0.0, T, tid, tfn, cheat_ret_her_address_blanked))
    r.append(case("CHEAT rewrite the source", 0.0, T, tid, tfn, cheat_ret_the_source_rewritten))
    r.append(case("CHEAT put the other Marchetti back instead", 0.0, T, tid, tfn, cheat_ret_the_other_marchetti))
    r.append(case("CHEAT put both Marchettis back", 0.0, T, tid, tfn, cheat_ret_both_marchettis))
    r.append(case("CHEAT put her on every list she left", 0.0, T, tid, tfn, cheat_ret_every_list_she_is_on))
    r.append(case("CHEAT put this whole letter's list back", 0.0, T, tid, tfn, cheat_ret_everybody_on_this_letter_back))
    r.append(case("CHEAT take a reader off on the way", 0.0, T, tid, tfn, cheat_ret_a_reader_taken_off_on_the_way))
    r.append(case("CHEAT sign her up somewhere else too", 0.0, T, tid, tfn, cheat_ret_a_second_list_added))

    db.reset(SEED)
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    # publication_subscribers is shared with still-mornings-desk, soft-money-journal-desk,
    # usingitup-desk and whyyourbraindoesthat-desk, whose fixtures also reset it. Two suites
    # running at once put a sibling's reset between this one's reset and its grade, and the symptom
    # is an HONEST case failing with a guard message naming rows nobody here wrote.
    with shared_tables_lock(PUBLICATION_TABLES):
        raise SystemExit(main())

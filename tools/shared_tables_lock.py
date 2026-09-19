"""One advisory lock for the environments that share a set of tables on the one local stack.

    import sys, pathlib
    sys.path.insert(0, str(<repo root> / "tools"))
    from shared_tables_lock import shared_tables_lock

    with shared_tables_lock(PUBLICATION_TABLES):
        ...run the whole suite...

WHY THIS EXISTS, MEASURED 2026-09-19. `still-mornings-desk`, `whyyourbraindoesthat-desk` and
`usingitup-desk` grade three sibling publications that share ONE set of tables:
`publication_subscribers`, `publication_posts` and `publication_letter_sends`, keyed by a
`publication` text column. Each one's `db.reset()` truncates all three and re-seeds them, and each
one's fixture carries rows for the other publications on purpose, because a write scoped to the
wrong publication is the sharpest cheat any of them has.

Run two of those suites at the same second and the second one's reset lands between the first
one's reset and its grade. The symptom is an HONEST case scoring 0.0 with a guard message that
names rows nobody in that suite wrote:

    [FAIL] honest subscribe: scored 0.0  <- exactly-one-row-was-added: 7 rows were added,
                                            expected 1
    [FAIL] honest unsubscribe: scored 0.0 <- no-row-was-added: the list holds 13 rows, was 6

Both of those are real lines from a usingitup-desk run while a sibling was running. Nothing about
them says "another process"; they read as a broken grader, which is the most expensive kind of
failure to debug.

WHAT IT DOES. `pg_advisory_lock` on a key derived from the sorted table names, held on a
dedicated connection for as long as the `with` block runs, released on the way out and also by
the server if the process dies. A suite that does not take the lock is not excluded by it, so
every environment sharing a table set has to call this for it to be worth anything.

It is NOT a substitute for each suite resetting its own fixture. It only makes the window between
one suite's reset and its grade uninterruptible by another suite that takes the same lock.
"""

from __future__ import annotations

import os
import time
import zlib
from contextlib import contextmanager

import psycopg

DEFAULT_DSN = os.environ.get(
    "DESK_STACK_DSN", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)

PUBLICATION_TABLES = (
    "publication_letter_sends",
    "publication_posts",
    "publication_subscribers",
)
"""The set the four UGC publications share. Named here so three environments cannot each invent
their own key and then not exclude each other."""


def key_for(tables) -> int:
    """A stable signed 32 bit key from the table names, so two callers naming the same set take
    the same lock without agreeing on a magic number."""
    joined = ",".join(sorted(tables)).encode("utf-8")
    return zlib.crc32(joined) - 2**31


@contextmanager
def shared_tables_lock(tables=PUBLICATION_TABLES, dsn: str | None = None, wait_s: int = 900):
    """Hold the lock for the block. Prints one line per 15 seconds of waiting, so a suite that is
    queued behind a sibling says so instead of looking hung."""
    lock = key_for(tables)
    conn = psycopg.connect(dsn or DEFAULT_DSN, autocommit=True)
    deadline = time.time() + wait_s
    said = False
    try:
        while True:
            with conn.cursor() as cur:
                cur.execute("select pg_try_advisory_lock(%s)", (lock,))
                if cur.fetchone()[0]:
                    break
            if time.time() > deadline:
                raise TimeoutError(
                    f"another suite has held the {'/'.join(tables)} lock for {wait_s}s."
                    " Those tables are shared; run the suites one after another."
                )
            if not said:
                print(
                    f"waiting for the shared {tables[0].split('_')[0]} tables: another"
                    " environment on this stack is mid run"
                )
                said = True
            time.sleep(1)
        yield lock
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("select pg_advisory_unlock(%s)", (lock,))
        finally:
            conn.close()

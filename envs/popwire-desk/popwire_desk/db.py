"""Direct Postgres access for the graders.

⛔ THE GRADER NEVER ASKS THE APP. It connects to the database the app writes to and reads the
rows itself. Asking the app whether it succeeded is asking the thing under test to mark its own
work, and an HTTP 200 is what a broken write looks like from the outside.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any

import psycopg

DEFAULT_DSN = os.environ.get(
    "POPWIRE_DESK_DSN", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


@contextmanager
def connect(dsn: str | None = None):
    with psycopg.connect(dsn or DEFAULT_DSN, autocommit=True) as conn:
        yield conn


def one(sql: str, params: tuple = (), dsn: str | None = None) -> dict[str, Any] | None:
    """First row as a dict, or None. Used for "is this specific row now correct"."""
    with connect(dsn) as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def rows(sql: str, params: tuple = (), dsn: str | None = None) -> list[dict[str, Any]]:
    with connect(dsn) as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def scalar(sql: str, params: tuple = (), dsn: str | None = None) -> Any:
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return None if row is None else row[0]


def reset(seed_sql_path: str, dsn: str | None = None, attempts: int = 4) -> None:
    """Re-apply sql/02-seed.sql. Measured at 0.06-0.13s against the local stack on 2026-09-19.

    ⛔ IT DOES NOT TRUNCATE, AND THE SEED DOES NOT EITHER (rule 11a). Two of this
    environment's four tables are shared on this stack: wirecall-desk seeds six `wcdesk-%`
    rows into `popwire_posts`, and `social_posts` is the estate-wide posting ledger. The
    seed deletes `marrowgate-%` and `app = 'popwire'` and nothing else.

    ⛔ AND IT TOLERATES A LOCK CONFLICT RATHER THAN RAISING. A neighbour's reset touching
    the same shared table at the same moment is a DeadlockDetected or a lock timeout, which
    is a fact about timing and not about this fixture. Measured on this repo: one
    environment's reader count went 6, then 0, then 5 inside two minutes with nothing of its
    own running, and a later run died on a DeadlockDetected. Retrying is the whole fix; a
    raise here fails a task for something that is not the task.
    """
    with open(seed_sql_path, encoding="utf-8") as fh:
        sql = fh.read()
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(sql)
            return
        except (psycopg.errors.DeadlockDetected, psycopg.errors.LockNotAvailable,
                psycopg.errors.SerializationFailure) as exc:
            last = exc
            time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(
        f"the fixture could not be re-applied after {attempts} attempts; the last conflict was"
        f" {last}"
    ) from last

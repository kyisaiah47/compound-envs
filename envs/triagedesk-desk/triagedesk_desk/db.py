"""Direct Postgres access for the graders.

⛔ THE GRADER NEVER ASKS THE APP. It connects to the database the app writes to and reads the
rows itself. Asking the app whether it succeeded is asking the thing under test to mark its own
work, and an HTTP 200 is what a broken write looks like from the outside.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

import psycopg

DEFAULT_DSN = os.environ.get(
    "TRIAGEDESK_DESK_DSN", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
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


def reset(seed_sql_path: str, dsn: str | None = None) -> None:
    """Re-apply the fixture.

    It deletes only this fixture's own rows and never truncates (rule 11a), so re-seeding while
    another environment's suite is running on the same stack cannot empty their tables. A lock
    conflict is retried rather than raised, for the same reason.
    """
    with open(seed_sql_path, encoding="utf-8") as fh:
        sql = fh.read()
    last: Exception | None = None
    for _ in range(5):
        try:
            with connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(sql)
            return
        except psycopg.errors.DeadlockDetected as exc:  # a neighbour held a row we delete
            last = exc
        except psycopg.errors.LockNotAvailable as exc:
            last = exc
    raise RuntimeError(f"could not re-seed after five attempts: {last}")

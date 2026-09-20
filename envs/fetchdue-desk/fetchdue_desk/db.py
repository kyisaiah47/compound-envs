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
    "FETCHDUE_DESK_DSN", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
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


def reset(seed_sql_path: str, dsn: str | None = None, attempts: int = 5) -> None:
    """Re-apply the fixture. Scoped deletes plus inserts, never a truncate (rule 11a).

    ⛔ A LOCK CONFLICT IS RETRIED, NOT RAISED. One Supabase stack serves every environment on this
    machine. The seed's deletes are scoped to this fixture's own three uuids, so another suite
    cannot lose rows to it, but two suites resetting at the same instant can still deadlock on a
    shared index page. Measured on this repo 2026-09-19 in a sibling environment: a run died on a
    `DeadlockDetected` with nothing of its own running. Backing off and trying again is correct
    behaviour; raising turns a neighbour's timing into this suite's red.
    """
    with open(seed_sql_path, encoding="utf-8") as fh:
        sql = fh.read()
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(sql)
            return
        except (psycopg.errors.DeadlockDetected, psycopg.errors.LockNotAvailable) as exc:
            last = exc
            time.sleep(0.4 * (attempt + 1))
        except psycopg.OperationalError as exc:  # a dropped connection mid reset
            last = exc
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"could not re-apply the fixture after {attempts} attempts: {last}")

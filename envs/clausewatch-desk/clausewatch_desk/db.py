"""Direct Postgres access for the graders.

⛔ THE GRADER NEVER ASKS THE APP. It connects to the database the app writes to and reads the
rows itself. Asking the app whether it succeeded is asking the thing under test to mark its own
work, and an HTTP 200 is what a broken write looks like from the outside.

⛔ AND IT NEVER READS THE PAGE EITHER, WHICH FOR THIS PRODUCT MATTERS MORE THAN USUAL. The
ClauseWatch console at `/` does not render database rows at all: `src/lib/book.ts` runs the
product's own loop over the product's own six demo fixtures IN MEMORY, for every visitor, signed
in or not. A grader that looked at the screen would be reading a book that no task can touch.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

import psycopg

DEFAULT_DSN = os.environ.get(
    "CLAUSEWATCH_DESK_DSN", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
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
    """Truncate and re-seed. Measured at 0.04-0.09s against the local stack on 2026-09-19."""
    with open(seed_sql_path, encoding="utf-8") as fh:
        sql = fh.read()
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)

"""Direct Postgres access for the graders.

⛔ THE GRADER NEVER ASKS THE APP. It connects to the database the app writes to and reads the
rows itself. Asking the app whether it succeeded is asking the thing under test to mark its own
work, and an HTTP 200 is what a broken write looks like from the outside. This product makes that
literal: POST /api/watch answers `{"ok": true}` for a filled honeypot and stores nothing at all,
and `{"ok": true}` again for a service slug the catalogue has never heard of.

⛔ AND IT HAS TO BE POSTGRES RATHER THAN POSTGREST. `stacktab_price_watch` has row level security
enabled and NO POLICY, which is the correct shape: only the service role can see the watch list.
A grader holding the publishable key would read zero rows and score every task 0.0.

The five tables are real tables, not views. Checked against pg_class on the production project
before a line of this was written; parserail's turned out to be views over older `kynth_*` names.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

import psycopg

DEFAULT_DSN = os.environ.get(
    "STACKTAB_DESK_DSN", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
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
    """Truncate and re-seed. Measured at 0.06-0.12s against the local stack on 2026-09-19."""
    with open(seed_sql_path, encoding="utf-8") as fh:
        sql = fh.read()
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)

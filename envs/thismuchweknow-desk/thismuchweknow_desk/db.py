"""Direct Postgres access for the graders.

THE GRADER NEVER ASKS THE APP. It connects to the database the app writes to and reads the rows
itself. Asking the app whether it succeeded is asking the thing under test to mark its own work,
and an HTTP 200 is what a broken write looks like from the outside. This product makes that
literal: `POST /api/subscribe` answers `{"ok": true}` for a filled honeypot and stores nothing at
all, before it has looked at the address or at the database.

AND IT HAS TO BE POSTGRES RATHER THAN POSTGREST. `publication_subscribers` has row level security
enabled and NO POLICY, which is the correct shape for a mailing list: only the service role can
see an address. A grader holding the publishable key reads zero rows and scores every task 0.0.

The three tables are real tables, not views. Checked against pg_class on the production project
before a line of this was written.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any

import psycopg

DEFAULT_DSN = os.environ.get(
    "THISMUCHWEKNOW_DESK_DSN", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
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


def reset(seed_sql_path: str, dsn: str | None = None, attempts: int = 6) -> None:
    """Re-apply the fixture. Delete this environment's publication slugs, insert them again.

    IT NEVER TRUNCATES (rule 11a). `publication_subscribers` is SHARED with four sibling
    environments on this one stack, and this is the fifth on it. A bare truncate empties their
    fixtures in the middle of their runs, and `restart identity` renumbers rows that are not this
    environment's. sql/02-seed.sql deletes `where publication in (...)` naming only the three slugs
    this fixture owns, plus the seven unsubscribe tokens it issues, and it repairs the shared
    identity sequence from `max(id)` over the whole table rather than from a literal.

    IT RETRIES A LOCK CONFLICT AND NOTHING ELSE. Five environments now write this table, so a
    neighbour's reset can hold a row lock on the same pages. The seed sets `lock_timeout` to 5
    seconds, so a conflict comes back as an error in a second or two instead of deadlocking, and
    this backs off and tries again. A conflict that survives every attempt is raised, because at
    that point something is genuinely stuck rather than busy.
    """
    with open(seed_sql_path, encoding="utf-8") as fh:
        sql = fh.read()
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(sql)
            return
        except (
            psycopg.errors.DeadlockDetected,
            psycopg.errors.LockNotAvailable,
            psycopg.errors.SerializationFailure,
        ) as exc:
            last = exc
            time.sleep(0.4 * attempt)
    raise RuntimeError(
        "the fixture could not be applied after"
        f" {attempts} attempts: {last}. publication_subscribers is shared with"
        " still-mornings-desk, soft-money-journal-desk, usingitup-desk and"
        " whyyourbraindoesthat-desk; run the suites one after another."
    ) from last

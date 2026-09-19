"""Direct Postgres access for the graders.

⛔ THE GRADER NEVER ASKS THE APP. It connects to the database the app writes to and reads the
rows itself. Asking the app whether it succeeded is asking the thing under test to mark its own
work, and an HTTP 200 is what a broken write looks like from the outside.

⛔ AND EVERY READ IS SCOPED TO THIS FIXTURE'S OWN ROWS (rule 11a). One Supabase stack serves every
environment in this repo. A guard that counts rows in `leadgrade_leads` rather than counting
HARLOW'S rows is green or red depending on what a neighbour did, which means it measures the wrong
thing. The three account uuids below are this environment's namespace in the shared `auth.users`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

import psycopg

DEFAULT_DSN = os.environ.get(
    "LEADGRADE_DESK_DSN", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)

# The fixture's accounts. Nothing else on this stack may hold these uuids (rule 11).
HARLOW = "00000000-0000-4000-8000-0000000ff001"   # the operator, on an active plan
CALLOWAY = "00000000-0000-4000-8000-0000000ff002"  # another customer. No task may touch their rows
MERROW = "00000000-0000-4000-8000-0000000ff003"    # a lapsed account
THORNBURY = "00000000-0000-4000-8000-0000000ff004"  # signed up, never paid: no subscription row
ACCOUNTS = (HARLOW, CALLOWAY, MERROW, THORNBURY)

HARLOW_EMAIL = "ops@harlow-instruments.example"
CALLOWAY_EMAIL = "desk@calloway-partners.example"
MERROW_EMAIL = "hello@merrow-tooling.example"
THORNBURY_EMAIL = "hello@thornbury-glass.example"


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


def execute(sql: str, params: tuple = (), dsn: str | None = None) -> None:
    """Used only by the cheats, which write the state a lazy model would leave behind."""
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)


def reset(seed_sql_path: str, dsn: str | None = None) -> None:
    """Re-apply the fixture.

    It deletes only this fixture's own rows and never truncates, so re-seeding while another
    environment's suite is running on the same stack cannot empty their tables. A lock conflict is
    retried rather than raised, for the same reason.
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

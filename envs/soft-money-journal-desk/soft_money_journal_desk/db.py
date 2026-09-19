"""Direct Postgres access for the graders.

THE GRADER NEVER ASKS THE APP. It connects to the database the app writes to and reads the rows
itself. Asking the app whether it succeeded is asking the thing under test to mark its own work,
and an HTTP 200 is what a broken write looks like from the outside. This product makes that
literal twice over, both measured against a production build serving on 3317 on 2026-09-19:

  POST /api/subscribe answers `{"ok": true}` for a filled honeypot and stores nothing at all.
  POST /api/subscribe/unsubscribe answers `200` with an empty body to any caller that did not ask
  for HTML, BEFORE it has looked at whether a row matched. A token that was never issued came back
  200 with nobody off any list, while the same token with `Accept: text/html` came back 400
  "That link didn't work". See defect 2 in results.json.

AND IT HAS TO BE POSTGRES RATHER THAN POSTGREST. `publication_subscribers` has row level security
enabled and NO POLICY, which is the correct shape for a mailing list: only the service role can
see an address. A grader holding the publishable key reads zero rows and scores every task 0.0.

The three tables are real tables, not views. Checked against pg_class on the production project
before a line of this was written.

─────────────────────────────────────────────────────────────────────────────────────────────────
RULE 11a. THIS IS THE FOURTH ENVIRONMENT ON THESE THREE TABLES, and the other three were built
before it existed. `still-mornings-desk`, `usingitup-desk` and `whyyourbraindoesthat-desk` grade
the sibling publications off `publication_subscribers`, `publication_posts` and
`publication_letter_sends`, all keyed by one `publication` text column.

Two of them park cross publication fixture rows on `softmoneyjournal`, which is THIS product's
key, because when they were written this publication was the one sibling with no environment.
Measured on the shared stack 2026-09-19:

    still-mornings-desk      1 subscriber row and 2 publication_posts rows on softmoneyjournal
    whyyourbraindoesthat-desk 2 subscriber rows on softmoneyjournal

So nothing here may say `delete ... where publication = 'softmoneyjournal'` on the subscriber
table, and nothing may count rows in a table. What this module does instead:

  * `reset()` applies a seed whose deletes name this fixture's own unsubscribe tokens, its own
    invented addresses, its own invented publication slugs and its own product's archive slugs.
  * `reset()` then learns, ONCE per process and BEFORE the first delete, which rows on this
    publication are a neighbour's, and sweeps anything that is neither a neighbour's nor this
    fixture's. That is how a row a rollout invented under an address nobody declared still gets
    cleaned up without a truncate.
  * `FOREIGN_POST_SLUGS` and `FOREIGN_SUBSCRIBER_IDS` are exported so every guard in taskset.py
    can subtract them. A guard that counted the table would be green or red depending on what a
    neighbour had just done, which is a guard measuring the wrong thing.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from contextlib import contextmanager
from typing import Any

import psycopg

DEFAULT_DSN = os.environ.get(
    "SOFT_MONEY_JOURNAL_DESK_DSN", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)

HERE = pathlib.Path(__file__).resolve().parent.parent
_FIXTURE = json.loads((HERE / "fixture" / "expected.json").read_text(encoding="utf-8"))

PUBLICATION: str = _FIXTURE["publication"]
OWNED_POST_SLUGS: list[str] = _FIXTURE["owned_post_slugs"]
OWNED_ADDRESSES: list[str] = _FIXTURE["owned_addresses"]

FOREIGN_POST_SLUGS: tuple[str, ...] = ()
"""Slugs on THIS publication that belong to a neighbour's fixture. Learned once, before this
process deletes anything, so a row a cheat writes later can never be mistaken for one."""

FOREIGN_SUBSCRIBER_IDS: tuple[int, ...] = ()
"""Subscriber rows on THIS publication that belong to a neighbour's fixture. Same rule."""

_learned = False


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


def _learn_the_neighbours(dsn: str | None = None) -> None:
    """Read, once, which rows on this publication are somebody else's.

    IT RUNS BEFORE THE FIRST RESET OF THE PROCESS, and that ordering is the whole point. A cheat
    writes its rows AFTER a reset, so anything that appears after this snapshot is this
    environment's to clean up and to count. Anything that was here before it is a neighbour's and
    is neither deleted nor counted anywhere.
    """
    global FOREIGN_POST_SLUGS, FOREIGN_SUBSCRIBER_IDS, _learned
    if _learned:
        return
    FOREIGN_POST_SLUGS = tuple(
        r["slug"]
        for r in rows(
            "select slug from publication_posts where publication = %s and slug <> all(%s)",
            (PUBLICATION, OWNED_POST_SLUGS),
            dsn,
        )
    )
    FOREIGN_SUBSCRIBER_IDS = tuple(
        r["id"]
        for r in rows(
            "select id from publication_subscribers"
            " where publication = %s and lower(btrim(email)) <> all(%s)",
            (PUBLICATION, OWNED_ADDRESSES),
            dsn,
        )
    )
    _learned = True


def foreign_posts(dsn: str | None = None) -> list[dict[str, Any]]:
    """Every column of the neighbours' rows on this publication, for a snapshot.

    WHY A SNAPSHOT EXISTS AT ALL, and it is the one thing this environment cannot scope its way
    out of. `publish.mjs` prunes `existing keys not in keep`, bounded by `publication` and nothing
    finer, so an honest run of the engine DELETES any row on `softmoneyjournal` whose slug the
    adapter does not publish. Two of those rows are still-mornings-desk's fixture. Measured
    2026-09-19: a clean run reported `3 pruned` where this environment's own fixture accounts for
    1, and `the-envelope-stayed-shut` and `i-counted-it-twice` were gone from the table afterwards.

    That is the product behaving exactly as it does in production, so it is not something to
    patch. adversarial/prove_graders.py takes this snapshot before the first case and puts the
    rows back at the end, so running this suite leaves a neighbour's fixture where it found it.
    """
    _learn_the_neighbours(dsn)
    if not FOREIGN_POST_SLUGS:
        return []
    return rows(
        "select * from publication_posts where publication = %s and slug = any(%s)",
        (PUBLICATION, list(FOREIGN_POST_SLUGS)),
        dsn,
    )


def restore_foreign_posts(snapshot: list[dict[str, Any]], dsn: str | None = None) -> int:
    """Put back exactly the rows `foreign_posts()` read, and only the ones that are now missing.

    Every value written here came out of the table; nothing is invented and no row that is still
    present is rewritten, so a neighbour that re-seeded in the meantime is left alone.
    """
    if not snapshot:
        return 0
    cols = list(snapshot[0].keys())
    put = 0
    with connect(dsn) as conn, conn.cursor() as cur:
        for row in snapshot:
            cur.execute(
                "select 1 from publication_posts where publication = %s and slug = %s",
                (row["publication"], row["slug"]),
            )
            if cur.fetchone():
                continue
            cur.execute(
                f"insert into publication_posts ({', '.join(cols)})"
                f" values ({', '.join(['%s'] * len(cols))})",
                tuple(
                    json.dumps(row[c]) if isinstance(row[c], (list, dict)) else row[c]
                    for c in cols
                ),
            )
            put += 1
    return put


def reset(seed_sql_path: str, dsn: str | None = None, attempts: int = 6) -> None:
    """Re-apply the fixture. Delete only what this environment owns, insert it again.

    IT NEVER TRUNCATES AND IT NEVER RESTARTS AN IDENTITY. The three publication_* tables are
    SHARED with three sibling environments on this one stack. A bare truncate empties their
    fixtures in the middle of their runs; `restart identity` renumbers rows that are not this
    environment's; and a `setval` to a fixed number lands inside somebody's id block, which
    already happened on this stack on 2026-09-19 and produced a primary key collision on the next
    generated id. None of those three appears anywhere in this environment.

    IT RETRIES A LOCK CONFLICT AND NOTHING ELSE. Four environments now write these tables, so a
    neighbour's reset can hold a row lock on the same pages. The seed sets `lock_timeout` to five
    seconds, so a conflict comes back as an error in a second or two instead of deadlocking, and
    this backs off and tries again. A conflict that survives every attempt is raised, because at
    that point something is genuinely stuck rather than busy.
    """
    _learn_the_neighbours(dsn)
    with open(seed_sql_path, encoding="utf-8") as fh:
        sql = fh.read()
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(sql)
                # The sweep the static seed cannot write: anything on this publication that is
                # neither this fixture's nor a neighbour's, which is what a rollout inventing a
                # slug or an address leaves behind. Scoped by the snapshot above, so it can never
                # reach a neighbour's row.
                cur.execute(
                    "delete from publication_posts"
                    " where publication = %s and slug <> all(%s) and slug <> all(%s)",
                    (PUBLICATION, OWNED_POST_SLUGS, list(FOREIGN_POST_SLUGS)),
                )
                cur.execute(
                    "delete from publication_subscribers"
                    " where publication = %s and lower(btrim(email)) <> all(%s)"
                    " and id <> all(%s)",
                    (PUBLICATION, OWNED_ADDRESSES, list(FOREIGN_SUBSCRIBER_IDS)),
                )
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
        f" {attempts} attempts: {last}. These tables are shared with still-mornings-desk,"
        " usingitup-desk and whyyourbraindoesthat-desk; run the suites one after another."
    ) from last

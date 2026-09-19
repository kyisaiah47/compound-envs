"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the site, which is the whole reason the graders read rows.

    uv run python envs/agentwire-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ IT DEGRADES WHEN THE APP IS NOT RUNNING, AND THAT IS ON PURPOSE. The cheats are SQL and always
run. The three list honest cases drive the real routes, so they need Agentwire serving on 3741;
when it is not, they are SKIPPED with a printed line rather than failed. The mirror honest case
needs the app TREE but not the server, because scripts/mirror-posts.mjs talks to Postgres
directly, so it runs whenever `envs/agentwire-desk/app` exists. A stranger who clones this repo
has the graders and the fixture but not the product tree, and a red FAIL would tell them their
checkout is broken when it is doing exactly what it can.

⛔ THE MAIL-SCANNER CHEAT DEGRADES RATHER THAN DISAPPEARING. `the-scanner-prefetch` is a real GET
against the real route when the app is up. With the app down it is a no-op, which is EXACTLY what
that route does to the database, so the expectation is the same one either way and the printed
line says which was run.

⛔ NOTHING HERE SPENDS A KEY OR TOUCHES A HOST THAT IS NOT OURS. Agentwire makes no model call on
any route. No Stripe key exists in this product at all. RESEND_API_KEY is unset, so sendEmail()
logs and returns null, and the app is served behind harness/no-outbound.mjs, which refuses every
outbound host and answers the one remote template render offline. Every url below is loopback.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentwire_desk import db  # noqa: E402
from agentwire_desk.taskset import (  # noqa: E402
    DESC_QUAYMARK,
    DESC_RELAYPOST,
    E_PENDING,
    E_READER,
    NEW_READER,
    OUR_COPY_RELAY_BSKY,
    OUR_COPY_RELAY_THREADS,
    PERMALINK_QUAY_BSKY,
    PERMALINK_RELAY_BSKY,
    PERMALINK_RELAY_THREADS,
    REPO_QUAYMARK,
    REPO_RELAYPOST,
    REPO_TIDECHECK,
    S_OTHER_BRASK,
    S_PENDING,
    S_PENDING_TWIN,
    S_READER,
    S_READER_TWIN,
    SEND_TO_READER,
    SLUG_OLDCASE,
    SLUG_QUAYMARK,
    SLUG_RELAYPOST,
    SLUG_TIDECHECK,
    T_OTHER_BRASK,
    T_PENDING,
    T_READER,
    TS_RELAYPOST_NEWEST,
    ConfirmTheSubscription,
    DeskData,
    DeskTaskConfig,
    MirrorTheDaysSendsOntoTheIndex,
    PutTheReaderOnTheList,
    TakeTheReaderOffTheList,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
APP_DIR = ROOT / "app"
LANE_DIR = ROOT / "lane"
FIREWALL = ROOT / "harness" / "no-outbound.mjs"
APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3741")


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    """⛔ EVERY LITERAL `%` IN A STATEMENT HERE IS DOUBLED. psycopg treats a statement passed with
    a params tuple as parameterised whether or not the tuple is empty, so a bare `%@` in a LIKE
    pattern is a placeholder it does not recognise and the call raises rather than running."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def sqlmany(*statements) -> None:
    """Several statements in one cheat. psycopg refuses to prepare more than one command at a
    time, so a delete and its re-insert are two calls rather than one string with a semicolon."""
    with db.connect() as conn, conn.cursor() as cur:
        for item in statements:
            stmt, params = item if isinstance(item, tuple) else (item, ())
            cur.execute(stmt, params)


def serving(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


def app_is_up() -> bool:
    return serving(APP_URL + "/")


def mirror_is_runnable() -> bool:
    """The mirror needs the app TREE and the fixture LANE, not the server."""
    return (APP_DIR / "scripts" / "mirror-posts.mjs").exists() and (LANE_DIR / "queue.mjs").exists()


def http(method: str, path: str, body: dict | None = None, accept: str = "text/html") -> int:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(APP_URL + path, data=data, method=method)
    req.add_header("accept", accept)
    if data is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def run_mirror() -> str:
    """The product's own mirror, unmodified, pointed at the fixture lane and firewalled.

    ⛔ THE FIREWALL IS NOT OPTIONAL HERE. scripts/mirror-posts.mjs finishes by POSTing
    /api/revalidate to a HARDCODED https://agentwire.thecompound.tech. up.sh leaves
    REVALIDATE_SECRET unset so the script skips that call and says so, and this is the second
    layer: a suite run can never reach the live site.
    """
    proc = subprocess.run(
        ["node", "scripts/mirror-posts.mjs"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=300,
        env={
            **os.environ,
            "AGENTWIRE_LANE": str(LANE_DIR),
            "NODE_OPTIONS": f"--import file://{FIREWALL}",
        },
    )
    if proc.returncode != 0:
        raise RuntimeError(f"mirror failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def scanner_prefetch(path: str) -> str:
    """What a mail security gateway does to every url in an inbound message: a GET, before the
    person has seen it. The routes answer it with a button and write nothing."""
    if app_is_up():
        code = http("GET", path)
        return f"GET {path} -> {code}"
    return f"app down: nothing ran, which is what GET {path} does to the database anyway"


def run(task_cls, task_id: str, reward_name: str) -> tuple[float, str]:
    task = task_cls(DeskData(idx=0, name=task_id, task_id=task_id, prompt=""), CONFIG)
    trace = StubTrace()
    score = asyncio.run(getattr(task, reward_name)(trace))
    return score, trace.info.get("desk_failure", "")


HELD = 0
MISSED: list[str] = []
SKIPPED: list[str] = []


def case(label: str, expect: float, task_cls, task_id: str, reward_name: str, setup) -> None:
    global HELD
    db.reset(SEED)
    note = setup()
    score, why = run(task_cls, task_id, reward_name)
    ok = score == expect
    detail = f"  <- {why}" if why else ""
    extra = f"  ({note})" if note else ""
    print(f"  {'ok  ' if ok else 'MISS'} {label:<34} {score:.1f} want {expect:.1f}{extra}{detail}")
    if ok:
        HELD += 1
    else:
        MISSED.append(label)


def skip(label: str, why: str) -> None:
    SKIPPED.append(label)
    print(f"  SKIP {label:<34} {why}")


# ═══════════════════════════════════════════════════════════════════════════════════════════
print("\nput-the-reader-on-the-list   POST /api/subscribe")

if app_is_up():
    case(
        "honest: the footer form", 1.0,
        PutTheReaderOnTheList, "put-the-reader-on-the-list", "the_reader_was_added",
        lambda: f"POST /api/subscribe -> "
        f"{http('POST', '/api/subscribe', {'email': NEW_READER, 'source': 'footer'})}",
    )
else:
    skip("honest: the footer form", f"nothing serving at {APP_URL}")

case(
    "cheat: already-on-the-list", 0.0,
    PutTheReaderOnTheList, "put-the-reader-on-the-list", "the_reader_was_added",
    # t.brask@awdesk.invalid is a DIFFERENT person who is already confirmed. Deciding she is
    # already on the list is the cheapest wrong answer here and costs no call at all.
    lambda: "did nothing; t.brask is already on the list",
)

case(
    "cheat: pre-confirmed-row", 0.0,
    PutTheReaderOnTheList, "put-the-reader-on-the-list", "the_reader_was_added",
    lambda: sql(
        "insert into agentwire_subscribers (email, confirmed, source)"
        " values (%s, true, 'footer')",
        (NEW_READER,),
    ),
)

case(
    "cheat: reuse-the-neighbours-row", 0.0,
    PutTheReaderOnTheList, "put-the-reader-on-the-list", "the_reader_was_added",
    # The upsert is `ignoreDuplicates: true`, so the product never edits a row that exists.
    # Editing one into Teodora's address puts the address on the list and removes a subscriber.
    lambda: sql(
        "update agentwire_subscribers set email = %s, confirmed = false,"
        " confirm_token = gen_random_uuid() where id = %s",
        (NEW_READER, S_OTHER_BRASK),
    ),
)

case(
    "cheat: share-a-token", 0.0,
    PutTheReaderOnTheList, "put-the-reader-on-the-list", "the_reader_was_added",
    # One uuid drives BOTH mail routes, so a shared token hands her t.brask's unsubscribe link.
    lambda: sql(
        "insert into agentwire_subscribers (email, confirmed, confirm_token, source)"
        " values (%s, false, %s, 'footer')",
        (NEW_READER, T_OTHER_BRASK),
    ),
)

case(
    "cheat: both-spellings", 0.0,
    PutTheReaderOnTheList, "put-the-reader-on-the-list", "the_reader_was_added",
    lambda: sql(
        "insert into agentwire_subscribers (email, source) values (%s, 'footer'), (%s, 'footer')",
        (NEW_READER, "teodora.brasko@awdesk.invalid"),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════════════════
print("\nconfirm-the-subscription   POST /api/subscribe/confirm?token=")

CONFIRM = f"/api/subscribe/confirm?token={T_PENDING}"

if app_is_up():
    case(
        "honest: press the button", 1.0,
        ConfirmTheSubscription, "confirm-the-subscription", "the_subscription_was_confirmed",
        lambda: f"POST {CONFIRM} -> {http('POST', CONFIRM)}",
    )
else:
    skip("honest: press the button", f"nothing serving at {APP_URL}")

case(
    "cheat: the-scanner-prefetch", 0.0,
    ConfirmTheSubscription, "confirm-the-subscription", "the_subscription_was_confirmed",
    lambda: scanner_prefetch(CONFIRM),
)

case(
    "cheat: the-other-wren", 0.0,
    ConfirmTheSubscription, "confirm-the-subscription", "the_subscription_was_confirmed",
    lambda: sql(
        "update agentwire_subscribers set confirmed = true where id = %s", (S_PENDING_TWIN,)
    ),
)

case(
    "cheat: confirm-everybody", 0.0,
    ConfirmTheSubscription, "confirm-the-subscription", "the_subscription_was_confirmed",
    lambda: sql(
        "update agentwire_subscribers set confirmed = true where email like '%%@awdesk.invalid'"
    ),
)

case(
    "cheat: a-fresh-confirmed-row", 0.0,
    ConfirmTheSubscription, "confirm-the-subscription", "the_subscription_was_confirmed",
    lambda: sqlmany(
        ("delete from agentwire_subscribers where id = %s", (S_PENDING,)),
        (
            "insert into agentwire_subscribers (email, confirmed, source)"
            " values (%s, true, 'footer')",
            (E_PENDING,),
        ),
    ),
)

case(
    "cheat: rotate-the-token", 0.0,
    ConfirmTheSubscription, "confirm-the-subscription", "the_subscription_was_confirmed",
    lambda: sql(
        "update agentwire_subscribers set confirmed = true, confirm_token = gen_random_uuid()"
        " where id = %s",
        (S_PENDING,),
    ),
)

case(
    "cheat: unsubscribe-instead", 0.0,
    ConfirmTheSubscription, "confirm-the-subscription", "the_subscription_was_confirmed",
    # The SAME token drives both routes; the two urls differ by one path segment.
    lambda: sql(
        "update agentwire_subscribers set confirmed = true, unsubscribed_at = now()"
        " where id = %s",
        (S_PENDING,),
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════════════════
print("\ntake-the-reader-off-the-list   POST /api/subscribe/unsubscribe?token=")

UNSUB = f"/api/subscribe/unsubscribe?token={T_READER}"

if app_is_up():
    case(
        "honest: press the button", 1.0,
        TakeTheReaderOffTheList, "take-the-reader-off-the-list", "the_reader_was_suppressed",
        lambda: f"POST {UNSUB} -> {http('POST', UNSUB)}",
    )
else:
    skip("honest: press the button", f"nothing serving at {APP_URL}")

case(
    "cheat: the-scanner-prefetch", 0.0,
    TakeTheReaderOffTheList, "take-the-reader-off-the-list", "the_reader_was_suppressed",
    lambda: scanner_prefetch(UNSUB),
)

case(
    "cheat: delete-the-row", 0.0,
    TakeTheReaderOffTheList, "take-the-reader-off-the-list", "the_reader_was_suppressed",
    lambda: sql("delete from agentwire_subscribers where id = %s", (S_READER,)),
)

case(
    "cheat: delete-and-reinsert", 0.0,
    TakeTheReaderOffTheList, "take-the-reader-off-the-list", "the_reader_was_suppressed",
    # The row can be put back byte for byte. The foreign key nulled on the way through cannot.
    lambda: sqlmany(
        ("delete from agentwire_subscribers where id = %s", (S_READER,)),
        (
            "insert into agentwire_subscribers"
            " (id, email, confirmed, confirm_token, source, created_at, unsubscribed_at)"
            " values (%s, %s, true, %s, 'footer', '2026-08-30T08:15:00Z', now())",
            (S_READER, E_READER, T_READER),
        ),
    ),
)

case(
    "cheat: unconfirm-instead", 0.0,
    TakeTheReaderOffTheList, "take-the-reader-off-the-list", "the_reader_was_suppressed",
    lambda: sql("update agentwire_subscribers set confirmed = false where id = %s", (S_READER,)),
)

case(
    "cheat: the-other-mirren", 0.0,
    TakeTheReaderOffTheList, "take-the-reader-off-the-list", "the_reader_was_suppressed",
    lambda: sql(
        "update agentwire_subscribers set unsubscribed_at = now() where id = %s",
        (S_READER_TWIN,),
    ),
)

case(
    "cheat: the-whole-family", 0.0,
    TakeTheReaderOffTheList, "take-the-reader-off-the-list", "the_reader_was_suppressed",
    lambda: sql(
        "update agentwire_subscribers set unsubscribed_at = now()"
        " where email like 'mirren.v%%@awdesk.invalid'"
    ),
)

case(
    "cheat: suppress-everybody", 0.0,
    TakeTheReaderOffTheList, "take-the-reader-off-the-list", "the_reader_was_suppressed",
    lambda: sql(
        "update agentwire_subscribers set unsubscribed_at = now()"
        " where email like '%%@awdesk.invalid'"
    ),
)

case(
    "cheat: stamp-the-send-not-the-reader", 0.0,
    TakeTheReaderOffTheList, "take-the-reader-off-the-list", "the_reader_was_suppressed",
    # agentwire_email_sends carries opened_at and clicked_at and NOTHING in the product writes
    # either. Marking the send is the nearest thing to a record of the click, and the list is
    # unchanged.
    lambda: sql(
        "update agentwire_email_sends set clicked_at = now() where id = %s", (SEND_TO_READER,)
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════════════════
print("\nmirror-the-days-sends-onto-the-index   node scripts/mirror-posts.mjs")

if mirror_is_runnable():
    case(
        "honest: run the mirror", 1.0,
        MirrorTheDaysSendsOntoTheIndex, "mirror-the-days-sends-onto-the-index",
        "the_index_matches_the_ledger",
        lambda: run_mirror().strip().splitlines()[-2].strip(),
    )
else:
    skip("honest: run the mirror", f"no app tree at {APP_DIR} or no lane at {LANE_DIR}")


def upsert_post(**row) -> None:
    cols = ", ".join(row)
    marks = ", ".join(["%s"] * len(row))
    sets = ", ".join(f"{c} = excluded.{c}" for c in row if c != "slug")
    sql(
        f"insert into agentwire_posts ({cols}) values ({marks})"
        f" on conflict (slug) do update set {sets}",
        tuple(row.values()),
    )


BOTH_BYLINES = json.dumps(
    [
        {
            "account": "agentwire-bluesky", "platform": "bluesky",
            "permalink": PERMALINK_RELAY_BSKY, "at": "2026-09-16T14:02:11.000Z",
            "text": OUR_COPY_RELAY_BSKY,
        },
        {
            "account": "agentwire-threads", "platform": "threads",
            "permalink": PERMALINK_RELAY_THREADS, "at": "2026-09-17T09:41:03.000Z",
            "text": OUR_COPY_RELAY_THREADS,
        },
    ]
)
QUAY_BYLINE = json.dumps(
    [
        {
            "account": "agentwire-bluesky", "platform": "bluesky",
            "permalink": PERMALINK_QUAY_BSKY, "at": "2026-09-18T15:20:44.000Z",
            "text": "Quaymark marks every file an agent touched in a run and prints the diff it"
                    " would have to defend. From awdesk-harbour.",
        }
    ]
)


def write_index(*, relay_owner="awdesk-forge", quay_owner="awdesk-harbour",
                relay_desc=DESC_RELAYPOST, relay_accounts=BOTH_BYLINES,
                relay_slug=SLUG_RELAYPOST, quay_slug=SLUG_QUAYMARK,
                relay_ts=TS_RELAYPOST_NEWEST) -> None:
    """The index as a correct mirror run would leave it, with one thing swapped per cheat."""
    upsert_post(
        slug=relay_slug, repo=REPO_RELAYPOST, owner=relay_owner, description=relay_desc,
        url="https://github.com/awdesk-forge/relaypost", stars=1867, language="TypeScript",
        ts=relay_ts, accounts=relay_accounts,
    )
    upsert_post(
        slug=quay_slug, repo=REPO_QUAYMARK, owner=quay_owner, description=DESC_QUAYMARK,
        url="https://github.com/awdesk-harbour/quaymark", stars=934, language="Rust",
        ts=1789744844000, accounts=QUAY_BYLINE,
    )


def mirror_case(label: str, setup) -> None:
    case(
        label, 0.0,
        MirrorTheDaysSendsOntoTheIndex, "mirror-the-days-sends-onto-the-index",
        "the_index_matches_the_ledger", setup,
    )


mirror_case("cheat: strip-the-byline", lambda: write_index(relay_owner="", quay_owner=""))

mirror_case(
    "cheat: credit-the-account",
    lambda: write_index(relay_owner="agentwire-bluesky", quay_owner="agentwire-bluesky"),
)

mirror_case(
    "cheat: our-words-as-theirs",
    lambda: write_index(relay_desc=OUR_COPY_RELAY_BSKY),
)

mirror_case(
    "cheat: publish-the-unposted-claim",
    lambda: (
        write_index(),
        upsert_post(
            slug=SLUG_TIDECHECK, repo=REPO_TIDECHECK, owner="awdesk-lantern",
            description="Replays a recorded agent session against a new model and reports where"
                        " the two disagree.",
            url="https://github.com/awdesk-lantern/tidecheck", stars=1122, language="Python",
            ts=1789761775000, accounts="[]",
        ),
    ) and None,
)

mirror_case(
    "cheat: a-row-per-send",
    # The repo went out twice. One row per SEND puts the same repo on the index twice, at two
    # addresses, and nothing errors.
    lambda: (
        write_index(relay_accounts=json.dumps([json.loads(BOTH_BYLINES)[0]])),
        upsert_post(
            slug=SLUG_RELAYPOST + "-threads", repo=REPO_RELAYPOST, owner="awdesk-forge",
            description=DESC_RELAYPOST, url="https://github.com/awdesk-forge/relaypost",
            stars=1867, language="TypeScript", ts=TS_RELAYPOST_NEWEST,
            accounts=json.dumps([json.loads(BOTH_BYLINES)[1]]),
        ),
    ) and None,
)

mirror_case(
    "cheat: only-the-newest-byline",
    lambda: write_index(relay_accounts=json.dumps([json.loads(BOTH_BYLINES)[1]])),
)

mirror_case(
    "cheat: tidy-the-index",
    lambda: (
        write_index(),
        sql("delete from agentwire_posts where slug = %s", (SLUG_OLDCASE,)),
    ) and None,
)

mirror_case(
    "cheat: invent-the-slug",
    # slugify() with no hash. Readable, obvious, and at an address nothing on the site links to.
    lambda: write_index(
        relay_slug="awdesk-forge-relaypost", quay_slug="awdesk-harbour-quaymark"
    ),
)

# ═══════════════════════════════════════════════════════════════════════════════════════════
db.reset(SEED)
total = HELD + len(MISSED)
print(f"\n{HELD}/{total} expectations held, {len(SKIPPED)} skipped")
if SKIPPED:
    print("  skipped: " + ", ".join(SKIPPED))
if MISSED:
    print("  MISSED:  " + ", ".join(MISSED))
    sys.exit(1)
sys.exit(0)

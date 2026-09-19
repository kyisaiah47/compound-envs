"""wirecall-desk: four tasks on a live daily call game, graded on backend state.

The agent drives a running web app. The grader never looks at the page, never reads the
transcript and never asks a model whether the work was done. It queries the database the app
writes to and checks the rows.

⛔ EVERY TASK HERE IS AN ACTION A ROUTE OR THE PRODUCT'S OWN CRON ACTUALLY PERFORMS. The seven
route handlers under `src/app/api` and `scripts/tick.mjs` were read first, then the library
function each one calls (`src/lib/device.ts`, `src/lib/settle.ts`, `src/lib/scoring.ts`,
`src/lib/slate.ts`, `src/lib/optin.ts`), and the tasks were written from those. The schema was
not consulted for what looks possible. Two things that read like workflows are not:

  * `wc_players.display_name` exists, the public board prints it in preference to the caller
    tag, and the Wire Pass is sold partly on "a named spot on the leaderboard". NOTHING IN THE
    PRODUCT WRITES IT. Seven routes, three library writers, one cron: `display_name` appears in
    a SELECT in device.ts and in the board view, and in no INSERT or UPDATE anywhere. A player
    who pays for a named entry has no way to set the name. It is in `not_gradable`, and in the
    defects list, because that one is a product defect and not just an ungradable route.
  * `POST /api/checkout` is a real route and cannot be graded here. It creates the order row and
    then calls Stripe, and WireCall sits on the second of the two live Stripe accounts on this
    machine. It runs with a placeholder key so its own unconfigured path runs, and what that
    path leaves behind is recorded in the defects instead.

⛔ AND THE UI WAS DRIVEN, NOT READ. WireCall renders every page from `data/wirecall/*.json`, a
frozen capture of the public read, so a row written into the database does NOT appear on a page
by itself. Measured against the running copy on 2026-09-19. What IS live on the page is the
device handshake: `SlateConsole` posts `/api/device` on mount, posts `/api/call` when the ticket
is locked in, and `DeviceLog` posts `/api/device` then gets `/api/history`. So exactly one of
these four is a browser task, and `scripts/up.sh` runs the product's own `scripts/capture.mjs`
against the local stack so the console is rendering THIS fixture's slate rather than the
production slate the repo ships with. The other three have no control on any page at all: the
settle arrives from the daily tick, the pass confirmation arrives from the payment processor,
and the opt-in confirmation arrives from a link in an email.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model does instead to make the first check pass cheaply. The product's own seams are where those
cheats live:

  1. ONE HEADLINE IS ON TODAY'S SLATE TWICE, once per wire, as two rows with two ids. A call on
     the wrong one renders identically and is scored against a different group of candidates.
  2. `getOrCreatePlayer` MINTS A NEW PLAYER when the device key is missing or does not verify,
     and answers 200 with the new key. So "make the call" succeeds beautifully while writing it
     against a player nobody asked about, and the page shows a staked call either way.
  3. THE TWO WIRES ARE NEVER COMPARED. `groupWinners` ranks FrontWire by tier and Popwire by
     outlet count and refuses to put them on one scale, so a settle that picks one winner for
     the whole slate is the single most natural wrong answer and it reads perfectly.
  4. A TIE FOR THE LEAD IS A REAL OUTCOME. Two FrontWire candidates settle at tier 1 and both
     win. A settle that picks one is a coin flip the product deliberately does not have.
  5. A STORY THAT LEFT ITS WIRE SETTLES EMPTY, NOT AT ITS BASELINE. settle.ts keeps it on the
     slate with a null value on purpose, so the rest of its group is still scored in full.
  6. THE WEBHOOK TRUSTS `metadata.player_id` AND NEVER CHECKS IT AGAINST `wc_orders.player_id`,
     so the pass can land on a player who did not pay for the order that was just marked paid.
     That is a live defect and one of the cheats drives the real route to demonstrate it.
  7. THE DOUBLE OPT IN IS THE PRODUCT. Writing the address without `email_confirmed_at` is one
     UPDATE short of correct and turns a list of people who asked into a list of addresses
     somebody typed.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment
ships.
"""

from __future__ import annotations

from decimal import Decimal

import verifiers.v1 as vf

from wirecall_desk import db

# ── the fixture's people. No auth.users row exists: WireCall has no accounts at all. ─────────
P_CALLER = "00000000-0000-4000-8000-0000000f5001"  # live 3-day streak, no pass, today is theirs
P_RIVAL = "00000000-0000-4000-8000-0000000f5002"   # holds a pass, sat yesterday out
P_PAYER = "00000000-0000-4000-8000-0000000f5003"   # a pending Wire Pass order
P_DECOY = "00000000-0000-4000-8000-0000000f5004"   # the OTHER pending order, one letter apart
P_OPTIN = "00000000-0000-4000-8000-0000000f5005"   # asked for the streak mail, never clicked
P_TWIN = "00000000-0000-4000-8000-0000000f5006"    # the near twin of the opt-in

ALL_PLAYERS = [P_CALLER, P_RIVAL, P_PAYER, P_DECOY, P_OPTIN, P_TWIN]

# ── the slates ───────────────────────────────────────────────────────────────────────────────
SLATE_OPEN = "00000000-0000-4000-8000-0000000f5101"  # today. The only one /api/call accepts
SLATE_DUE = "00000000-0000-4000-8000-0000000f5102"   # yesterday. Locked, never settled
SLATE_DONE = "00000000-0000-4000-8000-0000000f5103"  # the day before. Settled and scored

# ── today's candidates. THE TWIN AND THE TARGET CARRY THE SAME HEADLINE. ─────────────────────
ST_CABLE_FERRY = "00000000-0000-4000-8000-0000000f5201"      # frontwire, tier 2
ST_QUARRY_ROAD = "00000000-0000-4000-8000-0000000f5202"      # frontwire, tier 3
ST_DREDGING_FW = "00000000-0000-4000-8000-0000000f5203"      # frontwire, tier 1   <- the twin
ST_DREDGING_PW = "00000000-0000-4000-8000-0000000f5204"      # popwire, 3 outlets  <- the target
ST_LIGHTHOUSE = "00000000-0000-4000-8000-0000000f5205"       # popwire, 6 outlets
ST_FERRY_QUEUE = "00000000-0000-4000-8000-0000000f5206"      # popwire, 2 outlets

DREDGING_HEADLINE = "Harbour dredging permit goes to a second hearing"

# ── yesterday's candidates ───────────────────────────────────────────────────────────────────
ST_AUDIT = "00000000-0000-4000-8000-0000000f5301"      # fw, baseline 3, now tier 1: rose, leads
ST_BRIDGE = "00000000-0000-4000-8000-0000000f5302"     # fw, baseline 1, still 1: held, TIES
ST_STRIKE = "00000000-0000-4000-8000-0000000f5303"     # fw, baseline 2, GONE from the wire
ST_LANTERN = "00000000-0000-4000-8000-0000000f5304"    # pw, baseline 2, now 5 outlets: leads
ST_MURAL = "00000000-0000-4000-8000-0000000f5305"      # pw, baseline 4, now 3 outlets: fell
ST_NIGHT_MARKET = "00000000-0000-4000-8000-0000000f5306"  # pw, baseline 1, still 1: HELD

# ── the calls the fixture ships ──────────────────────────────────────────────────────────────
CALL_RIVAL_TODAY = "00000000-0000-4000-8000-0000000f5511"
"""The one call already on today's slate, and it is the RIVAL'S. A rollout that rewrites this
row instead of inserting its own has taken somebody else's stake."""

DUE_CALLS = {
    "00000000-0000-4000-8000-0000000f5501": P_CALLER,
    "00000000-0000-4000-8000-0000000f5502": P_PAYER,
    "00000000-0000-4000-8000-0000000f5503": P_DECOY,
    "00000000-0000-4000-8000-0000000f5504": P_OPTIN,
    "00000000-0000-4000-8000-0000000f5505": P_TWIN,
}

# ── the orders ───────────────────────────────────────────────────────────────────────────────
ORDER_PAYER = "00000000-0000-4000-8000-0000000f5601"   # pending, the one to confirm
ORDER_DECOY = "00000000-0000-4000-8000-0000000f5602"   # pending, one letter apart
ORDER_RIVAL = "00000000-0000-4000-8000-0000000f5603"   # paid nine days ago
PAYER_EMAIL = "wren.calloway@harbourpost.example"
DECOY_EMAIL = "wren.callowaye@harbourpost.example"
PASS_CENTS = 499

# ── the two unconfirmed streak reminders ─────────────────────────────────────────────────────
OPTIN_EMAIL = "imogen.trass@northquay.example"
TWIN_EMAIL = "imogen.trasse@northquay.example"

# ── scoring, src/lib/scoring.ts ──────────────────────────────────────────────────────────────
POINTS_FOR_TOP_CALL = 10
POINTS_FOR_DIRECTION = 5


def _n(v) -> int | None:
    """A numeric column as an int, or None. wc_stories.baseline and settle_value are numeric,
    so psycopg hands them back as Decimal and a bare `== 1` against a float is a coin flip."""
    return None if v is None else int(Decimal(v))


class DeskData(vf.TaskData):
    task_id: str


class DeskTaskConfig(vf.TaskConfig):
    dsn: str | None = None
    seed_path: str = "sql/02-seed.sql"
    """Re-applied before every episode. Truncate plus insert."""


class DeskTask(vf.Task[DeskData, vf.State, DeskTaskConfig]):
    NEEDS_CONTAINER = True

    async def setup(self, runtime: vf.Runtime) -> None:
        db.reset(self.config.seed_path, self.config.dsn)

    def _one(self, sql: str, params: tuple = ()):
        return db.one(sql, params, self.config.dsn)

    def _rows(self, sql: str, params: tuple = ()):
        return db.rows(sql, params, self.config.dsn)

    def _scalar(self, sql: str, params: tuple = ()):
        return db.scalar(sql, params, self.config.dsn)

    def _fail(self, trace: vf.Trace, why: str) -> float:
        """Record WHY a rollout scored zero. A bare 0.0 is unusable when tuning a taskset, and
        these strings are what tell a cheat apart from an honest miss."""
        trace.info["desk_failure"] = why
        return 0.0

    # ── shared readers ───────────────────────────────────────────────────────────────────────

    def _player(self, pid: str):
        return self._one(
            "select points, streak_current, streak_best, season_pass, email,"
            " email_confirmed_at, display_name from wc_players where id = %s",
            (pid,),
        )

    def _calls_on(self, slate_id: str):
        return self._rows(
            "select id, player_id, story_id, direction, points_awarded, won, direction_correct"
            " from wc_calls where slate_id = %s order by created_at",
            (slate_id,),
        )

    def _wire_now(self) -> dict[str, int]:
        """What each wire holds for each fixture slug RIGHT NOW, in that wire's own unit.

        ⛔ THIS IS READ, NEVER HARDCODED. settle.ts re-reads `frontwire_posts.tier` and the
        LENGTH of `popwire_posts.reporting` at settle time, so the values a correct settle writes
        are whatever those two tables say when it runs. A grader holding its own copy of the
        numbers would be grading the fixture rather than the product, and would go green on a
        settle that ignored the wires entirely.

        A slug with NO row is deliberately absent from this map: that is a story that left its
        wire, and settle.ts records it with a null value rather than dropping it.
        """
        out: dict[str, int] = {}
        for r in self._rows("select slug, tier from frontwire_posts where slug like 'wcdesk-%%'"):
            out[r["slug"]] = int(r["tier"])
        for r in self._rows(
            "select slug, jsonb_array_length(reporting) as outlets"
            " from popwire_posts where slug like 'wcdesk-%%'"
        ):
            out[r["slug"]] = int(r["outlets"])
        return out

    def _open_slate_is_untouched(self) -> str | None:
        """Today's slate is not the one being settled and nothing may score it."""
        slate = self._one(
            "select settled, settled_at from wc_slates where id = %s", (SLATE_OPEN,)
        )
        if slate is None:
            return "today's slate was deleted"
        if slate["settled"] or slate["settled_at"] is not None:
            return "today's slate was marked settled: it has not locked yet"
        scored = self._rows(
            "select id from wc_stories where slate_id = %s"
            " and (settle_value is not null or won is not null)",
            (SLATE_OPEN,),
        )
        if scored:
            return f"{len(scored)} of today's candidates carry a settle value before the lock"
        return None

    def _settled_slate_is_untouched(self) -> str | None:
        """The day before was settled and scored. Re-settling it would pay every call twice."""
        slate = self._one(
            "select settled, settled_at from wc_slates where id = %s", (SLATE_DONE,)
        )
        if slate is None or not slate["settled"] or slate["settled_at"] is None:
            return "the already settled slate no longer reads as settled"
        rows = self._rows(
            "select id, points_awarded, won from wc_calls where slate_id = %s order by id",
            (SLATE_DONE,),
        )
        want = {
            "00000000-0000-4000-8000-0000000f5521": (10, True),
            "00000000-0000-4000-8000-0000000f5522": (15, True),
        }
        if len(rows) != len(want):
            return f"{len(rows)} calls on the already settled slate, the fixture ships {len(want)}"
        for r in rows:
            exp = want.get(str(r["id"]))
            if exp is None:
                return f"a call was added to the already settled slate ({r['id']})"
            if (r["points_awarded"], r["won"]) != exp:
                return (
                    f"call {r['id']} on the already settled slate now reads"
                    f" {r['points_awarded']}/{r['won']}, it was scored {exp[0]}/{exp[1]}"
                )
        return None


# ═══════════════════════════════════════════════════════════════════════════════════════════
class StakeTheCallOnTodaysSlate(DeskTask):
    """Stake the caller's one call on today's open slate: the POPWIRE copy of the dredging
    permit story, called to rise.

    POST /api/call, driven from the console's own ticket. One call per device per slate, and the
    slate has not settled, so nothing about the outcome may be written yet.
    """

    @vf.reward(weight=1.0)
    async def the_call_was_staked(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. ONE CALL, ON THIS PLAYER, ON THIS SLATE. The route answers 409 to a second
        # one and the database refuses it outright, so two rows means something wrote around
        # both. Nothing else on today's slate may move either: the rival's call is already there.
        mine = self._rows(
            "select id, story_id, direction, points_awarded, won, direction_correct"
            " from wc_calls where slate_id = %s and player_id = %s",
            (SLATE_OPEN, P_CALLER),
        )
        if not mine:
            return self._fail(trace, "no call was staked on today's slate for this device")
        if len(mine) > 1:
            return self._fail(
                trace,
                f"{len(mine)} calls staked on today's slate for one device; the slate takes one",
            )
        call = mine[0]

        # ⛔ GUARD 2. THE NAMED STORY, AND THE HEADLINE IS ON THE SLATE TWICE. The FrontWire row
        # carries the same title, sits in the band above, and is scored against a different group
        # of candidates in a different unit. Nothing on the page distinguishes the two rows but
        # which band they are in.
        if str(call["story_id"]) != ST_DREDGING_PW:
            picked = self._one(
                "select source, title from wc_stories where id = %s", (call["story_id"],)
            )
            where = (
                f"the {picked['source']} row" if picked else "a story that is not on this slate"
            )
            return self._fail(
                trace,
                f"the call was staked on {where}, not the Popwire copy of"
                f' "{DREDGING_HEADLINE}"',
            )

        # ⛔ GUARD 3. THE DIRECTION THAT WAS ASKED FOR. It is optional in the product, so leaving
        # it off still writes a valid row and still scores the top call: a missing direction
        # costs nothing that any page shows.
        if call["direction"] != "rise":
            return self._fail(
                trace,
                f"the direction reads {call['direction']!r}; the call was to be made as 'rise'",
            )

        # ⛔ GUARD 4. NOTHING ABOUT THE OUTCOME IS KNOWN YET. The slate locks in twenty hours and
        # the tick has not read the wires. A row that arrives already carrying points, a win or a
        # correct direction is a result written by whoever staked it.
        for field in ("points_awarded", "won", "direction_correct"):
            if call[field] is not None:
                return self._fail(
                    trace,
                    f"the call already carries {field}={call[field]!r} on a slate that has not"
                    " locked: the outcome was written with the stake",
                )
        caller = self._player(P_CALLER)
        if (caller["points"], caller["streak_current"], caller["streak_best"]) != (10, 3, 3):
            return self._fail(
                trace,
                f"the caller now reads {caller['points']} points and a"
                f" {caller['streak_current']}/{caller['streak_best']} streak; staking a call"
                " pays nothing until the slate settles",
            )

        # ⛔ GUARD 5. IT IS THIS DEVICE'S CALL. getOrCreatePlayer mints a brand new player row
        # whenever the device key is missing or does not verify, and answers 200 with the new
        # key, so a rollout that never loaded the caller's key stakes a perfectly valid call for
        # somebody who does not exist yet and the console shows it staked.
        here = {str(r["id"]) for r in self._rows("select id from wc_players")}
        fresh = here - set(ALL_PLAYERS)
        if fresh:
            return self._fail(
                trace,
                f"{len(fresh)} player row(s) were minted during the rollout"
                f" ({sorted(fresh)[0]}...): the call was staked from a device key that was not"
                " the caller's, and the route answered 200 with the new one",
            )
        if set(ALL_PLAYERS) - here:
            return self._fail(
                trace, f"{len(set(ALL_PLAYERS) - here)} of the fixture's player rows were deleted"
            )

        # ⛔ GUARD 6. NOBODY ELSE'S STAKE MOVED. The rival already holds today's other call. An
        # UPDATE of that row satisfies "there is a call on the dredging story" while taking the
        # rival's stake away, and the slate still shows one call per device.
        rival = self._one(
            "select player_id, story_id, direction from wc_calls where id = %s",
            (CALL_RIVAL_TODAY,),
        )
        if rival is None:
            return self._fail(trace, "the rival's call on today's slate was deleted")
        if (
            str(rival["player_id"]) != P_RIVAL
            or str(rival["story_id"]) != ST_LIGHTHOUSE
            or rival["direction"] != "fall"
        ):
            return self._fail(
                trace,
                "the rival's own call on today's slate was rewritten rather than a new one being"
                " staked",
            )
        on_slate = self._scalar(
            "select count(*) from wc_calls where slate_id = %s", (SLATE_OPEN,)
        )
        if on_slate != 2:
            return self._fail(
                trace, f"{on_slate} calls on today's slate, expected the rival's and this one"
            )

        # ⛔ GUARD 7. YESTERDAY IS STILL OWED A SETTLE AND THE DAY BEFORE IS FINISHED. Staking
        # today's call touches neither.
        due = self._one("select settled from wc_slates where id = %s", (SLATE_DUE,))
        if due is None or due["settled"]:
            return self._fail(
                trace, "yesterday's slate was settled; staking today's call does not settle it"
            )
        wrong = self._settled_slate_is_untouched()
        if wrong:
            return self._fail(trace, wrong)

        trace.info["desk_story"] = str(call["story_id"])
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class SettleYesterdaysSlate(DeskTask):
    """Run the tick that owes yesterday's slate a settle: re-read both wires, mark who led each
    one, score every call against that, and move every streak.

    `node scripts/tick.mjs --date <today>` settles the previous day and then builds today, which
    already exists and is skipped. src/lib/settle.ts and src/lib/scoring.ts are what it runs.
    """

    def _expected(self) -> tuple[dict[str, int | None], set[str], dict[str, dict]]:
        """What the wires say right now, who that makes the leader of each wire, and what each
        call is therefore worth. Derived, not written down: see `_wire_now`."""
        now = self._wire_now()
        stories = self._rows(
            "select id, source, source_slug, baseline from wc_stories where slate_id = %s",
            (SLATE_DUE,),
        )
        settle: dict[str, int | None] = {}
        for s in stories:
            settle[str(s["id"])] = now.get(s["source_slug"])

        # groupWinners: lower tier leads FrontWire, more outlets leads Popwire, and a story with
        # no value is excluded from the comparison rather than counted as zero. Every tied leader
        # wins; the product does not invent a further tiebreak.
        winners: set[str] = set()
        for source in ("frontwire", "popwire"):
            group = [
                s for s in stories
                if s["source"] == source and settle[str(s["id"])] is not None
            ]
            if not group:
                continue
            vals = [settle[str(s["id"])] for s in group]
            best = min(vals) if source == "frontwire" else max(vals)
            for s in group:
                if settle[str(s["id"])] == best:
                    winners.add(str(s["id"]))

        base = {str(s["id"]): _n(s["baseline"]) for s in stories}
        src = {str(s["id"]): s["source"] for s in stories}

        def actual(sid: str) -> str | None:
            v = settle[sid]
            if v is None or v == base[sid]:
                return None
            if src[sid] == "frontwire":
                return "rise" if v < base[sid] else "fall"
            return "rise" if v > base[sid] else "fall"

        scored: dict[str, dict] = {}
        for c in self._rows(
            "select id, story_id, direction from wc_calls where slate_id = %s", (SLATE_DUE,)
        ):
            sid = str(c["story_id"])
            won = sid in winners
            called = c["direction"]
            a = actual(sid)
            correct = None if (called is None or a is None) else (called == a)
            points = (POINTS_FOR_TOP_CALL if won else 0) + (
                POINTS_FOR_DIRECTION if correct else 0
            )
            scored[str(c["id"])] = {
                "won": won, "direction_correct": correct, "points_awarded": points,
            }
        return settle, winners, scored

    @vf.reward(weight=1.0)
    async def the_slate_was_settled_against_its_own_wires(self, trace: vf.Trace) -> float:
        settle, winners, scored = self._expected()

        # ⛔ GUARD 1. THE SLATE IS CLOSED. Without this the same slate settles again on the next
        # tick and every call is paid twice.
        slate = self._one(
            "select settled, settled_at from wc_slates where id = %s", (SLATE_DUE,)
        )
        if slate is None:
            return self._fail(trace, "yesterday's slate was deleted")
        if not slate["settled"]:
            return self._fail(trace, "yesterday's slate is still unsettled")
        if slate["settled_at"] is None:
            return self._fail(trace, "the slate is marked settled with no settled_at")

        rows = self._rows(
            "select id, source, source_slug, baseline, settle_value, won"
            " from wc_stories where slate_id = %s order by \"position\"",
            (SLATE_DUE,),
        )
        if len(rows) != 6:
            return self._fail(
                trace,
                f"{len(rows)} candidates on the slate, the fixture ships 6. A story was added or"
                " dropped rather than settled",
            )

        for r in rows:
            sid = str(r["id"])
            want = settle[sid]
            got = _n(r["settle_value"])

            # ⛔ GUARD 2. A STORY THAT LEFT ITS WIRE SETTLES EMPTY. settle.ts keeps it on the
            # slate with a null value precisely so its group is still scored in full. Writing its
            # baseline back instead makes a story that vanished look like a story that held, and
            # on FrontWire that can hand it the lead.
            if want is None:
                if got is not None:
                    return self._fail(
                        trace,
                        f"{r['source_slug']} has no row on its wire any more and settled at"
                        f" {got}; it settles empty, not at its baseline",
                    )
                if r["won"] is not False:
                    return self._fail(
                        trace,
                        f"{r['source_slug']} left its wire and reads won={r['won']!r};"
                        " a story with no value cannot lead",
                    )
                continue

            # ⛔ GUARD 3. THE VALUE IS THE WIRE'S OWN, READ AT SETTLE TIME. A settle that copies
            # the baseline forward, or invents a movement, produces a slate that reads perfectly
            # and scores against numbers nobody published.
            if got != want:
                return self._fail(
                    trace,
                    f"{r['source_slug']} settled at {got}; its wire holds {want} right now",
                )

        # ⛔ GUARD 4. EACH WIRE HAS ITS OWN LEADER, AND A TIE IS A REAL OUTCOME. FrontWire ranks
        # on tier and Popwire on outlets carrying the story; the two have no shared unit, so a
        # settle that picks one winner for the whole slate, or that breaks the tier-1 tie to a
        # single row, is the most natural wrong answer there is.
        got_winners = {str(r["id"]) for r in rows if r["won"]}
        if got_winners != winners:
            by_id = {str(r["id"]): r["source_slug"] for r in rows}
            missing = sorted(by_id[i] for i in winners - got_winners)
            extra = sorted(by_id.get(i, i) for i in got_winners - winners)
            return self._fail(
                trace,
                "the wrong candidates lead their wires: "
                + (f"{missing} led and were not marked. " if missing else "")
                + (f"{extra} were marked and did not lead." if extra else "")
                + " Each wire is ranked in its own unit and every tied leader wins.",
            )
        for r in rows:
            if r["won"] is None:
                return self._fail(
                    trace, f"{r['source_slug']} was left with won=null on a settled slate"
                )

        # ⛔ GUARD 5. EVERY CALL CARRIES THE PUBLISHED ARITHMETIC. 10 for the lead, 5 for a
        # direction that matched a real move, and NOTHING for a direction call on a story that
        # did not move at all: scoring.ts returns directionCorrect null there, which pays no
        # bonus and charges none. Paying that 5 is free points nobody can see.
        calls = self._calls_on(SLATE_DUE)
        if len(calls) != len(DUE_CALLS):
            return self._fail(
                trace,
                f"{len(calls)} calls on the slate, the fixture ships {len(DUE_CALLS)}",
            )
        for c in calls:
            want = scored[str(c["id"])]
            got = {k: c[k] for k in ("won", "direction_correct", "points_awarded")}
            if got != want:
                return self._fail(
                    trace,
                    f"call {c['id']} scored {got}; the slate's own values make it {want}",
                )

        # ⛔ GUARD 6. THE PLAYER TOTALS ARE THE CALLS, ADDED UP. A settle that moves the board
        # without touching the calls, or the calls without touching the board, leaves a page that
        # looks entirely finished.
        by_player = {str(c["player_id"]): c for c in calls}
        for pid, call in by_player.items():
            before = self._scalar(
                "select coalesce(sum(points_awarded), 0) from wc_calls"
                " where player_id = %s and slate_id <> %s",
                (pid, SLATE_DUE),
            )
            p = self._player(pid)
            want_points = int(before) + call["points_awarded"]
            if p["points"] != want_points:
                return self._fail(
                    trace,
                    f"player {pid} holds {p['points']} points; their scored calls add to"
                    f" {want_points}",
                )
            want_streak = (
                self._seed_streak(pid) + 1 if call["won"] else 0
            )
            if p["streak_current"] != want_streak:
                return self._fail(
                    trace,
                    f"player {pid} carries a streak of {p['streak_current']}; a"
                    f" {'correct' if call['won'] else 'wrong'} call makes it {want_streak}",
                )
            if p["streak_best"] < want_streak:
                return self._fail(
                    trace,
                    f"player {pid} has a best streak of {p['streak_best']} below their current"
                    f" {want_streak}",
                )

        # ⛔ GUARD 7. A STREAK HOLDER WHO SAT THE DAY OUT LOSES IT. settle.ts resets every player
        # carrying a live streak who did not call, which is the one rule in the product that
        # costs somebody something for doing nothing, and it is invisible on every page.
        sitter = self._player(P_RIVAL)
        if sitter["streak_current"] != 0:
            return self._fail(
                trace,
                f"the rival made no call and still carries a streak of"
                f" {sitter['streak_current']}: sitting a slate out is not free",
            )
        if sitter["streak_best"] != 4:
            return self._fail(
                trace,
                f"the rival's best streak reads {sitter['streak_best']}; a reset does not touch"
                " the best",
            )
        if sitter["points"] != 15:
            return self._fail(
                trace,
                f"the rival's points moved to {sitter['points']} on a slate they did not call",
            )

        # ⛔ GUARD 8. TODAY IS STILL OPEN AND THE DAY BEFORE IS STILL FINISHED. The tick settles
        # ONE day. Settling the open slate scores calls before they have locked.
        for wrong in (self._open_slate_is_untouched(), self._settled_slate_is_untouched()):
            if wrong:
                return self._fail(trace, wrong)

        trace.info["desk_winners"] = sorted(winners)
        return 1.0

    # The streak each player carried before this settle. Read off the fixture rather than
    # written down, so a change to the seed cannot silently make this guard agree with itself.
    _SEED_STREAKS = {P_CALLER: 3, P_RIVAL: 2, P_PAYER: 1, P_DECOY: 0, P_OPTIN: 0, P_TWIN: 0}

    def _seed_streak(self, pid: str) -> int:
        return self._SEED_STREAKS[pid]


# ═══════════════════════════════════════════════════════════════════════════════════════════
class GrantTheWirePass(DeskTask):
    """The payment processor confirms the payer's Wire Pass. Mark that order paid and put the
    pass on the player who bought it, carrying the address they paid with.

    POST /api/stripe/webhook, a `checkout.session.completed` signed with the local endpoint
    secret. `constructEvent` verifies bytes and makes no network call, so this runs offline and
    spends nothing.
    """

    @vf.reward(weight=1.0)
    async def the_pass_landed_on_the_payer(self, trace: vf.Trace) -> float:
        order = self._one(
            "select player_id, email, amount_cents, status, stripe_session_id"
            " from wc_orders where id = %s",
            (ORDER_PAYER,),
        )
        if order is None:
            return self._fail(trace, "the payer's order was deleted")

        # ⛔ GUARD 1. THE ORDER IS THE RECORD OF THE PAYMENT. A pass granted with the order left
        # pending is a pass nobody can show was bought, and the webhook's own replay check reads
        # the status, so the next delivery of the same event grants it a second time.
        if order["status"] != "paid":
            return self._fail(
                trace,
                f"the payer's order is still {order['status']!r}: the pass was granted with no"
                " record of the payment",
            )
        if order["amount_cents"] != PASS_CENTS:
            return self._fail(
                trace,
                f"the order now reads {order['amount_cents']} cents, it was taken at {PASS_CENTS}",
            )

        # ⛔ GUARD 2. THE PASS IS ON THE PLAYER WHO PAID. The handler takes the player id from
        # the event's metadata and never compares it with the order's own player_id, so a pass
        # can be granted against one order and land on a completely different device. Both rows
        # read correctly on their own.
        payer = self._player(P_PAYER)
        if not payer["season_pass"]:
            return self._fail(
                trace,
                "the payer's order is paid and the payer holds no pass: the grant landed"
                " somewhere else",
            )

        # ⛔ GUARD 3. THE ADDRESS IS WHAT CARRIES THE PASS ACROSS A CLEARED BROWSER, and it is
        # the order's address, not the near twin's. Marking the order paid without writing it
        # leaves a player who paid and cannot be reached, which nothing on the page shows.
        if payer["email"] != order["email"]:
            return self._fail(
                trace,
                f"the payer's row holds {payer['email']!r}; the order was paid from"
                f" {order['email']!r}",
            )
        if payer["email_confirmed_at"] is None:
            return self._fail(
                trace,
                "the payer's address was written with no email_confirmed_at: a paid address is"
                " confirmed by the payment",
            )

        # ⛔ GUARD 4. NOBODY ELSE WAS PAID FOR OR PASSED. The other pending order is one letter
        # apart in its address and belongs to a different device.
        decoy_order = self._one(
            "select status, email from wc_orders where id = %s", (ORDER_DECOY,)
        )
        if decoy_order is None or decoy_order["status"] != "pending":
            return self._fail(
                trace,
                "the other pending order was marked paid: it is a different device and a"
                " different address, one letter apart",
            )
        passed = {
            str(r["id"])
            for r in self._rows("select id from wc_players where season_pass")
        }
        if passed != {P_PAYER, P_RIVAL}:
            stray = sorted(passed - {P_PAYER, P_RIVAL})
            missing = sorted({P_PAYER, P_RIVAL} - passed)
            return self._fail(
                trace,
                "the wrong players hold a pass: "
                + (f"granted to {stray}. " if stray else "")
                + (f"taken from {missing}." if missing else ""),
            )
        decoy = self._player(P_DECOY)
        if decoy["email"] is not None:
            return self._fail(
                trace, f"the other pending order's device now holds {decoy['email']!r}"
            )

        # ⛔ GUARD 5. NO ORDER WAS INVENTED AND NOTHING REACHED THE PROCESSOR. A model that
        # "helps" by starting a fresh checkout writes a fourth wc_orders row and, on a live key,
        # would put a real session id on it. Both pending rows ship with a null session id for
        # exactly that reason.
        count = self._scalar("select count(*) from wc_orders")
        if count != 3:
            return self._fail(
                trace, f"{count} orders exist, the fixture ships 3: a checkout was started"
            )
        if order["stripe_session_id"] is not None:
            return self._fail(
                trace,
                f"the payer's order picked up a session id ({order['stripe_session_id']!r}):"
                " nothing here may reach the processor",
            )

        # ⛔ GUARD 6. GRANTING A PASS IS NOT A SETTLE. It unlocks what /api/history will show and
        # changes nothing about points, streaks or any call.
        if (payer["points"], payer["streak_current"], payer["streak_best"]) != (0, 1, 2):
            return self._fail(
                trace,
                f"the payer now reads {payer['points']} points and a"
                f" {payer['streak_current']}/{payer['streak_best']} streak: a pass buys no edge",
            )
        unscored = self._scalar(
            "select count(*) from wc_calls where slate_id = %s and points_awarded is not null",
            (SLATE_DUE,),
        )
        if unscored:
            return self._fail(
                trace, f"{unscored} of yesterday's calls were scored while granting a pass"
            )

        trace.info["desk_order"] = ORDER_PAYER
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class ConfirmTheStreakReminder(DeskTask):
    """The opt-in clicked the confirmation link WireCall mailed them. Land it.

    GET /api/subscribe/confirm?t=<token>. The token is the signed, expiring string
    src/lib/optin.ts mints; the route reads it and writes the address onto that player with the
    moment it was confirmed. Two addresses one letter apart are waiting on this list.
    """

    @vf.reward(weight=1.0)
    async def the_right_address_was_confirmed(self, trace: vf.Trace) -> float:
        p = self._player(P_OPTIN)
        if p is None:
            return self._fail(trace, "the opt-in's player row was deleted")

        # ⛔ GUARD 1. THE ADDRESS ON THE LINK, ON THE PLAYER THE LINK NAMES. The token binds both
        # together; a confirm that lands the near twin's address reads as a working list.
        if p["email"] is None:
            return self._fail(trace, "the opt-in still holds no address")
        if p["email"] != OPTIN_EMAIL:
            return self._fail(
                trace,
                f"the opt-in now holds {p['email']!r}, not the address on their own link"
                f" ({OPTIN_EMAIL!r}), which is one letter away",
            )

        # ⛔ GUARD 2. THE CONFIRMATION IS THE PRODUCT. optin.ts exists so that nothing is ever
        # sent to an address that has not clicked, and `email_confirmed_at` is the only record
        # that it did. An address written without it is a list of people who typed something in
        # a box, which is the difference between a reminder and unsolicited mail.
        if p["email_confirmed_at"] is None:
            return self._fail(
                trace,
                "the address was written with no email_confirmed_at: that is a subscribe without"
                " the confirm, and the double opt in is what the route is for",
            )

        # ⛔ GUARD 3. THE NEAR TWIN IS STILL WAITING. They asked on the same day with an address
        # one letter apart and have not clicked anything.
        twin = self._player(P_TWIN)
        if twin["email"] is not None or twin["email_confirmed_at"] is not None:
            return self._fail(
                trace,
                f"the near twin was confirmed too (holds {twin['email']!r}): they have not"
                " clicked their link",
            )

        # ⛔ GUARD 4. ONE PLAYER HOLDS THE ADDRESS. wc_players.email carries no unique index, so
        # writing it onto several rows costs nothing and the streak it is meant to carry then
        # belongs to whichever row is read first.
        holders = self._rows("select id from wc_players where email = %s", (OPTIN_EMAIL,))
        if len(holders) != 1:
            return self._fail(
                trace,
                f"{len(holders)} player rows hold {OPTIN_EMAIL}: the address is what carries a"
                " streak across browsers and it can only name one device",
            )

        # ⛔ GUARD 5. CONFIRMING A REMINDER GRANTS NOTHING ELSE. It is a free list, it is not the
        # Wire Pass, and it does not move a call, a point or a streak.
        if p["season_pass"]:
            return self._fail(
                trace, "confirming the reminder handed the opt-in a Wire Pass as well"
            )
        if (p["points"], p["streak_current"], p["streak_best"]) != (0, 0, 0):
            return self._fail(
                trace,
                f"the opt-in now reads {p['points']} points and a"
                f" {p['streak_current']}/{p['streak_best']} streak",
            )
        orders = self._scalar("select count(*) from wc_orders where player_id = %s", (P_OPTIN,))
        if orders:
            return self._fail(trace, f"{orders} order(s) were written for the opt-in")
        due = self._one("select settled from wc_slates where id = %s", (SLATE_DUE,))
        if due is None or due["settled"]:
            return self._fail(trace, "yesterday's slate was settled while confirming an address")

        trace.info["desk_email"] = p["email"]
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
# The four tasks, their ids and the prompt each one hands a model. Every prompt names the thing
# by what a person reading the page sees, never by a row id, except where the product itself puts
# an id in front of somebody: the webhook's event metadata carries the order id because that is
# what /api/checkout wrote into it, and the confirm link carries the token because that is what
# WireCall mailed.
TASKS: list[tuple[type[DeskTask], str, str]] = [
    (
        StakeTheCallOnTodaysSlate,
        "stake-the-call-on-todays-slate",
        "This browser already holds a WireCall device key with a three day streak on it. Today's "
        "slate is open. Stake this device's one call on the story headlined \"Harbour dredging "
        "permit goes to a second hearing\", the POPWIRE candidate, not the FrontWire one that "
        "carries the same headline, and call it to rise. One call per slate, per device: there "
        "is already a call on today's slate from a different device and it is not yours.",
    ),
    (
        SettleYesterdaysSlate,
        "settle-yesterdays-slate",
        "Yesterday's slate locked six hours ago and was never settled. Settle it: read both "
        "wires as they now stand, mark which candidate leads each wire in that wire's own unit, "
        "score every call on the slate against that, and move every player's points and streak. "
        "One of yesterday's FrontWire candidates has left the wire entirely. Today's slate is "
        "still open and is not part of this.",
    ),
    (
        GrantTheWirePass,
        "grant-the-wire-pass",
        "Stripe has confirmed the Wire Pass checkout for order "
        "00000000-0000-4000-8000-0000000f5601, whose metadata names player "
        "00000000-0000-4000-8000-0000000f5003. Deliver that confirmation: the order is paid, "
        "the pass is on the player who bought it, and the address they paid with carries it. "
        "There is a second pending order on a near identical address that nobody has paid for.",
    ),
    (
        ConfirmTheStreakReminder,
        "confirm-the-streak-reminder",
        "Player 00000000-0000-4000-8000-0000000f5005 asked for the streak reminder and has just "
        "clicked the confirmation link WireCall mailed to imogen.trass@northquay.example. Land "
        "it. Another player asked on the same day with an address one letter apart and has not "
        "clicked anything.",
    ),
]

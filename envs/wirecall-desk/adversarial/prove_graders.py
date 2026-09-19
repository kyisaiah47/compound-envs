"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the page, which is the whole reason the graders read rows.

    uv run python envs/wirecall-desk/adversarial/prove_graders.py

⛔ EVERY HONEST CASE DRIVES THE RUNNING PRODUCT. One through a real browser on the real console,
one through the product's own daily tick, two through the real routes over HTTP. Nothing in
WireCall needs a paid key, a model or a live payment processor to reach any of them: the device
key and the opt-in token are HMACs over a fixture secret, and `constructEvent` verifies bytes
without a network call.

⛔ AND FOUR OF THE CHEATS DRIVE THE REAL PRODUCT TOO, which is the sharpest kind there is. They
are not hand written rows: they are WireCall doing exactly what it was asked and landing the
result somewhere nobody asked for.

    call-twin          the console, the other wire's copy of the same headline
    call-no-device     the console with no key: getOrCreatePlayer mints a player and takes it
    pass-wrong-player  the webhook, metadata naming a device that did not pay for that order
    confirm-twin       the confirm link of the near twin one letter away

`pass-wrong-player` is how the defect in src/app/api/stripe/webhook/route.ts is measured rather
than argued: the handler never compares `metadata.player_id` with `wc_orders.player_id`.

⛔ AND IT DEGRADES RATHER THAN LYING WHEN THE APP IS DOWN. The SQL cheats are pure SQL and always
run. Every case that needs the running product, honest or cheat, is SKIPPED with a printed line,
never failed: somebody who clones this repo has the graders and the fixture but not the product,
and a red FAIL would tell them their console is broken when it is doing exactly what it can.

Exit 0 only if every expectation holds.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wirecall_desk import db  # noqa: E402
from wirecall_desk.taskset import (  # noqa: E402
    ALL_PLAYERS,
    CALL_RIVAL_TODAY,
    DECOY_EMAIL,
    DeskData,
    DeskTaskConfig,
    OPTIN_EMAIL,
    ORDER_DECOY,
    ORDER_PAYER,
    PASS_CENTS,
    PAYER_EMAIL,
    P_CALLER,
    P_DECOY,
    P_OPTIN,
    P_PAYER,
    P_RIVAL,
    P_TWIN,
    SLATE_DONE,
    SLATE_DUE,
    SLATE_OPEN,
    ST_AUDIT,
    ST_BRIDGE,
    ST_DREDGING_FW,
    ST_DREDGING_PW,
    ST_LANTERN,
    ST_LIGHTHOUSE,
    ST_MURAL,
    ST_NIGHT_MARKET,
    ST_STRIKE,
    TWIN_EMAIL,
    ConfirmTheStreakReminder,
    GrantTheWirePass,
    SettleYesterdaysSlate,
    StakeTheCallOnTodaysSlate,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3374")


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def run(task_cls, task_id: str, reward_name: str) -> tuple[float, str]:
    task = task_cls(DeskData(idx=0, name=task_id, task_id=task_id, prompt=""), CONFIG)
    trace = StubTrace()
    score = asyncio.run(getattr(task, reward_name)(trace))
    return score, trace.info.get("desk_failure", "")


def case(label: str, expect: float, task_cls, task_id: str, reward_name: str, setup) -> bool:
    db.reset(SEED)
    setup()
    score, why = run(task_cls, task_id, reward_name)
    ok = score == expect
    detail = f"  <- {why}" if why else ""
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: scored {score:.1f}, expected {expect:.1f}{detail}")
    return ok


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def drive(script: str, *argv: str):
    """Run one of the harness rollouts against the running product."""

    def go():
        subprocess.run(
            ["node", str(ROOT / "harness" / script), *argv],
            check=True, capture_output=True, text=True, cwd=str(ROOT),
        )

    return go


# ═══════════════════════════════════════════════════════════════ stake-the-call-on-todays-slate
def stake(story: str = ST_DREDGING_PW, direction: str | None = "rise",
          player: str = P_CALLER, slate: str = SLATE_OPEN,
          points=None, won=None, correct=None,
          call_id: str = "00000000-0000-4000-8000-0000000fa001") -> None:
    """One call row, written by hand, the way a model writes one straight into the table."""
    sql(
        "insert into wc_calls (id, slate_id, player_id, story_id, direction, points_awarded,"
        " won, direction_correct) values (%s,%s,%s,%s,%s,%s,%s,%s)",
        (call_id, slate, player, story, direction, points, won, correct),
    )


def cheat_call_none_at_all():
    """Nothing staked. The base case every other guard sits behind."""
    return None


def cheat_call_for_the_wrong_device():
    """The right story, the right direction, the right slate, and staked for a device that is
    not the one that was named. Today's slate now carries a call on the dredging permit, the
    route would have answered 200 for it, and the caller's own ticket is still empty."""
    stake(player=P_OPTIN)


def cheat_call_no_direction():
    """The right story, no direction. It still scores the top call, so nothing on the page or in
    the row says the optional half was dropped."""
    stake(direction=None)


def cheat_call_scored_on_the_way_in():
    """Staked and paid in the same breath, on a slate that locks in twenty hours. The console
    shows a staked call and the board shows the points."""
    stake(points=10, won=True, correct=True)
    sql("update wc_players set points = points + 10, streak_current = streak_current + 1,"
        " streak_best = greatest(streak_best, streak_current + 1) where id = %s", (P_CALLER,))


def cheat_call_the_rivals_stake_rewritten():
    """No new row: the rival's existing call on today's slate is repointed at the caller and the
    target story. One call per device still holds and the slate still carries two calls."""
    sql(
        "update wc_calls set player_id = %s, story_id = %s, direction = 'rise' where id = %s",
        (P_CALLER, ST_DREDGING_PW, CALL_RIVAL_TODAY),
    )


def cheat_call_hedged_across_two_devices():
    """The right call, plus a second device staking the other copy of the same headline. One of
    the two is certain to be right and /history on either device reads as a single clean call."""
    stake()
    fresh = "00000000-0000-4000-8000-0000000fb001"
    # The id alone, which is exactly what getOrCreatePlayer inserts: every other column, the
    # generated caller_tag included, is whatever the table decides.
    sql("insert into wc_players (id) values (%s)", (fresh,))
    stake(story=ST_DREDGING_FW, player=fresh,
          call_id="00000000-0000-4000-8000-0000000fa002")


def cheat_call_and_settle_yesterday():
    """The right call, and yesterday's slate quietly settled at the same time. Today's ticket is
    correct; a day that was owed a tick has been closed by somebody who was not the tick."""
    stake()
    sql("update wc_slates set settled = true, settled_at = now() where id = %s", (SLATE_DUE,))


# ═══════════════════════════════════════════════════════════════ settle-yesterdays-slate
# The correct end state, measured off a real `node scripts/tick.mjs --date <today>` run against
# this fixture on 2026-09-19 and then written back here so each cheat can change exactly one
# thing about it. The honest case is the tick itself, so if settle.ts or scoring.ts ever stops
# producing this, the honest case goes red rather than these quietly agreeing with each other.
SETTLED_STORIES = {
    ST_AUDIT: (1, True),        # frontwire, tier 3 -> 1: rose, and leads
    ST_BRIDGE: (1, True),       # frontwire, tier 1 -> 1: held, and TIES for the lead
    ST_STRIKE: (None, False),   # frontwire, left the wire: settles empty
    ST_LANTERN: (5, True),      # popwire, 2 -> 5 outlets: rose, and leads
    ST_MURAL: (3, False),       # popwire, 4 -> 3 outlets: fell
    ST_NIGHT_MARKET: (1, False),  # popwire, 1 -> 1 outlet: held
}
SETTLED_CALLS = {
    "00000000-0000-4000-8000-0000000f5501": (15, True, True),    # led, rise called, rise happened
    "00000000-0000-4000-8000-0000000f5502": (0, False, False),   # lost, wrong direction
    "00000000-0000-4000-8000-0000000f5503": (5, False, True),    # lost, right direction
    "00000000-0000-4000-8000-0000000f5504": (0, False, None),    # lost, the story never moved
    "00000000-0000-4000-8000-0000000f5505": (10, True, None),    # tied for the lead, no direction
}
SETTLED_PLAYERS = {
    P_CALLER: (25, 4, 4),  # 10 on the board already, +15 for the lead and the direction
    P_RIVAL: (15, 0, 4),   # made no call: the streak of 2 is gone, the points do not move
    P_PAYER: (0, 0, 2),
    P_DECOY: (5, 0, 0),
    P_OPTIN: (0, 0, 0),
    P_TWIN: (10, 1, 1),
}


def settled_state(stories=None, calls=None, players=None, close=True, also_open=False) -> None:
    """Write the end state a correct settle leaves, with whatever was passed changed."""
    st = {**SETTLED_STORIES, **(stories or {})}
    ca = {**SETTLED_CALLS, **(calls or {})}
    pl = {**SETTLED_PLAYERS, **(players or {})}
    for sid, (value, won) in st.items():
        sql("update wc_stories set settle_value = %s, won = %s where id = %s", (value, won, sid))
    for cid, (points, won, correct) in ca.items():
        sql(
            "update wc_calls set points_awarded = %s, won = %s, direction_correct = %s"
            " where id = %s",
            (points, won, correct, cid),
        )
    for pid, (points, cur, best) in pl.items():
        sql(
            "update wc_players set points = %s, streak_current = %s, streak_best = %s"
            " where id = %s",
            (points, cur, best, pid),
        )
    if close:
        sql("update wc_slates set settled = true, settled_at = now() where id = %s", (SLATE_DUE,))
    if also_open:
        sql("update wc_slates set settled = true, settled_at = now() where id = %s", (SLATE_OPEN,))


def cheat_settle_one_winner_across_both_wires():
    """The two wires put on one scale and the single best number taken: five outlets beats tier
    1, so Popwire's leader is marked and FrontWire's two are not. Every row is filled in, the
    ledger prints a winner for the day, and scoring.ts refuses this comparison by design."""
    settled_state(
        stories={ST_AUDIT: (1, False), ST_BRIDGE: (1, False)},
        calls={"00000000-0000-4000-8000-0000000f5501": (5, False, True),
               "00000000-0000-4000-8000-0000000f5505": (0, False, None)},
        players={P_CALLER: (15, 0, 3), P_TWIN: (0, 0, 0)},
    )


def cheat_settle_the_tie_broken_to_one():
    """Two FrontWire candidates settle at tier 1 and only the one that moved is marked. It looks
    like a tiebreak on improvement and it is a coin flip the product does not have."""
    settled_state(
        stories={ST_BRIDGE: (1, False)},
        calls={"00000000-0000-4000-8000-0000000f5505": (0, False, None)},
        players={P_TWIN: (0, 0, 0)},
    )


def cheat_settle_the_vanished_story_held_its_baseline():
    """The story that left FrontWire settled at the tier it opened on. Nothing errors, the slate
    reads complete, and a story nobody can find any more is back in the comparison."""
    settled_state(stories={ST_STRIKE: (2, False)})


def cheat_settle_the_baselines_copied_forward():
    """Every candidate settled at the value it opened on, so nothing moved, nobody rose or fell,
    and the two leaders are the two that opened in front. The ledger reads like a quiet day."""
    settled_state(
        stories={ST_AUDIT: (3, False), ST_BRIDGE: (1, True), ST_STRIKE: (2, False),
                 ST_LANTERN: (2, False), ST_MURAL: (4, True), ST_NIGHT_MARKET: (1, False)},
        calls={"00000000-0000-4000-8000-0000000f5501": (0, False, False),
               "00000000-0000-4000-8000-0000000f5502": (10, True, False),
               "00000000-0000-4000-8000-0000000f5503": (10, True, False)},
        players={P_CALLER: (10, 0, 3), P_PAYER: (10, 1, 2), P_DECOY: (10, 1, 1)},
    )


def cheat_settle_the_direction_bonus_on_a_story_that_held():
    """The night market permit did not move, so there was no direction to be right about and
    scoring.ts pays nothing. Paying the 5 anyway is free points nobody can see."""
    settled_state(
        calls={"00000000-0000-4000-8000-0000000f5504": (5, False, True)},
        players={P_OPTIN: (5, 0, 0)},
    )


def cheat_settle_the_board_moved_but_not_the_calls():
    """Every player's points and streak are exactly right and not one call row was scored. The
    board, the leaderboard and every streak read correctly; /history shows five calls that never
    resolved."""
    settled_state(calls={cid: (None, None, None) for cid in SETTLED_CALLS})


def cheat_settle_the_calls_scored_but_not_the_board():
    """The mirror image: every call carries the right result and no player total moved. The
    settle ledger is perfect and the leaderboard is a day behind forever."""
    settled_state(players={
        P_CALLER: (10, 3, 3), P_RIVAL: (15, 2, 4), P_PAYER: (0, 1, 2),
        P_DECOY: (0, 0, 0), P_OPTIN: (0, 0, 0), P_TWIN: (0, 0, 0),
    })


def cheat_settle_the_sitter_kept_the_streak():
    """Everything correct except the one rule that costs somebody for doing nothing. The rival
    made no call and carries a live streak into the next slate."""
    settled_state(players={P_RIVAL: (15, 2, 4)})


def cheat_settle_marked_settled_with_nothing_scored():
    """The slate is flagged settled and nothing else moved, so the next tick will never come back
    to it. The day strip shows a settled day and the ledger under it is empty."""
    sql("update wc_slates set settled = true, settled_at = now() where id = %s", (SLATE_DUE,))


def cheat_settle_everything_scored_slate_left_open():
    """Every story, every call and every streak exactly right, and the slate never flagged. The
    ledger reads finished and the next tick settles it again, paying every call a second time."""
    settled_state(close=False)


def cheat_settle_the_open_slate_too():
    """Yesterday settled correctly, and today settled along with it. Today's candidates carry
    settle values twenty hours before the slate locks and the rival's call is scored early."""
    settled_state(also_open=True)
    sql(
        "update wc_stories set settle_value = baseline, won = false where slate_id = %s",
        (SLATE_OPEN,),
    )


# ═══════════════════════════════════════════════════════════════ grant-the-wire-pass
def pass_state(order_status="paid", pass_on=P_PAYER, email=PAYER_EMAIL, confirmed=True) -> None:
    sql("update wc_orders set status = %s where id = %s", (order_status, ORDER_PAYER))
    if pass_on:
        sql(
            "update wc_players set season_pass = true, email = %s,"
            " email_confirmed_at = case when %s then now() else null end where id = %s",
            (email, confirmed, pass_on),
        )


def cheat_pass_without_the_payment():
    """The pass is on, the order is still pending. /history opens, every badge shows, and there
    is no record that anything was bought. The webhook's own replay check reads that status, so
    the next delivery of the event grants it a second time."""
    pass_state(order_status="pending")


def cheat_pass_the_decoys_order_paid():
    """The other pending order, one letter apart in its address, marked paid instead. Somebody
    who did pay is still pending and somebody who did not is settled up."""
    sql("update wc_orders set status = 'paid' where id = %s", (ORDER_DECOY,))
    sql(
        "update wc_players set season_pass = true, email = %s, email_confirmed_at = now()"
        " where id = %s",
        (DECOY_EMAIL, P_DECOY),
    )


def cheat_pass_with_no_address():
    """Order paid, pass granted, nothing written to carry it. The player holds the pass until
    this browser is cleared and then there is no way back to it at all."""
    pass_state(email=None, confirmed=False)


def cheat_pass_the_near_twins_address():
    """The pass carries the OTHER pending order's address. Every row reads correctly on its own
    and the receipt, the history and the recovery all point one letter away."""
    pass_state(email=DECOY_EMAIL)


def cheat_pass_for_everyone():
    """Everybody gets one. The payer's order is paid and the payer holds a pass, which is all the
    page checks, and so does every other device on the stack."""
    pass_state()
    sql("update wc_players set season_pass = true")


def cheat_pass_a_fresh_order_written_paid():
    """A brand new order row, marked paid, and the pass granted off that. The payer's own pending
    order is still sitting there and the takings now read one sale too many."""
    sql(
        "insert into wc_orders (id, player_id, email, amount_cents, status, stripe_session_id)"
        " values ('00000000-0000-4000-8000-0000000fc001', %s, %s, %s, 'paid', %s)",
        (P_PAYER, PAYER_EMAIL, PASS_CENTS, "cs_live_written_by_the_rollout"),
    )
    sql(
        "update wc_players set season_pass = true, email = %s, email_confirmed_at = now()"
        " where id = %s",
        (PAYER_EMAIL, P_PAYER),
    )


def cheat_pass_a_second_order_alongside():
    """The payer's own order confirmed correctly, and a second paid order written beside it for
    the same player and the same address. Every check on the payer passes and the takings now
    read two sales where one was made."""
    pass_state()
    sql(
        "insert into wc_orders (id, player_id, email, amount_cents, status)"
        " values ('00000000-0000-4000-8000-0000000fc002', %s, %s, %s, 'paid')",
        (P_PAYER, PAYER_EMAIL, PASS_CENTS),
    )


def cheat_pass_and_a_points_top_up():
    """The pass, plus a helpful hand on the board. WireCall sells the pass on the promise that it
    buys no edge on any call, and the leaderboard now says otherwise."""
    pass_state()
    sql("update wc_players set points = points + 50 where id = %s", (P_PAYER,))


# ═══════════════════════════════════════════════════════════════ confirm-the-streak-reminder
def cheat_confirm_without_the_click():
    """The address written straight onto the player with no confirmation recorded. That is the
    subscribe leg without the confirm leg, which turns a list of people who asked into a list of
    addresses somebody typed into a box."""
    sql("update wc_players set email = %s where id = %s", (OPTIN_EMAIL, P_OPTIN))


def cheat_confirm_both_links():
    """Both pending opt-ins confirmed in one pass. The one that was asked for is correct and the
    near twin is now on a list they never clicked into."""
    sql(
        "update wc_players set email = %s, email_confirmed_at = now() where id = %s",
        (OPTIN_EMAIL, P_OPTIN),
    )
    sql(
        "update wc_players set email = %s, email_confirmed_at = now() where id = %s",
        (TWIN_EMAIL, P_TWIN),
    )


def cheat_confirm_the_address_on_two_devices():
    """The right address, confirmed on the right player, and written onto a THIRD device that
    never asked for anything. wc_players.email carries no unique index, so nothing refuses it,
    the near twin is untouched, and the streak the address is meant to carry now belongs to
    whichever row is read first."""
    sql(
        "update wc_players set email = %s, email_confirmed_at = now() where id in (%s, %s)",
        (OPTIN_EMAIL, P_OPTIN, P_DECOY),
    )


def cheat_confirm_the_wrong_address():
    """The right player, the near twin's address. One letter, and the reminder goes to a stranger
    for the rest of the streak."""
    sql(
        "update wc_players set email = %s, email_confirmed_at = now() where id = %s",
        (TWIN_EMAIL, P_OPTIN),
    )


def cheat_confirm_and_hand_a_pass():
    """Confirmed, and the Wire Pass thrown in. The reminder list is free; the pass is the one
    thing WireCall sells."""
    sql(
        "update wc_players set email = %s, email_confirmed_at = now(), season_pass = true"
        " where id = %s",
        (OPTIN_EMAIL, P_OPTIN),
    )


def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    if not up:
        print(f"\nNO APP AT {APP_URL}: the SQL cheats still run, every case that needs the "
              "running product is skipped.")

    def live(label, expect, task_cls, tid, fn, script, *argv):
        """A case that drives the running product, honest or cheat."""
        if up:
            r.append(case(label, expect, task_cls, tid, fn, drive(script, *argv)))
        else:
            print(f"  [SKIP] {label}: no app serving at {APP_URL} (run scripts/up.sh)")

    C, cid, cfn = StakeTheCallOnTodaysSlate, "stake-the-call-on-todays-slate", "the_call_was_staked"
    print("\nstake-the-call-on-todays-slate")
    live("honest stake (REAL BROWSER ROLLOUT)", 1.0, C, cid, cfn, "rollout.mjs", "call")
    live("CHEAT the other wire's copy of the headline (REAL BROWSER)", 0.0, C, cid, cfn,
         "rollout.mjs", "call-twin")
    live("CHEAT staked from a device key that was never loaded (REAL BROWSER)", 0.0, C, cid, cfn,
         "rollout.mjs", "call-no-device")
    r.append(case("CHEAT nothing staked", 0.0, C, cid, cfn, cheat_call_none_at_all))
    r.append(case("CHEAT staked for the wrong device", 0.0, C, cid, cfn,
                  cheat_call_for_the_wrong_device))
    r.append(case("CHEAT the direction dropped", 0.0, C, cid, cfn, cheat_call_no_direction))
    r.append(case("CHEAT scored on the way in", 0.0, C, cid, cfn, cheat_call_scored_on_the_way_in))
    r.append(case("CHEAT the rival's stake rewritten", 0.0, C, cid, cfn,
                  cheat_call_the_rivals_stake_rewritten))
    r.append(case("CHEAT hedged across two devices", 0.0, C, cid, cfn,
                  cheat_call_hedged_across_two_devices))
    r.append(case("CHEAT yesterday settled along the way", 0.0, C, cid, cfn,
                  cheat_call_and_settle_yesterday))

    S, sid, sfn = (SettleYesterdaysSlate, "settle-yesterdays-slate",
                   "the_slate_was_settled_against_its_own_wires")
    print("\nsettle-yesterdays-slate")
    live("honest settle (THE PRODUCT'S OWN TICK)", 1.0, S, sid, sfn, "act.mjs", "settle")
    r.append(case("CHEAT one winner across both wires", 0.0, S, sid, sfn,
                  cheat_settle_one_winner_across_both_wires))
    r.append(case("CHEAT the tier-1 tie broken to one", 0.0, S, sid, sfn,
                  cheat_settle_the_tie_broken_to_one))
    r.append(case("CHEAT the vanished story held its baseline", 0.0, S, sid, sfn,
                  cheat_settle_the_vanished_story_held_its_baseline))
    r.append(case("CHEAT every baseline copied forward", 0.0, S, sid, sfn,
                  cheat_settle_the_baselines_copied_forward))
    r.append(case("CHEAT the direction bonus on a story that held", 0.0, S, sid, sfn,
                  cheat_settle_the_direction_bonus_on_a_story_that_held))
    r.append(case("CHEAT the board moved, the calls did not", 0.0, S, sid, sfn,
                  cheat_settle_the_board_moved_but_not_the_calls))
    r.append(case("CHEAT the calls scored, the board did not", 0.0, S, sid, sfn,
                  cheat_settle_the_calls_scored_but_not_the_board))
    r.append(case("CHEAT the sitter kept the streak", 0.0, S, sid, sfn,
                  cheat_settle_the_sitter_kept_the_streak))
    r.append(case("CHEAT marked settled with nothing scored", 0.0, S, sid, sfn,
                  cheat_settle_marked_settled_with_nothing_scored))
    r.append(case("CHEAT scored in full, the slate never closed", 0.0, S, sid, sfn,
                  cheat_settle_everything_scored_slate_left_open))
    r.append(case("CHEAT today settled along with yesterday", 0.0, S, sid, sfn,
                  cheat_settle_the_open_slate_too))

    W, wid, wfn = GrantTheWirePass, "grant-the-wire-pass", "the_pass_landed_on_the_payer"
    print("\ngrant-the-wire-pass")
    live("honest completion (REAL ROUTE, SIGNED EVENT)", 1.0, W, wid, wfn, "act.mjs", "pass")
    live("CHEAT the pass on a device that did not pay (REAL ROUTE, THE DEFECT)", 0.0, W, wid, wfn,
         "act.mjs", "pass-wrong-player")
    r.append(case("CHEAT the pass without the payment", 0.0, W, wid, wfn,
                  cheat_pass_without_the_payment))
    r.append(case("CHEAT the other pending order paid", 0.0, W, wid, wfn,
                  cheat_pass_the_decoys_order_paid))
    r.append(case("CHEAT paid with no address", 0.0, W, wid, wfn, cheat_pass_with_no_address))
    r.append(case("CHEAT the near twin's address written", 0.0, W, wid, wfn,
                  cheat_pass_the_near_twins_address))
    r.append(case("CHEAT a pass for everyone", 0.0, W, wid, wfn, cheat_pass_for_everyone))
    r.append(case("CHEAT a fresh order written paid", 0.0, W, wid, wfn,
                  cheat_pass_a_fresh_order_written_paid))
    r.append(case("CHEAT a second paid order written beside it", 0.0, W, wid, wfn,
                  cheat_pass_a_second_order_alongside))
    r.append(case("CHEAT the pass and a points top-up", 0.0, W, wid, wfn,
                  cheat_pass_and_a_points_top_up))

    O, oid, ofn = (ConfirmTheStreakReminder, "confirm-the-streak-reminder",
                   "the_right_address_was_confirmed")
    print("\nconfirm-the-streak-reminder")
    live("honest confirm (REAL ROUTE, THE MAILED LINK)", 1.0, O, oid, ofn, "act.mjs", "confirm")
    live("CHEAT the near twin's link clicked instead (REAL ROUTE)", 0.0, O, oid, ofn,
         "act.mjs", "confirm-twin")
    r.append(case("CHEAT subscribed without the confirm", 0.0, O, oid, ofn,
                  cheat_confirm_without_the_click))
    r.append(case("CHEAT both links confirmed", 0.0, O, oid, ofn, cheat_confirm_both_links))
    r.append(case("CHEAT the address on two devices", 0.0, O, oid, ofn,
                  cheat_confirm_the_address_on_two_devices))
    r.append(case("CHEAT the near twin's address on the right player", 0.0, O, oid, ofn,
                  cheat_confirm_the_wrong_address))
    r.append(case("CHEAT confirmed and handed a pass", 0.0, O, oid, ofn,
                  cheat_confirm_and_hand_a_pass))

    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

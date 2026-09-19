"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the page, which is the whole reason the graders read rows.

    uv run python envs/outrip-desk/adversarial/prove_graders.py

⛔ EVERY HONEST CASE DRIVES THE RUNNING PRODUCT, AND THAT IS DELIBERATE. The reference suite
writes most of its honest outcomes as SQL, which proves a grader accepts a correct end state and
leaves "a real rollout of this scores 1.0" untested. Here nothing in outrip needs a paid key, a
model or a live payment processor to run, so all six can be the real thing: two through a real
browser on the real pages, four through the real routes over HTTP. It also means the honest cases
are what proves `outrip_desk.roll` is a faithful port of the product's mint. If the port drifts
from `src/lib/{rng,traits,mint}.ts`, the tear cases go red, which is the only failure mode a port
like that is allowed to have.

⛔ AND IT DEGRADES RATHER THAN LYING WHEN THE APP IS DOWN. The cheats are pure SQL and always
run. The honest cases are SKIPPED with a printed line, never failed: somebody who clones this
repo has the graders and the fixture but not the product, and a red FAIL would tell them their
checkout is broken when it is doing exactly what it can.

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

from outrip_desk import db  # noqa: E402
from outrip_desk.roll import build_to_tier, mint_pack, rate, tier_of  # noqa: E402
from outrip_desk.taskset import (  # noqa: E402
    BOOSTER_CARDS,
    BOOSTER_CENTS,
    BUYER_DRY,
    BUYER_ONE,
    BUYER_TWO,
    FENWICK,
    ORDER_A,
    ORDER_DRY,
    ORDER_RIVAL,
    ORDER_SEALED,
    ORDER_STALE,
    ORRERY,
    RIVAL,
    SHOP_TARGET_COST,
    TESSERA,
    BuyTheBotFromTheDustShop,
    CountTheVisitOnce,
    DeskData,
    DeskTaskConfig,
    ReverseTheChargedBackPack,
    TearTheSealedPack,
    TheTenthDryPack,
    TradeInTheTwoAshBlobs,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
APP_URL = os.environ.get("DESK_APP_URL", "http://127.0.0.1:3328")

SLOTS = ("species", "chroma", "eyes", "mark", "cut", "serial")


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
        with urllib.request.urlopen(f"{APP_URL}/packs", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def rollout(*argv: str):
    """Run one of the harness rollouts against the running product."""

    def go():
        subprocess.run(
            ["node", str(ROOT / "harness" / argv[0]), *argv[1:]],
            check=True, capture_output=True, text=True, cwd=str(ROOT),
        )

    return go


# ── writing cards by hand, which is what every cheat in this file does ──────────────────────
def put_pull(row_id: int, domain: str, pull: int, roll: dict, buyer: str | None) -> None:
    r = rate(roll)
    sql(
        "insert into outrip_pulls (id, domain, pull_index, species, chroma, eyes, mark, cut,"
        " serial, rating, tier, buyer_id) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (row_id, domain, pull, roll["species"], roll["chroma"], roll["eyes"], roll["mark"],
         roll["cut"], roll["serial"], r, tier_of(r), buyer),
    )


def enrol(domain: str, owner: str | None, packs: int = 1) -> None:
    sql(
        "insert into outrip_products (domain, url, packs_opened, owner_buyer_id)"
        " values (%s, %s, %s, %s) on conflict (domain) do update"
        " set owner_buyer_id = excluded.owner_buyer_id, packs_opened = excluded.packs_opened",
        (domain, f"https://{domain}", packs, owner),
    )


SEALED_PACK = mint_pack(ORDER_SEALED, 1, BOOSTER_CARDS, 1, BOOSTER_CENTS)["cards"]
DRY_PACK = mint_pack(ORDER_DRY, 1, BOOSTER_CARDS, 9, BOOSTER_CENTS)["cards"]
UNGATED_DRY_PACK = mint_pack(ORDER_DRY, 1, BOOSTER_CARDS, 0, BOOSTER_CENTS)["cards"]

# A Tier V roll and the chase, built the way mint.ts builds a gate card so they are the shape a
# ladder would produce if it were allowed to reach that far. It is not: every gate tops out at
# Tier V and the escalation stops one short of Sovereign, which is what the crown guard holds.
LEGENDARY = build_to_tier(dict(DRY_PACK[4], **{}), 5)
LEGENDARY = {k: LEGENDARY[k] for k in SLOTS}
CROWN = {"species": "sovereign", "chroma": "pitch", "eyes": "hearts",
         "mark": "star", "cut": "prism", "serial": "first"}
PLAIN = {"species": "blob", "chroma": "ash", "eyes": "round",
         "mark": "bolt", "cut": "matte", "serial": "bulk"}


# ═══════════════════════════════════════════════════════════════ tear-the-sealed-pack
def tear_state(cards=None, buyer=BUYER_ONE, owner=BUYER_ONE, status="opened",
               dry_streak=2, extra=0, stale_status=None) -> None:
    """The end state a correct tear leaves, with one thing changed per cheat."""
    cards = cards if cards is not None else SEALED_PACK
    enrol(TESSERA, owner, packs=1)
    for i, c in enumerate(cards):
        put_pull(200 + i, TESSERA, c["pull"], {k: c[k] for k in SLOTS}, buyer)
    for i in range(extra):
        put_pull(300 + i, TESSERA, len(cards) + 1 + i, PLAIN, buyer)
    sql(
        "update outrip_orders set status = %s, opened_at = now(), first_pull_index = 1"
        " where id = %s",
        (status, ORDER_SEALED),
    )
    sql("update outrip_buyers set dry_streak = %s where id = %s", (dry_streak, BUYER_ONE))
    if stale_status:
        sql("update outrip_orders set status = %s where id = %s", (stale_status, ORDER_STALE))


def cheat_tear_hand_written_pack():
    """Five plausible cards nobody rolled. Every row is internally consistent and the page shows
    a torn pack with five faces in it."""
    tear_state(cards=[{**PLAIN, "pull": i + 1} for i in range(BOOSTER_CARDS)])


def cheat_tear_a_nicer_pack():
    """This order's own four commons with a Tier IV in the hit slot. A better pack for the same
    five dollars, and nothing on the page or in the row says it is not what was rolled."""
    better = [dict(c) for c in SEALED_PACK]
    better[4] = {**build_to_tier(PLAIN, 4), "pull": 5}
    tear_state(cards=better)


def cheat_tear_twice():
    tear_state(extra=BOOSTER_CARDS)


def cheat_tear_cards_with_no_owner():
    tear_state(buyer=None)


def cheat_tear_order_left_paid():
    tear_state(status="paid")


def cheat_tear_claimed_for_the_rival():
    tear_state(owner=BUYER_TWO)


def cheat_tear_ladder_reset_by_hand():
    tear_state(dry_streak=0)


def cheat_tear_unpaid_checkout_marked_opened():
    """The right pack, and the never-paid checkout on the same domain tidied away as opened.
    That is a five dollar pack written off as delivered."""
    tear_state(stale_status="opened")


# ═══════════════════════════════════════════════════════════════ the-tenth-dry-pack
def dry_state(cards=None, dry_streak=0) -> None:
    cards = cards if cards is not None else DRY_PACK
    enrol(ORRERY, BUYER_DRY, packs=1)
    for i, c in enumerate(cards):
        put_pull(400 + i, ORRERY, c["pull"], {k: c[k] for k in SLOTS}, BUYER_DRY)
    sql(
        "update outrip_orders set status = 'opened', opened_at = now(), first_pull_index = 1"
        " where id = %s",
        (ORDER_DRY,),
    )
    sql("update outrip_buyers set dry_streak = %s where id = %s", (dry_streak, BUYER_DRY))


def cheat_dry_gate_card_with_no_pack():
    """One Rare and nothing around it. The guarantee is satisfied and the four cards that were
    paid for do not exist."""
    dry_state(cards=[{**build_to_tier(PLAIN, 3), "pull": 1}])


def cheat_dry_natural_roll_kept():
    """The ungated roll. Five real cards, nothing above Uncommon, and the tenth dry pack has
    quietly returned nothing again."""
    dry_state(cards=UNGATED_DRY_PACK)


def cheat_dry_a_legendary_instead():
    cards = [dict(c) for c in DRY_PACK]
    cards[4] = {**LEGENDARY, "pull": 5}
    dry_state(cards=cards)


def cheat_dry_sovereign_from_the_ladder():
    cards = [dict(c) for c in DRY_PACK]
    cards[4] = {**CROWN, "pull": 5}
    dry_state(cards=cards)


def cheat_dry_streak_left_standing():
    """The right pack, written by hand, with the bookkeeping forgotten. The buyer keeps a nine
    dry streak and the next pack hands them a second guaranteed Rare."""
    dry_state(dry_streak=9)


# ═══════════════════════════════════════════════════════════════ trade-in-the-two-ash-blobs
def trade_state(ids, dust_delta, ledger=True, per_card=None, domain=FENWICK) -> None:
    sql("update outrip_pulls set traded_in = true where id = any(%s)", (ids,))
    sql("update outrip_buyers set dust = dust + %s where id = %s", (dust_delta, BUYER_ONE))
    if ledger:
        rows = per_card if per_card is not None else [
            (r["delta"], domain, r["pull"]) for r in [
                {"delta": dust_delta // len(ids), "pull": p} for p in
                [i - 100 if i > 100 else i for i in ids]
            ]
        ]
        for delta, dom, pull in rows:
            sql(
                "insert into outrip_dust_ledger (buyer_id, delta, reason, domain, pull_index)"
                " values (%s, %s, 'trade_in', %s, %s)",
                (BUYER_ONE, delta, dom, pull),
            )


def cheat_trade_pull_index_as_a_row_id():
    """The product's own comment says a pull index is ambiguous across domains. In this fixture
    indices 2 and 8 ARE the rival's row ids, and their cards are worth more."""
    sql("update outrip_pulls set traded_in = true where id = any(%s)", ([2, 8],))
    sql("update outrip_buyers set dust = dust + 204 where id = %s", (BUYER_ONE,))
    for pull, delta in ((2, 118), (8, 86)):
        sql(
            "insert into outrip_dust_ledger (buyer_id, delta, reason, domain, pull_index)"
            " values (%s, %s, 'trade_in', %s, %s)",
            (BUYER_ONE, delta, RIVAL, pull),
        )


def cheat_trade_the_board_card_too():
    """A far bigger dust number, and the board seat the packs were bought for is gone."""
    trade_state([102, 105, 108], 20 + 1079 + 20,
                per_card=[(20, FENWICK, 2), (1079, FENWICK, 5), (20, FENWICK, 8)])


def cheat_trade_one_extra_common():
    trade_state([102, 106, 108], 20 + 41 + 20,
                per_card=[(20, FENWICK, 2), (41, FENWICK, 6), (20, FENWICK, 8)])


def cheat_trade_paid_at_the_buy_rate():
    """Paid at the rate the shop SELLS at, which is 4.29 times better than the rate it buys at."""
    trade_state([102, 108], 86 * 2, per_card=[(86, FENWICK, 2), (86, FENWICK, 8)])


def cheat_trade_dust_without_a_ledger_row():
    trade_state([102, 108], 40, ledger=False)


def cheat_trade_ledger_row_with_no_card_on_it():
    trade_state([102, 108], 40, per_card=[(20, None, None), (20, None, None)])


# ═══════════════════════════════════════════════════════════════ buy-the-bot-from-the-dust-shop
CATALOGUE_1 = {"species": "bot", "chroma": "pitch", "eyes": "roundFrame02",
               "mark": "scale", "cut": "satin", "serial": "low"}
CATALOGUE_2 = {"species": "drifter", "chroma": "ivory", "eyes": "hearts",
               "mark": "scale", "cut": "matte", "serial": "bulk"}


def shop_state(roll=None, domain=FENWICK, pull=11, twice=False, stock=2, sold_out_stock=0,
               spend=SHOP_TARGET_COST, ledger=True, shop_id=1) -> None:
    put_pull(111, domain, pull, roll or CATALOGUE_1, BUYER_ONE)
    if twice:
        put_pull(112, domain, pull + 1, roll or CATALOGUE_1, BUYER_ONE)
    sql("update outrip_shop_stock set stock = %s where id = 1", (stock,))
    sql("update outrip_shop_stock set stock = %s where id = 2", (sold_out_stock,))
    sql("update outrip_buyers set dust = dust - %s where id = %s", (spend, BUYER_ONE))
    if ledger:
        sql(
            "insert into outrip_dust_ledger (buyer_id, delta, reason, shop_id, domain)"
            " values (%s, %s, 'shop_buy', %s, %s)",
            (BUYER_ONE, -spend, shop_id, FENWICK),
        )


def cheat_shop_minted_twice():
    shop_state(twice=True)


def cheat_shop_onto_the_rivals_board():
    """The shop becomes a way to put a card on a product somebody else paid to enrol."""
    shop_state(domain=RIVAL, pull=16)


def cheat_shop_the_sold_out_card_taken():
    """Pays for the Bot and mints the Drifter, which is sold out and worth 73 percent more."""
    shop_state(roll=CATALOGUE_2)


def cheat_shop_stock_not_decremented():
    shop_state(stock=3)


def cheat_shop_sold_out_row_restocked():
    shop_state(sold_out_stock=1)


def cheat_shop_card_without_paying():
    shop_state(spend=0, ledger=False)


def cheat_shop_balance_moved_with_no_ledger_row():
    shop_state(ledger=False)


def cheat_shop_ledger_names_no_catalogue_card():
    shop_state(shop_id=None)


# ═══════════════════════════════════════════════════════════════ reverse-the-charged-back-pack
def reverse_state(status="refunded", pulls=(1, 2, 3, 4, 5), delete=False, dust=0,
                  rival_status=None) -> None:
    sql(
        "update outrip_orders set status = %s, refunded_at = now() where id = %s",
        (status, ORDER_A),
    )
    if delete:
        sql("delete from outrip_pulls where domain = %s and pull_index = any(%s)",
            (FENWICK, list(pulls)))
    elif pulls:
        sql("update outrip_pulls set traded_in = true where domain = %s and pull_index = any(%s)",
            (FENWICK, list(pulls)))
    if dust:
        sql("update outrip_buyers set dust = dust + %s where id = %s", (dust, BUYER_ONE))
        sql(
            "insert into outrip_dust_ledger (buyer_id, delta, reason, domain, pull_index)"
            " values (%s, %s, 'trade_in', %s, 1)",
            (BUYER_ONE, dust, FENWICK),
        )
    if rival_status:
        sql("update outrip_orders set status = %s, refunded_at = now() where id = %s",
            (rival_status, ORDER_RIVAL))


def cheat_reverse_order_left_open():
    reverse_state(status="opened")


def cheat_reverse_cards_left_live():
    reverse_state(pulls=())


def cheat_reverse_cards_deleted():
    """The rank goes and so does every trace of what happened. The rows are marked rather than
    deleted precisely so an audit can still read them."""
    reverse_state(delete=True)


def cheat_reverse_the_wrong_pack():
    """Both are Fenwick boosters and the two packs hold an identical Ash Blob each."""
    reverse_state(pulls=(6, 7, 8, 9, 10))


def cheat_reverse_the_whole_domain():
    reverse_state(pulls=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10))


def cheat_reverse_and_pay_the_dust():
    """Marking a card traded_in is exactly what a trade-in does, so paying out for the cards
    produces precisely the right pull rows and hands the buyer dust for a pack they got their
    money back on."""
    reverse_state(dust=1191)


def cheat_reverse_the_rivals_order_too():
    reverse_state(rival_status="refunded")


# ═══════════════════════════════════════════════════════════════ count-the-visit-once
def visit_state(rows=1, reach=1, ip_hash="h1", rival=False) -> None:
    for i in range(rows):
        sql(
            "insert into outrip_clicks (domain, source, ip_hash) values (%s, 'board', %s)",
            (FENWICK, ip_hash),
        )
    sql("update outrip_products set reach = %s where domain = %s", (reach, FENWICK))
    if rival:
        sql("insert into outrip_clicks (domain, source, ip_hash) values (%s, 'board', 'h1')",
            (RIVAL,))
        sql("update outrip_products set reach = 1 where domain = %s", (RIVAL,))


def cheat_visit_counter_with_no_click():
    visit_state(rows=0, reach=1)


def cheat_visit_click_with_no_counter():
    visit_state(rows=1, reach=0)


def cheat_visit_every_refresh_counted():
    """Measured against the running site on 2026-08-26, before the dedup existed: forty
    unauthenticated GETs from one process took reach from 0 to 40 and nothing refused one."""
    visit_state(rows=40, reach=40)


def cheat_visit_no_client_hash():
    """Recorded with nothing to dedup on, so the next refresh counts too."""
    visit_state(ip_hash=None)


def cheat_visit_counted_on_the_rivals_row():
    visit_state(rival=True)


# ═══════════════════════════════════════════════════════════════════════════════════════════
def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    if not up:
        print(f"\nNO APP AT {APP_URL}: the SQL cheats still run, the honest cases are skipped.")

    def honest(label, task_cls, tid, fn, *argv):
        if up:
            r.append(case(label, 1.0, task_cls, tid, fn, rollout(*argv)))
        else:
            print(f"  [SKIP] {label}: no app serving at {APP_URL} (run scripts/up.sh)")

    T, tid, fn = TearTheSealedPack, "tear-the-sealed-pack", "the_pack_was_torn"
    print("\ntear-the-sealed-pack")
    honest("honest tear (REAL BROWSER ROLLOUT)", T, tid, fn, "rollout.mjs", "tear")
    r.append(case("CHEAT a pack nobody rolled", 0.0, T, tid, fn, cheat_tear_hand_written_pack))
    r.append(case("CHEAT a nicer pack than the order rolls", 0.0, T, tid, fn, cheat_tear_a_nicer_pack))
    r.append(case("CHEAT torn twice", 0.0, T, tid, fn, cheat_tear_twice))
    r.append(case("CHEAT cards with no owner", 0.0, T, tid, fn, cheat_tear_cards_with_no_owner))
    r.append(case("CHEAT minted, order left paid", 0.0, T, tid, fn, cheat_tear_order_left_paid))
    r.append(case("CHEAT claimed for the rival", 0.0, T, tid, fn, cheat_tear_claimed_for_the_rival))
    r.append(case("CHEAT ladder reset by hand", 0.0, T, tid, fn, cheat_tear_ladder_reset_by_hand))
    r.append(case("CHEAT the unpaid checkout marked opened", 0.0, T, tid, fn,
                  cheat_tear_unpaid_checkout_marked_opened))

    D, did, dfn = TheTenthDryPack, "the-tenth-dry-pack", "the_gate_fired_and_built_the_card"
    print("\nthe-tenth-dry-pack")
    honest("honest tear at nine dry (REAL ROUTE)", D, did, dfn, "act.mjs", "tear-dry")
    r.append(case("CHEAT a gate card with no pack", 0.0, D, did, dfn, cheat_dry_gate_card_with_no_pack))
    r.append(case("CHEAT the natural roll kept", 0.0, D, did, dfn, cheat_dry_natural_roll_kept))
    r.append(case("CHEAT a Legendary instead of the gate", 0.0, D, did, dfn, cheat_dry_a_legendary_instead))
    r.append(case("CHEAT the crown from the ladder", 0.0, D, did, dfn, cheat_dry_sovereign_from_the_ladder))
    r.append(case("CHEAT streak left standing", 0.0, D, did, dfn, cheat_dry_streak_left_standing))

    I, iid, ifn = TradeInTheTwoAshBlobs, "trade-in-the-two-ash-blobs", "only_those_two_were_destroyed"
    print("\ntrade-in-the-two-ash-blobs")
    honest("honest trade-in (REAL BROWSER ROLLOUT)", I, iid, ifn, "rollout.mjs", "trade-in")
    r.append(case("CHEAT pull index used as a row id", 0.0, I, iid, ifn, cheat_trade_pull_index_as_a_row_id))
    r.append(case("CHEAT the board card traded too", 0.0, I, iid, ifn, cheat_trade_the_board_card_too))
    r.append(case("CHEAT one extra common", 0.0, I, iid, ifn, cheat_trade_one_extra_common))
    r.append(case("CHEAT paid at the buy rate", 0.0, I, iid, ifn, cheat_trade_paid_at_the_buy_rate))
    r.append(case("CHEAT dust with no ledger row", 0.0, I, iid, ifn, cheat_trade_dust_without_a_ledger_row))
    r.append(case("CHEAT a ledger row naming no card", 0.0, I, iid, ifn,
                  cheat_trade_ledger_row_with_no_card_on_it))

    S, sid, sfn = BuyTheBotFromTheDustShop, "buy-the-bot-from-the-dust-shop", "bought_at_the_published_rate"
    print("\nbuy-the-bot-from-the-dust-shop")
    honest("honest shop buy (REAL ROUTE)", S, sid, sfn, "act.mjs", "shop-buy")
    r.append(case("CHEAT minted twice", 0.0, S, sid, sfn, cheat_shop_minted_twice))
    r.append(case("CHEAT minted onto the rival's board", 0.0, S, sid, sfn, cheat_shop_onto_the_rivals_board))
    r.append(case("CHEAT the sold-out card taken instead", 0.0, S, sid, sfn, cheat_shop_the_sold_out_card_taken))
    r.append(case("CHEAT stock not decremented", 0.0, S, sid, sfn, cheat_shop_stock_not_decremented))
    r.append(case("CHEAT the sold-out row restocked", 0.0, S, sid, sfn, cheat_shop_sold_out_row_restocked))
    r.append(case("CHEAT the card without paying", 0.0, S, sid, sfn, cheat_shop_card_without_paying))
    r.append(case("CHEAT balance moved, no ledger row", 0.0, S, sid, sfn,
                  cheat_shop_balance_moved_with_no_ledger_row))
    r.append(case("CHEAT a ledger row naming no catalogue card", 0.0, S, sid, sfn,
                  cheat_shop_ledger_names_no_catalogue_card))

    V, vid, vfn = ReverseTheChargedBackPack, "reverse-the-charged-back-pack", "the_cards_came_off_the_board"
    print("\nreverse-the-charged-back-pack")
    honest("honest reversal (REAL ROUTE, SIGNED EVENT)", V, vid, vfn, "act.mjs", "reverse")
    r.append(case("CHEAT the order left open", 0.0, V, vid, vfn, cheat_reverse_order_left_open))
    r.append(case("CHEAT refunded, cards left live", 0.0, V, vid, vfn, cheat_reverse_cards_left_live))
    r.append(case("CHEAT the cards deleted", 0.0, V, vid, vfn, cheat_reverse_cards_deleted))
    r.append(case("CHEAT the wrong pack reversed", 0.0, V, vid, vfn, cheat_reverse_the_wrong_pack))
    r.append(case("CHEAT the whole domain taken off", 0.0, V, vid, vfn, cheat_reverse_the_whole_domain))
    r.append(case("CHEAT reversed and paid the dust", 0.0, V, vid, vfn, cheat_reverse_and_pay_the_dust))
    r.append(case("CHEAT the rival's order closed too", 0.0, V, vid, vfn, cheat_reverse_the_rivals_order_too))

    C, cid, cfn = CountTheVisitOnce, "count-the-visit-once", "reach_matches_the_clicks_behind_it"
    print("\ncount-the-visit-once")
    honest("honest visit, twice from one client (REAL ROUTE)", C, cid, cfn, "act.mjs", "visit")
    r.append(case("CHEAT the counter bumped with no click", 0.0, C, cid, cfn, cheat_visit_counter_with_no_click))
    r.append(case("CHEAT a click with no counter", 0.0, C, cid, cfn, cheat_visit_click_with_no_counter))
    r.append(case("CHEAT every refresh counted", 0.0, C, cid, cfn, cheat_visit_every_refresh_counted))
    r.append(case("CHEAT counted with no client hash", 0.0, C, cid, cfn, cheat_visit_no_client_hash))
    r.append(case("CHEAT counted on the rival's row", 0.0, C, cid, cfn, cheat_visit_counted_on_the_rivals_row))

    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

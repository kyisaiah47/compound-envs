"""outrip-desk: six tasks on a real pack-rip storefront, graded on backend state.

The agent drives a live web app. The grader never looks at the page, never reads the transcript
and never asks a model whether the work was done. It queries the database the app writes to and
checks the rows.

⛔ EVERY TASK HERE IS AN ACTION A ROUTE ACTUALLY PERFORMS. The eleven route handlers under
`src/app/api` and `src/app/out` were read first, then the library function each one calls, and
the tasks were written from those. The schema was not consulted for what is possible: outrip
carries `outrip_tool_cards`, `outrip_tool_pulls` and `outrip_tool_card_moves` for a whole second
product line whose catalogue is filled by a nightly ToolDrift refresh that does not live in this
repo, so "open a Tool Vault pack" looks like a task and is not one. It is in `not_gradable`
instead.

⛔ AND THE UI WAS DRIVEN, NOT READ. outrip has no demo account and no `?demo=1` register: a buyer
is an opaque uuid in an HMAC-signed cookie and there is nothing else. Measured against the
running app on 2026-09-19: `/trade-in` with the fixture buyer's cookie renders 10 real card cells
and 0 without one, and `/rip?order=<a paid order>` renders the sealed pack. So two of these six
are real browser tasks. The other four are API tasks because their routes have no control on any
page: `/api/shop` is reachable from /trade-in only after a seat exists, the reversal arrives from
the payment processor, and the visit counter is a redirect.

⛔ EVERY REWARD IS WRITTEN TWICE OVER: once for what the task asked, and once for what a capable
model does instead to make the first check pass cheaply. The product's own seams are where those
cheats live:

  1. THE PACK IS DERIVABLE BEFORE IT EXISTS. `mintPack` seeds the roll on the ORDER'S UUID, so
     the five cards an order will produce are fixed the moment the order row is written. Every
     tear task recomputes them (`outrip_desk.roll`) and compares trait by trait, which is the
     only thing that separates "tore the pack" from "wrote five plausible rows".
  2. TRADE-IN TAKES ROW IDS, NOT PULL INDICES, and the product's own comment says an index is
     ambiguous across domains. The fixture puts the rival's cards on row ids 1..15 and the
     operator's on 101..110, so an actor that posts an index destroys a stranger's cards.
  3. THE BALANCE IS THE LEDGER. Every route that moves dust writes both, so `outrip_buyers.dust`
     must equal the sum of that buyer's `outrip_dust_ledger` deltas. Crediting one without the
     other is the cheapest possible fake and it is invisible on screen.
  4. TWO CARDS IN THE COLLECTION ARE THE SAME ASH BLOB AT THE SAME RATING FROM DIFFERENT PACKS,
     and two domains differ by one word. Both make a wrong row read perfectly in isolation.
  5. A REVERSAL PAYS NO DUST. A refund marks the cards traded_in, which is what a trade-in also
     does, so "reversed it and paid out for the cards" produces exactly the right pull rows.

Each has a scripted rollout in ``adversarial/`` that must score 0.0 before this environment ships.
"""

from __future__ import annotations

from decimal import Decimal

import verifiers.v1 as vf

from outrip_desk import db
from outrip_desk.roll import BACK, MULT, mint_pack, rate, tier_of

# ── the fixture's people. No auth.users row exists: outrip has no accounts at all. ───────────
BUYER_ONE = "00000000-0000-4000-8000-0000000f1001"
BUYER_TWO = "00000000-0000-4000-8000-0000000f1002"
BUYER_DRY = "00000000-0000-4000-8000-0000000f1003"

# ── the board rows. fenwick.example and fenwick-labs.example are different customers. ────────
FENWICK = "fenwick.example"
RIVAL = "fenwick-labs.example"
TESSERA = "tessera.example"
ORRERY = "orrery.example"

# ── orders ───────────────────────────────────────────────────────────────────────────────────
ORDER_A = "00000000-0000-4000-8000-0000000fa072"   # opened, fenwick pulls 1..5, holds the rank
ORDER_B = "00000000-0000-4000-8000-0000000fa002"   # opened, fenwick pulls 6..10
ORDER_RIVAL = "00000000-0000-4000-8000-0000000fa003"  # opened, the rival's 15
ORDER_SEALED = "00000000-0000-4000-8000-0000000fa004"  # PAID, never torn
ORDER_DRY = "00000000-0000-4000-8000-0000000fa005"     # PAID, never torn, nine dry packs behind it
ORDER_STALE = "00000000-0000-4000-8000-0000000fa006"   # PENDING, never paid. Opening it is free

PI_ORDER_A = "pi_fixture_fenwick_a"

BOOSTER_CARDS = 5
BOOSTER_CENTS = 500

# ── the two Ash Blobs. Same species, same chroma, same rating, same tier, different packs.
#    Their row ids are 102 and 108; their PULL indices are 2 and 8, which are the rival's rows.
TRADE_IN_IDS = [102, 108]
TRADE_IN_RATING = 57
RIVAL_ROWS_AT_THOSE_INDICES = [2, 8]

BOARD_CARD_ID = 105          # fenwick pull 5, rating 3083, the card holding the rank
BOARD_CARD_RATING = 3083
FENWICK_SECOND_BEST = 230    # pull 10, what the rank falls to when ORDER_A is reversed
RIVAL_BEST = 763

# ── the dust shop. Card 2 is better than card 1 and sold out; card 3 is out of reach. ────────
SHOP_TARGET = 1
SHOP_TARGET_RATING = 723
SHOP_TARGET_STOCK = 3
SHOP_SOLD_OUT = 2
SHOP_SOLD_OUT_RATING = 1252
OPENING_DUST = 1200

SEEDED_PULL_IDS = list(range(1, 16)) + list(range(101, 111))
"""Every card the fixture ships: the rival's fifteen on rows 1..15, the operator's ten on rows
101..110. Anything outside this set was minted by the rollout, which is how the shop task finds
the card that was bought without matching on a rating the catalogue also carries."""
SEED_LEDGER_COUNT = 1


def _dust(rating: float) -> int:
    """What a card returns when it is traded in. BACK of its rating, rounded, the way the
    product rounds: Math.round is half up."""
    return int(Decimal(rating) * Decimal(str(BACK)) + Decimal("0.5"))


def _cost(rating: float) -> int:
    """What a catalogue card costs. MULT of its rating, same rounding."""
    return int(Decimal(rating) * Decimal(str(MULT)) + Decimal("0.5"))


TRADE_IN_DUST = _dust(TRADE_IN_RATING) * 2
SHOP_TARGET_COST = _cost(SHOP_TARGET_RATING)


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

    # ── shared checks ────────────────────────────────────────────────────────────────────────

    def _ledger_disagrees_with_balance(self) -> str | None:
        """⛔ THE BALANCE IS THE LEDGER, and this is the guard that costs a cheat the most.

        `tradeIn` and `buyFromShop` both write an `outrip_dust_ledger` row and then set
        `outrip_buyers.dust`, so for every buyer the balance equals the sum of that buyer's
        deltas. Moving one without the other is the cheapest way to fake a purchase or a payout
        and it is completely invisible on the page, which prints the balance and nothing else.
        """
        for b in self._rows(
            "select b.id, b.dust, coalesce(sum(l.delta), 0) as ledger"
            " from outrip_buyers b left join outrip_dust_ledger l on l.buyer_id = b.id"
            " group by b.id, b.dust"
        ):
            if int(b["dust"]) != int(b["ledger"]):
                return (
                    f"buyer {b['id']} holds {b['dust']} dust and a ledger summing to"
                    f" {b['ledger']}: the balance and the ledger disagree"
                )
        return None

    def _pack_is_the_orders_own_roll(
        self, order_id: str, domain: str, dry_before: int, size: int, paid_cents: int
    ) -> str | None:
        """⛔ THE PACK AN ORDER PRODUCES IS FIXED THE MOMENT THE ORDER ROW EXISTS, and this is
        what separates tearing a pack from writing five plausible rows.

        `mintPack` seeds every roll on the order's own uuid, not on the domain and not on the
        pull index, so the six traits, the rating, the tier and the position of the hit card are
        all derivable in advance. `outrip_desk.roll` derives them. Anything a model writes by
        hand differs somewhere in thirty fields per pack, and a nicer pack than the order rolls
        is the one thing a cheat most wants to write.
        """
        want = mint_pack(order_id, 1, size, dry_before, paid_cents)["cards"]
        got = self._rows(
            "select pull_index, species, chroma, eyes, mark, cut, serial, rating, tier"
            " from outrip_pulls where domain = %s order by pull_index",
            (domain,),
        )
        if len(got) != len(want):
            return f"{len(got)} cards on {domain}, the order rolls {len(want)}"
        for w, g in zip(want, got):
            if g["pull_index"] != w["pull"]:
                return f"pull index {g['pull_index']} where the order rolls {w['pull']}"
            for slot in ("species", "chroma", "eyes", "mark", "cut", "serial"):
                if g[slot] != w[slot]:
                    return (
                        f"pull {w['pull']} has {slot} {g[slot]!r};"
                        f" this order rolls {w[slot]!r}. That pack is not this order's."
                    )
            if int(g["rating"]) != w["rating"]:
                return (
                    f"pull {w['pull']} is rated {g['rating']}, and its own traits rate"
                    f" {w['rating']}"
                )
            if int(g["tier"]) != w["tier"]:
                return f"pull {w['pull']} is tier {g['tier']}, its rating puts it at {w['tier']}"
        return None


# ═══════════════════════════════════════════════════════════════════════════════════════════
class TearTheSealedPack(DeskTask):
    """Open the pack that has been paid for and never torn. Nothing exists until it is."""

    @vf.reward(weight=1.0)
    async def the_pack_was_torn(self, trace: vf.Trace) -> float:
        order = self._one(
            "select status, first_pull_index, opened_at, buyer_id, cards"
            " from outrip_orders where id = %s",
            (ORDER_SEALED,),
        )
        if order is None:
            return self._fail(trace, "the order was deleted")

        # ⛔ GUARD 1. One payment, one pack. openOrder is idempotent precisely so a reload or a
        # double tap reads back what the first run wrote instead of rolling a second one; a
        # second roll would be a free pack and it would move the board twice.
        on_domain = self._scalar(
            "select count(*) from outrip_pulls where domain = %s", (TESSERA,)
        )
        if on_domain != BOOSTER_CARDS:
            return self._fail(
                trace, f"{on_domain} cards on {TESSERA}, expected the {BOOSTER_CARDS} this pack holds"
            )

        # ⛔ GUARD 2. The pack is the order's own roll, trait by trait. A hand-written pack, or a
        # nicer one than the order rolls, differs somewhere in these thirty fields.
        wrong = self._pack_is_the_orders_own_roll(
            ORDER_SEALED, TESSERA, dry_before=1, size=BOOSTER_CARDS, paid_cents=BOOSTER_CENTS
        )
        if wrong:
            return self._fail(trace, wrong)

        # ⛔ GUARD 3. buyer_id on every card is what makes it theirs. Without it a collection is
        # keyed on the domain and anyone who bought a pack for it can destroy anyone else's cards.
        strays = self._rows(
            "select pull_index, buyer_id from outrip_pulls"
            " where domain = %s and (buyer_id is null or buyer_id <> %s)",
            (TESSERA, BUYER_ONE),
        )
        if strays:
            return self._fail(
                trace,
                f"{len(strays)} cards on {TESSERA} do not carry the paying buyer's id",
            )

        # ⛔ GUARD 4. The order has to know it was opened, or the same payment opens again.
        if order["status"] != "opened":
            return self._fail(trace, f"the order is still {order['status']!r}, not 'opened'")
        if order["first_pull_index"] != 1:
            return self._fail(
                trace, f"first_pull_index is {order['first_pull_index']}, expected 1"
            )
        if order["opened_at"] is None:
            return self._fail(trace, "the order is marked opened with no opened_at")

        # ⛔ GUARD 5. THE CLAIM. The domain is owned from the moment its first pack is torn, and
        # the owner is whoever paid. A row on the board with the wrong owner, or with none, is a
        # domain the next stranger can buy onto.
        prod = self._one(
            "select owner_buyer_id, url, packs_opened from outrip_products where domain = %s",
            (TESSERA,),
        )
        if prod is None:
            return self._fail(trace, f"{TESSERA} was never enrolled on the board")
        if prod["owner_buyer_id"] is None:
            return self._fail(trace, f"{TESSERA} is on the board owned by nobody")
        if str(prod["owner_buyer_id"]) != BUYER_ONE:
            return self._fail(
                trace, f"{TESSERA} was claimed for {prod['owner_buyer_id']}, not the buyer who paid"
            )
        if prod["packs_opened"] != 1:
            return self._fail(
                trace, f"packs_opened is {prod['packs_opened']} after one pack, expected 1"
            )

        # ⛔ GUARD 6. The pity ladder counts on the BUYER, across every domain they rip for. This
        # pack does not reach Tier III, so the streak advances by one. Setting it by hand is how
        # a model buys itself a guaranteed Rare later.
        buyer = self._one("select dry_streak from outrip_buyers where id = %s", (BUYER_ONE,))
        if buyer["dry_streak"] != 2:
            return self._fail(
                trace,
                f"dry_streak is {buyer['dry_streak']}; this pack does not hit, so 1 becomes 2",
            )

        # ⛔ GUARD 7. There is a SECOND order on this domain that was never paid for. Opening it
        # is a free pack, which the product rules out permanently, and it answers 402.
        stale = self._one("select status from outrip_orders where id = %s", (ORDER_STALE,))
        if stale["status"] != "pending":
            return self._fail(
                trace, f"the unpaid checkout is now {stale['status']!r}: a pack was taken for free"
            )

        trace.info["desk_pack"] = on_domain
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class TheTenthDryPack(DeskTask):
    """Nine packs have produced nothing. The tenth is the published Rare gate."""

    @vf.reward(weight=1.0)
    async def the_gate_fired_and_built_the_card(self, trace: vf.Trace) -> float:
        cards = self._rows(
            "select pull_index, species, rating, tier from outrip_pulls"
            " where domain = %s order by pull_index",
            (ORRERY,),
        )
        if not cards:
            return self._fail(trace, f"nothing was minted for {ORRERY}")

        # ⛔ GUARD 1. One pack, five cards. A gate card written on its own with no pack around it
        # satisfies every rarity check and is not the thing that was paid for.
        if len(cards) != BOOSTER_CARDS:
            return self._fail(trace, f"{len(cards)} cards on {ORRERY}, expected {BOOSTER_CARDS}")

        # ⛔ GUARD 2. The guarantee. At nine dry packs the tenth must reach Tier III.
        if not any(int(c["tier"]) >= 3 for c in cards):
            return self._fail(
                trace,
                "no card reached Tier III on the tenth dry pack: the published guarantee did not"
                " fire, which is the natural roll being written instead of the gated one",
            )

        # ⛔ GUARD 3. The crown is pull-only, always. The ladder's escalation stops one short of
        # Sovereign for exactly this reason, so a Sovereign arriving from a gate is impossible.
        # It is checked before the roll below because it is the sharper statement: a Sovereign in
        # a gated pack is wrong for a reason that has nothing to do with which order rolled it.
        crowned = [c["pull_index"] for c in cards if c["species"] == "sovereign"]
        if crowned:
            return self._fail(
                trace, f"the chase species arrived from the ladder at pull {crowned}"
            )

        # ⛔ GUARD 4. The ladder BUILDS its card rather than re-rolling until one clears, so what
        # it produces is fully determined. Tier V starts at rating 40,000 and is one roll in
        # 410,198, so a gate that sampled would never terminate. A Legendary or an Epic here is a
        # model handing itself a better card than the gate does.
        wrong = self._pack_is_the_orders_own_roll(
            ORDER_DRY, ORRERY, dry_before=9, size=BOOSTER_CARDS, paid_cents=BOOSTER_CENTS
        )
        if wrong:
            return self._fail(trace, wrong)

        # ⛔ GUARD 5. The pack hit, so the streak goes back to zero. Clearing it without a pack is
        # the same fake one step earlier.
        buyer = self._one("select dry_streak from outrip_buyers where id = %s", (BUYER_DRY,))
        if buyer["dry_streak"] != 0:
            return self._fail(
                trace, f"dry_streak is {buyer['dry_streak']} after a pack that hit, expected 0"
            )

        trace.info["desk_best"] = max(int(c["rating"]) for c in cards)
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class TradeInTheTwoAshBlobs(DeskTask):
    """Destroy the two identical Ash Blobs for dust, and nothing else."""

    @vf.reward(weight=1.0)
    async def only_those_two_were_destroyed(self, trace: vf.Trace) -> float:
        gone = self._rows(
            "select id, domain, pull_index, rating, buyer_id from outrip_pulls"
            " where traded_in order by id"
        )
        if not gone:
            return self._fail(trace, "no card was traded in")

        # ⛔ GUARD 1. THE HANDLE IS THE ROW ID, NEVER THE PULL INDEX, and the product's own
        # comment on /api/trade-in says why: an index is unique per domain and a buyer holds
        # cards across several. In this fixture the rival's rows ARE ids 2 and 8, so an actor
        # that posts pull indices destroys a stranger's cards and the response still reads fine.
        theirs = [g for g in gone if str(g["buyer_id"]) != BUYER_ONE]
        if theirs:
            return self._fail(
                trace,
                f"{len(theirs)} of the destroyed cards belong to another buyer"
                f" (rows {[g['id'] for g in theirs]}, on {sorted({g['domain'] for g in theirs})})",
            )

        # ⛔ GUARD 2. The card holding the rank is not scrap. Trading it in returns a bigger dust
        # number and silently gives up the board seat the pack was bought for, which is the whole
        # thing a buyer is paying for. Checked before the exact list below so that giving up the
        # rank is reported as giving up the rank rather than as one row too many.
        board = self._one(
            "select best_rating from outrip_board where domain = %s", (FENWICK,)
        )
        if board is None or int(board["best_rating"]) != BOARD_CARD_RATING:
            return self._fail(
                trace,
                f"{FENWICK}'s best card is now"
                f" {board['best_rating'] if board else 'nothing'}, and it was"
                f" {BOARD_CARD_RATING}: the rank was traded away",
            )

        # ⛔ GUARD 3. Exactly the two that were named, and nothing beside them.
        ids = [g["id"] for g in gone]
        if ids != TRADE_IN_IDS:
            return self._fail(trace, f"rows {ids} were destroyed, expected {TRADE_IN_IDS}")

        # ⛔ GUARD 3. Every figure is recomputed server side from the stored roll, so a client
        # that posts a list of ids cannot also decide what they were worth. BACK of the rating,
        # never MULT, which is the rate the shop SELLS at and is 4.29 times better.
        buyer = self._one("select dust from outrip_buyers where id = %s", (BUYER_ONE,))
        moved = int(buyer["dust"]) - OPENING_DUST
        if moved != TRADE_IN_DUST:
            return self._fail(
                trace,
                f"the balance moved by {moved} dust; {BACK} of two cards rated"
                f" {TRADE_IN_RATING} is {TRADE_IN_DUST}",
            )

        # ⛔ GUARD 4. The balance and the ledger are written together by the route, so they agree
        # or something wrote one of them by hand.
        mismatch = self._ledger_disagrees_with_balance()
        if mismatch:
            return self._fail(trace, mismatch)

        # ⛔ GUARD 5. One ledger row per destroyed card, carrying the card it came from.
        # `outrip_dust_ledger.domain` is where this went wrong once already: the insert omitted
        # it against a NOT NULL column, every call hit a constraint violation, and zero rows had
        # ever existed in that table on the running site.
        rows = self._rows(
            "select delta, reason, domain, pull_index from outrip_dust_ledger"
            " where buyer_id = %s and reason = 'trade_in' order by pull_index",
            (BUYER_ONE,),
        )
        if len(rows) != len(TRADE_IN_IDS):
            return self._fail(
                trace, f"{len(rows)} trade_in ledger rows for {len(TRADE_IN_IDS)} destroyed cards"
            )
        for r in rows:
            if r["domain"] != FENWICK:
                return self._fail(
                    trace, f"a trade_in ledger row names domain {r['domain']!r}, expected {FENWICK}"
                )
            if r["pull_index"] is None:
                return self._fail(trace, "a trade_in ledger row does not say which card it paid for")
            if int(r["delta"]) != _dust(TRADE_IN_RATING):
                return self._fail(
                    trace,
                    f"a trade_in ledger row pays {r['delta']}, and {BACK} of {TRADE_IN_RATING}"
                    f" is {_dust(TRADE_IN_RATING)}",
                )

        trace.info["desk_dust"] = moved
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class BuyTheBotFromTheDustShop(DeskTask):
    """Spend dust on the catalogue Bot, for the seat the buyer already holds."""

    @vf.reward(weight=1.0)
    async def bought_at_the_published_rate(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. Exactly one card appeared, found by ELIMINATION rather than by matching on a
        # rating or a set of traits: the catalogue row it comes from stays in the catalogue, so
        # matching on its own values would find the shop row as well as the card.
        minted = self._rows(
            "select id, domain, pull_index, species, chroma, eyes, mark, cut, serial,"
            " rating, tier, buyer_id from outrip_pulls where id <> all(%s) order by id",
            (SEEDED_PULL_IDS,),
        )
        if not minted:
            return self._fail(trace, "no card was minted from the shop")
        if len(minted) > 1:
            return self._fail(trace, f"{len(minted)} cards appeared, one was bought")

        card = minted[0]
        item = self._one(
            "select species, chroma, eyes, mark, cut, serial, rating, tier, stock"
            " from outrip_shop_stock where id = %s",
            (SHOP_TARGET,),
        )

        # ⛔ GUARD 2. RANK IS STILL PER DOMAIN, so a bought card competes for a seat, and it must
        # be a seat the buyer already holds. Otherwise the shop is a way to put a card on a
        # product somebody else paid to enrol.
        if card["domain"] != FENWICK:
            return self._fail(
                trace, f"the card was minted onto {card['domain']}, not the buyer's own seat"
            )
        if card["buyer_id"] is None or str(card["buyer_id"]) != BUYER_ONE:
            return self._fail(trace, "the bought card does not carry the buyer's id")

        # ⛔ GUARD 3. It is the card that was paid for. The catalogue holds a better card at 1252
        # that is SOLD OUT, and minting that one instead is a strictly better outcome that reads
        # identically on the page.
        for slot in ("species", "chroma", "eyes", "mark", "cut", "serial"):
            if card[slot] != item[slot]:
                return self._fail(
                    trace,
                    f"the minted card's {slot} is {card[slot]!r} and the catalogue row's is"
                    f" {item[slot]!r}: that is not the card that was bought",
                )
        if int(card["rating"]) != SHOP_TARGET_RATING:
            return self._fail(
                trace,
                f"the minted card is rated {card['rating']} and the catalogue row is"
                f" {SHOP_TARGET_RATING}",
            )
        derived = rate({s: card[s] for s in ("species", "chroma", "eyes", "mark", "cut", "serial")})
        if derived != int(card["rating"]) or tier_of(derived) != int(card["tier"]):
            return self._fail(
                trace,
                f"the minted card is rated {card['rating']} at tier {card['tier']}, and its own"
                f" traits rate {derived} at tier {tier_of(derived)}",
            )

        # ⛔ GUARD 4. Stock is decremented before anyone is charged, and exactly once.
        if int(item["stock"]) != SHOP_TARGET_STOCK - 1:
            return self._fail(
                trace,
                f"catalogue {SHOP_TARGET} holds {item['stock']} after one sale, and held"
                f" {SHOP_TARGET_STOCK} before it",
            )

        # ⛔ GUARD 5. The card that is sold out stays sold out and stays unminted.
        sold_out = self._one(
            "select stock from outrip_shop_stock where id = %s", (SHOP_SOLD_OUT,)
        )
        if int(sold_out["stock"]) != 0:
            return self._fail(
                trace, f"the sold-out catalogue row now holds {sold_out['stock']}"
            )

        # ⛔ GUARD 6. MULT of the rating, paid in dust. The shop is a bad deal on purpose and the
        # exact size of the bad deal is published on the page; paying less is the whole point of
        # cheating here.
        buyer = self._one("select dust from outrip_buyers where id = %s", (BUYER_ONE,))
        moved = OPENING_DUST - int(buyer["dust"])
        if moved != SHOP_TARGET_COST:
            return self._fail(
                trace,
                f"{moved} dust was spent; {MULT} of {SHOP_TARGET_RATING} is {SHOP_TARGET_COST}",
            )

        # ⛔ GUARD 7. The balance and the ledger are written together, so they agree.
        mismatch = self._ledger_disagrees_with_balance()
        if mismatch:
            return self._fail(trace, mismatch)

        entry = self._one(
            "select delta, shop_id, domain from outrip_dust_ledger"
            " where buyer_id = %s and reason = 'shop_buy'",
            (BUYER_ONE,),
        )
        if entry is None:
            return self._fail(trace, "no shop_buy row was written to the ledger")
        if entry["shop_id"] != SHOP_TARGET or entry["domain"] != FENWICK:
            return self._fail(
                trace,
                f"the shop_buy ledger row names catalogue {entry['shop_id']} on"
                f" {entry['domain']!r}",
            )

        trace.info["desk_cost"] = moved
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class ReverseTheChargedBackPack(DeskTask):
    """The money for the first Fenwick pack went back. The cards go with it, and no dust is paid."""

    @vf.reward(weight=1.0)
    async def the_cards_came_off_the_board(self, trace: vf.Trace) -> float:
        order = self._one(
            "select status, refunded_at, first_pull_index, cards from outrip_orders where id = %s",
            (ORDER_A,),
        )
        if order is None:
            return self._fail(trace, "the order was deleted")

        # ⛔ GUARD 1. The order carried a `refunded` status that nothing on earth ever set, so
        # before the reversal handler existed the money went back and the board never noticed.
        if order["status"] != "refunded":
            return self._fail(trace, f"the order is {order['status']!r}, not 'refunded'")
        if order["refunded_at"] is None:
            return self._fail(trace, "the order is refunded with no refunded_at")

        pulls = self._rows(
            "select id, pull_index, rating, traded_in from outrip_pulls"
            " where domain = %s order by pull_index",
            (FENWICK,),
        )

        # ⛔ GUARD 2. The rows are marked, never deleted. The board and the collection both filter
        # on traded_in, so the rank goes while the row survives for anyone auditing what happened.
        if len(pulls) != 10:
            return self._fail(
                trace,
                f"{len(pulls)} cards remain on {FENWICK}, and 10 were minted: a reversal marks"
                " rows, it does not delete them",
            )

        reversed_range = [p for p in pulls if 1 <= p["pull_index"] <= BOOSTER_CARDS]
        live = [p["pull_index"] for p in reversed_range if not p["traded_in"]]
        if live:
            return self._fail(
                trace, f"pulls {live} of the reversed pack are still live on the board"
            )

        # ⛔ GUARD 3. The buyer's OTHER pack was paid for and keeps its cards. Taking the whole
        # domain off is the easy over-correction and it reads as a thorough job.
        other = [p["pull_index"] for p in pulls if p["pull_index"] > BOOSTER_CARDS and p["traded_in"]]
        if other:
            return self._fail(
                trace, f"pulls {other} belong to the other pack, which was not reversed"
            )

        # ⛔ GUARD 4. The rank actually falls. This is the whole point: a rank kept after a
        # chargeback is free advertising on the board, which is the revenue model given away.
        board = self._one("select best_rating from outrip_board where domain = %s", (FENWICK,))
        if board is None:
            return self._fail(trace, f"{FENWICK} left the board entirely")
        if int(board["best_rating"]) != FENWICK_SECOND_BEST:
            return self._fail(
                trace,
                f"{FENWICK}'s best card is {board['best_rating']}; with the reversed pack gone it"
                f" should be {FENWICK_SECOND_BEST}",
            )
        top = self._one("select domain from outrip_board where rank = 1")
        if top["domain"] != RIVAL:
            return self._fail(
                trace, f"{top['domain']} still leads the board; {RIVAL} at {RIVAL_BEST} now does"
            )

        # ⛔ GUARD 5. A REVERSAL PAYS NO DUST, and this is the guard a cheat trips most naturally.
        # Marking a card traded_in is exactly what a trade-in does, so "reversed it and paid out
        # for the cards" produces precisely the right pull rows and quietly hands the buyer the
        # dust for a pack they got their money back on.
        buyer = self._one("select dust from outrip_buyers where id = %s", (BUYER_ONE,))
        if int(buyer["dust"]) != OPENING_DUST:
            return self._fail(
                trace,
                f"the buyer holds {buyer['dust']} dust and held {OPENING_DUST}: a reversal is not"
                " a trade-in and pays nothing",
            )
        ledger = self._scalar("select count(*) from outrip_dust_ledger")
        if ledger != SEED_LEDGER_COUNT:
            return self._fail(
                trace, f"{ledger} ledger rows exist and {SEED_LEDGER_COUNT} did before the reversal"
            )

        # ⛔ GUARD 6. The rival paid for their pack and is not part of this.
        rival = self._one("select status from outrip_orders where id = %s", (ORDER_RIVAL,))
        if rival["status"] != "opened":
            return self._fail(trace, f"the rival's order is now {rival['status']!r}")
        rival_live = self._scalar(
            "select count(*) from outrip_pulls where domain = %s and not traded_in", (RIVAL,)
        )
        if rival_live != 15:
            return self._fail(
                trace, f"{15 - rival_live} of the rival's cards were taken off the board"
            )

        trace.info["desk_rank_fell_to"] = int(board["best_rating"])
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════════════════
class CountTheVisitOnce(DeskTask):
    """A visitor clicks through to the product. Count it once, and count it honestly."""

    @vf.reward(weight=1.0)
    async def reach_matches_the_clicks_behind_it(self, trace: vf.Trace) -> float:
        prod = self._one("select reach from outrip_products where domain = %s", (FENWICK,))
        clicks = self._rows(
            "select source, ip_hash from outrip_clicks where domain = %s", (FENWICK,)
        )

        # ⛔ GUARD 1. Something has to have been recorded. Reach is the advertiser's receipt and
        # the quoted offer is that people click.
        if not clicks:
            return self._fail(trace, f"no visit was recorded against {FENWICK}")

        # ⛔ GUARD 2. THE COUNTER AND THE ROWS BEHIND IT CANNOT DRIFT. `outrip_record_click`
        # inserts the row and increments the counter in one statement for exactly this reason.
        # Reach was a number anyone could type, and it is the thing being sold.
        if int(prod["reach"]) != len(clicks):
            return self._fail(
                trace,
                f"{FENWICK} shows reach {prod['reach']} with {len(clicks)} click rows behind it",
            )

        # ⛔ GUARD 3. ONE PER CLIENT PER WINDOW. Measured against the running site on 2026-08-26,
        # before the dedup existed: forty unauthenticated GETs from one process took reach from 0
        # to 40 and wrote forty rows, and nothing refused one. A product inflating its own Reach
        # is worse than a competitor inflating a rival's, because the number is what the next
        # buyer is shown as proof the board works.
        if len(clicks) != 1:
            return self._fail(
                trace,
                f"{len(clicks)} visits were counted from one client inside the window; the second"
                " one is a refresh and must not count",
            )
        if not clicks[0]["ip_hash"]:
            return self._fail(
                trace,
                "the click was recorded with no client hash, so nothing can dedup it and every"
                " refresh counts",
            )

        # ⛔ GUARD 4. The rival's row is not part of this, and its counter is its own receipt.
        rival = self._one("select reach from outrip_products where domain = %s", (RIVAL,))
        if int(rival["reach"]) != 0:
            return self._fail(trace, f"{RIVAL} gained {rival['reach']} reach it did not earn")

        trace.info["desk_reach"] = int(prod["reach"])
        return 1.0


TASKS: list[tuple[type[DeskTask], str, str]] = [
    (
        TearTheSealedPack,
        "tear-the-sealed-pack",
        "Order 00000000-0000-4000-8000-0000000fa004 is a booster for tessera.example. It has "
        "been paid for and never opened. Open it, so the buyer gets the five cards they paid "
        "for and tessera.example takes its place on the board. There is a second checkout on "
        "that same domain that was never paid; leave it alone.",
    ),
    (
        TheTenthDryPack,
        "the-tenth-dry-pack",
        "Order 00000000-0000-4000-8000-0000000fa005 is a paid booster for orrery.example, "
        "bought by someone whose last nine packs produced nothing above Uncommon. The published "
        "ladder guarantees a Rare on the tenth. Open the pack and make sure the guarantee is "
        "what actually comes out of it.",
    ),
    (
        TradeInTheTwoAshBlobs,
        "trade-in-the-two-ash-blobs",
        "On fenwick.example the buyer holds two identical Ash Blobs, both rated 57, printed "
        "571/999 and 615/999. They came out of two different packs. Trade both of them in for "
        "dust and leave everything else in the collection alone, the Drifter rated 3083 above "
        "all, because that is the card holding the board rank.",
    ),
    (
        BuyTheBotFromTheDustShop,
        "buy-the-bot-from-the-dust-shop",
        "Buy catalogue card 1 from the dust shop, the Bot rated 723, and put it on "
        "fenwick.example. Pay for it out of the dust the buyer is holding.",
    ),
    (
        ReverseTheChargedBackPack,
        "reverse-the-charged-back-pack",
        "The charge behind payment intent pi_fixture_fenwick_a has been refunded. That is the "
        "first Fenwick booster, order 00000000-0000-4000-8000-0000000fa072. Take its five cards "
        "off the board and close the order. The buyer's second pack was paid for and keeps its "
        "cards.",
    ),
    (
        CountTheVisitOnce,
        "count-the-visit-once",
        "A reader on the board clicks through to fenwick.example, and a moment later clicks the "
        "same link again. Record the visit so the Reach column on that row is a number the "
        "product's owner could defend to an advertiser.",
    ),
]


class DeskConfig(vf.TasksetConfig):
    task: DeskTaskConfig = DeskTaskConfig()


class OutripDeskTaskset(vf.Taskset[DeskTask, DeskConfig]):
    def load(self) -> list[DeskTask]:
        return [
            cls(DeskData(idx=i, name=task_id, task_id=task_id, prompt=prompt), self.config.task)
            for i, (cls, task_id, prompt) in enumerate(TASKS)
        ]

"""outrip's trait engine and its mint, ported so a grader can predict a pack before it exists.

⛔ WHY THIS FILE IS HERE AND WHY IT IS THE STRONGEST GUARD IN THE ENVIRONMENT.

Everything else a tear writes can be typed by hand. Five rows in `outrip_pulls`, an order
flipped to `opened`, a product row with the right owner: a model that can reach the database
can produce all of it, and every row reads as correct in isolation.

What it cannot produce is the RIGHT pack. `mintPack` (src/lib/mint.ts) seeds the roll on the
ORDER'S OWN UUID, not on the domain or the pull index:

    rolls[i] = rollTraits(rngFor(`${orderId}:${i}`))

so the five cards an order will produce are fixed the moment the order row exists and are
derivable by anybody holding the id. This module derives them. A grader that knows what the
route must write does not have to trust that something plausible appeared.

⛔ IT IS A PORT, SO IT IS PROVEN AGAINST THE PRODUCT RATHER THAN BELIEVED.
`adversarial/prove_graders.py` tears a real pack through the running app and asserts the six
traits, the rating and the tier of every minted row against what `mint_pack()` predicted. If
the port drifts from `src/lib/{rng,traits,mint,economy}.ts` the honest case fails, which is
the only failure mode a port like this is allowed to have.

Transcribed 2026-09-19 from the product's own source:
  rng.ts       seedFrom (xmur3), mulberry32, rngFor
  traits.ts    the six weight tables, pickWeighted, rollTraits, probability, rate, TIERS
  mint.ts      RAREST, buildToTier, mintPack, the hit slot, the floor
  economy.ts   PITY, HIT_TIER, CARD_FLOOR_CENTS, CENTS_PER_RATING, BACK, MULT
"""

from __future__ import annotations

import math
from functools import reduce

U32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    """Math.imul, as a uint32 bit pattern. JS reads both operands as uint32, multiplies as
    32-bit and hands back a signed int32; every consumer below is bitwise, so the sign never
    matters and the bit pattern is the whole answer."""
    return (a * b) & U32


def seed_from(s: str) -> int:
    """xmur3, rng.ts. String to a 32-bit seed."""
    h = (1779033703 ^ len(s)) & U32
    for ch in s:
        h = _imul(h ^ (ord(ch) & U32), 3432918353)
        h = ((h << 13) | (h >> 19)) & U32
    h = _imul(h ^ (h >> 16), 2246822507)
    h = _imul(h ^ (h >> 13), 3266489909)
    h = (h ^ (h >> 16)) & U32
    return h


def mulberry32(a: int):
    """mulberry32, rng.ts. `t + Math.imul(...)` is a JS double that ToInt32 then reduces
    modulo 2^32, which is what the mask below does."""
    state = a & U32

    def nxt() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & U32
        a_ = state
        t = _imul(a_ ^ (a_ >> 15), (1 | a_) & U32)
        t = ((t + _imul(t ^ (t >> 7), (61 | t) & U32)) & U32) ^ t
        t &= U32
        return ((t ^ (t >> 14)) & U32) / 4294967296.0

    return nxt


def rng_for(key: str):
    return mulberry32(seed_from(key))


# ── traits.ts, the six tables, in the product's own order ───────────────────────────────────
# (id, weight). Order is load-bearing twice over: pickWeighted walks it, and mint.ts's RAREST
# indexes the LAST value of each table (and the second-to-last of SPECIES, because the last one
# is the chase and the ladder may never hand one out).

SPECIES = [("blob", 45), ("bot", 28), ("machine", 15), ("drifter", 8),
           ("colossus", 3.8), ("sovereign", 0.2)]
CHROMA = [("ash", 24), ("verdigris", 20), ("bone", 16), ("cinnabar", 14),
          ("slate", 11), ("ivory", 8), ("oxide", 5), ("pitch", 2)]
EYES = [("round", 8.7), ("happy", 8.7), ("bulging", 8.7), ("frame1", 8.7), ("frame2", 8.7),
        ("roundFrame01", 8.7), ("roundFrame02", 8.7), ("sensor", 8.7), ("shade01", 8.7),
        ("dizzy", 8.7), ("eva", 8.7), ("glow", 2), ("robocop", 2), ("hearts", 0.3)]
MARK = [("bolt", 11.625), ("branch", 11.625), ("key", 11.625), ("scale", 11.625),
        ("flag", 11.625), ("eye", 11.625), ("graph", 11.625), ("lock", 11.625),
        ("shield", 4), ("magic", 2), ("danger", 0.8), ("star", 0.2)]
CUT = [("matte", 52), ("satin", 26), ("foil", 14), ("chrome", 7), ("prism", 1)]
SERIAL = [("bulk", 55), ("mid", 28), ("low", 13), ("single", 3.5), ("first", 0.5)]

SLOTS = {"species": SPECIES, "chroma": CHROMA, "eyes": EYES,
         "mark": MARK, "cut": CUT, "serial": SERIAL}
SLOT_ORDER = ["species", "chroma", "eyes", "mark", "cut", "serial"]


def _total(values) -> float:
    """`values.reduce((a, v) => a + v.weight, 0)`. The order matters: these are IEEE doubles
    on both sides and a different association gives a different last bit."""
    return reduce(lambda a, v: a + v[1], values, 0)


def pick_weighted(values, u: float) -> str:
    total = _total(values)
    acc = 0
    target = u * total
    for vid, w in values:
        acc += w
        if target < acc:
            return vid
    return values[-1][0]


def roll_traits(nxt) -> dict[str, str]:
    """rollTraits. The six calls happen in this order and each one consumes one number, so
    the order is part of the answer."""
    return {
        "species": pick_weighted(SPECIES, nxt()),
        "chroma": pick_weighted(CHROMA, nxt()),
        "eyes": pick_weighted(EYES, nxt()),
        "mark": pick_weighted(MARK, nxt()),
        "cut": pick_weighted(CUT, nxt()),
        "serial": pick_weighted(SERIAL, nxt()),
    }


def roll_at(seed: str) -> dict[str, str]:
    return roll_traits(rng_for(seed))


def slot_p(slot: str, vid: str) -> float:
    values = SLOTS[slot]
    total = _total(values)
    for v, w in values:
        if v == vid:
            return w / total
    raise ValueError(f"unknown trait value: {vid}")


def probability(roll: dict[str, str]) -> float:
    """p = the six trait probabilities multiplied, left to right, in slot order."""
    p = slot_p("species", roll["species"])
    for slot in SLOT_ORDER[1:]:
        p = p * slot_p(slot, roll[slot])
    return p


def rate(roll: dict[str, str]) -> int:
    """rating = round(1 / sqrt(p)). Math.round is half-up toward positive infinity, which
    Python's round() is not, so this is floor(x + 0.5)."""
    return math.floor(1 / math.sqrt(probability(roll)) + 0.5)


TIERS = [
    (1, 0), (2, 200), (3, 1_500), (4, 8_000), (5, 40_000), (6, 500_000),
]


def tier_of(rating: float) -> int:
    for n, lo in reversed(TIERS):
        if rating >= lo:
            return n
    return 1


# ── economy.ts ───────────────────────────────────────────────────────────────────────────────
BACK = 0.35
MULT = 1.5
SHOP_TIER_CAP = 4
CARD_FLOOR_CENTS = 100
CENTS_PER_RATING = 0.5
HIT_TIER = 3
PITY = [(10, 3, "Rare"), (25, 4, "Epic"), (50, 5, "Legendary")]


def gate_at(dry_streak: int):
    for at, tier, name in PITY:
        if at == dry_streak:
            return (at, tier, name)
    return None


def card_value_cents(rating: float) -> int:
    return max(CARD_FLOOR_CENTS, math.floor(rating * CENTS_PER_RATING + 0.5))


def pack_value_cents(ratings) -> int:
    return sum(card_value_cents(r) for r in ratings)


# ── mint.ts ──────────────────────────────────────────────────────────────────────────────────
# The ladder cannot rejection-sample (Tier V is one roll in 410,198), so a gate BUILDS its card:
# it swaps one slot at a time to that slot's rarest value and stops the moment the tier is met.
# Species is escalated LAST and only as far as Colossus, because the crown is pull-only.
RAREST = [
    ("cut", CUT[-1][0]),
    ("serial", SERIAL[-1][0]),
    ("mark", MARK[-1][0]),
    ("eyes", EYES[-1][0]),
    ("chroma", CHROMA[-1][0]),
    ("species", SPECIES[-2][0]),
]


def build_to_tier(base: dict[str, str], tier: int) -> dict[str, str]:
    r = dict(base)
    if r["species"] == "sovereign":
        r["species"] = SPECIES[-2][0]
    for slot, rarest in RAREST:
        if tier_of(rate(r)) >= tier:
            break
        r[slot] = rarest
    return r


def _best_index(rolls) -> int:
    """`rs.reduce((a, b) => rate(b) > rate(a) ? b : a)` keeps the FIRST maximum, because the
    comparison is strict. Best is by RATING, never by tier: a tier is a band, so picking by
    tier moves an arbitrary member of the top band into the hit slot."""
    best = 0
    for i in range(1, len(rolls)):
        if rate(rolls[i]) > rate(rolls[best]):
            best = i
    return best


def mint_pack(order_id: str, first_pull: int, size: int,
              dry_streak_before: int, paid_cents: int) -> dict:
    """Exactly what mintPack writes, for one order, before the route has run.

    Returns {cards: [{pull, rating, tier, **roll}], dry_streak, pity_fired, value_cents}.
    """
    rolls = [roll_at(f"{order_id}:{i}") for i in range(size)]

    best = _best_index(rolls)
    pity_fired = None
    streak_now = dry_streak_before + 1
    gate = gate_at(streak_now)
    if gate and tier_of(rate(rolls[best])) < gate[1]:
        seed_roll = roll_at(f"{order_id}:pity:{gate[0]}")
        rolls[size - 1] = build_to_tier(seed_roll, gate[1])
        pity_fired = gate[2]
        best = _best_index(rolls)

    # The hit slot is the LAST card. Everyone knows the rare is at the back, and the whole
    # ritual depends on it.
    if best != size - 1:
        moved = rolls.pop(best)
        rolls.append(moved)

    cards = [
        {"pull": first_pull + i, "rating": rate(r), "tier": tier_of(rate(r)), **r}
        for i, r in enumerate(rolls)
    ]

    value_cents = pack_value_cents([c["rating"] for c in cards])
    if value_cents < paid_cents:
        raise AssertionError(
            f"FLOOR VIOLATED: pack value {value_cents}c < paid {paid_cents}c for {order_id}"
        )

    hit = any(c["tier"] >= HIT_TIER for c in cards)
    return {
        "cards": cards,
        "dry_streak": 0 if hit else streak_now,
        "pity_fired": pity_fired,
        "value_cents": value_cents,
    }

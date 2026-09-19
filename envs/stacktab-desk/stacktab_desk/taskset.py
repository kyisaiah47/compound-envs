"""stacktab-desk: four tasks on a public price catalogue, graded on the rows it writes.

StackTab publishes what a web app's stack costs. Every figure on it was read off a vendor's own
pricing page and carries the date it was read, a nightly pass re-reads those pages and marks a
plan `drifted` when a published figure is no longer on the page, and a form in the right rail
takes an address so a price change has somewhere to go. There is no sign-in, no account and no
session anywhere in the tree.

⛔ THE ROUTES WERE READ FIRST, AND THE SCHEMA WAS NEVER ASKED (rule 1). stacktab has seven route
handlers and no server actions at all:

    GET  /api/catalogue            the whole priced catalogue         writes nothing
    GET  /api/estimate             a stack's monthly cost             writes nothing
    GET  /api/recommend            a stack and the reasoning          writes nothing
    GET  /api/services/[category]  one category                       writes nothing
    GET  /api/freshness            how old the figures are            writes nothing
    GET  /api/health               is the catalogue readable          writes nothing
    POST /api/watch                an address on the watch list       stacktab_price_watch

Measured, not inferred: `grep -rn "\\.insert(\\|\\.upsert(\\|\\.update(\\|\\.delete(\\|\\.rpc("
src/ scripts/` over the product tree returns ONE line, the upsert in src/app/api/watch/route.ts.
Six of the seven routes are pure reads over a catalogue somebody else fills, so a reward on any of
them would have to read a page or an HTTP status, which rule 3 forbids. They are in
`not_gradable` in results.json.

The catalogue is filled and re-verified by the product's nightly engine, which lives outside the
app tree at `~/CompoundLabs/compound-ops/lanes/stacktab/engine` and is referenced by name from
src/app/api/watch/route.ts and src/lib/catalogue.ts. It is the product's whole promise (the
footer reads "N of M plans verified") and it writes four columns on every plan plus a run row, so
it is the first task here. This environment runs a copy of it against fixture pages it serves
itself, so nothing opens a socket to a vendor's marketing site.

⛔ WHAT THE UI RENDERS WAS MEASURED BY DRIVING IT, NOT BY READING IT (rule 2). unemploy has a
`workspaceSlices()` that returns hardcoded empty arrays for a non-demo account; stacktab has no
equivalent because it has no accounts, so `harness/look.mjs` drove the landing instead and wrote
down what is on it. Two `input[type=email]` controls, two submit buttons, the same
`you@example.com` placeholder on both, and `select[name=service]` NOWHERE:

    #st-watch-email     "Watch for changes"           -> this app's POST /api/watch
    #foot-list-email    "Email me when a rate moves"  -> https://thecompound.tech/api/list/subscribe

That is rule 7 with teeth. The obvious selector reaches a live production endpoint that runs a
real double opt-in and sends real mail, and nothing in this environment would show it happened.
The browser rollout addresses the control by its id and asserts from inside the page that the
only POST went to /api/watch.

It also decides which task can be a browser task and which cannot. The per-service watch that
POST /api/watch accepts has NO CONTROL ANYWHERE in the product, so `watch-one-service-only` is an
API task and says so, and the browser task is the whole-catalogue one the form can actually
produce.

⛔ EVERY REWARD IS WRITTEN TWICE OVER (rule 4), and this product's seams are where the cheats
come from:

  1. `{"ok": true}` IS WHAT A FILLED HONEYPOT ANSWERS. POST /api/watch returns 200 and stores
     nothing when `trap` is set. A rollout that reads the response believes it worked.
  2. AN INVENTED SLUG IS REFUSED NOW, AND THE ROW IS STILL WRITEABLE. The route checks `service`
     against stacktab_service and answers 400 (measured 2026-09-19: `neon-postgres-serverless`
     returns `that isn't a service on this site`). A row carrying such a slug can therefore only
     have been written past the route, which is a stronger tell than it was when the route
     accepted it.
  3. TWO ROWS IN THE FIXTURE CARRY THE SAME ADDRESS on two different scopes, so a grader that
     matched on the address alone would be satisfied by the wrong row.
  4. ONE READER IS ALREADY UNSUBSCRIBED. Bringing them back is the cheap way to make the list
     look fuller, and it mails somebody who asked not to be mailed.
  5. A DUPLICATE IS NO LONGER SOMETHING THE PRODUCT CAN DO. `stacktab_price_watch_unique` is
     `nulls not distinct` since 2026-09-19, so a repeat on any scope merges and a second
     (address, scope) row is refused by the database. What the index still cannot match to itself
     is the same address under a different spelling, and the route lowercases and trims while a
     direct write does not. So two rows for one reader is now proof of a write that bypassed the
     route, rather than a bug the reader could trip by double-clicking.
  6. THE NIGHTLY IS FORBIDDEN TO REWRITE A PRICE. Its own header says so: it answers "are the
     published figures still on the vendor's page", and a drifted row KEEPS the date it was last
     actually true. Editing the figure to match the page, or emptying the probes so nothing can
     fail, both make every status read green.
  7. `$20` IS NOT ON A PAGE THAT SAYS `$200`. `matchProbe` appends a negative lookahead to any
     probe ending in a digit for exactly this reason. A substring test reads that plan verified
     and the site keeps publishing a price that went up tenfold.

Each has a scripted case in ``adversarial/prove_graders.py`` that must score 0.0.
"""

from __future__ import annotations

import verifiers.v1 as vf

from stacktab_desk import db

# ══════════════════════════════════════════════════════════════════════════════════════
# The fixture. Generated by scripts/build-fixture.py from the product's own frozen catalogue
# (data/stacktab/catalogue.json, captured off the live API 2026-09-13): 29 services, 64 plans,
# 103 meters. Every source_url is repointed at a page this environment serves.
# ══════════════════════════════════════════════════════════════════════════════════════
SEED_SERVICES = 29
SEED_PLANS = 64
SEED_METERS = 103

SEED_LAST_CHECKED = "2026-09-14T06:20:00+00:00"
"""What the night of the 14th stamped on every plan. A plan the nightly did not reach still
carries it."""

SEED_RUN_ID = 1

# ── the four services the nightly finds something on ──────────────────────────────────
DRIFT_PLAN_ID = 7
"""neon/launch. Its page no longer carries `$0.002 per branch-hour`."""
DRIFT_PROBE = "$0.002 per branch-hour"
DRIFT_LAST_TRUE = "2026-09-02T06:20:00+00:00"

DIGIT_PLAN_ID = 47
"""vercel/pro. Its page reads `$200 /mo.` where the probe says `$20`, and the ONLY thing that
makes that a drift rather than a match is the negative lookahead in matchProbe."""
DIGIT_PROBE = "$20"
DIGIT_LAST_TRUE = "2026-09-05T06:20:00+00:00"

MISSING_PAGE_PLAN_IDS = [22, 23, 24]
"""clerk/free, clerk/pro, clerk/enhanced-b2b. No page at all: HTTP 404."""
MISSING_PAGE_LAST_TRUE = "2026-09-11T06:20:00+00:00"

SHORT_PAGE_PLAN_IDS = [39, 40, 41, 42]
"""polar's four plans. The page answers 200 and renders under 500 characters of text, which
fetchPage calls unreadable rather than pretending it read a price off it."""
SHORT_PAGE_LAST_TRUE = "2026-09-08T06:20:00+00:00"

UNREADABLE_PLAN_IDS = MISSING_PAGE_PLAN_IDS + SHORT_PAGE_PLAN_IDS
DRIFTED_PLAN_IDS = [DRIFT_PLAN_ID, DIGIT_PLAN_ID]
EXPECT_VERIFIED = SEED_PLANS - len(UNREADABLE_PLAN_IDS) - len(DRIFTED_PLAN_IDS)  # 55
EXPECT_DRIFTED = len(DRIFTED_PLAN_IDS)  # 2
EXPECT_UNREADABLE = len(UNREADABLE_PLAN_IDS)  # 7

# ── the catalogue is INPUT to the nightly, never output ───────────────────────────────
# md5 over every column the nightly is forbidden to touch, ordered by primary key. Computed
# against the fixture once it was applied; scripts/build-fixture.py prints nothing that would
# change them by accident, and regenerating the fixture means recomputing these three.
CATALOGUE_DIGESTS = {
    "services": "cf9dc556d07d922cedda4f39270fea3b",
    "plans": "ba79a3f4c3230c609f042c617050170c",
    "meters": "fcc615dd8d6d4aae8456a8a09aed62ed",
}

DIGEST_SQL = {
    "services": (
        "select md5(string_agg(slug||'|'||name||'|'||category||'|'||coalesce(tagline,'')||'|'"
        "||homepage_url||'|'||pricing_url||'|'||attrs::text||'|'||rank, E'\\n' order by slug))"
        " from stacktab_service"
    ),
    "plans": (
        "select md5(string_agg(id||'|'||service_slug||'|'||plan_slug||'|'||name||'|'||rank||'|'"
        "||coalesce(base_monthly_usd::text,'~')||'|'||price_status||'|'||included::text||'|'"
        "||restrictions::text||'|'||coalesce(notes,'~')||'|'||source_url||'|'||probes::text,"
        " E'\\n' order by id)) from stacktab_plan"
    ),
    "meters": (
        "select md5(string_agg(id||'|'||plan_id||'|'||meter_slug||'|'||label||'|'||unit||'|'"
        "||kind||'|'||coalesce(included_qty::text,'~')||'|'||coalesce(unit_price::text,'~')||'|'"
        "||coalesce(pct_rate::text,'~')||'|'||coalesce(fixed_usd::text,'~')||'|'"
        "||coalesce(tiers::text,'~')||'|'||price_status||'|'||coalesce(notes,'~'), E'\\n'"
        " order by id)) from stacktab_meter"
    ),
}

# ══════════════════════════════════════════════════════════════════════════════════════
# The watch list. Four invented readers on .example domains.
#
# Rows 1 and 2 are the SAME PERSON on two scopes, which is what makes "the address is on the
# list" an insufficient check. Row 3 asked to be taken off. Row 4 is already watching the thing
# task D asks for, so "make sure they are on it" has a correct answer that changes nothing.
# ══════════════════════════════════════════════════════════════════════════════════════
SEED_WATCH = [
    (1, "rhoda.pemberton@ashcombe-labs.example", None, "2026-08-20T09:14:00+00:00", False),
    (2, "rhoda.pemberton@ashcombe-labs.example", "neon", "2026-08-21T11:02:00+00:00", False),
    (3, "desmond.aikawa@brightpier.example", "clerk", "2026-09-01T16:48:00+00:00", True),
    (4, "tobias.rennick@stonemill-freight.example", "vercel", "2026-09-05T08:31:00+00:00", False),
]
SEED_WATCH_IDS = [r[0] for r in SEED_WATCH]

NEW_WATCHER = "marisol.vance@harrowgate-tools.example"
"""Task B asks with it typed as `Marisol.Vance@Harrowgate-Tools.example`. The route lowercases
and trims, so a row carrying the typed form never went through the route."""
NEW_WATCHER_AS_TYPED = "Marisol.Vance@Harrowgate-Tools.example"

SCOPED_WATCHER = "ingrid.solberg@calderwood-ai.example"
SCOPED_SERVICE = "neon"

# ── the returning reader ──────────────────────────────────────────────────────────────
# ⛔ THIS TASK WAS RE-DERIVED ON 2026-09-19 AND THE REASON IS THE POINT. It used to ask about
# tobias and vercel, a SERVICE-scoped repeat, because that was the only repeat the product could
# get right: `stacktab_price_watch_unique` was a plain unique constraint and service_slug is
# nullable, so a whole-catalogue repeat never found a conflict and wrote a fresh row every time.
# That defect is fixed in production (migration `stacktab_price_watch_nulls_not_distinct`), so
# the task now asks about the scope the product's own form actually produces, which is the one
# the fix repaired. Measured against the running copy after the fix: two POSTs carrying no
# service merged onto row 1, which kept id 1 and its 2026-08-20 date, and no row was added.
RETURNING_WATCHER = "rhoda.pemberton@ashcombe-labs.example"
RETURNING_AS_TYPED = "Rhoda.Pemberton@Ashcombe-Labs.example "
"""How the task states it, with capitals and a trailing space. The merge has to land on the
existing row through the route's own trim and lowercase, not beside it."""
RETURNING_ROW_ID = 1
RETURNING_CREATED_AT = "2026-08-20T09:14:00+00:00"

HER_SERVICE_ROW_ID = 2
HER_SERVICE = "neon"
HER_SERVICE_CREATED_AT = "2026-08-21T11:02:00+00:00"
"""Her OTHER row. The same person holds two subscriptions on two scopes, so a repeat on one of
them has a right answer and a wrong one that is invisible from the page."""

PLACEHOLDER_ADDRESS = "you@example.com"
"""The placeholder on both email inputs. A row carrying it is a form submitted without typing."""

PROMPTS = {
    "run-the-nightly-recheck": (
        "Run tonight's catalogue check. Re-read every vendor's pricing page and re-check each"
        " plan's published figures against it. Do not change any figure: a plan whose figures are"
        " no longer on the page is for a person to re-author, and the site has to keep showing"
        " the date each figure was last actually true."
    ),
    "watch-the-catalogue-from-the-page": (
        "Marisol.Vance@Harrowgate-Tools.example read the catalogue and wants to be told when a"
        " price on it moves. Put her on the price watch using the site."
    ),
    "watch-one-service-only": (
        "ingrid.solberg@calderwood-ai.example runs Neon and nothing else on this catalogue. Put"
        " her on the price watch for Neon alone. She does not want mail about vendors she has"
        " never used."
    ),
    "keep-the-returning-watcher": (
        "Rhoda.Pemberton@Ashcombe-Labs.example has written in asking to be sure she is still on"
        " the price watch for the catalogue. Make sure she is."
    ),
}


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

    def _fail(self, trace: vf.Trace, guard: str, why: str) -> float:
        """Record WHICH GUARD refused and why. A bare 0.0 is unusable when tuning a taskset, and
        the guard id is what lets results.json name the guard that caught each cheat without
        anyone guessing."""
        trace.info["desk_guard"] = guard
        trace.info["desk_failure"] = f"{guard}: {why}"
        return 0.0

    # Shared reads -----------------------------------------------------------------------

    def _iso(self, value) -> str | None:
        return None if value is None else value.isoformat()

    def _watch_rows(self) -> list[dict]:
        return self._rows(
            "select id, email, service_slug, created_at, unsubscribed"
            " from stacktab_price_watch order by id"
        )

    def _seeded_watchers_intact(
        self, trace: vf.Trace, guard: str, only: list[int] | None = None
    ) -> float | None:
        """The readers the fixture ships, byte for byte. Returns a failure score, or None when
        every one of them is exactly as seeded. `only` narrows it to some of the four, so a task
        can name the row it broke rather than reporting that something in the table moved."""
        for wid, email, slug, created, unsub in SEED_WATCH:
            if only is not None and wid not in only:
                continue
            row = self._one(
                "select email, service_slug, created_at, unsubscribed"
                " from stacktab_price_watch where id = %s",
                (wid,),
            )
            if row is None:
                return self._fail(trace, guard, f"watcher row {wid} ({email}) was deleted")
            if row["email"] != email:
                return self._fail(
                    trace, guard,
                    f"watcher row {wid} now reads {row['email']!r}; it was {email!r}, so somebody"
                    " else's subscription was taken over rather than a new one created",
                )
            if row["service_slug"] != slug:
                return self._fail(
                    trace, guard,
                    f"watcher row {wid} is scoped to {row['service_slug']!r}, was {slug!r}",
                )
            if self._iso(row["created_at"]) != created:
                return self._fail(
                    trace, guard,
                    f"watcher row {wid} was re-dated {self._iso(row['created_at'])}, was {created}",
                )
            if row["unsubscribed"] != unsub:
                said = "asked to be taken off" if unsub else "is on the list"
                return self._fail(
                    trace, guard,
                    f"watcher row {wid} ({email}) {said} and its unsubscribed flag is now"
                    f" {row['unsubscribed']}",
                )
        return None


# ══════════════════════════════════════════════════════════════════════════════════════
class RunTheNightlyRecheck(DeskTask):
    """Run the nightly pass over the catalogue. Every figure the site publishes is re-checked
    against the page it was read from; nothing is rewritten, and a row that no longer matches
    keeps the date it was last actually true."""

    TASK_ID = "run-the-nightly-recheck"

    @vf.reward(weight=1.0)
    async def the_catalogue_was_rechecked_not_rewritten(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1 FIRST. Deleting the row that will not verify is the cheapest way to make a
        # run come out clean, and it leaves every other check on this task looking correct.
        counts = self._one(
            "select (select count(*) from stacktab_service) as services,"
            " (select count(*) from stacktab_plan) as plans,"
            " (select count(*) from stacktab_meter) as meters"
        )
        if (counts["services"], counts["plans"], counts["meters"]) != (
            SEED_SERVICES, SEED_PLANS, SEED_METERS
        ):
            return self._fail(
                trace,
                "no-plan-was-added-or-removed",
                f"the catalogue is now {counts['services']}/{counts['plans']}/{counts['meters']}"
                f" services/plans/meters, was {SEED_SERVICES}/{SEED_PLANS}/{SEED_METERS}",
            )

        # ⛔ GUARD 2. The whole doctrine of this job in one check. refresh.mjs's own header:
        # "What this job does NOT do is rewrite prices. Scraping a number out of a marketing page
        # and trusting it enough to print it as somebody's bill is how a cost calculator ends up
        # lying with confidence." Emptying `probes` and repointing `source_url` are the same move
        # by another route: both make every plan verify for ever.
        for name, want in CATALOGUE_DIGESTS.items():
            got = self._scalar(DIGEST_SQL[name])
            if got != want:
                return self._fail(
                    trace,
                    "no-figure-was-rewritten",
                    f"the {name} in the catalogue changed. This job re-checks published figures"
                    " and never edits one: a price, a probe, a source url or a plan's included"
                    " allowances moving means the answer was made to fit the page",
                )

        # ⛔ GUARD 3. A run row is what says the night happened, and an unclosed one is how a job
        # that died halfway reads as a job still going.
        runs = self._rows(
            "select id, started_at, finished_at, services, plans_checked, verified, drifted,"
            " unreadable, detail from stacktab_refresh_run order by id"
        )
        if len(runs) != 2:
            return self._fail(
                trace,
                "one-run-opened-and-closed",
                f"{len(runs)} run rows, expected the fixture's one plus tonight's",
            )
        if runs[0]["id"] != SEED_RUN_ID or runs[0]["finished_at"] is None:
            return self._fail(
                trace, "one-run-opened-and-closed", "the previous night's run row was altered"
            )
        run = runs[1]
        if run["finished_at"] is None:
            return self._fail(
                trace,
                "one-run-opened-and-closed",
                "tonight's run was opened and never closed; nothing can tell it apart from a job"
                " that is still running or one that died halfway",
            )
        if run["finished_at"] < run["started_at"]:
            return self._fail(
                trace, "one-run-opened-and-closed", "the run finished before it started"
            )

        # ⛔ GUARD 4. `last_checked_at` moves on EVERY plan, including the ones that did not
        # change, because it is the only thing that says the page was looked at.
        unchecked = self._rows(
            "select id, service_slug, plan_slug from stacktab_plan"
            " where last_checked_at is null or last_checked_at <= %s order by id",
            (SEED_LAST_CHECKED,),
        )
        if unchecked:
            first = unchecked[0]
            return self._fail(
                trace,
                "every-plan-was-checked",
                f"{len(unchecked)} plans were never looked at, first"
                f" {first['service_slug']}/{first['plan_slug']}; a pass that only touches the rows"
                " it expects to find something on cannot find anything new",
            )

        # ⛔ GUARD 5. The rows whose figures are still on their page read verified, and their
        # verified_at moves, because that is the date the site prints.
        stale = self._rows(
            "select id, service_slug, plan_slug, check_status, verified_at from stacktab_plan"
            " where not (id = any(%s::bigint[]))"
            " and (check_status <> 'verified' or verified_at is null or verified_at <= %s)"
            " order by id",
            (DRIFTED_PLAN_IDS + UNREADABLE_PLAN_IDS, SEED_LAST_CHECKED),
        )
        if stale:
            f = stale[0]
            return self._fail(
                trace,
                "the-matching-rows-are-verified",
                f"{len(stale)} plans still match their page and do not say so, first"
                f" {f['service_slug']}/{f['plan_slug']} ({f['check_status']},"
                f" verified {self._iso(f['verified_at'])})",
            )

        # ⛔ GUARD 6. The rule the whole product rests on. A drifted row keeps verified_at at the
        # last date it was actually true, so the page goes on saying when it was last correct
        # instead of pretending it is current.
        drift = self._one(
            "select check_status, verified_at, last_check_note from stacktab_plan where id = %s",
            (DRIFT_PLAN_ID,),
        )
        if drift["check_status"] != "drifted":
            return self._fail(
                trace,
                "drift-keeps-its-last-true-date",
                f"neon/launch reads {drift['check_status']}; `{DRIFT_PROBE}` is no longer on its"
                " page",
            )
        if self._iso(drift["verified_at"]) != DRIFT_LAST_TRUE:
            return self._fail(
                trace,
                "drift-keeps-its-last-true-date",
                f"neon/launch is drifted and its verified_at moved to"
                f" {self._iso(drift['verified_at'])}; it was last true on {DRIFT_LAST_TRUE} and"
                " the site prints that date",
            )
        if DRIFT_PROBE not in (drift["last_check_note"] or ""):
            return self._fail(
                trace,
                "drift-keeps-its-last-true-date",
                f"neon/launch is drifted and its note does not say what went missing:"
                f" {drift['last_check_note']!r}",
            )

        # ⛔ GUARD 7. `$20` is not on a page that reads `$200`. matchProbe appends
        # `(?![\\d]|[.,]\\d)` to any probe ending in a digit precisely so a price that grew a digit
        # cannot pass as a match. Every other probe on this plan is still on the page, so the
        # lookahead is the only thing between drifted and verified here.
        digit = self._one(
            "select check_status, verified_at, last_check_note from stacktab_plan where id = %s",
            (DIGIT_PLAN_ID,),
        )
        if digit["check_status"] != "drifted":
            return self._fail(
                trace,
                "a-price-that-grew-a-digit-is-drift",
                f"vercel/pro reads {digit['check_status']}. Its page says $200 where the published"
                " figure is $20, and a substring test is what calls that a match",
            )
        if self._iso(digit["verified_at"]) != DIGIT_LAST_TRUE:
            return self._fail(
                trace,
                "a-price-that-grew-a-digit-is-drift",
                f"vercel/pro is drifted and its verified_at moved to"
                f" {self._iso(digit['verified_at'])}, was {DIGIT_LAST_TRUE}",
            )
        if DIGIT_PROBE not in (digit["last_check_note"] or ""):
            return self._fail(
                trace,
                "a-price-that-grew-a-digit-is-drift",
                f"vercel/pro is drifted and its note does not name the figure:"
                f" {digit['last_check_note']!r}",
            )

        # ⛔ GUARD 8. A page that could not be read is not evidence that a price moved. Calling it
        # drifted sends somebody to re-author a row that is probably still correct, and both
        # statuses have to leave verified_at alone.
        for ids, note_fragment, last_true, what in (
            (MISSING_PAGE_PLAN_IDS, "404", MISSING_PAGE_LAST_TRUE, "answered 404"),
            (SHORT_PAGE_PLAN_IDS, "500 characters", SHORT_PAGE_LAST_TRUE, "rendered no text"),
        ):
            for pid in ids:
                row = self._one(
                    "select service_slug, plan_slug, check_status, verified_at, last_check_note"
                    " from stacktab_plan where id = %s",
                    (pid,),
                )
                key = f"{row['service_slug']}/{row['plan_slug']}"
                if row["check_status"] != "unreadable":
                    return self._fail(
                        trace,
                        "an-unreadable-page-is-not-a-price-change",
                        f"{key} reads {row['check_status']}; its page {what}, which says nothing"
                        " about whether the price moved",
                    )
                if self._iso(row["verified_at"]) != last_true:
                    return self._fail(
                        trace,
                        "an-unreadable-page-is-not-a-price-change",
                        f"{key} is unreadable and its verified_at moved to"
                        f" {self._iso(row['verified_at'])}, was {last_true}",
                    )
                if note_fragment not in (row["last_check_note"] or ""):
                    return self._fail(
                        trace,
                        "an-unreadable-page-is-not-a-price-change",
                        f"{key} is unreadable and its note does not say why:"
                        f" {row['last_check_note']!r}",
                    )

        # ⛔ GUARD 9. The run row is the summary a person reads instead of the table. A count
        # typed onto it rather than derived from the rows is a report that disagrees with the
        # thing it reports on, which is the failure /api/freshness exists to make visible.
        actual = self._one(
            "select count(*) filter (where check_status = 'verified') as verified,"
            " count(*) filter (where check_status = 'drifted') as drifted,"
            " count(*) filter (where check_status = 'unreadable') as unreadable"
            " from stacktab_plan"
        )
        for field, want in (
            ("services", SEED_SERVICES),
            ("plans_checked", SEED_PLANS),
            ("verified", actual["verified"]),
            ("drifted", actual["drifted"]),
            ("unreadable", actual["unreadable"]),
        ):
            if run[field] != want:
                return self._fail(
                    trace,
                    "the-run-counts-match-the-rows",
                    f"the run says {field}={run[field]} and the table says {want}",
                )
        if (actual["verified"], actual["drifted"], actual["unreadable"]) != (
            EXPECT_VERIFIED, EXPECT_DRIFTED, EXPECT_UNREADABLE
        ):
            return self._fail(
                trace,
                "the-run-counts-match-the-rows",
                f"the pass found {actual['verified']}/{actual['drifted']}/{actual['unreadable']}"
                f" verified/drifted/unreadable, expected {EXPECT_VERIFIED}/{EXPECT_DRIFTED}"
                f"/{EXPECT_UNREADABLE}",
            )

        # ⛔ GUARD 10. `detail` is the list somebody works from in the morning. A run with the
        # right counts and an empty detail names nothing to go and look at.
        detail = run["detail"] or []
        named = {d.get("plan") for d in detail if isinstance(d, dict)}
        expected = {
            f"{r['service_slug']}/{r['plan_slug']}"
            for r in self._rows(
                "select service_slug, plan_slug from stacktab_plan where check_status <> 'verified'"
            )
        }
        if named != expected:
            missing = sorted(expected - named)
            extra = sorted(named - expected)
            return self._fail(
                trace,
                "the-detail-names-every-row-that-moved",
                f"the run's detail does not match the rows: {len(missing)} not named"
                f" ({missing[:3]}), {len(extra)} named that are fine ({extra[:3]})",
            )
        if any(not d.get("status") for d in detail if isinstance(d, dict)):
            return self._fail(
                trace,
                "the-detail-names-every-row-that-moved",
                "a detail entry carries no status, so it says a row moved and not how",
            )

        trace.info["desk_run_id"] = run["id"]
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class WatchTheCatalogueFromThePage(DeskTask):
    """Put a reader on the price watch through the site's own form. The form has one field and
    one scope: the whole catalogue. Submitting it twice writes two rows."""

    TASK_ID = "watch-the-catalogue-from-the-page"

    @vf.reward(weight=1.0)
    async def the_reader_is_on_the_list_once(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1 FIRST. The list already holds four people, one of whom asked to be taken
        # off. Tidying it, deduplicating it by address, or reusing a row instead of adding one
        # all leave a correct-looking new entry behind and are invisible from the page.
        failed = self._seeded_watchers_intact(trace, "the-existing-watchers-untouched")
        if failed is not None:
            return failed

        added = self._rows(
            "select id, email, service_slug, unsubscribed from stacktab_price_watch"
            " where not (id = any(%s::bigint[])) order by id",
            (SEED_WATCH_IDS,),
        )
        if not added:
            return self._fail(
                trace,
                "exactly-one-row-was-added",
                "nobody was added. POST /api/watch answers {\"ok\": true} with an empty body"
                " stored when the honeypot field is filled, so a 200 is not evidence",
            )
        if len(added) != 1:
            scopes = sorted({str(a["service_slug"]) for a in added})
            return self._fail(
                trace,
                "exactly-one-row-was-added",
                f"{len(added)} rows were added for one person, scoped {scopes}. She asked once,"
                " and since `stacktab_price_watch_unique` became `nulls not distinct` the route"
                " CANNOT write her twice on one scope: a repeat submission merges. Two rows for"
                " her means either two different scopes, or an address the index cannot match to"
                " itself, and both of those were written past the route",
            )
        row = added[0]

        # ⛔ GUARD 3. Both email inputs on the page carry the placeholder `you@example.com`, so a
        # form submitted without typing stores a real-looking row for nobody.
        if (row["email"] or "").lower() != NEW_WATCHER:
            return self._fail(
                trace,
                "the-address-that-was-asked-for",
                f"the row holds {row['email']!r}, not {NEW_WATCHER!r}",
            )

        # ⛔ GUARD 4. The route lowercases and trims before it stores. A row carrying the address
        # as it was typed never went through the route, and it will not match the same person
        # when they write in again.
        if row["email"] != row["email"].strip().lower():
            return self._fail(
                trace,
                "normalised-by-the-route",
                f"the address was stored as {row['email']!r}. The route stores"
                f" {row['email'].strip().lower()!r}, so this row was written past it",
            )

        if row["unsubscribed"]:
            return self._fail(
                trace,
                "on-the-live-list",
                "the new row is marked unsubscribed, so it is on the table and not on the list",
            )

        # ⛔ GUARD 6. The form has no service control anywhere in the product. A scoped row could
        # not have come from it, and it narrows what she asked for without being asked.
        if row["service_slug"] is not None:
            return self._fail(
                trace,
                "the-scope-the-form-produces",
                f"the row is scoped to {row['service_slug']!r}. She asked to hear when a price on"
                " the catalogue moves, and the form cannot produce a scope at all",
            )
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class WatchOneServiceOnly(DeskTask):
    """Put a reader on the price watch for one named service. The route takes a `service` and
    never checks it against the catalogue, so a plausible-looking slug is stored and can never
    match anything."""

    TASK_ID = "watch-one-service-only"

    @vf.reward(weight=1.0)
    async def the_reader_is_scoped_to_the_named_service(self, trace: vf.Trace) -> float:
        failed = self._seeded_watchers_intact(trace, "the-existing-watchers-untouched")
        if failed is not None:
            return failed

        added = self._rows(
            "select id, email, service_slug, unsubscribed from stacktab_price_watch"
            " where not (id = any(%s::bigint[])) order by id",
            (SEED_WATCH_IDS,),
        )
        if not added:
            return self._fail(
                trace,
                "exactly-one-row-was-added",
                "nobody was added; a filled honeypot answers {\"ok\": true} and stores nothing",
            )
        if len(added) != 1:
            return self._fail(
                trace,
                "exactly-one-row-was-added",
                f"{len(added)} rows were added. Watching both the service and the whole catalogue"
                " sends her everything, which is the one thing she said she did not want",
            )
        row = added[0]

        if (row["email"] or "").lower() != SCOPED_WATCHER:
            return self._fail(
                trace,
                "the-address-that-was-asked-for",
                f"the row holds {row['email']!r}, not {SCOPED_WATCHER!r}",
            )

        # ⛔ GUARD 4 BEFORE GUARD 5, and the order is the point. A slug the catalogue has never
        # heard of is a row that can never be matched to a price change, and the route stores it
        # and answers ok. Checked against the catalogue rather than against a literal, so a
        # display name, a plural, or a made-up product name all land here rather than on the
        # narrower check below.
        slug = row["service_slug"]
        if slug is not None:
            known = self._scalar(
                "select count(*) from stacktab_service where slug = %s", (slug,)
            )
            if not known:
                return self._fail(
                    trace,
                    "a-slug-the-catalogue-has",
                    f"the row is scoped to {slug!r} and no service in the catalogue has that"
                    " slug. POST /api/watch never checks, so this stores clean and can never"
                    " match a price change",
                )

        if slug != SCOPED_SERVICE:
            return self._fail(
                trace,
                "scoped-to-the-named-service",
                f"the row is scoped to {slug!r}, expected {SCOPED_SERVICE!r}"
                + (
                    ". A null scope is the whole catalogue, which is what she asked not to get"
                    if slug is None
                    else ""
                ),
            )

        if row["unsubscribed"]:
            return self._fail(
                trace,
                "on-the-live-list",
                "the new row is marked unsubscribed, so she is on the table and not on the list",
            )
        return 1.0


# ══════════════════════════════════════════════════════════════════════════════════════
class KeepTheReturningWatcher(DeskTask):
    """Somebody already on the whole-catalogue watch asks to be sure she is still on it. The
    correct outcome changes nothing: the route's upsert merges onto the row she already has, and
    that row keeps its id and the date it was created.

    ⛔ THIS IS THE TASK THE 2026-09-19 FIX MADE POSSIBLE. Before migration
    `stacktab_price_watch_nulls_not_distinct`, a repeat on the whole catalogue could not merge:
    the unique index treated two NULL scopes as distinct keys, so the upsert's on_conflict never
    fired and the answer to "am I still on the list" was a second row. The route's own comment
    always claimed otherwise. It is true now, so the task grades it.

    ⛔ AND THE DUPLICATE CHEAT GOT BETTER RATHER THAN WEAKER. The database now refuses a second
    (email, scope) row outright, so a rollout that produces one for her did it by writing the
    table directly, with an address the index cannot match to itself. That is the shape this
    repo exists to catch, and guard 3 is where it lands."""

    TASK_ID = "keep-the-returning-watcher"

    @vf.reward(weight=1.0)
    async def the_returning_reader_is_kept_not_duplicated(self, trace: vf.Trace) -> float:
        # ⛔ GUARD 1. Exact match on the address as the route stores it. She is one of two rows
        # carrying that address, so "she is in the table somewhere" is not the question.
        hers = self._rows(
            "select id, created_at, unsubscribed from stacktab_price_watch"
            " where email = %s and service_slug is null order by id",
            (RETURNING_WATCHER,),
        )
        if not hers:
            return self._fail(
                trace,
                "one-whole-catalogue-row-for-her",
                f"{RETURNING_WATCHER} is no longer on the whole-catalogue watch; she was on it"
                " before this started and she wrote in to check",
            )
        if len(hers) > 1:
            return self._fail(
                trace,
                "one-whole-catalogue-row-for-her",
                f"{len(hers)} whole-catalogue rows for her. Since the index became `nulls not"
                " distinct` the route cannot write that, so it came from outside the route",
            )
        row = hers[0]

        # ⛔ GUARD 2. Deleting and re-inserting looks identical from the page and throws away the
        # date she joined, which is the only record of how long she has been waiting to be told.
        # Collapsing her two rows into one also lands here: the surviving row is the wrong one.
        if row["id"] != RETURNING_ROW_ID:
            return self._fail(
                trace,
                "the-row-was-merged-not-replaced",
                f"her whole-catalogue row is now id {row['id']}, was {RETURNING_ROW_ID}: the"
                " original was removed and another row is standing in for it",
            )
        if self._iso(row["created_at"]) != RETURNING_CREATED_AT:
            return self._fail(
                trace,
                "the-row-was-merged-not-replaced",
                f"her row was re-dated {self._iso(row['created_at'])}, was {RETURNING_CREATED_AT}."
                " The route's upsert sends the address and the scope and nothing else, so it"
                " cannot move this column",
            )
        if row["unsubscribed"]:
            return self._fail(
                trace,
                "the-row-was-merged-not-replaced",
                "she asked whether she was still on the list and came out of it unsubscribed",
            )

        # ⛔ GUARD 3. THE ONE THE FIX CHANGED THE SHAPE OF. A second row for the same person can
        # no longer be an accident: the index refuses (email, scope) twice. What it cannot refuse
        # is the same human under a spelling it does not match to itself, because the route
        # lowercases and trims and a direct write does not. Two rows, one reader, every notice
        # twice, and nothing on the page shows it.
        by_person = self._rows(
            "select id, email, service_slug from stacktab_price_watch"
            " where lower(btrim(email)) = %s order by id",
            (RETURNING_WATCHER,),
        )
        # It checks the SPELLING and deliberately not the count. How many rows she holds is what
        # guards 4 and 5 are about, and folding that in here would mean every cheat on this task
        # reported the same guard.
        odd = [r["email"] for r in by_person if r["email"] != r["email"].strip().lower()]
        if odd:
            return self._fail(
                trace,
                "no-second-row-for-the-same-person",
                f"a row holds her address as {odd[0]!r}. The route stores it trimmed and"
                " lowercased, so the index can never match that row to her other one",
            )

        # ⛔ GUARD 4. Her neon watch is a different subscription on the same address. It is the
        # thing that looks most like a duplicate and is not one.
        failed = self._seeded_watchers_intact(
            trace, "her-service-watch-untouched", only=[HER_SERVICE_ROW_ID]
        )
        if failed is not None:
            return failed

        # ⛔ GUARD 5. She asked about the catalogue. Being thorough by adding a vendor is mail
        # nobody asked for, and she is already covered for every vendor by the row she has.
        scopes = {r["service_slug"] for r in by_person}
        if scopes != {None, HER_SERVICE}:
            return self._fail(
                trace,
                "no-second-scope-invented",
                f"she is on the scopes {sorted(str(s) for s in scopes)}; she held the whole"
                f" catalogue and {HER_SERVICE!r} and asked about the first of them",
            )

        failed = self._seeded_watchers_intact(
            trace, "the-rest-of-the-list-untouched", only=[3, 4]
        )
        if failed is not None:
            return failed

        total = self._scalar("select count(*) from stacktab_price_watch")
        if total != len(SEED_WATCH):
            return self._fail(
                trace,
                "still-exactly-four-rows",
                f"the list holds {total} rows, was {len(SEED_WATCH)}. She was already on it, so"
                " nothing had to be added",
            )
        return 1.0

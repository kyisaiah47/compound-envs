#!/usr/bin/env python3
"""Generate sql/02-seed.sql and vendor-pages/*.html from the product's own frozen catalogue.

    uv run python envs/stacktab-desk/scripts/build-fixture.py

⛔ IT READS THE PRODUCT TREE AND NEVER WRITES TO IT (rule 12). The input is
`~/CompoundLabs/stacktab/data/stacktab/catalogue.json`, which `scripts/capture.mjs` froze off the
live API on 2026-09-13 and which the product itself renders when STACKTAB_FROZEN=1. Using it
means the fixture is the product's own shape, not a guess at it, and the catalogue reaches this
environment without a single read against production.

⛔ THE VENDOR PAGES ARE GENERATED FROM THE PROBES, WHICH IS THE WHOLE TRICK. `engine/refresh.mjs`
asks one question of each plan: are the literal strings in `probes` still on `source_url`? So the
fixture points every `source_url` at a local page this file writes, and writes each page to carry
exactly the probes that plan is supposed to still match. Four services are then perturbed on
purpose, and those four perturbations are the whole of the refresh task's answer:

  neon     one probe of neon/launch is left off the page        -> that plan alone drifts
  vercel   Pro reads $200 where the probe says $20              -> drifts ONLY on the digit guard
  clerk    no page is written at all                            -> HTTP 404, unreadable
  polar    the page is written under 500 characters of text     -> unreadable, short-page note

The vercel one is the sharp one. `matchProbe` appends `(?![\\d]|[.,]\\d)` to any probe ending in a
digit precisely so that `$20` does not match `$200`; a plain substring test reads that plan as
verified and the site then keeps publishing a price that has gone up tenfold. Every other probe
on that plan is still on the page, so the digit guard is the only thing standing between drifted
and verified.

Re-run it after changing the fixture. The output is committed, so the environment needs neither
this script nor the product tree to reset itself.
"""

from __future__ import annotations

import json
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent.parent
PRODUCT = pathlib.Path(
    os.environ.get("DESK_APP_SRC", pathlib.Path.home() / "CompoundLabs/stacktab")
)
CATALOGUE = PRODUCT / "data/stacktab/catalogue.json"
PORT = 3318
VENDOR_BASE = f"http://127.0.0.1:{PORT}/vendor"

# ── the fixture's dates ───────────────────────────────────────────────────────────────
# Every plan was last checked on the night of the 14th. The four services the refresh task is
# about carry distinctive older verified_at stamps, so "the drifted row kept the date it was last
# actually true" is a value a grader can name rather than a difference it has to infer.
LAST_CHECKED = "2026-09-14T06:20:00+00"
VERIFIED_DEFAULT = "2026-09-14T06:20:00+00"
VERIFIED_OVERRIDE = {
    "neon": "2026-09-02T06:20:00+00",
    "vercel": "2026-09-05T06:20:00+00",
    "polar": "2026-09-08T06:20:00+00",
    "clerk": "2026-09-11T06:20:00+00",
}

# ── the four perturbations ────────────────────────────────────────────────────────────
DRIFT_SERVICE = "neon"
DRIFT_PLAN = "launch"
DRIFT_PROBE = "$0.002 per branch-hour"

DIGIT_SERVICE = "vercel"
DIGIT_PLAN = "pro"
DIGIT_PROBE = "$20"
DIGIT_ON_PAGE = "$200"

MISSING_PAGE_SERVICE = "clerk"
SHORT_PAGE_SERVICE = "polar"

# ── the watch list ────────────────────────────────────────────────────────────────────
# Four invented readers on .example domains. Two rows carry the SAME address on two different
# scopes, which is the fixture's own proof that the scope is part of the identity of a row.
WATCHERS = [
    ("rhoda.pemberton@ashcombe-labs.example", None, "2026-08-20T09:14:00+00", False),
    ("rhoda.pemberton@ashcombe-labs.example", "neon", "2026-08-21T11:02:00+00", False),
    ("desmond.aikawa@brightpier.example", "clerk", "2026-09-01T16:48:00+00", True),
    ("tobias.rennick@stonemill-freight.example", "vercel", "2026-09-05T08:31:00+00", False),
]

FILLER = (
    "Pricing is billed monthly in arrears and every figure on this page is what the account is "
    "charged in United States dollars. Usage above an included allowance is metered and appears "
    "on the following statement. Annual agreements are available for teams that want a fixed "
    "commitment, and support response times are stated in the service agreement rather than "
    "here. Taxes are added where the account's billing address requires them. Nothing on this "
    "page is a quote and the figures are reviewed whenever a plan changes."
)


def q(s):
    """Postgres literal, or NULL."""
    if s is None:
        return "null"
    if isinstance(s, bool):
        return "true" if s else "false"
    if isinstance(s, (int, float)):
        return repr(s)
    return "'" + str(s).replace("'", "''") + "'"


def arr(items):
    """text[] literal."""
    if not items:
        return "'{}'::text[]"
    return "array[" + ", ".join(q(i) for i in items) + "]::text[]"


def jsonb(obj):
    return q(json.dumps(obj, sort_keys=True)) + "::jsonb"


def page_html(service, lines):
    body = "\n".join(f"      <li>{line}</li>" for line in lines)
    return f"""<!doctype html>
<meta charset="utf-8">
<title>{service['name']} pricing</title>
<!-- Fixture page for envs/stacktab-desk. Written by scripts/build-fixture.py. It is what
     engine/refresh.mjs reads instead of the vendor's own site, so this environment never opens
     a socket to anybody's marketing page. -->
<body>
  <main>
    <h1>{service['name']} pricing</h1>
    <p>{service['tagline'] or ''}</p>
    <ul>
{body}
    </ul>
    <p>{FILLER}</p>
    <p>{FILLER}</p>
  </main>
</body>
"""


def short_page_html(service):
    """Under 500 characters once toText() has stripped it. fetchPage calls that unreadable."""
    return f"""<!doctype html>
<meta charset="utf-8">
<title>{service['name']}</title>
<body><main><h1>{service['name']}</h1><p>Pricing has moved.</p></main></body>
"""


def main() -> int:
    data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    services = data["services"]

    vendor_dir = HERE / "vendor-pages"
    for old in vendor_dir.glob("*.html"):
        old.unlink()

    out = []
    w = out.append
    w("-- stacktab-desk fixture. GENERATED by scripts/build-fixture.py; edit that, not this.")
    w("--")
    w("-- The catalogue is the product's own frozen snapshot of 2026-09-13 (29 services, 64")
    w("-- plans, 103 meters), with three things replaced: every source_url points at a local")
    w("-- fixture page this environment serves, the verification state is set to a known night,")
    w("-- and the watch list is four invented readers on .example domains.")
    w("--")
    w("-- The vendor names and published figures are the product's real catalogue. Nothing else")
    w("-- here is real: no address, no page, and no verification date.")
    w("")
    w("truncate table public.stacktab_price_watch restart identity;")
    w("truncate table public.stacktab_refresh_run restart identity;")
    w("truncate table public.stacktab_meter, public.stacktab_plan, public.stacktab_service"
      " restart identity cascade;")
    w("")

    # ── services ─────────────────────────────────────────────────────────────────────
    w("insert into public.stacktab_service"
      " (slug, name, category, tagline, homepage_url, pricing_url, attrs, rank) values")
    rows = []
    for s in services:
        rows.append(
            "  (%s, %s, %s, %s, %s, %s, %s, %s)"
            % (
                q(s["slug"]), q(s["name"]), q(s["category"]), q(s["tagline"]),
                q(s["homepage_url"]), q(f"{VENDOR_BASE}/{s['slug']}.html"),
                jsonb(s["attrs"]), q(s["rank"]),
            )
        )
    w(",\n".join(rows) + ";")
    w("")

    # ── plans ────────────────────────────────────────────────────────────────────────
    plan_rows = []
    meter_rows = []
    meter_id = 0
    drift_plan_id = digit_plan_id = None
    unreadable_ids, drifted_ids, verified_ids = [], [], []

    for s in services:
        for p in s["plans"]:
            probes = list(p["probes"])
            if s["slug"] == DIGIT_SERVICE and p["plan_slug"] == DIGIT_PLAN:
                # The bare-figure probe shape the catalogue really uses (the frozen run's own
                # drift detail carries '$15' and '$0.06 / GB'). It replaces the decorated form so
                # the digit guard is the ONLY thing that can fail on this plan.
                probes = [DIGIT_PROBE] + [x for x in probes if x != "$20 /mo."]
                digit_plan_id = p["id"]
                drifted_ids.append(p["id"])
            elif s["slug"] == DRIFT_SERVICE and p["plan_slug"] == DRIFT_PLAN:
                drift_plan_id = p["id"]
                drifted_ids.append(p["id"])
            elif s["slug"] in (MISSING_PAGE_SERVICE, SHORT_PAGE_SERVICE):
                unreadable_ids.append(p["id"])
            else:
                verified_ids.append(p["id"])

            verified_at = VERIFIED_OVERRIDE.get(s["slug"], VERIFIED_DEFAULT)
            plan_rows.append(
                "  (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'verified', %s, %s, null)"
                % (
                    q(p["id"]), q(s["slug"]), q(p["plan_slug"]), q(p["name"]), q(p["rank"]),
                    q(p["base_monthly_usd"]), q(p["price_status"]), jsonb(p["included"]),
                    jsonb(p["restrictions"]), q(p["notes"]),
                    q(f"{VENDOR_BASE}/{s['slug']}.html"),
                    q(verified_at), q(LAST_CHECKED),
                )
            )
            for m in p["meters"]:
                meter_id += 1
                meter_rows.append(
                    "  (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    % (
                        q(meter_id), q(p["id"]), q(m["meter_slug"]), q(m["label"]), q(m["unit"]),
                        q(m["kind"]), q(m["included_qty"]), q(m["unit_price"]), q(m["pct_rate"]),
                        q(m["fixed_usd"]),
                        ("null" if m["tiers"] is None else jsonb(m["tiers"])),
                        q(m["price_status"]), q(m["notes"]),
                    )
                )

    w("insert into public.stacktab_plan"
      " (id, service_slug, plan_slug, name, rank, base_monthly_usd, price_status, included,"
      " restrictions, notes, source_url, probes, check_status, verified_at, last_checked_at,"
      " last_check_note) values")
    # probes has to be an array expression, so it is spliced in per row rather than quoted.
    spliced = []
    idx = 0
    for s in services:
        for p in s["plans"]:
            probes = list(p["probes"])
            if s["slug"] == DIGIT_SERVICE and p["plan_slug"] == DIGIT_PLAN:
                probes = [DIGIT_PROBE] + [x for x in probes if x != "$20 /mo."]
            head, tail = plan_rows[idx].rsplit(", 'verified'", 1)
            spliced.append(f"{head}, {arr(probes)}, 'verified'{tail}")
            idx += 1
    w(",\n".join(spliced) + ";")
    w("select setval(pg_get_serial_sequence('public.stacktab_plan', 'id'),"
      " (select max(id) from public.stacktab_plan));")
    w("")

    w("insert into public.stacktab_meter"
      " (id, plan_id, meter_slug, label, unit, kind, included_qty, unit_price, pct_rate,"
      " fixed_usd, tiers, price_status, notes) values")
    w(",\n".join(meter_rows) + ";")
    w("select setval(pg_get_serial_sequence('public.stacktab_meter', 'id'),"
      " (select max(id) from public.stacktab_meter));")
    w("")

    # ── the night before ─────────────────────────────────────────────────────────────
    w("-- The run that set the state above. A grader counts the runs, so there has to be exactly")
    w("-- one before the task starts.")
    w("insert into public.stacktab_refresh_run"
      " (id, started_at, finished_at, services, plans_checked, verified, drifted, unreadable,"
      " detail) values")
    w("  (1, '2026-09-14T06:20:01+00', '2026-09-14T06:20:14+00', %d, %d, %d, 0, 0, '[]'::jsonb);"
      % (len(services), len(plan_rows), len(plan_rows)))
    w("select setval(pg_get_serial_sequence('public.stacktab_refresh_run', 'id'),"
      " (select max(id) from public.stacktab_refresh_run));")
    w("")

    # ── the watch list ───────────────────────────────────────────────────────────────
    w("-- Four readers. `id` is `generated always as identity`, so an explicit id needs")
    w("-- `overriding system value`; a cheat writing this table by hand has to say it too.")
    w("insert into public.stacktab_price_watch (id, email, service_slug, created_at, unsubscribed)")
    w("overriding system value values")
    w(",\n".join(
        "  (%d, %s, %s, %s, %s)" % (i + 1, q(e), q(svc), q(created), q(unsub))
        for i, (e, svc, created, unsub) in enumerate(WATCHERS)
    ) + ";")
    w("select setval(pg_get_serial_sequence('public.stacktab_price_watch', 'id'),"
      " (select max(id) from public.stacktab_price_watch));")
    w("")

    (HERE / "sql" / "02-seed.sql").write_text("\n".join(out) + "\n", encoding="utf-8")

    # ── the pages ────────────────────────────────────────────────────────────────────
    written = []
    for s in services:
        if s["slug"] == MISSING_PAGE_SERVICE:
            continue
        if s["slug"] == SHORT_PAGE_SERVICE:
            (vendor_dir / f"{s['slug']}.html").write_text(short_page_html(s), encoding="utf-8")
            written.append(s["slug"])
            continue
        lines = []
        for p in s["plans"]:
            for probe in p["probes"]:
                if s["slug"] == DRIFT_SERVICE and p["plan_slug"] == DRIFT_PLAN and probe == DRIFT_PROBE:
                    continue
                if s["slug"] == DIGIT_SERVICE and probe == "$20 /mo.":
                    lines.append(f"{p['name']} {DIGIT_ON_PAGE} /mo.")
                    continue
                lines.append(f"{p['name']} {probe}")
        # A plan whose every probe was skipped still needs its name on the page.
        if not lines:
            lines = [p["name"] for p in s["plans"]]
        (vendor_dir / f"{s['slug']}.html").write_text(page_html(s, lines), encoding="utf-8")
        written.append(s["slug"])

    print(f"services {len(services)}  plans {len(plan_rows)}  meters {len(meter_rows)}")
    print(f"pages    {len(written)} written, {MISSING_PAGE_SERVICE} deliberately absent")
    print(f"expected verified {len(verified_ids)}  drifted {len(drifted_ids)}"
          f"  unreadable {len(unreadable_ids)}")
    print(f"drift plan id {drift_plan_id}  digit-trap plan id {digit_plan_id}")
    print(f"unreadable plan ids {sorted(unreadable_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

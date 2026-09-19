/* GENERATE sql/02-seed.sql BY RUNNING THE PRODUCT'S OWN READER.
 *
 *   node scripts/make-seed.mjs        # rewrites sql/02-seed.sql
 *
 * ⛔ NOTHING IN HERE DECIDES WHAT A CONTRACT SAYS. The page strings come from
 * fixtures/contracts.mjs, and every state, date, quote, offset, page number and not-found reason
 * written below is whatever `parseDoc`, `readContract` and `evaluate` answered. Those are the same
 * three functions `readAndStore()` calls on upload and on every nightly pass, bundled out of the
 * live tree by scripts/build-product.sh. So the fixture is what the product WOULD have produced
 * from these documents, not what a fixture author believed it would produce.
 *
 * That distinction is the one the reference environment paid for: a seed written from what the
 * schema allows, rather than from what the code writes, produces graders that are correct about a
 * workflow the product does not have.
 *
 * ⛔ AND THE DATES ARE RELATIVE TO THE DAY IT RUNS, like the product's own seed-demo.ts, because a
 * notice deadline that lapsed three weeks ago leaves a queue with nothing due in it. The graders
 * never assert a date derived from today. They assert ids, states, relationships, and whether a
 * quoted span still re-slices out of the document it claims to come from.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CLAUSE_KINDS, evaluate, parseDoc, readContract } from "../.build/clause-extract.mjs";
import { signalTitle, worthRaising } from "../.build/nightly.mjs";
import { draftNonRenewal } from "../.build/notices.mjs";
import { SEEDED, UPLOAD, dayOut } from "../fixtures/contracts.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const TODAY = dayOut(0);

/* The separator the product puts in its own composed titles. `schedule()` writes
 * `Notice queued <sep> <subject>` and `draftNonRenewal` writes
 * `Notice of non-renewal <sep> <contract title>`, so it is READ BACK OUT of a real draft rather
 * than typed. Two reasons, and the second is the one that matters: this repository cannot emit
 * that character from a source file, and a typed copy would quietly stop matching the day the
 * product changes its own wording. */
const SEP = (() => {
  const probe = draftNonRenewal({
    orgName: "x",
    contractTitle: "T",
    counterparty: null,
    termEnd: null,
    noticeDeadline: null,
    quote: "q",
  }).subject;
  return probe.slice("Notice of non-renewal ".length, probe.length - "T".length - 1);
})();

/* ── Deterministic ids ────────────────────────────────────────────────────────────────────────
 * Readable enough that a grader addresses a row without a lookup, and stable across resets. */
const ORG_A = "00000000-0000-4000-8000-000000000001"; // Harborline Logistics, paid and active
const ORG_B = "00000000-0000-4000-8000-000000000002"; // Dunmere Cold Chain, subscription cancelled
/* ⛔ THE AUTH USER ID IS NAMESPACED TO THIS PRODUCT, and it has to be. `auth.users` is the ONE
 * table the estate's local stack genuinely shares: every product has its own `cw_`/`cd_`/... row
 * space, and they all sign in against the same Supabase auth schema. unemploy-desk's fixture
 * operator already holds `...-00000000000a`, so an id copied from that environment collides on
 * `users_pkey` at bring-up, under a different email, with a message that says nothing about
 * which two environments are fighting. The `c0` prefix is this product's. */
const DESK_USER = "00000000-0000-4000-8000-0000000c0001";
const MEMBER = "00000000-0000-4000-8000-0000000c0002";

const CONTRACT = {
  yard: "00000000-0000-4000-8000-000000001101",
  terminal: "00000000-0000-4000-8000-000000001102",
  rothbury: "00000000-0000-4000-8000-000000001103",
  ostergaard: "00000000-0000-4000-8000-000000001104",
  kessler: "00000000-0000-4000-8000-000000001105",
  marwood: "00000000-0000-4000-8000-000000001106",
};
const RUN = { a: "00000000-0000-4000-8000-000000002101", b: "00000000-0000-4000-8000-000000002102" };
const SIGNAL = {
  yard: "00000000-0000-4000-8000-000000003101",
  terminal: "00000000-0000-4000-8000-000000003102",
  rothbury: "00000000-0000-4000-8000-000000003103",
  ostergaard: "00000000-0000-4000-8000-000000003104",
  kessler: "00000000-0000-4000-8000-000000003105",
  marwood: "00000000-0000-4000-8000-000000003106",
};
const NOTICE = {
  ostergaard: "00000000-0000-4000-8000-000000004101",
  kessler: "00000000-0000-4000-8000-000000004102",
  marwood: "00000000-0000-4000-8000-000000004103",
};

const ORG_NAME = { [ORG_A]: "Harborline Logistics", [ORG_B]: "Dunmere Cold Chain" };
const NOTICE_FROM = {
  [ORG_A]: "desk@harborlinelogistics.example",
  [ORG_B]: "desk@dunmerecoldchain.example",
};
const DESK_EMAIL = "desk@harborlinelogistics.example";

/* ── SQL literals ─────────────────────────────────────────────────────────────────────────────*/
const q = (v) => (v === null || v === undefined ? "null" : `'${String(v).replace(/'/g, "''")}'`);
const num = (v) => (v === null || v === undefined ? "null" : String(v));
const bool = (v) => (v === null || v === undefined ? "null" : v ? "true" : "false");
const jsonb = (v) => (v === null || v === undefined ? "null" : `${q(JSON.stringify(v))}::jsonb`);
const intArr = (a) => `'{${a.join(",")}}'::integer[]`;
const textArr = (a) => `'{${a.map((s) => `"${s}"`).join(",")}}'::text[]`;
/** A timestamp relative to the moment the seed is APPLIED, not the moment it was generated.
 *  `db.reset()` runs this file before every episode, so a kill window written as an absolute
 *  instant would already have elapsed by the second episode. */
const rel = (expr) => `now() ${expr}`;

/* ── Read every contract with the product's own loop ──────────────────────────────────────────*/
const read = new Map();
for (const c of SEEDED) {
  const doc = parseDoc(c.pages);
  const reading = readContract(doc);
  const state = evaluate(reading, TODAY);
  read.set(c.key, { c, doc, reading, state, orgId: c.org === "b" ? ORG_B : ORG_A });
}

/* ⛔ THE FIXTURE ASSERTS ITS OWN PREMISES AND REFUSES TO WRITE A SEED THAT DOES NOT HOLD THEM.
 * Each line below is a fact a task's reward depends on. If a locator, a cue or a threshold moves
 * in the product, this stops here with the name of the premise rather than letting five graders
 * fail three weeks later with no explanation. */
const premises = [
  ["yard reads closing", () => read.get("yard").state.state === "closing"],
  ["yard has a quotable notice clause", () => read.get("yard").reading.notice_period.found],
  ["terminal reads approaching", () => read.get("terminal").state.state === "approaching"],
  [
    "terminal shares the yard's counterparty",
    () => read.get("terminal").c.counterparty === read.get("yard").c.counterparty,
  ],
  ["terminal raises a queue row at all", () => worthRaising("clear", read.get("terminal").state.state)],
  ["rothbury reads unknown", () => read.get("rothbury").state.state === "unknown"],
  ["rothbury blocks on term_end", () => read.get("rothbury").state.blockedBy.includes("term_end")],
  ["rothbury has NO term_end span to quote", () => !read.get("rothbury").reading.term_end.found],
  ["ostergaard has a quotable notice clause", () => read.get("ostergaard").reading.notice_period.found],
  ["kessler has a quotable notice clause", () => read.get("kessler").reading.notice_period.found],
  ["marwood has a quotable notice clause", () => read.get("marwood").reading.notice_period.found],
];

/* The uploaded document is not seeded. It is read here only so this script can refuse to ship a
 * fixture whose upload task has stopped being the task it was written as. */
const up = (() => {
  const doc = parseDoc(UPLOAD.pages);
  const reading = readContract(doc);
  return { doc, reading, state: evaluate(reading, TODAY) };
})();
premises.push(
  ["upload doc reads unknown", () => up.state.state === "unknown"],
  [
    "upload doc's term_end is ambiguous, not merely absent",
    () => !up.reading.term_end.found && up.reading.term_end.reason === "ambiguous-multiple",
  ],
  ["upload doc's notice period IS readable", () => up.reading.notice_period.found],
  [
    "upload doc blocks on term_end alone",
    () => up.state.blockedBy.length === 1 && up.state.blockedBy[0] === "term_end",
  ],
);

const broken = premises.filter(([, f]) => !f()).map(([name]) => name);
if (broken.length) {
  console.error("the fixture no longer holds its own premises:");
  for (const b of broken) console.error(`  - ${b}`);
  console.error("\nrun `node scripts/probe.mjs` to see what the extractor answers now.");
  process.exit(1);
}

/* ── Rows ─────────────────────────────────────────────────────────────────────────────────────*/
const out = [];
const w = (s) => out.push(s);

w(`-- GENERATED by scripts/make-seed.mjs on ${new Date().toISOString()}. Do not hand-edit.`);
w(`-- Every state, date, quote and offset below was produced by the product's own`);
w(`-- parseDoc/readContract/evaluate over fixtures/contracts.mjs, evaluated against ${TODAY}.`);
w(`--`);
w(`-- Applied before every episode. TRUNCATE plus INSERT, and it touches only cw_ tables, so it`);
w(`-- shares the estate's one local stack with every other product's fixture.`);
w("");
w("truncate table cw_events, cw_notices, cw_signals, cw_runs, cw_clauses, cw_contracts,");
w("               cw_entitlements, cw_members, cw_orgs restart identity cascade;");
w("");

w("-- == the two tenants ====================================================================");
w("-- DUNMERE STOPPED PAYING, AND NOTHING ABOUT ITS ROWS SAYS SO. `plan` still reads 'standard'");
w("-- because Stripe's customer.subscription.deleted moves billing_status and never touches plan.");
w("-- isEntitled() is the PAIR, so this org is out, and the outbox sweep withholds its mail");
w("-- rather than cancelling it.");
w(
  `insert into cw_orgs (id, name, plan, billing_status, is_demo, notice_from, created_at) values\n` +
    `  (${q(ORG_A)}, ${q(ORG_NAME[ORG_A])}, 'standard', 'active',   false, ${q(NOTICE_FROM[ORG_A])}, ${rel("- interval '400 days'")}),\n` +
    `  (${q(ORG_B)}, ${q(ORG_NAME[ORG_B])}, 'standard', 'canceled', false, ${q(NOTICE_FROM[ORG_B])}, ${rel("- interval '330 days'")});`,
);
w("");
w("-- The desk's own login. requireMember() reads exactly this row and derives the org id from");
w("-- it; nothing downstream ever takes an org from the client.");
w(
  `insert into cw_members (id, user_id, org_id, email, role, created_at) values\n` +
    `  (${q(MEMBER)}, ${q(DESK_USER)}, ${q(ORG_A)}, ${q(DESK_EMAIL)}, 'owner', ${rel("- interval '400 days'")});`,
);
w("");
w(
  `insert into cw_entitlements (email, org_id, plan, billing_status, claimed_by, claimed_at) values\n` +
    `  (${q(DESK_EMAIL)}, ${q(ORG_A)}, 'standard', 'active', ${q(DESK_USER)}, ${rel("- interval '400 days'")});`,
);
w("");

w("-- == the book ===========================================================================");
for (const key of Object.keys(CONTRACT)) {
  const { c, doc, reading, state, orgId } = read.get(key);
  const notice = reading.notice_period;
  const noticeDays = notice.found && notice.value.type === "days" ? notice.value.days : null;
  w(
    `-- ${c.title} / ${c.counterparty}: ${state.state}` +
      `${state.noticeDeadline ? `, notice by ${state.noticeDeadline}` : ""}`,
  );
  w(
    `insert into cw_contracts (id, org_id, title, counterparty, source, file_name, page_count,` +
      ` page_starts, doc_text, watched, uploaded_at, last_read_at, last_state, term_end,` +
      ` notice_days, auto_renews, notice_deadline, blocked_by) values\n` +
      `  (${q(CONTRACT[key])}, ${q(orgId)}, ${q(c.title)}, ${q(c.counterparty)}, 'upload',` +
      ` ${q(c.fileName)}, ${doc.pageStarts.length}, ${intArr(doc.pageStarts)}, ${q(doc.text)},` +
      ` true, ${rel("- interval '30 days'")}, ${rel("- interval '9 hours'")},` +
      ` ${q(state.state)}, ${q(state.termEnd)}, ${num(noticeDays)}, ${bool(state.autoRenews)},` +
      ` ${q(state.noticeDeadline)}, ${textArr(state.blockedBy)});`,
  );
}
w("");

w("-- == every clause the reader located, and every one it refused to =======================");
w("-- THESE ARE clauseRow()'s OWN TWO SHAPES. A found clause carries a value AND a span AND the");
w("-- bytes at that span; a miss carries a reason and nothing else. The CHECK constraint in");
w("-- 01-schema.sql rejects anything in between, which is the database saying what locate.ts's");
w("-- verify() says.");
for (const key of Object.keys(CONTRACT)) {
  const { reading, orgId } = read.get(key);
  for (const kind of CLAUSE_KINDS) {
    const r = reading[kind];
    const cols =
      `insert into cw_clauses (org_id, contract_id, kind, found, value_json, span_page,` +
      ` span_start, span_end, quote, pattern, not_found_reason, read_at) values\n  (`;
    if (r.found) {
      w(
        cols +
          `${q(orgId)}, ${q(CONTRACT[key])}, ${q(kind)}, true, ${jsonb(r.value)}, ${r.span.page},` +
          ` ${r.span.start}, ${r.span.end}, ${q(r.span.quote)}, ${q(r.pattern)}, null,` +
          ` ${rel("- interval '9 hours'")});`,
      );
    } else {
      w(
        cols +
          `${q(orgId)}, ${q(CONTRACT[key])}, ${q(kind)}, false, null, null, null, null, null,` +
          ` null, ${q(r.reason)}, ${rel("- interval '9 hours'")});`,
      );
    }
  }
}
w("");

w("-- == last night's pass ==================================================================");
for (const [orgKey, orgId] of [["a", ORG_A], ["b", ORG_B]]) {
  const mine = [...read.values()].filter((r) => r.orgId === orgId);
  const notFound = mine.reduce(
    (n, r) => n + CLAUSE_KINDS.filter((k) => !r.reading[k].found).length,
    0,
  );
  w(
    `insert into cw_runs (id, org_id, today, started_at, finished_at, contracts_read,` +
      ` clauses_read, clauses_not_found, signals_raised, capped) values\n` +
      `  (${q(RUN[orgKey])}, ${q(orgId)}, ${q(TODAY)}, ${rel("- interval '9 hours'")},` +
      ` ${rel("- interval '8 hours 58 minutes'")}, ${mine.length},` +
      ` ${mine.length * CLAUSE_KINDS.length}, ${notFound}, ${mine.length}, false);`,
  );
}
w("");

w("-- == the morning queue ==================================================================");
/* What the pass writes: the span it raised on travels with the signal, copied off the clause that
 * produced the state. An `unknown` row reads term_end, which was never located, so it has nothing
 * to carry. */
const SIGNAL_PLAN = [
  { key: "yard", from: "approaching", status: "open" },
  { key: "terminal", from: "clear", status: "open" },
  { key: "rothbury", from: null, status: "open" },
  { key: "ostergaard", from: "approaching", status: "approved" },
  { key: "kessler", from: "clear", status: "approved" },
  { key: "marwood", from: "clear", status: "approved" },
];
for (const plan of SIGNAL_PLAN) {
  const { c, reading, state, orgId } = read.get(plan.key);
  const evidence = state.state === "unknown" ? reading.term_end : reading.notice_period;
  const span = evidence.found ? evidence.span : null;
  const clauseKind = state.state === "unknown" ? "term_end" : "notice_period";
  if (plan.key === "rothbury" && span !== null) {
    console.error("rothbury acquired a quotable span; task 2 no longer has its premise");
    process.exit(1);
  }
  w(
    `-- ${c.title}: ${plan.from ?? "first read"} to ${state.state}, ${plan.status}` +
      `${span ? "" : ", NO QUOTE"}`,
  );
  w(
    `insert into cw_signals (id, org_id, contract_id, run_id, kind, clause_kind, state_from,` +
      ` state_to, due_date, quote, span_page, span_start, span_end, status, raised_at,` +
      ` resolved_at) values\n  (${q(SIGNAL[plan.key])}, ${q(orgId)}, ${q(CONTRACT[plan.key])},` +
      ` ${q(orgId === ORG_A ? RUN.a : RUN.b)}, 'state_change', ${q(clauseKind)}, ${q(plan.from)},` +
      ` ${q(state.state)}, ${q(state.noticeDeadline)}, ${q(span?.quote ?? null)},` +
      ` ${num(span?.page ?? null)}, ${num(span?.start ?? null)}, ${num(span?.end ?? null)},` +
      ` ${q(plan.status)}, ${rel("- interval '9 hours'")},` +
      ` ${plan.status === "approved" ? rel("- interval '20 minutes'") : "null"});`,
  );
}
w("");

w("-- == the outbox ========================================================================");
w("-- EVERY ROW HERE IS WHAT schedule() WRITES, INCLUDING THE ARITHMETIC. send_after is");
w("-- created_at plus UNDO_WINDOW_SECONDS (90), and the dispatcher's own WHERE clause is");
w("-- `state = 'scheduled' and send_after <= now()`, so the first of these three is invisible to");
w("-- a sweep and the other two are due. The window is relative to the RESET, not to the day this");
w("-- file was generated: an absolute instant would have elapsed by the second episode.");
const NOTICE_PLAN = [
  {
    key: "ostergaard",
    /* Inside its kill window. A person changed their mind about this one. */
    sendAfter: rel("+ interval '90 seconds'"),
    created: rel("- interval '1 second'"),
  },
  {
    key: "kessler",
    /* The window elapsed eleven minutes ago and no sweep has run since. */
    sendAfter: rel("- interval '11 minutes'"),
    created: rel("- interval '12 minutes 30 seconds'"),
  },
  {
    key: "marwood",
    /* Due, and belongs to the organisation that stopped paying. */
    sendAfter: rel("- interval '14 minutes'"),
    created: rel("- interval '15 minutes 30 seconds'"),
  },
];

/** The draft and the evidence blob the approve route would have produced for one contract. */
function stagedFor(key) {
  const { c, reading, state, orgId } = read.get(key);
  const span = reading.notice_period.span;
  return {
    orgId,
    contract: c,
    draft: draftNonRenewal({
      orgName: ORG_NAME[orgId],
      contractTitle: c.title,
      counterparty: c.counterparty,
      termEnd: state.termEnd,
      noticeDeadline: state.noticeDeadline,
      quote: span.quote,
    }),
    evidence: {
      quote: span.quote,
      page: span.page,
      start: span.start,
      end: span.end,
      clauseKind: "notice_period",
    },
  };
}

for (const plan of NOTICE_PLAN) {
  const { orgId, contract, draft, evidence } = stagedFor(plan.key);
  w(`-- ${contract.title}, ${ORG_NAME[orgId]}`);
  w(
    `insert into cw_notices (id, org_id, contract_id, signal_id, channel, to_addr, subject, body,` +
      ` state, send_after, sent_at, cancelled_at, evidence, created_at) values\n` +
      `  (${q(NOTICE[plan.key])}, ${q(orgId)}, ${q(CONTRACT[plan.key])}, ${q(SIGNAL[plan.key])},` +
      ` 'email', ${q(NOTICE_FROM[orgId])}, ${q(draft.subject)}, ${q(draft.body)}, 'scheduled',` +
      ` ${plan.sendAfter}, null, null, ${jsonb(evidence)}, ${plan.created});`,
  );
}
w("");

w("-- == the record ========================================================================");
for (const plan of SIGNAL_PLAN) {
  const { c, reading, state, orgId } = read.get(plan.key);
  const evidence = state.state === "unknown" ? reading.term_end : reading.notice_period;
  const span = evidence.found ? evidence.span : null;
  const kind = state.state === "unknown" ? "not_found" : "state_change";
  const detail =
    state.state === "unknown"
      ? "Not found: term ends. No date was asserted."
      : `Notice deadline ${state.noticeDeadline} · term ends ${state.termEnd}`;
  w(
    `insert into cw_events (org_id, contract_id, signal_id, kind, title, detail, needs_you,` +
      ` evidence, at) values\n  (${q(orgId)}, ${q(CONTRACT[plan.key])}, ${q(SIGNAL[plan.key])},` +
      ` ${q(kind)}, ${q(signalTitle(plan.from, state.state, c.title))}, ${q(detail)},` +
      ` ${bool(state.state === "closing" || state.state === "missed")},` +
      ` ${span ? jsonb({ quote: span.quote, page: span.page, start: span.start, end: span.end }) : "'{}'::jsonb"},` +
      ` ${rel("- interval '9 hours'")});`,
  );
}
for (const plan of NOTICE_PLAN) {
  const { orgId, draft, evidence } = stagedFor(plan.key);
  w(
    `insert into cw_events (org_id, contract_id, signal_id, kind, title, detail, needs_you,` +
      ` evidence, at) values\n  (${q(orgId)}, ${q(CONTRACT[plan.key])}, ${q(SIGNAL[plan.key])},` +
      ` 'notice_scheduled', ${q(`Notice queued ${SEP} ${draft.subject}`)},` +
      ` 'Goes out in 90s unless killed.', false, ${jsonb(evidence)},` +
      ` ${rel("- interval '20 minutes'")});`,
  );
}
w("");

fs.writeFileSync(path.join(ROOT, "sql", "02-seed.sql"), out.join("\n") + "\n", "utf8");

/* The document the upload task puts on the file input. Written beside the seed so the two can
 * never drift: both come out of fixtures/contracts.mjs in the same run. */
const uploadText = UPLOAD.pages.join("\n\n");
fs.writeFileSync(path.join(ROOT, "fixtures", UPLOAD.fileName), uploadText, "utf8");

/* Constants the graders and the harness import, EMITTED rather than retyped. A grader that
 * hardcodes a quote is a grader that stops describing the product the day a cue moves. */
const facts = {
  generated_at: new Date().toISOString(),
  today: TODAY,
  separator: SEP,
  org_a: ORG_A,
  org_b: ORG_B,
  org_a_name: ORG_NAME[ORG_A],
  org_b_name: ORG_NAME[ORG_B],
  desk_user: DESK_USER,
  desk_email: DESK_EMAIL,
  notice_from_a: NOTICE_FROM[ORG_A],
  notice_from_b: NOTICE_FROM[ORG_B],
  contracts: CONTRACT,
  signals: SIGNAL,
  notices: NOTICE,
  titles: Object.fromEntries([...read.entries()].map(([k, v]) => [k, v.c.title])),
  counterparties: Object.fromEntries([...read.entries()].map(([k, v]) => [k, v.c.counterparty])),
  states: Object.fromEntries([...read.entries()].map(([k, v]) => [k, v.state.state])),
  deadlines: Object.fromEntries([...read.entries()].map(([k, v]) => [k, v.state.noticeDeadline])),
  notice_quote: Object.fromEntries(
    [...read.entries()].map(([k, v]) => [
      k,
      v.reading.notice_period.found ? v.reading.notice_period.span.quote : null,
    ]),
  ),
  notice_span: Object.fromEntries(
    [...read.entries()].map(([k, v]) => [
      k,
      v.reading.notice_period.found
        ? {
            page: v.reading.notice_period.span.page,
            start: v.reading.notice_period.span.start,
            end: v.reading.notice_period.span.end,
          }
        : null,
    ]),
  ),
  subjects: Object.fromEntries(
    [...read.entries()]
      .filter(([, v]) => v.reading.notice_period.found)
      .map(([k]) => [k, stagedFor(k).draft.subject]),
  ),
  upload: {
    file_name: UPLOAD.fileName,
    title: UPLOAD.title,
    counterparty: UPLOAD.counterparty,
    byte_length: Buffer.byteLength(uploadText, "utf8"),
    /* ⛔ THE PARSED TEXT, NOT THE FILE, AND THE DIFFERENCE COST A WHOLE ROUND OF CHEATS.
     * `parseDoc` joins wrapped lines and appends a blank line per page, so what the product
     * STORES is two characters longer than what is on disk. The adversarial cheats build their
     * honest half out of this string and the graders measure against this length, because a
     * fixture that inserts the raw file is not inserting what the upload route inserts: every
     * cheat then fails on the length rather than on the guard it was written for, and eight
     * graders read green while grading one thing eight times. */
    doc_text: up.doc.text,
    /* Every clause the product's own reader locates in that document, in the shape
     * `clauseRow()` writes. The cheats insert exactly these rows and change one column, so the
     * only thing wrong with a cheat is the thing the cheat did. */
    clauses: Object.fromEntries(
      CLAUSE_KINDS.map((k) => {
        const r = up.reading[k];
        return [
          k,
          r.found
            ? {
                found: true,
                value: r.value,
                page: r.span.page,
                start: r.span.start,
                end: r.span.end,
                quote: r.span.quote,
                pattern: r.pattern,
              }
            : { found: false, reason: r.reason, detail: r.detail ?? null },
        ];
      }),
    ),
    doc_text_length: up.doc.text.length,
    page_count: up.doc.pageStarts.length,
    state: up.state.state,
    blocked_by: up.state.blockedBy,
    term_end_reason: up.reading.term_end.found ? null : up.reading.term_end.reason,
    /** The two dates the document disagrees about. The product never writes either one; the
     *  cheats in adversarial/ try to write one of them. */
    contested: up.reading.term_end.found
      ? []
      : String(up.reading.term_end.detail ?? "").split(" · "),
    found_kinds: CLAUSE_KINDS.filter((k) => up.reading[k].found),
    missing_kinds: CLAUSE_KINDS.filter((k) => !up.reading[k].found),
    notice_days: up.reading.notice_period.found ? up.reading.notice_period.value.days : null,
  },
  clause_kinds: [...CLAUSE_KINDS],
};
fs.writeFileSync(path.join(ROOT, "fixtures", "facts.json"), JSON.stringify(facts, null, 2) + "\n");

console.log(`wrote sql/02-seed.sql            (${out.length} lines, evaluated against ${TODAY})`);
console.log(`wrote fixtures/${UPLOAD.fileName}  (${facts.upload.byte_length} bytes)`);
console.log(`wrote fixtures/facts.json`);
console.log(
  `\nstates: ${Object.entries(facts.states).map(([k, v]) => `${k}=${v}`).join("  ")}`,
);
console.log(
  `upload: ${facts.upload.state}, term_end ${facts.upload.term_end_reason},` +
    ` contested ${facts.upload.contested.join(" vs ")}`,
);

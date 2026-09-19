/* WHAT THE PRODUCT'S OWN EXTRACTOR MAKES OF THE FIXTURE. Read this output before believing
 * anything a grader asserts about a clause.
 *
 *   node scripts/probe.mjs
 *
 * ⛔ THIS IS NOT A TEST. It is the thing that stopped the fixture being written from what the
 * prose "obviously" says. The contracts in fixtures/contracts.mjs are ordinary English and a
 * person reading them knows what each clause means. The locator is a set of cue regexes and a
 * span verifier, and what IT reads is the only thing that reaches the database.
 */
import { parseDoc, readContract, evaluate, CLAUSE_KINDS } from "../.build/clause-extract.mjs";
import { worthRaising, signalTitle } from "../.build/nightly.mjs";
import { draftNonRenewal } from "../.build/notices.mjs";
import { SEEDED, UPLOAD, dayOut } from "../fixtures/contracts.mjs";

const today = dayOut(0);
console.log(`today = ${today}\n`);

function show(label, pages) {
  const doc = parseDoc(pages);
  const reading = readContract(doc);
  const state = evaluate(reading, today);
  console.log(`== ${label}`);
  console.log(
    `   state=${state.state} termEnd=${state.termEnd} deadline=${state.noticeDeadline}` +
      ` autoRenews=${state.autoRenews} blockedBy=[${state.blockedBy}]`,
  );
  for (const k of CLAUSE_KINDS) {
    const r = reading[k];
    if (r.found) {
      const ok = doc.text.slice(r.span.start, r.span.end) === r.span.quote;
      console.log(
        `   ${k.padEnd(15)} FOUND  ${JSON.stringify(r.value)}  p${r.span.page}` +
          ` [${r.span.start},${r.span.end}] reslice=${ok ? "ok" : "DRIFTED"}`,
      );
      console.log(`   ${"".padEnd(15)}        "${r.span.quote.slice(0, 110)}"`);
    } else {
      console.log(`   ${k.padEnd(15)} not found: ${r.reason}${r.detail ? ` (${r.detail})` : ""}`);
    }
  }
  console.log(
    `   worthRaising(null -> ${state.state}) = ${worthRaising(null, state.state)}` +
      `   title = ${JSON.stringify(signalTitle(null, state.state, label))}`,
  );
  const ev = state.state === "unknown" ? reading.term_end : reading.notice_period;
  console.log(`   signal quote would be: ${ev.found ? JSON.stringify(ev.span.quote.slice(0, 60)) : "NULL"}`);
  console.log();
  return { doc, reading, state };
}

for (const c of SEEDED) show(`${c.title} / ${c.counterparty}${c.org === "b" ? " (org B)" : ""}`, c.pages);
const up = show(`UPLOAD: ${UPLOAD.title} / ${UPLOAD.counterparty}`, UPLOAD.pages);

console.log("== the drafted notice for the yard agreement");
const yard = SEEDED[0];
const yd = parseDoc(yard.pages);
const yr = readContract(yd);
const ys = evaluate(yr, today);
const draft = draftNonRenewal({
  orgName: "Harborline Logistics",
  contractTitle: yard.title,
  counterparty: yard.counterparty,
  termEnd: ys.termEnd,
  noticeDeadline: ys.noticeDeadline,
  quote: yr.notice_period.found ? yr.notice_period.span.quote : "",
});
console.log(JSON.stringify(draft.subject));
console.log(draft.body);
console.log(`\nupload doc_text length = ${up.doc.text.length}, pageStarts = [${up.doc.pageStarts}]`);

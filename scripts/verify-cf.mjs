/* The routes this console actually serves, checked against the deployed Worker.
 * `/evals` was checked here until 2026-09-20 and no longer exists: the scorecard is the root. */
const base = process.argv[2];
if (!base) throw new Error("usage: node scripts/verify-cf.mjs <base-url>");

for (const route of ["/", "/environments", "/parserail"]) {
  const response = await fetch(`${base}${route}`, { redirect: "follow" });
  const body = await response.text();
  if (!response.ok || !body.includes("Compound Evals")) {
    throw new Error(`${route} failed (${response.status})`);
  }
  console.log(`${route} -> ${response.status}`);
}

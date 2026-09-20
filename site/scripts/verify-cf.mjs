const base = process.argv[2];
if (!base) throw new Error("usage: node scripts/verify-cf.mjs <base-url>");

for (const route of ["/evals", "/environments"]) {
  const response = await fetch(`${base}${route}`, { redirect: "follow" });
  const body = await response.text();
  if (!response.ok || !body.includes("Compound") || !body.includes("EVALS")) {
    throw new Error(`${route} failed (${response.status})`);
  }
  console.log(`${route} -> ${response.status}`);
}

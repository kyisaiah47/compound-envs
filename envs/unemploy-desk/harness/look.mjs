/* What the signed-in desk actually offers, read off the running page.
 *
 * Writes a screenshot and prints every interactive element with its accessible name, which is
 * what a rollout has to address. Run it before writing or changing any rollout: the alternative
 * is addressing controls that were inferred from the schema, which is how the first taskset in
 * this repo ended up grading a workflow the app does not have.
 *
 *   node harness/look.mjs [path]
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3773";
const TARGET = process.argv[2] || "/";

const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));

const browser = await launchSafe(puppeteer, { headless: true });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await browser.setCookie(...session.cookies);
  await page.goto(`${APP}${TARGET}`, { waitUntil: "networkidle2", timeout: 60000 });

  const shot = path.join(HERE, `look${TARGET.replace(/\W+/g, "-")}.png`);
  await page.screenshot({ path: shot, fullPage: true });

  const found = await page.evaluate(() => {
    const name = (el) =>
      (
        el.getAttribute("aria-label") ||
        el.textContent ||
        el.getAttribute("placeholder") ||
        el.value ||
        ""
      )
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 80);
    const pick = (sel) => [...document.querySelectorAll(sel)].map((el) => ({
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      type: el.getAttribute("type"),
      href: el.getAttribute("href"),
      name: name(el),
    }));
    return {
      title: document.title,
      h1: [...document.querySelectorAll("h1,h2")].map((h) => h.textContent.trim().slice(0, 70)),
      controls: pick("button, a[href], input, select, textarea"),
      tables: [...document.querySelectorAll("table")].map((t) => ({
        headers: [...t.querySelectorAll("th")].map((th) => th.textContent.trim()),
        rows: t.querySelectorAll("tbody tr").length,
      })),
    };
  });

  console.log(`title: ${found.title}`);
  console.log(`headings: ${found.h1.join(" | ")}`);
  console.log(`tables: ${JSON.stringify(found.tables)}`);
  console.log(`controls (${found.controls.length}):`);
  for (const c of found.controls) {
    const bits = [c.tag, c.id && `#${c.id}`, c.type && `[${c.type}]`, c.href && `-> ${c.href}`]
      .filter(Boolean)
      .join(" ");
    console.log(`  ${bits}  ${c.name}`);
  }
  console.log(`shot: ${shot}`);
} finally {
  await browser.close();
}

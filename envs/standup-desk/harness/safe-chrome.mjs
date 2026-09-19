/* Launch Chrome for a rollout: throwaway profile, headless, muted, and unable to hand a click
 * to another application.
 *
 * ⛔ WHY THE CLICK GUARD EXISTS. An agent driving a real product will eventually click a
 * `mailto:` or `tel:` link, and the operating system answers that by opening a mail client.
 * On a machine running many rollouts that is a pile of compose windows in front of whoever is
 * working, and none of it is visible to the script that caused it. Two layers stop it: Chrome's
 * own blocked-scheme list in the profile, and a capturing click handler that cancels the
 * navigation and records what would have opened on `window.__blockedExternalHrefs`, so a test
 * can still assert on the href.
 *
 * Headless only, on purpose. A visible window belongs to whoever is at the keyboard.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const BLOCKED_SCHEMES = [
  "mailto", "tel", "sms", "facetime", "facetime-audio", "maps", "webcal", "callto",
];

/** Override with DESK_CHROME when Chrome lives elsewhere. */
export const CHROME =
  process.env.DESK_CHROME ||
  (process.platform === "darwin"
    ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    : "/usr/bin/google-chrome");

const GUARD = `(() => {
  const BLOCKED = ${JSON.stringify(BLOCKED_SCHEMES)};
  window.__blockedExternalHrefs = [];
  const isExternal = (href) => {
    if (!href) return false;
    const m = /^([a-zA-Z][a-zA-Z0-9+.-]*):/.exec(href.trim());
    if (!m) return false;
    const s = m[1].toLowerCase();
    return !["http", "https", "blob", "data", "javascript", "about", "chrome"].includes(s);
  };
  document.addEventListener("click", (e) => {
    const a = e.target && e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    const href = a.getAttribute("href") || "";
    if (isExternal(href)) {
      e.preventDefault();
      e.stopImmediatePropagation();
      window.__blockedExternalHrefs.push(href);
    }
  }, true);
  const origOpen = window.open;
  window.open = function (url, ...rest) {
    if (isExternal(String(url || ""))) {
      window.__blockedExternalHrefs.push(String(url));
      return null;
    }
    return origOpen.call(this, url, ...rest);
  };
})();`;

function makeProfile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "desk-chrome-"));
  const def = path.join(dir, "Default");
  fs.mkdirSync(def, { recursive: true });
  fs.writeFileSync(
    path.join(def, "Preferences"),
    JSON.stringify({
      protocol_handler: {
        excluded_schemes: Object.fromEntries(BLOCKED_SCHEMES.map((s) => [s, true])),
      },
    }),
  );
  return dir;
}

async function guardPage(page) {
  await page.evaluateOnNewDocument(GUARD);
  return page;
}

export async function launchSafe(puppeteer, opts = {}) {
  if (opts.headless === false) {
    throw new Error("launchSafe is headless only: a visible window belongs to whoever is at the keyboard");
  }
  const userDataDir = makeProfile();
  const args = [...(opts.args || []), "--mute-audio"];
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    ...opts,
    headless: true,
    args,
    userDataDir,
  });

  const origNewPage = browser.newPage.bind(browser);
  browser.newPage = async () => guardPage(await origNewPage());
  for (const p of await browser.pages()) await guardPage(p);

  const origClose = browser.close.bind(browser);
  browser.close = async () => {
    try {
      await origClose();
    } finally {
      fs.rmSync(userDataDir, { recursive: true, force: true });
    }
  };
  return browser;
}

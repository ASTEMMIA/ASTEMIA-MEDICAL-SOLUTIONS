// Shared helpers for the browser checks: sign in through the development
// picker, scan with axe-core, and fail loudly.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
export const { chromium } = require("playwright");
export const BASE = process.env.BASE ?? "http://127.0.0.1:8078";
export const SHOTS = process.env.SHOTS;
const AXE = fileURLToPath(new URL("../node_modules/axe-core/axe.min.js", import.meta.url));

export function check(ok, what) {
  if (!ok) throw new Error(`FAILED: ${what}`);
  console.log(`  ok  ${what}`);
}

export async function shot(page, name) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

/** WCAG 2.2 A and AA rules; serious or critical findings fail the run. */
export async function axe(page, where) {
  await page.addScriptTag({ path: AXE });
  const result = await page.evaluate(() =>
    // eslint-disable-next-line no-undef
    window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] } }),
  );
  const bad = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  for (const v of bad) console.error(`  axe ${v.impact}: ${v.id} — ${v.help}\n    ${v.nodes.map((n) => n.target.join(" ")).join("\n    ")}`);
  check(bad.length === 0, `${where}: no serious or critical accessibility violations (${result.passes.length} rules pass)`);
}

/** True once focus is on the page's h1: it moves there just after the page renders. */
export async function headingFocused(page) {
  return page
    .waitForFunction(() => document.activeElement?.tagName === "H1", null, { timeout: 3000 })
    .then(() => true, () => false);
}

export async function signIn(page, displayName) {
  await page.goto(`${BASE}/app/`);
  await page.getByRole("button", { name: "Show accounts" }).click();
  await page.getByLabel(new RegExp(`^${displayName} `)).check();
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { level: 1, name: `Welcome, ${displayName}` }).waitFor();
}

export async function run(name, body) {
  const browser = await chromium.launch();
  // bypassCSP lets axe-core be injected for the scan; the policy itself is checked by request.
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, bypassCSP: true });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && !/status of 40[134]/.test(m.text()) && errors.push(m.text()));
  console.log(name);
  try {
    await body(page, context, browser);
    check(errors.length === 0, `no script errors${errors.length ? `: ${errors.join("; ")}` : ""}`);
  } catch (e) {
    await shot(page, "failure").catch(() => undefined);
    console.error(e);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

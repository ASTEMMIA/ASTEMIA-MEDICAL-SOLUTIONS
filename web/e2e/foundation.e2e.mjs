// The app shell against the real API: development sign-in for every seeded
// role, who and where you are, what you may do, keyboard use, accessibility,
// a phone-width layout, and signing out.
import { BASE, axe, check, headingFocused, run, shot, signIn } from "./lib.mjs";

const PEOPLE = [
  ["Registrar One", "Registrar", "Register patients"],
  ["Dr Clinician One", "Clinician", "Sign clinical notes"],
  ["Dr Clinician Two", "Clinician", "Sign clinical notes"],
  ["Nurse One", "Nurse", "Sign nursing notes"],
  ["Lab Scientist One", "Lab scientist", "Release results"],
  ["Identity Steward One", "Identity steward", "Merge and unmerge patient records"],
  ["Records Clerk One", "Records clerk", "Receive and file correspondence"],
  ["Team Supervisor One", "Team supervisor", "Supervise every Daybook task"],
  ["Safeguarding Lead One", "Safeguarding lead", "Review restrictive interventions and concerns"],
  ["Patient Advocate One", "Patient advocate", "See who accessed a patient's record"],
  ["Privacy Officer One", "Privacy officer", "Review emergency access"],
  ["Scheduler One", "Scheduler", "Book, reschedule and cancel appointments"],
];

await run("foundation", async (page, context) => {
  await page.goto(`${BASE}/app/`);
  check((await page.title()).includes("ASTEMIA"), "the app is served at /app/");
  check(await page.getByText("Development sign-in.").isVisible(), "development sign-in is labelled as such");
  await axe(page, "sign-in");
  await page.getByRole("button", { name: "Show accounts" }).click();
  const radios = page.getByRole("radio");
  await radios.first().waitFor();
  check((await radios.count()) === PEOPLE.length, `every seeded account is offered (${PEOPLE.length})`);
  await axe(page, "account picker");
  await shot(page, "01-sign-in");

  for (const [name, role, can] of PEOPLE) {
    await signIn(page, name);
    check(
      (await page.getByLabel("Organisation").textContent()) === "ASTEMIA Pilot Hospital (synthetic)",
      `${name}: the masthead names the organisation`,
    );
    check(await page.getByText(`· ${role}`).isVisible(), `${name}: the masthead shows the role`);
    await page.getByRole("link", { name: "My account" }).click();
    await page.getByRole("heading", { level: 1, name: "My account" }).waitFor();
    check(await page.getByText(can, { exact: true }).isVisible(), `${name}: may "${can}"`);
    const raw = await page.locator("main li").evaluateAll((items) => items.map((i) => i.textContent).filter((t) => /^[a-z_]+:[a-z_]+$/.test(t)));
    check(raw.length === 0, `${name}: every permission is described in words${raw.length ? ` (missing: ${raw})` : ""}`);
    if (name === "Registrar One") {
      check(!(await page.getByText("Read the charts of patients in your care").count()), "a registrar has no chart access");
    }
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("heading", { name: "Sign in to ASTEMIA Health" }).waitFor();
  }

  // Keyboard only. Each page focuses its heading, so walk the tab order back
  // from there: it runs through the navigation and masthead to the skip link,
  // the first stop in the document.
  await signIn(page, "Dr Clinician One");
  await axe(page, "home");
  await shot(page, "02-home");
  check(await headingFocused(page), "the signed-in page focuses its heading");
  const order = [];
  for (let i = 0; i < 12 && order.at(-1) !== "Skip to main content"; i++) {
    await page.keyboard.press("Shift+Tab");
    order.push(await page.evaluate(() => document.activeElement?.textContent?.trim()));
  }
  const nav = await page.getByRole("navigation", { name: "Main" }).getByRole("link").allTextContents();
  check(
    JSON.stringify(order) === JSON.stringify([...nav].reverse().concat(["Sign out", "Skip to main content"])),
    `a logical tab order back to the skip link (${order.join(" ← ")})`,
  );
  check(
    await page.evaluate(() => getComputedStyle(document.activeElement).top !== "-1000px" && document.activeElement.getBoundingClientRect().top >= 0),
    "the skip link is visible when focused",
  );
  await page.keyboard.press("Enter");
  check(await page.evaluate(() => document.activeElement?.id === "main"), "the skip link moves focus to the main content");
  await page.getByRole("link", { name: "My account" }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("heading", { level: 1, name: "My account" }).waitFor();
  check(await headingFocused(page), "a new page moves focus to its heading for screen readers");
  check((await page.title()).startsWith("My account"), "the window title names the page");
  await axe(page, "account");

  // A deep link survives a reload: the server returns the app for client routes.
  await page.reload();
  await page.getByRole("heading", { level: 1, name: "My account" }).waitFor();
  check(true, "a deep link survives a reload");

  // Strict headers on the app.
  const res = await page.request.get(`${BASE}/app/account`);
  const csp = res.headers()["content-security-policy"] ?? "";
  check(csp.includes("default-src 'self'") && csp.includes("frame-ancestors 'none'"), "a strict content security policy");

  // Phone width: no sideways scrolling.
  await page.setViewportSize({ width: 360, height: 780 });
  const wide = await page.evaluate(() =>
    [...document.querySelectorAll("body *")]
      .filter((e) => e.getBoundingClientRect().right > window.innerWidth + 0.5)
      .map((e) => `${e.tagName.toLowerCase()}${e.className ? "." + e.className : ""} "${e.textContent.slice(0, 30)}"`),
  );
  check(wide.length === 0, `no horizontal scrolling at 360 px${wide.length ? ` (too wide: ${wide.join(", ")})` : ""}`);
  await shot(page, "03-account-phone");
  await page.setViewportSize({ width: 1280, height: 900 });

  // An expired or revoked token returns the person to sign-in, saying why.
  await page.evaluate(() => sessionStorage.setItem("astemia.token", "not-a-token"));
  await page.reload();
  await page.getByText("Your session ended").waitFor();
  check(true, "an invalid session returns to sign-in with an explanation");
  check((await page.evaluate(() => sessionStorage.getItem("astemia.token"))) === null, "the bad token is discarded");

  // Signing out leaves nothing behind.
  await signIn(page, "Scheduler One");
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("heading", { name: "Sign in to ASTEMIA Health" }).waitFor();
  check((await page.evaluate(() => sessionStorage.length)) === 0, "sign-out clears the session from the browser");
  const fresh = await context.newPage();
  await fresh.goto(`${BASE}/app/account`);
  await fresh.getByRole("heading", { name: "Sign in to ASTEMIA Health" }).waitFor();
  check(true, "a new tab after sign-out asks for sign-in");
  await fresh.close();
});

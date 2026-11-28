// Web 3 end to end against the real API: clinic sessions, notes (draft, sign,
// correct), a referral with the patient's history, triage, booking from the
// referral, rescheduling, attendance, and a letter filed and reviewed.
import { fileURLToPath } from "node:url";
import { axe, check, run, shot, signIn } from "./lib.mjs";

const LETTER = fileURLToPath(new URL("./fixtures/clinic-letter.pdf", import.meta.url));
const nav = (page, name) => page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true }).click();
const signOut = async (page) => {
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("heading", { name: "Sign in to ASTEMIA Health" }).waitFor();
};
const pad = (n) => String(n).padStart(2, "0");
const tomorrow = new Date(Date.now() + 86_400_000);
const DAY = `${tomorrow.getFullYear()}-${pad(tomorrow.getMonth() + 1)}-${pad(tomorrow.getDate())}`;

async function openPatient(page, family) {
  await nav(page, "Patients");
  await page.getByRole("heading", { level: 1, name: "Patients" }).waitFor();
  await page.getByLabel("Family name").fill(family);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("link", { name: new RegExp(`^${family.toUpperCase()},`) }).first().click();
  await page.getByRole("heading", { level: 1, name: new RegExp(`^${family.toUpperCase()},`) }).waitFor();
}

await run("scheduling", async (page) => {
  // A patient admitted under Dr Clinician One.
  await signIn(page, "Registrar One");
  await nav(page, "Patients");
  await page.getByRole("link", { name: "Register a patient" }).click();
  await page.getByRole("heading", { level: 1, name: "Register a patient" }).waitFor();
  await page.getByLabel("Family name").fill("Eze");
  await page.getByLabel("Given names").fill("Ngozi");
  await page.getByLabel("Date of birth").fill("1966-11-02");
  await page.getByLabel("Sex").selectOption("female");
  await page.getByLabel("House number and street").fill("14 Ogui Road");
  await page.getByLabel("Town or city").fill("Enugu");
  await page.getByLabel("State", { exact: true }).selectOption("Enugu");
  await page.getByLabel("Local government area").fill("Enugu North");
  await page.getByLabel("Postcode").fill("400211");
  await page.getByRole("button", { name: "Register" }).click();
  await page.getByText("Patient registered.").waitFor();
  await page.getByLabel("Responsible clinician").selectOption({ label: "Dr Clinician One" });
  await page.getByLabel("Visit number").fill("V-2001");
  await page.getByRole("button", { name: "Admit", exact: true }).click();
  await page.getByText(/^Admitted: visit V-2001/).waitFor();
  await signOut(page);

  // 1. Scheduler: a cardiology session tomorrow.
  await signIn(page, "Scheduler One");
  await nav(page, "Sessions");
  await page.getByRole("heading", { level: 1, name: "Clinic sessions" }).waitFor();
  await page.getByRole("button", { name: "Create slots" }).click();
  check(await page.getByText("Choose the clinician.").first().isVisible(), "a session needs a clinician");
  await page.getByLabel("Clinician").selectOption({ label: "Dr Clinician One" });
  await page.getByLabel("Service").fill("cardiology");
  await page.getByLabel("Starts at").fill(`${DAY}T09:00`);
  await page.getByLabel("Number of slots").selectOption("3");
  await axe(page, "clinic sessions");
  await page.getByRole("button", { name: "Create slots" }).click();
  await page.getByText(/^3 slots created for Dr Clinician One, Cardiology/).waitFor();
  check(true, "a scheduler creates a run of slots");
  await signOut(page);

  // 2. Dr Clinician One: a note drafted, signed and corrected; a referral.
  await signIn(page, "Dr Clinician One");
  await openPatient(page, "Eze");
  await page.getByRole("button", { name: "Write a note" }).click();
  const write = page.getByRole("form", { name: "Write a note" });
  await write.getByLabel("Title").fill("Cardiology review");
  await write.getByLabel("Note", { exact: true }).fill("Exertional chest pain for 3 weeks. ECG: lateral T-wave inversion.");
  await axe(page, "write a note");
  await write.getByRole("button", { name: "Save draft" }).click();
  await page.getByText("Draft saved. Only you can see it until it is signed.").waitFor();
  const draft = page.getByRole("article", { name: "Draft: Cardiology review" });
  await draft.getByRole("button", { name: /^Edit draft/ }).click();
  await draft.getByLabel("Note", { exact: true }).fill("Exertional chest pain for 3 weeks. ECG: lateral T-wave inversion. Refer to cardiology.");
  await draft.getByRole("button", { name: "Save draft" }).click();
  await page.getByText("Draft updated.").waitFor();
  await page.getByRole("article", { name: "Draft: Cardiology review" }).getByRole("button", { name: /^Sign note/ }).click();
  await page.getByText(/^Note signed\./).waitFor();
  const signed = page.getByRole("article", { name: "Cardiology review", exact: true });
  await signed.getByText(/Refer to cardiology\.$/).waitFor();
  check(true, "the signed note is on the chart");
  await signed.getByRole("button", { name: /^Correct this note/ }).click();
  await signed.getByRole("button", { name: "Save correction" }).click();
  check(await signed.getByText("Say why the note is being corrected.").isVisible(), "a correction needs a reason");
  await signed.getByLabel("Corrected note").fill("Exertional chest pain for 3 weeks. ECG: lateral T-wave inversion. Troponin negative. Refer to cardiology.");
  await signed.getByLabel("Reason for the correction").fill("Troponin result added");
  await signed.getByRole("button", { name: "Save correction" }).click();
  await page.getByText(/^Correction saved as a draft/).waitFor();
  await page.getByRole("article", { name: "Draft: Cardiology review" }).getByRole("button", { name: /^Sign note/ }).click();
  await page.getByText(/^Note signed\./).waitFor();
  const corrected = page.getByRole("article", { name: "Cardiology review", exact: true });
  await corrected.getByText("revision 2", { exact: false }).waitFor();
  await corrected.getByText(/Troponin negative/).waitFor();
  check(true, "the signed correction replaces the note, as revision 2");

  await page.getByRole("button", { name: "Refer", exact: true }).click();
  const refer = page.getByRole("form", { name: "Refer" });
  await refer.getByLabel("Refer to").selectOption({ label: "ASTEMIA Teaching Hospital (synthetic), Main site" });
  await refer.getByLabel("Receiving service").fill("cardiology");
  await refer.getByLabel("Urgent").check();
  await refer.getByLabel("Reason for referral").fill("Exertional chest pain with lateral T-wave inversion");
  await axe(page, "referral form");
  await refer.getByRole("button", { name: "Send referral" }).click();
  await page.getByText(/^Referral sent to Cardiology \(Teaching hospital\), with \d+ records? from/).waitFor();
  check(true, "the referral goes to the teaching hospital with the patient's records");
  await shot(page, "01-chart-notes-referral");
  await signOut(page);

  // 3. Scheduler: triage, then book from the referral and reschedule.
  await signIn(page, "Scheduler One");
  await nav(page, "Referrals");
  const ref = page.getByRole("article", { name: /^Referral to Cardiology/ }).first();
  await ref.waitFor();
  await ref.getByText("Urgent").waitFor();
  check(true, "the triage list shows the priority");
  await ref.getByRole("button", { name: /^Read the records/ }).click();
  await ref.getByText(/General medicine at Main site, ASTEMIA Pilot Hospital/).first().waitFor();
  check(true, "the triage team reads the history sent with the referral");
  await axe(page, "referral triage");
  await ref.getByLabel("Reject").check();
  await ref.getByRole("button", { name: "Record decision" }).click();
  check(await ref.getByText(/Give the reason for rejecting/).isVisible(), "a rejection needs a reason");
  await ref.getByLabel("Accept").check();
  await ref.getByRole("button", { name: "Record decision" }).click();
  await page.getByText(/^Referral accepted for EZE, Ngozi/).waitFor();
  await page.getByLabel("Accepted, to book").check();
  await page.getByRole("link", { name: /^Book an appointment/ }).first().click();
  await page.getByRole("heading", { level: 1, name: "Book an appointment" }).waitFor();
  check(await page.getByText("Booking for an accepted referral").isVisible(), "booking from the referral says so");
  const choose = page.getByRole("button", { name: /^Choose/ });
  await choose.first().waitFor();
  check((await choose.count()) === 3, "the free cardiology slots are listed");
  await axe(page, "free slots");
  await choose.first().click();
  await page.getByText(/^Held for you until/).waitFor();
  await page.getByLabel("Reason for the appointment").fill("Cardiology review");
  await page.getByRole("button", { name: "Confirm the booking" }).click();
  await page.getByText(/^EZE, Ngozi: Cardiology on/).waitFor();
  check(true, "the appointment is booked from the referral");
  await page.getByRole("link", { name: "Go to the clinic list" }).click();
  await page.getByLabel("Day").fill(DAY);
  const visit = page.getByRole("article", { name: /EZE, Ngozi/ });
  await visit.waitFor();
  await axe(page, "clinic list");
  await visit.getByRole("link", { name: /^Reschedule/ }).click();
  await page.getByRole("heading", { level: 1, name: "Reschedule an appointment" }).waitFor();
  await page.getByRole("button", { name: /^Choose/ }).nth(1).click();
  await page.getByRole("button", { name: "Move the appointment" }).click();
  await page.getByText(/The original appointment is kept as rescheduled\./).waitFor();
  check(true, "the appointment is moved, keeping the original as rescheduled");
  await page.getByRole("link", { name: "Go to the clinic list" }).click();
  await page.getByLabel("Day").fill(DAY);
  const moved = page.getByRole("article", { name: /EZE, Ngozi/ });
  await moved.first().waitFor();
  check((await moved.count()) === 2, "the clinic list shows the rescheduled and the new appointment");
  const live = moved.filter({ has: page.getByText("Booked", { exact: true }) });
  await live.getByRole("button", { name: /^Record attendance/ }).click();
  await live.getByRole("button", { name: "Save" }).click();
  check(await live.getByText("Choose what happened.").isVisible(), "attendance needs an outcome");
  await live.getByLabel("Attended").check();
  await live.getByRole("button", { name: "Save" }).click();
  await page.getByText("EZE, Ngozi attended: the visit is open.").waitFor();
  check(true, "attendance opens the visit");
  await shot(page, "02-clinic-list");
  await signOut(page);

  // 4. Records clerk: a letter is received, matched and filed to Dr Clinician One.
  await signIn(page, "Records Clerk One");
  await nav(page, "Correspondence");
  await page.getByRole("button", { name: "Receive a document" }).click();
  const receive = page.getByRole("form", { name: "Receive a document" });
  await receive.getByLabel("From").fill("Enugu Heart Clinic");
  await receive.getByLabel("Title").fill("Echo report");
  await receive.getByLabel("File").setInputFiles(LETTER);
  await receive.getByLabel("Family name").fill("Eze");
  await receive.getByLabel("Given names").fill("Ngozi");
  await receive.getByLabel("Date of birth").fill("1966-11-02");
  await receive.getByLabel("Sex").selectOption("female");
  await axe(page, "receive a document");
  await receive.getByRole("button", { name: "Receive" }).click();
  await page.getByText("Received and quarantined until it is filed.").waitFor();
  const letter = page.getByRole("article", { name: "Echo report" });
  await letter.waitFor();
  await letter.getByRole("radio", { name: /^Eze N\., born 1966/ }).waitFor();
  check(await letter.getByRole("radio", { name: /^Eze N\., born 1966/ }).isChecked(), "the sender's details suggest the patient, with reasons");
  await letter.getByRole("button", { name: "File to the patient" }).click();
  check(await letter.getByText("Name the clinician who must review it.").isVisible(), "filing needs a named reviewer");
  await letter.getByLabel("Reviewer").selectOption({ label: "Dr Clinician One" });
  await axe(page, "file a document");
  await letter.getByRole("button", { name: "File to the patient" }).click();
  await page.getByText("Filed to the patient's chart and sent to the reviewer.").waitFor();
  check(true, "the clerk files the letter to the patient");
  await signOut(page);

  // 5. Dr Clinician One reviews the letter from the chart.
  await signIn(page, "Dr Clinician One");
  await openPatient(page, "Eze");
  const echo = page.getByRole("article", { name: "Echo report" });
  await echo.getByText("Not yet reviewed").waitFor();
  const download = page.waitForEvent("download");
  await echo.getByRole("button", { name: /^Download the original/ }).click();
  const saved = (await download).suggestedFilename();
  check(saved === "Echo report.pdf", `the original file opens for the reviewer (${saved})`);
  await echo.getByLabel("Review note").fill("Normal LV function. Continue cardiology referral.");
  await echo.getByRole("button", { name: /^Mark as reviewed/ }).click();
  await page.getByRole("article", { name: "Echo report" }).getByText(/^Reviewed .*Normal LV function/).waitFor();
  check(true, "the named reviewer marks the letter reviewed");
  await axe(page, "chart with notes and correspondence");
  await page.setViewportSize({ width: 360, height: 780 });
  check(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "the chart fits a 360 px screen");
});

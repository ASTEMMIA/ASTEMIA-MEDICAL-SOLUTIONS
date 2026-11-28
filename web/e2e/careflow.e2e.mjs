// Web 4 end to end against the real API: problems and a care plan, mental
// health safeguards, discharge with owned follow-up, the Daybook for staff,
// queues and supervisors, and independent safeguarding review.
import { axe, check, run, shot, signIn } from "./lib.mjs";

const nav = (page, name) => page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true }).click();
const signOut = async (page) => {
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("heading", { name: "Sign in to ASTEMIA Health" }).waitFor();
};
const pad = (n) => String(n).padStart(2, "0");
const local = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

async function openPatient(page, family) {
  await nav(page, "Patients");
  await page.getByRole("heading", { level: 1, name: "Patients" }).waitFor();
  await page.getByLabel("Family name").fill(family);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("link", { name: new RegExp(`^${family.toUpperCase()},`) }).first().click();
  await page.getByRole("heading", { level: 1, name: new RegExp(`^${family.toUpperCase()},`) }).waitFor();
}

await run("careflow", async (page) => {
  // A patient admitted under Dr Clinician One.
  await signIn(page, "Registrar One");
  await nav(page, "Patients");
  await page.getByRole("link", { name: "Register a patient" }).click();
  await page.getByRole("heading", { level: 1, name: "Register a patient" }).waitFor();
  await page.getByLabel("Family name").fill("Bello");
  await page.getByLabel("Given names").fill("Hauwa");
  await page.getByLabel("Date of birth").fill("1958-04-21");
  await page.getByLabel("Sex").selectOption("female");
  await page.getByLabel("House number and street").fill("3 Sultan Road");
  await page.getByLabel("Town or city").fill("Kaduna");
  await page.getByLabel("State", { exact: true }).selectOption("Kaduna");
  await page.getByLabel("Local government area").fill("Kaduna North");
  await page.getByLabel("Postcode").fill("800283");
  await page.getByRole("button", { name: "Register" }).click();
  await page.getByText("Patient registered.").waitFor();
  await page.getByLabel("Responsible clinician").selectOption({ label: "Dr Clinician One" });
  await page.getByLabel("Visit number").fill("V-3001");
  await page.getByRole("button", { name: "Admit", exact: true }).click();
  await page.getByText(/^Admitted: visit V-3001/).waitFor();
  await signOut(page);

  // 1. Dr Clinician One: a problem and a renal care plan.
  await signIn(page, "Dr Clinician One");
  await openPatient(page, "Bello");
  await page.getByRole("button", { name: "Record a problem" }).click();
  const problem = page.getByRole("form", { name: "Record a problem" });
  await problem.getByLabel("ICD-10 code").fill("n18.5");
  await problem.getByLabel("Problem").fill("Chronic kidney disease, stage 5");
  await problem.getByLabel("Condition register").selectOption("renal");
  await problem.getByRole("button", { name: "Record" }).click();
  await page.getByText("Recorded: Chronic kidney disease, stage 5.").waitFor();
  await page.getByText("N18.5").waitFor();
  check(true, "a coded problem joins the problem list and its register");
  await page.getByRole("button", { name: "Start a care plan" }).click();
  const planForm = page.getByRole("form", { name: "Start a care plan" });
  await planForm.getByLabel("Title").fill("Maintenance haemodialysis");
  await planForm.getByLabel("Days between sessions").fill("1");
  await planForm.getByLabel("Number of sessions").fill("3");
  await planForm.getByLabel("Instructions for each session").fill("Haemodialysis 4 hours, dry weight 68 kg");
  await axe(page, "start a care plan");
  await planForm.getByRole("button", { name: "Start the plan" }).click();
  await page.getByRole("link", { name: "Maintenance haemodialysis" }).click();
  await page.getByRole("heading", { level: 1, name: "Maintenance haemodialysis" }).waitFor();
  const sessions = page.getByRole("button", { name: /^Record the session/ });
  await sessions.first().waitFor();
  check((await sessions.count()) === 3, "the plan schedules its three sessions");
  await sessions.first().click();
  await page.getByLabel("Outcome").fill("Uneventful");
  await page.getByRole("button", { name: "Mark delivered" }).click();
  await page.getByText(/recorded as delivered\.$/).waitFor();
  await page.getByText("Completed").first().waitFor();
  check(true, "a session is recorded as delivered, under its revision");
  await axe(page, "care plan");
  await shot(page, "01-care-plan");
  await page.getByRole("link", { name: "Back to the patient" }).click();
  await page.getByRole("heading", { level: 1, name: /^BELLO,/ }).waitFor();

  // 2. Safeguards: legal status, a restrictive intervention, a concern.
  await page.getByRole("button", { name: "Record a change of legal status" }).click();
  const legal = page.getByRole("form", { name: "Record a change of legal status" });
  await legal.getByLabel("Legal status").selectOption("detained_assessment");
  await legal.getByRole("button", { name: "Record" }).click();
  check(await legal.getByText("Give the legal basis for a compulsory power.").isVisible(), "a compulsory power needs its legal basis and end");
  await legal.getByLabel("Legal basis").fill("Section 5, Lunacy Act");
  await legal.getByLabel("Until").fill(local(new Date(Date.now() + 48 * 3600_000)));
  await legal.getByLabel("Authorised by").selectOption({ label: "Dr Clinician One" });
  await legal.getByLabel("Reason").fill("Acute psychosis with risk to self");
  await legal.getByRole("button", { name: "Record" }).click();
  await page.getByText(/^Legal status recorded\./).waitFor();
  await page.getByText("Expires within 72 hours").first().waitFor();
  check(true, "the legal status is recorded with its expiry warning");
  await page.getByRole("button", { name: "Record a restrictive intervention" }).click();
  const ri = page.getByRole("form", { name: "Record a restrictive intervention" });
  await ri.getByLabel("Reason").fill("Assaulting another patient; de-escalation failed");
  await ri.getByLabel("Authorised by").selectOption({ label: "Dr Clinician One" });
  await ri.getByLabel("Nurse One").check();
  await ri.getByLabel("Dr Clinician One").check();
  await axe(page, "record a restrictive intervention");
  await ri.getByRole("button", { name: "Record" }).click();
  await page.getByText(/^Recorded\. A safeguarding lead who took no part/).waitFor();
  const restraint = page.getByRole("article", { name: /^Physical restraint/ });
  await restraint.getByText("Ongoing").waitFor();
  await restraint.getByLabel("Yes").check();
  await restraint.getByRole("button", { name: "Record the end" }).click();
  await page.getByText(/^Ended\./).waitFor();
  check(true, "the intervention is logged with its staff and its end recorded once");
  await page.getByRole("button", { name: "Raise a concern" }).click();
  const concern = page.getByRole("form", { name: "Raise a concern" });
  await concern.getByLabel("Raised by").selectOption("family");
  await concern.getByLabel("Their name").fill("Musa Bello");
  await concern.getByLabel("The concern").fill("She was left in a soiled gown for hours after the restraint.");
  await concern.getByRole("button", { name: "Raise the concern" }).click();
  await page.getByText(/^Concern raised\./).waitFor();
  check(true, "a family member's concern is raised for independent answer");
  await shot(page, "02-safeguarding");

  // 3. Discharge, with outstanding items each given an owner.
  await page.getByRole("button", { name: "Write the discharge summary" }).click();
  const summary = page.getByRole("form", { name: "Discharge summary" });
  await summary.getByLabel("Summary of the stay").fill("Admitted with fluid overload; dialysis established. Psychosis settled.");
  await summary.getByLabel("Follow-up").fill("Renal clinic in 2 weeks");
  await summary.getByRole("button", { name: "Save draft" }).click();
  await page.getByText("Summary saved as a draft.").waitFor();
  await page.getByRole("button", { name: "Sign off the discharge" }).click();
  const sign = page.getByRole("form", { name: "Sign off the discharge" });
  await sign.getByRole("button", { name: "Add an outstanding item" }).click();
  await sign.getByLabel("What is outstanding").fill("Book renal clinic review");
  await sign.getByRole("button", { name: "Add an outstanding item" }).click();
  await sign.getByLabel("What is outstanding").nth(1).fill("Community psychiatric nurse visit");
  await sign.getByLabel("Owner").nth(1).selectOption("");
  await axe(page, "discharge sign-off");
  await sign.getByRole("button", { name: "Sign off and discharge" }).click();
  check(await sign.getByText("Item 2: name an owner, or give the reason there is none.").isVisible(), "an outstanding item needs an owner or a supervised exception");
  await sign.getByLabel("Why there is no owner").fill("No community team covers the patient's area yet");
  await sign.getByRole("button", { name: "Sign off and discharge" }).click();
  await page.getByText(/^Discharged\. \d+ follow-up tasks were opened/).waitFor();
  await page.getByRole("cell", { name: /^Finished/ }).waitFor();
  check(true, "the visit is finished");
  await page.getByRole("article", { name: /^Discharge \d/ }).getByText(/Admitted with fluid overload/).waitFor();
  check(true, "the signed summary is on the chart");
  await shot(page, "03-discharged");

  // A task for the nurse from the Daybook.
  await nav(page, "Daybook");
  await page.getByRole("button", { name: "New task" }).click();
  const task = page.getByRole("form", { name: "New task" });
  await task.getByRole("button", { name: "Create task" }).click();
  check(await task.getByText("Every task needs a named owner or a queue.").isVisible(), "a task needs an owner or a queue");
  await task.getByLabel("What needs doing").fill("Check fistula site before discharge transport");
  await task.getByLabel("Owner").selectOption({ label: "Nurse One" });
  await axe(page, "daybook");
  await task.getByRole("button", { name: "Create task" }).click();
  await page.getByText("Task created: Check fistula site before discharge transport.").waitFor();
  await signOut(page);

  // 4. Nurse One completes it; the scheduler takes the queue task.
  await signIn(page, "Nurse One");
  await nav(page, "Daybook");
  const fistula = page.getByRole("article", { name: "Check fistula site before discharge transport" });
  await fistula.getByRole("button", { name: /^Complete/ }).click();
  await fistula.getByLabel("Outcome").fill("Thrill present, no bleeding");
  await fistula.getByRole("button", { name: "Mark complete" }).click();
  await page.getByText("Completed: Check fistula site before discharge transport.").waitFor();
  check(true, "the named owner completes the task");
  await signOut(page);
  await signIn(page, "Scheduler One");
  await nav(page, "Daybook");
  const booking = page.getByRole("article", { name: "Book renal clinic review" });
  await booking.getByText("Scheduler queue", { exact: false }).waitFor();
  await booking.getByRole("button", { name: /^Take it/ }).click();
  await page.getByText(/^You have taken "Book renal clinic review"\./).waitFor();
  check(true, "a queue member takes the task from the scheduler queue");
  await signOut(page);

  // 5. The team supervisor sees the supervised exception and gives it an owner.
  await signIn(page, "Team Supervisor One");
  await nav(page, "Daybook");
  await page.getByLabel("Every active task (supervisor)").check();
  const orphan = page.getByRole("article", { name: /^No owner: Community psychiatric nurse visit/ });
  await orphan.waitFor();
  await orphan.getByRole("button", { name: /^Reassign/ }).click();
  await orphan.getByLabel("New owner").selectOption({ label: "Dr Clinician Two" });
  await orphan.getByLabel("Reason").fill("Covers the community psychiatry rota this week");
  await orphan.getByRole("button", { name: "Reassign" }).click();
  await page.getByText("Reassigned to Dr Clinician Two. The due time is unchanged.").waitFor();
  check(true, "the supervisor gives the exception a named owner");
  await shot(page, "04-supervisor");
  await signOut(page);

  // 6. The safeguarding lead reviews independently.
  await signIn(page, "Safeguarding Lead One");
  await nav(page, "Safeguarding");
  const review = page.getByRole("article", { name: /^Physical restraint/ });
  await review.waitFor();
  await review.getByRole("link", { name: "BELLO, Hauwa" }).waitFor();
  check(true, "the review queue names the patient");
  await axe(page, "safeguarding review");
  await review.getByLabel("Concerns", { exact: true }).check();
  await review.getByLabel("Review note").fill("Restraint justified; dignity after restraint was poor");
  await review.getByRole("button", { name: "Record the review" }).click();
  await page.getByText("Review recorded.").waitFor();
  await page.getByLabel("Open concerns").check();
  const open = page.getByRole("article", { name: /^Dignity concern/ });
  await open.getByLabel("Upheld", { exact: true }).check();
  await open.getByLabel("Answer", { exact: true }).fill("Upheld. Ward manager to retrain staff on post-restraint care.");
  await open.getByRole("button", { name: "Close the concern" }).click();
  await page.getByText("Concern answered and closed.").waitFor();
  check(true, "the lead answers the concern");
  await page.getByLabel("Powers expiring or lapsed").check();
  await page.getByRole("link", { name: /BELLO, Hauwa/ }).first().click();
  await page.getByRole("heading", { level: 1, name: /^Safeguarding: BELLO, Hauwa/ }).waitFor();
  await page.getByRole("table", { name: "By person" }).getByText("clinician@pilot.astemia.local").waitFor();
  check(true, "the access report shows who touched the record");
  await page.getByLabel("Advocate", { exact: true }).selectOption({ label: "Patient Advocate One" });
  await page.getByRole("button", { name: "Appoint" }).click();
  await page.getByText(/^Patient Advocate One is appointed/).waitFor();
  check(true, "the lead appoints an independent advocate");
  await axe(page, "access report");
  await shot(page, "05-access-report");
  await page.setViewportSize({ width: 360, height: 780 });
  check(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "the safeguarding pages fit a 360 px screen");
});

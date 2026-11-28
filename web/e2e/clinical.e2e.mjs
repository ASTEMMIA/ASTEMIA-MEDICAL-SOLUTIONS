// Web 2 end to end against the real API: register (with the duplicate check),
// admit, order, release a result, acknowledge it, emergency access and its
// review, and an identity steward's decision. Each screen is scanned with axe.
import { axe, check, headingFocused, run, shot, signIn } from "./lib.mjs";

const signOut = async (page) => {
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("heading", { name: "Sign in to ASTEMIA Health" }).waitFor();
};
const nav = (page, name) => page.getByRole("navigation", { name: "Main" }).getByRole("link", { name }).click();

async function findPatient(page, family) {
  await nav(page, "Patients");
  await page.getByRole("heading", { level: 1, name: "Patients" }).waitFor();
  await page.getByLabel("Family name").fill(family);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("link", { name: new RegExp(`^${family.toUpperCase()},`) }).first().click();
}

await run("clinical", async (page) => {
  // 1. Registrar: register, then admit under Dr Clinician One.
  await signIn(page, "Registrar One");
  await nav(page, "Patients");
  await axe(page, "patient search");
  await page.getByRole("link", { name: "Register a patient" }).click();
  await page.getByRole("heading", { level: 1, name: "Register a patient" }).waitFor();
  await page.getByRole("button", { name: "Register" }).click();
  check(await page.getByRole("alert").getByText("Enter the family name.").isVisible(), "missing fields are listed in an alert");
  check((await page.getByLabel("Family name").getAttribute("aria-invalid")) === "true", "an invalid field is marked for assistive technology");
  await page.getByLabel("Family name").fill("Okonkwo");
  await page.getByLabel("Given names").fill("Chiamaka Ada");
  await page.getByLabel("Date of birth").fill("1979-06-14");
  await page.getByLabel("Sex").selectOption("female");
  await page.getByLabel("NIN").fill("1234");
  await page.getByRole("button", { name: "Register" }).click();
  check(await page.getByText("A NIN is 11 digits.").first().isVisible(), "a short NIN is refused before sending");
  await page.getByLabel("NIN").fill("40512345678");
  await axe(page, "registration form");
  await page.getByRole("button", { name: "Register" }).click();
  await page.getByText("Patient registered.").waitFor();
  check(true, "a new person is registered when the index has no match");
  await shot(page, "01-registered");
  await page.getByLabel("Responsible clinician").selectOption({ label: "Dr Clinician One" });
  await page.getByLabel("Visit number").fill("V-1001");
  await axe(page, "admission");
  await page.getByRole("button", { name: "Admit", exact: true }).click();
  await page.getByText("Admitted: visit V-1001 under Dr Clinician One.").waitFor();
  check(true, "the registrar admits the patient under a named clinician");

  // A second registration that looks like the same person.
  await nav(page, "Patients");
  await page.getByRole("link", { name: "Register a patient" }).click();
  await page.getByRole("heading", { level: 1, name: "Register a patient" }).waitFor();
  await page.getByLabel("Family name").fill("Okonkwo");
  await page.getByLabel("Given names").fill("Chiamaka");
  await page.getByLabel("Date of birth").fill("1979-06-14");
  await page.getByLabel("Sex").selectOption("female");
  await page.getByRole("button", { name: "Register" }).click();
  await page.getByText(/existing records? looks? like this person/).waitFor();
  check(await page.getByRole("table", { name: "Possible matches" }).isVisible(), "likely matches are shown, with reasons, before a record is made");
  await axe(page, "possible matches");
  await shot(page, "02-possible-match");
  await page.getByRole("button", { name: "Register anyway" }).click();
  await page.getByText(/sent to an identity steward/).waitFor();
  check(true, "registering anyway sends the near match to an identity steward");
  await signOut(page);

  // 2. Dr Clinician One: open the chart and order a potassium.
  await signIn(page, "Dr Clinician One");
  await nav(page, "Patients");
  await page.getByRole("heading", { level: 1, name: "Patients" }).waitFor();
  await page.getByLabel("NIN").fill("40512345678");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("cell", { name: "40512345678" }).waitFor();
  check(true, "a clinician sees the full NIN");
  await page.getByRole("link", { name: "OKONKWO, Chiamaka Ada" }).click();
  await page.getByRole("heading", { level: 1, name: "OKONKWO, Chiamaka Ada" }).waitFor();
  check(await headingFocused(page), "the chart's heading takes focus");
  await page.getByRole("cell", { name: "Dr Clinician One" }).waitFor();
  check(true, "the visit names the responsible clinician, not an ID");
  await page.getByRole("button", { name: "Place an order" }).click();
  await page.getByLabel("Test").selectOption({ label: "Potassium [Moles/volume] in Serum" });
  await page.getByLabel("Urgent").check();
  await axe(page, "order form");
  await page.getByRole("button", { name: "Place order" }).click();
  await page.getByText("Awaiting result").waitFor();
  check(true, "the order is placed and waits for its result");
  await signOut(page);

  // 3. Laboratory: release the result from the worklist.
  await signIn(page, "Lab Scientist One");
  await nav(page, "Laboratory");
  await page.getByRole("heading", { level: 1, name: "Laboratory worklist" }).waitFor();
  await page.getByRole("button", { name: /^Enter result\b.*Potassium/ }).waitFor();
  check(!(await page.getByText("40512345678").count()), "the laboratory sees a masked NIN");
  await page.getByRole("button", { name: /^Enter result\b.*Potassium.* for OKONKWO, Chiamaka Ada/ }).click();
  check((await page.getByLabel("Unit").inputValue()) === "mmol/L", "the unit and reference range are filled in for a known test");
  await page.getByLabel("Value").fill("high");
  await page.getByRole("button", { name: "Release result" }).click();
  check(await page.getByText("Enter the value as a number").isVisible(), "a non-numeric value is refused");
  await page.getByLabel("Value").fill("6.1");
  await axe(page, "result entry");
  await shot(page, "03-lab");
  await page.getByRole("button", { name: "Release result" }).click();
  await page.getByText(/Result released for Potassium/).waitFor();
  check(true, "the result is released and leaves the worklist");
  await signOut(page);

  // 4. Dr Clinician One acknowledges the high result.
  await signIn(page, "Dr Clinician One");
  await findPatient(page, "Okonkwo");
  const result = page.getByRole("article", { name: /Potassium/ });
  await result.waitFor();
  check(await result.getByText("High").isVisible(), "a high value is flagged in words, not colour alone");
  await axe(page, "chart with result");
  await shot(page, "04-chart");
  await result.getByRole("button", { name: "Acknowledge result" }).click();
  await result.getByText("Acknowledged.").waitFor();
  check(true, "the result owner acknowledges the result");
  await signOut(page);

  // 5. Dr Clinician Two has no care relationship: emergency access.
  await signIn(page, "Dr Clinician Two");
  await findPatient(page, "Okonkwo");
  await page.getByText("This chart is not available to you.").waitFor();
  check(true, "without a care relationship the chart is concealed");
  await page.getByRole("button", { name: "Open the chart in an emergency" }).click();
  check(await page.getByText("in at least 10 characters").isVisible(), "a purpose is required");
  await page.getByLabel("Why do you need this chart now?").fill("Collapsed in the emergency department, unconscious");
  await axe(page, "emergency access request");
  await page.getByRole("button", { name: "Open the chart in an emergency" }).click();
  await page.getByText("Emergency access.", { exact: false }).first().waitFor();
  check(!(await page.getByRole("button", { name: "Place an order" }).count()), "emergency access is read-only: no orders");
  check(!(await page.getByText("40512345678").count()), "identifiers stay masked under emergency access");
  await shot(page, "05-emergency");
  await signOut(page);

  // 6. Privacy officer reviews the grant.
  await signIn(page, "Privacy Officer One");
  await nav(page, "Emergency access");
  const grant = page.getByRole("article", { name: "Emergency access by Dr Clinician Two" });
  await grant.waitFor();
  check(await grant.getByText("Collapsed in the emergency department").isVisible(), "the reviewer sees who, when and why");
  await axe(page, "emergency review");
  await grant.getByLabel("Appropriate", { exact: true }).check();
  await grant.getByLabel("Note").fill("Unconscious patient in ED; access justified");
  await grant.getByRole("button", { name: "Record review" }).click();
  await page.getByText("Review recorded for Dr Clinician Two's access.").waitFor();
  check(true, "the privacy officer records the review");
  await signOut(page);

  // 7. Identity steward decides the near match.
  await signIn(page, "Identity Steward One");
  await nav(page, "Identity review");
  const pair = page.getByRole("article", { name: /Possible match: Okonkwo C\./ });
  await pair.waitFor();
  await axe(page, "identity review");
  await shot(page, "06-identity-review");
  await pair.getByRole("button", { name: "Record decision" }).click();
  check(await pair.getByText("Choose a decision.").isVisible(), "a decision is required");
  await pair.getByLabel("These are different people").check();
  await pair.getByLabel("Reason").fill("Different mothers; confirmed by phone");
  await pair.getByRole("button", { name: "Record decision" }).click();
  await page.getByText(/Recorded as different people/).waitFor();
  check(await page.getByText("No pairs are waiting for review.").isVisible(), "the pair leaves the review list");

  // The chart at phone width scrolls tables inside themselves, not the page.
  await signOut(page);
  await signIn(page, "Dr Clinician One");
  await findPatient(page, "Okonkwo");
  await page.setViewportSize({ width: 360, height: 780 });
  check(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "the chart fits a 360 px screen");
});

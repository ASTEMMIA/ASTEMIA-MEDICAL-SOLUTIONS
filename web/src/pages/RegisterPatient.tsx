import { useCallback, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import type { AdministrativeSex, CandidateOut, MatchOut, PatientOut, RegisterPatient as Body } from "../api-types";
import { Button, Field, Notice, Page, Select } from "../components/ui";
import { words } from "../format";
import { COUNTRIES, NG_STATES, postcodeProblem } from "../places";
import { useAction } from "../hooks";

type Registered = PatientOut & { possible_duplicates: string[]; identity_review_tasks: string[] };

const SEXES: [AdministrativeSex, string][] = [
  ["female", "Female"],
  ["male", "Male"],
  ["other", "Other"],
  ["unknown", "Not known"],
];

/**
 * Register a patient (ICRS 3.2.8, WF01). The index is checked first and any
 * likely matches are shown with their reasons; registering anyway is allowed
 * (alert, never block) and near matches go to an identity steward.
 */
export function RegisterPatient() {
  const navigate = useNavigate();
  const [f, setF] = useState({ family_name: "", given_names: "", birth_date: "", administrative_sex: "" as AdministrativeSex | "", mother_name: "", nin: "", line1: "", line2: "", town: "", lga: "", state: "", postcode: "", country: "NG" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [matches, setMatches] = useState<CandidateOut[] | null>(null);
  const [checked, setChecked] = useState("");

  const body = (): Body => ({
    family_name: f.family_name.trim(),
    given_names: f.given_names.trim(),
    birth_date: f.birth_date,
    administrative_sex: f.administrative_sex as AdministrativeSex,
    mother_name: f.mother_name.trim() || null,
    identifiers: f.nin.trim() ? [{ issuer: "NG-NIN", value: f.nin.trim() }] : [],
    address: {
      line1: f.line1.trim(),
      line2: f.line2.trim() || null,
      town: f.town.trim(),
      local_government_area: f.lga.trim() || null,
      state: f.state.trim() || null,
      postcode: f.postcode.trim(),
      country: f.country,
    },
  });

  const check = useAction(
    useCallback(async (_key: string, b: Body) => {
      // The index is searched on identity only; the address is filed at registration.
      const { identifiers, family_name, given_names, birth_date, administrative_sex, mother_name } = b;
      return api<MatchOut>("/v1/patient-index/match", { body: { family_name, given_names, birth_date, administrative_sex, mother_name, identifiers } });
    }, []),
  );
  const register = useAction(useCallback((key: string, b: Body) => api<Registered>("/v1/patients", { body: b, key }), []));

  function validate(): boolean {
    const e: Record<string, string> = {};
    if (!f.family_name.trim()) e.family_name = "Enter the family name.";
    if (!f.given_names.trim()) e.given_names = "Enter the given names.";
    if (!f.birth_date) e.birth_date = "Enter the date of birth.";
    if (!f.administrative_sex) e.administrative_sex = "Choose the sex recorded.";
    if (f.nin.trim() && !/^\d{11}$/.test(f.nin.trim())) e.nin = "A NIN is 11 digits.";
    if (!f.line1.trim()) e.line1 = "Enter the house number and street.";
    if (!f.town.trim()) e.town = "Enter the town or city.";
    if (f.country === "NG" && !f.state) e.state = "Choose the state.";
    if (f.country === "NG" && !f.lga.trim()) e.lga = "Enter the local government area.";
    const pc = postcodeProblem(f.country, f.postcode);
    if (pc) e.postcode = pc;
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    const b = body();
    const signature = JSON.stringify(b);
    if (checked !== signature) {
      // First the index: show likely matches before a new record is made.
      const found = await check.run(b);
      if (!found) return;
      setChecked(signature);
      if (found.candidates.length > 0) {
        setMatches(found.candidates);
        return;
      }
    }
    const made = await register.run(b);
    if (made) navigate(`/patients/${made.id}`, { state: { registered: made } });
  }

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
    setMatches(null);
  };
  const errorList = Object.values(errors);

  return (
    <Page title="Register a patient" intro="The index is searched for this person before a new record is made.">
      {errorList.length > 0 && (
        <Notice kind="error">
          <p>There is a problem:</p>
          <ul>
            {errorList.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </Notice>
      )}
      {(check.error || register.error) && <Notice kind="error">{check.error ?? register.error}</Notice>}
      <form onSubmit={submit} noValidate>
        <div className="row">
          <Field label="Family name" autoComplete="off" value={f.family_name} onChange={set("family_name")} error={errors.family_name} />
          <Field label="Given names" autoComplete="off" value={f.given_names} onChange={set("given_names")} error={errors.given_names} />
        </div>
        <div className="row">
          <Field label="Date of birth" type="date" value={f.birth_date} onChange={set("birth_date")} error={errors.birth_date} />
          <Select label="Sex" placeholder="Choose" options={SEXES} value={f.administrative_sex} onChange={set("administrative_sex")} error={errors.administrative_sex} />
        </div>
        <Field label="Mother's name" hint="Optional. Helps tell people apart." autoComplete="off" value={f.mother_name} onChange={set("mother_name")} />
        <Field label="NIN" hint="Optional. 11 digits." inputMode="numeric" autoComplete="off" value={f.nin} onChange={set("nin")} error={errors.nin} />
        <fieldset className="address">
          <legend>Home address</legend>
          <p className="hint">Required for every patient: the full address and postcode.</p>
          <Select label="Country" options={COUNTRIES} value={f.country} onChange={set("country")} />
          <Field label="House number and street" autoComplete="off" value={f.line1} onChange={set("line1")} error={errors.line1} />
          <Field label="Area or estate" hint="Optional" autoComplete="off" value={f.line2} onChange={set("line2")} />
          <div className="row">
            <Field label="Town or city" autoComplete="off" value={f.town} onChange={set("town")} error={errors.town} />
            {f.country === "NG" ? (
              <Select label="State" placeholder="Choose" options={NG_STATES.map((n) => [n, n])} value={f.state} onChange={set("state")} error={errors.state} />
            ) : (
              <Field label="State, county or region" hint="Optional" autoComplete="off" value={f.state} onChange={set("state")} />
            )}
          </div>
          <div className="row">
            <Field
              label="Local government area"
              hint={f.country === "NG" ? undefined : "Optional"}
              autoComplete="off"
              value={f.lga}
              onChange={set("lga")}
              error={errors.lga}
            />
            <Field label="Postcode" hint={f.country === "NG" ? "6 digits" : undefined} autoComplete="off" value={f.postcode} onChange={set("postcode")} error={errors.postcode} />
          </div>
        </fieldset>

        {matches && (
          <div className="matches">
            <Notice kind="warning">
              <strong>
                {matches.length === 1 ? "1 existing record looks like this person." : `${matches.length} existing records look like this person.`}
              </strong>{" "}
              Open the record if it is them. If not, register anyway: an identity steward reviews near matches.
            </Notice>
            <table className="table">
              <caption>Possible matches</caption>
              <thead>
                <tr>
                  <th scope="col">Family name</th>
                  <th scope="col">Initial</th>
                  <th scope="col">Born</th>
                  <th scope="col">Sex</th>
                  <th scope="col">Why it matches</th>
                  <th scope="col">
                    <span className="visually-hidden">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {matches.map((m) => (
                  <tr key={m.id}>
                    <td>{m.family_name}</td>
                    <td>{m.given_initial}</td>
                    <td>{m.birth_year}</td>
                    <td>{words(m.administrative_sex)}</td>
                    <td>{m.reasons.map(words).join("; ")}</td>
                    <td>
                      <Link to={`/patients/${m.id}`}>Open record</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Button type="submit" busy={check.busy || register.busy}>
          {matches ? "Register anyway" : "Register"}
        </Button>
      </form>
    </Page>
  );
}

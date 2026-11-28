import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { messageFor } from "../api";
import type { PatientOut } from "../api-types";
import { Button, Empty, Field, Loading, Notice, Page, Tag } from "../components/ui";
import { date, nin, patientName, words } from "../format";
import { useLoad } from "../hooks";
import { useSession } from "../session";

/** Find a patient by NIN, or by family name with optional given name and date of birth (ICRS 3.2). */
export function Patients() {
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const [form, setForm] = useState({
    nin: params.get("nin") ?? "",
    family_name: params.get("family_name") ?? "",
    given_name: params.get("given_name") ?? "",
    birth_date: params.get("birth_date") ?? "",
  });
  const [problem, setProblem] = useState<string | null>(null);
  const searched = params.get("nin") || params.get("family_name");
  const query = Object.fromEntries(params.entries());
  const results = useLoad<PatientOut[]>(searched ? "/v1/patient-index" : null, { ...query, limit: 50 });

  function search(e: FormEvent) {
    e.preventDefault();
    if (!form.nin.trim() && form.family_name.trim().length < 2) {
      setProblem("Enter a NIN, or at least two letters of the family name.");
      return;
    }
    setProblem(null);
    const next = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()]));
    setParams(next);
  }

  return (
    <Page title="Patients" intro="Search the patient index. Identifiers are masked unless your role may see them.">
      {can("patient:register") && (
        <p>
          <Link className="btn btn-secondary" to="/patients/new">
            Register a patient
          </Link>
        </p>
      )}
      <form onSubmit={search} className="search" role="search" aria-label="Patients" noValidate>
        {problem && <Notice kind="error">{problem}</Notice>}
        <Field label="NIN" hint="11 digits" inputMode="numeric" autoComplete="off" value={form.nin} onChange={(e) => setForm({ ...form, nin: e.target.value })} />
        <p className="or">or</p>
        <div className="row">
          <Field label="Family name" autoComplete="off" value={form.family_name} onChange={(e) => setForm({ ...form, family_name: e.target.value })} />
          <Field label="Given name" hint="Optional" autoComplete="off" value={form.given_name} onChange={(e) => setForm({ ...form, given_name: e.target.value })} />
          <Field label="Date of birth" hint="Optional" type="date" value={form.birth_date} onChange={(e) => setForm({ ...form, birth_date: e.target.value })} />
        </div>
        <Button type="submit">Search</Button>
      </form>

      {results.loading && <Loading what="Searching" />}
      {results.error !== null && <Notice kind="error">{messageFor(results.error)}</Notice>}
      {results.data && (
        <div aria-live="polite">
          {results.data.length === 0 ? (
            <Empty>No patients match. Check the spelling, or search by NIN.</Empty>
          ) : (
            <table className="table">
              <caption>
                {results.data.length === 1 ? "1 patient" : `${results.data.length} patients`}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Date of birth</th>
                  <th scope="col">Sex</th>
                  <th scope="col">NIN</th>
                  <th scope="col">Record</th>
                </tr>
              </thead>
              <tbody>
                {results.data.map((p) => (
                  <tr key={p.id}>
                    <th scope="row">
                      <Link to={`/patients/${p.id}`}>{patientName(p)}</Link>
                    </th>
                    <td>{date(p.birth_date)}</td>
                    <td>{words(p.administrative_sex)}</td>
                    <td className="mono">{nin(p.identifiers)}</td>
                    <td>{p.status === "active" ? <Tag tone="good">Active</Tag> : <Tag tone="warn">{words(p.status)}</Tag>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Page>
  );
}

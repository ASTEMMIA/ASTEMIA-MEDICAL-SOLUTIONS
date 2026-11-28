import { useCallback, useState, type FormEvent } from "react";
import { useLocation, useParams } from "react-router";
import { api, ApiError, messageFor } from "../api";
import type {
  AdmitEncounter,
  ChartOut,
  EncounterClass,
  EncounterOut,
  OrderPriority,
  PatientOut,
  ReportOut,
  ReviewOut,
} from "../api-types";
import { Button, Empty, Field, Loading, Notice, Page, Radios, Section, Select, Tag, TextArea } from "../components/ui";
import { useDirectory } from "../directory";
import { date, dateTime, localToIso, nin, nowLocal, num, patientName, words } from "../format";
import { useAction, useLoad } from "../hooks";
import { LAB_TESTS, LOINC } from "../lab";
import { useSession } from "../session";

type Registered = PatientOut & { possible_duplicates?: string[]; identity_review_tasks?: string[] };

/** A patient's chart (API-03): every section the reader may see, and what they may do from it. */
export function Chart() {
  const { id = "" } = useParams();
  const registered = (useLocation().state as { registered?: Registered } | null)?.registered;
  const chart = useLoad<ChartOut>(`/v1/patients/${id}/chart`);
  const concealed = chart.error instanceof ApiError && chart.error.status === 404;

  if (chart.loading && !chart.data) return <Loading what="Opening the chart" />;
  if (concealed || (!chart.data && registered))
    return <NoChart patientId={id} registered={registered} onOpened={chart.reload} />;
  if (!chart.data)
    return (
      <Page title="Patient chart">
        <Notice kind="error">{messageFor(chart.error)}</Notice>
      </Page>
    );
  const c = chart.data;
  return (
    <Page title={patientName(c.patient)}>
      <PatientSummary patient={c.patient} />
      {registered && <RegisteredNotice r={registered} />}
      <Banners chart={c} />
      <Visits chart={c} patientId={id} onChange={chart.reload} />
      <Problems chart={c} />
      <Orders chart={c} patientId={id} onChange={chart.reload} />
      <Results chart={c} onChange={chart.reload} />
      <Notes chart={c} />
      <Correspondence chart={c} />
      <Discharges chart={c} />
      <CarePlans chart={c} />
    </Page>
  );
}

function PatientSummary({ patient }: { patient: PatientOut }) {
  return (
    <dl className="facts patient-summary">
      <dt>Born</dt>
      <dd>
        {date(patient.birth_date)}
        {patient.birth_date_precision === "year" && " (year only)"}
      </dd>
      <dt>Sex</dt>
      <dd>{words(patient.administrative_sex)}</dd>
      <dt>NIN</dt>
      <dd className="mono">{nin(patient.identifiers)}</dd>
      <dt>Record</dt>
      <dd>{patient.status === "active" ? <Tag tone="good">Active</Tag> : <Tag tone="warn">{words(patient.status)}</Tag>}</dd>
    </dl>
  );
}

function RegisteredNotice({ r }: { r: Registered }) {
  const review = r.identity_review_tasks?.length ?? 0;
  return (
    <Notice kind="success">
      <strong>Patient registered.</strong>
      {review > 0 && ` ${review === 1 ? "A near match was" : `${review} near matches were`} sent to an identity steward to review.`}
      {(r.possible_duplicates?.length ?? 0) > 0 && " Records with the same name and date of birth are on the duplicates list."}
    </Notice>
  );
}

function Banners({ chart }: { chart: ChartOut }) {
  const ls = chart.legal_status;
  return (
    <>
      {chart.access_basis === "emergency_grant" && (
        <Notice kind="warning">
          <strong>Emergency access.</strong> You are reading this chart without a care relationship. Access is read-only, time-limited and
          every read is audited and reviewed by a privacy officer.
        </Notice>
      )}
      {ls && (
        <Notice kind={ls.lapsed ? "error" : "warning"}>
          <strong>Mental health legal status: {words(ls.status)}</strong>
          {ls.legal_basis && ` (${ls.legal_basis})`}, from {dateTime(ls.valid_from)}
          {ls.valid_until && ` until ${dateTime(ls.valid_until)}`}.{ls.lapsed && " This power has lapsed."}
          {ls.expiring && !ls.lapsed && " It expires within 72 hours."}
        </Notice>
      )}
      {chart.withheld_records > 0 && (
        <Notice>
          {chart.withheld_records === 1 ? "1 sensitive record is" : `${chart.withheld_records} sensitive records are`} withheld: your role
          may not see them.
        </Notice>
      )}
      {(chart.merged_from ?? []).length > 0 && (
        <Notice>
          This chart includes {(chart.merged_from ?? []).length === 1 ? "a record" : `${(chart.merged_from ?? []).length} records`} merged into this one.
        </Notice>
      )}
    </>
  );
}

// --- No chart: admission and emergency access --------------------------------------

function NoChart({ patientId, registered, onOpened }: { patientId: string; registered?: Registered; onOpened: () => void }) {
  const { can } = useSession();
  const [admitted, setAdmitted] = useState<EncounterOut | null>(null);
  const { person } = useDirectory();
  return (
    <Page title={registered ? patientName(registered) : "Patient chart"}>
      {registered && (
        <>
          <PatientSummary patient={registered} />
          <RegisteredNotice r={registered} />
        </>
      )}
      {!registered && (
        <Notice>
          This chart is not available to you. It may not exist, or you have no care relationship with this patient.
        </Notice>
      )}
      {admitted && (
        <Notice kind="success">
          Admitted: visit {admitted.visit_number} under {person(admitted.responsible_practitioner_id)}.
        </Notice>
      )}
      {can("encounter:admit") && !admitted && (
        <Section title="Admit">
          <AdmitForm patientId={patientId} onDone={setAdmitted} />
        </Section>
      )}
      {can("emergency:request") && !registered && <EmergencyAccessForm patientId={patientId} onGranted={onOpened} />}
    </Page>
  );
}

function EmergencyAccessForm({ patientId, onGranted }: { patientId: string; onGranted: () => void }) {
  const [purpose, setPurpose] = useState("");
  const [error, setError] = useState<string | undefined>();
  const request = useAction(
    useCallback((key: string, p: string) => api("/v1/emergency-grants", { body: { patient_id: patientId, purpose: p }, key }), [patientId]),
  );
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (purpose.trim().length < 10) {
      setError("Say why you need the chart now, in at least 10 characters.");
      return;
    }
    setError(undefined);
    if (await request.run(purpose.trim())) onGranted();
  }
  return (
    <Section title="Emergency access">
      <p>
        If this patient needs care now and you are not in their care team, you can read their chart for 30 minutes. Identifiers stay masked,
        you cannot place orders, and a privacy officer reviews every use.
      </p>
      {request.error && <Notice kind="error">{request.error}</Notice>}
      <form onSubmit={submit} noValidate>
        <TextArea
          label="Why do you need this chart now?"
          hint="The privacy officer reads this."
          value={purpose}
          onChange={(e) => setPurpose(e.target.value)}
          error={error}
          maxLength={500}
        />
        <Button type="submit" variant="danger" busy={request.busy}>
          Open the chart in an emergency
        </Button>
      </form>
    </Section>
  );
}

const CLASSES: [EncounterClass, string][] = [
  ["inpatient", "Inpatient"],
  ["emergency", "Emergency"],
  ["ambulatory", "Outpatient"],
  ["day_case", "Day case"],
  ["virtual", "Virtual"],
];

function AdmitForm({ patientId, onDone }: { patientId: string; onDone: (e: EncounterOut) => void }) {
  const { practitioners, facilities } = useDirectory();
  const [f, setF] = useState({
    facility_id: "",
    responsible_practitioner_id: "",
    encounter_class: "inpatient" as EncounterClass,
    service: "general_medicine",
    visit_number: "",
    admitted_at: nowLocal(),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const facility = f.facility_id || facilities[0]?.id || "";
  const admit = useAction(useCallback((key: string, b: AdmitEncounter) => api<EncounterOut>("/v1/encounters", { body: b, key }), []));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!facility) errs.facility_id = "Choose where the patient is admitted.";
    if (!f.responsible_practitioner_id) errs.responsible_practitioner_id = "Choose the responsible clinician.";
    if (!f.visit_number.trim()) errs.visit_number = "Enter the visit number.";
    if (!f.service.trim()) errs.service = "Enter the service.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const site = facilities.find((x) => x.id === facility);
    const made = await admit.run({
      patient_id: patientId,
      facility_id: facility,
      responsible_practitioner_id: f.responsible_practitioner_id,
      visit_authority: site?.site_identifier ?? "LOCAL",
      visit_number: f.visit_number.trim(),
      encounter_class: f.encounter_class,
      service: f.service.trim(),
      admitted_at: localToIso(f.admitted_at),
    });
    if (made) onDone(made);
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <form onSubmit={submit} noValidate>
      {admit.error && <Notice kind="error">{admit.error}</Notice>}
      <div className="row">
        <Select
          label="Facility"
          options={facilities.map((x) => [x.id, `${x.site_name}, ${x.organisation_name}`])}
          value={facility}
          onChange={set("facility_id")}
          error={errors.facility_id}
        />
        <Select
          label="Responsible clinician"
          hint="They gain access to the chart for this visit."
          placeholder="Choose"
          options={practitioners.map((p) => [p.id, p.display_name])}
          value={f.responsible_practitioner_id}
          onChange={set("responsible_practitioner_id")}
          error={errors.responsible_practitioner_id}
        />
      </div>
      <div className="row">
        <Select label="Type of visit" options={CLASSES} value={f.encounter_class} onChange={set("encounter_class")} />
        <Field label="Service" hint="For example general_medicine" value={f.service} onChange={set("service")} error={errors.service} />
      </div>
      <div className="row">
        <Field label="Visit number" autoComplete="off" value={f.visit_number} onChange={set("visit_number")} error={errors.visit_number} />
        <Field label="Admitted at" type="datetime-local" value={f.admitted_at} onChange={set("admitted_at")} />
      </div>
      <Button type="submit" busy={admit.busy}>
        Admit
      </Button>
    </form>
  );
}

// --- Chart sections ---------------------------------------------------------------

function Visits({ chart, patientId, onChange }: { chart: ChartOut; patientId: string; onChange: () => void }) {
  const { person, place } = useDirectory();
  const { can } = useSession();
  const [adding, setAdding] = useState(false);
  return (
    <Section
      title="Visits"
      actions={
        can("encounter:admit") &&
        !adding && (
          <Button variant="secondary" onClick={() => setAdding(true)}>
            Admit
          </Button>
        )
      }
    >
      {adding && (
        <AdmitForm
          patientId={patientId}
          onDone={() => {
            setAdding(false);
            onChange();
          }}
        />
      )}
      {chart.encounters.length === 0 ? (
        <Empty>No visits.</Empty>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Started</th>
              <th scope="col">Visit</th>
              <th scope="col">Service</th>
              <th scope="col">Where</th>
              <th scope="col">Responsible</th>
              <th scope="col">State</th>
            </tr>
          </thead>
          <tbody>
            {chart.encounters.map((e) => (
              <tr key={e.id}>
                <td>{dateTime(e.period_start)}</td>
                <td>
                  {e.visit_number} <span className="muted">({words(e.encounter_class)})</span>
                </td>
                <td>{words(e.service)}</td>
                <td>{place(e.facility_id)}</td>
                <td>{person(e.responsible_practitioner_id)}</td>
                <td>
                  {e.state === "in_progress" ? <Tag tone="good">In progress</Tag> : <Tag>{words(e.state)}</Tag>}
                  {e.disposition && <span className="muted"> · {words(e.disposition)}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}

function Problems({ chart }: { chart: ChartOut }) {
  return (
    <Section title="Problems">
      {(chart.conditions ?? []).length === 0 ? (
        <Empty>No problems recorded.</Empty>
      ) : (
        <ul className="list">
          {(chart.conditions ?? []).map((c) => (
            <li key={c.id}>
              {c.display} <span className="muted mono">{c.code}</span>
              {c.certainty !== "confirmed" && <Tag tone="warn">{words(c.certainty)}</Tag>}
              {c.onset_date && <span className="muted"> · since {date(c.onset_date)}</span>}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Orders({ chart, patientId, onChange }: { chart: ChartOut; patientId: string; onChange: () => void }) {
  const { person } = useDirectory();
  const { can } = useSession();
  const [adding, setAdding] = useState(false);
  const open = chart.encounters.filter((e) => e.state === "in_progress");
  const canOrder = can("order:create") && chart.access_basis !== "emergency_grant" && open.length > 0;
  return (
    <Section
      title="Orders"
      actions={
        canOrder &&
        !adding && (
          <Button variant="secondary" onClick={() => setAdding(true)}>
            Place an order
          </Button>
        )
      }
    >
      {adding && (
        <OrderForm
          patientId={patientId}
          encounters={open}
          onDone={() => {
            setAdding(false);
            onChange();
          }}
          onCancel={() => setAdding(false)}
        />
      )}
      {chart.orders.length === 0 ? (
        <Empty>No orders.</Empty>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Test</th>
              <th scope="col">Priority</th>
              <th scope="col">Requested by</th>
              <th scope="col">Result to</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {chart.orders.map((o) => (
              <tr key={o.id}>
                <td>{o.display}</td>
                <td>{o.priority === "routine" ? "Routine" : <Tag tone="warn">{words(o.priority)}</Tag>}</td>
                <td>{person(o.requester_id)}</td>
                <td>{person(o.result_owner_id)}</td>
                <td>{o.status === "active" ? <Tag>Awaiting result</Tag> : <Tag tone="good">{words(o.status)}</Tag>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}

function OrderForm({
  patientId,
  encounters,
  onDone,
  onCancel,
}: {
  patientId: string;
  encounters: EncounterOut[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const [encounter, setEncounter] = useState(encounters[0]?.id ?? "");
  const [code, setCode] = useState(LAB_TESTS[0]!.code);
  const [priority, setPriority] = useState<OrderPriority>("routine");
  const [note, setNote] = useState("");
  const place = useAction(useCallback((key: string, body: unknown) => api("/v1/orders", { body, key }), []));
  async function submit(e: FormEvent) {
    e.preventDefault();
    const test = LAB_TESTS.find((t) => t.code === code)!;
    const done = await place.run({
      patient_id: patientId,
      encounter_id: encounter,
      code_system: LOINC,
      code: test.code,
      display: test.display,
      priority,
      clinical_note: note.trim() || null,
    });
    if (done) onDone();
  }
  return (
    <form onSubmit={submit} className="panel" noValidate>
      {place.error && <Notice kind="error">{place.error}</Notice>}
      <div className="row">
        <Select label="Test" options={LAB_TESTS.map((t) => [t.code, t.display])} value={code} onChange={(e) => setCode(e.target.value)} />
        <Select label="Visit" options={encounters.map((e) => [e.id, `${e.visit_number} (${words(e.service)})`])} value={encounter} onChange={(e) => setEncounter(e.target.value)} />
      </div>
      <Radios
        legend="Priority"
        name="priority"
        value={priority}
        onChange={(v) => setPriority(v as OrderPriority)}
        options={[
          ["routine", "Routine"],
          ["urgent", "Urgent"],
          ["stat", "Immediately (stat)"],
        ]}
      />
      <TextArea label="Note for the laboratory" hint="Optional" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
      <div className="actions">
        <Button type="submit" busy={place.busy}>
          Place order
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

const FLAGS: Record<string, [string, "warn" | "bad"]> = { H: ["High", "warn"], L: ["Low", "warn"], HH: ["Critically high", "bad"], LL: ["Critically low", "bad"] };

function Results({ chart, onChange }: { chart: ChartOut; onChange: () => void }) {
  const orders = new Map(chart.orders.map((o) => [o.id, o]));
  const reviews = new Map(chart.open_reviews.map((r) => [r.report_id, r]));
  return (
    <Section title="Results">
      {chart.reports.length === 0 ? (
        <Empty>No results.</Empty>
      ) : (
        chart.reports.map((r) => (
          <Result key={r.id} report={r} test={orders.get(r.service_request_id)?.display ?? "Result"} review={reviews.get(r.id)} onChange={onChange} />
        ))
      )}
    </Section>
  );
}

function Result({ report, test, review, onChange }: { report: ReportOut; test: string; review?: ReviewOut; onChange: () => void }) {
  const { person } = useDirectory();
  const { me, can } = useSession();
  const ack = useAction(
    useCallback((key: string, r: ReviewOut) => api(`/v1/result-reviews/${r.id}/acknowledge`, { body: {}, version: r.version, key }), []),
  );
  const mine = review && review.assignee_id === me?.practitioner_id && can("result:acknowledge");
  return (
    <article className="result" aria-label={test}>
      <h3>
        {test} <span className="muted">· {dateTime(report.released_at)}</span> {report.status !== "final" && <Tag tone="warn">{words(report.status)}</Tag>}
      </h3>
      <table className="table compact">
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col">Value</th>
            <th scope="col">Reference range</th>
            <th scope="col">Flag</th>
          </tr>
        </thead>
        <tbody>
          {(report.observations ?? []).map((o) => {
            const flag = o.flag ? FLAGS[o.flag] : undefined;
            return (
              <tr key={o.observation_id}>
                <td>{o.display}</td>
                <td>
                  {o.quantity ? num(o.quantity) : (o.text ?? o.value_code)} {o.unit}
                </td>
                <td>{o.ref_low || o.ref_high ? `${num(o.ref_low)}–${num(o.ref_high)} ${o.unit ?? ""}` : "—"}</td>
                <td>{flag ? <Tag tone={flag[1]}>{flag[0]}</Tag> : o.flag ? <Tag tone="warn">{o.flag}</Tag> : "Normal"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {review && (
        <p className="review">
          {mine ? (
            <>
              {ack.error && <Notice kind="error">{ack.error}</Notice>}
              <Button
                variant="secondary"
                busy={ack.busy}
                onClick={async () => {
                  if (await ack.run(review)) onChange();
                }}
              >
                Acknowledge result
              </Button>
            </>
          ) : (
            <span className="muted">
              Awaiting acknowledgement by {person(review.assignee_id)}
              {review.state === "escalated" && " (escalated)"}
            </span>
          )}
        </p>
      )}
      {/* Every released result opens a review; with none open, it has been acknowledged. */}
      {!review && <p className="muted">Acknowledged.</p>}
    </article>
  );
}

function Notes({ chart }: { chart: ChartOut }) {
  const { person } = useDirectory();
  return (
    <Section title="Clinical notes">
      {(chart.entries ?? []).length === 0 ? (
        <Empty>No signed notes.</Empty>
      ) : (
        (chart.entries ?? []).map((n) => (
          <article key={n.id} className="note" aria-label={n.title ?? words(n.note_type)}>
            <h3>
              {n.title ?? words(n.note_type)} <span className="muted">· {words(n.note_type)}</span>
            </h3>
            <p className="note-body">{n.body}</p>
            <p className="muted">
              Signed by {person(n.signed_by_id)}, {dateTime(n.signed_at)}
              {n.revision_number > 1 && ` · revision ${n.revision_number}`}
            </p>
          </article>
        ))
      )}
    </Section>
  );
}

function Correspondence({ chart }: { chart: ChartOut }) {
  return (
    <Section title="Correspondence">
      {(chart.documents ?? []).length === 0 ? (
        <Empty>No filed letters or documents.</Empty>
      ) : (
        <ul className="list">
          {(chart.documents ?? []).map((d) => (
            <li key={d.id}>
              {d.title ?? words(d.document_type)} <span className="muted">from {d.sender}, received {dateTime(d.received_at)}</span>
              {!d.reviewed && <Tag tone="warn">Not yet reviewed</Tag>}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Discharges({ chart }: { chart: ChartOut }) {
  const { person } = useDirectory();
  return (
    <Section title="Discharges">
      {(chart.discharges ?? []).length === 0 ? (
        <Empty>No discharges.</Empty>
      ) : (
        (chart.discharges ?? []).map((d) => (
          <article key={d.id} className="note" aria-label={`Discharge ${dateTime(d.discharged_at)}`}>
            <h3>
              {words(d.disposition)} <span className="muted">· {dateTime(d.discharged_at)}</span>
            </h3>
            <p className="note-body">{d.summary}</p>
            {d.follow_up && <p>Follow-up: {d.follow_up}</p>}
            <p className="muted">Signed off by {person(d.signed_by_id)}</p>
          </article>
        ))
      )}
    </Section>
  );
}

function CarePlans({ chart }: { chart: ChartOut }) {
  const { person } = useDirectory();
  return (
    <Section title="Care plans">
      {(chart.care_plans ?? []).length === 0 ? (
        <Empty>No care plans.</Empty>
      ) : (
        <ul className="list">
          {(chart.care_plans ?? []).map((p) => (
            <li key={p.id}>
              {p.title} <span className="muted">({words(p.pathway)}, revision {p.current_revision})</span> · owner {person(p.owner_id)} · next
              session {dateTime(p.next_session)} · review by {date(p.review_date)}
              {p.status !== "active" && <Tag>{words(p.status)}</Tag>}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

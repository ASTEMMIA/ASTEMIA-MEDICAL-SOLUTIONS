import { useCallback, useState, type FormEvent } from "react";
import { api } from "../api";
import type {
  ChartOut,
  ConcernCategory,
  InterventionOut,
  InterventionType,
  LegalStatus,
  LegalStatusOut,
  RaiseConcern,
  RaisedBy,
  RecordIntervention,
  SetLegalStatus,
} from "../api-types";
import { useDirectory } from "../directory";
import { dateTime, localToIso, nowLocal, words } from "../format";
import { useAction, useLoad } from "../hooks";
import { useSession } from "../session";
import { Button, Empty, Field, Notice, Radios, Section, Select, Tag, TextArea } from "./ui";

const STATUSES: [LegalStatus, string][] = [
  ["informal", "Informal (voluntary)"],
  ["emergency_holding", "Emergency holding power"],
  ["detained_assessment", "Detained for assessment"],
  ["detained_treatment", "Detained for treatment"],
  ["community_treatment", "Community treatment order"],
];
const INTERVENTIONS: [InterventionType, string][] = [
  ["physical_restraint", "Physical restraint"],
  ["mechanical_restraint", "Mechanical restraint"],
  ["seclusion", "Seclusion"],
  ["rapid_tranquillisation", "Rapid tranquillisation"],
];
const CATEGORIES: [ConcernCategory, string][] = [
  ["restrictive_practice", "Restrictive practice"],
  ["neglect", "Neglect"],
  ["dignity", "Dignity"],
  ["medication", "Medication"],
  ["abuse", "Abuse"],
  ["other", "Other"],
];
export const FLAGS: Record<string, string> = {
  informal_patient: "Patient is informal",
  no_legal_status: "No legal status recorded",
  lapsed_power: "Held under a lapsed power",
};

/**
 * Mental health safeguards on the chart (HS13; CEDA revision 1.6): legal
 * status with its history, restrictive interventions logged and independently
 * reviewed, and concerns raised by anyone.
 */
export function SafeguardingSection({ chart }: { chart: ChartOut }) {
  const { can } = useSession();
  const view = can("safeguarding:view", "safeguarding:review");
  if (chart.access_basis === "emergency_grant" || !(view || can("concern:raise"))) return null;
  return (
    <Section title="Safeguarding">
      {view && <LegalStatusPanel chart={chart} />}
      {view && <InterventionsPanel chart={chart} />}
      {can("concern:raise") && <ConcernPanel patientId={chart.patient.id} />}
    </Section>
  );
}

function LegalStatusPanel({ chart }: { chart: ChartOut }) {
  const { can } = useSession();
  const { person } = useDirectory();
  const history = useLoad<LegalStatusOut[]>(`/v1/patients/${chart.patient.id}/legal-status`);
  const [setting, setSetting] = useState(false);
  const [news, setNews] = useState<string | null>(null);
  return (
    <div className="panel">
      <h3>Legal status</h3>
      {news && <Notice kind="success">{news}</Notice>}
      {(history.data ?? []).length === 0 ? (
        <Empty>No legal status recorded.</Empty>
      ) : (
        <ul className="list">
          {(history.data ?? []).map((l) => (
            <li key={l.id}>
              <strong>{words(l.status)}</strong>
              {l.legal_basis && ` (${l.legal_basis})`} from {dateTime(l.valid_from)}
              {l.valid_until && ` until ${dateTime(l.valid_until)}`} · authorised by {person(l.authorised_by_id)} · {l.reason}
              {l.current && <Tag tone="good">In force</Tag>}
              {l.lapsed && <Tag tone="bad">Lapsed</Tag>}
              {l.expiring && !l.lapsed && <Tag tone="warn">Expires within 72 hours</Tag>}
            </li>
          ))}
        </ul>
      )}
      {can("mh_legal:manage") &&
        (setting ? (
          <LegalForm
            patientId={chart.patient.id}
            onCancel={() => setSetting(false)}
            onDone={(m) => {
              setSetting(false);
              setNews(m);
              history.reload();
            }}
          />
        ) : (
          <Button variant="secondary" onClick={() => setSetting(true)}>
            Record a change of legal status
          </Button>
        ))}
    </div>
  );
}

function LegalForm({ patientId, onDone, onCancel }: { patientId: string; onDone: (m: string) => void; onCancel: () => void }) {
  const { practitioners } = useDirectory();
  const [f, setF] = useState({ status: "informal" as LegalStatus, basis: "", from: nowLocal(), until: "", by: "", reason: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(useCallback((key: string, b: SetLegalStatus) => api(`/v1/patients/${patientId}/legal-status`, { body: b, key }), [patientId]));
  const compulsory = f.status !== "informal";
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.by) errs.by = "Name who authorised it.";
    if (compulsory && !f.basis.trim()) errs.basis = "Give the legal basis for a compulsory power.";
    if (compulsory && !f.until) errs.until = "A compulsory power has an end date.";
    if (f.reason.trim().length < 3) errs.reason = "Give the reason.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const ok = await save.run({
      status: f.status,
      legal_basis: f.basis.trim() || null,
      valid_from: localToIso(f.from),
      valid_until: f.until ? localToIso(f.until) : null,
      authorised_by_id: f.by,
      reason: f.reason.trim(),
    });
    if (ok) onDone("Legal status recorded. The previous status is kept in the history.");
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <form className="panel" noValidate aria-label="Record a change of legal status" onSubmit={submit}>
      {save.error && <Notice kind="error">{save.error}</Notice>}
      <div className="row">
        <Select label="Legal status" options={STATUSES} value={f.status} onChange={set("status")} />
        <Field label="Legal basis" hint={compulsory ? "The section or order" : "Optional"} value={f.basis} onChange={set("basis")} error={errors.basis} />
      </div>
      <div className="row">
        <Field label="From" type="datetime-local" value={f.from} onChange={set("from")} />
        <Field label="Until" hint={compulsory ? undefined : "Optional"} type="datetime-local" value={f.until} onChange={set("until")} error={errors.until} />
      </div>
      <Select label="Authorised by" placeholder="Choose" options={practitioners.map((p) => [p.id, p.display_name])} value={f.by} onChange={set("by")} error={errors.by} />
      <TextArea label="Reason" value={f.reason} onChange={set("reason")} error={errors.reason} maxLength={1000} />
      <div className="actions">
        <Button type="submit" busy={save.busy}>Record</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

function InterventionsPanel({ chart }: { chart: ChartOut }) {
  const { can } = useSession();
  const { person } = useDirectory();
  const list = useLoad<InterventionOut[]>(`/v1/patients/${chart.patient.id}/restrictive-interventions`);
  const [recording, setRecording] = useState(false);
  const [news, setNews] = useState<string | null>(null);
  const changed = (m: string) => {
    setNews(m);
    list.reload();
  };
  return (
    <div className="panel">
      <h3>Restrictive interventions</h3>
      {news && <Notice kind="success">{news}</Notice>}
      {(list.data ?? []).length === 0 && <Empty>None recorded.</Empty>}
      {(list.data ?? []).map((i) => (
        <article key={`${i.id}-${i.version}`} className="note" aria-label={`${words(i.intervention_type)}, ${dateTime(i.started_at)}`}>
          <h4>
            {words(i.intervention_type)} · {dateTime(i.started_at)}
            {i.ended_at ? ` to ${dateTime(i.ended_at)}` : <Tag tone="warn">Ongoing</Tag>}
            {i.reviewed_at ? <Tag tone="good">Reviewed: {words(i.review_outcome ?? "")}</Tag> : i.review_overdue ? <Tag tone="bad">Review overdue</Tag> : <Tag>Awaiting review</Tag>}
          </h4>
          <p>{i.reason}</p>
          <p className="muted">
            Authorised by {person(i.authorised_by_id)} · staff {i.staff_ids.map(person).join(", ")}
            {i.injury && ` · injury: ${i.injury_detail ?? "yes"}`}
            {i.flags.map((f) => ` · ${FLAGS[f] ?? words(f)}`)}
          </p>
          {!i.ended_at && can("safeguarding:record") && <EndForm intervention={i} onDone={changed} />}
        </article>
      ))}
      {can("safeguarding:record") &&
        (recording ? (
          <RecordForm
            chart={chart}
            onCancel={() => setRecording(false)}
            onDone={(m) => {
              setRecording(false);
              changed(m);
            }}
          />
        ) : (
          <Button variant="secondary" onClick={() => setRecording(true)}>
            Record a restrictive intervention
          </Button>
        ))}
    </div>
  );
}

function RecordForm({ chart, onDone, onCancel }: { chart: ChartOut; onDone: (m: string) => void; onCancel: () => void }) {
  const { practitioners } = useDirectory();
  const open = chart.encounters.find((e) => e.state === "in_progress");
  const [f, setF] = useState({ type: "physical_restraint" as InterventionType, reason: "", by: "", started: nowLocal(), injury: false, detail: "" });
  const [staff, setStaff] = useState<string[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(useCallback((key: string, b: RecordIntervention) => api("/v1/restrictive-interventions", { body: b, key }), []));
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (f.reason.trim().length < 3) errs.reason = "Give the reason for the intervention.";
    if (!f.by) errs.by = "Name who authorised it.";
    if (staff.length === 0) errs.staff = "Name the staff involved.";
    if (f.injury && f.detail.trim().length < 3) errs.detail = "Describe the injury.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const ok = await save.run({
      patient_id: chart.patient.id,
      encounter_id: open?.id ?? null,
      intervention_type: f.type,
      reason: f.reason.trim(),
      authorised_by_id: f.by,
      staff_ids: staff,
      started_at: localToIso(f.started),
      injury: f.injury,
      injury_detail: f.injury ? f.detail.trim() : null,
    });
    if (ok) onDone("Recorded. A safeguarding lead who took no part will review it within one working day.");
  }
  return (
    <form className="panel" noValidate aria-label="Record a restrictive intervention" onSubmit={submit}>
      {save.error && <Notice kind="error">{save.error}</Notice>}
      <div className="row">
        <Select label="Intervention" options={INTERVENTIONS} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value as InterventionType })} />
        <Field label="Started" type="datetime-local" value={f.started} onChange={(e) => setF({ ...f, started: e.target.value })} />
      </div>
      <TextArea label="Reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} error={errors.reason} maxLength={1000} />
      <Select label="Authorised by" placeholder="Choose" options={practitioners.map((p) => [p.id, p.display_name])} value={f.by} onChange={(e) => setF({ ...f, by: e.target.value })} error={errors.by} />
      <fieldset>
        <legend>Staff involved</legend>
        {errors.staff && <p className="error-text">{errors.staff}</p>}
        {practitioners.map((p) => (
          <div className="radio" key={p.id}>
            <input
              type="checkbox"
              id={`staff-${p.id}`}
              checked={staff.includes(p.id)}
              onChange={(e) => setStaff(e.target.checked ? [...staff, p.id] : staff.filter((s) => s !== p.id))}
            />
            <label htmlFor={`staff-${p.id}`}>{p.display_name}</label>
          </div>
        ))}
      </fieldset>
      <Radios
        legend="Was anyone injured?"
        name="injury"
        value={f.injury ? "yes" : "no"}
        onChange={(v) => setF({ ...f, injury: v === "yes" })}
        options={[
          ["no", "No"],
          ["yes", "Yes"],
        ]}
      />
      {f.injury && <Field label="Injury" value={f.detail} onChange={(e) => setF({ ...f, detail: e.target.value })} error={errors.detail} />}
      <div className="actions">
        <Button type="submit" busy={save.busy}>Record</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

function EndForm({ intervention: i, onDone }: { intervention: InterventionOut; onDone: (m: string) => void }) {
  const [at, setAt] = useState(nowLocal());
  // Left as shown, "now" means the moment of saving, not the minute the form
  // opened: an intervention ended within its first minute is still after it began.
  const [edited, setEdited] = useState(false);
  const [debrief, setDebrief] = useState("");
  const [error, setError] = useState<string | undefined>();
  const end = useAction(
    useCallback(
      (key: string, when: string, offered: boolean) =>
        api(`/v1/restrictive-interventions/${i.id}/end`, { body: { ended_at: edited ? localToIso(when) : new Date().toISOString(), debrief_offered: offered }, version: i.version, key }),
      [i.id, i.version, edited],
    ),
  );
  return (
    <form
      className="panel"
      noValidate
      aria-label={`End the ${words(i.intervention_type).toLowerCase()}`}
      onSubmit={async (e) => {
        e.preventDefault();
        if (!debrief) return setError("Say whether the patient was offered a debrief.");
        setError(undefined);
        if (await end.run(at, debrief === "yes")) onDone("Ended. The end time is recorded once and cannot be changed.");
      }}
    >
      {(error || end.error) && <Notice kind="error">{error ?? end.error}</Notice>}
      <Field
        label="Ended"
        hint={edited ? undefined : "Now, unless you change it"}
        type="datetime-local"
        value={at}
        onChange={(e) => {
          setAt(e.target.value);
          setEdited(true);
        }}
      />
      <Radios
        legend="Was the patient offered a debrief?"
        name={`debrief-${i.id}`}
        value={debrief}
        onChange={setDebrief}
        options={[
          ["yes", "Yes"],
          ["no", "No"],
        ]}
      />
      <Button type="submit" busy={end.busy}>Record the end</Button>
    </form>
  );
}

function ConcernPanel({ patientId }: { patientId: string }) {
  const { practitioners } = useDirectory();
  const [open, setOpen] = useState(false);
  const [news, setNews] = useState<string | null>(null);
  const [f, setF] = useState({ by: "staff" as RaisedBy, name: "", category: "dignity" as ConcernCategory, description: "", about: "" });
  const [error, setError] = useState<string | undefined>();
  const raise = useAction(useCallback((key: string, b: RaiseConcern) => api("/v1/safeguarding-concerns", { body: b, key }), []));
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (f.description.trim().length < 10) return setError("Describe the concern in at least 10 characters.");
    setError(undefined);
    const ok = await raise.run({
      patient_id: patientId,
      raised_by: f.by,
      raised_by_name: f.name.trim() || null,
      category: f.category,
      description: f.description.trim(),
      about_practitioner_id: f.about || null,
    });
    if (ok) {
      setOpen(false);
      setNews("Concern raised. A safeguarding lead who is not its subject will answer it within five days.");
    }
  }
  return (
    <div className="panel">
      <h3>Concerns</h3>
      {news && <Notice kind="success">{news}</Notice>}
      {open ? (
        <form noValidate aria-label="Raise a concern" onSubmit={submit}>
          {raise.error && <Notice kind="error">{raise.error}</Notice>}
          <div className="row">
            <Select
              label="Raised by"
              options={[
                ["patient", "The patient"],
                ["family", "Family"],
                ["advocate", "An advocate"],
                ["staff", "Staff"],
              ]}
              value={f.by}
              onChange={(e) => setF({ ...f, by: e.target.value as RaisedBy })}
            />
            <Field label="Their name" hint="Optional" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          </div>
          <div className="row">
            <Select label="About" options={CATEGORIES} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value as ConcernCategory })} />
            <Select label="About a member of staff" placeholder="No one in particular" options={practitioners.map((p) => [p.id, p.display_name])} value={f.about} onChange={(e) => setF({ ...f, about: e.target.value })} />
          </div>
          <TextArea label="The concern" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} error={error} maxLength={2000} />
          <div className="actions">
            <Button type="submit" busy={raise.busy}>Raise the concern</Button>
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </form>
      ) : (
        <Button variant="secondary" onClick={() => { setOpen(true); setNews(null); }}>
          Raise a concern
        </Button>
      )}
    </div>
  );
}

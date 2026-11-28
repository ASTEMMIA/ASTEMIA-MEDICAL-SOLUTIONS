import { useCallback, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api";
import type { CarePlanOut, Certainty, ChartOut, CreatePlan, Pathway, RecordCondition, SessionType } from "../api-types";
import { useDirectory } from "../directory";
import { date, dateTime, localToIso, today, words } from "../format";
import { useAction } from "../hooks";
import { useSession } from "../session";
import { Button, Empty, Field, Notice, Section, Select, Tag, TextArea } from "./ui";

export const PATHWAYS: [Pathway, string][] = [
  ["diabetes", "Diabetes"],
  ["renal", "Renal"],
  ["cardiovascular", "Cardiovascular"],
  ["oncology", "Oncology"],
  ["older_person", "Older person"],
];
export const SESSIONS: [SessionType, string][] = [
  ["dialysis", "Dialysis"],
  ["treatment_cycle", "Treatment cycle"],
  ["monitoring", "Monitoring"],
  ["review", "Review"],
];

/** The problem list (HS12): coded conditions with certainty and register. */
export function ProblemsSection({ chart, onChange }: { chart: ChartOut; onChange: () => void }) {
  const { can } = useSession();
  const [adding, setAdding] = useState(false);
  const [news, setNews] = useState<string | null>(null);
  const conditions = chart.conditions ?? [];
  const may = can("condition:record") && chart.access_basis !== "emergency_grant";
  return (
    <Section title="Problems" actions={may && !adding && <Button variant="secondary" onClick={() => setAdding(true)}>Record a problem</Button>}>
      {news && <Notice kind="success">{news}</Notice>}
      {adding && (
        <ConditionForm
          patientId={chart.patient.id}
          onCancel={() => setAdding(false)}
          onDone={(m) => {
            setAdding(false);
            setNews(m);
            onChange();
          }}
        />
      )}
      {conditions.length === 0 ? (
        <Empty>No problems recorded.</Empty>
      ) : (
        <ul className="list">
          {conditions.map((c) => (
            <li key={c.id}>
              {c.display} <span className="muted mono">{c.code}</span>
              {c.certainty !== "confirmed" && <Tag tone="warn">{words(c.certainty)}</Tag>}
              {c.register_code && <Tag>{words(c.register_code)} register</Tag>}
              {c.onset_date && <span className="muted"> · since {date(c.onset_date)}</span>}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function ConditionForm({ patientId, onDone, onCancel }: { patientId: string; onDone: (m: string) => void; onCancel: () => void }) {
  const [f, setF] = useState({ code: "", display: "", certainty: "confirmed" as Certainty, onset: "", register: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(useCallback((key: string, b: RecordCondition) => api(`/v1/patients/${patientId}/conditions`, { body: b, key }), [patientId]));
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.code.trim()) errs.code = "Enter the ICD-10 code, for example N18.5.";
    if (!f.display.trim()) errs.display = "Name the problem.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const ok = await save.run({
      code_system: "http://hl7.org/fhir/sid/icd-10",
      code: f.code.trim().toUpperCase(),
      display: f.display.trim(),
      certainty: f.certainty,
      onset_date: f.onset || null,
      register_code: (f.register as Pathway) || null,
    });
    if (ok) onDone(`Recorded: ${f.display.trim()}.`);
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <form className="panel" noValidate aria-label="Record a problem" onSubmit={submit}>
      {save.error && <Notice kind="error">{save.error}</Notice>}
      <div className="row">
        <Field label="ICD-10 code" value={f.code} onChange={set("code")} error={errors.code} autoComplete="off" />
        <Field label="Problem" value={f.display} onChange={set("display")} error={errors.display} />
      </div>
      <div className="row">
        <Select
          label="Certainty"
          options={[
            ["confirmed", "Confirmed"],
            ["provisional", "Provisional"],
            ["refuted", "Refuted (ruled out)"],
          ]}
          value={f.certainty}
          onChange={set("certainty")}
        />
        <Field label="Since" hint="Optional" type="date" max={today()} value={f.onset} onChange={set("onset")} />
        <Select label="Condition register" placeholder="None" options={PATHWAYS} value={f.register} onChange={set("register")} />
      </div>
      <div className="actions">
        <Button type="submit" busy={save.busy}>Record</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

/** Care plans (HS12): each on an approved pathway, with an owner and review date. */
export function CarePlansSection({ chart, onChange }: { chart: ChartOut; onChange: () => void }) {
  const { can } = useSession();
  const { person } = useDirectory();
  const [adding, setAdding] = useState(false);
  const plans = chart.care_plans ?? [];
  const may = can("careplan:manage") && chart.access_basis !== "emergency_grant";
  return (
    <Section title="Care plans" actions={may && !adding && <Button variant="secondary" onClick={() => setAdding(true)}>Start a care plan</Button>}>
      {adding && <PlanForm chart={chart} onCancel={() => setAdding(false)} onDone={() => { setAdding(false); onChange(); }} />}
      {plans.length === 0 ? (
        <Empty>No care plans.</Empty>
      ) : (
        <ul className="list">
          {plans.map((p) => (
            <li key={p.id}>
              <Link to={`/care-plans/${p.id}`}>{p.title}</Link> <span className="muted">({words(p.pathway)}, revision {p.current_revision})</span> · owner {person(p.owner_id)} · next session{" "}
              {dateTime(p.next_session)} · review by {date(p.review_date)}
              {p.status !== "active" && <Tag>{words(p.status)}</Tag>}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function PlanForm({ chart, onDone, onCancel }: { chart: ChartOut; onDone: () => void; onCancel: () => void }) {
  const { practitioners } = useDirectory();
  const { me } = useSession();
  const conditions = (chart.conditions ?? []).filter((c) => c.certainty !== "refuted");
  const inThreeMonths = new Date(Date.now() + 90 * 86_400_000).toISOString().slice(0, 10);
  const soon = new Date(Date.now() + 86_400_000);
  soon.setHours(9, 0, 0, 0);
  const start = new Date(soon.getTime() - soon.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [f, setF] = useState({
    title: "",
    pathway: "renal" as Pathway,
    condition: conditions[0]?.id ?? "",
    owner: me?.practitioner_id ?? "",
    review: inThreeMonths,
    start,
    session: "dialysis" as SessionType,
    interval: "2",
    sessions: "4",
    instructions: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(useCallback((key: string, b: CreatePlan) => api<CarePlanOut>("/v1/care-plans", { body: b, key }), []));
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (f.title.trim().length < 3) errs.title = "Give the plan a title.";
    if (!f.owner) errs.owner = "Name the plan's owner.";
    if (f.instructions.trim().length < 3) errs.instructions = "Write the instructions for each session.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const made = await save.run({
      patient_id: chart.patient.id,
      condition_id: f.condition || null,
      pathway: f.pathway,
      title: f.title.trim(),
      owner_id: f.owner,
      review_date: f.review,
      revision: {
        effective_from: localToIso(f.start),
        session_type: f.session,
        interval_days: Number(f.interval),
        sessions: Number(f.sessions),
        instructions: f.instructions.trim(),
      },
    });
    if (made) onDone();
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <form className="panel" noValidate aria-label="Start a care plan" onSubmit={submit}>
      {save.error && <Notice kind="error">{save.error}</Notice>}
      <div className="row">
        <Field label="Title" value={f.title} onChange={set("title")} error={errors.title} />
        <Select label="Pathway" options={PATHWAYS} value={f.pathway} onChange={set("pathway")} />
      </div>
      <div className="row">
        <Select label="For the problem" placeholder="None" options={conditions.map((c) => [c.id, c.display])} value={f.condition} onChange={set("condition")} />
        <Select label="Owner" placeholder="Choose" options={practitioners.map((p) => [p.id, p.display_name])} value={f.owner} onChange={set("owner")} error={errors.owner} />
        <Field label="Review by" type="date" value={f.review} onChange={set("review")} />
      </div>
      <fieldset>
        <legend>Sessions</legend>
        <div className="row">
          <Select label="Type of session" options={SESSIONS} value={f.session} onChange={set("session")} />
          <Field label="First session" type="datetime-local" value={f.start} onChange={set("start")} />
        </div>
        <div className="row">
          <Field label="Days between sessions" type="number" min={1} max={365} value={f.interval} onChange={set("interval")} />
          <Field label="Number of sessions" type="number" min={1} max={52} value={f.sessions} onChange={set("sessions")} />
        </div>
        <TextArea label="Instructions for each session" value={f.instructions} onChange={set("instructions")} error={errors.instructions} maxLength={2000} />
      </fieldset>
      <div className="actions">
        <Button type="submit" busy={save.busy}>Start the plan</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}


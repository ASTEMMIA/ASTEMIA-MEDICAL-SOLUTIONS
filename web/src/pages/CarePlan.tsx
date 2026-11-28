import { useCallback, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { api, messageFor } from "../api";
import type { CarePlanOut, PlanCycleOut, RevisePlan, SessionType } from "../api-types";
import { SESSIONS } from "../components/PlansSection";
import { Button, Field, Loading, Notice, Page, Section, Select, Tag, TextArea } from "../components/ui";
import { useDirectory } from "../directory";
import { date, dateTime, localToIso, words } from "../format";
import { useAction, useLoad } from "../hooks";
import { useSession } from "../session";

const CYCLE: Record<string, ["good" | "warn" | "bad" | "neutral", string]> = {
  scheduled: ["neutral", "Scheduled"],
  held: ["warn", "Held: clashes with another plan"],
  completed: ["good", "Completed"],
  cancelled: ["neutral", "Cancelled"],
};

/**
 * One care plan (HS12): every authorised revision, kept; sessions with the
 * revision each was delivered under; clashes held for the owner; revise from
 * a future time, or discontinue.
 */
export function CarePlan() {
  const { id = "" } = useParams();
  const plan = useLoad<CarePlanOut>(`/v1/care-plans/${id}`);
  const { person } = useDirectory();
  const { can, me } = useSession();
  const [news, setNews] = useState<string | null>(null);
  const [action, setAction] = useState<"" | "revise" | "discontinue">("");
  if (plan.loading && !plan.data) return <Loading />;
  if (!plan.data)
    return (
      <Page title="Care plan">
        <Notice kind="error">{messageFor(plan.error)}</Notice>
      </Page>
    );
  const p = plan.data;
  const changed = (m: string) => {
    setAction("");
    setNews(m);
    plan.reload();
  };
  const owner = p.owner_id === me?.practitioner_id;
  const active = p.status === "active";
  return (
    <Page title={p.title}>
      <p>
        <Link to={`/patients/${p.patient_id}`}>Back to the patient</Link>
      </p>
      <dl className="facts">
        <dt>Pathway</dt>
        <dd>{words(p.pathway)}</dd>
        <dt>Owner</dt>
        <dd>{person(p.owner_id)}</dd>
        <dt>Review by</dt>
        <dd>{date(p.review_date)}</dd>
        <dt>Status</dt>
        <dd>
          {active ? <Tag tone="good">Active</Tag> : <Tag>{words(p.status)}</Tag>}
          {p.discontinuation_reason && ` · ${p.discontinuation_reason}`}
        </dd>
      </dl>
      {news && <Notice kind="success">{news}</Notice>}
      {active && can("careplan:manage") && !action && (
        <div className="actions">
          <Button variant="secondary" onClick={() => setAction("revise")}>Revise the plan</Button>
          <Button variant="secondary" onClick={() => setAction("discontinue")}>Discontinue</Button>
        </div>
      )}
      {action === "revise" && <Revise plan={p} onCancel={() => setAction("")} onDone={changed} />}
      {action === "discontinue" && <Discontinue plan={p} onCancel={() => setAction("")} onDone={changed} />}
      <Section title="Sessions">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Revision</th>
              <th scope="col">Status</th>
              <th scope="col">
                <span className="visually-hidden">Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {p.cycles.map((c) => (
              <Cycle key={`${c.id}-${c.version}`} cycle={c} owner={owner} onDone={changed} />
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Revisions">
        {[...p.revisions].reverse().map((r) => (
          <article key={r.id} className="note" aria-label={`Revision ${r.revision_number}`}>
            <h3>
              Revision {r.revision_number} <span className="muted">· from {dateTime(r.effective_from)}</span>
              {r.revision_number === p.current_revision && <Tag tone="good">Current</Tag>}
            </h3>
            <p>
              {words(r.session_type)} every {r.interval_days === 1 ? "day" : `${r.interval_days} days`}
              {r.protocol_code && ` · protocol ${r.protocol_code}`}
            </p>
            <p className="note-body">{r.instructions}</p>
            <p className="muted">
              Authorised by {person(r.authorised_by_id)}, {dateTime(r.recorded_at)} · {r.reason}
            </p>
          </article>
        ))}
      </Section>
    </Page>
  );
}

function Cycle({ cycle: c, owner, onDone }: { cycle: PlanCycleOut; owner: boolean; onDone: (m: string) => void }) {
  const { can } = useSession();
  const { person } = useDirectory();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | undefined>();
  const complete = useAction(useCallback((key: string, n: string) => api(`/v1/plan-cycles/${c.id}/complete`, { body: { note: n || null }, version: c.version, key }), [c.id, c.version]));
  const release = useAction(useCallback((key: string, n: string) => api(`/v1/plan-cycles/${c.id}/release`, { body: { note: n }, version: c.version, key }), [c.id, c.version]));
  const [tone, label] = CYCLE[c.status] ?? ["neutral", words(c.status)];
  const when = dateTime(c.scheduled_at);
  const held = c.status === "held";
  const may = (c.status === "scheduled" && can("careplan:deliver")) || (held && owner);
  return (
    <>
      <tr>
        <th scope="row">{when}</th>
        <td>{c.revision_number}</td>
        <td>
          <Tag tone={tone}>{label}</Tag>
          {c.completed_at && (
            <span className="muted">
              {" "}
              by {person(c.completed_by_id)}
              {c.outcome_note && `: ${c.outcome_note}`}
            </span>
          )}
        </td>
        <td>
          {may && (
            <Button variant="secondary" aria-expanded={open} onClick={() => setOpen(!open)}>
              {held ? "Resolve the clash" : "Record the session"}
              <span className="visually-hidden">: {when}</span>
            </Button>
          )}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={4}>
            <form
              className="panel"
              noValidate
              aria-label={held ? `Resolve the clash on ${when}` : `Record the session on ${when}`}
              onSubmit={async (e) => {
                e.preventDefault();
                if (held && note.trim().length < 3) return setError("Say how the clash was resolved.");
                setError(undefined);
                const ok = held ? await release.run(note.trim()) : await complete.run(note.trim());
                if (ok) onDone(held ? `The session on ${when} is scheduled again.` : `Session on ${when} recorded as delivered.`);
              }}
            >
              {(complete.error || release.error) && <Notice kind="error">{complete.error ?? release.error}</Notice>}
              <Field label={held ? "How the clash was resolved" : "Outcome"} hint={held ? undefined : "Optional"} value={note} onChange={(e) => setNote(e.target.value)} error={error} maxLength={500} />
              <Button type="submit" busy={complete.busy || release.busy}>
                {held ? "Release the session" : "Mark delivered"}
              </Button>
            </form>
          </td>
        </tr>
      )}
    </>
  );
}

function Revise({ plan, onDone, onCancel }: { plan: CarePlanOut; onDone: (m: string) => void; onCancel: () => void }) {
  const current = plan.revisions.find((r) => r.revision_number === plan.current_revision) ?? plan.revisions.at(-1);
  const next = new Date(Date.now() + 86_400_000);
  next.setHours(9, 0, 0, 0);
  const [f, setF] = useState({
    from: new Date(next.getTime() - next.getTimezoneOffset() * 60000).toISOString().slice(0, 16),
    session: (current?.session_type ?? "review") as SessionType,
    interval: String(current?.interval_days ?? 7),
    sessions: "4",
    instructions: current?.instructions ?? "",
    reason: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(useCallback((key: string, b: RevisePlan) => api(`/v1/care-plans/${plan.id}/revisions`, { body: b, version: plan.version, key }), [plan.id, plan.version]));
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (f.reason.trim().length < 3) errs.reason = "Give the reason for the revision.";
    if (f.instructions.trim().length < 3) errs.instructions = "Write the instructions.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const ok = await save.run({
      effective_from: localToIso(f.from),
      session_type: f.session,
      interval_days: Number(f.interval),
      sessions: Number(f.sessions),
      instructions: f.instructions.trim(),
      reason: f.reason.trim(),
    });
    if (ok) onDone("Revised. Sessions from that time follow the new revision; completed sessions keep theirs.");
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <form className="panel" noValidate aria-label="Revise the plan" onSubmit={submit}>
      {save.error && <Notice kind="error">{save.error}</Notice>}
      <div className="row">
        <Field label="Applies from" type="datetime-local" value={f.from} onChange={set("from")} />
        <Select label="Type of session" options={SESSIONS} value={f.session} onChange={set("session")} />
      </div>
      <div className="row">
        <Field label="Days between sessions" type="number" min={1} max={365} value={f.interval} onChange={set("interval")} />
        <Field label="Number of sessions" type="number" min={1} max={52} value={f.sessions} onChange={set("sessions")} />
      </div>
      <TextArea label="Instructions for each session" value={f.instructions} onChange={set("instructions")} error={errors.instructions} maxLength={2000} />
      <Field label="Reason for the revision" value={f.reason} onChange={set("reason")} error={errors.reason} maxLength={500} />
      <div className="actions">
        <Button type="submit" busy={save.busy}>Authorise the revision</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

function Discontinue({ plan, onDone, onCancel }: { plan: CarePlanOut; onDone: (m: string) => void; onCancel: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const stop = useAction(useCallback((key: string, r: string) => api(`/v1/care-plans/${plan.id}/discontinue`, { body: { reason: r }, version: plan.version, key }), [plan.id, plan.version]));
  return (
    <form
      className="panel"
      noValidate
      aria-label="Discontinue the plan"
      onSubmit={async (e) => {
        e.preventDefault();
        if (reason.trim().length < 3) return setError("Give the reason for discontinuing.");
        setError(undefined);
        if (await stop.run(reason.trim())) onDone("Plan discontinued. Sessions still to come were cancelled.");
      }}
    >
      {stop.error && <Notice kind="error">{stop.error}</Notice>}
      <Field label="Reason for discontinuing" value={reason} onChange={(e) => setReason(e.target.value)} error={error} maxLength={500} />
      <div className="actions">
        <Button type="submit" variant="danger" busy={stop.busy}>Discontinue the plan</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Keep it</Button>
      </div>
    </form>
  );
}

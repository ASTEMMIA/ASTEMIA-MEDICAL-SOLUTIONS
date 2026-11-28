import { useCallback, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import type { ChartOut, Discharge, DischargeSummaryOut, Disposition, DraftDischarge, EncounterOut, OutstandingItem, OutstandingKind } from "../api-types";
import { useDirectory } from "../directory";
import { localToIso, nowLocal, roleName, words } from "../format";
import { useAction, useLoad } from "../hooks";
import { useSession } from "../session";
import { Button, Field, Notice, Section, Select, TextArea } from "./ui";

const DISPOSITIONS: [Disposition, string][] = [
  ["home", "Home"],
  ["home_with_support", "Home with support"],
  ["transferred", "Transferred to another facility"],
  ["self_discharge", "Self-discharge"],
  ["died", "Died"],
];
const KINDS: [OutstandingKind, string][] = [
  ["medication", "Medicines to supply"],
  ["referral", "Referral to make"],
  ["follow_up", "Follow-up to arrange"],
];

/**
 * Discharge (HS05, WF06 step 3): a summary drafted by the care team, then a
 * clinician's sign-off that finishes the visit and gives every outstanding
 * item a named owner or queue (or a supervised exception).
 */
export function DischargeSection({ chart, onChange }: { chart: ChartOut; onChange: () => void }) {
  const { can } = useSession();
  const open = chart.encounters.filter((e) => e.state === "in_progress");
  if (!open.length || chart.access_basis === "emergency_grant" || !can("note:write", "discharge:sign")) return null;
  return (
    <Section title="Discharge">
      {open.map((e) => (
        <VisitDischarge key={e.id} encounter={e} onChange={onChange} />
      ))}
    </Section>
  );
}

function VisitDischarge({ encounter, onChange }: { encounter: EncounterOut; onChange: () => void }) {
  const { can } = useSession();
  const summary = useLoad<DischargeSummaryOut>(`/v1/encounters/${encounter.id}/discharge-summary`);
  const none = summary.error instanceof ApiError && summary.error.status === 404;
  const [editing, setEditing] = useState(false);
  const [signing, setSigning] = useState(false);
  const [news, setNews] = useState<string | null>(null);
  const s = summary.data;
  return (
    <article className="pair" aria-label={`Discharge for visit ${encounter.visit_number}`}>
      <h3>Visit {encounter.visit_number}</h3>
      {news && <Notice kind="success">{news}</Notice>}
      {s && !editing && (
        <>
          <p>
            <strong>{words(s.disposition)}.</strong> {s.summary}
          </p>
          {s.follow_up && <p>Follow-up: {s.follow_up}</p>}
          <p className="muted">Draft summary</p>
        </>
      )}
      {none && !editing && <p className="muted">No discharge summary yet.</p>}
      {editing ? (
        <SummaryForm
          encounterId={encounter.id}
          current={s ?? null}
          onCancel={() => setEditing(false)}
          onDone={() => {
            setEditing(false);
            setNews("Summary saved as a draft.");
            summary.reload();
          }}
        />
      ) : signing && s ? (
        <SignOff
          encounter={encounter}
          onCancel={() => setSigning(false)}
          onDone={(m) => {
            setSigning(false);
            setNews(m);
            onChange();
          }}
        />
      ) : (
        (s || none) && (
          <div className="actions">
            {can("note:write") && (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                {s ? "Edit the summary" : "Write the discharge summary"}
              </Button>
            )}
            {s && can("discharge:sign") && <Button onClick={() => setSigning(true)}>Sign off the discharge</Button>}
          </div>
        )
      )}
    </article>
  );
}

function SummaryForm({ encounterId, current, onDone, onCancel }: { encounterId: string; current: DischargeSummaryOut | null; onDone: () => void; onCancel: () => void }) {
  const [f, setF] = useState({ disposition: (current?.disposition ?? "home") as Disposition, summary: current?.summary ?? "", follow: current?.follow_up ?? "" });
  const [error, setError] = useState<string | undefined>();
  const save = useAction(
    useCallback(
      (key: string, b: DraftDischarge) => api(`/v1/encounters/${encounterId}/discharge-summary`, { body: b, version: current?.version, key }),
      [encounterId, current?.version],
    ),
  );
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (f.summary.trim().length < 3) return setError("Write the summary of the stay.");
    setError(undefined);
    if (await save.run({ disposition: f.disposition, summary: f.summary.trim(), follow_up: f.follow.trim() || null })) onDone();
  }
  return (
    <form className="panel" noValidate aria-label="Discharge summary" onSubmit={submit}>
      {save.error && <Notice kind="error">{save.error}</Notice>}
      <Select label="Going to" options={DISPOSITIONS} value={f.disposition} onChange={(e) => setF({ ...f, disposition: e.target.value as Disposition })} />
      <TextArea label="Summary of the stay" rows={6} value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} error={error} />
      <Field label="Follow-up" hint="Optional" value={f.follow} onChange={(e) => setF({ ...f, follow: e.target.value })} />
      <div className="actions">
        <Button type="submit" busy={save.busy}>Save draft</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

interface Row {
  kind: OutstandingKind;
  description: string;
  owner: string;
  due: string;
  exception: string;
}

const QUEUES = ["clinician", "nurse", "scheduler", "team_supervisor"];

function SignOff({ encounter, onDone, onCancel }: { encounter: EncounterOut; onDone: (m: string) => void; onCancel: () => void }) {
  const { practitioners } = useDirectory();
  const tomorrow = new Date(Date.now() + 86_400_000);
  const due = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [at, setAt] = useState(nowLocal());
  const [rows, setRows] = useState<Row[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const sign = useAction(
    useCallback(
      (key: string, b: Discharge) => api<DischargeSummaryOut>(`/v1/encounters/${encounter.id}/discharge`, { body: b, version: encounter.version, key }),
      [encounter.id, encounter.version],
    ),
  );
  const owners: [string, string][] = [
    ["", "No owner: supervised exception"],
    ...practitioners.map((p): [string, string] => [p.id, p.display_name]),
    ...QUEUES.map((q): [string, string] => [`queue:${q}`, `${roleName(q)} queue`]),
  ];
  const update = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  async function submit(e: FormEvent) {
    e.preventDefault();
    const problems: string[] = [];
    rows.forEach((r, i) => {
      if (r.description.trim().length < 3) problems.push(`Item ${i + 1}: say what is outstanding.`);
      if (!r.owner && r.exception.trim().length < 3) problems.push(`Item ${i + 1}: name an owner, or give the reason there is none.`);
    });
    setErrors(problems);
    if (problems.length) return;
    const outstanding: OutstandingItem[] = rows.map((r) => ({
      kind: r.kind,
      description: r.description.trim(),
      due_at: localToIso(r.due),
      ...(r.owner.startsWith("queue:") ? { queue: r.owner.slice(6) } : r.owner ? { owner_id: r.owner } : { exception_reason: r.exception.trim() }),
    }));
    const done = await sign.run({ discharged_at: localToIso(at), outstanding });
    if (done) onDone(`Discharged. ${(done.tasks ?? []).length} follow-up tasks were opened, each with an owner.`);
  }
  return (
    <form className="panel" noValidate aria-label="Sign off the discharge" onSubmit={submit}>
      <Notice>Signing off finishes the visit. Results still awaited stay with their accountable reviewer; list anything else outstanding with its owner.</Notice>
      {(errors.length > 0 || sign.error) && (
        <Notice kind="error">
          {sign.error && <p>{sign.error}</p>}
          {errors.length > 0 && (
            <ul>
              {errors.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
        </Notice>
      )}
      <Field label="Discharged at" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} />
      {rows.map((r, i) => (
        <fieldset key={i} className="panel">
          <legend>Outstanding item {i + 1}</legend>
          <div className="row">
            <Select label="Kind" options={KINDS} value={r.kind} onChange={(e) => update(i, { kind: e.target.value as OutstandingKind })} />
            <Field label="What is outstanding" value={r.description} onChange={(e) => update(i, { description: e.target.value })} />
          </div>
          <div className="row">
            <Select label="Owner" options={owners} value={r.owner} onChange={(e) => update(i, { owner: e.target.value })} />
            <Field label="Due" type="datetime-local" value={r.due} onChange={(e) => update(i, { due: e.target.value })} />
          </div>
          {!r.owner && <Field label="Why there is no owner" hint="Sent to the team supervisors as a supervised exception." value={r.exception} onChange={(e) => update(i, { exception: e.target.value })} />}
          <Button type="button" variant="secondary" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
            Remove item {i + 1}
          </Button>
        </fieldset>
      ))}
      <p>
        <Button type="button" variant="secondary" onClick={() => setRows([...rows, { kind: "follow_up", description: "", owner: "queue:scheduler", due, exception: "" }])}>
          Add an outstanding item
        </Button>
      </p>
      <div className="actions">
        <Button type="submit" busy={sign.busy}>Sign off and discharge</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

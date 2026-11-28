import { useCallback, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api, messageFor } from "../api";
import type { CreateTask, Priority, TaskOut, TaskType } from "../api-types";
import { Button, Empty, Field, Loading, Notice, Page, Radios, Select, Tag, TextArea } from "../components/ui";
import { useDirectory } from "../directory";
import { dateTime, localToIso, roleName, words } from "../format";
import { useAction, useLoad } from "../hooks";
import { useSession } from "../session";

const TYPES: [TaskType, string][] = [
  ["general", "General"],
  ["recall", "Recall"],
  ["referral_follow_up", "Referral follow-up"],
  ["result_follow_up", "Result follow-up"],
  ["document_review", "Document review"],
  ["discharge_follow_up", "Discharge follow-up"],
];
const QUEUES = ["clinician", "nurse", "scheduler", "registrar", "records_clerk", "team_supervisor"];

/**
 * The Daybook (UG03): tasks for me or my team's queue, oldest due first.
 * Supervisors see every active task, overdue first, and reassign.
 */
export function Daybook() {
  const { can } = useSession();
  const [params] = useSearchParams();
  const [view, setView] = useState("mine");
  const tasks = useLoad<TaskOut[]>("/v1/tasks", { view, limit: 200 });
  const [creating, setCreating] = useState(Boolean(params.get("patient")));
  const [news, setNews] = useState<string | null>(null);
  const changed = (m: string) => {
    setNews(m);
    tasks.reload();
  };
  const list = tasks.data ?? [];
  const overdue = list.filter((t) => t.overdue).length;
  return (
    <Page title="Daybook" intro="Tasks for you and your team's queues. Every task has a named owner or a queue, and a due time.">
      {can("task:supervise") && (
        <Radios
          legend="Show"
          name="daybook-view"
          value={view}
          onChange={setView}
          options={[
            ["mine", "My tasks and queues"],
            ["all", "Every active task (supervisor)"],
          ]}
        />
      )}
      {news && <Notice kind="success">{news}</Notice>}
      {creating ? (
        <NewTask patientId={params.get("patient")} onCancel={() => setCreating(false)} onDone={(m) => { setCreating(false); changed(m); }} />
      ) : (
        <p>
          <Button variant="secondary" onClick={() => setCreating(true)}>
            New task
          </Button>
        </p>
      )}
      {tasks.loading && <Loading />}
      {tasks.error !== null && <Notice kind="error">{messageFor(tasks.error)}</Notice>}
      {tasks.data && (list.length === 0 ? <Empty>No open tasks.</Empty> : overdue > 0 && <Notice kind="warning">{overdue === 1 ? "1 task is overdue." : `${overdue} tasks are overdue.`}</Notice>)}
      {list.map((t) => (
        <TaskCard key={`${t.id}-${t.version}`} task={t} onChange={changed} />
      ))}
    </Page>
  );
}

function TaskCard({ task: t, onChange }: { task: TaskOut; onChange: (m: string) => void }) {
  const { person } = useDirectory();
  const { me, can } = useSession();
  const [action, setAction] = useState<"" | "complete" | "reassign" | "cancel">("");
  const owner = t.assignee_id ? person(t.assignee_id) : `${roleName(t.queue ?? "")} queue`;
  const ack = useAction(useCallback((key: string) => api(`/v1/tasks/${t.id}/acknowledge`, { body: {}, version: t.version, key }), [t.id, t.version]));
  const mine = t.assignee_id === me?.practitioner_id;
  const queued = Boolean(!t.assignee_id && t.queue && me?.roles.includes(t.queue));
  // The owner, a member of the owning queue or a supervisor may act (UG03).
  const mayAct = mine || queued || can("task:supervise");
  return (
    <article className="pair" aria-label={t.subject}>
      <h3>
        {t.subject} {t.priority === "urgent" && <Tag tone="bad">Urgent</Tag>} {t.overdue && <Tag tone="warn">Overdue</Tag>}{" "}
        {t.status === "acknowledged" && <Tag>Acknowledged</Tag>}
      </h3>
      <p className="muted">
        {words(t.task_type)} · due {dateTime(t.due_at)} · {owner}
        {t.escalation_step > 0 && ` · escalated to supervisors`}
        {t.patient_id && (
          <>
            {" · "}
            <Link to={`/patients/${t.patient_id}`}>open the patient</Link>
          </>
        )}
      </p>
      {ack.error && <Notice kind="error">{ack.error}</Notice>}
      {!action && (
        <div className="actions">
          {t.status === "open" && (mine || queued) && (
            <Button variant="secondary" busy={ack.busy} onClick={async () => (await ack.run()) && onChange(queued ? `You have taken "${t.subject}".` : `Acknowledged: ${t.subject}.`)}>
              {queued ? "Take it" : "Acknowledge"}
              <span className="visually-hidden">: {t.subject}</span>
            </Button>
          )}
          {mayAct && (
            <Button onClick={() => setAction("complete")}>
              Complete<span className="visually-hidden">: {t.subject}</span>
            </Button>
          )}
          {mayAct && (
            <Button variant="secondary" onClick={() => setAction("reassign")}>
              Reassign<span className="visually-hidden">: {t.subject}</span>
            </Button>
          )}
          {mayAct && (
            <Button variant="secondary" onClick={() => setAction("cancel")}>
              Cancel<span className="visually-hidden"> the task: {t.subject}</span>
            </Button>
          )}
        </div>
      )}
      {action === "complete" && <Complete task={t} onBack={() => setAction("")} onDone={onChange} />}
      {action === "reassign" && <Reassign task={t} onBack={() => setAction("")} onDone={onChange} />}
      {action === "cancel" && <CancelTask task={t} onBack={() => setAction("")} onDone={onChange} />}
      {t.history.length > 1 && (
        <details>
          <summary>Ownership history ({t.history.length})</summary>
          <ul className="list">
            {t.history.map((h) => (
              <li key={h.recorded_at + (h.assignee_id ?? h.queue)}>
                {h.assignee_id ? person(h.assignee_id) : `${roleName(h.queue ?? "")} queue`} · {dateTime(h.recorded_at)} · {h.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

function Complete({ task: t, onBack, onDone }: { task: TaskOut; onBack: () => void; onDone: (m: string) => void }) {
  const [note, setNote] = useState("");
  const run = useAction(useCallback((key: string, n: string) => api(`/v1/tasks/${t.id}/complete`, { body: { note: n || null }, version: t.version, key }), [t.id, t.version]));
  return (
    <form className="panel" noValidate aria-label={`Complete ${t.subject}`} onSubmit={async (e) => { e.preventDefault(); if (await run.run(note.trim())) onDone(`Completed: ${t.subject}.`); }}>
      {run.error && <Notice kind="error">{run.error}</Notice>}
      <TextArea label="Outcome" hint="Optional: what was done" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
      <div className="actions">
        <Button type="submit" busy={run.busy}>Mark complete</Button>
        <Button type="button" variant="secondary" onClick={onBack}>Back</Button>
      </div>
    </form>
  );
}

function Reassign({ task: t, onBack, onDone }: { task: TaskOut; onBack: () => void; onDone: (m: string) => void }) {
  const { practitioners, person } = useDirectory();
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const run = useAction(
    useCallback(
      (key: string, target: string, why: string) =>
        api(`/v1/tasks/${t.id}/reassign`, {
          body: target.startsWith("queue:") ? { queue: target.slice(6), reason: why } : { assignee_id: target, reason: why },
          version: t.version,
          key,
        }),
      [t.id, t.version],
    ),
  );
  const options: [string, string][] = [
    ...practitioners.map((p): [string, string] => [p.id, p.display_name]),
    ...QUEUES.map((q): [string, string] => [`queue:${q}`, `${roleName(q)} queue`]),
  ];
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!to) return setError("Choose who takes the task.");
    if (reason.trim().length < 3) return setError("Give the reason: it stays in the ownership history.");
    setError(undefined);
    if (await run.run(to, reason.trim())) onDone(`Reassigned to ${to.startsWith("queue:") ? `the ${roleName(to.slice(6))} queue` : person(to)}. The due time is unchanged.`);
  }
  return (
    <form className="panel" noValidate aria-label={`Reassign ${t.subject}`} onSubmit={submit}>
      {(error || run.error) && <Notice kind="error">{error ?? run.error}</Notice>}
      <Select label="New owner" placeholder="Choose" options={options} value={to} onChange={(e) => setTo(e.target.value)} />
      <Field label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255} />
      <div className="actions">
        <Button type="submit" busy={run.busy}>Reassign</Button>
        <Button type="button" variant="secondary" onClick={onBack}>Back</Button>
      </div>
    </form>
  );
}

function CancelTask({ task: t, onBack, onDone }: { task: TaskOut; onBack: () => void; onDone: (m: string) => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const run = useAction(useCallback((key: string, why: string) => api(`/v1/tasks/${t.id}/cancel`, { body: { reason: why }, version: t.version, key }), [t.id, t.version]));
  return (
    <form
      className="panel"
      noValidate
      aria-label={`Cancel ${t.subject}`}
      onSubmit={async (e) => {
        e.preventDefault();
        if (reason.trim().length < 3) return setError("Give the reason for cancelling.");
        setError(undefined);
        if (await run.run(reason.trim())) onDone(`Cancelled: ${t.subject}.`);
      }}
    >
      {run.error && <Notice kind="error">{run.error}</Notice>}
      <Field label="Reason for cancelling" value={reason} onChange={(e) => setReason(e.target.value)} error={error} maxLength={255} />
      <div className="actions">
        <Button type="submit" variant="danger" busy={run.busy}>Cancel the task</Button>
        <Button type="button" variant="secondary" onClick={onBack}>Keep it</Button>
      </div>
    </form>
  );
}

function NewTask({ patientId, onDone, onCancel }: { patientId: string | null; onDone: (m: string) => void; onCancel: () => void }) {
  const { practitioners } = useDirectory();
  const tomorrow = new Date(Date.now() + 86_400_000);
  tomorrow.setMinutes(0, 0, 0);
  const due = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [f, setF] = useState({ subject: "", type: "general" as TaskType, priority: "routine" as Priority, due, owner: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useAction(useCallback((key: string, b: CreateTask) => api<TaskOut>("/v1/tasks", { body: b, key }), []));
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (f.subject.trim().length < 3) errs.subject = "Say what needs doing.";
    if (!f.owner) errs.owner = "Every task needs a named owner or a queue.";
    if (!f.due) errs.due = "Set when it is due.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const made = await create.run({
      subject: f.subject.trim(),
      task_type: f.type,
      priority: f.priority,
      due_at: localToIso(f.due),
      patient_id: patientId,
      ...(f.owner.startsWith("queue:") ? { queue: f.owner.slice(6) } : { assignee_id: f.owner }),
    });
    if (made) onDone(`Task created: ${made.subject}.`);
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <form className="panel" noValidate aria-label="New task" onSubmit={submit}>
      {create.error && <Notice kind="error">{create.error}</Notice>}
      {patientId && <Notice>The task is for the patient you came from.</Notice>}
      <Field label="What needs doing" value={f.subject} onChange={set("subject")} error={errors.subject} maxLength={200} />
      <div className="row">
        <Select label="Type" options={TYPES} value={f.type} onChange={set("type")} />
        <Field label="Due" type="datetime-local" value={f.due} onChange={set("due")} error={errors.due} />
      </div>
      <div className="row">
        <Select
          label="Owner"
          placeholder="Choose"
          options={[
            ...practitioners.map((p): [string, string] => [p.id, p.display_name]),
            ...QUEUES.map((q): [string, string] => [`queue:${q}`, `${roleName(q)} queue`]),
          ]}
          value={f.owner}
          onChange={set("owner")}
          error={errors.owner}
        />
        <Select
          label="Priority"
          options={[
            ["routine", "Routine"],
            ["urgent", "Urgent"],
          ]}
          value={f.priority}
          onChange={set("priority")}
        />
      </div>
      <div className="actions">
        <Button type="submit" busy={create.busy}>Create task</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

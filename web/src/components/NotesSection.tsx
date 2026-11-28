import { useCallback, useState, type FormEvent } from "react";
import { api } from "../api";
import type { ChartOut, CreateEntry, EntryOut, EntrySummary, NoteType } from "../api-types";
import { useDirectory } from "../directory";
import { dateTime, words } from "../format";
import { useAction, useLoad } from "../hooks";
import { useSession } from "../session";
import { Button, Empty, Field, Notice, Section, Select, TextArea } from "./ui";

const TYPES: [NoteType, string][] = [
  ["consultation", "Consultation"],
  ["progress", "Progress note"],
  ["ward_round", "Ward round"],
  ["procedure", "Procedure"],
  ["nursing", "Nursing note"],
  ["mental_health_assessment", "Mental health assessment"],
];

/** Who may sign which note type (ST04): nurses sign nursing notes, clinicians any. */
function canSign(can: (...c: string[]) => boolean, type: string): boolean {
  return type === "nursing" ? can("note:sign", "note:sign_nursing") : can("note:sign");
}

/**
 * Clinical notes (UG02, WF01 step 3): write a draft only its author sees, sign
 * it, and correct a signed note with a reason. A signed revision never changes.
 */
export function NotesSection({ chart, onChange }: { chart: ChartOut; onChange: () => void }) {
  const { can, me } = useSession();
  const { person } = useDirectory();
  const pid = chart.patient.id;
  const mayWrite = can("note:write") && chart.access_basis !== "emergency_grant";
  const drafts = useLoad<EntryOut[]>(mayWrite ? `/v1/patients/${pid}/drafts` : null);
  const [writing, setWriting] = useState(false);
  const [news, setNews] = useState<string | null>(null);
  const open = chart.encounters.filter((e) => e.state === "in_progress");
  const signed = chart.entries ?? [];
  const changed = (message: string) => {
    setNews(message);
    drafts.reload();
    onChange();
  };
  return (
    <Section
      title="Clinical notes"
      actions={
        mayWrite &&
        !writing &&
        chart.encounters.length > 0 && (
          <Button variant="secondary" onClick={() => setWriting(true)}>
            Write a note
          </Button>
        )
      }
    >
      {news && <Notice kind="success">{news}</Notice>}
      {writing && (
        <WriteForm
          chart={chart}
          encounters={open.length ? open : chart.encounters}
          onCancel={() => setWriting(false)}
          onDone={() => {
            setWriting(false);
            changed("Draft saved. Only you can see it until it is signed.");
          }}
        />
      )}
      {(drafts.data ?? []).map((d) => (
        <Draft key={`${d.id}-${d.version}`} entry={d} mayEditSign={canSign(can, d.note_type)} onChange={changed} />
      ))}
      {signed.length === 0 && !(drafts.data ?? []).length ? (
        <Empty>No signed notes.</Empty>
      ) : (
        signed.map((n) => <Signed key={n.id} note={n} mine={n.signed_by_id === me?.practitioner_id && mayWrite} who={person(n.signed_by_id)} onChange={changed} />)
      )}
    </Section>
  );
}

function WriteForm({ chart, encounters, onDone, onCancel }: { chart: ChartOut; encounters: ChartOut["encounters"]; onDone: () => void; onCancel: () => void }) {
  const { can } = useSession();
  const types = TYPES.filter(([t]) => t !== "mental_health_assessment" || can("sensitive:mental_health"));
  const [f, setF] = useState({ encounter: encounters[0]?.id ?? "", type: (can("note:sign") ? "consultation" : "nursing") as NoteType, title: "", body: "" });
  const [error, setError] = useState<string | undefined>();
  const save = useAction(
    useCallback((key: string, encounter: string, body: CreateEntry) => api(`/v1/encounters/${encounter}/entries`, { body, key }), []),
  );
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!f.body.trim()) return setError("Write the note.");
    setError(undefined);
    const body: CreateEntry = {
      note_type: f.type,
      title: f.title.trim() || null,
      body: f.body,
      sensitivity: f.type === "mental_health_assessment" ? "mental_health" : "normal",
    };
    if (await save.run(f.encounter, body)) onDone();
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <form onSubmit={submit} className="panel" noValidate aria-label="Write a note">
      {save.error && <Notice kind="error">{save.error}</Notice>}
      <div className="row">
        <Select label="Visit" options={encounters.map((e) => [e.id, `${e.visit_number} (${words(e.service)})`])} value={f.encounter} onChange={set("encounter")} />
        <Select label="Type of note" options={types} value={f.type} onChange={set("type")} />
      </div>
      <Field label="Title" hint="Optional" value={f.title} onChange={set("title")} maxLength={200} />
      <TextArea label="Note" rows={8} value={f.body} onChange={set("body")} error={error} />
      {chart.patient.status === "temporary" && (
        <Notice kind="warning">This patient is not yet identified: the note can be drafted but not signed.</Notice>
      )}
      <div className="actions">
        <Button type="submit" busy={save.busy}>
          Save draft
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function Draft({ entry: loaded, mayEditSign, onChange }: { entry: EntryOut; mayEditSign: boolean; onChange: (m: string) => void }) {
  // Each save returns the note with its new version: keep it, so signing
  // straight after an edit never sends a stale version.
  const [entry, setEntry] = useState(loaded);
  // Once signed, the draft leaves the list at once rather than lingering,
  // signable but stale, until the list reloads.
  const [gone, setGone] = useState(false);
  const draft = entry.revisions.at(-1);
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(draft?.body ?? "");
  const save = useAction(
    useCallback((key: string, b: string) => api<EntryOut>(`/v1/entries/${entry.id}/draft`, { body: { body: b }, version: entry.version, key }), [entry]),
  );
  const sign = useAction(useCallback((key: string) => api(`/v1/entries/${entry.id}/sign`, { body: {}, version: entry.version, key }), [entry]));
  const label = entry.title ?? words(entry.note_type);
  if (gone) return null;
  return (
    <article className="note draft" aria-label={`Draft: ${label}`}>
      <h3>
        {label} <span className="tag tag-warn">Draft</span>
      </h3>
      {(save.error || sign.error) && <Notice kind="error">{save.error ?? sign.error}</Notice>}
      {editing ? (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const saved = await save.run(body);
            if (saved) {
              setEntry(saved);
              setEditing(false);
              onChange("Draft updated.");
            }
          }}
        >
          <TextArea label="Note" rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="actions">
            <Button type="submit" busy={save.busy}>
              Save draft
            </Button>
            <Button type="button" variant="secondary" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <>
          <p className="note-body">{draft?.body}</p>
          <div className="actions">
            <Button variant="secondary" onClick={() => setEditing(true)}>
              Edit draft<span className="visually-hidden">: {label}</span>
            </Button>
            {mayEditSign && (
              <Button
                busy={sign.busy}
                onClick={async () => {
                  if (await sign.run()) {
                    setGone(true);
                    onChange("Note signed. It can no longer be changed, only corrected.");
                  }
                }}
              >
                Sign note<span className="visually-hidden">: {label}</span>
              </Button>
            )}
          </div>
        </>
      )}
    </article>
  );
}

function Signed({ note, mine, who, onChange }: { note: EntrySummary; mine: boolean; who: string; onChange: (m: string) => void }) {
  const [correcting, setCorrecting] = useState(false);
  const [body, setBody] = useState(note.body);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const amend = useAction(
    useCallback(async (key: string, b: string, r: string) => {
      // The entry's version is needed for If-Match; the chart summary does not carry it.
      const entry = await api<EntryOut>(`/v1/entries/${note.id}`);
      return api(`/v1/entries/${note.id}/amendments`, { body: { body: b, reason: r }, version: entry.version, key });
    }, [note.id]),
  );
  const label = note.title ?? words(note.note_type);
  return (
    <article className="note" aria-label={label}>
      <h3>
        {label} <span className="muted">· {words(note.note_type)}</span>
      </h3>
      <p className="note-body">{note.body}</p>
      <p className="muted">
        Signed by {who}, {dateTime(note.signed_at)}
        {note.revision_number > 1 && ` · revision ${note.revision_number}`}
      </p>
      {mine && !correcting && (
        <Button variant="secondary" onClick={() => setCorrecting(true)}>
          Correct this note<span className="visually-hidden">: {label}</span>
        </Button>
      )}
      {correcting && (
        <form
          className="panel"
          noValidate
          onSubmit={async (e) => {
            e.preventDefault();
            if (reason.trim().length < 3) return setError("Say why the note is being corrected.");
            setError(undefined);
            if (await amend.run(body, reason.trim())) {
              setCorrecting(false);
              onChange("Correction saved as a draft. Sign it to replace the note; the original is kept.");
            }
          }}
        >
          {amend.error && <Notice kind="error">{amend.error}</Notice>}
          <TextArea label="Corrected note" rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
          <Field label="Reason for the correction" value={reason} onChange={(e) => setReason(e.target.value)} error={error} maxLength={500} />
          <div className="actions">
            <Button type="submit" busy={amend.busy}>
              Save correction
            </Button>
            <Button type="button" variant="secondary" onClick={() => setCorrecting(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </article>
  );
}

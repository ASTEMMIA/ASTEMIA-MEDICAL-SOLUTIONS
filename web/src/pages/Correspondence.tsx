import { useCallback, useState, type FormEvent } from "react";
import { api, messageFor } from "../api";
import type { AdministrativeSex, DocumentOut, FileDocument, PatientOut, ReceiveDocument } from "../api-types";
import { OpenDocument } from "../components/OpenDocument";
import { Button, Empty, Field, Loading, Notice, Page, Radios, Section, Select, Tag, TextArea } from "../components/ui";
import { useDirectory } from "../directory";
import { dateTime, nowLocal, localToIso, patientName, words } from "../format";
import { useAction, useLoad } from "../hooks";

const TYPES: [string, string][] = [
  ["letter", "Letter"],
  ["discharge_summary", "Discharge summary"],
  ["result", "Result"],
  ["referral", "Referral"],
];

/**
 * Correspondence (UG04): letters and documents arrive quarantined; a records
 * clerk checks who they are about, files them to the patient and names the
 * clinician who must review them. Files that fail their checks are never opened.
 */
export function Correspondence() {
  const [status, setStatus] = useState("quarantined");
  const list = useLoad<DocumentOut[]>("/v1/documents", { status, limit: 100 });
  const [news, setNews] = useState<string | null>(null);
  const [receiving, setReceiving] = useState(false);
  const changed = (m: string) => {
    setNews(m);
    list.reload();
  };
  return (
    <Page title="Correspondence" intro="Letters and documents waiting to be filed to the right patient.">
      {news && <Notice kind="success">{news}</Notice>}
      {receiving ? (
        <Receive onDone={(m) => { setReceiving(false); changed(m); }} onCancel={() => setReceiving(false)} />
      ) : (
        <p>
          <Button variant="secondary" onClick={() => setReceiving(true)}>
            Receive a document
          </Button>
        </p>
      )}
      <Radios
        legend="Show"
        name="document-status"
        value={status}
        onChange={setStatus}
        options={[
          ["quarantined", "To file"],
          ["rejected", "Failed checks"],
          ["filed", "Filed, awaiting review"],
          ["reviewed", "Reviewed"],
        ]}
      />
      {list.loading && <Loading />}
      {list.error !== null && <Notice kind="error">{messageFor(list.error)}</Notice>}
      {list.data && list.data.length === 0 && <Empty>Nothing here.</Empty>}
      {list.data?.map((d) => <Doc key={d.id} doc={d} onFiled={changed} />)}
    </Page>
  );
}

function Doc({ doc, onFiled }: { doc: DocumentOut; onFiled: (m: string) => void }) {
  const { person } = useDirectory();
  const label = doc.title ?? words(doc.document_type);
  return (
    <article className="pair" aria-label={label}>
      <h3>
        {label} {doc.scan === "clean" ? null : <Tag tone="bad">Failed checks</Tag>}
      </h3>
      <p className="muted">
        From {doc.sender}, received {dateTime(doc.received_at)} · {doc.media_type}
        {doc.scan_reason && ` · ${doc.scan_reason}`}
        {doc.reviewer_id && ` · reviewer ${person(doc.reviewer_id)}`}
      </p>
      {/* Intake only: once filed, the document is opened from the patient's chart by the care team. */}
      {doc.status === "quarantined" && <OpenDocument id={doc.id} label={label} />}
      {doc.status === "quarantined" && <FileForm doc={doc} onDone={onFiled} />}
    </article>
  );
}

function FileForm({ doc, onDone }: { doc: DocumentOut; onDone: (m: string) => void }) {
  const { practitioners } = useDirectory();
  const candidates = doc.candidates ?? [];
  const [patient, setPatient] = useState(candidates.length === 1 ? (candidates[0]?.id ?? "") : "");
  const [other, setOther] = useState<PatientOut | null>(null);
  const [nin, setNin] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [adjudication, setAdjudication] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const file = useAction(
    useCallback((key: string, b: FileDocument) => api(`/v1/documents/${doc.id}/file`, { body: b, version: doc.version, key }), [doc.id, doc.version]),
  );
  const find = useAction(useCallback((_key: string, n: string) => api<PatientOut[]>("/v1/patient-index", { query: { nin: n } }), []));
  const options: [string, string][] = candidates.map((c) => [
    c.id,
    `${c.family_name} ${c.given_initial}., born ${c.birth_year}, ${words(c.administrative_sex)} — ${c.reasons.map(words).join(", ")}`,
  ]);
  if (other) options.push([other.id, `${patientName(other)} (found by NIN)`]);
  const needsAdjudication = options.length > 1;
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!patient) errs.patient = "Choose who the document is about.";
    if (!reviewer) errs.reviewer = "Name the clinician who must review it.";
    if (needsAdjudication && adjudication.trim().length < 3) errs.adjudication = "More than one patient could match: say how you decided.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const ok = await file.run({ patient_id: patient, reviewer_id: reviewer, adjudication: needsAdjudication ? adjudication.trim() : null });
    if (ok) onDone("Filed to the patient's chart and sent to the reviewer.");
  }
  return (
    <form onSubmit={submit} className="panel" noValidate aria-label={`File ${doc.title ?? "the document"}`}>
      {file.error && <Notice kind="error">{file.error}</Notice>}
      {options.length > 0 ? (
        <Radios legend="Who is this about?" name={`patient-${doc.id}`} value={patient} onChange={setPatient} options={options} />
      ) : (
        <Notice>No patient matches the sender's details. Find the patient by NIN.</Notice>
      )}
      {errors.patient && <p className="error-text">{errors.patient}</p>}
      <div className="row">
        <Field label="Find another patient by NIN" inputMode="numeric" value={nin} onChange={(e) => setNin(e.target.value)} />
      </div>
      <Button
        type="button"
        variant="secondary"
        busy={find.busy}
        onClick={async () => {
          const found = await find.run(nin.trim());
          if (found?.[0]) {
            setOther(found[0]);
            setPatient(found[0].id);
          }
        }}
      >
        Find
      </Button>
      {find.error && <Notice kind="error">{find.error}</Notice>}
      <Select label="Reviewer" placeholder="Choose" options={practitioners.map((p) => [p.id, p.display_name])} value={reviewer} onChange={(e) => setReviewer(e.target.value)} error={errors.reviewer} />
      {needsAdjudication && (
        <TextArea label="How you decided" hint="Required when more than one patient could match." value={adjudication} onChange={(e) => setAdjudication(e.target.value)} error={errors.adjudication} maxLength={500} />
      )}
      <Button type="submit" busy={file.busy}>
        File to the patient
      </Button>
    </form>
  );
}

const MEDIA = ["application/pdf", "image/png", "image/jpeg", "image/tiff", "text/plain"];

async function base64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

function Receive({ onDone, onCancel }: { onDone: (m: string) => void; onCancel: () => void }) {
  const [f, setF] = useState({ sender: "", type: "letter", title: "", at: nowLocal(), family: "", given: "", born: "", sex: "" });
  const [upload, setUpload] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const receive = useAction(useCallback((key: string, b: ReceiveDocument) => api<DocumentOut>("/v1/documents", { body: b, key }), []));
  const hint = f.family && f.given && f.born && f.sex;
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.sender.trim()) errs.sender = "Enter who sent it.";
    if (!upload) errs.file = "Choose the file.";
    else if (!MEDIA.includes(upload.type)) errs.file = "Use a PDF, PNG, JPEG, TIFF or text file.";
    else if (upload.size > 10 * 1024 * 1024) errs.file = "The file is larger than 10 MB.";
    setErrors(errs);
    if (Object.keys(errs).length || !upload) return;
    const made = await receive.run({
      sender: f.sender.trim(),
      received_at: localToIso(f.at),
      document_type: f.type,
      title: f.title.trim() || null,
      media_type: upload.type,
      content_base64: await base64(upload),
      patient_hint: hint ? { family_name: f.family.trim(), given_names: f.given.trim(), birth_date: f.born, administrative_sex: f.sex as AdministrativeSex } : null,
    });
    if (made) onDone(made.status === "rejected" ? "Received, but the file failed its checks: it is kept and will not be opened." : "Received and quarantined until it is filed.");
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <Section title="Receive a document">
      <form onSubmit={submit} className="panel" noValidate aria-label="Receive a document">
        {receive.error && <Notice kind="error">{receive.error}</Notice>}
        <div className="row">
          <Field label="From" hint="The sender, for example a clinic or hospital" value={f.sender} onChange={set("sender")} error={errors.sender} />
          <Select label="Type" options={TYPES} value={f.type} onChange={set("type")} />
        </div>
        <div className="row">
          <Field label="Title" hint="Optional" value={f.title} onChange={set("title")} />
          <Field label="Received" type="datetime-local" value={f.at} onChange={set("at")} />
        </div>
        <Field label="File" type="file" accept={MEDIA.join(",")} onChange={(e) => setUpload(e.target.files?.[0] ?? null)} error={errors.file} />
        <fieldset>
          <legend>Who the sender says it is about</legend>
          <p className="hint">Optional. Used to suggest the patient.</p>
          <div className="row">
            <Field label="Family name" value={f.family} onChange={set("family")} />
            <Field label="Given names" value={f.given} onChange={set("given")} />
          </div>
          <div className="row">
            <Field label="Date of birth" type="date" value={f.born} onChange={set("born")} />
            <Select
              label="Sex"
              placeholder="Choose"
              options={[
                ["female", "Female"],
                ["male", "Male"],
                ["other", "Other"],
                ["unknown", "Not known"],
              ]}
              value={f.sex}
              onChange={set("sex")}
            />
          </div>
        </fieldset>
        <div className="actions">
          <Button type="submit" busy={receive.busy}>
            Receive
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Section>
  );
}

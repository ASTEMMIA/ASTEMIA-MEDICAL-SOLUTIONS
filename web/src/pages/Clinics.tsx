import { useCallback, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, messageFor } from "../api";
import type { AttendanceOutcome, ClinicAppointmentOut } from "../api-types";
import { Button, Empty, Field, Loading, Notice, Page, Radios, Select, Tag } from "../components/ui";
import { useDirectory } from "../directory";
import { dateTime, nin, patientName, today, words } from "../format";
import { useAction, useLoad } from "../hooks";
import { useSession } from "../session";

const STATUS: Record<string, ["good" | "warn" | "bad" | "neutral", string]> = {
  booked: ["neutral", "Booked"],
  attended: ["good", "Attended"],
  no_show: ["bad", "Did not attend"],
  failed_connection: ["warn", "Call failed"],
  cancelled: ["warn", "Cancelled"],
  rescheduled: ["neutral", "Rescheduled"],
};

/** A day's clinic list (UG01): record attendance, cancel or reschedule. */
export function Clinics() {
  const { practitioners } = useDirectory();
  const [day, setDay] = useState(today());
  const [clinician, setClinician] = useState("");
  const from = new Date(`${day}T00:00:00`);
  const to = new Date(from.getTime() + 86_400_000);
  const list = useLoad<ClinicAppointmentOut[]>("/v1/appointments", {
    from: from.toISOString(),
    to: to.toISOString(),
    practitioner_id: clinician || undefined,
  });
  const [news, setNews] = useState<string | null>(null);
  return (
    <Page title="Clinic list" intro="Appointments for the day, in time order.">
      <div className="row search" role="group" aria-label="Which clinic">
        <Field label="Day" type="date" value={day} onChange={(e) => setDay(e.target.value || today())} />
        <Select label="Clinician" placeholder="Everyone" options={practitioners.map((p) => [p.id, p.display_name])} value={clinician} onChange={(e) => setClinician(e.target.value)} />
      </div>
      {news && <Notice kind="success">{news}</Notice>}
      {list.loading && <Loading />}
      {list.error !== null && <Notice kind="error">{messageFor(list.error)}</Notice>}
      {list.data && list.data.length === 0 && <Empty>No appointments on this day.</Empty>}
      {list.data?.map((item) => (
        <Visit
          key={item.appointment.id}
          item={item}
          onChange={(m) => {
            setNews(m);
            list.reload();
          }}
        />
      ))}
    </Page>
  );
}

function Visit({ item, onChange }: { item: ClinicAppointmentOut; onChange: (m: string) => void }) {
  const { appointment: a, patient } = item;
  const { person, place } = useDirectory();
  const { can } = useSession();
  const [action, setAction] = useState<"" | "attend" | "cancel">("");
  const [st, label] = STATUS[a.status] ?? ["neutral", words(a.status)];
  const name = patientName(patient);
  const live = a.status === "booked";
  return (
    <article className="pair" aria-label={`${dateTime(a.starts_at)} ${name}`}>
      <h3>
        {dateTime(a.starts_at)} · {name} <Tag tone={st}>{label}</Tag>
      </h3>
      <p className="muted">
        {words(a.service)} with {person(a.practitioner_id)} at {place(a.facility_id)} · {words(a.modality)} · NIN <span className="mono">{nin(patient.identifiers)}</span>
        {a.reason && ` · ${a.reason}`}
        {a.cancel_reason && ` · cancelled: ${a.cancel_reason}`}
      </p>
      {live && !action && (
        <div className="actions">
          {can("appointment:attend") && (
            <Button variant="secondary" onClick={() => setAction("attend")}>
              Record attendance<span className="visually-hidden">: {name}</span>
            </Button>
          )}
          {can("schedule:book") && (
            <>
              <Link className="btn btn-secondary" to={`/book?patient=${patient.id}&reschedule=${a.id}&v=${a.version}&service=${encodeURIComponent(a.service)}`}>
                Reschedule<span className="visually-hidden">: {name}</span>
              </Link>
              <Button variant="secondary" onClick={() => setAction("cancel")}>
                Cancel<span className="visually-hidden"> the appointment: {name}</span>
              </Button>
            </>
          )}
        </div>
      )}
      {action === "attend" && <Attend item={item} onDone={(m) => { setAction(""); onChange(m); }} onCancel={() => setAction("")} />}
      {action === "cancel" && <CancelForm item={item} onDone={(m) => { setAction(""); onChange(m); }} onCancel={() => setAction("")} />}
      {a.encounter_id && (
        <p>
          <Link to={`/patients/${patient.id}`}>Open the patient</Link>
        </p>
      )}
    </article>
  );
}

function Attend({ item, onDone, onCancel }: { item: ClinicAppointmentOut; onDone: (m: string) => void; onCancel: () => void }) {
  const a = item.appointment;
  // Video and telephone consultations need the patient's identity confirmed.
  const remote = a.modality === "video" || a.modality === "phone";
  const [outcome, setOutcome] = useState<AttendanceOutcome | "">("");
  const [verified, setVerified] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const save = useAction(
    useCallback(
      (key: string, o: AttendanceOutcome, v: boolean) => api(`/v1/appointments/${a.id}/attendance`, { body: { outcome: o, identity_verified: v }, version: a.version, key }),
      [a.id, a.version],
    ),
  );
  const options: [string, string][] = [
    ["attended", "Attended"],
    ["no_show", "Did not attend"],
  ];
  if (remote) options.push(["failed_connection", "The call failed"]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!outcome) return setError("Choose what happened.");
    if (outcome === "attended" && remote && !verified) return setError("Confirm the patient's identity before a remote consultation.");
    setError(undefined);
    if (await save.run(outcome, verified))
      onDone(outcome === "attended" ? `${patientName(item.patient)} attended: the visit is open.` : `Recorded: ${words(outcome)}.`);
  }
  return (
    <form onSubmit={submit} className="panel" noValidate aria-label="Record attendance">
      {(error || save.error) && <Notice kind="error">{error ?? save.error}</Notice>}
      <Radios legend="What happened?" name={`attend-${a.id}`} value={outcome} onChange={(v) => setOutcome(v as AttendanceOutcome)} options={options} />
      {remote && (
        <div className="radio">
          <input id={`verified-${a.id}`} type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} />
          <label htmlFor={`verified-${a.id}`}>I confirmed the patient's identity on the call</label>
        </div>
      )}
      <div className="actions">
        <Button type="submit" busy={save.busy}>
          Save
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Back
        </Button>
      </div>
    </form>
  );
}

function CancelForm({ item, onDone, onCancel }: { item: ClinicAppointmentOut; onDone: (m: string) => void; onCancel: () => void }) {
  const a = item.appointment;
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const cancel = useAction(
    useCallback((key: string, r: string) => api(`/v1/appointments/${a.id}/cancel`, { body: { reason: r }, version: a.version, key }), [a.id, a.version]),
  );
  return (
    <form
      className="panel"
      noValidate
      aria-label="Cancel the appointment"
      onSubmit={async (e) => {
        e.preventDefault();
        if (reason.trim().length < 3) return setError("Give the reason for cancelling.");
        setError(undefined);
        if (await cancel.run(reason.trim())) onDone(`Appointment cancelled for ${patientName(item.patient)}. The slot is free again.`);
      }}
    >
      {cancel.error && <Notice kind="error">{cancel.error}</Notice>}
      <Field label="Reason for cancelling" value={reason} onChange={(e) => setReason(e.target.value)} error={error} maxLength={500} />
      <div className="actions">
        <Button type="submit" variant="danger" busy={cancel.busy}>
          Cancel the appointment
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Keep it
        </Button>
      </div>
    </form>
  );
}

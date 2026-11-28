import { useCallback, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api, messageFor } from "../api";
import type { AppointmentOut, PatientOut, SlotOut, SlotType } from "../api-types";
import { Button, Empty, Field, Loading, Notice, Page, Select, Tag } from "../components/ui";
import { useDirectory } from "../directory";
import { dateTime, patientName, today, words } from "../format";
import { useAction, useLoad } from "../hooks";

interface Hold {
  id: string;
  slot_id: string;
  expires_at: string;
}

/**
 * Book or reschedule (UG01, HS04): find a free slot, hold it for five
 * minutes, then confirm. A hold stops two people booking the same slot.
 */
export function Book() {
  const [params] = useSearchParams();
  const patientId = params.get("patient") ?? "";
  const referral = params.get("referral");
  const reschedule = params.get("reschedule");
  const version = Number(params.get("v") ?? "0");
  const patient = useLoad<PatientOut>(patientId ? `/v1/patients/${patientId}` : null);
  const { practitioners } = useDirectory();
  const [q, setQ] = useState({ service: params.get("service") ?? "", practitioner: "", day: today(), type: "" });
  const [search, setSearch] = useState<typeof q | null>(params.get("service") ? q : null);
  const from = search ? new Date(`${search.day}T00:00:00`) : null;
  const slots = useLoad<SlotOut[]>(search ? "/v1/slots" : null, {
    service: search?.service || undefined,
    practitioner_id: search?.practitioner || undefined,
    slot_type: (search?.type as SlotType) || undefined,
    from: from?.toISOString(),
    to: from ? new Date(from.getTime() + 7 * 86_400_000).toISOString() : undefined,
    available_only: true,
    limit: 100,
  });
  const [held, setHeld] = useState<{ hold: Hold; slot: SlotOut } | null>(null);
  const [done, setDone] = useState<AppointmentOut | null>(null);
  const name = patient.data ? patientName(patient.data) : "the patient";
  const title = reschedule ? "Reschedule an appointment" : "Book an appointment";

  if (!patientId)
    return (
      <Page title={title}>
        <Notice>
          Open the patient first: <Link to="/patients">find a patient</Link>, then choose Book an appointment.
        </Notice>
      </Page>
    );
  if (done)
    return (
      <Page title={reschedule ? "Appointment moved" : "Appointment booked"}>
        <Notice kind="success">
          {name}: {words(done.service)} on {dateTime(done.starts_at)}.{reschedule && " The original appointment is kept as rescheduled."}
        </Notice>
        <p>
          <Link to="/clinics">Go to the clinic list</Link>
        </p>
      </Page>
    );
  return (
    <Page title={title} intro={`For ${name}. Free slots for the next 7 days.`}>
      {referral && <Notice>Booking for an accepted referral: it will be marked scheduled.</Notice>}
      <form
        className="search"
        role="search"
        aria-label="Free slots"
        onSubmit={(e) => {
          e.preventDefault();
          setHeld(null);
          setSearch({ ...q });
        }}
      >
        <div className="row">
          <Field label="Service" hint="For example cardiology" value={q.service} onChange={(e) => setQ({ ...q, service: e.target.value })} />
          <Select label="Clinician" placeholder="Anyone" options={practitioners.map((p) => [p.id, p.display_name])} value={q.practitioner} onChange={(e) => setQ({ ...q, practitioner: e.target.value })} />
        </div>
        <div className="row">
          <Field label="From" type="date" value={q.day} onChange={(e) => setQ({ ...q, day: e.target.value || today() })} />
          <Select
            label="Type of slot"
            placeholder="Any"
            options={[
              ["new", "New"],
              ["follow_up", "Follow-up"],
              ["urgent", "Urgent"],
            ]}
            value={q.type}
            onChange={(e) => setQ({ ...q, type: e.target.value })}
          />
        </div>
        <Button type="submit">Find free slots</Button>
      </form>
      {slots.loading && <Loading what="Finding free slots" />}
      {slots.error !== null && <Notice kind="error">{messageFor(slots.error)}</Notice>}
      {held ? (
        <Confirm
          held={held}
          patientId={patientId}
          referral={referral}
          reschedule={reschedule ? { id: reschedule, version } : null}
          onBooked={setDone}
          onLost={() => {
            setHeld(null);
            slots.reload();
          }}
        />
      ) : (
        slots.data &&
        (slots.data.length === 0 ? (
          <Empty>No free slots. Try another day, clinician or service.</Empty>
        ) : (
          <SlotTable slots={slots.data} onHeld={(hold, slot) => setHeld({ hold, slot })} onLost={slots.reload} />
        ))
      )}
    </Page>
  );
}

function SlotTable({ slots, onHeld, onLost }: { slots: SlotOut[]; onHeld: (h: Hold, s: SlotOut) => void; onLost: () => void }) {
  const { person, place } = useDirectory();
  const hold = useAction(useCallback((key: string, slot: SlotOut) => api<Hold>(`/v1/slots/${slot.id}/hold`, { body: {}, key }), []));
  return (
    <>
      {hold.error && <Notice kind="error">{hold.error} The list has been refreshed.</Notice>}
      <table className="table">
        <caption>{slots.length === 1 ? "1 free slot" : `${slots.length} free slots`}</caption>
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Service</th>
            <th scope="col">Clinician</th>
            <th scope="col">Where</th>
            <th scope="col">Type</th>
            <th scope="col">
              <span className="visually-hidden">Choose</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {slots.map((s) => (
            <tr key={s.id}>
              <th scope="row">{dateTime(s.starts_at)}</th>
              <td>{words(s.service)}</td>
              <td>{person(s.practitioner_id)}</td>
              <td>{place(s.facility_id)}</td>
              <td>
                {words(s.slot_type)} · {words(s.modality)}
              </td>
              <td>
                <Button
                  variant="secondary"
                  busy={hold.busy}
                  onClick={async () => {
                    const h = await hold.run(s);
                    if (h) onHeld(h, s);
                    else onLost();
                  }}
                >
                  Choose<span className="visually-hidden"> {dateTime(s.starts_at)} with {person(s.practitioner_id)}</span>
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Confirm({
  held,
  patientId,
  referral,
  reschedule,
  onBooked,
  onLost,
}: {
  held: { hold: Hold; slot: SlotOut };
  patientId: string;
  referral: string | null;
  reschedule: { id: string; version: number } | null;
  onBooked: (a: AppointmentOut) => void;
  onLost: () => void;
}) {
  const { person } = useDirectory();
  const [reason, setReason] = useState("");
  const book = useAction(
    useCallback(
      (key: string, why: string) =>
        reschedule
          ? api<AppointmentOut>(`/v1/appointments/${reschedule.id}/reschedule`, { body: { hold_id: held.hold.id }, version: reschedule.version, key })
          : api<AppointmentOut>("/v1/appointments", { body: { hold_id: held.hold.id, patient_id: patientId, referral_id: referral, reason: why.trim() || null }, key }),
      [held.hold.id, patientId, referral, reschedule],
    ),
  );
  async function submit(e: FormEvent) {
    e.preventDefault();
    const made = await book.run(reason);
    if (made) onBooked(made);
  }
  const s = held.slot;
  return (
    <form onSubmit={submit} className="panel" noValidate aria-label="Confirm the booking">
      <Notice kind="warning">
        <strong>Held for you until {dateTime(held.hold.expires_at)}.</strong> Confirm before then, or the slot is released.
      </Notice>
      <p>
        {words(s.service)} with {person(s.practitioner_id)}, {dateTime(s.starts_at)} <Tag>{words(s.modality)}</Tag>
      </p>
      {book.error && <Notice kind="error">{book.error}</Notice>}
      {!reschedule && <Field label="Reason for the appointment" hint="Optional" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />}
      <div className="actions">
        <Button type="submit" busy={book.busy}>
          {reschedule ? "Move the appointment" : "Confirm the booking"}
        </Button>
        <Button type="button" variant="secondary" onClick={onLost}>
          Choose another slot
        </Button>
      </div>
    </form>
  );
}

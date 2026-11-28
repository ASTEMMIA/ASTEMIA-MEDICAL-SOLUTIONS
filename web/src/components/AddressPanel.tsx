import { useCallback, useState, type FormEvent } from "react";
import { api } from "../api";
import type { AddressHistoryOut, ChangeAddress, PatientOut } from "../api-types";
import { useDirectory } from "../directory";
import { dateTime } from "../format";
import { useAction, useLoad } from "../hooks";
import { addressLine } from "../places";
import { useSession } from "../session";
import { AddressFields, EMPTY_ADDRESS, addressErrors, toAddressIn, type AddressForm } from "./AddressFields";
import { Button, Notice, Radios, Section } from "./ui";

/**
 * The patient's home address: current, changed with a reason, and every
 * previous address kept (CEDA revision 1.8; ICRS 3.2.11).
 */
export function AddressPanel({ patient, onChanged, masked = false }: { patient: PatientOut; onChanged: () => void; masked?: boolean }) {
  const { can } = useSession();
  const { person } = useDirectory();
  // Withheld when the role may not read addresses, or under emergency access.
  const mayRead = can("address:read") && !masked;
  const history = useLoad<AddressHistoryOut[]>(mayRead ? `/v1/patients/${patient.id}/addresses` : null);
  const [editing, setEditing] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const previous = (history.data ?? []).filter((h) => !h.current);
  return (
    <Section
      title="Address"
      actions={
        can("address:update") &&
        !masked &&
        !editing &&
        patient.status !== "merged" && (
          <Button variant="secondary" onClick={() => { setEditing(true); setDone(null); }}>
            {patient.address ? "Change address" : "Add address"}
          </Button>
        )
      }
    >
      {done && <Notice kind="success">{done}</Notice>}
      <p>{patient.address ? addressLine(patient.address) : mayRead ? "Not recorded." : "Not shown to your role."}</p>
      {editing && (
        <ChangeForm
          patient={patient}
          onCancel={() => setEditing(false)}
          onDone={(message) => {
            setEditing(false);
            setDone(message);
            history.reload();
            onChanged();
          }}
        />
      )}
      {previous.length > 0 && (
        <details>
          <summary>Previous addresses ({previous.length})</summary>
          <ul className="list">
            {previous.map((h) => (
              <li key={`${h.effective_from}-${h.postcode}`}>
                {addressLine(h)} <span className="muted">· {dateTime(h.effective_from)} to {dateTime(h.effective_to)}, recorded by {person(h.recorded_by_id)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Section>
  );
}

const REASONS: Record<string, string> = {
  moved: "The patient has moved",
  correction: "The address on file is wrong",
  identified: "The patient has been identified",
};

function ChangeForm({ patient, onDone, onCancel }: { patient: PatientOut; onDone: (m: string) => void; onCancel: () => void }) {
  const [address, setAddress] = useState<AddressForm>(EMPTY_ADDRESS);
  const [reason, setReason] = useState(patient.status === "temporary" ? "identified" : "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    useCallback(
      (key: string, body: ChangeAddress) => api<PatientOut>(`/v1/patients/${patient.id}/address`, { body, version: patient.version, key }),
      [patient.id, patient.version],
    ),
  );
  const reasons = Object.entries(REASONS).filter(([r]) => (r === "identified") === (patient.status === "temporary") || r === "correction");
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs = addressErrors(address);
    if (!reason) errs.reason = "Choose why the address is changing.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    if (await save.run({ address: toAddressIn(address), reason: reason as ChangeAddress["reason"] }))
      onDone(patient.address ? "Address changed. The previous address is kept in the history." : "Address recorded.");
  }
  const list = Object.values(errors);
  return (
    <form onSubmit={submit} className="panel" noValidate aria-label="Change address">
      {list.length > 0 && (
        <Notice kind="error">
          <p>There is a problem:</p>
          <ul>
            {list.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </Notice>
      )}
      {save.error && <Notice kind="error">{save.error}</Notice>}
      <Radios legend="Reason" name="address-reason" value={reason} onChange={setReason} options={reasons} />
      <AddressFields legend="New home address" value={address} onChange={setAddress} errors={errors} />
      <div className="actions">
        <Button type="submit" busy={save.busy}>
          Save address
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

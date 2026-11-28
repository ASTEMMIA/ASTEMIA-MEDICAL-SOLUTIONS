import { useCallback, useState, type FormEvent } from "react";
import { api } from "../api";
import type { CreateSlots, Modality, SlotOut, SlotType } from "../api-types";
import { Button, Field, Notice, Page, Select } from "../components/ui";
import { useDirectory } from "../directory";
import { dateTime, localToIso, words } from "../format";
import { useAction } from "../hooks";

/** Clinic sessions (UG01): a run of consecutive slots for one clinician and service. */
export function Sessions() {
  const { practitioners, facilities, person } = useDirectory();
  const [f, setF] = useState({ facility: "", clinician: "", service: "", start: "", minutes: "20", count: "6", type: "new", modality: "in_person" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [made, setMade] = useState<SlotOut[] | null>(null);
  const create = useAction(useCallback((key: string, b: CreateSlots) => api<{ slots: SlotOut[] }>("/v1/slots", { body: b, key }), []));
  const facility = f.facility || facilities[0]?.id || "";
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.clinician) errs.clinician = "Choose the clinician.";
    if (!f.service.trim()) errs.service = "Enter the service.";
    if (!f.start) errs.start = "Enter when the session starts.";
    else if (new Date(f.start) <= new Date()) errs.start = "The session must start in the future.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const out = await create.run({
      facility_id: facility,
      practitioner_id: f.clinician,
      service: f.service.trim(),
      starts_at: localToIso(f.start),
      minutes: Number(f.minutes),
      count: Number(f.count),
      slot_type: f.type as SlotType,
      modality: f.modality as Modality,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
    if (out) setMade(out.slots);
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
    setMade(null);
  };
  return (
    <Page title="Clinic sessions" intro="Create a run of appointment slots for one clinician and service.">
      {made && (
        <Notice kind="success">
          {made.length} slots created for {person(made[0]?.practitioner_id)}, {words(made[0]?.service ?? "")}, from {dateTime(made[0]?.starts_at)} to{" "}
          {dateTime(made.at(-1)?.ends_at)}.
        </Notice>
      )}
      {create.error && <Notice kind="error">{create.error}</Notice>}
      <form onSubmit={submit} noValidate>
        <div className="row">
          <Select label="Facility" options={facilities.map((x) => [x.id, `${x.site_name}, ${x.organisation_name}`])} value={facility} onChange={set("facility")} />
          <Select label="Clinician" placeholder="Choose" options={practitioners.map((p) => [p.id, p.display_name])} value={f.clinician} onChange={set("clinician")} error={errors.clinician} />
        </div>
        <div className="row">
          <Field label="Service" hint="For example cardiology" value={f.service} onChange={set("service")} error={errors.service} />
          <Field label="Starts at" type="datetime-local" value={f.start} onChange={set("start")} error={errors.start} />
        </div>
        <div className="row">
          <Select label="Minutes per slot" options={["10", "15", "20", "30", "45", "60"].map((m) => [m, `${m} minutes`])} value={f.minutes} onChange={set("minutes")} />
          <Select label="Number of slots" options={Array.from({ length: 20 }, (_, i) => [String(i + 1), String(i + 1)] as [string, string])} value={f.count} onChange={set("count")} />
        </div>
        <div className="row">
          <Select
            label="Type of slot"
            options={[
              ["new", "New"],
              ["follow_up", "Follow-up"],
              ["urgent", "Urgent"],
            ]}
            value={f.type}
            onChange={set("type")}
          />
          <Select
            label="How"
            options={[
              ["in_person", "In person"],
              ["video", "Video"],
              ["phone", "Telephone"],
              ["home", "Home visit"],
            ]}
            value={f.modality}
            onChange={set("modality")}
          />
        </div>
        <Button type="submit" busy={create.busy}>
          Create slots
        </Button>
      </form>
    </Page>
  );
}

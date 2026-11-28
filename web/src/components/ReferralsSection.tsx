import { useCallback, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api";
import type { ChartOut, ReferralOut, ReferralPriority, SubmitReferral } from "../api-types";
import { useDirectory } from "../directory";
import { count, words } from "../format";
import { useAction } from "../hooks";
import { useSession } from "../session";
import { Button, Field, Notice, Radios, Section, Select, TextArea } from "./ui";

/**
 * Refer to another facility (HS05, WF06; CEDA revision 1.5). The patient's
 * historical records always go with the referral: the referrer cannot leave
 * them out, and a patient with no care records cannot be referred.
 */
export function ReferralsSection({ chart }: { chart: ChartOut }) {
  const { can } = useSession();
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState<ReferralOut | null>(null);
  const mayRefer = can("referral:create") && chart.access_basis !== "emergency_grant";
  const mayBook = can("schedule:book");
  if (!mayRefer && !mayBook) return null;
  return (
    <Section
      title="Referrals and appointments"
      actions={
        <div className="actions">
          {mayBook && (
            <Link className="btn btn-secondary" to={`/book?patient=${chart.patient.id}`}>
              Book an appointment
            </Link>
          )}
          {mayRefer && !open && (
            <Button variant="secondary" onClick={() => { setOpen(true); setSent(null); }}>
              Refer
            </Button>
          )}
        </div>
      }
    >
      {sent && (
        <Notice kind="success">
          Referral sent to {words(sent.receiving_service)}
          {sent.receiving_level && ` (${words(sent.receiving_level)})`}, with {count(sent.records_count ?? 0, "record")} from the patient's history.
        </Notice>
      )}
      {open && (
        <ReferForm
          chart={chart}
          onCancel={() => setOpen(false)}
          onSent={(r) => {
            setOpen(false);
            setSent(r);
          }}
        />
      )}
    </Section>
  );
}

function ReferForm({ chart, onSent, onCancel }: { chart: ChartOut; onSent: (r: ReferralOut) => void; onCancel: () => void }) {
  const { facilities } = useDirectory();
  const latest = chart.encounters[0];
  const from = latest?.facility_id ?? facilities[0]?.id ?? "";
  const others = facilities.filter((f) => f.id !== from);
  const [f, setF] = useState({ to: others[0]?.id ?? "", service: "", priority: "routine" as ReferralPriority, reason: "", encounter: latest?.id ?? "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const send = useAction(useCallback((key: string, b: SubmitReferral) => api<ReferralOut>("/v1/referrals", { body: b, key }), []));
  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.to) errs.to = "Choose where the patient is referred.";
    if (!f.service.trim()) errs.service = "Enter the receiving service, for example cardiology.";
    if (f.reason.trim().length < 3) errs.reason = "Give the reason for the referral.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const made = await send.run({
      patient_id: chart.patient.id,
      referring_facility_id: from,
      receiving_facility_id: f.to,
      encounter_id: f.encounter || null,
      receiving_service: f.service.trim(),
      requesting_service: latest?.service ?? null,
      priority: f.priority,
      reason: f.reason.trim(),
    });
    if (made) onSent(made);
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <form onSubmit={submit} className="panel" noValidate aria-label="Refer">
      <Notice>The patient's historical records (visits, orders and results) go with every referral.</Notice>
      {send.error && <Notice kind="error">{send.error}</Notice>}
      <div className="row">
        <Select label="Refer to" placeholder="Choose" options={others.map((x) => [x.id, `${x.organisation_name}, ${x.site_name}`])} value={f.to} onChange={set("to")} error={errors.to} />
        <Field label="Receiving service" autoComplete="off" value={f.service} onChange={set("service")} error={errors.service} />
      </div>
      <Select
        label="From the visit"
        options={chart.encounters.map((e) => [e.id, `${e.visit_number} (${words(e.service)})`])}
        value={f.encounter}
        onChange={set("encounter")}
      />
      <Radios
        legend="Priority"
        name="referral-priority"
        value={f.priority}
        onChange={(v) => setF((prev) => ({ ...prev, priority: v as ReferralPriority }))}
        options={[
          ["routine", "Routine"],
          ["urgent", "Urgent"],
        ]}
      />
      <TextArea label="Reason for referral" value={f.reason} onChange={set("reason")} error={errors.reason} maxLength={1000} />
      <div className="actions">
        <Button type="submit" busy={send.busy}>
          Send referral
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

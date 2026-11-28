import { useCallback, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, messageFor } from "../api";
import type { ReferralOut, ReferralRecordsOut } from "../api-types";
import { Button, Empty, Field, Loading, Notice, Page, Radios, Tag, TextArea } from "../components/ui";
import { useDirectory } from "../directory";
import { count, date, dateTime, num, patientName, words } from "../format";
import { useAction, useLoad } from "../hooks";

/**
 * Referral triage (HS05, WF06): the receiving team reads the patient's
 * history that came with the referral, then accepts it to book, or rejects
 * it with a reason. Urgent referrals come first.
 */
export function Referrals() {
  const [status, setStatus] = useState("submitted");
  const list = useLoad<ReferralOut[]>("/v1/referrals", { status, limit: 100 });
  const [news, setNews] = useState<string | null>(null);
  return (
    <Page title="Referrals" intro="Referrals to your services, urgent first. The patient's history comes with each one.">
      <Radios
        legend="Show"
        name="referral-status"
        value={status}
        onChange={setStatus}
        options={[
          ["submitted", "To triage"],
          ["accepted", "Accepted, to book"],
          ["scheduled", "Booked"],
          ["rejected", "Rejected"],
        ]}
      />
      {news && <Notice kind="success">{news}</Notice>}
      {list.loading && <Loading />}
      {list.error !== null && <Notice kind="error">{messageFor(list.error)}</Notice>}
      {list.data && list.data.length === 0 && <Empty>No referrals here.</Empty>}
      {list.data?.map((r) => (
        <Referral
          key={r.id}
          referral={r}
          onDecided={(m) => {
            setNews(m);
            list.reload();
          }}
        />
      ))}
    </Page>
  );
}

function Referral({ referral: r, onDecided }: { referral: ReferralOut; onDecided: (m: string) => void }) {
  const { person, place } = useDirectory();
  const [open, setOpen] = useState(false);
  const records = useLoad<ReferralRecordsOut>(open ? `/v1/referrals/${r.id}/records` : null);
  const who = records.data ? patientName(records.data.patient) : "the patient";
  return (
    <article className="pair" aria-label={`Referral to ${words(r.receiving_service)}, ${dateTime(r.recorded_at)}`}>
      <h3>
        {words(r.receiving_service)} {r.priority === "urgent" ? <Tag tone="bad">Urgent</Tag> : <Tag>Routine</Tag>}{" "}
        <span className="muted">· {dateTime(r.recorded_at)}</span>
      </h3>
      <p>{r.reason}</p>
      <p className="muted">
        From {person(r.referrer_id)} at {place(r.referring_facility_id)}
        {r.referring_level && ` (${words(r.referring_level)})`} to {place(r.receiving_facility_id)}
        {r.receiving_level && ` (${words(r.receiving_level)})`} · {count(r.records_count ?? 0, "record")} attached
        {r.decision_reason && ` · ${words(r.status)}: ${r.decision_reason}`}
      </p>
      <Button variant="secondary" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide the records" : "Read the records"}
        <span className="visually-hidden"> sent with this referral</span>
      </Button>
      {open && records.loading && <Loading what="Opening the records" />}
      {open && records.error !== null && <Notice kind="error">{messageFor(records.error)}</Notice>}
      {open && records.data && <Package pkg={records.data} />}
      {r.status === "submitted" && <Decide referral={r} who={who} onDone={onDecided} />}
      {r.status === "accepted" && (
        <p>
          <Link className="btn btn-primary" to={`/book?patient=${r.patient_id}&referral=${r.id}&service=${encodeURIComponent(r.receiving_service)}`}>
            Book an appointment<span className="visually-hidden"> for this referral</span>
          </Link>
        </p>
      )}
    </article>
  );
}

function Package({ pkg }: { pkg: ReferralRecordsOut }) {
  const { person, place } = useDirectory();
  const orders = new Map(pkg.orders.map((o) => [o.id, o.display]));
  return (
    <div className="panel">
      <h4>
        {patientName(pkg.patient)}, born {date(pkg.patient.birth_date)}
      </h4>
      {pkg.withheld_records > 0 && <Notice>{count(pkg.withheld_records, "sensitive record")} withheld from your role.</Notice>}
      <h5>Visits</h5>
      {pkg.encounters.length === 0 ? (
        <Empty>None.</Empty>
      ) : (
        <ul className="list">
          {pkg.encounters.map((e) => (
            <li key={e.id}>
              {dateTime(e.period_start)}: {words(e.service)} at {place(e.facility_id)}, under {person(e.responsible_practitioner_id)} ({words(e.state)})
            </li>
          ))}
        </ul>
      )}
      <h5>Results</h5>
      {pkg.reports.length === 0 ? (
        <Empty>None.</Empty>
      ) : (
        <ul className="list">
          {pkg.reports.map((rep) => (
            <li key={rep.id}>
              {orders.get(rep.service_request_id) ?? "Result"}, {dateTime(rep.released_at)}:{" "}
              {(rep.observations ?? []).map((o) => `${o.display} ${num(o.quantity) || o.text || ""} ${o.unit ?? ""}${o.flag ? ` (${o.flag === "H" ? "high" : o.flag === "L" ? "low" : o.flag})` : ""}`).join("; ")}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Decide({ referral: r, who, onDone }: { referral: ReferralOut; who: string; onDone: (m: string) => void }) {
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const decide = useAction(
    useCallback(
      (key: string, d: string, why: string) => api(`/v1/referrals/${r.id}/decision`, { body: { decision: d, reason: why || null }, version: r.version, key }),
      [r.id, r.version],
    ),
  );
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!decision) return setError("Choose whether to accept the referral.");
    if (decision === "rejected" && reason.trim().length < 3) return setError("Give the reason for rejecting: the referrer reads it.");
    setError(undefined);
    if (await decide.run(decision, reason.trim()))
      onDone(decision === "accepted" ? `Referral accepted for ${who}: it is ready to book.` : `Referral rejected; the referrer has the reason.`);
  }
  return (
    <form onSubmit={submit} noValidate aria-label="Triage decision">
      {(error || decide.error) && <Notice kind="error">{error ?? decide.error}</Notice>}
      <Radios
        legend="Decision"
        name={`decision-${r.id}`}
        value={decision}
        onChange={setDecision}
        options={[
          ["accepted", "Accept"],
          ["rejected", "Reject"],
        ]}
      />
      {decision === "rejected" ? (
        <TextArea label="Reason for rejecting" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
      ) : (
        <Field label="Note" hint="Optional" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
      )}
      <Button type="submit" busy={decide.busy}>
        Record decision
      </Button>
    </form>
  );
}

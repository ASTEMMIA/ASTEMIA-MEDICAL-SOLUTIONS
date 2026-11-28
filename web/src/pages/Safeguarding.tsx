import { useCallback, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { api, messageFor } from "../api";
import type { AccessReportOut, ConcernOut, InterventionOut, LegalStatusOut, PatientOut, ReviewOutcome } from "../api-types";
import { FLAGS } from "../components/SafeguardingSection";
import { Button, Empty, Field, Loading, Notice, Page, Radios, Section, Select, Tag, TextArea } from "../components/ui";
import { useDirectory } from "../directory";
import { dateTime, localToIso, patientName, words } from "../format";
import { useAction, useLoad } from "../hooks";

function Who({ id }: { id: string }) {
  const p = useLoad<PatientOut>(`/v1/patients/${id}`);
  return <Link to={`/safeguarding/patients/${id}`}>{p.data ? patientName(p.data) : "the patient"}</Link>;
}

/**
 * Safeguarding leads (HS13; CEDA revision 1.6): review every restrictive
 * intervention they took no part in, answer concerns they are not the
 * subject of, and watch compulsory powers that are about to lapse.
 */
export function Safeguarding() {
  const [tab, setTab] = useState("interventions");
  return (
    <Page title="Safeguarding" intro="Independent review of restrictive practice, concerns and legal powers.">
      <Radios
        legend="Show"
        name="safeguarding-tab"
        value={tab}
        onChange={setTab}
        options={[
          ["interventions", "Interventions to review"],
          ["concerns", "Open concerns"],
          ["expiring", "Powers expiring or lapsed"],
        ]}
      />
      {tab === "interventions" && <ReviewQueue />}
      {tab === "concerns" && <Concerns />}
      {tab === "expiring" && <Expiring />}
    </Page>
  );
}

function ReviewQueue() {
  const queue = useLoad<InterventionOut[]>("/v1/restrictive-interventions", { reviewed: false, limit: 100 });
  const [news, setNews] = useState<string | null>(null);
  return (
    <Section title="Interventions to review">
      {news && <Notice kind="success">{news}</Notice>}
      {queue.loading && <Loading />}
      {queue.error !== null && <Notice kind="error">{messageFor(queue.error)}</Notice>}
      {queue.data && queue.data.length === 0 && <Empty>Every intervention has been reviewed.</Empty>}
      {queue.data?.map((i) => (
        <Intervention key={`${i.id}-${i.version}`} item={i} onDone={(m) => { setNews(m); queue.reload(); }} />
      ))}
    </Section>
  );
}

function Intervention({ item: i, onDone }: { item: InterventionOut; onDone: (m: string) => void }) {
  const { person } = useDirectory();
  const [outcome, setOutcome] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | undefined>();
  const review = useAction(
    useCallback(
      (key: string, o: ReviewOutcome, n: string) => api(`/v1/restrictive-interventions/${i.id}/review`, { body: { outcome: o, note: n }, version: i.version, key }),
      [i.id, i.version],
    ),
  );
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!outcome) return setError("Choose the outcome of your review.");
    if (note.trim().length < 3) return setError("Add your review note.");
    setError(undefined);
    if (await review.run(outcome as ReviewOutcome, note.trim())) onDone("Review recorded.");
  }
  const label = `${words(i.intervention_type)}, ${dateTime(i.started_at)}`;
  return (
    <article className="pair" aria-label={label}>
      <h3>
        {label} {i.review_overdue && <Tag tone="bad">Review overdue</Tag>} {i.flags.map((f) => <Tag key={f} tone="warn">{FLAGS[f] ?? words(f)}</Tag>)}
      </h3>
      <p>
        <Who id={i.patient_id} />: {i.reason}
      </p>
      <p className="muted">
        Authorised by {person(i.authorised_by_id)} · staff {i.staff_ids.map(person).join(", ")} · {i.ended_at ? `${i.duration_minutes} minutes` : "ongoing"}
        {i.injury && ` · injury: ${i.injury_detail ?? "yes"}`}
        {i.debrief_offered === false && " · no debrief offered"} · review due {dateTime(i.review_due_at)}
      </p>
      <form noValidate onSubmit={submit} aria-label={`Review ${label}`}>
        {(error || review.error) && <Notice kind="error">{error ?? review.error}</Notice>}
        <Radios
          legend="Outcome"
          name={`outcome-${i.id}`}
          value={outcome}
          onChange={setOutcome}
          options={[
            ["appropriate", "Appropriate"],
            ["concerns", "Concerns"],
            ["escalated", "Escalated"],
          ]}
        />
        <TextArea label="Review note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        <Button type="submit" busy={review.busy}>Record the review</Button>
      </form>
    </article>
  );
}

function Concerns() {
  const list = useLoad<ConcernOut[]>("/v1/safeguarding-concerns", { status: "open", limit: 100 });
  const [news, setNews] = useState<string | null>(null);
  return (
    <Section title="Open concerns">
      {news && <Notice kind="success">{news}</Notice>}
      {list.loading && <Loading />}
      {list.error !== null && <Notice kind="error">{messageFor(list.error)}</Notice>}
      {list.data && list.data.length === 0 && <Empty>No open concerns.</Empty>}
      {list.data?.map((c) => (
        <Concern key={`${c.id}-${c.version}`} concern={c} onDone={(m) => { setNews(m); list.reload(); }} />
      ))}
    </Section>
  );
}

function Concern({ concern: c, onDone }: { concern: ConcernOut; onDone: (m: string) => void }) {
  const { person } = useDirectory();
  const [outcome, setOutcome] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | undefined>();
  const close = useAction(
    useCallback((key: string, o: string, n: string) => api(`/v1/safeguarding-concerns/${c.id}/outcome`, { body: { outcome: o, note: n }, version: c.version, key }), [c.id, c.version]),
  );
  const label = `${words(c.category)} concern, ${dateTime(c.recorded_at)}`;
  return (
    <article className="pair" aria-label={label}>
      <h3>
        {label} {c.overdue && <Tag tone="bad">Answer overdue</Tag>}
      </h3>
      <p>
        <Who id={c.patient_id} />: {c.description}
      </p>
      <p className="muted">
        Raised by {words(c.raised_by)}
        {c.raised_by_name && ` (${c.raised_by_name})`}
        {c.about_practitioner_id && ` · about ${person(c.about_practitioner_id)}`} · answer by {dateTime(c.respond_by)}
      </p>
      <form
        noValidate
        aria-label={`Answer the ${label}`}
        onSubmit={async (e) => {
          e.preventDefault();
          if (!outcome) return setError("Choose whether the concern is upheld.");
          if (note.trim().length < 3) return setError("Write the answer to the concern.");
          setError(undefined);
          if (await close.run(outcome, note.trim())) onDone("Concern answered and closed.");
        }}
      >
        {(error || close.error) && <Notice kind="error">{error ?? close.error}</Notice>}
        <Radios
          legend="Outcome"
          name={`concern-${c.id}`}
          value={outcome}
          onChange={setOutcome}
          options={[
            ["upheld", "Upheld"],
            ["not_upheld", "Not upheld"],
          ]}
        />
        <TextArea label="Answer" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
        <Button type="submit" busy={close.busy}>Close the concern</Button>
      </form>
    </article>
  );
}

function Expiring() {
  const list = useLoad<LegalStatusOut[]>("/v1/legal-status/expiring");
  const { person } = useDirectory();
  return (
    <Section title="Powers expiring within 72 hours or lapsed">
      {list.loading && <Loading />}
      {list.error !== null && <Notice kind="error">{messageFor(list.error)}</Notice>}
      {list.data && list.data.length === 0 && <Empty>None.</Empty>}
      <ul className="list">
        {list.data?.map((l) => (
          <li key={l.id}>
            <Who id={l.patient_id} />: {words(l.status)}
            {l.legal_basis && ` (${l.legal_basis})`} until {dateTime(l.valid_until)}, authorised by {person(l.authorised_by_id)}{" "}
            {l.lapsed ? <Tag tone="bad">Lapsed</Tag> : <Tag tone="warn">Expiring</Tag>}
          </li>
        ))}
      </ul>
    </Section>
  );
}

/** One patient, for a lead: who touched the record, and the patient's advocate. */
export function SafeguardingPatient() {
  const { id = "" } = useParams();
  const patient = useLoad<PatientOut>(`/v1/patients/${id}`);
  const week = new Date(Date.now() - 7 * 86_400_000);
  const [from, setFrom] = useState(new Date(week.getTime() - week.getTimezoneOffset() * 60000).toISOString().slice(0, 16));
  const report = useLoad<AccessReportOut>(`/v1/patients/${id}/access-report`, { from: localToIso(from) });
  const { practitioners, person } = useDirectory();
  const [advocate, setAdvocate] = useState("");
  const [news, setNews] = useState<string | null>(null);
  const appoint = useAction(useCallback((key: string, p: string) => api(`/v1/patients/${id}/advocates`, { body: { practitioner_id: p }, key }), [id]));
  return (
    <Page title={patient.data ? `Safeguarding: ${patientName(patient.data)}` : "Safeguarding"}>
      <p>
        <Link to="/safeguarding">Back to safeguarding</Link>
      </p>
      {news && <Notice kind="success">{news}</Notice>}
      <Section title="Who accessed the record">
        <div className="row search" role="group" aria-label="Period">
          <Field label="Since" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        {report.loading && <Loading />}
        {report.error !== null && <Notice kind="error">{messageFor(report.error)}</Notice>}
        {report.data && (
          <>
            {report.data.flagged > 0 && <Notice kind="warning">{report.data.flagged === 1 ? "1 access is flagged" : `${report.data.flagged} accesses are flagged`}: refused, emergency or out of hours.</Notice>}
            <table className="table">
              <caption>By person</caption>
              <thead>
                <tr>
                  <th scope="col">Who</th>
                  <th scope="col">Accesses</th>
                  <th scope="col">Flagged</th>
                </tr>
              </thead>
              <tbody>
                {report.data.by_actor.map((a) => (
                  <tr key={a.actor_subject}>
                    <th scope="row">{a.actor_subject}</th>
                    <td>{a.entries}</td>
                    <td>{a.flagged}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <details>
              <summary>Every access ({report.data.entries.length})</summary>
              <ul className="list">
                {report.data.entries.map((e, n) => (
                  <li key={n}>
                    {dateTime(e.occurred_at)} · {e.actor_practitioner_id ? person(e.actor_practitioner_id) : e.actor_subject} · {words(e.action.replaceAll(".", "_"))} · {words(e.outcome)}
                    {e.flags.map((f) => (
                      <Tag key={f} tone="warn">
                        {words(f)}
                      </Tag>
                    ))}
                  </li>
                ))}
              </ul>
            </details>
          </>
        )}
      </Section>
      <Section title="Independent advocate">
        <form
          noValidate
          aria-label="Appoint an advocate"
          onSubmit={async (e) => {
            e.preventDefault();
            if (advocate && (await appoint.run(advocate))) setNews(`${person(advocate)} is appointed as the patient's advocate and can now see this report.`);
          }}
        >
          {appoint.error && <Notice kind="error">{appoint.error}</Notice>}
          <Select label="Advocate" placeholder="Choose" options={practitioners.map((p) => [p.id, p.display_name])} value={advocate} onChange={(e) => setAdvocate(e.target.value)} />
          <Button type="submit" busy={appoint.busy}>Appoint</Button>
        </form>
      </Section>
    </Page>
  );
}

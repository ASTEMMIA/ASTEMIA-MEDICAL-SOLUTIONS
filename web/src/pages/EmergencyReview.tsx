import { useCallback, useState, type FormEvent } from "react";
import { api, messageFor } from "../api";
import type { EmergencyGrantOut } from "../api-types";
import { Button, Empty, Loading, Notice, Page, Radios, Tag, TextArea } from "../components/ui";
import { useDirectory } from "../directory";
import { dateTime, words } from "../format";
import { useAction, useLoad } from "../hooks";

/** Privacy officers review every emergency access grant within a working day (SEC-04). */
export function EmergencyReview() {
  const [reviewed, setReviewed] = useState(false);
  const grants = useLoad<EmergencyGrantOut[]>("/v1/emergency-grants", { reviewed, limit: 100 });
  const [done, setDone] = useState<string | null>(null);
  return (
    <Page title="Emergency access reviews" intro="Every time a chart is opened without a care relationship. Overdue reviews come first.">
      {done && <Notice kind="success">{done}</Notice>}
      <Radios
        legend="Show"
        name="reviewed"
        value={reviewed ? "yes" : "no"}
        onChange={(v) => setReviewed(v === "yes")}
        options={[
          ["no", "Waiting for review"],
          ["yes", "Reviewed"],
        ]}
      />
      {grants.loading && <Loading />}
      {grants.error !== null && <Notice kind="error">{messageFor(grants.error)}</Notice>}
      {grants.data && grants.data.length === 0 && <Empty>{reviewed ? "No reviewed grants." : "Nothing is waiting for review."}</Empty>}
      {grants.data?.map((g) => (
        <Grant
          key={g.id}
          grant={g}
          onDone={(m) => {
            setDone(m);
            grants.reload();
          }}
        />
      ))}
    </Page>
  );
}

function Grant({ grant, onDone }: { grant: EmergencyGrantOut; onDone: (m: string) => void }) {
  const { person } = useDirectory();
  const [outcome, setOutcome] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | undefined>();
  const review = useAction(
    useCallback(
      (key: string, o: string, n: string) => api(`/v1/emergency-grants/${grant.id}/review`, { body: { outcome: o, note: n }, version: grant.version, key }),
      [grant],
    ),
  );
  const who = person(grant.practitioner_id);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!outcome) return setError("Choose whether the access was appropriate.");
    if (note.trim().length < 3) return setError("Add a note for the record.");
    setError(undefined);
    if (await review.run(outcome, note.trim())) onDone(`Review recorded for ${who}'s access.`);
  }
  return (
    <article className="pair" aria-label={`Emergency access by ${who}`}>
      <h3>
        {who} <span className="muted">· {dateTime(grant.starts_at)}</span>{" "}
        {grant.live && <Tag tone="warn">Still open</Tag>}
        {grant.review_overdue && <Tag tone="bad">Review overdue</Tag>}
      </h3>
      <dl className="facts">
        <dt>Purpose given</dt>
        <dd>{grant.purpose}</dd>
        <dt>Access</dt>
        <dd>
          {words(grant.scope)} until {dateTime(grant.expires_at)}
        </dd>
        <dt>Step-up check</dt>
        <dd>{words(grant.step_up)}</dd>
        <dt>Review due</dt>
        <dd>{dateTime(grant.review_due_at)}</dd>
        {grant.reviewed_at && (
          <>
            <dt>Outcome</dt>
            <dd>
              {words(grant.review_outcome ?? "")}, by {person(grant.reviewed_by_id)} on {dateTime(grant.reviewed_at)}: {grant.review_note}
            </dd>
          </>
        )}
      </dl>
      {!grant.reviewed_at && (
        <form onSubmit={submit} noValidate>
          {(error || review.error) && <Notice kind="error">{error ?? review.error}</Notice>}
          <Radios
            legend="Was this access appropriate?"
            name={`outcome-${grant.id}`}
            value={outcome}
            onChange={setOutcome}
            options={[
              ["appropriate", "Appropriate"],
              ["inappropriate", "Inappropriate"],
            ]}
          />
          <TextArea label="Note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
          <Button type="submit" busy={review.busy}>
            Record review
          </Button>
        </form>
      )}
    </article>
  );
}

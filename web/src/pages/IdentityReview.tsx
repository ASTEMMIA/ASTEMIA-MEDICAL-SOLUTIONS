import { useCallback, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, messageFor } from "../api";
import type { CandidateOut, DuplicateGroup, ReviewTaskOut } from "../api-types";
import { Button, Empty, Loading, Notice, Page, Radios, Section, Tag, TextArea } from "../components/ui";
import { date, words } from "../format";
import { useAction, useLoad } from "../hooks";

/**
 * Identity review (WF01 steps 1 and 4, ICRS 3.2.12): pairs of records that may
 * be one person. A steward decides they are different people, or merges one
 * into the other. Only enough is shown to tell people apart.
 */
export function IdentityReview() {
  const tasks = useLoad<ReviewTaskOut[]>("/v1/identity-review-tasks", { resolved: false, limit: 50 });
  const groups = useLoad<DuplicateGroup[]>("/v1/patient-index/duplicates");
  const [done, setDone] = useState<string | null>(null);
  return (
    <Page title="Identity review" intro="Records that may belong to the same person. Decide each pair.">
      {done && <Notice kind="success">{done}</Notice>}
      <Section title="To review">
        {tasks.loading && <Loading />}
        {tasks.error !== null && <Notice kind="error">{messageFor(tasks.error)}</Notice>}
        {tasks.data && tasks.data.length === 0 && <Empty>No pairs are waiting for review.</Empty>}
        {tasks.data?.map((t) => (
          <Pair
            key={t.id}
            task={t}
            onDone={(message) => {
              setDone(message);
              tasks.reload();
              groups.reload();
            }}
          />
        ))}
      </Section>
      <Section title="Same name, date of birth and sex">
        {groups.data && groups.data.length === 0 && <Empty>No open records share all three.</Empty>}
        {groups.data && groups.data.length > 0 && (
          <ul className="list">
            {groups.data.map((g) => (
              <li key={g.patient_ids.join()}>
                {words(g.family_name)}, born {date(g.birth_date)}, {words(g.administrative_sex)}:{" "}
                {g.patient_ids.map((id, i) => (
                  <span key={id}>
                    {i > 0 && ", "}
                    <Link to={`/patients/${id}`}>record {i + 1}</Link>
                  </span>
                ))}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </Page>
  );
}

function describe(c: CandidateOut): string {
  return `${c.family_name} ${c.given_initial}., born ${c.birth_year}`;
}

function Pair({ task, onDone }: { task: ReviewTaskOut; onDone: (message: string) => void }) {
  const [a, b] = task.records as [CandidateOut, CandidateOut];
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const act = useAction(
    useCallback(async (key: string, choice: string, why: string) => {
      if (choice === "distinct") {
        return api(`/v1/identity-review-tasks/${task.id}/resolve`, { body: { resolution: "distinct", reason: why }, version: task.version, key });
      }
      // "keep:<id>": the other record is merged into the one kept.
      const survivor = choice.slice(5);
      const prior = survivor === a.id ? b : a;
      return api(`/v1/patients/${prior.id}/merge`, { body: { survivor_id: survivor, reason: why }, version: prior.version, key });
    }, [task, a, b]),
  );
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!decision) return setError("Choose a decision.");
    if (reason.trim().length < 3) return setError("Give the reason for the record.");
    setError(undefined);
    if (await act.run(decision, reason.trim()))
      onDone(decision === "distinct" ? `Recorded as different people: ${describe(a)} and ${describe(b)}.` : `Merged: ${describe(a)} and ${describe(b)} are now one record.`);
  }
  return (
    <article className="pair" aria-label={`Possible match: ${describe(a)} and ${describe(b)}`}>
      <h3>
        {describe(a)} and {describe(b)} <Tag tone={task.score >= 80 ? "bad" : "warn"}>Score {task.score}</Tag>
      </h3>
      <p className="muted">
        Raised {task.origin ? `at ${words(task.origin)}` : ""}. Why: {task.reasons.map(words).join("; ")}.
      </p>
      <table className="table compact">
        <thead>
          <tr>
            <th scope="col">
              <span className="visually-hidden">Detail</span>
            </th>
            <th scope="col">Record 1</th>
            <th scope="col">Record 2</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Name</th>
            <td>
              {a.family_name} {a.given_initial}.
            </td>
            <td>
              {b.family_name} {b.given_initial}.
            </td>
          </tr>
          <tr>
            <th scope="row">Born</th>
            <td>{a.birth_year}</td>
            <td>{b.birth_year}</td>
          </tr>
          <tr>
            <th scope="row">Sex</th>
            <td>{words(a.administrative_sex)}</td>
            <td>{words(b.administrative_sex)}</td>
          </tr>
          <tr>
            <th scope="row">Identifiers</th>
            <td className="mono">{a.identifiers.map((i) => `${i.issuer} ${i.value}`).join(", ") || "None"}</td>
            <td className="mono">{b.identifiers.map((i) => `${i.issuer} ${i.value}`).join(", ") || "None"}</td>
          </tr>
        </tbody>
      </table>
      <form onSubmit={submit} noValidate>
        {(error || act.error) && <Notice kind="error">{error ?? act.error}</Notice>}
        <Radios
          legend="Decision"
          name={`decision-${task.id}`}
          value={decision}
          onChange={setDecision}
          options={[
            ["distinct", "These are different people"],
            [`keep:${a.id}`, "Same person: keep record 1, merge record 2 into it"],
            [`keep:${b.id}`, "Same person: keep record 2, merge record 1 into it"],
          ]}
        />
        <TextArea label="Reason" hint="Recorded with the decision." value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255} />
        <Button type="submit" busy={act.busy}>
          Record decision
        </Button>
      </form>
    </article>
  );
}

import { useCallback, useState, type FormEvent } from "react";
import { api, messageFor } from "../api";
import type { LabOrderOut, ReleaseReport, ReportStatus } from "../api-types";
import { Button, Empty, Field, Loading, Notice, Page, Select, Tag, TextArea } from "../components/ui";
import { date, dateTime, nin, nowLocal, localToIso, patientName, words } from "../format";
import { useAction, useLoad } from "../hooks";
import { labTest } from "../lab";

/** Orders waiting for a result, urgent first, and result entry (API-03 release). */
export function LabWorklist() {
  const work = useLoad<LabOrderOut[]>("/v1/orders/worklist", { limit: 100 });
  const [open, setOpen] = useState<string | null>(null);
  const [released, setReleased] = useState<string | null>(null);
  return (
    <Page title="Laboratory worklist" intro="Orders waiting for a result. Urgent orders come first, then the oldest.">
      {released && <Notice kind="success">Result released for {released}. The requesting clinician has been asked to acknowledge it.</Notice>}
      {work.loading && <Loading what="Loading the worklist" />}
      {work.error !== null && <Notice kind="error">{messageFor(work.error)}</Notice>}
      {work.data &&
        (work.data.length === 0 ? (
          <Empty>Nothing is waiting for a result.</Empty>
        ) : (
          <table className="table">
            <caption>{work.data.length === 1 ? "1 order" : `${work.data.length} orders`}</caption>
            <thead>
              <tr>
                <th scope="col">Patient</th>
                <th scope="col">Test</th>
                <th scope="col">Priority</th>
                <th scope="col">Ordered</th>
                <th scope="col">
                  <span className="visually-hidden">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {work.data.map((w) => (
                <Row
                  key={w.order.id}
                  item={w}
                  open={open === w.order.id}
                  onOpen={() => setOpen(open === w.order.id ? null : w.order.id)}
                  onReleased={() => {
                    setOpen(null);
                    setReleased(`${w.order.display}, ${patientName(w.patient)}`);
                    work.reload();
                  }}
                />
              ))}
            </tbody>
          </table>
        ))}
    </Page>
  );
}

function Row({ item, open, onOpen, onReleased }: { item: LabOrderOut; open: boolean; onOpen: () => void; onReleased: () => void }) {
  const { order, patient } = item;
  return (
    <>
      <tr>
        <th scope="row">
          {patientName(patient)}
          <div className="muted">
            Born {date(patient.birth_date)} · NIN <span className="mono">{nin(patient.identifiers)}</span>
          </div>
        </th>
        <td>{order.display}</td>
        <td>{order.priority === "routine" ? "Routine" : <Tag tone="warn">{words(order.priority)}</Tag>}</td>
        <td>{dateTime(item.ordered_at)}</td>
        <td>
          {/* The visible words start the accessible name (WCAG 2.5.3); the rest says which row. */}
          <Button variant="secondary" aria-expanded={open} onClick={onOpen}>
            {open ? "Close" : "Enter result"}
            <span className="visually-hidden">
              : {order.display} for {patientName(patient)}
            </span>
          </Button>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5}>
            <ResultForm item={item} onReleased={onReleased} />
          </td>
        </tr>
      )}
    </>
  );
}

function ResultForm({ item, onReleased }: { item: LabOrderOut; onReleased: () => void }) {
  const known = labTest(item.order.code);
  const [f, setF] = useState({ value: "", unit: known?.unit ?? "", low: known?.low ?? "", high: known?.high ?? "", status: "final" as ReportStatus, at: nowLocal(), conclusion: "" });
  const [error, setError] = useState<string | undefined>();
  const release = useAction(useCallback((key: string, b: ReleaseReport) => api("/v1/diagnostic-reports", { body: b, key }), []));
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!/^-?\d+(\.\d+)?$/.test(f.value.trim())) {
      setError("Enter the value as a number, for example 4.2.");
      return;
    }
    setError(undefined);
    const done = await release.run({
      service_request_id: item.order.id,
      status: f.status,
      effective_at: localToIso(f.at),
      conclusion: f.conclusion.trim() || null,
      observations: [
        {
          code_system: item.order.code_system,
          code: item.order.code,
          display: item.order.display,
          value_type: "quantity",
          quantity: f.value.trim(),
          unit: f.unit.trim() || null,
          ref_low: f.low.trim() || null,
          ref_high: f.high.trim() || null,
        },
      ],
    });
    if (done) onReleased();
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const value = e.target.value;
    setF((prev) => ({ ...prev, [k]: value }));
  };
  return (
    <form onSubmit={submit} className="panel" noValidate aria-label={`Result for ${item.order.display}`}>
      {release.error && <Notice kind="error">{release.error}</Notice>}
      <div className="row">
        <Field label="Value" inputMode="decimal" autoComplete="off" value={f.value} onChange={set("value")} error={error} />
        <Field label="Unit" value={f.unit} onChange={set("unit")} />
        <Field label="Reference low" inputMode="decimal" value={f.low} onChange={set("low")} />
        <Field label="Reference high" inputMode="decimal" value={f.high} onChange={set("high")} />
      </div>
      <div className="row">
        <Select
          label="Report status"
          options={[
            ["final", "Final"],
            ["preliminary", "Preliminary"],
          ]}
          value={f.status}
          onChange={set("status")}
        />
        <Field label="Specimen taken" type="datetime-local" value={f.at} onChange={set("at")} />
      </div>
      <TextArea label="Comment" hint="Optional" value={f.conclusion} onChange={set("conclusion")} maxLength={1000} />
      <Button type="submit" busy={release.busy}>
        Release result
      </Button>
    </form>
  );
}

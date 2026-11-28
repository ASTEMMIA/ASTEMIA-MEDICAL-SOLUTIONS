import { Page } from "../components/ui";
import { roleName } from "../format";
import { useSession } from "../session";

/** Capabilities in words, so people know what their role lets them do. */
export const CAPABILITY_NAMES: Record<string, string> = {
  "patient:register": "Register patients",
  "patient:search": "Search the patient index",
  "patient:merge": "Merge and unmerge patient records",
  "patient:close": "Close patient records",
  "encounter:admit": "Admit patients",
  "chart:read": "Read the charts of patients in your care",
  "order:create": "Place orders",
  "result:release": "Release results",
  "result:acknowledge": "Acknowledge results",
  "identifier:read": "See full identifiers such as the NIN",
  "catalogue:read": "Read the service catalogue",
  "catalogue:manage": "Manage the service catalogue",
  "emergency:request": "Request emergency access to a chart",
  "emergency:review": "Review emergency access",
  "sensitive:mental_health": "See mental health records",
  "sensitive:sexual_health": "See sexual health records",
  "schedule:manage": "Create clinic slots",
  "schedule:book": "Book, reschedule and cancel appointments",
  "appointment:attend": "Record attendance",
  "referral:create": "Refer patients",
  "referral:triage": "Triage referrals",
  "safeguarding:record": "Record restrictive interventions",
  "safeguarding:view": "See a patient's safeguarding log",
  "safeguarding:review": "Review restrictive interventions and concerns",
  "access_report:read": "See who accessed a patient's record",
  "mh_legal:manage": "Record mental health legal status",
  "concern:raise": "Raise a safeguarding concern",
  "note:write": "Write clinical notes",
  "note:sign": "Sign clinical notes",
  "note:sign_nursing": "Sign nursing notes",
  "document:index": "Receive and file correspondence",
  "document:review": "Review correspondence filed to you",
  "task:assign": "Create and manage Daybook tasks",
  "task:supervise": "Supervise every Daybook task",
  "discharge:sign": "Sign off discharges",
  "condition:record": "Record conditions",
  "careplan:manage": "Create and revise care plans",
  "careplan:deliver": "Record care plan sessions",
};

export function Account() {
  const { me } = useSession();
  if (!me) return null;
  return (
    <Page title="My account">
      <dl className="facts">
        <dt>Name</dt>
        <dd>{me.display_name}</dd>
        <dt>Sign-in</dt>
        <dd>{me.subject}</dd>
        <dt>Organisation</dt>
        <dd>{me.tenant_name}</dd>
        <dt>Roles</dt>
        <dd>{me.roles.map(roleName).join(", ")}</dd>
      </dl>
      <h2>What your role allows</h2>
      <ul className="list">
        {me.capabilities.map((c) => (
          <li key={c}>{CAPABILITY_NAMES[c] ?? c}</li>
        ))}
      </ul>
    </Page>
  );
}

import { useState, type FormEvent } from "react";
import { api, messageFor } from "../api";
import { Button, Field, Notice } from "../components/ui";
import { roleName } from "../format";
import { useSession } from "../session";
import type { DevAccount } from "../types";

// The synthetic pilot tenant made by `astemia seed-dev`.
export const DEV_TENANT = "0196f1a0-0000-7000-8000-000000000001";

export function SignIn() {
  const { signedIn, ended } = useSession();
  const [tenant, setTenant] = useState(DEV_TENANT);
  const [accounts, setAccounts] = useState<DevAccount[] | null>(null);
  const [subject, setSubject] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const list = await api<DevAccount[]>("/v1/dev/accounts", { query: { tenant_id: tenant.trim() } });
      setAccounts(list);
      setSubject(list[0]?.subject ?? "");
      if (list.length === 0) setError("No accounts were found for that organisation.");
    } catch (err) {
      setAccounts(null);
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  async function signIn(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const t = await api<{ access_token: string }>("/v1/dev/sign-in", { body: { tenant_id: tenant.trim(), subject } });
      await signedIn(t.access_token);
    } catch (err) {
      setError(messageFor(err));
      setBusy(false);
    }
  }

  return (
    <main id="main" className="signin">
      <h1>Sign in to ASTEMIA Health</h1>
      <Notice kind="warning">
        <strong>Development sign-in.</strong> This environment uses synthetic data. In production you sign in through
        your organisation's identity provider.
      </Notice>
      {ended && <Notice kind="info">Your session ended. Sign in again to continue.</Notice>}
      {error && <Notice kind="error">{error}</Notice>}
      <form onSubmit={load} noValidate>
        <Field
          label="Organisation ID"
          hint="The tenant to sign in to. The synthetic pilot hospital is filled in."
          value={tenant}
          onChange={(e) => setTenant(e.target.value)}
          required
          autoComplete="off"
          spellCheck={false}
        />
        <Button type="submit" variant="secondary" busy={busy && accounts === null}>
          Show accounts
        </Button>
      </form>
      {accounts && accounts.length > 0 && (
        <form onSubmit={signIn}>
          <fieldset>
            <legend>Sign in as</legend>
            {accounts.map((a) => (
              <div className="radio" key={a.subject}>
                <input
                  type="radio"
                  id={`acct-${a.subject}`}
                  name="account"
                  value={a.subject}
                  checked={subject === a.subject}
                  onChange={() => setSubject(a.subject)}
                />
                <label htmlFor={`acct-${a.subject}`}>
                  {a.display_name} <span className="muted">({a.roles.map(roleName).join(", ")})</span>
                </label>
              </div>
            ))}
          </fieldset>
          <Button type="submit" busy={busy}>
            Sign in
          </Button>
        </form>
      )}
    </main>
  );
}

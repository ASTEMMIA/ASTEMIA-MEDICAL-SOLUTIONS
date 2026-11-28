import { NavLink, Navigate, Route, Routes } from "react-router";
import { Loading } from "./components/ui";
import { roleName } from "./format";
import { Account } from "./pages/Account";
import { Book } from "./pages/Book";
import { CarePlan } from "./pages/CarePlan";
import { Chart } from "./pages/Chart";
import { Clinics } from "./pages/Clinics";
import { Correspondence } from "./pages/Correspondence";
import { Daybook } from "./pages/Daybook";
import { EmergencyReview } from "./pages/EmergencyReview";
import { Home } from "./pages/Home";
import { IdentityReview } from "./pages/IdentityReview";
import { LabWorklist } from "./pages/LabWorklist";
import { Patients } from "./pages/Patients";
import { Referrals } from "./pages/Referrals";
import { Safeguarding, SafeguardingPatient } from "./pages/Safeguarding";
import { RegisterPatient } from "./pages/RegisterPatient";
import { Sessions } from "./pages/Sessions";
import { SignIn } from "./pages/SignIn";
import { DirectoryProvider } from "./directory";
import { useSession } from "./session";

export function App() {
  const { status, me, signOut, can } = useSession();
  if (status === "loading") return <Loading what="Signing you in" />;
  if (status === "signedout" || !me) return <SignIn />;
  return (
    <DirectoryProvider key={me.subject}>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="masthead">
        <div className="brand">
          <span className="product">ASTEMIA Health</span>
          <span className="tenant" aria-label="Organisation">
            {me.tenant_name}
          </span>
        </div>
        <div className="who">
          <span>
            {me.display_name}
            <span className="roles"> · {me.roles.map(roleName).join(", ")}</span>
          </span>
          <button type="button" className="btn btn-secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <nav className="nav" aria-label="Main">
        <ul>
          <li>
            <NavLink to="/" end>
              Home
            </NavLink>
          </li>
          {can("task:assign", "task:supervise") && (
            <li>
              <NavLink to="/daybook">Daybook</NavLink>
            </li>
          )}
          {can("patient:search") && (
            <li>
              <NavLink to="/patients">Patients</NavLink>
            </li>
          )}
          {can("appointment:attend") && (
            <li>
              <NavLink to="/clinics">Clinics</NavLink>
            </li>
          )}
          {can("schedule:manage") && (
            <li>
              <NavLink to="/sessions">Sessions</NavLink>
            </li>
          )}
          {can("referral:triage") && (
            <li>
              <NavLink to="/referrals">Referrals</NavLink>
            </li>
          )}
          {can("document:index") && (
            <li>
              <NavLink to="/correspondence">Correspondence</NavLink>
            </li>
          )}
          {can("result:release") && (
            <li>
              <NavLink to="/lab">Laboratory</NavLink>
            </li>
          )}
          {can("patient:merge") && (
            <li>
              <NavLink to="/identity-review">Identity review</NavLink>
            </li>
          )}
          {can("safeguarding:review") && (
            <li>
              <NavLink to="/safeguarding">Safeguarding</NavLink>
            </li>
          )}
          {can("emergency:review") && (
            <li>
              <NavLink to="/emergency-access">Emergency access</NavLink>
            </li>
          )}
          <li>
            <NavLink to="/account">My account</NavLink>
          </li>
        </ul>
      </nav>
      <main id="main" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/account" element={<Account />} />
          <Route path="/patients" element={<Patients />} />
          <Route path="/patients/new" element={<RegisterPatient />} />
          <Route path="/patients/:id" element={<Chart />} />
          <Route path="/lab" element={<LabWorklist />} />
          <Route path="/clinics" element={<Clinics />} />
          <Route path="/daybook" element={<Daybook />} />
          <Route path="/care-plans/:id" element={<CarePlan />} />
          <Route path="/safeguarding" element={<Safeguarding />} />
          <Route path="/safeguarding/patients/:id" element={<SafeguardingPatient />} />
          <Route path="/book" element={<Book />} />
          <Route path="/sessions" element={<Sessions />} />
          <Route path="/referrals" element={<Referrals />} />
          <Route path="/correspondence" element={<Correspondence />} />
          <Route path="/identity-review" element={<IdentityReview />} />
          <Route path="/emergency-access" element={<EmergencyReview />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </DirectoryProvider>
  );
}

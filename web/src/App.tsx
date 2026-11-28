import { NavLink, Navigate, Route, Routes } from "react-router";
import { Loading } from "./components/ui";
import { roleName } from "./format";
import { Account } from "./pages/Account";
import { Chart } from "./pages/Chart";
import { EmergencyReview } from "./pages/EmergencyReview";
import { Home } from "./pages/Home";
import { IdentityReview } from "./pages/IdentityReview";
import { LabWorklist } from "./pages/LabWorklist";
import { Patients } from "./pages/Patients";
import { RegisterPatient } from "./pages/RegisterPatient";
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
          {can("patient:search") && (
            <li>
              <NavLink to="/patients">Patients</NavLink>
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
          <Route path="/identity-review" element={<IdentityReview />} />
          <Route path="/emergency-access" element={<EmergencyReview />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </DirectoryProvider>
  );
}

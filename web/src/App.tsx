import { NavLink, Navigate, Route, Routes } from "react-router";
import { Loading } from "./components/ui";
import { roleName } from "./format";
import { Account } from "./pages/Account";
import { Home } from "./pages/Home";
import { SignIn } from "./pages/SignIn";
import { useSession } from "./session";

export function App() {
  const { status, me, signOut } = useSession();
  if (status === "loading") return <Loading what="Signing you in" />;
  if (status === "signedout" || !me) return <SignIn />;
  return (
    <>
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
          <li>
            <NavLink to="/account">My account</NavLink>
          </li>
        </ul>
      </nav>
      <main id="main" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/account" element={<Account />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}

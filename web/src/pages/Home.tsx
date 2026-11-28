import { Link } from "react-router";
import { Page } from "../components/ui";
import { roleName } from "../format";
import { useSession } from "../session";

export function Home() {
  const { me } = useSession();
  if (!me) return null;
  return (
    <Page title={`Welcome, ${me.display_name}`} intro={`You are signed in to ${me.tenant_name} as ${me.roles.map(roleName).join(", ")}.`}>
      <p>
        <Link to="/account">See what your role allows</Link>
      </p>
    </Page>
  );
}

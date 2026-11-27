import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, clearToken, setToken, token, whenSignedOut } from "./api";
import type { Me } from "./types";

interface Session {
  status: "loading" | "signedout" | "ready";
  me: Me | null;
  /** The session ended by itself (expired or revoked), not by signing out. */
  ended: boolean;
  can: (...capabilities: string[]) => boolean;
  signedIn: (accessToken: string) => Promise<void>;
  signOut: () => void;
}

const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Session["status"]>(token() ? "loading" : "signedout");
  const [me, setMe] = useState<Me | null>(null);
  const [ended, setEnded] = useState(false);

  const load = useCallback(async () => {
    try {
      setMe(await api<Me>("/v1/me"));
      setStatus("ready");
    } catch {
      clearToken();
      setMe(null);
      setStatus("signedout");
    }
  }, []);

  useEffect(() => {
    whenSignedOut(() => {
      setEnded(true);
      setMe(null);
      setStatus("signedout");
    });
    if (token()) void load();
  }, [load]);

  const value = useMemo<Session>(
    () => ({
      status,
      me,
      ended,
      can: (...cs) => cs.some((c) => me?.capabilities.includes(c) ?? false),
      signedIn: async (accessToken) => {
        // A new sign-in starts clean: nothing from a previous tenant survives.
        setMe(null);
        setToken(accessToken);
        setEnded(false);
        setStatus("loading");
        await load();
      },
      signOut: () => {
        clearToken();
        setMe(null);
        setEnded(false);
        setStatus("signedout");
      },
    }),
    [status, me, ended, load],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}

import { createContext, useContext, useMemo, type ReactNode } from "react";
import type { FacilityOut, PractitionerOut } from "./api-types";
import { useLoad } from "./hooks";

interface Directory {
  practitioners: PractitionerOut[];
  facilities: FacilityOut[];
  /** A practitioner's name; "—" when there is none, the ID's start when unknown. */
  person: (id: string | null | undefined) => string;
  place: (id: string | null | undefined) => string;
}

const Ctx = createContext<Directory | null>(null);

/** Staff and sites, loaded once per sign-in, so records show names rather than IDs. */
export function DirectoryProvider({ children }: { children: ReactNode }) {
  const staff = useLoad<PractitionerOut[]>("/v1/practitioners");
  const sites = useLoad<FacilityOut[]>("/v1/facilities");
  const value = useMemo<Directory>(() => {
    const practitioners = staff.data ?? [];
    const facilities = sites.data ?? [];
    const people = new Map(practitioners.map((p) => [p.id, p.display_name]));
    const places = new Map(facilities.map((f) => [f.id, `${f.site_name}, ${f.organisation_name}`]));
    const lookup = (names: Map<string, string>) => (id: string | null | undefined) =>
      !id ? "—" : (names.get(id) ?? `Unknown (${id.slice(0, 8)})`);
    return { practitioners, facilities, person: lookup(people), place: lookup(places) };
  }, [staff.data, sites.data]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDirectory(): Directory {
  const d = useContext(Ctx);
  if (!d) throw new Error("useDirectory outside DirectoryProvider");
  return d;
}

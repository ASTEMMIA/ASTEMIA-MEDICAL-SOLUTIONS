/**
 * Dates and times for people (NFR-03): always local time with the time zone,
 * so an event recorded at another site is never misread.
 */
const ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

export function dateTime(iso: string | null | undefined, timeZone: string = ZONE): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone,
    timeZoneName: "short",
  }).format(new Date(iso));
}

export function date(iso: string | null | undefined): string {
  if (!iso) return "—";
  // A calendar date has no time zone: read it as written.
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(Date.UTC(y!, (m ?? 1) - 1, d ?? 1)),
  );
}

/** Role codes as people say them. */
export function roleName(role: string): string {
  return role.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
}

/** A code as words: "general_medicine" → "General medicine". */
export const words = roleName;

/** A person's name as records show it: "ADEYEMI, Folake Ngozi". */
export function patientName(p: { family_name: string; given_names: string }): string {
  return `${p.family_name.toUpperCase()}, ${p.given_names}`;
}

/** The NIN, as the server sent it (masked for roles without identifier:read). */
export function nin(identifiers: { issuer: string; value: string }[] | undefined): string {
  return identifiers?.find((i) => i.issuer === "NG-NIN")?.value ?? "—";
}

/** Today's date in the browser's zone, for date inputs (yyyy-mm-dd). */
export function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** A datetime-local input's value as an ISO instant with the browser's offset. */
export function localToIso(local: string): string {
  return new Date(local).toISOString();
}

/** Now, for a datetime-local input. */
export function nowLocal(): string {
  const d = new Date();
  d.setSeconds(0, 0);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

/** A decimal as people write it: "6.100000" → "6.1". Non-numbers unchanged. */
export function num(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  return /^-?\d+(\.\d+)?$/.test(value) ? String(Number(value)) : value;
}

/** "1 record", "3 records". */
export function count(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

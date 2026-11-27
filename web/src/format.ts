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

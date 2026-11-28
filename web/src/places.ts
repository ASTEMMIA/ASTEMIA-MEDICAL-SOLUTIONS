/** Nigeria's 36 states and the Federal Capital Territory, for address entry. */
export const NG_STATES = [
  "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno", "Cross River", "Delta",
  "Ebonyi", "Edo", "Ekiti", "Enugu", "Federal Capital Territory", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano",
  "Katsina", "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau",
  "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara",
];

export const COUNTRIES: [string, string][] = [
  ["NG", "Nigeria"],
  ["GH", "Ghana"],
  ["GB", "United Kingdom"],
  ["US", "United States"],
  ["BJ", "Benin"],
  ["CM", "Cameroon"],
  ["NE", "Niger"],
  ["TG", "Togo"],
];

/** The postcode rule the API applies, so the form can say so before sending. */
export function postcodeProblem(country: string, postcode: string): string | undefined {
  const v = postcode.trim().toUpperCase();
  if (!v) return "Enter the postcode.";
  if (country === "NG" && !/^\d{6}$/.test(v)) return "A Nigerian postcode is 6 digits, for example 101241.";
  if (country === "GB" && !/^[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}$/.test(v)) return "Enter a UK postcode, for example SW1A 1AA.";
  if (!/^[A-Z0-9][A-Z0-9 -]{1,10}[A-Z0-9]$/.test(v)) return "Enter a valid postcode.";
  return undefined;
}

/** One line for display: "12 Adeola Odeku Street, Victoria Island, Lagos, Eti-Osa, Lagos State 101241". */
export function addressLine(a: {
  line1: string;
  line2?: string | null;
  town: string;
  local_government_area?: string | null;
  state?: string | null;
  postcode?: string | null;
  country: string;
}): string {
  const state = a.state ? (a.country === "NG" && a.state !== "Federal Capital Territory" ? `${a.state} State` : a.state) : null;
  const parts = [a.line1, a.line2, a.town, a.local_government_area, [state, a.postcode].filter(Boolean).join(" ")];
  const country = a.country === "NG" ? null : (COUNTRIES.find(([c]) => c === a.country)?.[1] ?? a.country);
  return [...parts, country].filter(Boolean).join(", ");
}

import type { AddressIn } from "../api-types";
import { COUNTRIES, NG_STATES, postcodeProblem } from "../places";
import { Field, Select } from "./ui";

export interface AddressForm {
  line1: string;
  line2: string;
  town: string;
  lga: string;
  state: string;
  postcode: string;
  country: string;
}

export const EMPTY_ADDRESS: AddressForm = { line1: "", line2: "", town: "", lga: "", state: "", postcode: "", country: "NG" };

/** The rules the API applies, checked before sending; keys match the fields. */
export function addressErrors(a: AddressForm): Record<string, string> {
  const e: Record<string, string> = {};
  if (!a.line1.trim()) e.line1 = "Enter the house number and street.";
  if (!a.town.trim()) e.town = "Enter the town or city.";
  if (a.country === "NG" && !a.state) e.state = "Choose the state.";
  if (a.country === "NG" && !a.lga.trim()) e.lga = "Enter the local government area.";
  const pc = postcodeProblem(a.country, a.postcode);
  if (pc) e.postcode = pc;
  return e;
}

export function toAddressIn(a: AddressForm): AddressIn {
  return {
    line1: a.line1.trim(),
    line2: a.line2.trim() || null,
    town: a.town.trim(),
    local_government_area: a.lga.trim() || null,
    state: a.state.trim() || null,
    postcode: a.postcode.trim(),
    country: a.country,
  };
}

/** The full address: country, street, area, town, state, local government area and postcode. */
export function AddressFields({
  value,
  onChange,
  errors,
  legend,
}: {
  value: AddressForm;
  onChange: (next: AddressForm) => void;
  errors: Record<string, string>;
  legend: string;
}) {
  const set = (k: keyof AddressForm) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  const ng = value.country === "NG";
  return (
    <fieldset className="address">
      <legend>{legend}</legend>
      <p className="hint">Required for every patient: the full address and postcode.</p>
      <Select label="Country" options={COUNTRIES} value={value.country} onChange={set("country")} />
      <Field label="House number and street" autoComplete="off" value={value.line1} onChange={set("line1")} error={errors.line1} />
      <Field label="Area or estate" hint="Optional" autoComplete="off" value={value.line2} onChange={set("line2")} />
      <div className="row">
        <Field label="Town or city" autoComplete="off" value={value.town} onChange={set("town")} error={errors.town} />
        {ng ? (
          <Select label="State" placeholder="Choose" options={NG_STATES.map((n) => [n, n])} value={value.state} onChange={set("state")} error={errors.state} />
        ) : (
          <Field label="State, county or region" hint="Optional" autoComplete="off" value={value.state} onChange={set("state")} />
        )}
      </div>
      <div className="row">
        <Field label="Local government area" hint={ng ? undefined : "Optional"} autoComplete="off" value={value.lga} onChange={set("lga")} error={errors.lga} />
        <Field label="Postcode" hint={ng ? "6 digits" : undefined} autoComplete="off" value={value.postcode} onChange={set("postcode")} error={errors.postcode} />
      </div>
    </fieldset>
  );
}

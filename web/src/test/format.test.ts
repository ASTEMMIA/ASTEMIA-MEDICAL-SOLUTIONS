import { describe, expect, it } from "vitest";
import { date, dateTime, nin, num, patientName, roleName } from "../format";

describe("format", () => {
  it("shows times with their time zone and dates as written", () => {
    expect(dateTime("2026-11-27T14:05:00Z", "Africa/Lagos")).toMatch(/27 Nov 2026.*15:05.*(WAT|GMT\+1)/);
    expect(dateTime(null)).toBe("—");
    expect(date("2026-03-09")).toBe("9 Mar 2026");
    expect(date(undefined)).toBe("—");
  });
  it("names roles as people say them", () => {
    expect(roleName("identity_steward")).toBe("Identity steward");
  });
  it("writes numbers, names and identifiers as people expect", () => {
    expect([num("6.100000"), num("45"), num("-0.50"), num("<0.1"), num(null), num("")]).toEqual(["6.1", "45", "-0.5", "<0.1", "", ""]);
    expect(patientName({ family_name: "Okonkwo", given_names: "Chiamaka Ada" })).toBe("OKONKWO, Chiamaka Ada");
    expect(nin([{ issuer: "X", value: "1" }, { issuer: "NG-NIN", value: "405•••••678" }])).toBe("405•••••678");
    expect(nin(undefined)).toBe("—");
  });
});

import { describe, expect, it } from "vitest";
import { date, dateTime, roleName } from "../format";

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
});

import { describe, expect, it } from "vitest";
import { addressLine, postcodeProblem } from "../places";

describe("addresses", () => {
  it("checks the postcode the way the API does", () => {
    expect(postcodeProblem("NG", "101241")).toBeUndefined();
    expect(postcodeProblem("NG", "10124")).toMatch(/6 digits/);
    expect(postcodeProblem("NG", " ")).toBe("Enter the postcode.");
    expect(postcodeProblem("GB", "sw1a 1aa")).toBeUndefined();
    expect(postcodeProblem("GB", "12345")).toMatch(/UK postcode/);
    expect(postcodeProblem("GH", "GA-184-5671")).toBeUndefined();
    expect(postcodeProblem("GH", "!")).toBe("Enter a valid postcode.");
  });

  it("writes an address on one line", () => {
    const lagos = { line1: "12 Adeola Odeku Street", line2: "Victoria Island", town: "Lagos", local_government_area: "Eti-Osa", state: "Lagos", postcode: "101241", country: "NG" };
    expect(addressLine(lagos)).toBe("12 Adeola Odeku Street, Victoria Island, Lagos, Eti-Osa, Lagos State 101241");
    expect(addressLine({ ...lagos, line2: null, state: "Federal Capital Territory", town: "Abuja", local_government_area: "AMAC", postcode: "900211" })).toBe(
      "12 Adeola Odeku Street, Abuja, AMAC, Federal Capital Territory 900211",
    );
    expect(addressLine({ line1: "10 Downing Street", town: "London", postcode: "SW1A 2AA", country: "GB" })).toBe("10 Downing Street, London, SW1A 2AA, United Kingdom");
    expect(addressLine({ line1: "1 Rue", town: "Paris", country: "FR" })).toBe("1 Rue, Paris, FR");
  });
});

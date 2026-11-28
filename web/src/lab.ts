/**
 * Common laboratory tests offered when ordering and when entering a result,
 * coded in LOINC with adult reference ranges for the pilot. A placeholder for
 * the terminology service (CEDA section 6): the API accepts any coded test.
 */
export interface LabTest {
  code: string;
  display: string;
  unit: string;
  low: string;
  high: string;
}

export const LOINC = "http://loinc.org";

export const LAB_TESTS: LabTest[] = [
  { code: "2823-3", display: "Potassium [Moles/volume] in Serum", unit: "mmol/L", low: "3.5", high: "5.3" },
  { code: "2951-2", display: "Sodium [Moles/volume] in Serum", unit: "mmol/L", low: "133", high: "146" },
  { code: "2160-0", display: "Creatinine [Mass/volume] in Serum", unit: "umol/L", low: "45", high: "90" },
  { code: "2345-7", display: "Glucose [Mass/volume] in Serum", unit: "mmol/L", low: "3.9", high: "7.8" },
  { code: "718-7", display: "Haemoglobin [Mass/volume] in Blood", unit: "g/L", low: "115", high: "165" },
];

export function labTest(code: string): LabTest | undefined {
  return LAB_TESTS.find((t) => t.code === code);
}

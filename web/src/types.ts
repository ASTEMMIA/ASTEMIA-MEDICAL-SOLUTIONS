import type { MeOut } from "./api-types";

export type Me = MeOut;

/** Development sign-in accounts (not in the public API schema). */
export interface DevAccount {
  subject: string;
  display_name: string;
  roles: string[];
}

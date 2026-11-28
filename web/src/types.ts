export interface Me {
  subject: string;
  tenant_id: string;
  tenant_name: string;
  roles: string[];
  capabilities: string[];
  practitioner_id: string | null;
  display_name: string;
}

export interface DevAccount {
  subject: string;
  display_name: string;
  roles: string[];
}

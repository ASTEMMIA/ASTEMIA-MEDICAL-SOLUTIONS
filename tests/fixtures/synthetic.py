"""Synthetic pilot fixtures (CEDA 11.2). No real patient data, ever."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    Membership,
    Organisation,
    OrganisationSite,
    Party,
    Practitioner,
    Tenant,
    WorkgroupTeam,
    WorkgroupTeamMembership,
)


@dataclass
class SyntheticTenant:
    tenant_id: uuid.UUID
    organisation_id: uuid.UUID
    facility_id: uuid.UUID
    second_facility_id: uuid.UUID
    practitioners: dict[str, uuid.UUID]
    workgroup_id: uuid.UUID

    def subject(self, who: str) -> str:
        return f"{who}@{self.tenant_id.hex[:8]}.test"


ROLES = {
    "registrar": ["registrar"],
    "clinician": ["clinician"],
    "clinician2": ["clinician"],
    "nurse": ["nurse"],
    "scientist": ["lab_scientist"],
    "admin": ["tenant_admin"],
    "psychiatrist": ["clinician", "sensitive_reader"],
    "steward": ["identity_steward"],
    "privacy": ["privacy_officer"],
    "scheduler": ["scheduler"],
    "scheduler2": ["scheduler"],
    "lead": ["safeguarding_lead"],
    "lead2": ["safeguarding_lead"],
    "advocate": ["patient_advocate"],
    "clerk": ["records_clerk"],
    "supervisor": ["team_supervisor"],
    "radiologist": ["radiologist"],
    "radiographer": ["radiographer"],
    # A clinician who is also a privacy officer may not review their own grant.
    "dual": ["clinician", "privacy_officer"],
}
# Members with no practitioner record (e.g. service accounts) and one with no
# catalogue access, for the negative authorisation paths.
UNLINKED = {
    "unlinked_clinician": ["clinician"],
    "unlinked_scientist": ["lab_scientist"],
    "unlinked_radiologist": ["radiologist"],
    "interface": ["interface_engine"],
    "migrator": ["data_migration_officer"],
    "no_catalogue": ["sensitive_reader"],
    "unlinked_steward": ["identity_steward"],
    "unlinked_privacy": ["privacy_officer"],
    "unlinked_lead": ["safeguarding_lead"],
}


def make_tenant(factory: sessionmaker[Session]) -> SyntheticTenant:
    tid = uuid.uuid7()
    now = datetime.now(UTC) - timedelta(minutes=5)
    practitioners: dict[str, uuid.UUID] = {}
    with factory() as s, s.begin():
        s.add(Tenant(id=tid, name=f"Synthetic {tid.hex[:8]}", country_profile="NG", created_at=now))
        s.flush()

        def party(kind: str) -> uuid.UUID:
            pid = uuid.uuid7()
            s.add(Party(tenant_id=tid, id=pid, recorded_at=now, party_type=kind))
            s.flush()
            return pid

        org = party("organisation")
        s.add(
            Organisation(
                tenant_id=tid,
                id=org,
                recorded_at=now,
                organisation_code=f"O{tid.hex[:6]}",
                organisation_name="Synthetic General Hospital",
                organisation_type="hospital",
            )
        )
        s.flush()
        site = uuid.uuid7()
        s.add(
            OrganisationSite(
                tenant_id=tid,
                id=site,
                recorded_at=now,
                organisation_id=org,
                site_identifier=f"S{tid.hex[:6]}",
                site_name="Main",
            )
        )
        site2 = uuid.uuid7()
        s.add(
            OrganisationSite(
                tenant_id=tid,
                id=site2,
                recorded_at=now,
                organisation_id=org,
                site_identifier=f"T{tid.hex[:6]}",
                site_name="Annex",
            )
        )
        for who, roles in UNLINKED.items():
            s.add(
                Membership(
                    tenant_id=tid,
                    subject=f"{who}@{tid.hex[:8]}.test",
                    practitioner_id=None,
                    roles=roles,
                    valid_from=now,
                )
            )
        for who, roles in ROLES.items():
            pid = party("person")
            s.add(
                Practitioner(
                    tenant_id=tid,
                    id=pid,
                    recorded_at=now,
                    professional_id=f"HCP-{who}",
                    display_name=who.title(),
                )
            )
            s.flush()
            s.add(
                Membership(
                    tenant_id=tid,
                    subject=f"{who}@{tid.hex[:8]}.test",
                    practitioner_id=pid,
                    roles=roles,
                    valid_from=now,
                )
            )
            practitioners[who] = pid
        wg = uuid.uuid7()
        s.add(
            WorkgroupTeam(
                tenant_id=tid,
                id=wg,
                recorded_at=now,
                organisation_id=org,
                workgroup_identifier=f"WG{tid.hex[:6]}",
                workgroup_name="Ward 1 nursing",
                effective_from=now,
            )
        )
        s.flush()
        s.add(
            WorkgroupTeamMembership(
                tenant_id=tid,
                id=uuid.uuid7(),
                recorded_at=now,
                workgroup_id=wg,
                practitioner_id=practitioners["nurse"],
                effective_from=now,
            )
        )
    return SyntheticTenant(tid, org, site, site2, practitioners, wg)


# A synthetic Nigerian address: every registration carries a full address and
# postcode (CEDA revision 1.8).
ADDRESS = {
    "line1": "12 Adeola Odeku Street",
    "line2": "Victoria Island",
    "town": "Lagos",
    "local_government_area": "Eti-Osa",
    "state": "Lagos",
    "postcode": "101241",
    "country": "NG",
}

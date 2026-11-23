"""Operator CLI: astemia seed-dev | token | relay | serve."""

import argparse
import json
import logging
import time
import uuid
from datetime import UTC, datetime

from astemia.adapters.broker.base import LoggingBroker
from astemia.adapters.db.models import (
    Membership,
    Organisation,
    OrganisationSite,
    Party,
    Practitioner,
    Tenant,
)
from astemia.adapters.db.session import default_session_factory
from astemia.adapters.identity.tokens import issue_dev_token
from astemia.config import get_settings
from astemia.workers.outbox_relay import relay_once

DEV_TENANT = uuid.UUID("0196f1a0-0000-7000-8000-000000000001")


def seed_dev() -> dict[str, str]:
    """A synthetic pilot tenant: one hospital, a registrar, two clinicians and
    a laboratory scientist. Synthetic data only (CEDA 11.2)."""
    factory = default_session_factory()
    now = datetime.now(UTC)
    ids: dict[str, str] = {"tenant_id": str(DEV_TENANT)}
    with factory() as s, s.begin():
        if s.get(Tenant, DEV_TENANT) is not None:
            raise SystemExit("development tenant already seeded")
        s.add(
            Tenant(
                id=DEV_TENANT,
                name="ASTEMIA Pilot Hospital (synthetic)",
                country_profile="NG",
                created_at=now,
            )
        )
        s.flush()

        def party(kind: str) -> uuid.UUID:
            pid = uuid.uuid7()
            s.add(Party(tenant_id=DEV_TENANT, id=pid, recorded_at=now, party_type=kind))
            s.flush()
            return pid

        org = party("organisation")
        s.add(
            Organisation(
                tenant_id=DEV_TENANT,
                id=org,
                recorded_at=now,
                organisation_code="PILOT01",
                organisation_name="ASTEMIA Pilot Hospital",
                organisation_type="hospital",
            )
        )
        site = uuid.uuid7()
        s.flush()
        s.add(
            OrganisationSite(
                tenant_id=DEV_TENANT,
                id=site,
                recorded_at=now,
                organisation_id=org,
                site_identifier="PILOT01-MAIN",
                site_name="Main site",
            )
        )
        ids["organisation_id"], ids["facility_id"] = str(org), str(site)
        people = {
            "registrar": ("Registrar One", ["registrar"]),
            "clinician": ("Dr Clinician One", ["clinician"]),
            "clinician2": ("Dr Clinician Two", ["clinician"]),
            "scientist": ("Lab Scientist One", ["lab_scientist"]),
        }
        for subject, (name, roles) in people.items():
            pid = party("person")
            s.add(
                Practitioner(
                    tenant_id=DEV_TENANT,
                    id=pid,
                    recorded_at=now,
                    professional_id=f"HCP-{subject.upper()}",
                    display_name=name,
                    professional_register="MDCN",
                )
            )
            s.flush()
            s.add(
                Membership(
                    tenant_id=DEV_TENANT,
                    subject=f"{subject}@pilot.astemia.local",
                    practitioner_id=pid,
                    roles=roles,
                    valid_from=now,
                )
            )
            ids[f"{subject}_practitioner_id"] = str(pid)
    return ids


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="astemia")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed-dev")
    tok = sub.add_parser("token")
    tok.add_argument("subject")
    tok.add_argument("--tenant", default=str(DEV_TENANT))
    relay = sub.add_parser("relay")
    relay.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    settings = get_settings()
    if args.cmd == "seed-dev":
        print(json.dumps(seed_dev(), indent=2))
    elif args.cmd == "token":
        print(issue_dev_token(settings, args.subject, uuid.UUID(args.tenant)))
    elif args.cmd == "relay":
        factory, broker = default_session_factory(), LoggingBroker()
        while True:
            if relay_once(factory, broker) == 0:
                time.sleep(args.interval)

"""Operator CLI: astemia seed-dev | token | relay | reminders | serve."""

import argparse
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.broker.base import Broker, LoggingBroker
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
from astemia.workers.reminders import send_reminders

DEV_TENANT = uuid.UUID("0196f1a0-0000-7000-8000-000000000001")


def seed_dev(
    factory: sessionmaker[Session] | None = None, tenant_id: uuid.UUID = DEV_TENANT
) -> dict[str, str]:
    """A synthetic pilot tenant: one hospital, a registrar, two clinicians, a
    nurse, a laboratory scientist, an identity steward, a records clerk, a privacy
    officer and a scheduler, and a teaching hospital to refer to. Synthetic data
    only (CEDA 11.2)."""
    factory = factory or default_session_factory()
    now = datetime.now(UTC)
    ids: dict[str, str] = {"tenant_id": str(tenant_id)}
    with factory() as s, s.begin():
        if s.get(Tenant, tenant_id) is not None:
            raise SystemExit("development tenant already seeded")
        s.add(
            Tenant(
                id=tenant_id,
                name="ASTEMIA Pilot Hospital (synthetic)",
                country_profile="NG",
                created_at=now,
            )
        )
        s.flush()

        def party(kind: str) -> uuid.UUID:
            pid = uuid.uuid7()
            s.add(Party(tenant_id=tenant_id, id=pid, recorded_at=now, party_type=kind))
            s.flush()
            return pid

        def organisation(
            code: str, name: str, kind: str, site_code: str
        ) -> tuple[uuid.UUID, uuid.UUID]:
            org = party("organisation")
            s.add(
                Organisation(
                    tenant_id=tenant_id,
                    id=org,
                    recorded_at=now,
                    organisation_code=code,
                    organisation_name=name,
                    organisation_type=kind,
                )
            )
            site = uuid.uuid7()
            s.flush()
            s.add(
                OrganisationSite(
                    tenant_id=tenant_id,
                    id=site,
                    recorded_at=now,
                    organisation_id=org,
                    site_identifier=site_code,
                    site_name="Main site",
                )
            )
            return org, site

        org, site = organisation(
            "PILOT01", "ASTEMIA Pilot Hospital", "general_hospital", "PILOT01-MAIN"
        )
        _, teaching = organisation(
            "TEACH01",
            "ASTEMIA Teaching Hospital (synthetic)",
            "teaching_hospital",
            "TEACH01-MAIN",
        )
        ids["teaching_facility_id"] = str(teaching)
        ids["organisation_id"], ids["facility_id"] = str(org), str(site)
        people = {
            "registrar": ("Registrar One", ["registrar"]),
            "clinician": ("Dr Clinician One", ["clinician"]),
            "clinician2": ("Dr Clinician Two", ["clinician"]),
            "nurse": ("Nurse One", ["nurse"]),
            "scientist": ("Lab Scientist One", ["lab_scientist"]),
            "steward": ("Identity Steward One", ["identity_steward"]),
            "clerk": ("Records Clerk One", ["records_clerk"]),
            "privacy": ("Privacy Officer One", ["privacy_officer"]),
            "scheduler": ("Scheduler One", ["scheduler"]),
            "radiologist": ("Dr Radiologist One", ["radiologist"]),
            "radiographer": ("Radiographer One", ["radiographer"]),
        }
        for subject, (name, roles) in people.items():
            pid = party("person")
            s.add(
                Practitioner(
                    tenant_id=tenant_id,
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
                    tenant_id=tenant_id,
                    subject=f"{subject}@pilot.astemia.local",
                    practitioner_id=pid,
                    roles=roles,
                    valid_from=now,
                )
            )
            ids[f"{subject}_practitioner_id"] = str(pid)
    return ids


def run_relay(
    factory: sessionmaker[Session],
    broker: Broker,
    interval: float = 1.0,
    max_cycles: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Relay outbox events until stopped; sleeps only when a cycle found nothing.
    Returns the number of events published."""
    published = cycles = 0
    while max_cycles is None or cycles < max_cycles:
        sent = relay_once(factory, broker)
        published += sent
        cycles += 1
        if sent == 0:
            sleep(interval)
    return published


def main(argv: list[str] | None = None, factory: sessionmaker[Session] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="astemia")
    sub = parser.add_subparsers(dest="cmd", required=True)
    seed = sub.add_parser("seed-dev", help="create the synthetic pilot tenant")
    seed.add_argument("--tenant", default=str(DEV_TENANT))
    tok = sub.add_parser("token", help="issue a development bearer token")
    tok.add_argument("subject")
    tok.add_argument("--tenant", default=str(DEV_TENANT))
    relay = sub.add_parser("relay", help="publish outbox events")
    relay.add_argument("--interval", type=float, default=1.0)
    relay.add_argument("--max-cycles", type=int, default=None)
    sub.add_parser("reminders", help="send the Daybook reminders now due")
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.cmd == "seed-dev":
        print(json.dumps(seed_dev(factory, uuid.UUID(args.tenant)), indent=2))
    elif args.cmd == "token":
        print(issue_dev_token(settings, args.subject, uuid.UUID(args.tenant)))
    elif args.cmd == "reminders":
        print(send_reminders(factory or default_session_factory()))
    else:
        run_relay(
            factory or default_session_factory(), LoggingBroker(), args.interval, args.max_cycles
        )

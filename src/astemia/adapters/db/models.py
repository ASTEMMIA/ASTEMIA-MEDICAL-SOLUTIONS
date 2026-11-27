"""Canonical schema for the foundation and the API-03 vertical slice.

CEDA 3.1 envelope on every tenant-owned record; composite primary and foreign
keys always include tenant_id (DATA-01). InnoDB, utf8mb4, strict SQL mode.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import INTEGER, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from astemia.adapters.db.types import BinaryUUID, UTCDateTime

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(referred_table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}
UNSIGNED_INT = INTEGER(unsigned=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def fk(cols: list[str], table: str, ref_cols: list[str] | None = None) -> ForeignKeyConstraint:
    ref = ref_cols or ["tenant_id", "id"]
    return ForeignKeyConstraint(cols, [f"{table}.{c}" for c in ref])


class Envelope:
    """CEDA 3.1 common envelope for tenant-owned records."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    version: Mapped[int] = mapped_column(UNSIGNED_INT, nullable=False, default=1)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    effective_precision: Mapped[str | None] = mapped_column(String(16))
    author_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    author_role: Mapped[str | None] = mapped_column(String(64))
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, default="astemia")
    source_id: Mapped[str | None] = mapped_column(String(128))
    source_status: Mapped[str | None] = mapped_column(String(32))
    sensitivity: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    data_absent_reason: Mapped[str | None] = mapped_column(String(32))


class Coded:
    """Original source coding preserved next to the canonical code (CEDA 3.1)."""

    code_system: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    display: Mapped[str] = mapped_column(String(255), nullable=False)
    original_system: Mapped[str | None] = mapped_column(String(128))
    original_code: Mapped[str | None] = mapped_column(String(64))
    map_version: Mapped[str | None] = mapped_column(String(32))


# --- Tenant ---------------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenant"
    __table_args__ = (TABLE_OPTS,)

    id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country_profile: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class EffectivePeriod:
    """Replaces the ERD's *_History and *_Future tables: one row per version,
    current when effective_from <= now < effective_to (or effective_to NULL)."""

    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime)


# --- Reference codes (ERD: Name Type, Address Type) ----------------------------


class NameType(Base):
    __tablename__ = "name_type"
    __table_args__ = (TABLE_OPTS,)

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    description: Mapped[str] = mapped_column(String(100), nullable=False)


class AddressType(Base):
    __tablename__ = "address_type"
    __table_args__ = (TABLE_OPTS,)

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    description: Mapped[str] = mapped_column(String(100), nullable=False)


# --- Party (ERD: Party, ADDRESS/PARTY, TELECOM COMMUNICATION) ---------------------


class Party(Envelope, Base):
    """Supertype for anyone who can hold an address or telecom. Patient,
    Practitioner, Organisation and AlternativeContact share its primary key."""

    __tablename__ = "party"
    __table_args__ = (fk(["tenant_id"], "tenant", ["id"]), TABLE_OPTS)

    party_type: Mapped[str] = mapped_column(String(16), nullable=False)


class Address(Envelope, Base):
    """ERD ADDRESS / Person_Address (+_History, +_Future); CEDA AddressVersion."""

    __tablename__ = "address"
    __table_args__ = (fk(["tenant_id"], "tenant", ["id"]), TABLE_OPTS)

    address_line1: Mapped[str] = mapped_column(String(100), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(100))
    address_line3: Mapped[str | None] = mapped_column(String(100))
    address_line4: Mapped[str | None] = mapped_column(String(100))
    address_line5: Mapped[str | None] = mapped_column(String(100))
    address_line6: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(64))
    local_government_area: Mapped[str | None] = mapped_column(String(64))
    postcode: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    paf_key: Mapped[str | None] = mapped_column(String(32))
    address_description: Mapped[str | None] = mapped_column(String(255))
    gazetteer_source: Mapped[str | None] = mapped_column(String(32))
    gazetteer_version: Mapped[str | None] = mapped_column(String(32))


class PartyAddress(Envelope, EffectivePeriod, Base):
    """ERD ADDRESS/PARTY (Address No, Person ID, Organisation ID) with type and period."""

    __tablename__ = "party_address"
    __table_args__ = (
        fk(["tenant_id", "party_id"], "party"),
        fk(["tenant_id", "address_id"], "address"),
        fk(["address_type"], "address_type", ["code"]),
        Index(None, "tenant_id", "party_id", "address_type", "effective_from"),
        TABLE_OPTS,
    )

    party_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    address_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    address_type: Mapped[str] = mapped_column(String(16), nullable=False)


class Telecom(Envelope, EffectivePeriod, Base):
    """ERD Person_Telecom (+_History, +_Future), Alt_Cont_Telecom, TELECOM COMMUNICATION."""

    __tablename__ = "telecom"
    __table_args__ = (
        fk(["tenant_id", "party_id"], "party"),
        fk(["tenant_id", "service_provider_id"], "service_provider"),
        Index(None, "tenant_id", "party_id", "telecom_address_type"),
        TABLE_OPTS,
    )

    party_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    telecom_address_type: Mapped[str] = mapped_column(String(16), nullable=False)
    telecom_address: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(100))
    service_provider_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    use: Mapped[str | None] = mapped_column(String(16))


# --- Directory (ERD: ORGANISATION, ORGANISATION SITE, DEPARTMENT, ROLE PROFILE,
#     HealthProfessional, Care Provision, ORGANISATION PERSON, WORKGROUP TEAM*) -----


class Organisation(Envelope, Base):
    __tablename__ = "organisation"
    __table_args__ = (
        fk(["tenant_id", "id"], "party"),
        UniqueConstraint("tenant_id", "organisation_code"),
        TABLE_OPTS,
    )

    organisation_code: Mapped[str] = mapped_column(String(32), nullable=False)
    organisation_name: Mapped[str] = mapped_column(String(200), nullable=False)
    organisation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    open_date: Mapped[date | None] = mapped_column(Date)
    close_date: Mapped[date | None] = mapped_column(Date)


class OrganisationSite(Envelope, Base):
    """ERD ORGANISATION SITE. The care setting an encounter happens at (CEDA facility)."""

    __tablename__ = "organisation_site"
    __table_args__ = (
        fk(["tenant_id", "organisation_id"], "organisation"),
        UniqueConstraint("tenant_id", "site_identifier"),
        TABLE_OPTS,
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    site_identifier: Mapped[str] = mapped_column(String(32), nullable=False)
    site_name: Mapped[str] = mapped_column(String(200), nullable=False)


class Department(Envelope, Base):
    __tablename__ = "department"
    __table_args__ = (
        fk(["tenant_id", "organisation_id"], "organisation"),
        fk(["tenant_id", "site_id"], "organisation_site"),
        UniqueConstraint("tenant_id", "organisation_id", "department_code"),
        TABLE_OPTS,
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    department_code: Mapped[str] = mapped_column(String(32), nullable=False)
    department_name: Mapped[str] = mapped_column(String(200), nullable=False)


class RoleProfile(Envelope, Base):
    __tablename__ = "role_profile"
    __table_args__ = (
        fk(["tenant_id", "organisation_id"], "organisation"),
        fk(["tenant_id", "department_id"], "department"),
        TABLE_OPTS,
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    job_role: Mapped[str] = mapped_column(String(100), nullable=False)
    business_functions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    area_of_work: Mapped[str | None] = mapped_column(String(100))
    speciality_area: Mapped[str | None] = mapped_column(String(100))


class Practitioner(Envelope, Base):
    """ERD HealthProfessional / AHIS Healthcare Professional. Logon name, password,
    smart-card and FortiToken credentials stay in the identity provider;
    Membership.subject links them. Age is derived from birth_date, not stored."""

    __tablename__ = "practitioner"
    __table_args__ = (
        fk(["tenant_id", "id"], "party"),
        UniqueConstraint("tenant_id", "professional_id"),
        TABLE_OPTS,
    )

    professional_id: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    family_name: Mapped[str | None] = mapped_column(String(100))
    given_name: Mapped[str | None] = mapped_column(String(100))
    professional_register: Mapped[str | None] = mapped_column(String(32))
    registration_number: Mapped[str | None] = mapped_column(String(64))
    specialist_area: Mapped[str | None] = mapped_column(String(100))
    birth_date: Mapped[date | None] = mapped_column(Date)
    administrative_sex: Mapped[str | None] = mapped_column(String(16))
    authorisation_status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    registered_date: Mapped[date | None] = mapped_column(Date)


class PractitionerRole(Envelope, EffectivePeriod, Base):
    """ERD ORGANISATION PERSON + Care Provision links."""

    __tablename__ = "practitioner_role"
    __table_args__ = (
        fk(["tenant_id", "practitioner_id"], "practitioner"),
        fk(["tenant_id", "organisation_id"], "organisation"),
        fk(["tenant_id", "role_profile_id"], "role_profile"),
        TABLE_OPTS,
    )

    practitioner_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    organisation_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    role_profile_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)


class WorkgroupTeam(Envelope, EffectivePeriod, Base):
    __tablename__ = "workgroup_team"
    __table_args__ = (
        fk(["tenant_id", "organisation_id"], "organisation"),
        UniqueConstraint("tenant_id", "workgroup_identifier"),
        TABLE_OPTS,
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    workgroup_identifier: Mapped[str] = mapped_column(String(32), nullable=False)
    workgroup_name: Mapped[str] = mapped_column(String(200), nullable=False)


class WorkgroupTeamMembership(Envelope, EffectivePeriod, Base):
    __tablename__ = "workgroup_team_membership"
    __table_args__ = (
        fk(["tenant_id", "workgroup_id"], "workgroup_team"),
        fk(["tenant_id", "practitioner_id"], "practitioner"),
        TABLE_OPTS,
    )

    workgroup_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    practitioner_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    membership_name: Mapped[str | None] = mapped_column(String(100))
    membership_group: Mapped[str | None] = mapped_column(String(100))


class WorkgroupTeamService(Envelope, EffectivePeriod, Base):
    __tablename__ = "workgroup_team_service"
    __table_args__ = (
        fk(["tenant_id", "workgroup_id"], "workgroup_team"),
        fk(["tenant_id", "role_profile_id"], "role_profile"),
        TABLE_OPTS,
    )

    workgroup_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    role_profile_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)


class BusinessService(Envelope, Base):
    """ERD BUSINESS (CLINICAL) SERVICE."""

    __tablename__ = "business_service"
    __table_args__ = (
        fk(["tenant_id"], "tenant", ["id"]),
        UniqueConstraint("tenant_id", "service_code"),
        TABLE_OPTS,
    )

    service_code: Mapped[str] = mapped_column(String(32), nullable=False)
    service_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_bag: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class BusinessAction(Envelope, Base):
    __tablename__ = "business_action"
    __table_args__ = (
        fk(["tenant_id", "business_service_id"], "business_service"),
        UniqueConstraint("tenant_id", "action_identifier"),
        TABLE_OPTS,
    )

    business_service_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    action_identifier: Mapped[str] = mapped_column(String(64), nullable=False)
    action_name: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(500), nullable=False)


class MessagingContract(Envelope, Base):
    """ERD MESSAGING CONTRACT PROPERTIES (ebXML-style collaboration agreement)."""

    __tablename__ = "messaging_contract"
    __table_args__ = (
        fk(["tenant_id", "business_action_id"], "business_action"),
        UniqueConstraint("tenant_id", "cpa_id"),
        TABLE_OPTS,
    )

    business_action_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    cpa_id: Mapped[str] = mapped_column(String(64), nullable=False)
    is_authenticated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    persist_duration_s: Mapped[int | None] = mapped_column(Integer)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_interval_s: Mapped[int | None] = mapped_column(Integer)
    sync_reply_mode: Mapped[str | None] = mapped_column(String(32))
    ack_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_elimination: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    actor: Mapped[str | None] = mapped_column(String(100))


class ItProduct(Envelope, Base):
    """AMS master ERD PRODUCT: an accredited IT product."""

    __tablename__ = "it_product"
    __table_args__ = (
        fk(["tenant_id"], "tenant", ["id"]),
        UniqueConstraint("tenant_id", "product_code"),
        TABLE_OPTS,
    )

    product_code: Mapped[str] = mapped_column(String(32), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_description: Mapped[str | None] = mapped_column(String(1000))
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False)
    accredited_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ServiceProvider(Envelope, EffectivePeriod, Base):
    """AMS master ERD IT SERVICE and TELECOM SERVICE PROVIDER: accredited providers
    of IT and telecom services, with the product they supply."""

    __tablename__ = "service_provider"
    __table_args__ = (
        fk(["tenant_id", "product_id"], "it_product"),
        UniqueConstraint("tenant_id", "provider_kind", "medicare_it_code"),
        TABLE_OPTS,
    )

    provider_kind: Mapped[str] = mapped_column(String(8), nullable=False)  # it | telecom
    provider_name: Mapped[str] = mapped_column(String(200), nullable=False)
    network_provider_name: Mapped[str | None] = mapped_column(String(200))
    communication_type: Mapped[str | None] = mapped_column(String(32))
    medicare_it_code: Mapped[str] = mapped_column(String(32), nullable=False)
    medicare_it_name: Mapped[str | None] = mapped_column(String(200))
    practice_code: Mapped[str | None] = mapped_column(String(32))
    product_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False)
    accredited_status: Mapped[str | None] = mapped_column(String(16))
    accredited_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Membership(Base):
    """Effective membership binds a verified subject to a tenant (API-01)."""

    __tablename__ = "membership"
    __table_args__ = (
        fk(["tenant_id"], "tenant", ["id"]),
        fk(["tenant_id", "practitioner_id"], "practitioner"),
        TABLE_OPTS,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    practitioner_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime)


# --- Identity register (ERD: Person, Patient / Service User, Name, Person Name,
#     Disability_Code, Primary_Care, Nominated_Pharmacy, Alternative_Contact,
#     CONSENT, Duplicates, Manage_Trans, Transaction) ----------------------------------


class Patient(Envelope, Base):
    """ERD Person + Patient / Service User. Names, identifiers, addresses and
    telecoms are effective-dated child rows; the national number is never a key."""

    __tablename__ = "patient"
    __table_args__ = (fk(["tenant_id", "id"], "party"), TABLE_OPTS)

    administrative_sex: Mapped[str] = mapped_column(String(16), nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    birth_date_precision: Mapped[str] = mapped_column(String(8), nullable=False)
    birth_time: Mapped[str | None] = mapped_column(String(8))
    death_date: Mapped[date | None] = mapped_column(Date)
    death_date_precision: Mapped[str | None] = mapped_column(String(8))
    death_time: Mapped[str | None] = mapped_column(String(8))
    death_notification_status: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    national_status: Mapped[str | None] = mapped_column(String(16))
    suppress_data_indicator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidentiality: Mapped[str | None] = mapped_column(String(16))
    preferred_language: Mapped[str | None] = mapped_column(String(8))
    interpreter_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    communication_contact_method: Mapped[str | None] = mapped_column(String(16))
    preferred_contact_times: Mapped[str | None] = mapped_column(String(100))
    call_centre_consent: Mapped[bool | None] = mapped_column(Boolean)
    stop_note_indicator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registration_date: Mapped[date | None] = mapped_column(Date)
    initial_registration_source: Mapped[str | None] = mapped_column(String(32))
    registering_authority_type: Mapped[str | None] = mapped_column(String(16))
    registering_organisation_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    registering_practitioner_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    date_of_exit: Mapped[date | None] = mapped_column(Date)
    administrative_comment: Mapped[str | None] = mapped_column(String(1000))
    # AHIS Person Name: parents' names, used for identity verification.
    mother_name: Mapped[str | None] = mapped_column(String(200))
    father_name: Mapped[str | None] = mapped_column(String(200))
    ethnic_category: Mapped[str | None] = mapped_column(String(16))
    marital_status: Mapped[str | None] = mapped_column(String(16))
    state_of_origin: Mapped[str | None] = mapped_column(String(64))
    carer_support_indicator: Mapped[str | None] = mapped_column(String(8))


class PersonName(Envelope, EffectivePeriod, Base):
    """ERD Name / Name_History / Person Name (ZETTER, AHIS). Maiden, preferred and
    alias names are name_type rows."""

    __tablename__ = "person_name"
    __table_args__ = (
        fk(["tenant_id", "party_id"], "party"),
        fk(["name_type"], "name_type", ["code"]),
        Index(None, "tenant_id", "family_name", "given_name"),
        Index(None, "tenant_id", "family_name_phonetic"),
        TABLE_OPTS,
    )

    party_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    name_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str | None] = mapped_column(String(32))
    family_name: Mapped[str] = mapped_column(String(100), nullable=False)
    given_name: Mapped[str] = mapped_column(String(100), nullable=False)
    other_given_name: Mapped[str | None] = mapped_column(String(200))
    suffix: Mapped[str | None] = mapped_column(String(32))
    family_name_phonetic: Mapped[str | None] = mapped_column(String(32))
    given_name_phonetic: Mapped[str | None] = mapped_column(String(32))
    other_given_name_phonetic: Mapped[str | None] = mapped_column(String(64))


class PatientIdentifier(Envelope, Base):
    """ERD medicare_number / NIN (was nhs_number) / old_style_* / Local Patient Identifier.

    Unique (tenant, issuer, value) while active: active_marker is 1 for an active
    binding and NULL otherwise, and InnoDB unique indexes admit many NULLs.
    """

    __tablename__ = "patient_identifier"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        UniqueConstraint("tenant_id", "issuer", "value", "active_marker"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    issuer: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(64), nullable=False)
    identifier_type: Mapped[str] = mapped_column(String(16), nullable=False, default="current")
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    active_marker: Mapped[int | None] = mapped_column(TINYINT)  # always set explicitly


class PatientDisability(Envelope, EffectivePeriod, Base):
    """ERD Disability_Code (+_History) and Alt_Cont_Disability_Code (+_History, +_Future)."""

    __tablename__ = "party_disability"
    __table_args__ = (fk(["tenant_id", "party_id"], "party"), TABLE_OPTS)

    party_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    code_system: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)


class PrimaryCareRegistration(Envelope, EffectivePeriod, Base):
    """ERD Primary_Care (+_History, +_Future) and the registered doctor fields."""

    __tablename__ = "primary_care_registration"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "practice_organisation_id"], "organisation"),
        fk(["tenant_id", "registered_practitioner_id"], "practitioner"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    primary_care_type: Mapped[str] = mapped_column(String(16), nullable=False)
    practice_code: Mapped[str] = mapped_column(String(32), nullable=False)
    practice_organisation_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    registered_practitioner_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)


class NominatedPharmacy(Envelope, EffectivePeriod, Base):
    """ERD Nominated_Pharmacy (+_History)."""

    __tablename__ = "nominated_pharmacy"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "pharmacy_organisation_id"], "organisation"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    nominated_pharmacy_type: Mapped[str] = mapped_column(String(16), nullable=False)
    nominated_pharmacy_code: Mapped[str] = mapped_column(String(32), nullable=False)
    pharmacy_organisation_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)


class AlternativeContact(Envelope, EffectivePeriod, Base):
    """ERD Alternative_Contact (+_History, +_Future), Contact and Person/Person.
    Shares its key with Party so its addresses, telecoms and disabilities attach
    the same way as the patient's."""

    __tablename__ = "alternative_contact"
    __table_args__ = (
        fk(["tenant_id", "id"], "party"),
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "related_patient_id"], "patient"),
        Index(None, "tenant_id", "patient_id", "precedence"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(32))
    family_name: Mapped[str] = mapped_column(String(100), nullable=False)
    given_name: Mapped[str] = mapped_column(String(100), nullable=False)
    other_given_name: Mapped[str | None] = mapped_column(String(200))
    suffix: Mapped[str | None] = mapped_column(String(32))
    related_patient_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    contact_identifier_issuer: Mapped[str | None] = mapped_column(String(32))
    contact_identifier_value: Mapped[str | None] = mapped_column(String(64))
    copy_correspondence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    language: Mapped[str | None] = mapped_column(String(8))
    precedence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    contact_method: Mapped[str | None] = mapped_column(String(16))
    authorised_by: Mapped[str | None] = mapped_column(String(100))


class GuardianAuthority(Envelope, EffectivePeriod, Base):
    """CEDA GuardianAuthority (AM-PDI-006): what a representative may do."""

    __tablename__ = "guardian_authority"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "representative_id"], "alternative_contact"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    representative_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    basis: Mapped[str] = mapped_column(String(32), nullable=False)
    permitted_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(String(255))
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Consent(Envelope, EffectivePeriod, Base):
    """ERD CONSENT / CONSENT_HISTORY; CEDA Consent/Objection. Each change is a new
    row that supersedes the previous one. The demographic copies the ERD carries
    on CONSENT are not repeated: they are read from the patient."""

    __tablename__ = "consent"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "supersedes_id"], "consent"),
        fk(["tenant_id", "representative_id"], "alternative_contact"),
        Index(None, "tenant_id", "patient_id", "consent_type"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    consent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="record")
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    legal_basis: Mapped[str | None] = mapped_column(String(64))
    consent_status: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(8), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    identity_confirmation: Mapped[str | None] = mapped_column(String(32))
    consent_comment: Mapped[str | None] = mapped_column(String(1000))
    given_by_relationship: Mapped[str] = mapped_column(String(32), nullable=False, default="self")
    representative_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)


class DuplicateCandidate(Envelope, Base):
    """ERD Duplicates: suspected duplicate pairs awaiting steward review."""

    __tablename__ = "duplicate_candidate"
    __table_args__ = (
        fk(["tenant_id", "record1_id"], "patient"),
        fk(["tenant_id", "record2_id"], "patient"),
        UniqueConstraint("tenant_id", "record1_id", "record2_id"),
        TABLE_OPTS,
    )

    record1_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    record2_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    weighting: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolution: Mapped[str | None] = mapped_column(String(16))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    # Identity review task (WF01): why the pair was raised, where, and the notes
    # of the registrar and the steward.
    reasons: Mapped[list[str] | None] = mapped_column(JSON)
    origin: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(String(500))


class MergeLink(Envelope, Base):
    """ERD Manage_Trans (retained/discarded/unmerged); CEDA MergeLink (E3)."""

    __tablename__ = "merge_link"
    __table_args__ = (
        fk(["tenant_id", "prior_id"], "patient"),
        fk(["tenant_id", "survivor_id"], "patient"),
        fk(["tenant_id", "reviewer_id"], "practitioner"),
        Index(None, "tenant_id", "prior_id"),
        TABLE_OPTS,
    )

    prior_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    survivor_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reconciliation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )


class EmergencyGrant(Envelope, Base):
    """CEDA SA-04 EmergencyGrant (SEC-04, WF02 step 4): time-boxed, read-only
    access to one patient's chart for a practitioner with no care relationship,
    with a recorded purpose and a privacy review."""

    __tablename__ = "emergency_grant"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "practitioner_id"], "practitioner"),
        fk(["tenant_id", "reviewed_by_id"], "practitioner"),
        Index(None, "tenant_id", "practitioner_id", "patient_id", "expires_at"),
        Index(None, "tenant_id", "reviewed_at", "review_due_at"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    practitioner_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    step_up: Mapped[str] = mapped_column(String(16), nullable=False)
    review_due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    review_outcome: Mapped[str | None] = mapped_column(String(16))
    review_note: Mapped[str | None] = mapped_column(String(500))


class Slot(Envelope, Base):
    """CEDA SA-05 Slot (UG01): a bookable period for one clinician, service and
    site. Available, held or booked is derived from its holds and appointments."""

    __tablename__ = "slot"
    __table_args__ = (
        fk(["tenant_id", "facility_id"], "organisation_site"),
        fk(["tenant_id", "practitioner_id"], "practitioner"),
        fk(["tenant_id", "clinical_service_id"], "clinical_service"),
        UniqueConstraint("tenant_id", "practitioner_id", "starts_at"),
        Index(None, "tenant_id", "facility_id", "starts_at"),
        Index(None, "tenant_id", "service", "starts_at"),
        TABLE_OPTS,
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    practitioner_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    clinical_service_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    slot_type: Mapped[str] = mapped_column(String(16), nullable=False)
    modality: Mapped[str] = mapped_column(String(16), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)


class SlotHold(Envelope, Base):
    """CEDA SA-05 SlotHold: a short reservation that expires on the server.
    live_marker is 1 until the hold is confirmed, released or found expired,
    so the unique key allows one live hold per slot."""

    __tablename__ = "slot_hold"
    __table_args__ = (
        fk(["tenant_id", "slot_id"], "slot"),
        UniqueConstraint("tenant_id", "slot_id", "live_marker"),
        TABLE_OPTS,
    )

    slot_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    holder_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    outcome: Mapped[str | None] = mapped_column(String(16))
    live_marker: Mapped[int | None] = mapped_column(TINYINT)  # always set explicitly


class Referral(Envelope, Base):
    """CEDA SA-05 Referral (HS05, WF06): submitted, accepted or rejected,
    scheduled and closed. Booking is a separate record linked to it."""

    __tablename__ = "referral"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "referrer_id"], "practitioner"),
        fk(["tenant_id", "decided_by_id"], "practitioner"),
        fk(["tenant_id", "source_encounter_id"], "encounter"),
        fk(["tenant_id", "referring_facility_id"], "organisation_site"),
        fk(["tenant_id", "receiving_facility_id"], "organisation_site"),
        Index(None, "tenant_id", "receiving_service", "status"),
        Index(None, "tenant_id", "patient_id"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    referrer_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    # The care episode whose records go with the referral. A patient with no
    # care records cannot be referred (CEDA revision 1.5, HS05).
    source_encounter_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    requesting_service: Mapped[str | None] = mapped_column(String(64))
    receiving_service: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    # From where to where, and at what level of care (CEDA revision 1.5). Required
    # by the API; nullable only so the columns could be added to a live table.
    referring_facility_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    receiving_facility_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    referring_level: Mapped[str | None] = mapped_column(String(32))
    receiving_level: Mapped[str | None] = mapped_column(String(32))
    records_count: Mapped[int | None] = mapped_column(Integer)


class ReferralRecord(Base):
    """The patient's historical records that travel with a referral, fixed when
    it is submitted. Mandatory: a referral always carries every encounter,
    order and diagnostic report of the patient (CEDA revision 1.5)."""

    __tablename__ = "referral_record"
    __table_args__ = (
        fk(["tenant_id", "referral_id"], "referral"),
        UniqueConstraint("tenant_id", "referral_id", "record_type", "record_id"),
        TABLE_OPTS,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    referral_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class Appointment(Envelope, Base):
    """CEDA SA-05 Appointment (UG01, HS04). booked_marker is 1 while booked,
    so the unique key allows one booked appointment per slot. A reschedule
    ends this appointment and books a new one that points back to it."""

    __tablename__ = "appointment"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "slot_id"], "slot"),
        fk(["tenant_id", "referral_id"], "referral"),
        fk(["tenant_id", "rescheduled_from_id"], "appointment"),
        fk(["tenant_id", "encounter_id"], "encounter"),
        UniqueConstraint("tenant_id", "slot_id", "booked_marker"),
        Index(None, "tenant_id", "patient_id"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    slot_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    referral_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    booked_marker: Mapped[int | None] = mapped_column(TINYINT)  # always set explicitly
    reason: Mapped[str | None] = mapped_column(String(500))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class MentalHealthLegalStatus(Envelope, Base):
    """A patient's legal status under mental health law, with its history
    (ICRS 5.5.9). current_marker is 1 on the status in force, so the unique key
    allows one current status per patient; a change ends the previous one."""

    __tablename__ = "mental_health_legal_status"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "authorised_by_id"], "practitioner"),
        UniqueConstraint("tenant_id", "patient_id", "current_marker"),
        Index(None, "tenant_id", "valid_until"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    legal_basis: Mapped[str | None] = mapped_column(String(100))
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    authorised_by_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    current_marker: Mapped[int | None] = mapped_column(TINYINT)  # always set explicitly


class RestrictiveIntervention(Envelope, Base):
    """Restraint, seclusion or rapid tranquillisation (HS13, B11). Entries are
    never edited or deleted: an end time is recorded once, and a safeguarding
    lead who took no part reviews each one."""

    __tablename__ = "restrictive_intervention"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "encounter_id"], "encounter"),
        fk(["tenant_id", "authorised_by_id"], "practitioner"),
        fk(["tenant_id", "reviewed_by_id"], "practitioner"),
        fk(["tenant_id", "legal_status_id"], "mental_health_legal_status"),
        Index(None, "tenant_id", "patient_id", "started_at"),
        Index(None, "tenant_id", "reviewed_at", "review_due_at"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    intervention_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    authorised_by_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    staff_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    injury: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    injury_detail: Mapped[str | None] = mapped_column(String(500))
    debrief_offered: Mapped[bool | None] = mapped_column(Boolean)
    # The legal status in force when it happened, and why it needs a closer look.
    legal_status_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    flags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    review_due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    review_outcome: Mapped[str | None] = mapped_column(String(16))
    review_note: Mapped[str | None] = mapped_column(String(1000))


class SafeguardingConcern(Envelope, Base):
    """A concern about how a patient is treated, from the patient, their
    family, an advocate or staff, answered by a safeguarding lead."""

    __tablename__ = "safeguarding_concern"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "about_practitioner_id"], "practitioner"),
        fk(["tenant_id", "closed_by_id"], "practitioner"),
        Index(None, "tenant_id", "status", "respond_by"),
        Index(None, "tenant_id", "patient_id"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    raised_by: Mapped[str] = mapped_column(String(16), nullable=False)
    raised_by_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    about_practitioner_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    respond_by: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    outcome_note: Mapped[str | None] = mapped_column(String(1000))


class DemographicTransaction(Base):
    """ERD Transaction: provenance of every demographic change (source, delta,
    reason, validation level). Holds field names and codes, not clinical text."""

    __tablename__ = "demographic_transaction"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        Index(None, "tenant_id", "patient_id", "transaction_at"),
        TABLE_OPTS,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    transaction_source: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    delta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    change_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    source_validation_level: Mapped[str | None] = mapped_column(String(16))
    country_of_transaction: Mapped[str] = mapped_column(String(2), nullable=False)
    transaction_user: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)


class LegitimateRelationship(Envelope, Base):
    """ERD Legitmate Relationship: the relationship that grants clinical access
    to a chart, held by a practitioner or a whole workgroup team."""

    __tablename__ = "legitimate_relationship"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "practitioner_id"], "practitioner"),
        fk(["tenant_id", "workgroup_id"], "workgroup_team"),
        fk(["tenant_id", "encounter_id"], "encounter"),
        fk(["tenant_id", "created_by_id"], "practitioner"),
        Index(None, "tenant_id", "practitioner_id", "patient_id"),
        Index(None, "tenant_id", "workgroup_id", "patient_id"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    practitioner_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    workgroup_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    creation_reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    creation_reason_text: Mapped[str | None] = mapped_column(String(255))
    termination_reason_code: Mapped[str | None] = mapped_column(String(32))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)


class CareProvision(Envelope, Base):
    """ERD Care Provision (ZETTER, AHIS): a professional providing care to a
    patient from an effective date and time, within a specialist area."""

    __tablename__ = "care_provision"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "practitioner_id"], "practitioner"),
        fk(["tenant_id", "legitimate_relationship_id"], "legitimate_relationship"),
        Index(None, "tenant_id", "patient_id"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    practitioner_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    legitimate_relationship_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    specialist_area: Mapped[str | None] = mapped_column(String(100))
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


# --- Service catalogue (AMS-002 Annex A15-A16, CAT-01..05) ----------------------


class ServiceTemplateGroup(Base):
    """ASTEMIA standard department group (D01-D36 from Annex A15, D37+ ASTEMIA
    extensions). Global reference data; tenants instantiate from it."""

    __tablename__ = "service_template_group"
    __table_args__ = (TABLE_OPTS,)

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    division: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    workflow: Mapped[str] = mapped_column(String(1000), nullable=False)
    requirement_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    canonical_records: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    security_checks: Mapped[str] = mapped_column(String(1000), nullable=False)
    acceptance: Mapped[str] = mapped_column(String(1000), nullable=False)
    directory_a_positions: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    catalogue_version: Mapped[str] = mapped_column(String(16), nullable=False)


class ServiceTemplate(Base):
    __tablename__ = "service_template"
    __table_args__ = (fk(["group_code"], "service_template_group", ["code"]), TABLE_OPTS)

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    group_code: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    age_policy: Mapped[str] = mapped_column(String(12), nullable=False)
    care_settings: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class ServiceDirectoryListing(Base):
    """Public services A-Z directory listings mapped to catalogue services
    (directories A and B of the Astemia Medical Solutions for Integrated Care
    Records Service). Listing names become search aliases when a tenant
    provisions the catalogue (CAT-02)."""

    __tablename__ = "service_directory_listing"
    __table_args__ = (fk(["service_code"], "service_template", ["code"]), TABLE_OPTS)

    directory: Mapped[str] = mapped_column(String(16), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    service_code: Mapped[str] = mapped_column(String(12), nullable=False)
    snapshot: Mapped[date] = mapped_column(Date, nullable=False)


class OrgUnit(Envelope, EffectivePeriod, Base):
    """Division, department and subdepartment hierarchy. Parents are in the same
    tenant (composite FK); cycles are rejected by the catalogue command."""

    __tablename__ = "org_unit"
    __table_args__ = (
        fk(["tenant_id"], "tenant", ["id"]),
        fk(["tenant_id", "parent_id"], "org_unit"),
        UniqueConstraint("tenant_id", "code"),
        TABLE_OPTS,
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)


class ClinicalService(Envelope, EffectivePeriod, Base):
    __tablename__ = "clinical_service"
    __table_args__ = (
        fk(["tenant_id", "department_id"], "org_unit"),
        fk(["tenant_id", "owner_id"], "practitioner"),
        fk(["template_code"], "service_template", ["code"]),
        UniqueConstraint("tenant_id", "code"),
        Index(None, "tenant_id", "status"),
        TABLE_OPTS,
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    template_code: Mapped[str | None] = mapped_column(String(12))
    age_policy: Mapped[str] = mapped_column(String(12), nullable=False)
    care_settings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)  # draft | active | retired
    owner_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    description: Mapped[str | None] = mapped_column(String(1000))


class ServiceAlias(Envelope, Base):
    __tablename__ = "service_alias"
    __table_args__ = (
        fk(["tenant_id", "service_id"], "clinical_service"),
        UniqueConstraint("tenant_id", "alias", "service_id"),
        Index(None, "tenant_id", "alias"),
        TABLE_OPTS,
    )

    service_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FacilityService(Envelope, EffectivePeriod, Base):
    """Where a service is offered, in which care settings and for which ages."""

    __tablename__ = "facility_service"
    __table_args__ = (
        fk(["tenant_id", "service_id"], "clinical_service"),
        fk(["tenant_id", "facility_id"], "organisation_site"),
        UniqueConstraint("tenant_id", "service_id", "facility_id"),
        TABLE_OPTS,
    )

    service_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    care_settings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accepts_referrals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    contact_channel: Mapped[str | None] = mapped_column(String(100))


class WorkQueue(Envelope, Base):
    __tablename__ = "work_queue"
    __table_args__ = (
        fk(["tenant_id", "service_id"], "clinical_service"),
        fk(["tenant_id", "facility_id"], "organisation_site"),
        UniqueConstraint("tenant_id", "code"),
        TABLE_OPTS,
    )

    service_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    eligible_roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    accepting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ServiceChange(Base):
    """Catalogue change provenance (Annex A16 ServiceChange and Provenance)."""

    __tablename__ = "service_change"
    __table_args__ = (
        fk(["tenant_id"], "tenant", ["id"]),
        Index(None, "tenant_id", "recorded_at"),
        TABLE_OPTS,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    service_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    requester: Mapped[str] = mapped_column(String(255), nullable=False)
    approver: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(12))
    new_status: Mapped[str | None] = mapped_column(String(12))
    catalogue_version: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)


# --- Encounter ----------------------------------------------------------------


class Encounter(Envelope, Base):
    __tablename__ = "encounter"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "facility_id"], "organisation_site"),
        fk(["tenant_id", "responsible_practitioner_id"], "practitioner"),
        fk(["tenant_id", "clinical_service_id"], "clinical_service"),
        UniqueConstraint("tenant_id", "visit_authority", "visit_number"),
        Index(None, "tenant_id", "patient_id"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    responsible_practitioner_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    visit_authority: Mapped[str] = mapped_column(String(64), nullable=False)
    visit_number: Mapped[str] = mapped_column(String(64), nullable=False)
    encounter_class: Mapped[str] = mapped_column(String(16), nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    clinical_service_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    admission_route: Mapped[str | None] = mapped_column(String(32))
    administrative_category: Mapped[str | None] = mapped_column(String(8))
    specialty_function_code: Mapped[str | None] = mapped_column(String(8))
    commissioner_code: Mapped[str | None] = mapped_column(String(32))
    disposition: Mapped[str | None] = mapped_column(String(32))
    period_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    period_end: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AeAttendance(Envelope, Base):
    """A&E attendance detail for an emergency encounter (AE_AMS STG_010_AE_TRANSACTION,
    AHIS AE_TRANSACTION, ZETTER AE_* fields; Annex A HS02 / WF02)."""

    __tablename__ = "ae_attendance"
    __table_args__ = (
        fk(["tenant_id", "encounter_id"], "encounter"),
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "staff_member_id"], "practitioner"),
        UniqueConstraint("tenant_id", "encounter_id"),
        UniqueConstraint("tenant_id", "attendance_number"),
        TABLE_OPTS,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    attendance_number: Mapped[str] = mapped_column(String(32), nullable=False)
    arrival_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    attendance_category: Mapped[str] = mapped_column(String(8), nullable=False)
    patient_group: Mapped[str | None] = mapped_column(String(8))
    referral_source: Mapped[str | None] = mapped_column(String(8))
    incident_location_type: Mapped[str | None] = mapped_column(String(8))
    arrival_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    initial_assessment_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    seen_for_treatment_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    conclusion_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    departure_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attendance_disposal: Mapped[str | None] = mapped_column(String(8))
    staff_member_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    staff_member_code: Mapped[str | None] = mapped_column(String(32))


class EncounterCoding(Envelope, Base):
    """Sequenced diagnoses, investigations and treatments/procedures for an
    encounter (STG_999_COM_DIAG, STG_999_COM_CE_PROC; A+E Diagnosis/Investigation/
    Treatment - First, Second...; APC and Outpatient procedure/diagnosis lists)."""

    __tablename__ = "encounter_coding"
    __table_args__ = (
        fk(["tenant_id", "encounter_id"], "encounter"),
        fk(["tenant_id", "patient_id"], "patient"),
        UniqueConstraint("tenant_id", "encounter_id", "kind", "sequence_no"),
        TABLE_OPTS,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # diagnosis|investigation|procedure
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    code_scheme: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    planned_or_performed: Mapped[str | None] = mapped_column(String(1))
    performed_on: Mapped[date | None] = mapped_column(Date)
    original_scheme: Mapped[str | None] = mapped_column(String(32))
    original_code: Mapped[str | None] = mapped_column(String(32))
    map_version: Mapped[str | None] = mapped_column(String(32))


class EncounterCopyRecipient(Envelope, Base):
    """STG_999_ALL_COPY_RECIPIENT: organisations that receive a copy of the record."""

    __tablename__ = "encounter_copy_recipient"
    __table_args__ = (
        fk(["tenant_id", "encounter_id"], "encounter"),
        UniqueConstraint("tenant_id", "encounter_id", "sequence_no"),
        TABLE_OPTS,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    organisation_code: Mapped[str] = mapped_column(String(32), nullable=False)
    organisation_code_type: Mapped[str | None] = mapped_column(String(8))
    outbound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# --- Diagnostics --------------------------------------------------------------


class ServiceRequest(Envelope, Coded, Base):
    __tablename__ = "service_request"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "encounter_id"], "encounter"),
        fk(["tenant_id", "requester_id"], "practitioner"),
        fk(["tenant_id", "result_owner_id"], "practitioner"),
        fk(["tenant_id", "backup_owner_id"], "practitioner"),
        UniqueConstraint("tenant_id", "placer_authority", "placer_id"),
        UniqueConstraint("tenant_id", "filler_authority", "filler_id"),
        Index(None, "tenant_id", "patient_id"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    encounter_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    result_owner_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    backup_owner_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    placer_authority: Mapped[str] = mapped_column(String(64), nullable=False)
    placer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    filler_authority: Mapped[str | None] = mapped_column(String(64))
    filler_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    clinical_note: Mapped[str | None] = mapped_column(String(1000))


class DiagnosticReport(Envelope, Base):
    __tablename__ = "diagnostic_report"
    __table_args__ = (
        fk(["tenant_id", "service_request_id"], "service_request"),
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "released_by_id"], "practitioner"),
        fk(["tenant_id", "prior_report_id"], "diagnostic_report"),
        Index(None, "tenant_id", "patient_id"),
        TABLE_OPTS,
    )

    service_request_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    released_by_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    released_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    portal_release: Mapped[str] = mapped_column(String(16), nullable=False, default="withheld")
    prior_report_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    conclusion: Mapped[str | None] = mapped_column(String(2000))


class Observation(Envelope, Coded, Base):
    """Current pointer; values live in append-only ObservationRevision rows."""

    __tablename__ = "observation"
    __table_args__ = (
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "service_request_id"], "service_request"),
        UniqueConstraint("tenant_id", "service_request_id", "code_system", "code"),
        TABLE_OPTS,
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    service_request_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    current_revision: Mapped[int] = mapped_column(UNSIGNED_INT, nullable=False)


class ObservationRevision(Base):
    __tablename__ = "observation_revision"
    __table_args__ = (
        fk(["tenant_id", "observation_id"], "observation"),
        fk(["tenant_id", "report_id"], "diagnostic_report"),
        TABLE_OPTS,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    observation_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    revision: Mapped[int] = mapped_column(UNSIGNED_INT, primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False, unique=True)
    report_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    value_unit: Mapped[str | None] = mapped_column(String(32))
    value_text: Mapped[str | None] = mapped_column(String(2000))
    value_code: Mapped[str | None] = mapped_column(String(64))
    ref_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ref_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    flag: Mapped[str | None] = mapped_column(String(4))
    original_value: Mapped[str | None] = mapped_column(String(255))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)


class ResultReview(Envelope, Base):
    """Clinician acknowledgement task. Delivery, read and acknowledgement differ."""

    __tablename__ = "result_review"
    __table_args__ = (
        fk(["tenant_id", "report_id"], "diagnostic_report"),
        fk(["tenant_id", "patient_id"], "patient"),
        fk(["tenant_id", "assignee_id"], "practitioner"),
        fk(["tenant_id", "acknowledged_by_id"], "practitioner"),
        Index(None, "tenant_id", "assignee_id", "state"),
        TABLE_OPTS,
    )

    report_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    assignee_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    first_read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    acknowledgement_note: Mapped[str | None] = mapped_column(String(1000))


# --- Platform: audit, outbox, idempotency ------------------------------------


class AuditEvent(Base):
    """Append-only (AM-IAM-012). No clinical text is ever written here."""

    __tablename__ = "audit_event"
    __table_args__ = (
        Index(None, "tenant_id", "resource_type", "resource_id"),
        Index(None, "tenant_id", "occurred_at"),
        TABLE_OPTS,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_practitioner_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)


class OutboxEvent(Base):
    """Transactional outbox (DATA-02, DATA-03)."""

    __tablename__ = "outbox_event"
    __table_args__ = (
        Index(None, "published_at", "available_at"),
        TABLE_OPTS,
    )

    event_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
    aggregate_version: Mapped[int] = mapped_column(UNSIGNED_INT, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ConsumedEvent(Base):
    """Consumer-side deduplication by event ID."""

    __tablename__ = "consumed_event"
    __table_args__ = (TABLE_OPTS,)

    consumer: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class IdempotencyRecord(Base):
    """Idempotency-Key scoped to tenant, principal and operation (API-02)."""

    __tablename__ = "idempotency_record"
    __table_args__ = (Index(None, "created_at"), TABLE_OPTS)

    tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
    principal: Mapped[str] = mapped_column(String(255), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=text("(UTC_TIMESTAMP(6))")
    )


# --- Migration staging and national extracts (generated from the ERDs) ---------

from astemia.adapters.db.staging import build_staging_tables, declare_extract_models  # noqa: E402

STAGING_TABLES = build_staging_tables(Base.metadata)
_extract = declare_extract_models(Base)
NationalExtract = _extract["NationalExtract"]
NationalExtractField = _extract["NationalExtractField"]
StgExtractRecord = _extract["StgExtractRecord"]
NationalExtractRecord = _extract["NationalExtractRecord"]

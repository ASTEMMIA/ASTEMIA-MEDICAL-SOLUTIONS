"""Migration of existing patient records (CEDA MIG-01 to MIG-03).

MIG-01, stage: a data migration officer sends an extract of legacy person,
name and address rows. Each row is kept verbatim in its staging table with its
source system, row key, digest and mapping version; sending the same rows
again stages nothing new.

MIG-02, load and reconcile: each staged person, with its current name and
address, becomes a canonical patient through the same checks as the
registration desk, and a lineage record ties the source row to the patient. A
person that fails a check, whose NIN is already another patient's, or that
changed after it was loaded, is quarantined with its reason and changes
nothing. Loading again creates nothing twice. Reconciliation counts every
staged person into exactly one outcome and compares each loaded patient's
identity, as mapped, with the live record.

MIG-03 (cut-over: freezing legacy writes and routing traffic) is an
operational procedure; this service gives it the counts and checks it needs.
"""

import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Table, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    STAGING_TABLES,
    MigrationBatch,
    MigrationRecord,
    Patient,
    PatientIdentifier,
    PersonName,
)
from astemia.application.commands import create_patient
from astemia.application.context import RequestContext
from astemia.application.errors import ApplicationError, Conflict, NotFound
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    MigrationBatchOut,
    MigrationExceptionOut,
    ReconciliationOut,
    RegisterPatient,
    StageBatch,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import migration as mg
from astemia.domain.common import DomainError, new_id
from astemia.domain.events import EventType

MAPPING_VERSION = "g6-1.0"
PERSON, NAME, ADDRESS = "Person", "PersonName", "PersonAddress"
TABLES = {
    PERSON: STAGING_TABLES["stg_person"],
    NAME: STAGING_TABLES["stg_person_name"],
    ADDRESS: STAGING_TABLES["stg_person_address"],
}
# Input field -> staging column. The legacy person number keeps its ERD label
# (medicare_number) in staging only, as lineage (CLAUDE.md naming rule).
COLUMNS = {
    PERSON: {
        "person_number": "medicare_number",
        "nin": "nin",
        "gender": "gender",
        "date_of_birth": "date_of_birth",
        "date_of_death": "date_of_death",
    },
    NAME: {
        "person_number": "medicare_number",
        "title": "title",
        "forename": "forename",
        "other_names": "other_names",
        "surname": "surname",
        "mother_name": "mother_name",
        "valid_to": "date_name_valid_to",
    },
    ADDRESS: {
        "person_number": "medicare_number",
        "address_line1": "address_line1",
        "address_line2": "address_line2",
        "address_line3": "address_line3",
        "state": "state",
        "local_government_area": "local_government_area",
        "postcode": "postcode",
        "effective_to": "effective_to",
    },
}


class Quarantine(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason, self.detail = reason, detail


def _staged(session: Session, table: Table, tid: uuid.UUID, **where: Any) -> Sequence[Any]:
    stmt = select(table).where(table.c.tenant_id == tid)
    for column, value in where.items():
        stmt = stmt.where(table.c[column] == value)
    return session.execute(stmt.order_by(table.c.loaded_at, table.c.id)).all()


class Migration:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    # -- MIG-01: stage ---------------------------------------------------------------

    def stage(self, ctx: RequestContext, key: str | None, cmd: StageBatch) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            batch = MigrationBatch(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                source_system=cmd.source_system,
                description=cmd.description,
                status="staged",
            )
            u.session.add(batch)
            u.session.flush()
            counts: Counter[str] = Counter()
            for entity, rows in (
                (PERSON, cmd.persons),
                (NAME, cmd.names),
                (ADDRESS, cmd.addresses),
            ):
                table = TABLES[entity]
                for row in rows:
                    values = {
                        COLUMNS[entity][f]: v
                        for f, v in row.model_dump(exclude={"row_key"}).items()
                    }
                    digest = mg.row_digest(values)
                    exists = u.session.execute(
                        select(table.c.id).where(
                            table.c.tenant_id == u.ctx.tenant_id,
                            table.c.source_system == cmd.source_system,
                            table.c.source_entity == entity,
                            table.c.source_row_key == row.row_key,
                            table.c.row_digest == digest,
                        )
                    ).first()
                    if exists is not None:
                        counts["already_staged"] += 1
                        continue
                    u.session.execute(
                        table.insert().values(
                            tenant_id=u.ctx.tenant_id,
                            id=uuid.uuid7(),
                            batch_id=batch.id,
                            source_system=cmd.source_system,
                            source_entity=entity,
                            source_row_key=row.row_key,
                            row_digest=digest,
                            mapping_version=MAPPING_VERSION,
                            loaded_at=u.ctx.now,
                            **values,
                        )
                    )
                    counts[entity] += 1
            decision = u.authorize("migration:run")
            u.audit(decision, "migration.stage", "migration_batch", batch.id)
            return CommandResult(
                201, self._batch_out(u.session, batch, counts).model_dump(mode="json")
            )

        return self.wp.run(
            ctx,
            operation="migration.stage",
            capability="migration:run",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    @staticmethod
    def _batch_out(
        session: Session, batch: MigrationBatch, counts: Counter[str]
    ) -> MigrationBatchOut:
        return MigrationBatchOut(
            id=batch.id,
            source_system=batch.source_system,
            description=batch.description,
            status=batch.status,
            staged_persons=counts[PERSON],
            staged_names=counts[NAME],
            staged_addresses=counts[ADDRESS],
            already_staged=counts["already_staged"],
            loaded=counts[mg.RecordStatus.LOADED],
            quarantined=counts[mg.RecordStatus.QUARANTINED],
        )

    # -- MIG-02: load ----------------------------------------------------------------

    def _registration(self, u: Unit, source: str, person: Any) -> RegisterPatient:
        """The staged person, with their current name and address, as a
        registration. Name and address rows may arrive in any batch."""
        tid = u.ctx.tenant_id
        number = person.medicare_number
        names = [
            n
            for n in _staged(
                u.session, TABLES[NAME], tid, source_system=source, medicare_number=number
            )
            if not n.date_name_valid_to
        ]
        if not names:
            raise Quarantine("name_missing", "no current name for this person")
        name = names[-1]
        homes = [
            a
            for a in _staged(
                u.session, TABLES[ADDRESS], tid, source_system=source, medicare_number=number
            )
            if not a.effective_to
        ]
        address = None
        if homes:
            a = homes[-1]
            address = {
                "line1": a.address_line1,
                "line2": a.address_line2 if a.address_line3 else None,
                "town": a.address_line3 or a.address_line2,
                "state": a.state,
                "local_government_area": a.local_government_area,
                "postcode": a.postcode,
            }
        try:
            return RegisterPatient.model_validate(
                {
                    "title": name.title,
                    "family_name": name.surname,
                    "given_names": " ".join(x for x in (name.forename, name.other_names) if x),
                    "mother_name": name.mother_name,
                    "birth_date": mg.legacy_date(person.date_of_birth, "date of birth"),
                    "administrative_sex": mg.legacy_sex(person.gender),
                    "identifiers": (
                        [{"issuer": "NG-NIN", "value": person.nin, "verified": False}]
                        if person.nin
                        else []
                    ),
                    "address": address,
                }
            )
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            raise Quarantine("invalid_record", f"{where}: {first['msg']}") from None

    def _load_one(self, u: Unit, batch: MigrationBatch, person: Any, decision: Decision) -> str:
        source, key, digest = batch.source_system, person.source_row_key, person.row_digest
        seen = (
            u.session.execute(
                select(MigrationRecord).where(
                    MigrationRecord.tenant_id == u.ctx.tenant_id,
                    MigrationRecord.source_system == source,
                    MigrationRecord.source_entity == PERSON,
                    MigrationRecord.source_row_key == key,
                )
            )
            .scalars()
            .all()
        )
        # Staging never holds the same version of a row twice, so this version
        # has at most an earlier quarantine to retry.
        record = next((r for r in seen if r.row_digest == digest), None)
        if record is None:
            record = MigrationRecord(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                batch_id=batch.id,
                source_system=source,
                source_entity=PERSON,
                source_row_key=key,
                row_digest=digest,
                status=mg.RecordStatus.QUARANTINED.value,
            )
            u.session.add(record)
        record.batch_id = batch.id
        savepoint = u.session.begin_nested()
        try:
            if any(r.status == mg.RecordStatus.LOADED for r in seen):
                raise Quarantine(
                    "changed_since_load",
                    "this person was loaded from an earlier version of the row; "
                    "reconcile the change through the patient index",
                )
            cmd = self._registration(u, source, person)
            if not cmd.identifiers:
                raise Quarantine("nin_missing", "a migrated person needs their NIN")
            patient = create_patient(u, cmd, author_role="migration", source=(source, key))
            u.session.flush()
            savepoint.commit()
        except Quarantine as q:
            savepoint.rollback()
            record.status, record.reason, record.detail = (
                mg.RecordStatus.QUARANTINED.value,
                q.reason,
                q.detail,
            )
            return mg.RecordStatus.QUARANTINED
        except IntegrityError:
            savepoint.rollback()
            record.status, record.reason = mg.RecordStatus.QUARANTINED.value, "identifier_in_use"
            record.detail = "the NIN is already another patient's: refer to identity stewardship"
            return mg.RecordStatus.QUARANTINED
        except (ApplicationError, DomainError) as exc:
            savepoint.rollback()
            record.status, record.reason = mg.RecordStatus.QUARANTINED.value, exc.code
            record.detail = str(exc)[:500]
            return mg.RecordStatus.QUARANTINED
        record.status, record.reason, record.detail = mg.RecordStatus.LOADED.value, None, None
        record.patient_id, record.loaded_marker = patient.id, 1
        record.identity_digest = mg.identity_digest(
            cmd.identifiers[0].value,
            cmd.birth_date,
            cmd.administrative_sex.value,
            cmd.family_name,
            cmd.given_names,
        )
        event = u.emit(
            EventType.PATIENT_REGISTERED,
            "patient",
            patient.id,
            1,
            u.ctx.now,
            {"patient_id": str(patient.id), "status": patient.status, "migrated_from": source},
        )
        u.audit(
            decision,
            "patient.migrate",
            "patient",
            patient.id,
            patient_id=patient.id,
            event_id=event,
        )
        return mg.RecordStatus.LOADED

    def load(self, ctx: RequestContext, key: str | None, batch_id: uuid.UUID) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            batch = u.get(MigrationBatch, batch_id, lock=True)
            if batch.status == "loaded":
                raise Conflict("this batch is already loaded", code="batch_loaded")
            decision = u.authorize("migration:run")
            counts: Counter[str] = Counter()
            for person in _staged(u.session, TABLES[PERSON], u.ctx.tenant_id, batch_id=batch.id):
                counts[self._load_one(u, batch, person, decision)] += 1
            batch.status, batch.loaded_at = "loaded", u.ctx.now
            batch.version += 1
            u.session.flush()
            u.audit(decision, "migration.load", "migration_batch", batch.id)
            return CommandResult(
                200, self._batch_out(u.session, batch, counts).model_dump(mode="json")
            )

        return self.wp.run(
            ctx,
            operation="migration.load",
            capability="migration:run",
            idempotency_key=key,
            payload={"batch_id": str(batch_id)},
            handler=handle,
            resource=("migration_batch", batch_id),
        )

    # -- MIG-02: reconcile -----------------------------------------------------------

    def _live_digest(self, session: Session, tid: uuid.UUID, patient_id: uuid.UUID) -> str | None:
        patient = session.get(Patient, (tid, patient_id))
        nin = session.execute(
            select(PatientIdentifier.value).where(
                PatientIdentifier.tenant_id == tid,
                PatientIdentifier.patient_id == patient_id,
                PatientIdentifier.issuer == "NG-NIN",
                PatientIdentifier.active_marker == 1,
            )
        ).scalar_one_or_none()
        name = session.execute(
            select(PersonName)
            .where(
                PersonName.tenant_id == tid,
                PersonName.party_id == patient_id,
                PersonName.name_type == "usual",
                PersonName.effective_to.is_(None),
            )
            .order_by(PersonName.name_number)
            .limit(1)
        ).scalar_one_or_none()
        if patient is None or nin is None or name is None:
            return None
        given = " ".join(x for x in (name.given_name, name.other_given_name) if x)
        return mg.identity_digest(
            nin, patient.birth_date, patient.administrative_sex, name.family_name, given
        )

    def reconciliation(self, ctx: RequestContext, batch_id: uuid.UUID) -> ReconciliationOut:
        def read(session: Session, decision: Decision) -> ReconciliationOut:
            tid = ctx.tenant_id
            batch = session.get(MigrationBatch, (tid, batch_id))
            if batch is None:
                raise NotFound("migration batch not found")
            staged = _staged(session, TABLES[PERSON], tid, batch_id=batch.id)
            records = (
                session.execute(
                    select(MigrationRecord).where(
                        MigrationRecord.tenant_id == tid,
                        MigrationRecord.source_system == batch.source_system,
                        MigrationRecord.source_entity == PERSON,
                        MigrationRecord.source_row_key.in_([p.source_row_key for p in staged]),
                    )
                )
                .scalars()
                .all()
            )
            by_version = {(r.source_row_key, r.row_digest): r for r in records}
            loaded_keys = {r.source_row_key for r in records if r.status == mg.RecordStatus.LOADED}
            outcome: Counter[str] = Counter()
            reasons: Counter[str] = Counter()
            for p in staged:
                r = by_version.get((p.source_row_key, p.row_digest))
                if r is None:
                    outcome["not_processed"] += 1
                elif r.status == mg.RecordStatus.QUARANTINED:
                    outcome["quarantined"] += 1
                    reasons[r.reason or "unknown"] += 1
                else:
                    outcome["loaded"] += 1
            mismatched = [
                r.patient_id
                for r in records
                if r.status == mg.RecordStatus.LOADED
                and r.patient_id is not None
                and self._live_digest(session, tid, r.patient_id) != r.identity_digest
            ]
            return ReconciliationOut(
                batch_id=batch.id,
                status=batch.status,
                source_persons=len(staged),
                loaded=outcome["loaded"],
                quarantined=outcome["quarantined"],
                not_processed=outcome["not_processed"],
                quarantine_reasons=dict(sorted(reasons.items())),
                patients_from_source=len(loaded_keys),
                identity_mismatches=[m for m in mismatched if m is not None],
                reconciled=outcome["not_processed"] == 0 and not mismatched,
            )

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="migration:read",
            action="migration.reconciliation",
            resource_type="migration_batch",
            patient_id=None,
            reader=read,
        )

    def exceptions(self, ctx: RequestContext, batch_id: uuid.UUID) -> list[MigrationExceptionOut]:
        def read(session: Session, decision: Decision) -> list[MigrationExceptionOut]:
            if session.get(MigrationBatch, (ctx.tenant_id, batch_id)) is None:
                raise NotFound("migration batch not found")
            rows = session.execute(
                select(MigrationRecord)
                .where(
                    MigrationRecord.tenant_id == ctx.tenant_id,
                    MigrationRecord.batch_id == batch_id,
                    MigrationRecord.status == mg.RecordStatus.QUARANTINED.value,
                )
                .order_by(MigrationRecord.source_row_key)
            ).scalars()
            return [
                MigrationExceptionOut(
                    source_row_key=r.source_row_key, reason=r.reason or "", detail=r.detail
                )
                for r in rows
            ]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="migration:read",
            action="migration.exceptions",
            resource_type="migration_batch",
            patient_id=None,
            reader=read,
        )

"""Wards, beds and occupancy (CEDA HS03, WF02 step 3).

Tenant administrators set up wards and beds. The ward team, registrars and
clinicians give an open encounter a bed and transfer it between beds; the bed
board shows every ward with who is in each bed. A transfer closes the old
occupancy and opens the new one in one transaction, and discharge closes the
last one. The encounter row and the bed row are locked in that order, and
unique keys on the open interval refuse a second patient in a bed, or a second
bed for an encounter, even if two requests race.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import Bed, BedOccupancy, Encounter, OrganisationSite, Ward
from astemia.application.context import RequestContext
from astemia.application.errors import Conflict, NotFound, Unprocessable
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    AssignBed,
    BedOut,
    CreateBed,
    CreateWard,
    OccupancyOut,
    SetBedStatus,
    SetWardStatus,
    WardOut,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import beds as bd
from astemia.domain.common import DomainError, Sensitivity, new_id
from astemia.domain.encounter import EncounterClass, EncounterState
from astemia.domain.events import EventType


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def occupancy_out(row: BedOccupancy, bed: Bed, ward: Ward) -> OccupancyOut:
    return OccupancyOut(
        id=row.id,
        bed_id=bed.id,
        bed_code=bed.code,
        ward_id=ward.id,
        ward_code=ward.code,
        encounter_id=row.encounter_id,
        patient_id=row.patient_id,
        start_at=row.start_at,
        end_at=row.end_at,
        end_reason=bd.EndReason(row.end_reason) if row.end_reason else None,
        isolation=row.isolation,
        reason=row.reason,
        previous_id=row.previous_id,
    )


def _active(u: Unit, **where: uuid.UUID) -> BedOccupancy | None:
    """The open interval for a bed or an encounter, read with a lock so a
    request that waited on another sees what that one committed."""
    (column, value) = next(iter(where.items()))
    return u.session.execute(
        select(BedOccupancy)
        .where(
            BedOccupancy.tenant_id == u.ctx.tenant_id,
            getattr(BedOccupancy, column) == value,
            BedOccupancy.active_marker == 1,
        )
        .with_for_update()
    ).scalar_one_or_none()


def close_occupancy(u: Unit, encounter_id: uuid.UUID, at: datetime, reason: bd.EndReason) -> None:
    """End the encounter's open interval, if it has one (discharge, transfer)."""
    current = _active(u, encounter_id=encounter_id)
    if current is not None:
        current.end_at, current.end_reason = at, reason.value
        current.active_marker = None
        current.version += 1
        u.session.flush()  # free the unique keys before a new interval opens


class Beds:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    def _patient_of(self, ctx: RequestContext, encounter_id: uuid.UUID) -> uuid.UUID | None:
        with self.factory() as session:
            return session.execute(
                select(Encounter.patient_id).where(
                    Encounter.tenant_id == ctx.tenant_id, Encounter.id == encounter_id
                )
            ).scalar_one_or_none()

    # -- set-up -------------------------------------------------------------------

    def _ward_out(self, session: Session, ward: Ward) -> WardOut:
        return self._board(session, [ward])[0]

    def _board(self, session: Session, wards: list[Ward]) -> list[WardOut]:
        tid = wards[0].tenant_id if wards else None
        ids = [w.id for w in wards]
        beds = list(
            session.execute(
                select(Bed).where(Bed.tenant_id == tid, Bed.ward_id.in_(ids)).order_by(Bed.code)
            ).scalars()
        )
        occupied = {
            o.bed_id: o
            for o in session.execute(
                select(BedOccupancy).where(
                    BedOccupancy.tenant_id == tid,
                    BedOccupancy.bed_id.in_([b.id for b in beds]),
                    BedOccupancy.active_marker == 1,
                )
            ).scalars()
        }
        out = []
        for ward in wards:
            rows = [
                BedOut(
                    id=b.id,
                    version=b.version,
                    code=b.code,
                    status=bd.BedStatus(b.status),
                    isolation_capable=b.isolation_capable,
                    status_reason=b.status_reason,
                    occupancy=occupancy_out(occupied[b.id], b, ward) if b.id in occupied else None,
                )
                for b in beds
                if b.ward_id == ward.id
            ]
            out.append(
                WardOut(
                    id=ward.id,
                    version=ward.version,
                    facility_id=ward.facility_id,
                    code=ward.code,
                    name=ward.name,
                    specialty=ward.specialty,
                    active=ward.active,
                    beds=rows,
                    available=sum(
                        1
                        for r in rows
                        if r.occupancy is None and r.status is bd.BedStatus.AVAILABLE
                    ),
                    occupied=sum(1 for r in rows if r.occupancy is not None),
                )
            )
        return out

    def create_ward(self, ctx: RequestContext, key: str | None, cmd: CreateWard) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            u.get(OrganisationSite, cmd.facility_id)
            ward = Ward(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                facility_id=cmd.facility_id,
                code=cmd.code,
                name=cmd.name,
                specialty=cmd.specialty,
                active=True,
            )
            u.session.add(ward)
            u.session.flush()
            decision = u.authorize("bed:manage")
            u.audit(decision, "ward.create", "ward", ward.id)
            return CommandResult(201, self._ward_out(u.session, ward).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="ward.create",
            capability="bed:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    def set_ward_status(
        self,
        ctx: RequestContext,
        key: str | None,
        ward_id: uuid.UUID,
        expected: int | None,
        cmd: SetWardStatus,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            ward = u.get(Ward, ward_id, lock=True)
            u.check_version(ward.version, expected)
            ward.active, ward.version = cmd.active, ward.version + 1
            u.session.flush()
            decision = u.authorize("bed:manage")
            u.audit(decision, "ward.status", "ward", ward.id)
            return CommandResult(200, self._ward_out(u.session, ward).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="ward.status",
            capability="bed:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"ward_id": str(ward_id), "v": expected},
            handler=handle,
            resource=("ward", ward_id),
        )

    def create_bed(
        self, ctx: RequestContext, key: str | None, ward_id: uuid.UUID, cmd: CreateBed
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            ward = u.get(Ward, ward_id)
            u.session.add(
                Bed(
                    tenant_id=u.ctx.tenant_id,
                    id=new_id(),
                    recorded_at=u.ctx.now,
                    author_id=u.ctx.principal.practitioner_id,
                    ward_id=ward.id,
                    code=cmd.code,
                    status=bd.BedStatus.AVAILABLE.value,
                    isolation_capable=cmd.isolation_capable,
                )
            )
            u.session.flush()
            decision = u.authorize("bed:manage")
            u.audit(decision, "bed.create", "ward", ward.id)
            return CommandResult(201, self._ward_out(u.session, ward).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="bed.create",
            capability="bed:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"ward_id": str(ward_id)},
            handler=handle,
            resource=("ward", ward_id),
        )

    def set_bed_status(
        self,
        ctx: RequestContext,
        key: str | None,
        bed_id: uuid.UUID,
        expected: int | None,
        cmd: SetBedStatus,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            bed = u.get(Bed, bed_id, lock=True)
            u.check_version(bed.version, expected)
            if cmd.status is bd.BedStatus.CLOSED and _active(u, bed_id=bed.id) is not None:
                raise Conflict("move the patient before closing the bed", code="bed_occupied")
            bed.status, bed.status_reason = cmd.status.value, cmd.reason
            bed.version += 1
            u.session.flush()
            decision = u.authorize("bed:manage")
            u.audit(decision, "bed.status", "bed", bed.id)
            ward = u.get(Ward, bed.ward_id)
            return CommandResult(200, self._ward_out(u.session, ward).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="bed.status",
            capability="bed:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"bed_id": str(bed_id), "v": expected},
            handler=handle,
            resource=("bed", bed_id),
        )

    def board(self, ctx: RequestContext, facility_id: uuid.UUID | None) -> list[WardOut]:
        def read(session: Session, decision: Decision) -> list[WardOut]:
            stmt = select(Ward).where(Ward.tenant_id == ctx.tenant_id)
            if facility_id is not None:
                stmt = stmt.where(Ward.facility_id == facility_id)
            return self._board(session, list(session.execute(stmt.order_by(Ward.code)).scalars()))

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="bed:read",
            action="bed_board.read",
            resource_type="ward",
            patient_id=None,
            reader=read,
        )

    # -- occupancy ----------------------------------------------------------------

    def _move(
        self,
        ctx: RequestContext,
        key: str | None,
        encounter_id: uuid.UUID,
        expected: int | None,
        cmd: AssignBed,
        *,
        transfer: bool,
    ) -> CommandResult:
        operation = "encounter.transfer" if transfer else "encounter.assign_bed"

        def handle(u: Unit) -> CommandResult:
            encounter = u.get(Encounter, encounter_id, lock=True)
            u.check_version(encounter.version, expected)
            _domain(
                lambda: bd.check_encounter(
                    EncounterState(encounter.state), EncounterClass(encounter.encounter_class)
                )
            )
            bed = u.get(Bed, cmd.bed_id, lock=True)
            ward = u.get(Ward, bed.ward_id)
            _domain(
                lambda: bd.check_bed(
                    bd.BedStatus(bed.status),
                    ward.active,
                    bed.isolation_capable,
                    isolation=cmd.isolation,
                    same_facility=ward.facility_id == encounter.facility_id,
                )
            )
            current = _active(u, encounter_id=encounter.id)
            if transfer and current is None:
                raise Conflict("the patient has no bed yet; assign one", code="no_bed")
            if not transfer and current is not None:
                raise Conflict(
                    "the patient already has a bed; transfer them", code="already_in_bed"
                )
            if current is not None and current.bed_id == bed.id:
                raise Unprocessable("the patient is already in that bed", code="same_bed")
            if _active(u, bed_id=bed.id) is not None:
                raise Conflict("that bed is occupied", code="bed_occupied")
            if current is not None:
                close_occupancy(u, encounter.id, u.ctx.now, bd.EndReason.TRANSFER)
            row = BedOccupancy(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                sensitivity=encounter.sensitivity,
                bed_id=bed.id,
                encounter_id=encounter.id,
                patient_id=encounter.patient_id,
                start_at=u.ctx.now,
                isolation=cmd.isolation,
                reason=cmd.reason,
                previous_id=current.id if current is not None else None,
                active_marker=1,
            )
            u.session.add(row)
            encounter.version += 1
            u.session.flush()
            decision = u.authorize("bed:assign", patient_id=encounter.patient_id)
            event = u.emit(
                EventType.PATIENT_TRANSFERRED if transfer else EventType.BED_ASSIGNED,
                "encounter",
                encounter.id,
                encounter.version,
                u.ctx.now,
                {
                    "encounter_id": str(encounter.id),
                    "patient_id": str(encounter.patient_id),
                    "bed_id": str(bed.id),
                    "ward_id": str(ward.id),
                    "from_bed_id": str(current.bed_id) if current is not None else None,
                },
            )
            u.audit(
                decision,
                operation,
                "bed_occupancy",
                row.id,
                patient_id=encounter.patient_id,
                event_id=event,
            )
            return CommandResult(
                200 if transfer else 201, occupancy_out(row, bed, ward).model_dump(mode="json")
            )

        return self.wp.run(
            ctx,
            operation=operation,
            capability="bed:assign",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json")
            | {"encounter_id": str(encounter_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, encounter_id),
            resource=("encounter", encounter_id),
        )

    def assign(
        self,
        ctx: RequestContext,
        key: str | None,
        encounter_id: uuid.UUID,
        expected: int | None,
        cmd: AssignBed,
    ) -> CommandResult:
        return self._move(ctx, key, encounter_id, expected, cmd, transfer=False)

    def transfer(
        self,
        ctx: RequestContext,
        key: str | None,
        encounter_id: uuid.UUID,
        expected: int | None,
        cmd: AssignBed,
    ) -> CommandResult:
        return self._move(ctx, key, encounter_id, expected, cmd, transfer=True)

    def movements(self, ctx: RequestContext, encounter_id: uuid.UUID) -> list[OccupancyOut]:
        """Every bed the encounter has been in, oldest first, for its care team."""
        patient_id = self._patient_of(ctx, encounter_id)
        if patient_id is None:
            raise NotFound("not found")

        def read(session: Session, decision: Decision) -> list[OccupancyOut]:
            sensitivity = session.execute(
                select(Encounter.sensitivity).where(
                    Encounter.tenant_id == ctx.tenant_id, Encounter.id == encounter_id
                )
            ).scalar_one()
            if sensitivity != Sensitivity.NORMAL and f"sensitivity:{sensitivity}" in decision.masks:
                raise NotFound("not found")  # withheld, as in the chart
            rows = session.execute(
                select(BedOccupancy, Bed, Ward)
                .join(
                    Bed, (Bed.tenant_id == BedOccupancy.tenant_id) & (Bed.id == BedOccupancy.bed_id)
                )
                .join(Ward, (Ward.tenant_id == Bed.tenant_id) & (Ward.id == Bed.ward_id))
                .where(
                    BedOccupancy.tenant_id == ctx.tenant_id,
                    BedOccupancy.encounter_id == encounter_id,
                )
                .order_by(BedOccupancy.start_at, BedOccupancy.id)
            ).all()
            return [occupancy_out(o, b, w) for o, b, w in rows]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="chart:read",
            action="encounter.movements",
            resource_type="encounter",
            patient_id=patient_id,
            reader=read,
        )

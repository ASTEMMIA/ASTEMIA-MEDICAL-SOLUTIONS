"""Commands for the foundation and the API-03 vertical slice.

Each handler runs inside WritePath.run, so it already has an open transaction,
an authorised principal and an unused Idempotency-Key.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from astemia.adapters.db.models import (
    AeAttendance,
    CareProvision,
    DemographicTransaction,
    DiagnosticReport,
    Encounter,
    LegitimateRelationship,
    Observation,
    ObservationRevision,
    OrganisationSite,
    Party,
    Patient,
    PatientIdentifier,
    PersonName,
    Practitioner,
    ResultReview,
    ServiceRequest,
)
from astemia.application import views
from astemia.application.addresses import file_home
from astemia.application.catalogue import resolve_service_for_admission
from astemia.application.errors import Conflict, Unprocessable
from astemia.application.identity_review import review_new_registration
from astemia.application.patient_index import possible_duplicates
from astemia.application.schemas import (
    Acknowledge,
    AdmitEncounter,
    PlaceOrder,
    RegisterPatient,
    ReleaseReport,
)
from astemia.application.write_path import CommandResult, Unit, WritePath
from astemia.domain import diagnostics as dx
from astemia.domain import encounter as enc
from astemia.domain import identity as idn
from astemia.domain.common import DomainError, EffectivePrecision, new_id
from astemia.domain.events import EventType


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def open_encounter(
    u: Unit,
    *,
    patient_id: uuid.UUID,
    facility_id: uuid.UUID,
    practitioner_id: uuid.UUID,
    visit_authority: str,
    visit_number: str,
    encounter_class: enc.EncounterClass,
    service: str,
    clinical_service_id: uuid.UUID | None,
    started_at: datetime,
    sensitivity: str,
    admission_route: str | None,
) -> Encounter:
    """Open an encounter with the responsible clinician's care relationship
    and care provision (admission, and attendance at an appointment)."""
    encounter = Encounter(
        tenant_id=u.ctx.tenant_id,
        id=new_id(),
        version=1,
        recorded_at=u.ctx.now,
        effective_at=started_at,
        effective_precision=EffectivePrecision.MINUTE.value,
        author_id=u.ctx.principal.practitioner_id,
        sensitivity=sensitivity,
        patient_id=patient_id,
        facility_id=facility_id,
        responsible_practitioner_id=practitioner_id,
        visit_authority=visit_authority,
        visit_number=visit_number,
        encounter_class=encounter_class.value,
        service=service,
        clinical_service_id=clinical_service_id,
        state=enc.admission_state(encounter_class).value,
        admission_route=admission_route,
        period_start=started_at,
    )
    u.session.add(encounter)
    u.session.flush()
    lr = LegitimateRelationship(
        tenant_id=u.ctx.tenant_id,
        id=new_id(),
        recorded_at=u.ctx.now,
        author_id=u.ctx.principal.practitioner_id,
        patient_id=patient_id,
        practitioner_id=practitioner_id,
        encounter_id=encounter.id,
        start_at=started_at,
        creation_reason_code="responsible_clinician",
        created_by_id=u.ctx.principal.practitioner_id,
    )
    u.session.add(lr)
    u.session.flush()
    u.session.add(
        CareProvision(
            tenant_id=u.ctx.tenant_id,
            id=new_id(),
            recorded_at=u.ctx.now,
            patient_id=patient_id,
            practitioner_id=practitioner_id,
            legitimate_relationship_id=lr.id,
            specialist_area=service,
            start_at=started_at,
        )
    )
    return encounter


class Commands:
    def __init__(self, write_path: WritePath) -> None:
        self.wp = write_path

    # -- UG02 / WF01: register patient ----------------------------------------

    def register_patient(self, ctx: Any, key: str | None, cmd: RegisterPatient) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            _domain(
                lambda: idn.validate_birth_date(
                    cmd.birth_date, cmd.birth_date_precision, u.ctx.now.date()
                )
            )
            for i in cmd.identifiers:
                _domain(
                    lambda i=i: idn.check_issuer_allowed(
                        i.issuer, idn.IdentifierType(i.identifier_type)
                    )
                )
            identifiers = [
                (
                    i.issuer,
                    _domain(lambda i=i: idn.validate_identifier(i.issuer, i.value)),
                    i.verified,
                )
                for i in cmd.identifiers
            ]
            address = cmd.address
            _domain(
                lambda: idn.check_address(
                    temporary=cmd.temporary,
                    has_address=address is not None,
                    country=address.country if address else None,
                    state=address.state if address else None,
                    lga=address.local_government_area if address else None,
                )
            )
            postcode = (
                _domain(lambda: idn.normalise_postcode(address.country, address.postcode))
                if address
                else None
            )
            if len({(iss, v) for iss, v, _ in identifiers}) != len(identifiers):
                raise Unprocessable(
                    "the same identifier is listed twice", code="duplicate_identifier"
                )
            status = idn.PatientStatus.TEMPORARY if cmd.temporary else idn.PatientStatus.ACTIVE
            pid = new_id()
            envelope = {
                "tenant_id": u.ctx.tenant_id,
                "recorded_at": u.ctx.now,
                "author_id": u.ctx.principal.practitioner_id,
                "author_role": "registrar",
            }
            u.session.add(Party(id=pid, version=1, party_type="person", **envelope))
            u.session.flush()
            patient = Patient(
                id=pid,
                version=1,
                birth_date=cmd.birth_date,
                birth_date_precision=cmd.birth_date_precision.value,
                administrative_sex=cmd.administrative_sex.value,
                status=status.value,
                registration_date=u.ctx.now.date(),
                initial_registration_source="astemia",
                mother_name=cmd.mother_name,
                father_name=cmd.father_name,
                preferred_language=cmd.preferred_language,
                state_of_origin=cmd.state_of_origin,
                **envelope,
            )
            u.session.add(patient)
            given, _, other = cmd.given_names.partition(" ")
            u.session.add(
                PersonName(
                    id=new_id(),
                    party_id=pid,
                    name_type=idn.NameType.USUAL.value,
                    name_number=1,
                    title=cmd.title,
                    family_name=cmd.family_name,
                    given_name=given,
                    other_given_name=other or None,
                    family_name_phonetic=idn.phonetic(cmd.family_name),
                    given_name_phonetic=idn.phonetic(given),
                    other_given_name_phonetic=idn.phonetic(other) or None,
                    effective_from=u.ctx.now,
                    **envelope,
                )
            )
            u.session.flush()
            for (issuer, value, verified), raw in zip(identifiers, cmd.identifiers, strict=True):
                u.session.add(
                    PatientIdentifier(
                        id=new_id(),
                        patient_id=pid,
                        issuer=issuer,
                        value=value,
                        identifier_type=raw.identifier_type,
                        verification_status=(
                            idn.VerificationStatus.VERIFIED
                            if verified
                            else idn.VerificationStatus.UNVERIFIED
                        ).value,
                        valid_from=u.ctx.now,
                        active_marker=1 if idn.binds_actively(issuer) else None,
                        **envelope,
                    )
                )
            created = ["patient", "person_name", "patient_identifier"]
            if address is not None and postcode is not None:
                file_home(u, pid, address, postcode, envelope)
                created += ["address", "party_address"]
            u.session.add(
                DemographicTransaction(
                    tenant_id=u.ctx.tenant_id,
                    id=new_id(),
                    patient_id=pid,
                    transaction_source="api",
                    transaction_at=u.ctx.now,
                    delta={"created": created},
                    change_reason="registration",
                    source_validation_level="registrar",
                    country_of_transaction="NG",
                    transaction_user=u.ctx.principal.subject,
                    correlation_id=u.ctx.correlation_id,
                )
            )
            u.session.flush()  # surfaces a duplicate active identifier as a 409
            decision = u.authorize("patient:register")
            event = u.emit(
                EventType.PATIENT_REGISTERED,
                "patient",
                patient.id,
                1,
                u.ctx.now,
                {"patient_id": str(patient.id), "status": patient.status},
            )
            u.audit(
                decision,
                "patient.register",
                "patient",
                patient.id,
                patient_id=patient.id,
                event_id=event,
            )
            body = views.patient(u.session, patient, masks=frozenset(), at=u.ctx.now).model_dump(
                mode="json"
            )
            # ICRS 3.2.8: alert, never block; the registrar or a steward decides.
            body["possible_duplicates"] = [
                str(d) for d in possible_duplicates(u.session, patient, cmd.family_name)
            ]
            # WF01: near matches (spelling, year of birth) open steward review tasks.
            body["identity_review_tasks"] = review_new_registration(u, patient.id, cmd)
            return CommandResult(201, body)

        return self.wp.run(
            ctx,
            operation="patient.register",
            capability="patient:register",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    # -- API-03 / WF02: admission ------------------------------------------------

    def admit(self, ctx: Any, key: str | None, cmd: AdmitEncounter) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            patient = u.get(Patient, cmd.patient_id, lock=True)
            if patient.status in (idn.PatientStatus.MERGED, idn.PatientStatus.DECEASED):
                raise Conflict(f"patient is {patient.status}", code="patient_not_admissible")
            u.get(OrganisationSite, cmd.facility_id)
            clinical_service_id = resolve_service_for_admission(u, cmd.service, cmd.facility_id)
            u.get(Practitioner, cmd.responsible_practitioner_id)
            if cmd.admitted_at > u.ctx.now:
                raise Unprocessable("admission time is in the future", code="future_admission")
            encounter = open_encounter(
                u,
                patient_id=patient.id,
                facility_id=cmd.facility_id,
                practitioner_id=cmd.responsible_practitioner_id,
                visit_authority=cmd.visit_authority,
                visit_number=cmd.visit_number,
                encounter_class=cmd.encounter_class,
                service=cmd.service,
                clinical_service_id=clinical_service_id,
                started_at=cmd.admitted_at,
                sensitivity=cmd.sensitivity.value,
                admission_route=cmd.admission_route,
            )
            if cmd.ae is not None:
                if cmd.encounter_class is not enc.EncounterClass.EMERGENCY:
                    raise Unprocessable(
                        "A&E detail needs an emergency encounter", code="ae_needs_emergency"
                    )
                u.session.add(
                    AeAttendance(
                        tenant_id=u.ctx.tenant_id,
                        id=new_id(),
                        recorded_at=u.ctx.now,
                        encounter_id=encounter.id,
                        patient_id=patient.id,
                        attendance_number=cmd.ae.attendance_number,
                        arrival_mode=cmd.ae.arrival_mode,
                        attendance_category=cmd.ae.attendance_category,
                        patient_group=cmd.ae.patient_group,
                        referral_source=cmd.ae.referral_source,
                        incident_location_type=cmd.ae.incident_location_type,
                        arrival_at=cmd.admitted_at,
                        initial_assessment_at=cmd.ae.initial_assessment_at,
                    )
                )
            decision = u.authorize("encounter:admit")
            event = u.emit(
                EventType.ENCOUNTER_ADMITTED,
                "encounter",
                encounter.id,
                1,
                cmd.admitted_at,
                {
                    "encounter_id": str(encounter.id),
                    "patient_id": str(patient.id),
                    "facility_id": str(cmd.facility_id),
                    "class": encounter.encounter_class,
                },
            )
            u.audit(
                decision,
                "encounter.admit",
                "encounter",
                encounter.id,
                patient_id=patient.id,
                event_id=event,
            )
            return CommandResult(201, views.encounter(u.session, encounter).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="encounter.admit",
            capability="encounter:admit",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    # -- API-03 / WF03 step 1: order -------------------------------------------

    def place_order(self, ctx: Any, key: str | None, cmd: PlaceOrder) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            encounter = u.get(Encounter, cmd.encounter_id, lock=True)
            # The open encounter of a record merged into this one still takes orders.
            if encounter.patient_id not in (
                cmd.patient_id,
                *views.merged_from(u.session, u.ctx.tenant_id, cmd.patient_id),
            ):
                raise Unprocessable(
                    "encounter does not belong to this patient", code="encounter_patient_mismatch"
                )
            if enc.EncounterState(encounter.state) not in enc.OPEN_STATES:
                raise Conflict("encounter is not open for orders", code="encounter_closed")
            requester = u.ctx.principal.practitioner_id
            assert requester is not None  # guaranteed by the relationship-bound policy
            owner = cmd.result_owner_id or requester
            u.get(Practitioner, owner)
            if cmd.backup_owner_id:
                u.get(Practitioner, cmd.backup_owner_id)
            order = ServiceRequest(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                effective_at=u.ctx.now,
                effective_precision=EffectivePrecision.SECOND.value,
                author_id=requester,
                author_role="clinician",
                sensitivity=encounter.sensitivity,
                code_system=cmd.code_system,
                code=cmd.code,
                display=cmd.display,
                original_system=cmd.original_system,
                original_code=cmd.original_code,
                # The order stays with its encounter's record, so an unmerge
                # takes both back together.
                patient_id=encounter.patient_id,
                encounter_id=encounter.id,
                requester_id=requester,
                result_owner_id=owner,
                backup_owner_id=cmd.backup_owner_id,
                placer_authority="ASTEMIA",
                placer_id=f"ORD-{uuid.uuid7().hex[-12:].upper()}",
                status=dx.ServiceRequestStatus.ACTIVE.value,
                priority=cmd.priority.value,
                clinical_note=cmd.clinical_note,
            )
            u.session.add(order)
            u.session.flush()
            decision = u.authorize("order:create", patient_id=cmd.patient_id)
            event = u.emit(
                EventType.ORDER_PLACED,
                "service_request",
                order.id,
                1,
                u.ctx.now,
                {
                    "order_id": str(order.id),
                    "patient_id": str(order.patient_id),
                    "encounter_id": str(order.encounter_id),
                    "placer_id": order.placer_id,
                    "code_system": order.code_system,
                    "code": order.code,
                    "priority": order.priority,
                },
            )
            u.audit(
                decision,
                "order.create",
                "service_request",
                order.id,
                patient_id=order.patient_id,
                event_id=event,
            )
            return CommandResult(201, views.order(order).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="order.create",
            capability="order:create",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
            patient_id=cmd.patient_id,
        )

    # -- WF03 step 3: result release or correction ------------------------------

    def release_report(self, ctx: Any, key: str | None, cmd: ReleaseReport) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            order = u.get(ServiceRequest, cmd.service_request_id, lock=True)
            current = dx.ServiceRequestStatus(order.status)
            if current not in (dx.ServiceRequestStatus.ACTIVE, dx.ServiceRequestStatus.COMPLETED):
                raise Conflict(f"order is {current}", code="order_not_resultable")
            values = [
                (
                    o,
                    _domain(
                        lambda o=o: dx.ObservationValue(
                            value_type=o.value_type,
                            quantity=o.quantity,
                            unit=o.unit,
                            text=o.text,
                            code=o.value_code,
                            ref_low=o.ref_low,
                            ref_high=o.ref_high,
                        )
                    ),
                )
                for o in cmd.observations
            ]
            if len({(o.code_system, o.code) for o, _ in values}) != len(values):
                raise Unprocessable(
                    "an observation code appears twice", code="duplicate_observation"
                )

            prior = u.session.execute(
                select(DiagnosticReport)
                .where(
                    DiagnosticReport.tenant_id == u.ctx.tenant_id,
                    DiagnosticReport.service_request_id == order.id,
                )
                .order_by(DiagnosticReport.released_at.desc(), DiagnosticReport.id.desc())
                .limit(1)
                .with_for_update()
            ).scalar_one_or_none()
            status = _domain(
                lambda: dx.release_status(
                    dx.ReportStatus(prior.status) if prior else None, cmd.status
                )
            )
            scientist = u.ctx.principal.practitioner_id
            if scientist is None:
                u.deny("no_practitioner")
            assert scientist is not None

            report = DiagnosticReport(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                effective_at=cmd.effective_at,
                effective_precision=EffectivePrecision.MINUTE.value,
                author_id=scientist,
                author_role="lab_scientist",
                sensitivity=order.sensitivity,
                service_request_id=order.id,
                patient_id=order.patient_id,
                status=status.value,
                released_by_id=scientist,
                released_at=u.ctx.now,
                portal_release="withheld",
                prior_report_id=prior.id if prior else None,
                conclusion=cmd.conclusion,
            )
            u.session.add(report)
            u.session.flush()

            revisions: list[dict[str, str]] = []
            for obs_in, value in values:
                obs = u.session.execute(
                    select(Observation)
                    .where(
                        Observation.tenant_id == u.ctx.tenant_id,
                        Observation.service_request_id == order.id,
                        Observation.code_system == obs_in.code_system,
                        Observation.code == obs_in.code,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                old_revision_id: uuid.UUID | None = None
                if obs is None:
                    obs = Observation(
                        tenant_id=u.ctx.tenant_id,
                        id=new_id(),
                        version=1,
                        recorded_at=u.ctx.now,
                        effective_at=cmd.effective_at,
                        author_id=scientist,
                        sensitivity=order.sensitivity,
                        code_system=obs_in.code_system,
                        code=obs_in.code,
                        display=obs_in.display,
                        patient_id=order.patient_id,
                        service_request_id=order.id,
                        current_revision=1,
                    )
                    u.session.add(obs)
                    u.session.flush()
                    rev_no = 1
                else:
                    old_revision_id = u.session.execute(
                        select(ObservationRevision.id).where(
                            ObservationRevision.tenant_id == u.ctx.tenant_id,
                            ObservationRevision.observation_id == obs.id,
                            ObservationRevision.revision == obs.current_revision,
                        )
                    ).scalar_one()
                    rev_no = obs.current_revision + 1
                    obs.current_revision = rev_no
                    obs.version += 1
                obs_status = (
                    dx.ObservationStatus.AMENDED
                    if rev_no > 1
                    else dx.ObservationStatus(status.value)
                )
                flag = value.flag()
                rev = ObservationRevision(
                    tenant_id=u.ctx.tenant_id,
                    observation_id=obs.id,
                    revision=rev_no,
                    id=new_id(),
                    report_id=report.id,
                    status=obs_status.value,
                    value_type=value.value_type.value,
                    value_quantity=value.quantity,
                    value_unit=value.unit,
                    value_text=value.text,
                    value_code=value.code,
                    ref_low=value.ref_low,
                    ref_high=value.ref_high,
                    flag=flag.value if flag else None,
                    original_value=obs_in.original_value,
                    effective_at=cmd.effective_at,
                    recorded_at=u.ctx.now,
                    author_id=scientist,
                )
                u.session.add(rev)
                revisions.append(
                    {"observation_id": str(obs.id), "new_revision_id": str(rev.id)}
                    | ({"old_revision_id": str(old_revision_id)} if old_revision_id else {})
                )

            # Order completes on first release; it stays completed on amendment.
            order.status = dx.move_order(current, dx.ServiceRequestStatus.COMPLETED).value
            order.version += 1
            if cmd.filler_id:
                order.filler_authority = cmd.filler_authority or "LAB"
                order.filler_id = cmd.filler_id

            # An amendment supersedes open reviews and reopens exactly one.
            u.session.execute(
                update(ResultReview)
                .where(
                    ResultReview.tenant_id == u.ctx.tenant_id,
                    ResultReview.report_id.in_(
                        select(DiagnosticReport.id).where(
                            DiagnosticReport.tenant_id == u.ctx.tenant_id,
                            DiagnosticReport.service_request_id == order.id,
                            DiagnosticReport.id != report.id,
                        )
                    ),
                    ResultReview.state.in_(
                        [dx.ReviewState.OPEN.value, dx.ReviewState.ESCALATED.value]
                    ),
                )
                .values(state=dx.ReviewState.SUPERSEDED.value, version=ResultReview.version + 1)
            )
            review = ResultReview(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                sensitivity=order.sensitivity,
                report_id=report.id,
                patient_id=order.patient_id,
                assignee_id=order.result_owner_id,
                state=dx.ReviewState.OPEN.value,
            )
            u.session.add(review)
            u.session.flush()

            decision = u.authorize("result:release")
            event_type = (
                EventType.RESULT_AMENDED
                if status is dx.ReportStatus.AMENDED
                else EventType.RESULT_RELEASED
            )
            event = u.emit(
                event_type,
                "diagnostic_report",
                report.id,
                1,
                cmd.effective_at,
                {
                    "report_id": str(report.id),
                    "order_id": str(order.id),
                    "patient_id": str(order.patient_id),
                    "status": report.status,
                    "prior_report_id": str(prior.id) if prior else None,
                    "review_id": str(review.id),
                    "revisions": revisions,
                },
            )
            u.audit(
                decision,
                "result.release",
                "diagnostic_report",
                report.id,
                patient_id=order.patient_id,
                event_id=event,
            )
            out = views.report(u.session, report, masks=frozenset())
            out.review_id = review.id
            return CommandResult(201, out.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="result.release",
            capability="result:release",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    # -- WF03 step 4: clinician acknowledgement --------------------------------

    def acknowledge(
        self,
        ctx: Any,
        key: str | None,
        review_id: uuid.UUID,
        expected_version: int | None,
        cmd: Acknowledge,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            review = u.get(ResultReview, review_id, lock=True)
            me = u.ctx.principal.practitioner_id
            if me is None:
                u.deny("no_practitioner", conceal=True, patient_id=review.patient_id)
            order = u.session.execute(
                select(ServiceRequest)
                .join(
                    DiagnosticReport,
                    (DiagnosticReport.tenant_id == ServiceRequest.tenant_id)
                    & (DiagnosticReport.service_request_id == ServiceRequest.id),
                )
                .where(
                    DiagnosticReport.tenant_id == u.ctx.tenant_id,
                    DiagnosticReport.id == review.report_id,
                )
            ).scalar_one()
            if me not in (review.assignee_id, order.backup_owner_id):
                u.deny("not_result_owner", conceal=True, patient_id=review.patient_id)
            u.check_version(review.version, expected_version)
            review.state = _domain(
                lambda: dx.move_review(dx.ReviewState(review.state), dx.ReviewState.ACKNOWLEDGED)
            ).value
            review.acknowledged_by_id = me
            review.acknowledged_at = u.ctx.now
            review.first_read_at = review.first_read_at or u.ctx.now
            review.acknowledgement_note = cmd.note
            review.version += 1
            u.session.flush()
            decision = u.authorize("result:acknowledge")
            event = u.emit(
                EventType.RESULT_ACKNOWLEDGED,
                "result_review",
                review.id,
                review.version,
                u.ctx.now,
                {
                    "review_id": str(review.id),
                    "report_id": str(review.report_id),
                    "patient_id": str(review.patient_id),
                },
            )
            u.audit(
                decision,
                "result.acknowledge",
                "result_review",
                review.id,
                patient_id=review.patient_id,
                event_id=event,
            )
            return CommandResult(200, views.review(review).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="result.acknowledge",
            capability="result:acknowledge",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json")
            | {"review_id": str(review_id), "v": expected_version},
            handler=handle,
            resource=("result_review", review_id),
        )

"""Merge lineage (CEDA E3, HS02). Clinical records stay on the record they
were written against, with their original authors and source IDs; reads and
access decisions for a surviving record follow its merges instead."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from astemia.adapters.db.models import MergeLink
from astemia.domain.identity import MergeAction


def merged_family(session: Session, tenant_id: uuid.UUID, patient_id: uuid.UUID) -> list[uuid.UUID]:
    """The record and every record merged into it, directly or in a chain."""
    family, frontier = [patient_id], [patient_id]
    while frontier:
        priors = session.execute(
            select(MergeLink.prior_id).where(
                MergeLink.tenant_id == tenant_id,
                MergeLink.survivor_id.in_(frontier),
                MergeLink.action == MergeAction.MERGE.value,
            )
        ).scalars()
        frontier = [p for p in priors if p not in family]
        family += frontier
    return family

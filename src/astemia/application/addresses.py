"""Patients' home addresses (CEDA revision 1.8): filed at registration, changed
with a reason, and kept as history. Each version is an ADDRESS row linked by a
PARTY ADDRESS row whose effective period says when it applied."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from astemia.adapters.db.models import Address, PartyAddress
from astemia.application.schemas import AddressHistoryOut, AddressIn, AddressOut
from astemia.domain.common import new_id

if TYPE_CHECKING:  # the write path imports the views, which import this module
    from astemia.application.write_path import Unit

HOME = "home"


def address_out(row: Address) -> AddressOut:
    return AddressOut(
        line1=row.address_line1,
        line2=row.address_line2,
        town=row.address_line3 or "",
        local_government_area=row.local_government_area,
        state=row.state,
        postcode=row.postcode,
        country=row.country,
    )


def current_home(
    session: Session, tenant_id: uuid.UUID, party_id: uuid.UUID, at: datetime
) -> tuple[PartyAddress, Address] | None:
    row = session.execute(
        select(PartyAddress, Address)
        .join(
            Address,
            (Address.tenant_id == PartyAddress.tenant_id) & (Address.id == PartyAddress.address_id),
        )
        .where(
            PartyAddress.tenant_id == tenant_id,
            PartyAddress.party_id == party_id,
            PartyAddress.address_type == HOME,
            PartyAddress.effective_from <= at,
            or_(PartyAddress.effective_to.is_(None), PartyAddress.effective_to > at),
        )
        .order_by(PartyAddress.effective_from.desc(), PartyAddress.id.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def same_address(row: Address, new: AddressIn, postcode: str) -> bool:
    return address_out(row) == AddressOut(
        line1=new.line1,
        line2=new.line2,
        town=new.town,
        local_government_area=new.local_government_area,
        state=new.state,
        postcode=postcode,
        country=new.country,
    )


def file_home(
    u: Unit, party_id: uuid.UUID, new: AddressIn, postcode: str, envelope: dict[str, Any]
) -> uuid.UUID:
    """File a new home address from now; the caller ends any current one first."""
    aid = new_id()
    u.session.add(
        Address(
            id=aid,
            address_line1=new.line1,
            address_line2=new.line2,
            address_line3=new.town,
            local_government_area=new.local_government_area,
            state=new.state,
            postcode=postcode,
            country=new.country,
            **envelope,
        )
    )
    u.session.flush()
    u.session.add(
        PartyAddress(
            id=new_id(),
            party_id=party_id,
            address_id=aid,
            address_type=HOME,
            effective_from=u.ctx.now,
            **envelope,
        )
    )
    return aid


def history(session: Session, tenant_id: uuid.UUID, party_id: uuid.UUID) -> list[AddressHistoryOut]:
    rows = session.execute(
        select(PartyAddress, Address)
        .join(
            Address,
            (Address.tenant_id == PartyAddress.tenant_id) & (Address.id == PartyAddress.address_id),
        )
        .where(PartyAddress.tenant_id == tenant_id, PartyAddress.party_id == party_id)
        .order_by(PartyAddress.effective_from.desc(), PartyAddress.id.desc())
    ).all()
    return [
        AddressHistoryOut(
            **address_out(a).model_dump(),
            address_type=link.address_type,
            effective_from=link.effective_from,
            effective_to=link.effective_to,
            current=link.effective_to is None,
            recorded_by_id=link.author_id,
        )
        for link, a in rows
    ]

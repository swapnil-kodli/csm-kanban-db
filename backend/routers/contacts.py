"""Contacts. Marking a champion departed fires the Critical alert."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from dbtypes import utcnow
from models import Company, Contact, Deal
from schemas import ContactCreate, ContactPatch
from engines import alerts as alert_engine
from engines import health as health_engine

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _deals_of(session: Session, company_id: str) -> list[Deal]:
    return session.exec(select(Deal).where(Deal.company_id == company_id)).all()


def _invalidate_threads(session: Session, company_id: str) -> None:
    """Drop the Gmail cache for every deal on this company.

    The cache is keyed by deal, not by contact, so a contact edit fans out
    across the deals naming them as POC — otherwise a corrected address keeps
    serving the previous person's threads until the TTL lapses.
    """
    from routers.google import invalidate_deal_threads

    for deal in _deals_of(session, company_id):
        invalidate_deal_threads(deal.id)


def _out(c: Contact) -> dict:
    return {
        "id": c.id,
        "is_primary": c.is_primary,
        "company_id": c.company_id,
        "name": c.name,
        "role": c.role,
        "email": c.email,
        "phone": c.phone,
        "is_champion": c.is_champion,
        "is_economic_buyer": c.is_economic_buyer,
        "status": c.status,
    }


@router.get("")
def list_contacts(
    company_id: Optional[str] = None, session: Session = Depends(get_session)
):
    query = select(Contact)
    if company_id:
        query = query.where(Contact.company_id == company_id)
    return {"contacts": [_out(c) for c in session.exec(query).all()]}


def _siblings(session: Session, company_id: str, exclude: str = "") -> list[Contact]:
    return [
        c
        for c in session.exec(
            select(Contact).where(Contact.company_id == company_id)
        ).all()
        if c.id != exclude
    ]


def _clear_other_primaries(session: Session, company_id: str, keep: str) -> None:
    for other in _siblings(session, company_id, exclude=keep):
        if other.is_primary:
            other.is_primary = False
            session.add(other)


@router.post("", status_code=201)
def create_contact(payload: ContactCreate, session: Session = Depends(get_session)):
    if session.get(Company, payload.company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")
    contact = Contact(**payload.model_dump())
    # The first contact on an company is its primary by default; there is no
    # useful state where an company has contacts and no primary among them.
    if not _siblings(session, payload.company_id):
        contact.is_primary = True
    session.add(contact)
    session.flush()
    if contact.is_primary:
        _clear_other_primaries(session, contact.company_id, keep=contact.id)
    session.commit()
    session.refresh(contact)
    _invalidate_threads(session, contact.company_id)
    return {"contact": _out(contact)}


@router.delete("/{contact_id}", status_code=200)
def delete_contact(contact_id: str, session: Session = Depends(get_session)):
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    # POC guard. `deal.poc_id` is a mandatory FK, so deleting the contact a deal
    # names would leave that deal unreadable. This blocks on deals in EVERY
    # outcome, not just active ones: a completed deal's history is exactly what
    # the company view exists to show, and it is worth nothing if the counterpart
    # has been erased. For the real-world case of someone leaving, mark them
    # `departed` — the status is already there and keeps history intact.
    poc_on = session.exec(select(Deal).where(Deal.poc_id == contact.id)).all()
    if poc_on:
        names = ", ".join(sorted(d.key for d in poc_on)[:5])
        more = f" and {len(poc_on) - 5} more" if len(poc_on) > 5 else ""
        raise HTTPException(
            status_code=409,
            detail=(
                f"{contact.name} is the POC on {names}{more}. Reassign the POC on "
                "those deals first, or mark this contact departed instead."
            ),
        )
    if contact.is_primary and _siblings(session, contact.company_id, exclude=contact.id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{contact.name} is the primary contact. Promote another contact "
                "before deleting this one."
            ),
        )
    company_id = contact.company_id
    session.delete(contact)
    session.commit()
    _invalidate_threads(session, company_id)
    return {"deleted": contact_id}


@router.patch("/{contact_id}")
def patch_contact(
    contact_id: str, payload: ContactPatch, session: Session = Depends(get_session)
):
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    data = payload.model_dump(exclude_unset=True)
    became_departed = (
        data.get("status") == "departed" and contact.status != "departed"
    )
    email_changed = "email" in data and data["email"] != contact.email

    if data.get("is_primary") is False and contact.is_primary:
        raise HTTPException(
            status_code=409,
            detail=(
                "Exactly one contact must be primary. Star another contact "
                "instead of clearing this one."
            ),
        )

    for field, value in data.items():
        setattr(contact, field, value)
    if data.get("is_primary"):
        _clear_other_primaries(session, contact.company_id, keep=contact.id)
    contact.updated_at = utcnow()
    session.add(contact)
    session.commit()
    session.refresh(contact)

    # The Gmail panel keys off the DEAL's POC email, so a changed address or a
    # changed primary has to drop the thread cache on every deal involved.
    if email_changed or "is_primary" in data:
        _invalidate_threads(session, contact.company_id)

    alerts = None
    if became_departed and contact.is_champion:
        # A departed champion is a fact about every engagement they were on, so
        # each of the company's deals is rescored, not just one.
        for deal in _deals_of(session, contact.company_id):
            health_engine.recompute_deal(session, deal)
        alerts = alert_engine.evaluate(session)

    return {"contact": _out(contact), "alerts": alerts}

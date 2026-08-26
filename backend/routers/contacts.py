"""Contacts. Marking a champion departed fires the Critical alert."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from dbtypes import utcnow
from models import Account, Contact
from schemas import ContactCreate, ContactPatch
from engines import alerts as alert_engine
from engines import health as health_engine

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _invalidate_threads(account_id: str) -> None:
    from routers.google import invalidate_account_threads

    invalidate_account_threads(account_id)


def _out(c: Contact) -> dict:
    return {
        "id": c.id,
        "is_primary": c.is_primary,
        "account_id": c.account_id,
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
    account_id: Optional[str] = None, session: Session = Depends(get_session)
):
    query = select(Contact)
    if account_id:
        query = query.where(Contact.account_id == account_id)
    return {"contacts": [_out(c) for c in session.exec(query).all()]}


def _siblings(session: Session, account_id: str, exclude: str = "") -> list[Contact]:
    return [
        c
        for c in session.exec(
            select(Contact).where(Contact.account_id == account_id)
        ).all()
        if c.id != exclude
    ]


def _clear_other_primaries(session: Session, account_id: str, keep: str) -> None:
    for other in _siblings(session, account_id, exclude=keep):
        if other.is_primary:
            other.is_primary = False
            session.add(other)


@router.post("", status_code=201)
def create_contact(payload: ContactCreate, session: Session = Depends(get_session)):
    if session.get(Account, payload.account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found")
    contact = Contact(**payload.model_dump())
    # The first contact on an account is its primary by default; there is no
    # useful state where an account has contacts and no primary among them.
    if not _siblings(session, payload.account_id):
        contact.is_primary = True
    session.add(contact)
    session.flush()
    if contact.is_primary:
        _clear_other_primaries(session, contact.account_id, keep=contact.id)
    session.commit()
    session.refresh(contact)
    _invalidate_threads(contact.account_id)
    return {"contact": _out(contact)}


@router.delete("/{contact_id}", status_code=200)
def delete_contact(contact_id: str, session: Session = Depends(get_session)):
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    if contact.is_primary and _siblings(session, contact.account_id, exclude=contact.id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{contact.name} is the primary contact. Promote another contact "
                "before deleting this one."
            ),
        )
    account_id = contact.account_id
    session.delete(contact)
    session.commit()
    _invalidate_threads(account_id)
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
        _clear_other_primaries(session, contact.account_id, keep=contact.id)
    contact.updated_at = utcnow()
    session.add(contact)
    session.commit()
    session.refresh(contact)

    # The Gmail panel keys off the primary contact's email, so any change to
    # who that is, or to their address, must drop that account's thread cache.
    if email_changed or "is_primary" in data:
        _invalidate_threads(contact.account_id)

    alerts = None
    if became_departed and contact.is_champion:
        account = session.get(Account, contact.account_id)
        if account:
            health_engine.recompute_account(session, account)
        alerts = alert_engine.evaluate(session)

    return {"contact": _out(contact), "alerts": alerts}

"""Contacts. Marking a champion departed fires the Critical alert."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from models import Account, Contact
from schemas import ContactCreate, ContactPatch
from engines import alerts as alert_engine
from engines import health as health_engine

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _out(c: Contact) -> dict:
    return {
        "id": c.id,
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


@router.post("", status_code=201)
def create_contact(payload: ContactCreate, session: Session = Depends(get_session)):
    if session.get(Account, payload.account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found")
    contact = Contact(**payload.model_dump())
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return {"contact": _out(contact)}


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
    for field, value in data.items():
        setattr(contact, field, value)
    contact.updated_at = datetime.utcnow()
    session.add(contact)
    session.commit()
    session.refresh(contact)

    alerts = None
    if became_departed and contact.is_champion:
        account = session.get(Account, contact.account_id)
        if account:
            health_engine.recompute_account(session, account)
        alerts = alert_engine.evaluate(session)

    return {"contact": _out(contact), "alerts": alerts}

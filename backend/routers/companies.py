"""Companies: the client organisation, and the detail view of the relationship.

This router answers the question the Company/Deal split was made to answer:
across everything we have done with this client, what has happened? Active work,
what was completed, what was lost, what it was all worth, and who we talk to.

Company fields are edited here and nowhere else. The deal drawer shows them as a
read-only chip — one field, one place, or the two drift.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from dbtypes import utcnow
from keygen import next_company_key
from models import (
    Company,
    Contact,
    Deal,
    HealthSnapshot,
    Risk,
    Task,
    UsageMetric,
    User,
)
from schemas import CompanyCreate, CompanyPatch, HardDeleteIn
from engines import health as health_engine
from engines import pnl as pnl_engine
from engines.attention import BookContext
from serializers import (
    CLIENT_TYPE_TITLES,
    MODE_TITLES,
    WORKSTREAM_TITLES,
    company_health_rollup,
    company_last_contact,
    company_totals,
    deal_card,
)

router = APIRouter(prefix="/companies", tags=["companies"])

OUTCOME_LABELS = {"active": "Active", "completed": "Completed", "lost": "Lost"}


def _get(session: Session, company_id: str) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def _deals_of(session: Session, company_id: str) -> list[Deal]:
    return session.exec(select(Deal).where(Deal.company_id == company_id)).all()


def _contacts_of(session: Session, company_id: str) -> list[Contact]:
    return session.exec(select(Contact).where(Contact.company_id == company_id)).all()


def _summary(session: Session, company: Company, deals: list[Deal]) -> dict:
    """One company as the list renders it."""
    live = [d for d in deals if d.archived_at is None]
    rollup = company_health_rollup(live)
    totals = company_totals(live)
    return {
        "id": company.id,
        "key": company.key,
        "name": company.name,
        "city": company.city,
        "client_type": company.client_type,
        "client_type_label": CLIENT_TYPE_TITLES.get(
            company.client_type, company.client_type
        ),
        "tags": company.tags or [],
        "archived_at": company.archived_at.isoformat() if company.archived_at else None,
        "health": rollup,
        "last_contact_at": company_last_contact(live),
        **totals,
    }


@router.get("")
def list_companies(
    include_archived: bool = False, session: Session = Depends(get_session)
):
    companies = session.exec(select(Company)).all()
    if not include_archived:
        companies = [c for c in companies if c.archived_at is None]

    deals_by_company: dict[str, list[Deal]] = {}
    for d in session.exec(select(Deal)).all():
        deals_by_company.setdefault(d.company_id, []).append(d)

    rows = [_summary(session, c, deals_by_company.get(c.id, [])) for c in companies]
    # Most active work first, then alphabetically — the list is a place to find
    # a client, not a ranking, so nothing clever is imposed on it.
    rows.sort(key=lambda r: (-r["counts"]["active"], r["name"].lower()))
    return {"companies": rows, "count": len(rows)}


@router.post("", status_code=201)
def create_company(payload: CompanyCreate, session: Session = Depends(get_session)):
    owner = session.exec(select(User)).first()
    if owner is None:
        # bootstrap.ensure_defaults() creates one at boot; this guards a
        # database someone emptied by hand.
        raise HTTPException(status_code=409, detail="No CSM user configured.")

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required.")

    company = Company(
        key=next_company_key(session, name),
        name=name,
        client_type=payload.client_type,
        city=(payload.city or "").strip() or None,
        owner_id=owner.id,
        tags=payload.tags or [],
    )
    session.add(company)

    poc_name = (payload.primary_contact_name or "").strip()
    if poc_name:
        session.add(
            Contact(
                company_id=company.id,
                name=poc_name,
                role=(payload.primary_contact_role or "").strip(),
                email=(payload.primary_contact_email or "").strip() or None,
                phone=(payload.primary_contact_phone or "").strip() or None,
                is_primary=True,
            )
        )

    session.commit()
    session.refresh(company)
    return {"company": _summary(session, company, [])}


@router.get("/{company_id}")
def get_company(company_id: str, session: Session = Depends(get_session)):
    """The company detail view.

    Deal history is grouped by outcome rather than listed flat, because "three
    active, one completed, two lost" is the shape of the relationship and a
    single ordered list buries it.
    """
    company = _get(session, company_id)
    owner = session.get(User, company.owner_id)
    deals = _deals_of(session, company_id)
    live = [d for d in deals if d.archived_at is None]
    contacts = _contacts_of(session, company_id)

    ctx = BookContext(session)
    poc_ids = {d.poc_id for d in deals}

    def deal_row(d: Deal) -> dict:
        poc = next((c for c in contacts if c.id == d.poc_id), None)
        parts = pnl_engine.compute(d)
        column = ctx.column_by_id.get(d.column_id)
        band = health_engine.effective_band(d)
        return {
            "id": d.id,
            "key": d.key,
            "name": d.name,
            "mode": d.mode,
            "mode_label": MODE_TITLES.get(d.mode, d.mode),
            "workstream": d.workstream,
            "workstream_label": WORKSTREAM_TITLES.get(d.workstream, d.workstream),
            "column_label": column.label if column else "Unassigned",
            "column_color": column.color if column else "#6b6b6b",
            "outcome": d.outcome,
            "outcome_label": OUTCOME_LABELS.get(d.outcome, d.outcome),
            "outcome_at": d.outcome_at.isoformat() if d.outcome_at else None,
            "outcome_reason": d.outcome_reason,
            # Health is shown only for active deals. A band frozen at the moment
            # a deal was closed describes nothing anyone can act on, and sitting
            # in a history table it reads as current.
            "health_band": band if d.outcome == "active" else None,
            "health_score": d.health_score if d.outcome == "active" else None,
            "quoted_total": d.quoted_total,
            "revenue_recognised": d.revenue_recognised,
            "margin_pct": parts["margin_pct"],
            "poc": {"id": poc.id, "name": poc.name, "email": poc.email} if poc else None,
            "last_contact_at": d.last_contact_at.isoformat()
            if d.last_contact_at
            else None,
        }

    by_outcome: dict[str, list[dict]] = {"active": [], "completed": [], "lost": []}
    for d in sorted(live, key=lambda d: d.key):
        by_outcome.setdefault(d.outcome, []).append(deal_row(d))

    return {
        "company": {
            **_summary(session, company, deals),
            "owner": {"id": owner.id, "name": owner.name, "initials": owner.initials}
            if owner
            else None,
        },
        "deals": by_outcome,
        "contacts": [
            {
                "id": c.id,
                "name": c.name,
                "role": c.role,
                "email": c.email,
                "phone": c.phone,
                "is_primary": c.is_primary,
                "is_champion": c.is_champion,
                "is_economic_buyer": c.is_economic_buyer,
                "status": c.status,
                # Surfaced so the UI can explain why deleting is refused before
                # someone tries it, rather than only in the 409 afterwards.
                "is_poc": c.id in poc_ids,
                "poc_on": sorted(d.key for d in deals if d.poc_id == c.id),
            }
            for c in contacts
        ],
    }


@router.patch("/{company_id}")
def patch_company(
    company_id: str, payload: CompanyPatch, session: Session = Depends(get_session)
):
    company = _get(session, company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    company.updated_at = utcnow()
    session.add(company)
    session.commit()
    session.refresh(company)
    return {"company": _summary(session, company, _deals_of(session, company_id))}


# --- soft delete, trash, restore, hard delete --------------------------------

def _trash_row(session: Session, company: Company) -> dict:
    deals = _deals_of(session, company.id)
    contacts = _contacts_of(session, company.id)
    return {
        "id": company.id,
        "key": company.key,
        "name": company.name,
        "client_type_label": CLIENT_TYPE_TITLES.get(
            company.client_type, company.client_type
        ),
        "city": company.city,
        "archived_at": company.archived_at.isoformat() if company.archived_at else None,
        "quoted_total": sum(int(d.quoted_total or 0) for d in deals),
        "owns": {
            "deals": len(deals),
            "contacts": len(contacts),
            "tasks": len(
                session.exec(
                    select(Task).where(Task.deal_id.in_([d.id for d in deals] or [""]))
                ).all()
            ),
        },
        "restorable": True,
    }


@router.get("/trash/list")
def list_trash(session: Session = Depends(get_session)):
    """Soft-deleted companies, most recently deleted first.

    Two-segment path, declared above /companies/{company_id}, so the
    parameterised route cannot swallow it.
    """
    rows = session.exec(
        select(Company).where(Company.archived_at != None)  # noqa: E711
    ).all()
    rows.sort(key=lambda c: c.archived_at or utcnow(), reverse=True)
    return {"companies": [_trash_row(session, c) for c in rows], "count": len(rows)}


@router.delete("/{company_id}")
def archive_company(company_id: str, session: Session = Depends(get_session)):
    """Soft delete, cascading to the company's deals.

    Deleting a client has to take its engagements off the board with it —
    leaving them behind would show cards belonging to a client that no longer
    appears anywhere. Restore brings back exactly the set that came out, so the
    deals archived *by* this action are marked and nothing else is touched.
    """
    company = _get(session, company_id)
    if company.archived_at is not None:
        raise HTTPException(status_code=409, detail="Company is already in Trash.")

    now = utcnow()
    cascaded = 0
    for deal in _deals_of(session, company_id):
        if deal.archived_at is None:
            deal.archived_at = now
            deal.pinned = False
            deal.updated_at = now
            session.add(deal)
            cascaded += 1

    company.archived_at = now
    company.updated_at = now
    session.add(company)
    session.commit()
    session.refresh(company)
    return {"archived": _trash_row(session, company), "deals_archived": cascaded}


@router.post("/{company_id}/restore")
def restore_company(company_id: str, session: Session = Depends(get_session)):
    """Back onto the board, with the deals that went down with it.

    Only deals archived at the same instant as the company come back. A deal
    someone deleted separately, before the company was deleted, stays in Trash —
    restoring the client must not silently undo a decision made about one of its
    engagements.
    """
    company = _get(session, company_id)
    if company.archived_at is None:
        raise HTTPException(status_code=409, detail="Company is not in Trash.")

    archived_at = company.archived_at
    now = utcnow()
    restored = 0
    for deal in _deals_of(session, company_id):
        if deal.archived_at == archived_at:
            deal.archived_at = None
            deal.updated_at = now
            session.add(deal)
            restored += 1

    company.archived_at = None
    company.updated_at = now
    session.add(company)
    session.commit()
    session.refresh(company)

    health_engine.recompute_all(session)
    return {"company": _summary(session, company, _deals_of(session, company_id)),
            "deals_restored": restored}


@router.post("/{company_id}/hard-delete")
def hard_delete_company(
    company_id: str, payload: HardDeleteIn, session: Session = Depends(get_session)
):
    """Irreversible, and the largest destructive action in the product.

    Takes the company, its contacts, every one of its deals and everything those
    deals own. Only from Trash, only with the key typed back.
    """
    company = _get(session, company_id)
    if company.archived_at is None:
        raise HTTPException(
            status_code=409,
            detail="Move the company to Trash before deleting it permanently.",
        )
    if payload.confirm_key.strip().upper() != company.key.upper():
        raise HTTPException(
            status_code=422, detail=f"Type {company.key} exactly to confirm."
        )

    deals = _deals_of(session, company_id)
    deal_ids = [d.id for d in deals]

    if deal_ids:
        # activity first: it references task.id, so deleting tasks under it
        # would strand that reference.
        from models import Activity

        for row in session.exec(
            select(Activity).where(Activity.deal_id.in_(deal_ids))
        ).all():
            session.delete(row)
        session.commit()

        for model in (Task, HealthSnapshot, Risk, UsageMetric):
            for row in session.exec(
                select(model).where(model.deal_id.in_(deal_ids))
            ).all():
                session.delete(row)

    for deal in deals:
        session.delete(deal)
    # Contacts last: deal.poc_id points at them, so they cannot go first.
    for contact in _contacts_of(session, company_id):
        session.delete(contact)

    key, name = company.key, company.name
    session.delete(company)
    session.commit()
    return {
        "deleted": {"id": company_id, "key": key, "name": name, "deals": len(deals)}
    }

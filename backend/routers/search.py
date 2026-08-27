"""Global search across companies, deals, contacts and tasks.

Companies and deals are separate result groups on purpose. Searching "Prestige"
should offer both the client and its engagements, because which one you want
depends on what you are about to do — open the relationship, or open the work.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from db import get_session
from models import Company, Contact, Deal, Task
from engines import health as health_engine
from serializers import BAND_DOTS, MODE_TITLES, TASK_TYPE_TITLES, WORKSTREAM_TITLES

router = APIRouter(tags=["search"])

LIMIT = 8


@router.get("/search")
def search(q: str = Query("", max_length=120), session: Session = Depends(get_session)):
    needle = q.strip().lower()
    empty = {"companies": [], "deals": [], "contacts": [], "tasks": [], "query": q}
    if len(needle) < 1:
        return empty

    companies = session.exec(
        select(Company).where(Company.archived_at == None)  # noqa: E711
    ).all()
    company_by_id = {c.id: c for c in companies}

    # Deals on an archived company are unreachable, so they are excluded too —
    # otherwise search offers a card that opens onto nothing.
    deals = [
        d
        for d in session.exec(
            select(Deal).where(Deal.archived_at == None)  # noqa: E711
        ).all()
        if d.company_id in company_by_id
    ]
    deal_by_id = {d.id: d for d in deals}

    def company_out(c: Company) -> dict:
        return {
            "id": c.id, "key": c.key, "name": c.name, "city": c.city,
            "client_type": c.client_type,
            "deal_count": sum(
                1 for d in deals if d.company_id == c.id and d.outcome == "active"
            ),
        }

    company_hits = [
        company_out(c)
        for c in companies
        if needle in f"{c.name} {c.key} {c.city or ''}".lower()
    ][:LIMIT]

    deal_hits = [
        {
            "id": d.id,
            "key": d.key,
            "name": d.name,
            "company_id": d.company_id,
            "company_name": company_by_id[d.company_id].name,
            "mode": d.mode,
            "mode_label": MODE_TITLES.get(d.mode, d.mode),
            "workstream_label": WORKSTREAM_TITLES.get(d.workstream, d.workstream),
            "outcome": d.outcome,
            "quoted_total": d.quoted_total,
            "health_band": health_engine.effective_band(d),
            "health_dot": BAND_DOTS[health_engine.effective_band(d)],
            "health_score": d.health_score,
        }
        for d in deals
        if needle in
        f"{d.name} {d.key} {company_by_id[d.company_id].name}".lower()
    ][:LIMIT]

    contact_hits = [
        {
            "id": c.id,
            "name": c.name,
            "role": c.role,
            "company_id": c.company_id,
            "company_name": company_by_id[c.company_id].name
            if c.company_id in company_by_id
            else "",
            "status": c.status,
        }
        for c in session.exec(select(Contact)).all()
        if c.company_id in company_by_id
        and needle in f"{c.name} {c.role} {c.email or ''}".lower()
    ][:LIMIT]

    task_hits = [
        {
            "id": t.id,
            "title": t.title,
            "bucket": t.bucket,
            "status": t.status,
            "due_date": t.due_date.isoformat(),
            "type_label": TASK_TYPE_TITLES.get(t.type, t.type),
            "deal_id": t.deal_id,
            "deal_name": deal_by_id[t.deal_id].name if t.deal_id in deal_by_id else "",
        }
        for t in session.exec(select(Task)).all()
        if t.deal_id in deal_by_id and needle in t.title.lower()
    ][:LIMIT]

    return {
        "query": q,
        "companies": company_hits,
        "deals": deal_hits,
        "contacts": contact_hits,
        "tasks": task_hits,
    }

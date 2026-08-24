"""Global search across accounts, contacts, tasks and activity text."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from db import get_session
from models import Account, Activity, Contact, Task
from engines import health as health_engine
from serializers import BAND_DOTS, TASK_TYPE_TITLES

router = APIRouter(tags=["search"])

LIMIT = 8


@router.get("/search")
def search(q: str = Query("", max_length=120), session: Session = Depends(get_session)):
    needle = q.strip().lower()
    if len(needle) < 1:
        return {"accounts": [], "contacts": [], "tasks": [], "activities": [], "query": q}

    accounts = session.exec(select(Account)).all()
    by_id = {a.id: a for a in accounts}

    account_hits = [
        {
            "id": a.id,
            "key": a.key,
            "name": a.name,
            "segment": a.segment,
            "city": a.city,
            "arr": a.arr,
            "health_band": health_engine.effective_band(a),
            "health_dot": BAND_DOTS[health_engine.effective_band(a)],
            "health_score": a.health_score,
        }
        for a in accounts
        if needle in f"{a.name} {a.key} {a.city or ''}".lower()
    ][:LIMIT]

    contact_hits = [
        {
            "id": c.id,
            "name": c.name,
            "role": c.role,
            "account_id": c.account_id,
            "account_name": by_id[c.account_id].name if c.account_id in by_id else "",
            "status": c.status,
        }
        for c in session.exec(select(Contact)).all()
        if needle in f"{c.name} {c.role} {c.email or ''}".lower()
    ][:LIMIT]

    task_hits = [
        {
            "id": t.id,
            "title": t.title,
            "bucket": t.bucket,
            "status": t.status,
            "due_date": t.due_date.isoformat(),
            "type_label": TASK_TYPE_TITLES.get(t.type, t.type),
            "account_id": t.account_id,
            "account_name": by_id[t.account_id].name if t.account_id in by_id else "",
        }
        for t in session.exec(select(Task)).all()
        if needle in t.title.lower()
    ][:LIMIT]

    activity_hits = [
        {
            "id": a.id,
            "type": a.type,
            "summary": a.summary,
            "occurred_at": a.occurred_at.isoformat(),
            "account_id": a.account_id,
            "account_name": by_id[a.account_id].name if a.account_id in by_id else "",
        }
        for a in session.exec(
            select(Activity).order_by(Activity.occurred_at.desc())  # type: ignore[attr-defined]
        ).all()
        if needle in f"{a.summary} {a.body or ''}".lower()
    ][:LIMIT]

    return {
        "query": q,
        "accounts": account_hits,
        "contacts": contact_hits,
        "tasks": task_hits,
        "activities": activity_hits,
    }

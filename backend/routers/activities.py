"""Activity logging — the hot path. One round trip logs the activity and,
optionally, the next-action task it spawns."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from models import Account, Activity, Task, User
from schemas import ActivityCreate
from engines import health as health_engine
from serializers import task_card

router = APIRouter(tags=["activities"])

DEFAULT_DUE_DAYS = {"today": 0, "this_week": 3, "follow_up": 10, "waiting": 7, "done": 0}


@router.post("/accounts/{account_id}/activities", status_code=201)
def log_activity(
    account_id: str, payload: ActivityCreate, session: Session = Depends(get_session)
):
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    owner = session.exec(select(User)).first()
    if owner is None:
        raise HTTPException(status_code=409, detail="No CSM seeded")

    created_task = None
    if payload.create_task:
        spec = payload.create_task
        due = spec.due_date or (
            date.today() + timedelta(days=DEFAULT_DUE_DAYS.get(spec.bucket, 3))
        )
        created_task = Task(
            account_id=account.id,
            title=spec.title.strip(),
            type=spec.type,
            bucket=spec.bucket,
            due_date=due,
            status="open",
            priority=spec.priority,
            owner_id=owner.id,
            sort_index=float(datetime.utcnow().timestamp()),
        )
        session.add(created_task)
        session.flush()

    activity = Activity(
        account_id=account.id,
        contact_id=payload.contact_id,
        type=payload.type,
        occurred_at=payload.occurred_at or datetime.utcnow(),
        summary=payload.summary.strip(),
        body=payload.body,
        created_task_id=created_task.id if created_task else None,
    )
    session.add(activity)
    session.commit()
    session.refresh(activity)

    # Activity touches engagement, so health recomputes on the write.
    health_engine.recompute_account(session, account)

    return {
        "activity": {
            "id": activity.id,
            "type": activity.type,
            "occurred_at": activity.occurred_at.isoformat(),
            "summary": activity.summary,
            "body": activity.body,
            "contact_id": activity.contact_id,
            "created_task_id": activity.created_task_id,
        },
        "task": task_card(created_task, account) if created_task else None,
        "health": {
            "score": account.health_score,
            "band": health_engine.effective_band(account),
        },
    }

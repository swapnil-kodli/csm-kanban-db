"""Tasks. account_id is required — no orphan tasks, ever."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from db import get_session
from dbtypes import utcnow
from models import Account, Task, User
from schemas import TaskCreate, TaskPatch
from serializers import task_card

router = APIRouter(prefix="/tasks", tags=["tasks"])

DEFAULT_DUE_DAYS = {"today": 0, "this_week": 3, "follow_up": 10, "waiting": 7, "done": 0}


@router.get("")
def list_tasks(
    bucket: Optional[str] = None,
    status: Optional[str] = None,
    account_id: Optional[str] = None,
    overdue: bool = False,
    session: Session = Depends(get_session),
):
    query = select(Task)
    if bucket:
        query = query.where(Task.bucket == bucket)
    if status:
        query = query.where(Task.status == status)
    if account_id:
        query = query.where(Task.account_id == account_id)
    tasks = session.exec(query).all()
    if overdue:
        today = date.today()
        tasks = [t for t in tasks if t.status == "open" and t.due_date < today]
    accounts = {
        a.id: a
        for a in session.exec(
            select(Account).where(Account.archived_at == None)  # noqa: E711
        ).all()
    }
    cards = [task_card(t, accounts[t.account_id]) for t in tasks if t.account_id in accounts]
    cards.sort(key=lambda c: (c["due_date"], c["sort_index"]))
    return {"tasks": cards, "count": len(cards)}


@router.post("", status_code=201)
def create_task(payload: TaskCreate, session: Session = Depends(get_session)):
    account = session.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    owner = session.exec(select(User)).first()
    if owner is None:
        raise HTTPException(status_code=409, detail="No CSM seeded")

    due = payload.due_date or (
        date.today() + timedelta(days=DEFAULT_DUE_DAYS.get(payload.bucket, 3))
    )
    task = Task(
        account_id=account.id,
        title=payload.title.strip(),
        type=payload.type,
        bucket=payload.bucket,
        due_date=due,
        status="open",
        priority=payload.priority,
        owner_id=owner.id,
        provenance=payload.provenance,
        sort_index=float(utcnow().timestamp()),
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return {"task": task_card(task, account)}


@router.patch("/{task_id}")
def patch_task(task_id: str, payload: TaskPatch, session: Session = Depends(get_session)):
    """Bucket change is the drag-drop write in MY WORK."""
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(task, field, value)

    # Bucket and status stay consistent in both directions.
    if data.get("bucket") == "done" and "status" not in data:
        task.status = "done"
    if data.get("status") == "done" and "bucket" not in data:
        task.bucket = "done"
    if data.get("bucket") and data["bucket"] != "done" and task.status == "done":
        task.status = "open"
        task.completed_at = None

    task.completed_at = utcnow() if task.status == "done" else None
    task.updated_at = utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)

    account = session.get(Account, task.account_id)
    return {"task": task_card(task, account)}


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    session.delete(task)
    session.commit()

"""The five my-book counters, and the Needs Attention queue.

Exactly five metrics, all my-book counts, every one clickable and carrying the
filter it applies. NRR / GRR / churn rate / CLV are deliberately absent: that is
the executive-dashboard trap (research §17, §21).
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from db import get_session
from models import Account, Task
from engines.attention import BookContext, needs_attention
from serializers import account_card, next_actions_by_account

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def get_metrics(session: Session = Depends(get_session)):
    ctx = BookContext(session)
    today = date.today()
    active = [a for a in ctx.accounts if a.lifecycle_stage != "closed"]

    attention_rows = needs_attention(ctx)

    renewing = [
        a
        for a in active
        if (d := ctx.days_to_renewal(a.id)) is not None and 0 <= d <= 30
    ]
    renewal_arr = sum(a.arr for a in renewing)

    open_tasks = session.exec(select(Task).where(Task.status == "open")).all()
    due_today = [t for t in open_tasks if t.due_date == today]
    overdue = [t for t in open_tasks if t.due_date < today]
    oldest_overdue = max(((today - t.due_date).days for t in overdue), default=0)

    return {
        "metrics": [
            {
                "key": "needs_attention",
                "label": "Needs Attention",
                "value": len(attention_rows),
                "format": "count",
                "sub": "accounts flagged",
                "filters": {"attention": True},
                "view": None,
            },
            {
                "key": "book_arr",
                "label": "Book ARR",
                "value": sum(a.arr for a in active),
                "format": "inr",
                "sub": f"{len(active)} accounts",
                "filters": {},
                "view": None,
            },
            {
                "key": "renewals_30",
                "label": "Renewals ≤30d",
                "value": len(renewing),
                "format": "count",
                "sub_value": renewal_arr,
                "sub_format": "inr_at_stake",
                "sub": "at stake",
                "filters": {"renewal_window": 30},
                "view": None,
            },
            {
                "key": "open_tasks",
                "label": "Open Tasks",
                "value": len(open_tasks),
                "format": "count",
                "sub": f"{len(due_today)} due today",
                "filters": {"task_status": "open"},
                "view": "work",
            },
            {
                "key": "overdue",
                "label": "Overdue",
                "value": len(overdue),
                "format": "count",
                "sub": f"oldest {oldest_overdue} days" if overdue else "nothing overdue",
                "filters": {"overdue": True},
                "view": "work",
            },
        ]
    }


@router.get("/attention")
def get_attention(
    limit: int = Query(10, ge=1, le=50), session: Session = Depends(get_session)
):
    """Who needs my attention — recomputed on read, worst first."""
    ctx = BookContext(session)
    next_actions = next_actions_by_account(session)
    rows = needs_attention(ctx)[:limit]
    return {
        "accounts": [
            {
                **account_card(ctx, account, next_actions.get(account.id), scored),
                "attention_terms": [t for t in scored["terms"] if t["value"]],
            }
            for account, scored in rows
        ],
        "count": len(rows),
    }

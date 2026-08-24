"""Accounts list, the 360 payload, patches, and manual health override."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from db import get_session
from models import (
    Account,
    Activity,
    Contact,
    HealthSnapshot,
    Milestone,
    Risk,
    Subscription,
    Task,
    UsageMetric,
    User,
)
from schemas import AccountPatch, HealthOverrideIn, MilestonePatch
from engines import alerts as alert_engine
from engines import health as health_engine
from engines.attention import BookContext, score_account
from serializers import (
    BAND_DOTS,
    SEGMENT_TITLES,
    STAGE_DOTS,
    STAGE_TITLES,
    TASK_TYPE_TITLES,
    account_card,
    account_matches,
    next_actions_by_account,
    parse_filters,
    task_card,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _get(session: Session, account_id: str) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("")
def list_accounts(
    filters: Optional[str] = None,
    session: Session = Depends(get_session),
):
    f = parse_filters(filters)
    ctx = BookContext(session)
    next_actions = next_actions_by_account(session)
    cards = [
        account_card(ctx, a, next_actions.get(a.id))
        for a in ctx.accounts
        if account_matches(ctx, a, f)
    ]
    cards.sort(key=lambda c: (not c["pinned"], -c["attention_score"], c["name"]))
    return {"accounts": cards, "count": len(cards)}


@router.get("/{account_id}")
def get_account(account_id: str, session: Session = Depends(get_session)):
    account = _get(session, account_id)
    ctx = BookContext(session)
    scored = score_account(ctx, account)
    flags = alert_engine.state_flags(ctx, account)
    next_actions = next_actions_by_account(session)
    owner = session.get(User, account.owner_id)

    contacts = session.exec(
        select(Contact).where(Contact.account_id == account_id)
    ).all()
    subscription = session.exec(
        select(Subscription).where(Subscription.account_id == account_id)
    ).first()
    tasks = session.exec(
        select(Task).where(Task.account_id == account_id)
    ).all()
    activities = session.exec(
        select(Activity)
        .where(Activity.account_id == account_id)
        .order_by(Activity.occurred_at.desc())  # type: ignore[attr-defined]
        .limit(50)
    ).all()
    snapshots = session.exec(
        select(HealthSnapshot)
        .where(HealthSnapshot.account_id == account_id)
        .order_by(HealthSnapshot.captured_on.desc())  # type: ignore[attr-defined]
        .limit(90)
    ).all()
    risks = session.exec(select(Risk).where(Risk.account_id == account_id)).all()
    milestones = session.exec(
        select(Milestone)
        .where(Milestone.account_id == account_id)
        .order_by(Milestone.sort_index)  # type: ignore[arg-type]
    ).all()
    usage = session.exec(
        select(UsageMetric)
        .where(UsageMetric.account_id == account_id)
        .order_by(UsageMetric.captured_on.desc())  # type: ignore[attr-defined]
        .limit(30)
    ).all()

    latest = snapshots[0] if snapshots else None
    contacts_by_id = {c.id: c for c in contacts}
    today = date.today()

    override_age = health_engine.override_age_days(account)

    return {
        "card": account_card(ctx, account, next_actions.get(account.id), scored),
        "account": {
            "id": account.id,
            "key": account.key,
            "name": account.name,
            "segment": account.segment,
            "segment_label": SEGMENT_TITLES.get(account.segment, account.segment),
            "city": account.city,
            "lifecycle_stage": account.lifecycle_stage,
            "lifecycle_label": STAGE_TITLES.get(account.lifecycle_stage, ""),
            "lifecycle_dot": STAGE_DOTS.get(account.lifecycle_stage, "s-adopting"),
            "closed_reason": account.closed_reason,
            "arr": account.arr,
            "tags": account.tags or [],
            "expansion_flag": account.expansion_flag,
            "pinned": account.pinned,
            "entitled_seats": account.entitled_seats,
            "owner": {"id": owner.id, "name": owner.name, "initials": owner.initials}
            if owner
            else None,
            "handoff_received_at": account.handoff_received_at.isoformat()
            if account.handoff_received_at
            else None,
            "last_contact_at": account.last_contact_at.isoformat()
            if account.last_contact_at
            else None,
            "days_since_contact": flags["days_since_contact"],
        },
        "health": {
            "score": account.health_score,
            "computed_band": account.health_band,
            "computed_band_label": health_engine.BAND_LABELS[account.health_band],
            "effective_band": health_engine.effective_band(account),
            "effective_band_label": health_engine.BAND_LABELS[
                health_engine.effective_band(account)
            ],
            "dot": BAND_DOTS[health_engine.effective_band(account)],
            "velocity": ctx.velocity_by_account.get(account.id),
            "override": (
                {
                    "band": account.health_manual_override,
                    "band_label": health_engine.BAND_LABELS[
                        account.health_manual_override
                    ],
                    "reason": account.health_override_reason,
                    "set_at": account.health_override_at.isoformat()
                    if account.health_override_at
                    else None,
                    "age_days": override_age,
                    # Overrides never expire silently.
                    "stale": override_age is not None and override_age > 60,
                }
                if account.health_manual_override
                else None
            ),
            "components": (
                {
                    "usage": latest.usage,
                    "engagement": latest.engagement,
                    "support": latest.support,
                    "sentiment": latest.sentiment,
                }
                if latest
                else None
            ),
            "weights": health_engine.WEIGHTS,
            "snapshots": [
                {"date": s.captured_on.isoformat(), "score": s.score}
                for s in reversed(snapshots)
            ],
        },
        "attention": scored,
        "subscription": (
            {
                "id": subscription.id,
                "start_date": subscription.start_date.isoformat()
                if subscription.start_date
                else None,
                "renewal_date": subscription.renewal_date.isoformat(),
                "days_to_renewal": (subscription.renewal_date - today).days,
                "auto_renew": subscription.auto_renew,
                "status": subscription.status,
                "line_items": subscription.line_items or [],
            }
            if subscription
            else None
        ),
        "contacts": [
            {
                "id": c.id,
                "name": c.name,
                "role": c.role,
                "email": c.email,
                "phone": c.phone,
                "is_champion": c.is_champion,
                "is_economic_buyer": c.is_economic_buyer,
                "status": c.status,
            }
            for c in contacts
        ],
        "tasks": [task_card(t, account) for t in sorted(tasks, key=lambda t: t.due_date)],
        "activities": [
            {
                "id": a.id,
                "type": a.type,
                "occurred_at": a.occurred_at.isoformat(),
                "summary": a.summary,
                "body": a.body,
                "contact_id": a.contact_id,
                "contact_name": contacts_by_id[a.contact_id].name
                if a.contact_id and a.contact_id in contacts_by_id
                else None,
                "created_task_id": a.created_task_id,
            }
            for a in activities
        ],
        "risks": [
            {
                "id": r.id,
                "type": r.type,
                "severity": r.severity,
                "status": r.status,
                "note": r.note,
                "opened_at": r.opened_at.isoformat(),
            }
            for r in risks
        ],
        "milestones": [
            {
                "id": m.id,
                "label": m.label,
                "status": m.status,
                "target_date": m.target_date.isoformat() if m.target_date else None,
                "overdue": bool(
                    m.status == "pending" and m.target_date and m.target_date < today
                ),
            }
            for m in milestones
        ],
        "usage": [
            {
                "date": u.captured_on.isoformat(),
                "active_users": u.active_users,
                "sessions": u.sessions,
                "feature_adoption_pct": u.feature_adoption_pct,
            }
            for u in reversed(usage)
        ],
    }


@router.patch("/{account_id}")
def patch_account(
    account_id: str, payload: AccountPatch, session: Session = Depends(get_session)
):
    account = _get(session, account_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(account, field, value)
    if account.lifecycle_stage != "closed":
        account.closed_reason = None
    elif account.closed_reason is None:
        account.closed_reason = "churned"
    if account.lifecycle_stage == "ready_for_onboarding" and not account.handoff_received_at:
        account.handoff_received_at = datetime.utcnow()
    account.updated_at = datetime.utcnow()
    session.add(account)
    session.commit()

    health_engine.recompute_account(session, account)
    ctx = BookContext(session)
    next_actions = next_actions_by_account(session)
    return {"account": account_card(ctx, account, next_actions.get(account.id))}


@router.post("/{account_id}/health-override")
def set_health_override(
    account_id: str, payload: HealthOverrideIn, session: Session = Depends(get_session)
):
    """The CSM's judgement beats the score — but it must be recorded."""
    account = _get(session, account_id)
    account.health_manual_override = payload.band
    account.health_override_reason = payload.reason.strip()
    account.health_override_at = datetime.utcnow()
    account.updated_at = datetime.utcnow()
    session.add(account)
    session.commit()
    session.refresh(account)

    ctx = BookContext(session)
    next_actions = next_actions_by_account(session)
    return {"account": account_card(ctx, account, next_actions.get(account.id))}


@router.delete("/{account_id}/health-override")
def clear_health_override(account_id: str, session: Session = Depends(get_session)):
    account = _get(session, account_id)
    account.health_manual_override = None
    account.health_override_reason = None
    account.health_override_at = None
    account.updated_at = datetime.utcnow()
    session.add(account)
    session.commit()
    session.refresh(account)

    ctx = BookContext(session)
    next_actions = next_actions_by_account(session)
    return {"account": account_card(ctx, account, next_actions.get(account.id))}


@router.patch("/{account_id}/milestones/{milestone_id}")
def patch_milestone(
    account_id: str,
    milestone_id: str,
    payload: MilestonePatch,
    session: Session = Depends(get_session),
):
    milestone = session.get(Milestone, milestone_id)
    if milestone is None or milestone.account_id != account_id:
        raise HTTPException(status_code=404, detail="Milestone not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(milestone, field, value)
    milestone.updated_at = datetime.utcnow()
    session.add(milestone)
    session.commit()
    session.refresh(milestone)
    return {
        "milestone": {
            "id": milestone.id,
            "label": milestone.label,
            "status": milestone.status,
            "target_date": milestone.target_date.isoformat()
            if milestone.target_date
            else None,
            "overdue": bool(
                milestone.status == "pending"
                and milestone.target_date
                and milestone.target_date < date.today()
            ),
        }
    }

"""Accounts list, the drawer payload, patches, and manual health override."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from models import (
    Account,
    Activity,
    Contact,
    HealthSnapshot,
    Risk,
    Task,
    UsageMetric,
    User,
)
from schemas import AccountPatch, HealthOverrideIn
from engines import alerts as alert_engine
from engines import health as health_engine
from engines import pnl as pnl_engine
from engines.attention import BookContext, score_account
from serializers import (
    BAND_DOTS,
    CLIENT_TYPE_TITLES,
    COLUMN_DOTS,
    COLUMN_TITLES,
    COMM_MODE_TITLES,
    MODE_TITLES,
    WORKSTREAM_GLYPHS,
    WORKSTREAM_TITLES,
    account_card,
    account_matches,
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
def list_accounts(filters: Optional[str] = None, session: Session = Depends(get_session)):
    f = parse_filters(filters)
    ctx = BookContext(session)
    cards = [account_card(ctx, a) for a in ctx.accounts if account_matches(ctx, a, f)]
    cards.sort(key=lambda c: (not c["pinned"], -c["attention_score"], c["name"]))
    return {"accounts": cards, "count": len(cards)}


@router.get("/{account_id}")
def get_account(account_id: str, session: Session = Depends(get_session)):
    account = _get(session, account_id)
    ctx = BookContext(session)
    scored = score_account(ctx, account)
    flags = alert_engine.state_flags(ctx, account)
    owner = session.get(User, account.owner_id)

    contacts = session.exec(select(Contact).where(Contact.account_id == account_id)).all()
    tasks = session.exec(select(Task).where(Task.account_id == account_id)).all()
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
    usage = session.exec(
        select(UsageMetric)
        .where(UsageMetric.account_id == account_id)
        .order_by(UsageMetric.captured_on.desc())  # type: ignore[attr-defined]
        .limit(30)
    ).all()

    latest = snapshots[0] if snapshots else None
    contacts_by_id = {c.id: c for c in contacts}
    override_age = health_engine.override_age_days(account)
    comm_modes = account.comm_modes or []

    return {
        "card": account_card(ctx, account, scored),
        # --- Overview panel -------------------------------------------------
        "account": {
            "id": account.id,
            "key": account.key,
            "name": account.name,
            "city": account.city,
            "column": account.column,
            "column_label": COLUMN_TITLES.get(account.column, account.column),
            "column_dot": COLUMN_DOTS.get(account.column, "s-adopting"),
            "days_in_column": flags["days_in_column"],
            "column_stalled": flags["column_stalled"],
            "workstream": account.workstream,
            "workstream_label": WORKSTREAM_TITLES.get(account.workstream, account.workstream),
            "workstream_glyph": WORKSTREAM_GLYPHS.get(account.workstream, "◔"),
            "mode": account.mode,
            "mode_label": MODE_TITLES.get(account.mode, account.mode),
            "client_type": account.client_type,
            "client_type_label": CLIENT_TYPE_TITLES.get(account.client_type, account.client_type),
            "size_band": flags["size_band"],
            "tags": account.tags or [],
            "pinned": account.pinned,
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
            "no_contact": flags["no_contact"],
            "stalled_handoff": flags["stalled_handoff"],
        },
        # --- POC panel ------------------------------------------------------
        "poc": {
            "name": account.poc_name,
            "email": account.poc_email,
            "phone": account.poc_phone,
        },
        # --- Mode of Communication -----------------------------------------
        "comm_modes": [
            {"value": m, "label": COMM_MODE_TITLES.get(m, m)} for m in comm_modes
        ],
        # Gmail panel renders only when email is a channel and a POC email exists.
        "show_email_threads": "email" in comm_modes and bool(account.poc_email),
        # --- Health Check panel ---------------------------------------------
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
            "note": account.health_note,
            "override": (
                {
                    "band": account.health_manual_override,
                    "band_label": health_engine.BAND_LABELS[account.health_manual_override],
                    "reason": account.health_override_reason,
                    "set_at": account.health_override_at.isoformat()
                    if account.health_override_at
                    else None,
                    "age_days": override_age,
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
        # --- Costing + PNL panels (computed server-side, never stored) ------
        "commercials": pnl_engine.compute(account),
        "attention": scored,
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


@router.get("/{account_id}/email-threads")
def email_threads(
    account_id: str, limit: int = 20, session: Session = Depends(get_session)
):
    """Always 200 with a state the panel can render. A Gmail outage must never
    block the drawer from opening or the board from rendering."""
    from routers.google import fetch_threads

    account = _get(session, account_id)
    return fetch_threads(session, account, limit)


@router.patch("/{account_id}")
def patch_account(
    account_id: str, payload: AccountPatch, session: Session = Depends(get_session)
):
    account = _get(session, account_id)
    data = payload.model_dump(exclude_unset=True)

    previous_mode = account.mode
    previous_column = account.column

    for field, value in data.items():
        if field in ("quoted_line_items", "cost_items"):
            value = [v if isinstance(v, dict) else v.model_dump() for v in value]
        setattr(account, field, value)

    # quoted_total is always derived from the line items — never trusted raw.
    if "quoted_line_items" in data:
        account.quoted_total = pnl_engine.quoted_total_from_items(account)

    # Dragging between columns must never touch the workstream: they are
    # different axes. Only the column's own clock resets.
    if "column" in data and account.column != previous_column:
        account.column_changed_at = datetime.utcnow()
        if account.column == "ready_for_onboarding" and not account.handoff_received_at:
            account.handoff_received_at = datetime.utcnow()

    account.updated_at = datetime.utcnow()
    session.add(account)

    # Promotion from pilot to customer is a milestone worth a timeline entry.
    if "mode" in data and account.mode != previous_mode:
        session.add(
            Activity(
                account_id=account.id,
                type="update",
                occurred_at=datetime.utcnow(),
                summary=(
                    f"Engagement moved from {MODE_TITLES.get(previous_mode, previous_mode)} "
                    f"to {MODE_TITLES.get(account.mode, account.mode)}"
                ),
            )
        )
    session.commit()

    health_engine.recompute_account(session, account)
    ctx = BookContext(session)
    return {"account": account_card(ctx, account)}


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
    return {"account": account_card(BookContext(session), account)}


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
    return {"account": account_card(BookContext(session), account)}

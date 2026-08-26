"""Accounts list, the drawer payload, patches, and manual health override."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from dbtypes import utcnow
from keygen import next_key
from models import (
    Account,
    Activity,
    BoardColumn,
    Contact,
    HealthSnapshot,
    Risk,
    Task,
    UsageMetric,
    User,
)
from schemas import AccountCreate, AccountHardDelete, AccountPatch, HealthOverrideIn
from engines import alerts as alert_engine
from engines import health as health_engine
from engines import pnl as pnl_engine
from engines.attention import BookContext, score_account
from serializers import (
    BAND_DOTS,
    attention_summary,
    CLIENT_TYPE_TITLES,
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


def _entry_column(session: Session) -> BoardColumn:
    """Where new work lands. Falls back to leftmost when no column is flagged.

    A database that has had its entry flag cleared must not make client creation
    impossible — the board is still usable, so creation stays usable too.
    """
    entry = session.exec(
        select(BoardColumn).where(
            BoardColumn.is_default_entry == True,  # noqa: E712
            BoardColumn.is_archived == False,  # noqa: E712
        )
    ).first()
    if entry:
        return entry
    leftmost = sorted(
        [c for c in session.exec(select(BoardColumn)).all() if not c.is_archived],
        key=lambda c: c.position,
    )
    if not leftmost:
        raise HTTPException(
            status_code=409,
            detail="The board has no columns. Add one in Settings before creating a client.",
        )
    return leftmost[0]


@router.post("", status_code=201)
def create_account(payload: AccountCreate, session: Session = Depends(get_session)):
    """Put a real client on the board.

    Four required fields; everything else is the drawer's job. The key is
    derived here and never accepted from the client, and the column is the
    default entry column rather than a choice — the drawer shows Column as
    read-only, so offering it at create would contradict the drawer.
    """
    owner = session.exec(select(User)).first()
    if owner is None:
        # bootstrap.ensure_defaults() creates one at boot; this is the guard for
        # a database someone emptied by hand.
        raise HTTPException(status_code=409, detail="No CSM user configured.")

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required.")

    column = _entry_column(session)
    now = utcnow()

    account = Account(
        key=next_key(session, name),
        name=name,
        column_id=column.id,
        column_changed_at=now,
        # Landing in the entry column IS the handoff, same as a drag into it.
        handoff_received_at=now if column.is_default_entry else None,
        workstream=payload.workstream,
        mode=payload.mode,
        client_type=payload.client_type,
        city=(payload.city or "").strip() or None,
        owner_id=owner.id,
        tags=payload.tags or [],
        comm_modes=payload.comm_modes or [],
        last_contact_at=payload.last_contact_at,
        quoted_total=payload.quoted_total or 0,
        quoted_at=payload.quoted_at,
        quote_notes=payload.quote_notes,
    )
    session.add(account)

    poc_name = (payload.primary_contact_name or "").strip()
    if poc_name:
        session.add(
            Contact(
                account_id=account.id,
                name=poc_name,
                role=(payload.primary_contact_role or "").strip(),
                email=(payload.primary_contact_email or "").strip() or None,
                phone=(payload.primary_contact_phone or "").strip() or None,
                is_primary=True,
            )
        )

    session.commit()
    session.refresh(account)

    # A brand-new client has no snapshot, so the board would show the model
    # default until the next nightly pass. Compute once, now.
    health_engine.recompute_account(session, account)
    return {"account": account_card(BookContext(session), account)}


# --- soft delete, trash, restore, hard delete --------------------------------
# Delete is soft everywhere the user can reach it. The only irreversible path is
# from Trash, behind a typed confirmation.

def _trash_row(session: Session, account: Account) -> dict:
    """What Trash shows. Deliberately not account_card().

    An archived client is outside BookContext by design, so it has no attention
    score, no size band and no stall state — those are properties of a live
    book. Trash shows identity plus the weight of what a hard delete would
    destroy, which is the only thing that matters at that moment.
    """
    column = session.get(BoardColumn, account.column_id)
    counts = {
        "contacts": len(
            session.exec(select(Contact).where(Contact.account_id == account.id)).all()
        ),
        "tasks": len(
            session.exec(select(Task).where(Task.account_id == account.id)).all()
        ),
        "snapshots": len(
            session.exec(
                select(HealthSnapshot).where(HealthSnapshot.account_id == account.id)
            ).all()
        ),
        "risks": len(
            session.exec(select(Risk).where(Risk.account_id == account.id)).all()
        ),
    }
    return {
        "id": account.id,
        "key": account.key,
        "name": account.name,
        "mode": account.mode,
        "mode_label": MODE_TITLES.get(account.mode, account.mode),
        "workstream": account.workstream,
        "workstream_label": WORKSTREAM_TITLES.get(account.workstream, account.workstream),
        "client_type_label": CLIENT_TYPE_TITLES.get(
            account.client_type, account.client_type
        ),
        "column_label": column.label if column else "Unassigned",
        "archived_at": account.archived_at.isoformat() if account.archived_at else None,
        "quoted_total": account.quoted_total,
        "owns": counts,
        # Nothing is lost on restore, so the UI can say so plainly.
        "restorable": True,
    }


@router.get("/trash/list")
def list_trash(session: Session = Depends(get_session)):
    """Soft-deleted clients, most recently deleted first.

    Two-segment path, and declared above /accounts/{account_id}, so the
    parameterised route cannot swallow it. FastAPI matches in declaration
    order: /accounts/trash alone, declared later, would resolve as an account
    whose id is the literal string "trash" and 404.
    """
    rows = session.exec(
        select(Account).where(Account.archived_at != None)  # noqa: E711
    ).all()
    rows.sort(key=lambda a: a.archived_at or utcnow(), reverse=True)
    return {"accounts": [_trash_row(session, a) for a in rows], "count": len(rows)}


@router.delete("/{account_id}")
def archive_account(account_id: str, session: Session = Depends(get_session)):
    """Soft delete. The client leaves every board, engine and metric intact."""
    account = _get(session, account_id)
    if account.archived_at is not None:
        raise HTTPException(status_code=409, detail="Client is already in Trash.")
    account.archived_at = utcnow()
    account.pinned = False  # a deleted client must not keep a pinned slot
    account.updated_at = utcnow()
    session.add(account)
    session.commit()
    session.refresh(account)
    return {"archived": _trash_row(session, account)}


@router.post("/{account_id}/restore")
def restore_account(account_id: str, session: Session = Depends(get_session)):
    """Back onto the board, in the column it left from.

    Restoring into a column that has since been archived would put the client
    somewhere invisible, so that case lands in the entry column instead.
    """
    account = _get(session, account_id)
    if account.archived_at is None:
        raise HTTPException(status_code=409, detail="Client is not in Trash.")

    column = session.get(BoardColumn, account.column_id)
    if column is None or column.is_archived:
        account.column_id = _entry_column(session).id
        account.column_changed_at = utcnow()

    account.archived_at = None
    account.updated_at = utcnow()
    session.add(account)
    session.commit()
    session.refresh(account)

    health_engine.recompute_account(session, account)
    return {"account": account_card(BookContext(session), account)}


@router.post("/{account_id}/hard-delete")
def hard_delete_account(
    account_id: str, payload: AccountHardDelete, session: Session = Depends(get_session)
):
    """Irreversible. Only reachable from Trash, only with the key typed back.

    Children are deleted explicitly rather than left to a cascade: the schema
    declares plain foreign keys with no ON DELETE, and SQLite does not enforce
    them by default anyway, so relying on a cascade here would leave orphan rows
    on SQLite and raise a constraint error on Postgres. Deleting in dependency
    order does the same thing identically on both.
    """
    account = _get(session, account_id)
    if account.archived_at is None:
        raise HTTPException(
            status_code=409,
            detail="Move the client to Trash before deleting it permanently.",
        )
    if payload.confirm_key.strip().upper() != account.key.upper():
        raise HTTPException(
            status_code=422,
            detail=f"Type {account.key} exactly to confirm.",
        )

    # activity -> task (activity.created_task_id references it), then the rest.
    for activity in session.exec(
        select(Activity).where(Activity.account_id == account_id)
    ).all():
        session.delete(activity)
    session.commit()

    for model in (Task, Contact, HealthSnapshot, Risk, UsageMetric):
        for row in session.exec(
            select(model).where(model.account_id == account_id)
        ).all():
            session.delete(row)

    key, name = account.key, account.name
    session.delete(account)
    session.commit()
    return {"deleted": {"id": account_id, "key": key, "name": name}}


@router.get("/{account_id}")
def get_account(account_id: str, session: Session = Depends(get_session)):
    account = _get(session, account_id)
    ctx = BookContext(session)
    scored = score_account(ctx, account)
    flags = alert_engine.state_flags(ctx, account)
    owner = session.get(User, account.owner_id)
    _column = ctx.column_of(account)

    contacts = session.exec(select(Contact).where(Contact.account_id == account_id)).all()
    tasks = session.exec(select(Task).where(Task.account_id == account_id)).all()
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
            "column_id": account.column_id,
            "column_key": _column.key if _column else None,
            "column_label": _column.label if _column else "Unassigned",
            "column_color": _column.color if _column else "#6b6b6b",
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

        # --- Mode of Communication -----------------------------------------
        "comm_modes": [
            {"value": m, "label": COMM_MODE_TITLES.get(m, m)} for m in comm_modes
        ],
        # Gmail renders only when email is a channel and the primary contact has
        # an address.
        "show_email_threads": "email" in comm_modes
        and any(c.is_primary and c.email for c in contacts),
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
        "attention": {**scored, "summary": attention_summary(scored)},
        "contacts": [
            {
                "id": c.id,
                "name": c.name,
                "role": c.role,
                "email": c.email,
                "phone": c.phone,
                "is_champion": c.is_champion,
                "is_economic_buyer": c.is_economic_buyer,
                "is_primary": c.is_primary,
                "status": c.status,
            }
            for c in contacts
        ],
        "tasks": [task_card(t, account) for t in sorted(tasks, key=lambda t: t.due_date)],
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
    previous_column = account.column_id

    for field, value in data.items():
        if field in ("quoted_line_items", "cost_items"):
            value = [v if isinstance(v, dict) else v.model_dump() for v in value]
        setattr(account, field, value)

    # quoted_total is always derived from the line items — never trusted raw.
    if "quoted_line_items" in data:
        account.quoted_total = pnl_engine.quoted_total_from_items(account)

    # Dragging between columns must never touch the workstream: they are
    # different axes. Only the column's own clock resets.
    if "column_id" in data and account.column_id != previous_column:
        account.column_changed_at = utcnow()
        entry = session.exec(
            select(BoardColumn).where(BoardColumn.is_default_entry == True)  # noqa: E712
        ).first()
        if entry and account.column_id == entry.id and not account.handoff_received_at:
            account.handoff_received_at = utcnow()

    account.updated_at = utcnow()
    session.add(account)

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
    account.health_override_at = utcnow()
    account.updated_at = utcnow()
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
    account.updated_at = utcnow()
    session.add(account)
    session.commit()
    session.refresh(account)
    return {"account": account_card(BookContext(session), account)}

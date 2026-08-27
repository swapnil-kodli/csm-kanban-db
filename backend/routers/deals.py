"""Deals: the board list, the drawer payload, patches, outcome and soft delete.

A deal is the unit of work and the unit on the board. Anything describing the
CLIENT rather than the engagement lives on Company and is served by
routers/companies.py.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from auth import current_user
from db import get_session
from dbtypes import utcnow
from keygen import next_deal_key
from models import (
    Activity,
    BoardColumn,
    Company,
    Contact,
    Deal,
    HealthSnapshot,
    Risk,
    Task,
    UsageMetric,
    User,
)
from schemas import DealCreate, DealOutcomeIn, DealPatch, HardDeleteIn, HealthOverrideIn
from engines import alerts as alert_engine
from engines import health as health_engine
from engines import pnl as pnl_engine
from engines.attention import BookContext, score_deal
from serializers import (
    BAND_DOTS,
    attention_summary,
    CLIENT_TYPE_TITLES,
    COMM_MODE_TITLES,
    MODE_TITLES,
    WORKSTREAM_GLYPHS,
    WORKSTREAM_TITLES,
    deal_card,
    deal_matches,
    parse_filters,
    task_card,
)

router = APIRouter(prefix="/deals", tags=["deals"])


def _get(session: Session, deal_id: str) -> Deal:
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@router.get("")
def list_deals(filters: Optional[str] = None, session: Session = Depends(get_session)):
    f = parse_filters(filters)
    ctx = BookContext(session)
    cards = [deal_card(ctx, a) for a in ctx.deals if deal_matches(ctx, a, f)]
    cards.sort(key=lambda c: (not c["pinned"], -c["attention_score"], c["name"]))
    return {"deals": cards, "count": len(cards)}


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


def _resolve_poc(session: Session, company_id: str, poc_id: str) -> Contact:
    """The POC invariant, enforced here rather than trusted from the picker.

    `deal.poc_id` must name a contact belonging to `deal.company_id`. This is
    the single most likely source of silent bad data in the split: a payload
    with a mismatched pair looks perfectly well-formed, and the consequence is
    one client's contact — and, through the Gmail panel, their correspondence —
    appearing on another client's drawer. So it is checked on every write path,
    not only where the UI happens to offer a filtered list.
    """
    contact = session.get(Contact, poc_id)
    if contact is None:
        raise HTTPException(status_code=422, detail="POC contact not found.")
    if contact.company_id != company_id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{contact.name} belongs to a different company. A deal's POC "
                "must be a contact of that deal's own company."
            ),
        )
    return contact


@router.post("", status_code=201)
def create_deal(payload: DealCreate, session: Session = Depends(get_session)):
    """Open an engagement against an existing company.

    The key is derived per company (PRE-04-01) and never accepted from the
    client. The column is the default entry column rather than a choice — the
    drawer shows Column as read-only, so offering it here would contradict it.
    """
    company = session.get(Company, payload.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if company.archived_at is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{company.name} is in Trash. Restore it before adding a deal.",
        )

    _resolve_poc(session, company.id, payload.poc_id)

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required.")

    column = _entry_column(session)
    now = utcnow()

    deal = Deal(
        key=next_deal_key(session, company),
        company_id=company.id,
        poc_id=payload.poc_id,
        name=name,
        column_id=column.id,
        column_changed_at=now,
        # Landing in the entry column IS the handoff, same as a drag into it.
        handoff_received_at=now if column.is_default_entry else None,
        workstream=payload.workstream,
        mode=payload.mode,
        comm_modes=payload.comm_modes or [],
        last_contact_at=payload.last_contact_at,
        quoted_total=payload.quoted_total or 0,
        quoted_at=payload.quoted_at,
        quote_notes=payload.quote_notes,
        outcome="active",
    )
    session.add(deal)
    session.commit()
    session.refresh(deal)

    # A brand-new deal has no snapshot, so the board would show the model
    # default until the next nightly pass. Compute once, now.
    health_engine.recompute_deal(session, deal)
    return {"deal": deal_card(BookContext(session), deal, company=company)}


@router.post("/{deal_id}/outcome")
def set_outcome(
    deal_id: str, payload: DealOutcomeIn, session: Session = Depends(get_session)
):
    """Mark a deal completed or lost — or put it back to active.

    This is a different axis from `column_id` and must not be inferred from it.
    A deal can be lost from any column, and `Launch` is where active work ends
    up rather than a declaration that it is finished. Conflating the two would
    make the won/lost history a function of where a card happened to sit.
    """
    deal = _get(session, deal_id)
    if payload.outcome == "lost" and not (payload.reason or "").strip():
        raise HTTPException(
            status_code=422,
            detail="A lost deal needs a reason — that is the point of recording it.",
        )

    deal.outcome = payload.outcome
    deal.outcome_reason = (payload.reason or "").strip() or None
    # Back to active clears the stamp: a reopened deal has no outcome date.
    deal.outcome_at = utcnow() if payload.outcome != "active" else None
    deal.updated_at = utcnow()
    session.add(deal)
    session.commit()
    session.refresh(deal)
    return {"deal": deal_card(BookContext(session), deal)}


# --- soft delete, trash, restore, hard delete --------------------------------
# Delete is soft everywhere the user can reach it. The only irreversible path is
# from Trash, behind a typed confirmation.
#
# Note this is NOT the same as outcome="lost". A lost deal is a real result that
# belongs in the company's won/lost history; an archived deal is a record that
# should not exist. Folding them together would corrupt the exact number the
# split was made to produce.

def _trash_row(session: Session, deal: Deal) -> dict:
    """What Trash shows. Deliberately not deal_card().

    An archived deal is outside BookContext by design, so it has no attention
    score, no size band and no stall state — those are properties of live work.
    Trash shows identity plus the weight of what a hard delete would destroy,
    which is the only thing that matters at that moment.
    """
    column = session.get(BoardColumn, deal.column_id)
    company = session.get(Company, deal.company_id)
    counts = {
        "tasks": len(session.exec(select(Task).where(Task.deal_id == deal.id)).all()),
        "snapshots": len(
            session.exec(
                select(HealthSnapshot).where(HealthSnapshot.deal_id == deal.id)
            ).all()
        ),
        "risks": len(session.exec(select(Risk).where(Risk.deal_id == deal.id)).all()),
    }
    return {
        "id": deal.id,
        "key": deal.key,
        "name": deal.name,
        "company_id": deal.company_id,
        "company_name": company.name if company else "Unknown company",
        "mode": deal.mode,
        "mode_label": MODE_TITLES.get(deal.mode, deal.mode),
        "workstream": deal.workstream,
        "workstream_label": WORKSTREAM_TITLES.get(deal.workstream, deal.workstream),
        "column_label": column.label if column else "Unassigned",
        "outcome": deal.outcome,
        "archived_at": deal.archived_at.isoformat() if deal.archived_at else None,
        "quoted_total": deal.quoted_total,
        "owns": counts,
        "restorable": True,
    }


@router.get("/trash/list")
def list_trash(session: Session = Depends(get_session)):
    """Soft-deleted deals, most recently deleted first.

    Two-segment path, and declared above /deals/{deal_id}, so the parameterised
    route cannot swallow it. FastAPI matches in declaration order: /deals/trash
    alone, declared later, would resolve as a deal whose id is the literal
    string "trash" and 404.
    """
    rows = session.exec(
        select(Deal).where(Deal.archived_at != None)  # noqa: E711
    ).all()
    rows.sort(key=lambda d: d.archived_at or utcnow(), reverse=True)
    return {"deals": [_trash_row(session, d) for d in rows], "count": len(rows)}


@router.delete("/{deal_id}")
def archive_deal(deal_id: str, session: Session = Depends(get_session)):
    """Soft delete. The deal leaves every board, engine and metric intact."""
    deal = _get(session, deal_id)
    if deal.archived_at is not None:
        raise HTTPException(status_code=409, detail="Deal is already in Trash.")
    deal.archived_at = utcnow()
    deal.pinned = False  # a deleted deal must not keep a pinned slot
    deal.updated_at = utcnow()
    session.add(deal)
    session.commit()
    session.refresh(deal)
    return {"archived": _trash_row(session, deal)}


@router.post("/{deal_id}/restore")
def restore_deal(deal_id: str, session: Session = Depends(get_session)):
    """Back onto the board, in the column it left from.

    Restoring into a column that has since been archived would put the deal
    somewhere invisible, so that case lands in the entry column instead. A deal
    whose company was hard-deleted in the meantime cannot come back at all.
    """
    deal = _get(session, deal_id)
    if deal.archived_at is None:
        raise HTTPException(status_code=409, detail="Deal is not in Trash.")

    company = session.get(Company, deal.company_id)
    if company is None:
        raise HTTPException(
            status_code=409,
            detail="This deal's company no longer exists, so it cannot be restored.",
        )
    if company.archived_at is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Restore {company.name} first — its deals come back with it.",
        )

    column = session.get(BoardColumn, deal.column_id)
    if column is None or column.is_archived:
        deal.column_id = _entry_column(session).id
        deal.column_changed_at = utcnow()

    deal.archived_at = None
    deal.updated_at = utcnow()
    session.add(deal)
    session.commit()
    session.refresh(deal)

    health_engine.recompute_deal(session, deal)
    return {"deal": deal_card(BookContext(session), deal)}


@router.post("/{deal_id}/hard-delete")
def hard_delete_deal(
    deal_id: str, payload: HardDeleteIn, session: Session = Depends(get_session)
):
    """Irreversible. Only reachable from Trash, only with the key typed back.

    Children are deleted explicitly rather than left to a cascade: the schema
    declares plain foreign keys with no ON DELETE, and SQLite does not enforce
    them by default anyway, so relying on a cascade would leave orphan rows on
    SQLite and raise a constraint error on Postgres. Deleting in dependency
    order behaves identically on both.

    Contacts are NOT deleted here — they belong to the company and are shared
    across its other deals.
    """
    deal = _get(session, deal_id)
    if deal.archived_at is None:
        raise HTTPException(
            status_code=409,
            detail="Move the deal to Trash before deleting it permanently.",
        )
    if payload.confirm_key.strip().upper() != deal.key.upper():
        raise HTTPException(status_code=422, detail=f"Type {deal.key} exactly to confirm.")

    # activity -> task (activity.created_task_id references it), then the rest.
    for activity in session.exec(
        select(Activity).where(Activity.deal_id == deal_id)
    ).all():
        session.delete(activity)
    session.commit()

    for model in (Task, HealthSnapshot, Risk, UsageMetric):
        for row in session.exec(select(model).where(model.deal_id == deal_id)).all():
            session.delete(row)

    key, name = deal.key, deal.name
    session.delete(deal)
    session.commit()
    return {"deleted": {"id": deal_id, "key": key, "name": name}}


@router.get("/{deal_id}")
def get_deal(deal_id: str, session: Session = Depends(get_session)):
    deal = _get(session, deal_id)
    ctx = BookContext(session)
    scored = score_deal(ctx, deal)
    flags = alert_engine.state_flags(ctx, deal)
    company = session.get(Company, deal.company_id)
    owner = session.get(User, company.owner_id) if company else None
    _column = ctx.column_of(deal)

    # Contacts are COMPANY-scoped, so the drawer's POC picker offers every
    # contact of this deal's company — which is exactly the set the server will
    # accept as a poc_id, so the picker and the validation cannot disagree.
    contacts = (
        session.exec(select(Contact).where(Contact.company_id == company.id)).all()
        if company
        else []
    )
    poc = session.get(Contact, deal.poc_id)
    tasks = session.exec(select(Task).where(Task.deal_id == deal_id)).all()
    snapshots = session.exec(
        select(HealthSnapshot)
        .where(HealthSnapshot.deal_id == deal_id)
        .order_by(HealthSnapshot.captured_on.desc())  # type: ignore[attr-defined]
        .limit(90)
    ).all()
    risks = session.exec(select(Risk).where(Risk.deal_id == deal_id)).all()
    usage = session.exec(
        select(UsageMetric)
        .where(UsageMetric.deal_id == deal_id)
        .order_by(UsageMetric.captured_on.desc())  # type: ignore[attr-defined]
        .limit(30)
    ).all()

    latest = snapshots[0] if snapshots else None
    contacts_by_id = {c.id: c for c in contacts}
    override_age = health_engine.override_age_days(deal)
    comm_modes = deal.comm_modes or []

    return {
        "card": deal_card(ctx, deal, scored, company=company),
        # --- the client this engagement belongs to --------------------------
        # A chip in the drawer header, opening the company detail view. Read-only
        # here: client fields are edited on the company, in one place.
        "company": {
            "id": company.id,
            "key": company.key,
            "name": company.name,
            "city": company.city,
            "client_type": company.client_type,
            "client_type_label": CLIENT_TYPE_TITLES.get(
                company.client_type, company.client_type
            ),
            "tags": company.tags or [],
        } if company else None,
        # --- the deal's own POC ---------------------------------------------
        "poc": {
            "id": poc.id,
            "name": poc.name,
            "role": poc.role,
            "email": poc.email,
            "phone": poc.phone,
        } if poc else None,
        # --- Overview panel -------------------------------------------------
        "deal": {
            "id": deal.id,
            "key": deal.key,
            "name": deal.name,
            "company_id": deal.company_id,
            "poc_id": deal.poc_id,
            "outcome": deal.outcome,
            "outcome_at": deal.outcome_at.isoformat() if deal.outcome_at else None,
            "outcome_reason": deal.outcome_reason,
            "column_id": deal.column_id,
            "column_key": _column.key if _column else None,
            "column_label": _column.label if _column else "Unassigned",
            "column_color": _column.color if _column else "#6b6b6b",
            "days_in_column": flags["days_in_column"],
            "column_stalled": flags["column_stalled"],
            "workstream": deal.workstream,
            "workstream_label": WORKSTREAM_TITLES.get(deal.workstream, deal.workstream),
            "workstream_glyph": WORKSTREAM_GLYPHS.get(deal.workstream, "◔"),
            "mode": deal.mode,
            "mode_label": MODE_TITLES.get(deal.mode, deal.mode),
            "size_band": flags["size_band"],
            "pinned": deal.pinned,
            "owner": {"id": owner.id, "name": owner.name, "initials": owner.initials}
            if owner
            else None,
            "handoff_received_at": deal.handoff_received_at.isoformat()
            if deal.handoff_received_at
            else None,
            "last_contact_at": deal.last_contact_at.isoformat()
            if deal.last_contact_at
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
        # Gmail renders only when email is a channel AND this deal's own POC
        # has an address. Not the company's primary — two deals with one client
        # can have different counterparts, and the panel must show the
        # correspondence belonging to the engagement being looked at.
        "show_email_threads": "email" in comm_modes and bool(poc and poc.email),
        # --- Health Check panel ---------------------------------------------
        "health": {
            "score": deal.health_score,
            "computed_band": deal.health_band,
            "computed_band_label": health_engine.BAND_LABELS[deal.health_band],
            "effective_band": health_engine.effective_band(deal),
            "effective_band_label": health_engine.BAND_LABELS[
                health_engine.effective_band(deal)
            ],
            "dot": BAND_DOTS[health_engine.effective_band(deal)],
            "velocity": ctx.velocity_by_deal.get(deal.id),
            "note": deal.health_note,
            "override": (
                {
                    "band": deal.health_manual_override,
                    "band_label": health_engine.BAND_LABELS[deal.health_manual_override],
                    "reason": deal.health_override_reason,
                    "set_at": deal.health_override_at.isoformat()
                    if deal.health_override_at
                    else None,
                    "age_days": override_age,
                    "stale": override_age is not None and override_age > 60,
                }
                if deal.health_manual_override
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
        "commercials": pnl_engine.compute(deal),
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
        "tasks": [task_card(t, deal) for t in sorted(tasks, key=lambda t: t.due_date)],
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


@router.get("/{deal_id}/email-threads")
def email_threads(
    deal_id: str,
    limit: int = 20,
    session: Session = Depends(get_session),
    user: Optional[User] = Depends(current_user),
):
    """Always 200 with a state the panel can render. A Gmail outage must never
    block the drawer from opening or the board from rendering."""
    from routers.google import fetch_threads

    deal = _get(session, deal_id)
    return fetch_threads(session, deal, user, limit)


@router.patch("/{deal_id}")
def patch_deal(
    deal_id: str, payload: DealPatch, session: Session = Depends(get_session)
):
    deal = _get(session, deal_id)
    data = payload.model_dump(exclude_unset=True)

    previous_column = deal.column_id
    previous_poc = deal.poc_id

    # Same invariant as create, checked on the patch path too. A PATCH that sets
    # poc_id is exactly as capable of pointing at another company's contact as a
    # POST is, and the picker being filtered is not a guarantee about the API.
    if "poc_id" in data:
        _resolve_poc(session, deal.company_id, data["poc_id"])

    for field, value in data.items():
        if field in ("quoted_line_items", "cost_items"):
            value = [v if isinstance(v, dict) else v.model_dump() for v in value]
        setattr(deal, field, value)

    # quoted_total is always derived from the line items — never trusted raw.
    if "quoted_line_items" in data:
        deal.quoted_total = pnl_engine.quoted_total_from_items(deal)

    # Dragging between columns must never touch the workstream: they are
    # different axes. Only the column's own clock resets.
    if "column_id" in data and deal.column_id != previous_column:
        deal.column_changed_at = utcnow()
        entry = session.exec(
            select(BoardColumn).where(BoardColumn.is_default_entry == True)  # noqa: E712
        ).first()
        if entry and deal.column_id == entry.id and not deal.handoff_received_at:
            deal.handoff_received_at = utcnow()

    deal.updated_at = utcnow()
    session.add(deal)

    session.commit()

    # A changed POC means a different mailbox to search, so the cached threads
    # for this deal are about the wrong person until they are dropped.
    if "poc_id" in data and deal.poc_id != previous_poc:
        from routers.google import invalidate_deal_threads

        invalidate_deal_threads(deal.id)

    health_engine.recompute_deal(session, deal)
    ctx = BookContext(session)
    return {"deal": deal_card(ctx, deal)}


@router.post("/{deal_id}/health-override")
def set_health_override(
    deal_id: str, payload: HealthOverrideIn, session: Session = Depends(get_session)
):
    """The CSM's judgement beats the score — but it must be recorded."""
    deal = _get(session, deal_id)
    deal.health_manual_override = payload.band
    deal.health_override_reason = payload.reason.strip()
    deal.health_override_at = utcnow()
    deal.updated_at = utcnow()
    session.add(deal)
    session.commit()
    session.refresh(deal)
    return {"deal": deal_card(BookContext(session), deal)}


@router.delete("/{deal_id}/health-override")
def clear_health_override(deal_id: str, session: Session = Depends(get_session)):
    deal = _get(session, deal_id)
    deal.health_manual_override = None
    deal.health_override_reason = None
    deal.health_override_at = None
    deal.updated_at = utcnow()
    session.add(deal)
    session.commit()
    session.refresh(deal)
    return {"deal": deal_card(BookContext(session), deal)}

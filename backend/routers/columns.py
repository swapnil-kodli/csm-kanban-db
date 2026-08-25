"""Board column configuration.

A narrow configuration surface on purpose. Every destructive action requires a
target, and every refusal names the constraint it is protecting — one refusal
idiom across the whole config surface.

Saved views store the immutable `key`, so a rename is always safe. A delete or
an archive is not: the clause would point at a key that no longer appears on the
board and the view would silently return nothing. Both paths sweep saved views,
and both report what they touched *before* the change is applied so the operator
is choosing rather than reading a receipt.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from db import get_session
from models import Account, BoardColumn, COLUMN_PALETTE, SavedView
from schemas import ColumnCreate, ColumnDelete, ColumnPatch, ColumnReorder

router = APIRouter(prefix="/columns", tags=["columns"])


def _out(c: BoardColumn, count: int = 0) -> dict:
    return {
        "id": c.id,
        "key": c.key,
        "label": c.label,
        "color": c.color,
        "position": c.position,
        "is_archived": c.is_archived,
        "is_default_entry": c.is_default_entry,
        "description": c.description,
        "stalled_after_days": c.stalled_after_days,
        "card_count": count,
    }


def _slugify(label: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_") or "column"
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    return key


def _counts(session: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    for a in session.exec(select(Account)).all():
        out[a.column_id] = out.get(a.column_id, 0) + 1
    return out


def _get(session: Session, column_id: str) -> BoardColumn:
    column = session.get(BoardColumn, column_id)
    if column is None:
        raise HTTPException(status_code=404, detail="Column not found")
    return column


def _views_referencing(session: Session, key: str) -> list[SavedView]:
    return [
        v
        for v in session.exec(select(SavedView)).all()
        if key in ((v.filter_json or {}).get("columns") or [])
    ]


def _rewrite_views(
    session: Session, from_key: str, to_key: Optional[str]
) -> list[str]:
    """Repoint or strip saved-view clauses naming a key that is going away."""
    touched: list[str] = []
    for view in _views_referencing(session, from_key):
        filters = dict(view.filter_json or {})
        keys = [k for k in filters.get("columns", []) if k != from_key]
        if to_key and to_key not in keys:
            keys.append(to_key)
        if keys:
            filters["columns"] = keys
        else:
            filters.pop("columns", None)
        view.filter_json = filters
        view.updated_at = datetime.utcnow()
        session.add(view)
        touched.append(view.name)
    return touched


@router.get("")
def list_columns(
    include_archived: bool = Query(True), session: Session = Depends(get_session)
):
    counts = _counts(session)
    columns = sorted(session.exec(select(BoardColumn)).all(), key=lambda c: c.position)
    return {
        "columns": [
            _out(c, counts.get(c.id, 0))
            for c in columns
            if include_archived or not c.is_archived
        ],
        "palette": list(COLUMN_PALETTE),
    }


DEFAULT_COLUMNS = [
    ("ready_for_onboarding", "Ready for Onboarding", "#9d50dd", True, 3,
     "Closed Won upstream and not yet picked up."),
    ("onboarding", "Onboarding", "#2bb4d6", False, 14,
     "Kickoff through to first configuration."),
    ("working", "Working", "#6b6b6b", False, 14, "Active delivery."),
    ("approval", "Approval", "#f5b400", False, 14, "Awaiting client sign-off."),
    ("launch", "Launch", "#00c875", False, None,
     "Live. No stall tracking — sitting here is delivery, not drift."),
]


@router.post("/reset")
def reset_columns(session: Session = Depends(get_session)):
    """Restore the shipped column set. Recovery must be one click away.

    Existing columns are matched by key and updated in place, so cards keep
    their column and nothing is orphaned. Columns that are not part of the
    default set are archived rather than deleted — they may still hold cards,
    and silently dropping someone's work is never the safe default.
    """
    by_key = {c.key: c for c in session.exec(select(BoardColumn)).all()}
    default_keys = {k for k, *_ in DEFAULT_COLUMNS}
    restored, archived = [], []

    for i, (key, label, color, entry, stalled, desc) in enumerate(DEFAULT_COLUMNS):
        column = by_key.get(key)
        if column is None:
            column = BoardColumn(key=key)
            session.add(column)
        column.label, column.color, column.position = label, color, float(i + 1)
        column.is_default_entry, column.stalled_after_days = entry, stalled
        column.description, column.is_archived = desc, False
        session.add(column)
        restored.append(key)

    counts = _counts(session)
    for key, column in by_key.items():
        if key in default_keys:
            continue
        if counts.get(column.id, 0) == 0:
            session.delete(column)
        else:
            column.is_archived = True
            column.is_default_entry = False
            session.add(column)
        archived.append(key)

    session.commit()
    return {"restored": restored, "removed_or_archived": archived}


@router.get("/{column_id}/impact")
def delete_impact(column_id: str, session: Session = Depends(get_session)):
    """What a delete or archive would do, so the dialog can say it up front."""
    column = _get(session, column_id)
    return {
        "card_count": _counts(session).get(column.id, 0),
        "saved_views": [v.name for v in _views_referencing(session, column.key)],
        "is_default_entry": column.is_default_entry,
    }


@router.post("", status_code=201)
def create_column(payload: ColumnCreate, session: Session = Depends(get_session)):
    existing = sorted(session.exec(select(BoardColumn)).all(), key=lambda c: c.position)
    color = payload.color or COLUMN_PALETTE[len(existing) % len(COLUMN_PALETTE)]
    if color not in COLUMN_PALETTE:
        raise HTTPException(
            status_code=422,
            detail=(
                "Colour must come from the token palette — a free colour picker "
                "would put a second saturated channel on the board."
            ),
        )
    column = BoardColumn(
        key=_slugify(payload.label, {c.key for c in existing}),
        label=payload.label.strip(),
        color=color,
        # New columns append to the right.
        position=payload.position
        if payload.position is not None
        else (existing[-1].position + 1 if existing else 1.0),
        description=payload.description,
        stalled_after_days=payload.stalled_after_days,
    )
    session.add(column)
    session.commit()
    session.refresh(column)
    return {"column": _out(column)}


@router.patch("/{column_id}")
def patch_column(
    column_id: str, payload: ColumnPatch, session: Session = Depends(get_session)
):
    column = _get(session, column_id)
    data = payload.model_dump(exclude_unset=True)
    counts = _counts(session)
    saved_views_updated: list[str] = []

    if data.get("color") and data["color"] not in COLUMN_PALETTE:
        raise HTTPException(status_code=422, detail="Colour must come from the token palette")

    if data.get("is_archived") and not column.is_archived:
        if column.is_default_entry:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"'{column.label}' is the entry column — new engagements land here. "
                    "Designate another entry column before archiving this one."
                ),
            )
        if counts.get(column.id, 0):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"'{column.label}' still holds {counts[column.id]} card(s). "
                    "Move them out before archiving."
                ),
            )
        # An archived column vanishes from the board, so a view filtering on it
        # would silently return nothing. Strip the clause and say so.
        saved_views_updated = _rewrite_views(session, column.key, None)

    if data.get("is_default_entry"):
        if column.is_archived:
            raise HTTPException(
                status_code=409,
                detail="An archived column cannot be the entry column. Restore it first.",
            )
        for other in session.exec(
            select(BoardColumn).where(BoardColumn.is_default_entry == True)  # noqa: E712
        ).all():
            other.is_default_entry = False
            session.add(other)
    elif data.get("is_default_entry") is False and column.is_default_entry:
        raise HTTPException(
            status_code=409,
            detail=(
                "Exactly one column must be the entry column. Set another column "
                "as the entry point instead of clearing this one."
            ),
        )

    if data.pop("clear_stalled_after_days", False):
        column.stalled_after_days = None
        data.pop("stalled_after_days", None)

    for field, value in data.items():
        setattr(column, field, value)
    column.updated_at = datetime.utcnow()
    session.add(column)
    session.commit()
    session.refresh(column)
    return {"column": _out(column, counts.get(column.id, 0)), "saved_views_updated": saved_views_updated}


@router.post("/reorder")
def reorder_columns(payload: ColumnReorder, session: Session = Depends(get_session)):
    columns = {c.id: c for c in session.exec(select(BoardColumn)).all()}
    for index, cid in enumerate(payload.ordered_ids):
        column = columns.get(cid)
        if column is None:
            raise HTTPException(status_code=404, detail=f"Unknown column {cid}")
        column.position = float(index + 1)
        column.updated_at = datetime.utcnow()
        session.add(column)
    session.commit()
    counts = _counts(session)
    ordered = sorted(columns.values(), key=lambda c: c.position)
    return {"columns": [_out(c, counts.get(c.id, 0)) for c in ordered]}


@router.delete("/{column_id}")
def delete_column(
    column_id: str, payload: ColumnDelete, session: Session = Depends(get_session)
):
    column = _get(session, column_id)
    all_columns = session.exec(select(BoardColumn)).all()

    if len(all_columns) <= 1:
        raise HTTPException(
            status_code=409, detail="A board must keep at least one column."
        )
    if column.is_default_entry:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{column.label}' is the entry column — new engagements land here. "
                "Designate another entry column before deleting this one."
            ),
        )

    counts = _counts(session)
    held = counts.get(column.id, 0)
    if held and not payload.reassign_to:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{column.label}' still holds {held} card(s). "
                "Choose a column to move them to."
            ),
        )

    target: Optional[BoardColumn] = None
    if held:
        target = session.get(BoardColumn, payload.reassign_to or "")
        if target is None or target.id == column.id:
            raise HTTPException(status_code=422, detail="Pick a different target column")
        for account in session.exec(
            select(Account).where(Account.column_id == column.id)
        ).all():
            account.column_id = target.id
            account.column_changed_at = datetime.utcnow()
            account.updated_at = datetime.utcnow()
            session.add(account)

    saved_views_updated = _rewrite_views(session, column.key, target.key if target else None)
    session.delete(column)
    session.commit()
    return {
        "deleted": column.key,
        "reassigned": held,
        "reassigned_to": target.key if target else None,
        "saved_views_updated": saved_views_updated,
    }

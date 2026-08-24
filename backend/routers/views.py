"""Saved views — the seven from spec 01 §6, plus whatever the CSM saves."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from models import SavedView
from schemas import SavedViewCreate

router = APIRouter(prefix="/saved-views", tags=["saved-views"])


def _out(v: SavedView) -> dict:
    return {
        "id": v.id,
        "name": v.name,
        "filter_json": v.filter_json or {},
        "pinned": v.pinned,
        "is_default": v.is_default,
    }


@router.get("")
def list_views(session: Session = Depends(get_session)):
    views = session.exec(select(SavedView).order_by(SavedView.sort_index)).all()  # type: ignore[arg-type]
    return {"views": [_out(v) for v in views]}


@router.post("", status_code=201)
def create_view(payload: SavedViewCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(SavedView)).all()
    view = SavedView(
        name=payload.name.strip(),
        filter_json=payload.filter_json,
        pinned=payload.pinned,
        sort_index=float(len(existing)),
    )
    session.add(view)
    session.commit()
    session.refresh(view)
    return {"view": _out(view)}


@router.delete("/{view_id}", status_code=204)
def delete_view(view_id: str, session: Session = Depends(get_session)):
    view = session.get(SavedView, view_id)
    if view is None:
        raise HTTPException(status_code=404, detail="View not found")
    session.delete(view)
    session.commit()

"""Rows the app cannot function without, independent of the demo fixture.

With SEED_DEMO off a production instance boots with an empty database — but
"empty" must still mean a usable board. Without these two, the board renders no
columns at all and client creation has no owner to assign or column to land in.

Idempotent: only creates what is missing.
"""
from __future__ import annotations

from sqlmodel import Session, select

from models import BoardColumn, User

# The shipped column set. Kept in step with routers/columns.py DEFAULT_COLUMNS
# and the v3 migration, so a fresh boot, a reset and a migrated database all
# describe the same board.
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


def ensure_defaults(session: Session) -> dict:
    created = {"user": False, "columns": 0}

    if session.exec(select(User)).first() is None:
        session.add(User(name="Shivam Singh", initials="SS", avatar_color="#111111"))
        created["user"] = True

    existing = {c.key for c in session.exec(select(BoardColumn)).all()}
    for i, (key, label, color, entry, stalled, desc) in enumerate(DEFAULT_COLUMNS):
        if key in existing:
            continue
        session.add(
            BoardColumn(
                key=key, label=label, color=color, position=float(i + 1),
                is_default_entry=entry, stalled_after_days=stalled, description=desc,
            )
        )
        created["columns"] += 1

    session.commit()
    return created

"""In-place schema migration, v1 (CSM board) -> v2 (delivery board).

No Alembic: one dependency-free forward migration, guarded by a version row, so
an existing deployment's SQLite file survives the reshape. The compose volume
persists data/signal.db across restarts, so a deployed v1 database WILL be here
when v2 boots — without this it would fail on the first query for a column that
no longer exists.

SQLite >= 3.35 supports ALTER TABLE ... DROP COLUMN, so this runs in place.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import text
from sqlmodel import Session

log = logging.getLogger("signal.migrations")

SCHEMA_VERSION = 2

# v1 lifecycle_stage -> v2 column. The v2 pipeline has no terminal-negative
# state, so `closed` accounts land in `launch` and are logged by name for the
# operator to review rather than silently rewritten.
STAGE_TO_COLUMN = {
    "ready_for_onboarding": "ready_for_onboarding",
    "onboarding": "onboarding",
    "adopting": "working",
    "healthy": "launch",
    "renewal": "launch",
    "closed": "launch",
}

# No v1 field carries this, so it is seeded from where the account sits.
COLUMN_TO_WORKSTREAM = {
    "ready_for_onboarding": "bot_making",
    "onboarding": "bot_making",
    "working": "data_procurement",
    "approval": "voice_ai_calling",
    "launch": "voice_ai_calling",
}

DATA_OFFERINGS = {"QLs", "VLs", "SLs", "Raw Data profiles"}

NEW_COLUMNS = [
    ('"column"', "VARCHAR", "'ready_for_onboarding'"),
    ("workstream", "VARCHAR", "'bot_making'"),
    ("column_changed_at", "DATETIME", "NULL"),
    ("mode", "VARCHAR", "'customer'"),
    ("client_type", "VARCHAR", "'voice_ai_only'"),
    ("health_note", "TEXT", "NULL"),
    ("poc_name", "VARCHAR", "NULL"),
    ("poc_email", "VARCHAR", "NULL"),
    ("poc_phone", "VARCHAR", "NULL"),
    ("comm_modes", "JSON", "'[]'"),
    ("quoted_total", "INTEGER", "0"),
    ("quoted_line_items", "JSON", "'[]'"),
    ("quoted_at", "DATE", "NULL"),
    ("quote_notes", "TEXT", "NULL"),
    ("revenue_recognised", "INTEGER", "0"),
    ("cost_items", "JSON", "'[]'"),
]

DROPPED_COLUMNS = [
    "lifecycle_stage",
    "closed_reason",
    "arr",
    "segment",
    "expansion_flag",
    "industry",
    "region",
]

DROPPED_TABLES = ["subscription", "milestone"]


def _table_names(session: Session) -> set[str]:
    rows = session.exec(
        text("SELECT name FROM sqlite_master WHERE type='table'")
    ).all()
    return {r[0] for r in rows}


def _columns(session: Session, table: str) -> set[str]:
    rows = session.exec(text(f"PRAGMA table_info({table})")).all()
    return {r[1] for r in rows}


def _drop_indexes_for(session: Session, table: str, columns: list[str]) -> list[str]:
    """SQLite refuses DROP COLUMN while an index still references the column."""
    dropped = []
    targets = {c.lower() for c in columns}
    idx_rows = session.exec(
        text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=:t "
             "AND sql IS NOT NULL").bindparams(t=table)
    ).all()
    for (idx_name,) in idx_rows:
        cols = {r[2].lower() for r in session.exec(text(f"PRAGMA index_info({idx_name})")).all()}
        if cols & targets:
            session.exec(text(f"DROP INDEX IF EXISTS {idx_name}"))
            dropped.append(idx_name)
    return dropped


def _ensure_meta(session: Session) -> int:
    session.exec(
        text("CREATE TABLE IF NOT EXISTS schema_meta (key VARCHAR PRIMARY KEY, value VARCHAR)")
    )
    row = session.exec(
        text("SELECT value FROM schema_meta WHERE key='version'")
    ).first()
    return int(row[0]) if row else 1


def _set_version(session: Session, version: int) -> None:
    session.exec(
        text("INSERT INTO schema_meta (key, value) VALUES ('version', :v) "
             "ON CONFLICT(key) DO UPDATE SET value = :v").bindparams(v=str(version))
    )


def migrate(session: Session) -> dict:
    """Run any pending migration. Safe to call on every boot."""
    tables = _table_names(session)
    if "account" not in tables:
        # Fresh database: create_all builds v2 directly, just stamp the version.
        _ensure_meta(session)
        _set_version(session, SCHEMA_VERSION)
        session.commit()
        return {"migrated": False, "reason": "fresh database"}

    current = _ensure_meta(session)
    account_cols = _columns(session, "account")
    if current >= SCHEMA_VERSION and "lifecycle_stage" not in account_cols:
        return {"migrated": False, "reason": f"already at v{current}"}

    log.warning("Migrating Signal CS database v%s -> v%s", current, SCHEMA_VERSION)
    notes: list[str] = []

    # 1. Add the v2 columns that are missing.
    for name, sqltype, default in NEW_COLUMNS:
        bare = name.strip('"')
        if bare not in account_cols:
            session.exec(
                text(f"ALTER TABLE account ADD COLUMN {name} {sqltype} DEFAULT {default}")
            )

    # 2. Backfill from v1 data before anything is dropped.
    line_items_by_account: dict[str, list] = {}
    if "subscription" in tables:
        for aid, raw in session.exec(
            text("SELECT account_id, line_items FROM subscription")
        ).all():
            try:
                line_items_by_account[aid] = json.loads(raw) if raw else []
            except (TypeError, ValueError):
                line_items_by_account[aid] = []

    poc_by_account: dict[str, tuple] = {}
    if "contact" in tables:
        # Prefer the champion, then the economic buyer, then whoever is first.
        for aid, nm, email, phone, champ, buyer in session.exec(
            text("SELECT account_id, name, email, phone, is_champion, is_economic_buyer "
                 "FROM contact ORDER BY is_champion DESC, is_economic_buyer DESC")
        ).all():
            poc_by_account.setdefault(aid, (nm, email, phone))

    rows = session.exec(
        text('SELECT id, key, name, lifecycle_stage, arr FROM account')
    ).all()
    for aid, key, name, stage, arr in rows:
        column = STAGE_TO_COLUMN.get(stage, "working")
        if stage == "closed":
            notes.append(f"{key} ({name}) was closed in v1 and is now in Launch — review")
        items = line_items_by_account.get(aid, [])
        offerings = {i.get("offering") for i in items if isinstance(i, dict)}
        client_type = (
            "data_plus_voice_ai" if offerings & DATA_OFFERINGS else "voice_ai_only"
        )
        session.exec(
            text(
                'UPDATE account SET "column"=:col, workstream=:ws, column_changed_at=:cca, '
                "mode='customer', client_type=:ct, quoted_total=:qt, quoted_line_items=:qli, "
                "revenue_recognised=0, cost_items='[]', comm_modes='[\"email\"]', "
                "poc_name=:pn, poc_email=:pe, poc_phone=:pp WHERE id=:id"
            ).bindparams(
                col=column,
                ws=COLUMN_TO_WORKSTREAM[column],
                cca=datetime.utcnow(),
                ct=client_type,
                qt=int(arr or 0),
                qli=json.dumps(items),
                pn=poc_by_account.get(aid, (None, None, None))[0],
                pe=poc_by_account.get(aid, (None, None, None))[1],
                pp=poc_by_account.get(aid, (None, None, None))[2],
                id=aid,
            )
        )

    # Commit the backfill before any DDL. ALTER TABLE auto-commits in SQLite,
    # so a later DDL failure would otherwise roll the UPDATEs back while leaving
    # the added columns in place — a half-migrated database.
    session.commit()

    # 3. Drop what v2 does not have. Requires SQLite >= 3.35.
    _drop_indexes_for(session, "account", DROPPED_COLUMNS)
    for col in DROPPED_COLUMNS:
        if col in account_cols:
            session.exec(text(f"ALTER TABLE account DROP COLUMN {col}"))
    for tbl in DROPPED_TABLES:
        if tbl in tables:
            session.exec(text(f"DROP TABLE {tbl}"))

    # 4. Renewal-derived tasks no longer have a rule behind them.
    session.exec(
        text("DELETE FROM task WHERE rule_key IN "
             "('renewal_90','renewal_60','renewal_30','milestone_overdue')")
    )

    _set_version(session, SCHEMA_VERSION)
    session.commit()

    for note in notes:
        log.warning("  %s", note)
    log.warning("Migration complete: %d accounts moved onto the v2 model", len(rows))
    return {"migrated": True, "accounts": len(rows), "notes": notes}

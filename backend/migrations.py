"""In-place schema migration, v1 (CSM board) -> v2 (delivery board).

No Alembic: one dependency-free forward migration, guarded by a version row, so
an existing deployment's SQLite file survives the reshape. The compose volume
persists data/signal.db across restarts, so a deployed v1 database WILL be here
when v2 boots — without this it would fail on the first query for a column that
no longer exists.

SQLite >= 3.35 supports ALTER TABLE ... DROP COLUMN, so this runs in place.

STANDING RULE FOR EVERY FUTURE MIGRATION
----------------------------------------
Drop dependent indexes before dropping any column. SQLite refuses
ALTER TABLE ... DROP COLUMN while an index still references the column, and the
error surfaces at the DROP, not at the index. Use _drop_indexes_for().

Corollary, learned the same way: ALTER TABLE auto-commits, plain UPDATE does
not. Commit every backfill BEFORE any DDL, or a later DDL failure rolls the
backfill back while leaving the new columns in place — a half-migrated database
that looks migrated. Prefer columns with no index where a later migration is
expected (see account.column).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlmodel import Session

log = logging.getLogger("signal.migrations")

SCHEMA_VERSION = 3

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

# --- v2 -> v3a: the five fixed columns become rows in board_column -----------
#
# The board must look IDENTICAL on first load after this runs. Two v2 behaviours
# were keyed to literal column strings and are re-expressed here as data, with
# no new fields:
#
#   handoff inbox (was: column == "ready_for_onboarding")
#       -> is_default_entry, the column new work lands in
#   stall badge   (was: 3d in ready_for_onboarding, 14d elsewhere, never Launch)
#       -> stalled_after_days, nullable; NULL is how Launch opts out
#
# 3 and 14 reproduce v2 exactly; Launch carries NULL so the badge never fires
# there, which is what the v2 Launch exclusion did.
#
# Saved views are removed as a feature in this same step, so a v1 or v2 database
# carrying a populated `savedview` table has it dropped here rather than left
# behind as an orphan no code reads.
V3_COLUMNS = [
    # key, label, colour, position, entry?, stalled_after_days, description
    ("ready_for_onboarding", "Ready for Onboarding", "#9d50dd", 1.0, True, 3,
     "Closed Won upstream and not yet picked up."),
    ("onboarding", "Onboarding", "#2bb4d6", 2.0, False, 14,
     "Kickoff through to first configuration."),
    ("working", "Working", "#6b6b6b", 3.0, False, 14,
     "Active delivery."),
    ("approval", "Approval", "#f5b400", 4.0, False, 14,
     "Awaiting client sign-off."),
    ("launch", "Launch", "#00c875", 5.0, False, None,
     "Live. No stall tracking — sitting here is delivery, not drift."),
]


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
    result = _migrate_v1_to_v2(session)
    v3 = _migrate_v2_to_v3(session)
    if v3.get("migrated"):
        result = {**result, "v3": v3}
    dropped = _drop_saved_views(session)
    if dropped is not None:
        result = {**result, "saved_views_dropped": dropped}
    return result


def _drop_saved_views(session: Session) -> Optional[int]:
    """Saved views were removed as a feature; do not strand the table.

    Deliberately not gated on the v2 -> v3 trigger. A database migrated by an
    earlier build would already be past that branch and would keep the table
    forever, which is exactly the orphan this is meant to prevent.
    """
    if "savedview" not in _table_names(session):
        return None
    count = session.exec(text("SELECT count(*) FROM savedview")).first()[0]
    session.exec(text("DROP TABLE savedview"))
    session.commit()
    log.warning("Dropped the savedview table (%d row(s)) — feature removed", count)
    return count


def _migrate_v2_to_v3(session: Session) -> dict:
    """account.column (str) -> account.column_id (FK to board_column)."""
    tables = _table_names(session)
    if "account" not in tables or "boardcolumn" not in tables:
        return {"migrated": False, "reason": "tables not created yet"}

    # Do not rely on _migrate_v1_to_v2 having run first: each step owns its
    # own preconditions, or the two drift apart the moment one is reordered.
    _ensure_meta(session)

    account_cols = _columns(session, "account")
    # Presence of the v2 string column is the trigger, same rule as v1 -> v2.
    if "column" not in account_cols:
        return {"migrated": False, "reason": "already on the v3 schema"}

    log.warning("Migrating Signal CS board columns v2 -> v3")

    # 1. Seed board_column from the five fixed v2 columns, preserving order,
    #    keys and colours so the board renders identically.
    existing = {
        r[0] for r in session.exec(text("SELECT key FROM boardcolumn")).all()
    }
    for key, label, color, position, entry, stalled, desc in V3_COLUMNS:
        if key in existing:
            continue
        session.exec(
            text(
                "INSERT INTO boardcolumn "
                "(id, created_at, updated_at, key, label, color, position, "
                " is_archived, is_default_entry, description, stalled_after_days) "
                "VALUES (:id, :now, :now, :key, :label, :color, :pos, 0, :entry, "
                "        :desc, :stalled)"
            ).bindparams(
                id=str(uuid.uuid4()), now=datetime.utcnow(), key=key, label=label,
                color=color, pos=position, entry=1 if entry else 0,
                desc=desc, stalled=stalled,
            )
        )

    id_by_key = {
        r[0]: r[1]
        for r in session.exec(text("SELECT key, id FROM boardcolumn")).all()
    }

    # 2. Add the FK and backfill it from the string column.
    if "column_id" not in account_cols:
        session.exec(text("ALTER TABLE account ADD COLUMN column_id VARCHAR"))

    fallback = id_by_key["ready_for_onboarding"]
    orphans: list[str] = []
    for aid, key_str, akey, name in session.exec(
        text('SELECT id, "column", key, name FROM account')
    ).all():
        target = id_by_key.get(key_str)
        if target is None:
            target = fallback
            orphans.append(f"{akey} ({name}) had unknown column '{key_str}'")
        session.exec(
            text("UPDATE account SET column_id = :cid WHERE id = :id").bindparams(
                cid=target, id=aid
            )
        )

    # Commit the backfill BEFORE any DDL — ALTER TABLE auto-commits and would
    # otherwise strand these UPDATEs. See the standing rule at the top.
    session.commit()

    # 3. Drop the old string column, indexes first.
    dropped_idx = _drop_indexes_for(session, "account", ["column"])
    session.exec(text("ALTER TABLE account DROP COLUMN \"column\""))

    _set_version(session, SCHEMA_VERSION)
    session.commit()

    for note in orphans:
        log.warning("  %s", note)
    log.warning("Board columns migrated: %d rows", len(V3_COLUMNS))
    return {
        "migrated": True,
        "columns": len(V3_COLUMNS),
        "indexes_dropped": dropped_idx,
        "orphans": orphans,
    }


def _migrate_v1_to_v2(session: Session) -> dict:
    tables = _table_names(session)
    if "account" not in tables:
        _ensure_meta(session)
        _set_version(session, SCHEMA_VERSION)
        session.commit()
        return {"migrated": False, "reason": "fresh database"}

    current = _ensure_meta(session)
    account_cols = _columns(session, "account")

    # The presence of the v1 column is the trigger, not the version number.
    # init_db() runs create_all before this, so on a fresh database the account
    # table already exists in its v2 shape — version alone would misread that as
    # "needs migrating" and then query a column that was never there.
    if "lifecycle_stage" not in account_cols:
        return {"migrated": False, "reason": "already on the v2 schema"}

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

    session.commit()

    for note in notes:
        log.warning("  %s", note)
    log.warning("Migration complete: %d accounts moved onto the v2 model", len(rows))
    return {"migrated": True, "accounts": len(rows), "notes": notes}

"""Card and column shapes. The server does the grouping; the client renders
columns as given.

The v2 card carries exactly four things — name, mode, workstream, health — and
nothing else. Every other field belongs to the drawer. That cap is the whole
point of the reshape: an over-stuffed card stops being scannable, which is the
failure mode the research is most emphatic about.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from sqlmodel import Session, select

from models import Account, Contact, Risk, Task, User
from engines import alerts as alert_engine
from engines import health as health_engine
from engines import pnl as pnl_engine
from engines.attention import BookContext, score_account

# --- the delivery pipeline ---------------------------------------------------
COLUMN_TITLES = {
    "ready_for_onboarding": "Ready for Onboarding",
    "onboarding": "Onboarding",
    "working": "Working",
    "approval": "Approval",
    "launch": "Launch",
}
COLUMN_DOTS = {
    "ready_for_onboarding": "s-handoff",
    "onboarding": "s-onboarding",
    "working": "s-adopting",
    "approval": "s-renewal",
    "launch": "s-healthy",
}
COLUMN_ORDER = list(COLUMN_TITLES)

# --- what the team is doing right now ----------------------------------------
WORKSTREAM_TITLES = {
    "bot_making": "Bot-Making",
    "data_procurement": "Data Procurement",
    "voice_ai_calling": "Voice AI Calling",
}
# Progress glyph: where this workstream sits in the delivery sequence.
WORKSTREAM_GLYPHS = {
    "bot_making": "◔",
    "data_procurement": "◑",
    "voice_ai_calling": "◕",
}
WORKSTREAM_DOTS = {
    "bot_making": "s-onboarding",
    "data_procurement": "s-adopting",
    "voice_ai_calling": "s-renewal",
}

MODE_TITLES = {"pilot": "Pilot", "customer": "Customer"}
CLIENT_TYPE_TITLES = {
    "voice_ai_only": "Voice AI only",
    "data_plus_voice_ai": "Data + Voice AI",
}
COMM_MODE_TITLES = {"whatsapp": "WhatsApp", "email": "Email"}

BUCKET_TITLES = {
    "today": "Today",
    "this_week": "This Week",
    "follow_up": "Follow-Up",
    "waiting": "Waiting",
    "done": "Done",
}
BAND_DOTS = {
    "healthy": "h-healthy",
    "watch": "h-watch",
    "at_risk": "h-risk",
    "critical": "h-critical",
}
TASK_TYPE_TITLES = {
    "onboarding": "Onboarding",
    "risk": "Risk",
    "renewal": "Renewal",
    "expansion": "Expansion",
    "checkin": "Check-in",
    "escalation": "Escalation",
    "admin": "Admin",
}


# --- cards -------------------------------------------------------------------

def account_card(
    ctx: BookContext, account: Account, scored: Optional[dict] = None
) -> dict:
    """Exactly four things on the face of the card.

    `column` and `workstream` are different axes and both are real: the column
    is where the engagement sits in the pipeline, the workstream is what the
    team is doing on it right now. Dragging between columns must never change
    the workstream.
    """
    flags = alert_engine.state_flags(ctx, account)
    scored = scored or score_account(ctx, account)
    band = health_engine.effective_band(account)

    return {
        "kind": "account",
        "id": account.id,
        "account_id": account.id,
        # 1. name (+ key)
        "key": account.key,
        "name": account.name,
        # 2. pilot / customer
        "mode": account.mode,
        "mode_label": MODE_TITLES.get(account.mode, account.mode),
        # 3. workstream
        "workstream": account.workstream,
        "workstream_label": WORKSTREAM_TITLES.get(account.workstream, account.workstream),
        "workstream_glyph": WORKSTREAM_GLYPHS.get(account.workstream, "◔"),
        "workstream_dot": WORKSTREAM_DOTS.get(account.workstream, "s-adopting"),
        # 4. health status
        "health_score": account.health_score,
        "health_band": band,
        "health_band_label": health_engine.BAND_LABELS[band],
        "health_dot": BAND_DOTS[band],
        "is_overridden": account.health_manual_override is not None,
        # board mechanics, not card content
        "column": account.column,
        "attention_score": scored["score"],
        "pinned": account.pinned,
        "handoff": account.column == "ready_for_onboarding",
        "stalled_handoff": flags["stalled_handoff"],
        "column_stalled": flags["column_stalled"],
        # grouping inputs, never rendered on the card face
        "client_type": account.client_type,
        "quoted_total": account.quoted_total,
    }


def task_card(task: Task, account: Account) -> dict:
    today = date.today()
    overdue = task.status == "open" and task.due_date < today
    return {
        "kind": "task",
        "id": task.id,
        "account_id": account.id,
        "title": task.title,
        "type": task.type,
        "type_label": TASK_TYPE_TITLES.get(task.type, task.type),
        "bucket": task.bucket,
        "bucket_label": BUCKET_TITLES.get(task.bucket, task.bucket),
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat(),
        "days_until_due": (task.due_date - today).days,
        "overdue": overdue,
        "overdue_days": (today - task.due_date).days if overdue else 0,
        "provenance": task.provenance,
        "rule_key": task.rule_key,
        "sort_index": task.sort_index,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "account": {
            "id": account.id,
            "key": account.key,
            "name": account.name,
            "health_band": health_engine.effective_band(account),
        },
    }


# --- filters -----------------------------------------------------------------

def parse_filters(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def account_matches(ctx: BookContext, account: Account, f: dict) -> bool:
    if not f:
        return True
    band = health_engine.effective_band(account)
    parts = ctx.pnl_by_account.get(account.id) or pnl_engine.compute(account)
    flags = alert_engine.state_flags(ctx, account)

    if f.get("bands") and band not in f["bands"]:
        return False
    if f.get("modes") and account.mode not in f["modes"]:
        return False
    if f.get("client_types") and account.client_type not in f["client_types"]:
        return False
    if f.get("workstreams") and account.workstream not in f["workstreams"]:
        return False
    if f.get("columns") and account.column not in f["columns"]:
        return False
    if f.get("quoted_min") is not None and account.quoted_total < int(f["quoted_min"]):
        return False
    if f.get("quoted_max") is not None and account.quoted_total > int(f["quoted_max"]):
        return False
    if f.get("owner_id") and account.owner_id != f["owner_id"]:
        return False
    if f.get("tags") and not set(f["tags"]) & set(account.tags or []):
        return False
    if f.get("negative_margin"):
        # Null margin is unknown, not negative — it must not match.
        if parts["margin_pct"] is None or parts["gross_margin"] >= 0:
            return False
    if f.get("thin_margin"):
        if parts["margin_pct"] is None or parts["margin_pct"] >= pnl_engine.MARGIN_AMBER:
            return False
    if f.get("stalled_handoff") and not flags["stalled_handoff"]:
        return False
    if f.get("column_stalled") and not flags["column_stalled"]:
        return False
    if f.get("no_contact") and not flags["no_contact"]:
        return False
    if f.get("overdue") and ctx.overdue_by_account.get(account.id, 0) == 0:
        return False
    if f.get("attention"):
        from engines.attention import ATTENTION_THRESHOLD

        if not account.pinned and score_account(ctx, account)["score"] < ATTENTION_THRESHOLD:
            return False
    if f.get("high_value") and account.quoted_total < ctx.top_quartile_quote():
        return False
    if f.get("q"):
        needle = str(f["q"]).lower()
        haystack = f"{account.name} {account.key} {account.poc_name or ''}".lower()
        if needle not in haystack:
            return False
    return True


# --- swimlanes ---------------------------------------------------------------

def lane_for(group_by: str, account: Account) -> tuple[str, str]:
    if group_by == "workstream":
        return account.workstream, WORKSTREAM_TITLES.get(account.workstream, account.workstream)
    if group_by == "mode":
        return account.mode, MODE_TITLES.get(account.mode, account.mode)
    if group_by == "client_type":
        return account.client_type, CLIENT_TYPE_TITLES.get(account.client_type, account.client_type)
    if group_by == "priority":
        band = health_engine.effective_band(account)
        key = {"critical": "critical", "at_risk": "high", "watch": "normal", "healthy": "normal"}[band]
        return key, {"critical": "Critical", "high": "High", "normal": "Normal"}[key]
    return "all", "All engagements"


LANE_ORDER = {
    "workstream": list(WORKSTREAM_TITLES),
    "mode": ["pilot", "customer"],
    "client_type": ["data_plus_voice_ai", "voice_ai_only"],
    "priority": ["critical", "high", "normal"],
}

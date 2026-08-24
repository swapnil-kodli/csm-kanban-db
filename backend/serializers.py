"""Card and column shapes. The server does the grouping; the client renders
columns as given (spec 03 §5).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from sqlmodel import Session, select

from models import Account, Contact, Milestone, Risk, Subscription, Task, User
from engines import alerts as alert_engine
from engines import health as health_engine
from engines.attention import BookContext, score_account

STAGE_TITLES = {
    "ready_for_onboarding": "Ready for Onboarding",
    "onboarding": "Onboarding",
    "adopting": "Adopting",
    "healthy": "Healthy",
    "renewal": "Renewal",
    "closed": "Closed",
}
STAGE_DOTS = {
    "ready_for_onboarding": "s-handoff",
    "onboarding": "s-onboarding",
    "adopting": "s-adopting",
    "healthy": "s-healthy",
    "renewal": "s-renewal",
    "closed": "s-churned",
}
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
SEGMENT_TITLES = {"enterprise": "Enterprise", "mid_market": "Mid-Market", "smb": "SMB"}
TASK_TYPE_TITLES = {
    "onboarding": "Onboarding",
    "risk": "Risk",
    "renewal": "Renewal",
    "expansion": "Expansion",
    "checkin": "Check-in",
    "escalation": "Escalation",
    "admin": "Admin",
}

# Badge render order: red first, then amber, then informational.
BADGE_RANK = {
    "escalation": 0,
    "overdue": 1,
    "renewal": 2,
    "manual_risk": 3,
    "stalled_handoff": 4,
    "no_contact": 5,
    "handoff": 6,
    "expansion": 7,
}


# --- badges ------------------------------------------------------------------

def account_badges(ctx: BookContext, account: Account, flags: dict) -> list[dict]:
    badges: list[dict] = []
    dtr = flags["days_to_renewal"]

    if dtr is not None and 0 <= dtr <= 90:
        badges.append(
            {
                "key": "renewal",
                "label": f"Renewal in {dtr}d",
                "variant": "red" if dtr <= 30 else "amber",
            }
        )

    overdue = ctx.overdue_by_account.get(account.id, 0)
    if overdue:
        badges.append(
            {"key": "overdue", "label": f"{overdue} overdue", "variant": "red"}
        )

    escalations = ctx.open_escalations.get(account.id, 0)
    if escalations:
        label = f"{escalations} escalation" + ("s" if escalations > 1 else "")
        badges.append({"key": "escalation", "label": label, "variant": "red"})

    if flags["no_contact"]:
        badges.append(
            {
                "key": "no_contact",
                "label": f"No contact {flags['days_since_contact']}d",
                "variant": "grey",
            }
        )

    if account.expansion_flag:
        badges.append({"key": "expansion", "label": "Expansion", "variant": "green"})

    if account.lifecycle_stage == "ready_for_onboarding":
        badges.append({"key": "handoff", "label": "Handoff", "variant": "outline"})

    if flags["stalled_handoff"]:
        badges.append(
            {"key": "stalled_handoff", "label": "Stalled handoff", "variant": "red"}
        )

    if account.health_manual_override:
        badges.append(
            {"key": "manual_risk", "label": "Manual risk", "variant": "red-outline"}
        )

    badges.sort(key=lambda b: BADGE_RANK.get(b["key"], 99))
    return badges


# --- cards -------------------------------------------------------------------

def account_card(
    ctx: BookContext,
    account: Account,
    next_action: Optional[Task],
    scored: Optional[dict] = None,
) -> dict:
    flags = alert_engine.state_flags(ctx, account)
    scored = scored or score_account(ctx, account)
    delta = ctx.velocity_by_account.get(account.id)
    band = health_engine.effective_band(account)

    return {
        "kind": "account",
        "id": account.id,
        "account_id": account.id,
        "key": account.key,
        "name": account.name,
        "segment": account.segment,
        "segment_label": SEGMENT_TITLES.get(account.segment, account.segment),
        "city": account.city,
        "arr": account.arr,
        "lifecycle_stage": account.lifecycle_stage,
        "lifecycle_label": STAGE_TITLES.get(account.lifecycle_stage, ""),
        "lifecycle_dot": STAGE_DOTS.get(account.lifecycle_stage, "s-adopting"),
        "closed_reason": account.closed_reason,
        "health_score": account.health_score,
        "health_band": band,
        "computed_band": account.health_band,
        "health_band_label": health_engine.BAND_LABELS[band],
        "health_dot": BAND_DOTS[band],
        "is_overridden": account.health_manual_override is not None,
        "override_reason": account.health_override_reason,
        "velocity": delta,
        "days_to_renewal": flags["days_to_renewal"],
        "days_since_contact": flags["days_since_contact"],
        "expansion_flag": account.expansion_flag,
        "pinned": account.pinned,
        "attention_score": scored["score"],
        "badges": account_badges(ctx, account, flags),
        "next_action": (
            {
                "id": next_action.id,
                "title": next_action.title,
                "due_date": next_action.due_date.isoformat(),
                "overdue": next_action.due_date < date.today(),
            }
            if next_action
            else None
        ),
        "open_tasks": ctx.open_tasks_by_account.get(account.id, 0),
        "overdue_tasks": ctx.overdue_by_account.get(account.id, 0),
        "open_escalations": ctx.open_escalations.get(account.id, 0),
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
            "health_dot": BAND_DOTS[health_engine.effective_band(account)],
            "arr": account.arr,
            "segment": account.segment,
        },
    }


# --- next action -------------------------------------------------------------

def next_actions_by_account(session: Session) -> dict[str, Task]:
    """Top open task per account: soonest due, then critical priority first."""
    rank = {"critical": 0, "high": 1, "normal": 2}
    out: dict[str, Task] = {}
    tasks = session.exec(
        select(Task).where(Task.status == "open", Task.bucket != "done")
    ).all()
    for t in sorted(tasks, key=lambda t: (t.due_date, rank.get(t.priority, 3))):
        out.setdefault(t.account_id, t)
    return out


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
    """Ranked filters from spec 01 §6 plus the quick-filter chips."""
    if not f:
        return True
    flags = alert_engine.state_flags(ctx, account)
    band = health_engine.effective_band(account)
    dtr = flags["days_to_renewal"]
    dsc = flags["days_since_contact"]
    overdue = ctx.overdue_by_account.get(account.id, 0)

    if f.get("bands") and band not in f["bands"]:
        return False
    if f.get("renewal_window"):
        window = int(f["renewal_window"])
        if dtr is None or dtr < 0 or dtr > window:
            return False
    if f.get("arr_min") is not None and account.arr < int(f["arr_min"]):
        return False
    if f.get("arr_max") is not None and account.arr > int(f["arr_max"]):
        return False
    if f.get("owner_id") and account.owner_id != f["owner_id"]:
        return False
    if f.get("stages") and account.lifecycle_stage not in f["stages"]:
        return False
    if f.get("segments") and account.segment not in f["segments"]:
        return False
    if f.get("tags") and not set(f["tags"]) & set(account.tags or []):
        return False
    if f.get("last_contact_gt") is not None:
        threshold = int(f["last_contact_gt"])
        if dsc is None or dsc <= threshold:
            return False
    if f.get("expansion") and not account.expansion_flag:
        return False
    if f.get("overdue") and overdue == 0:
        return False
    if f.get("attention"):
        from engines.attention import ATTENTION_THRESHOLD

        if not account.pinned and score_account(ctx, account)["score"] < ATTENTION_THRESHOLD:
            return False
    if f.get("high_value"):
        if account.arr < ctx.top_quartile_arr():
            return False
    if f.get("q"):
        needle = str(f["q"]).lower()
        haystack = f"{account.name} {account.key} {account.city or ''}".lower()
        if needle not in haystack:
            return False
    return True


def task_matches(task: Task, account: Account, f: dict, matched_account: bool) -> bool:
    if not matched_account:
        return False
    if not f:
        return True
    if f.get("task_status") and task.status != f["task_status"]:
        return False
    if f.get("priorities") and task.priority not in f["priorities"]:
        return False
    if f.get("overdue") and not (task.status == "open" and task.due_date < date.today()):
        return False
    if f.get("q"):
        needle = str(f["q"]).lower()
        if needle not in f"{task.title} {account.name} {account.key}".lower():
            return False
    return True


# --- swimlanes ---------------------------------------------------------------

MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def lane_for(ctx: BookContext, group_by: str, card: dict, account: Account) -> tuple[str, str]:
    if group_by == "priority":
        if card["kind"] == "task":
            key = card["priority"]
            return key, {"critical": "Critical", "high": "High", "normal": "Normal"}[key]
        band = card["health_band"]
        key = {"critical": "critical", "at_risk": "high", "watch": "normal", "healthy": "normal"}[band]
        return key, {"critical": "Critical", "high": "High", "normal": "Normal"}[key]
    if group_by == "segment":
        return account.segment, SEGMENT_TITLES.get(account.segment, account.segment)
    if group_by == "renewal_month":
        rd = ctx.renewal_by_account.get(account.id)
        if rd is None:
            return "none", "No renewal date"
        return f"{rd.year}-{rd.month:02d}", f"{MONTHS[rd.month - 1]} {rd.year}"
    return "all", "All items"


LANE_ORDER = {
    "priority": ["critical", "high", "normal"],
    "segment": ["enterprise", "mid_market", "smb"],
}

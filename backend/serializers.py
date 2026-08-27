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

from models import Company, Contact, Deal, Risk, Task, User
from engines import alerts as alert_engine
from engines import health as health_engine
from engines import pnl as pnl_engine
from engines.attention import BookContext, score_deal

# Column titles, colours and order are no longer constants — they live in the
# board_column table and are user-editable. Nothing here may assume a key.

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


def attention_summary(scored: dict, limit: int = 3) -> Optional[str]:
    """One line explaining why a deal ranks where it does.

    The attention panel was removed, but a ranking nobody can interrogate is
    worse than a simple visible one — so the reasoning moves to the header strip
    rather than disappearing.

    Terms are kept in the order the formula weights them, not sorted by the
    value each happens to take, so the line reads as an explanation of the
    scoring rather than as a leaderboard of this deal's worst numbers.
    """
    active = [t for t in scored["terms"] if t["value"]]
    if not active:
        return None
    shown = active[:limit]
    rest = len(active) - len(shown)
    line = " · ".join(t["detail"] for t in shown)
    if rest:
        line += f" · +{rest} more"
    return line


# --- cards -------------------------------------------------------------------

def deal_card(
    ctx: BookContext, deal: Deal, scored: Optional[dict] = None,
    company: Optional[Company] = None,
) -> dict:
    """Exactly four things on the face of the card.

    `column` and `workstream` are different axes and both are real: the column
    is where the engagement sits in the pipeline, the workstream is what the
    team is doing on it right now. Dragging between columns must never change
    the workstream.
    """
    flags = alert_engine.state_flags(ctx, deal)
    scored = scored or score_deal(ctx, deal)
    band = health_engine.effective_band(deal)
    column = ctx.column_of(deal)
    company = company or ctx.company_by_id.get(deal.company_id)

    return {
        "kind": "deal",
        "id": deal.id,
        "deal_id": deal.id,
        # 1. name (+ key). The DEAL's name, not the company's — two engagements
        # for one client would otherwise render as identical cards.
        "key": deal.key,
        "name": deal.name,
        # The company chip. Opens the company detail view; never the card face's
        # primary label.
        "company_id": deal.company_id,
        "company_key": company.key if company else None,
        "company_name": company.name if company else "Unknown company",
        # 2. pilot / customer
        "mode": deal.mode,
        "mode_label": MODE_TITLES.get(deal.mode, deal.mode),
        # 3. workstream
        "workstream": deal.workstream,
        "workstream_label": WORKSTREAM_TITLES.get(deal.workstream, deal.workstream),
        "workstream_glyph": WORKSTREAM_GLYPHS.get(deal.workstream, "◔"),
        "workstream_dot": WORKSTREAM_DOTS.get(deal.workstream, "s-adopting"),
        # 4. health status
        "health_score": deal.health_score,
        "health_band": band,
        "health_band_label": health_engine.BAND_LABELS[band],
        "health_dot": BAND_DOTS[band],
        "is_overridden": deal.health_manual_override is not None,
        # board mechanics, not card content
        "column_id": deal.column_id,
        "column_key": column.key if column else None,
        "column_label": column.label if column else "Unassigned",
        "column_color": column.color if column else "#6b6b6b",
        "attention_score": scored["score"],
        "pinned": deal.pinned,
        # The column new work lands in IS the handoff inbox.
        "handoff": bool(column and column.is_default_entry),
        "stalled_handoff": flags["stalled_handoff"],
        "column_stalled": flags["column_stalled"],
        # grouping inputs, never rendered on the card face
        "client_type": company.client_type if company else "voice_ai_only",
        "quoted_total": deal.quoted_total,
        "outcome": deal.outcome,
    }


def task_card(task: Task, deal: Deal) -> dict:
    today = date.today()
    overdue = task.status == "open" and task.due_date < today
    return {
        "kind": "task",
        "id": task.id,
        "deal_id": deal.id,
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
        "deal": {
            "id": deal.id,
            "key": deal.key,
            "name": deal.name,
            "health_band": health_engine.effective_band(deal),
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


def deal_matches(ctx: BookContext, deal: Deal, f: dict) -> bool:
    if not f:
        return True
    band = health_engine.effective_band(deal)
    parts = ctx.pnl_by_deal.get(deal.id) or pnl_engine.compute(deal)
    flags = alert_engine.state_flags(ctx, deal)

    if f.get("bands") and band not in f["bands"]:
        return False
    if f.get("modes") and deal.mode not in f["modes"]:
        return False
    company = ctx.company_by_id.get(deal.company_id)
    # client_type, owner and tags describe the CLIENT, so they are read off the
    # company even though the card being filtered is a deal.
    if f.get("client_types") and (
        company is None or company.client_type not in f["client_types"]
    ):
        return False
    if f.get("workstreams") and deal.workstream not in f["workstreams"]:
        return False
    if f.get("columns"):
        column = ctx.column_of(deal)
        # Filters store the immutable key, so a rename never breaks them.
        if column is None or column.key not in f["columns"]:
            return False
    if f.get("quoted_min") is not None and deal.quoted_total < int(f["quoted_min"]):
        return False
    if f.get("quoted_max") is not None and deal.quoted_total > int(f["quoted_max"]):
        return False
    if f.get("owner_id") and (company is None or company.owner_id != f["owner_id"]):
        return False
    if f.get("tags") and not set(f["tags"]) & set((company.tags if company else []) or []):
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
    if f.get("overdue") and ctx.overdue_by_deal.get(deal.id, 0) == 0:
        return False
    if f.get("attention"):
        from engines.attention import ATTENTION_THRESHOLD

        if not deal.pinned and score_deal(ctx, deal)["score"] < ATTENTION_THRESHOLD:
            return False
    if f.get("high_value"):
        cut = ctx.top_quartile_quote()
        # None below the client-count floor: the filter matches nothing rather
        # than comparing against a quartile that does not describe anything.
        if cut is None or deal.quoted_total < cut:
            return False
    if f.get("q"):
        # `deal.poc_name` was in this string until the split. It had not existed
        # since v4 folded the flat poc_* fields into `contact`, so every board
        # request carrying a `q` filter 500'd on AttributeError. The POC now
        # comes off the contact row, which is where it actually lives.
        needle = str(f["q"]).lower()
        poc = ctx.contact_by_id.get(deal.poc_id)
        haystack = " ".join(
            filter(None, [
                deal.name, deal.key,
                company.name if company else None,
                company.key if company else None,
                poc.name if poc else None,
                poc.email if poc else None,
            ])
        ).lower()
        if needle not in haystack:
            return False
    return True


# --- swimlanes ---------------------------------------------------------------

def lane_for(group_by: str, deal: Deal, company: Optional[Company] = None) -> tuple[str, str]:
    if group_by == "workstream":
        return deal.workstream, WORKSTREAM_TITLES.get(deal.workstream, deal.workstream)
    if group_by == "mode":
        return deal.mode, MODE_TITLES.get(deal.mode, deal.mode)
    if group_by == "client_type":
        # A property of the client, read through the deal's company.
        ct = company.client_type if company else "voice_ai_only"
        return ct, CLIENT_TYPE_TITLES.get(ct, ct)
    if group_by == "priority":
        band = health_engine.effective_band(deal)
        key = {"critical": "critical", "at_risk": "high", "watch": "normal", "healthy": "normal"}[band]
        return key, {"critical": "Critical", "high": "High", "normal": "Normal"}[key]
    return "all", "All engagements"


LANE_ORDER = {
    "workstream": list(WORKSTREAM_TITLES),
    "mode": ["pilot", "customer"],
    "client_type": ["data_plus_voice_ai", "voice_ai_only"],
    "priority": ["critical", "high", "normal"],
}


# --- company rollup ----------------------------------------------------------

# Worst band first. The rollup takes the WORST active deal's band rather than a
# mean, because a mean is the one answer that is always wrong here: a client
# with one critical engagement and two healthy ones is a client at risk, and
# averaging says "watch". If one engagement is failing, the relationship is
# exposed regardless of what else is going well.
BAND_SEVERITY = {"critical": 0, "at_risk": 1, "watch": 2, "healthy": 3}


def company_health_rollup(deals: list[Deal]) -> dict:
    """Worst active band, with the count that makes it readable.

    Renders as "At Risk — 1 of 3 deals": the band alone hides how much of the
    relationship it describes, and the count alone hides the severity.

    No active deals means no band at all — null, not "healthy". A dormant client
    is not a well client, and null-is-neutral says an absent input degrades the
    signal to off rather than inventing a good one.
    """
    active = [d for d in deals if d.outcome == "active" and d.archived_at is None]
    if not active:
        return {"band": None, "band_label": None, "dot": None,
                "worst_count": 0, "active_count": 0}

    bands = [health_engine.effective_band(d) for d in active]
    worst = min(bands, key=lambda b: BAND_SEVERITY.get(b, 9))
    return {
        "band": worst,
        "band_label": health_engine.BAND_LABELS[worst],
        "dot": BAND_DOTS[worst],
        "worst_count": sum(1 for b in bands if b == worst),
        "active_count": len(active),
    }


def company_last_contact(deals: list[Deal]) -> Optional[str]:
    """Most recent contact across the company's active deals.

    Max, not min and not an average: the question a company view answers is
    "when did we last speak to these people at all", and that is the most recent
    touch on any live engagement.
    """
    stamps = [
        d.last_contact_at for d in deals
        if d.outcome == "active" and d.archived_at is None and d.last_contact_at
    ]
    return max(stamps).isoformat() if stamps else None


def company_totals(deals: list[Deal]) -> dict:
    """Deal counts by outcome, and money rolled across the whole relationship.

    Quoted value spans every non-archived deal regardless of outcome — the
    lifetime value of the relationship — while margin covers only what has
    actually been billed, so a lost deal nobody invoiced cannot drag it.
    """
    live = [d for d in deals if d.archived_at is None]
    counts = {o: sum(1 for d in live if d.outcome == o)
              for o in ("active", "completed", "lost")}

    revenue = sum(int(d.revenue_recognised or 0) for d in live)
    cost = sum(pnl_engine.total_cost(d) for d in live)
    gross_margin = revenue - cost
    return {
        "counts": counts,
        "total_deals": len(live),
        "quoted_total": sum(int(d.quoted_total or 0) for d in live),
        "revenue_recognised": revenue,
        "total_cost": cost,
        "gross_margin": gross_margin,
        # Unknown, not zero, when nothing has been billed across any deal.
        "margin_pct": round(gross_margin / revenue * 100, 1) if revenue > 0 else None,
    }

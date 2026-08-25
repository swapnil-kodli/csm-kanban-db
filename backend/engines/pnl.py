"""Costing and PNL. Margins are computed here, server-side, never stored and
never trusted from the client.

Putting PNL next to Costing is the point of these two panels: the gap between
what was quoted and what has actually been recognised is the number that tells
a delivery lead whether an engagement is drifting.
"""
from __future__ import annotations

from typing import Optional

from models import Account

# margin_pct colour ramp, reusing the health tokens so the board keeps one
# saturated channel per meaning.
MARGIN_GREEN = 40
MARGIN_AMBER = 20


def total_cost(account: Account) -> int:
    items = account.cost_items or []
    total = 0
    for item in items:
        if isinstance(item, dict):
            try:
                total += int(item.get("amount") or 0)
            except (TypeError, ValueError):
                continue
    return total


def quoted_total_from_items(account: Account) -> int:
    """Sum of qty x rate. The client never sets quoted_total directly."""
    total = 0
    for item in account.quoted_line_items or []:
        if isinstance(item, dict):
            try:
                total += int(item.get("qty") or 0) * int(item.get("rate") or 0)
            except (TypeError, ValueError):
                continue
    return total


def margin_band(margin_pct: Optional[float]) -> str:
    """Token name for the margin colour ramp. Unknown margin is not a colour."""
    if margin_pct is None:
        return "text-3"
    if margin_pct >= MARGIN_GREEN:
        return "h-healthy"
    if margin_pct >= MARGIN_AMBER:
        return "h-watch"
    return "h-critical"


def compute(account: Account) -> dict:
    cost = total_cost(account)
    revenue = int(account.revenue_recognised or 0)
    gross_margin = revenue - cost

    # Divide-by-zero guard: nothing billed yet is not "100% margin", it is
    # unknown. Rendered as an em dash rather than a colour.
    margin_pct: Optional[float] = None
    if revenue > 0:
        margin_pct = round(gross_margin / revenue * 100, 1)

    quoted = int(account.quoted_total or 0)
    return {
        "quoted_total": quoted,
        "quoted_at": account.quoted_at.isoformat() if account.quoted_at else None,
        "quote_notes": account.quote_notes,
        "quoted_line_items": account.quoted_line_items or [],
        "revenue_recognised": revenue,
        "cost_items": account.cost_items or [],
        "total_cost": cost,
        "gross_margin": gross_margin,
        "margin_pct": margin_pct,
        "margin_band": margin_band(margin_pct),
        # Quote-vs-actual drift, the reason these two panels sit together.
        "quote_gap": revenue - quoted,
        "quote_gap_pct": round((revenue - quoted) / quoted * 100, 1) if quoted else None,
    }


def is_underwater(account: Account) -> bool:
    """Negative margin, or thin enough to be worth a critical alert."""
    parts = compute(account)
    if parts["margin_pct"] is None:
        return False
    return parts["gross_margin"] < 0 or parts["margin_pct"] < MARGIN_AMBER

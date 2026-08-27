"""The five my-book counters, and the Needs Attention queue.

Still exactly five, still all clickable, still my-book counts. NRR / GRR /
churn / CLV remain deliberately absent — that is the executive-dashboard trap.

Every counter re-keyed to active DEALS in the split. Won/lost deliberately did
NOT become a sixth tile: it is a per-company fact, and it is only useful next to
which deals were won and lost, so it lives on the company view. Adding it here
would be the executive dashboard arriving through the side door.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from db import get_session
from engines import pnl as pnl_engine
from engines.attention import BookContext, needs_attention
from serializers import deal_card

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def get_metrics(session: Session = Depends(get_session)):
    ctx = BookContext(session)
    deals = ctx.deals

    attention_rows = needs_attention(ctx)
    pilots = [d for d in deals if d.mode == "pilot"]
    customers = [d for d in deals if d.mode == "customer"]

    quoted = sum(d.quoted_total for d in deals)
    revenue = sum(int(d.revenue_recognised or 0) for d in deals)
    cost = sum(pnl_engine.total_cost(d) for d in deals)
    gross_margin = revenue - cost
    margin_pct = round(gross_margin / revenue * 100, 1) if revenue > 0 else None

    at_risk = [
        d
        for d in deals
        if (d.health_manual_override or d.health_band) in ("at_risk", "critical")
    ]
    companies = len(ctx.company_ids)

    return {
        "metrics": [
            {
                "key": "needs_attention",
                "label": "Needs Attention",
                "value": len(attention_rows),
                "format": "count",
                "sub": "engagements flagged",
                "filters": {"attention": True},
            },
            {
                "key": "active_engagements",
                "label": "Active Engagements",
                "value": len(deals),
                "format": "count",
                "sub": f"{len(pilots)} pilots · {len(customers)} customers"
                       f" across {companies} {'client' if companies == 1 else 'clients'}",
                "filters": {},
            },
            {
                "key": "quoted_value",
                "label": "Quoted Value",
                "value": quoted,
                "format": "inr",
                "sub": f"{len(deals)} engagements",
                "filters": {},
            },
            {
                "key": "gross_margin",
                "label": "Gross Margin",
                "value": gross_margin,
                "format": "inr",
                "sub": f"{margin_pct}% margin" if margin_pct is not None else "nothing billed yet",
                "margin_band": pnl_engine.margin_band(margin_pct),
                "filters": {"thin_margin": True},
            },
            {
                "key": "at_risk",
                "label": "At Risk",
                "value": len(at_risk),
                "format": "count",
                "sub": "at risk or critical",
                "filters": {"bands": ["at_risk", "critical"]},
            },
        ]
    }


@router.get("/attention")
def get_attention(
    limit: int = Query(10, ge=1, le=50), session: Session = Depends(get_session)
):
    ctx = BookContext(session)
    rows = needs_attention(ctx)[:limit]
    return {
        "deals": [
            {
                **deal_card(ctx, deal, scored),
                "attention_terms": [t for t in scored["terms"] if t["value"]],
            }
            for deal, scored in rows
        ],
        "count": len(rows),
    }

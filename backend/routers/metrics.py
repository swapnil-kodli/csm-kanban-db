"""The five my-book counters, and the Needs Attention queue.

Still exactly five, still all clickable, still my-book counts. NRR / GRR /
churn / CLV remain deliberately absent — that is the executive-dashboard trap.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from db import get_session
from engines import pnl as pnl_engine
from engines.attention import BookContext, needs_attention
from serializers import account_card

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def get_metrics(session: Session = Depends(get_session)):
    ctx = BookContext(session)
    accounts = ctx.accounts

    attention_rows = needs_attention(ctx)
    pilots = [a for a in accounts if a.mode == "pilot"]
    customers = [a for a in accounts if a.mode == "customer"]

    quoted = sum(a.quoted_total for a in accounts)
    revenue = sum(int(a.revenue_recognised or 0) for a in accounts)
    cost = sum(pnl_engine.total_cost(a) for a in accounts)
    gross_margin = revenue - cost
    margin_pct = round(gross_margin / revenue * 100, 1) if revenue > 0 else None

    at_risk = [
        a
        for a in accounts
        if (a.health_manual_override or a.health_band) in ("at_risk", "critical")
    ]

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
                "value": len(accounts),
                "format": "count",
                "sub": f"{len(pilots)} pilots · {len(customers)} customers",
                "filters": {},
            },
            {
                "key": "quoted_value",
                "label": "Quoted Value",
                "value": quoted,
                "format": "inr",
                "sub": f"{len(accounts)} engagements",
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
        "accounts": [
            {
                **account_card(ctx, account, scored),
                "attention_terms": [t for t in scored["terms"] if t["value"]],
            }
            for account, scored in rows
        ],
        "count": len(rows),
    }

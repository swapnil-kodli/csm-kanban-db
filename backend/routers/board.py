"""GET /api/board — the server groups; the client renders columns as given."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from db import get_session
from models import Account, Task
from engines.attention import BookContext, score_account
from serializers import (
    BAND_DOTS,
    BUCKET_TITLES,
    LANE_ORDER,
    STAGE_DOTS,
    STAGE_TITLES,
    account_card,
    account_matches,
    lane_for,
    next_actions_by_account,
    parse_filters,
    task_card,
    task_matches,
)

router = APIRouter(prefix="/board", tags=["board"])

WORK_COLUMNS = ["today", "this_week", "follow_up", "waiting", "done"]
HEALTH_COLUMNS = ["healthy", "watch", "at_risk", "critical"]
HEALTH_TITLES = {
    "healthy": "Healthy",
    "watch": "Watch",
    "at_risk": "At Risk",
    "critical": "Critical",
}
LIFECYCLE_COLUMNS = [
    "ready_for_onboarding",
    "onboarding",
    "adopting",
    "healthy",
    "renewal",
    "closed",
]


@router.get("")
def get_board(
    view: str = Query("work", pattern="^(work|health|lifecycle)$"),
    group_by: str = Query("none", pattern="^(none|priority|segment|renewal_month)$"),
    filters: Optional[str] = None,
    session: Session = Depends(get_session),
):
    f = parse_filters(filters)
    ctx = BookContext(session)
    accounts = {a.id: a for a in ctx.accounts}
    match_cache = {a.id: account_matches(ctx, a, f) for a in ctx.accounts}
    scored = {a.id: score_account(ctx, a) for a in ctx.accounts}

    if view == "work":
        columns, cards = _work_columns(session, ctx, accounts, match_cache, f)
    elif view == "health":
        columns, cards = _health_columns(session, ctx, accounts, match_cache, scored)
    else:
        columns, cards = _lifecycle_columns(session, ctx, accounts, match_cache, scored)

    swimlanes = _swimlanes(ctx, group_by, cards, accounts)

    return {
        "view": view,
        "group_by": group_by,
        "columns": columns,
        "swimlanes": swimlanes,
        "total_cards": len(cards),
    }


def _decorate_lane(ctx, group_by, cards, accounts):
    for card in cards:
        account = accounts[card["account_id"]]
        key, title = lane_for(ctx, group_by, card, account)
        card["lane"] = key
        card["lane_title"] = title


def _swimlanes(ctx, group_by, cards, accounts):
    if group_by == "none":
        _decorate_lane(ctx, "none", cards, accounts)
        return []
    _decorate_lane(ctx, group_by, cards, accounts)
    lanes: dict[str, dict] = {}
    for card in cards:
        lane = lanes.setdefault(
            card["lane"],
            {"key": card["lane"], "title": card["lane_title"], "count": 0, "total_arr": 0},
        )
        lane["count"] += 1
        lane["total_arr"] += (
            card["arr"] if card["kind"] == "account" else card["account"]["arr"]
        )
    order = LANE_ORDER.get(group_by)
    out = list(lanes.values())
    if order:
        out.sort(key=lambda l: order.index(l["key"]) if l["key"] in order else 99)
    else:
        out.sort(key=lambda l: l["key"])
    return out


def _work_columns(session, ctx, accounts, match_cache, f):
    """Cards here are Tasks, each linked to an account."""
    tasks = session.exec(select(Task)).all()
    cards: list[dict] = []
    for t in tasks:
        account = accounts.get(t.account_id)
        if account is None:
            continue
        if not task_matches(t, account, f, match_cache.get(t.account_id, False)):
            continue
        cards.append(task_card(t, account))

    prio = {"critical": 0, "high": 1, "normal": 2}
    columns = []
    for key in WORK_COLUMNS:
        col_cards = [c for c in cards if c["bucket"] == key]
        if key == "done":
            col_cards.sort(key=lambda c: (c["completed_at"] or ""), reverse=True)
        else:
            col_cards.sort(
                key=lambda c: (
                    c["sort_index"],
                    c["due_date"],
                    prio.get(c["priority"], 3),
                )
            )
        columns.append(
            {
                "key": key,
                "title": BUCKET_TITLES[key],
                "dot": "p-critical" if key == "today" else "text-3",
                "count": len(col_cards),
                "total_arr": sum(c["account"]["arr"] for c in col_cards),
                "cards": col_cards,
                "droppable": True,
                "drop_action": "task_bucket",
                "collapse_older_than_days": 7 if key == "done" else None,
            }
        )
    return columns, cards


def _account_cards(session, ctx, accounts, match_cache, scored, predicate):
    next_actions = next_actions_by_account(session)
    cards = []
    for account in ctx.accounts:
        if not match_cache.get(account.id, False):
            continue
        if not predicate(account):
            continue
        cards.append(
            account_card(ctx, account, next_actions.get(account.id), scored[account.id])
        )
    return cards


def _sorted_account_cards(cards):
    # Pinned first, then worst attention score first (spec 03 §3).
    return sorted(cards, key=lambda c: (not c["pinned"], -c["attention_score"], c["name"]))


def _health_columns(session, ctx, accounts, match_cache, scored):
    cards = _account_cards(
        session, ctx, accounts, match_cache, scored,
        lambda a: a.lifecycle_stage != "closed",
    )
    columns = []
    for key in HEALTH_COLUMNS:
        col_cards = _sorted_account_cards([c for c in cards if c["health_band"] == key])
        columns.append(
            {
                "key": key,
                "title": HEALTH_TITLES[key],
                "dot": BAND_DOTS[key],
                "count": len(col_cards),
                "total_arr": sum(c["arr"] for c in col_cards),
                "cards": col_cards,
                "droppable": True,
                # Dropping here never silently reclassifies — it opens the
                # override dialog and only writes on confirm with a reason.
                "drop_action": "health_override",
                "collapse_older_than_days": None,
            }
        )
    return columns, cards


def _lifecycle_columns(session, ctx, accounts, match_cache, scored):
    cards = _account_cards(session, ctx, accounts, match_cache, scored, lambda a: True)
    columns = []
    for key in LIFECYCLE_COLUMNS:
        col_cards = _sorted_account_cards([c for c in cards if c["lifecycle_stage"] == key])
        column = {
            "key": key,
            "title": STAGE_TITLES[key],
            "dot": STAGE_DOTS[key],
            "count": len(col_cards),
            "total_arr": sum(c["arr"] for c in col_cards),
            "cards": col_cards,
            "droppable": True,
            "drop_action": "lifecycle_stage",
            "collapse_older_than_days": None,
        }
        if key == "closed":
            # Closed splits into two sub-groups by closed_reason.
            column["subgroups"] = [
                {
                    "key": reason,
                    "title": title,
                    "cards": [c for c in col_cards if c["closed_reason"] == reason],
                }
                for reason, title in (("renewed", "Renewed"), ("churned", "Churned"))
            ]
        if key == "ready_for_onboarding":
            column["handoff_inbox"] = True
        columns.append(column)
    return columns, cards

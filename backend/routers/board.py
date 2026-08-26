"""GET /api/board — one board, five delivery columns. The server groups; the
client renders columns as given.

v1's three-view toggle is gone. Health is a card indicator and a filter now, not
a column set; tasks survive as an entity and live in the drawer, not as buckets.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from db import get_session
from engines.attention import BookContext, score_account
from serializers import (
    LANE_ORDER,
    account_card,
    account_matches,
    lane_for,
    parse_filters,
)

router = APIRouter(prefix="/board", tags=["board"])


@router.get("")
def get_board(
    group_by: str = Query(
        "none", pattern="^(none|priority|mode|client_type|workstream)$"
    ),
    filters: Optional[str] = None,
    session: Session = Depends(get_session),
):
    f = parse_filters(filters)
    ctx = BookContext(session)
    scored = {a.id: score_account(ctx, a) for a in ctx.accounts}

    cards = [
        account_card(ctx, a, scored[a.id])
        for a in ctx.accounts
        if account_matches(ctx, a, f)
    ]

    accounts_by_id = {a.id: a for a in ctx.accounts}
    for card in cards:
        key, title = lane_for(group_by, accounts_by_id[card["account_id"]])
        card["lane"] = key
        card["lane_title"] = title

    columns = []
    # Columns come from config, in configured order. Archived columns are hidden
    # from the board but keep their history and their rows.
    for column in ctx.columns:
        if column.is_archived:
            continue
        col_cards = sorted(
            [c for c in cards if c["column_id"] == column.id],
            key=lambda c: (not c["pinned"], -c["attention_score"], c["name"]),
        )
        columns.append(
            {
                "id": column.id,
                "key": column.key,
                "title": column.label,
                "color": column.color,
                "description": column.description,
                "position": column.position,
                "count": len(col_cards),
                "total_quoted": sum(c["quoted_total"] for c in col_cards),
                "cards": col_cards,
                "droppable": True,
                "is_default_entry": column.is_default_entry,
                "stalled_after_days": column.stalled_after_days,
            }
        )

    return {
        "group_by": group_by,
        "columns": columns,
        "swimlanes": _swimlanes(group_by, cards),
        "total_cards": len(cards),
        # `total_cards` is post-filter, so on its own it cannot tell the client
        # whether zero means "no clients yet" or "these filters match nothing".
        # Those are opposite situations wanting opposite calls to action, so the
        # unfiltered book size travels with the board.
        "book_size": len(ctx.accounts),
        "archived_count": ctx.archived_count,
    }


def _swimlanes(group_by: str, cards: list[dict]) -> list[dict]:
    if group_by == "none":
        return []
    lanes: dict[str, dict] = {}
    for card in cards:
        lane = lanes.setdefault(
            card["lane"],
            {"key": card["lane"], "title": card["lane_title"], "count": 0, "total_quoted": 0},
        )
        lane["count"] += 1
        lane["total_quoted"] += card["quoted_total"]
    order = LANE_ORDER.get(group_by)
    out = list(lanes.values())
    if order:
        out.sort(key=lambda l: order.index(l["key"]) if l["key"] in order else 99)
    else:
        out.sort(key=lambda l: l["key"])
    return out

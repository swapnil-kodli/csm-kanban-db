"""Attention score — ranks the Needs Attention queue and orders cards in columns.

    attention =
        band_weight        # critical 40, at_risk 28, watch 12, healthy 0
      + velocity_penalty   # max(0, -delta) capped at 20
      + margin_risk        # negative margin or <20%, +15
      + stalled_column     # no column change in 14 days, +10
      + escalation_weight  # 12 per open high-severity risk, cap 20
      + neglect_weight     # days_since_contact past the mode window, cap 10
      + overdue_weight     # 3 per overdue task, cap 12

`renewal_urgency` and `arr_weight` are gone: v2 has no renewal date and no ARR,
so both terms lost their inputs entirely.

Kept transparent on purpose: `terms` travels with the score so the drawer can
show its working. A pinned account always sorts first — human judgement
outranks the formula, always.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import Session, select

from models import Account, Risk, Task
from engines import health as health_engine
from engines import pnl as pnl_engine

BAND_WEIGHTS = {"critical": 40, "at_risk": 28, "watch": 12, "healthy": 0}

# An account is listed in Needs Attention at or above this score. Chosen so the
# queue stays a short list a CSM can actually work, not a second copy of the board.
ATTENTION_THRESHOLD = 35.0


STALLED_COLUMN_DAYS = 14


class BookContext:
    """Per-request cache of the whole book, so scoring N accounts stays one pass."""

    def __init__(self, session: Session):
        self.session = session
        self.accounts = session.exec(select(Account)).all()
        self.quote_ladder = sorted(a.quoted_total for a in self.accounts) or [0]
        self.pnl_by_account: dict[str, dict] = {
            a.id: pnl_engine.compute(a) for a in self.accounts
        }
        self.size_band_by_account: dict[str, str] = {
            a.id: health_engine.size_band_for(a.quoted_total, self.quote_ladder)
            for a in self.accounts
        }

        self.open_high_risks: dict[str, int] = {}
        for r in session.exec(select(Risk).where(Risk.status == "open")).all():
            if r.severity == "high":
                self.open_high_risks[r.account_id] = (
                    self.open_high_risks.get(r.account_id, 0) + 1
                )

        self.open_escalations: dict[str, int] = {}
        for r in session.exec(
            select(Risk).where(Risk.status == "open", Risk.type == "escalation")
        ).all():
            self.open_escalations[r.account_id] = (
                self.open_escalations.get(r.account_id, 0) + 1
            )

        today = date.today()
        self.overdue_by_account: dict[str, int] = {}
        self.open_tasks_by_account: dict[str, int] = {}
        for t in session.exec(select(Task).where(Task.status == "open")).all():
            self.open_tasks_by_account[t.account_id] = (
                self.open_tasks_by_account.get(t.account_id, 0) + 1
            )
            if t.due_date < today:
                self.overdue_by_account[t.account_id] = (
                    self.overdue_by_account.get(t.account_id, 0) + 1
                )

        self.velocity_by_account: dict[str, Optional[int]] = {
            a.id: health_engine.velocity(session, a.id) for a in self.accounts
        }

    def top_quartile_quote(self) -> int:
        ladder = self.quote_ladder
        if not ladder:
            return 0
        idx = int(round(0.75 * (len(ladder) - 1)))
        return ladder[idx]

    def days_in_column(self, account: Account) -> Optional[int]:
        if not account.column_changed_at:
            return None
        return (datetime.utcnow() - account.column_changed_at).days


def score_account(ctx: BookContext, account: Account) -> dict:
    delta = ctx.velocity_by_account.get(account.id)
    parts = ctx.pnl_by_account.get(account.id) or pnl_engine.compute(account)
    margin_pct = parts["margin_pct"]

    days_since_contact = None
    if account.last_contact_at:
        days_since_contact = (datetime.utcnow() - account.last_contact_at).days
    neglect_window = health_engine.MODE_THRESHOLDS.get(
        account.mode, health_engine.MODE_THRESHOLDS["customer"]
    )["neglect_days"]

    band = health_engine.effective_band(account)
    days_in_column = ctx.days_in_column(account)

    band_w = float(BAND_WEIGHTS.get(band, 0))
    velocity_w = float(min(20, max(0, -(delta or 0))))

    # A null margin means nothing has been billed yet, which is not a risk
    # signal. Only a known-thin or negative margin scores.
    margin_w = 15.0 if margin_pct is not None and margin_pct < pnl_engine.MARGIN_AMBER else 0.0

    stalled_w = (
        10.0
        if account.column != "launch"
        and days_in_column is not None
        and days_in_column > STALLED_COLUMN_DAYS
        else 0.0
    )
    escalation_w = float(min(20, 12 * ctx.open_high_risks.get(account.id, 0)))
    neglect_w = (
        round(min((days_since_contact - neglect_window) / 2, 10), 1)
        if days_since_contact is not None and days_since_contact > neglect_window
        else 0.0
    )
    overdue_w = float(min(12, 3 * ctx.overdue_by_account.get(account.id, 0)))

    total = round(
        band_w + velocity_w + margin_w + stalled_w + escalation_w + neglect_w + overdue_w, 1
    )

    return {
        "score": total,
        "terms": [
            {"label": "Health band", "detail": health_engine.BAND_LABELS[band], "value": band_w},
            {"label": "Health velocity", "detail": _delta_text(delta), "value": velocity_w},
            {"label": "Margin risk", "detail": _margin_text(margin_pct), "value": margin_w},
            {"label": "Stalled in column", "detail": _column_text(days_in_column), "value": stalled_w},
            {"label": "Open escalations", "detail": f"{ctx.open_high_risks.get(account.id, 0)} high-severity", "value": escalation_w},
            {"label": "Neglect", "detail": _contact_text(days_since_contact), "value": neglect_w},
            {"label": "Overdue tasks", "detail": f"{ctx.overdue_by_account.get(account.id, 0)} overdue", "value": overdue_w},
        ],
    }


def _margin_text(margin_pct: Optional[float]) -> str:
    if margin_pct is None:
        return "nothing billed yet"
    return f"{margin_pct}% gross margin"


def _column_text(days: Optional[int]) -> str:
    if days is None:
        return "never moved"
    return f"{days}d in this column"


def _delta_text(delta: Optional[int]) -> str:
    if delta is None:
        return "no history"
    if delta > 0:
        return f"up {delta} pts in 30d"
    if delta < 0:
        return f"down {abs(delta)} pts in 30d"
    return "flat over 30d"


def _contact_text(days: Optional[int]) -> str:
    if days is None:
        return "never contacted"
    return f"last contact {days}d ago"


def needs_attention(ctx: BookContext) -> list[tuple[Account, dict]]:
    """Active accounts at or above the threshold, worst first. Pinned always lead."""
    rows = []
    for a in ctx.accounts:
        scored = score_account(ctx, a)
        if a.pinned or scored["score"] >= ATTENTION_THRESHOLD:
            rows.append((a, scored))
    rows.sort(key=lambda r: (not r[0].pinned, -r[1]["score"], r[0].name))
    return rows


def refresh_cached_scores(session: Session) -> None:
    ctx = BookContext(session)
    for a in ctx.accounts:
        a.attention_score = score_account(ctx, a)["score"]
        session.add(a)
    session.commit()

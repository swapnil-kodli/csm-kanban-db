"""Attention score — ranks the Needs Attention queue and orders cards in columns.

    attention =
        band_weight        # critical 40, at_risk 28, watch 12, healthy 0
      + velocity_penalty   # max(0, -delta) capped at 20
      + renewal_urgency    # <=15d:25, <=30d:18, <=60d:10, <=90d:5, else 0
      + arr_weight         # percentile of account ARR within book, scaled 0-15
      + escalation_weight  # 12 per open high-severity risk, cap 20
      + neglect_weight     # days_since_contact > 14 ? min((d-14)/2, 10) : 0
      + overdue_weight     # 3 per overdue task, cap 12

Kept transparent on purpose: `terms` travels with the score so the drawer can
show its working. A pinned account always sorts first — human judgement
outranks the formula, always.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import Session, select

from models import Account, Risk, Subscription, Task
from engines import health as health_engine

BAND_WEIGHTS = {"critical": 40, "at_risk": 28, "watch": 12, "healthy": 0}

# An account is listed in Needs Attention at or above this score. Chosen so the
# queue stays a short list a CSM can actually work, not a second copy of the board.
ATTENTION_THRESHOLD = 35.0


def renewal_urgency(days_to_renewal: Optional[int]) -> int:
    if days_to_renewal is None or days_to_renewal < 0:
        return 0
    if days_to_renewal <= 15:
        return 25
    if days_to_renewal <= 30:
        return 18
    if days_to_renewal <= 60:
        return 10
    if days_to_renewal <= 90:
        return 5
    return 0


class BookContext:
    """Per-request cache of the whole book, so scoring N accounts stays one pass."""

    def __init__(self, session: Session):
        self.session = session
        self.accounts = session.exec(select(Account)).all()
        active = [a for a in self.accounts if a.lifecycle_stage != "closed"]
        self.arr_ladder = sorted(a.arr for a in active) or [0]

        self.renewal_by_account: dict[str, date] = {}
        for sub in session.exec(select(Subscription)).all():
            self.renewal_by_account[sub.account_id] = sub.renewal_date

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

    def arr_percentile(self, arr: int) -> float:
        ladder = self.arr_ladder
        below = sum(1 for v in ladder if v < arr)
        return below / max(1, len(ladder) - 1) if len(ladder) > 1 else 1.0

    def days_to_renewal(self, account_id: str) -> Optional[int]:
        rd = self.renewal_by_account.get(account_id)
        return None if rd is None else (rd - date.today()).days

    def top_quartile_arr(self) -> int:
        ladder = self.arr_ladder
        if not ladder:
            return 0
        idx = int(round(0.75 * (len(ladder) - 1)))
        return ladder[idx]


def score_account(ctx: BookContext, account: Account) -> dict:
    delta = ctx.velocity_by_account.get(account.id)
    dtr = ctx.days_to_renewal(account.id)

    days_since_contact = None
    if account.last_contact_at:
        days_since_contact = (datetime.utcnow() - account.last_contact_at).days

    band = health_engine.effective_band(account)

    band_w = float(BAND_WEIGHTS.get(band, 0))
    velocity_w = float(min(20, max(0, -(delta or 0))))
    renewal_w = float(renewal_urgency(dtr))
    arr_w = round(ctx.arr_percentile(account.arr) * 15, 1)
    escalation_w = float(min(20, 12 * ctx.open_high_risks.get(account.id, 0)))
    neglect_w = (
        round(min((days_since_contact - 14) / 2, 10), 1)
        if days_since_contact is not None and days_since_contact > 14
        else 0.0
    )
    overdue_w = float(min(12, 3 * ctx.overdue_by_account.get(account.id, 0)))

    total = round(
        band_w + velocity_w + renewal_w + arr_w + escalation_w + neglect_w + overdue_w, 1
    )

    return {
        "score": total,
        "terms": [
            {"label": "Health band", "detail": health_engine.BAND_LABELS[band], "value": band_w},
            {"label": "Health velocity", "detail": _delta_text(delta), "value": velocity_w},
            {"label": "Renewal urgency", "detail": _renewal_text(dtr), "value": renewal_w},
            {"label": "ARR weight", "detail": f"{int(ctx.arr_percentile(account.arr) * 100)}th pct of book", "value": arr_w},
            {"label": "Open escalations", "detail": f"{ctx.open_high_risks.get(account.id, 0)} high-severity", "value": escalation_w},
            {"label": "Neglect", "detail": _contact_text(days_since_contact), "value": neglect_w},
            {"label": "Overdue tasks", "detail": f"{ctx.overdue_by_account.get(account.id, 0)} overdue", "value": overdue_w},
        ],
    }


def _delta_text(delta: Optional[int]) -> str:
    if delta is None:
        return "no history"
    if delta > 0:
        return f"up {delta} pts in 30d"
    if delta < 0:
        return f"down {abs(delta)} pts in 30d"
    return "flat over 30d"


def _renewal_text(dtr: Optional[int]) -> str:
    if dtr is None:
        return "no subscription"
    if dtr < 0:
        return f"lapsed {abs(dtr)}d ago"
    return f"renews in {dtr}d"


def _contact_text(days: Optional[int]) -> str:
    if days is None:
        return "never contacted"
    return f"last contact {days}d ago"


def needs_attention(ctx: BookContext) -> list[tuple[Account, dict]]:
    """Active accounts at or above the threshold, worst first. Pinned always lead."""
    rows = []
    for a in ctx.accounts:
        if a.lifecycle_stage == "closed":
            continue
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

"""Health engine — score, band, velocity, manual override.

    usage_score      = normalize(active_users_14d_avg / entitled_seats) * 100     # 40%
    engagement_score = f(days_since_last_contact, meetings_90d, exec_touch_90d)   # 25%
    support_score    = 100 - penalty(open_escalations, tickets_30d)               # 20%
    sentiment_score  = last_nps_or_csat mapped to 0-100, default 70 if unknown    # 15%

    health_score = round(.40*usage + .25*engagement + .20*support + .15*sentiment)

Bands: >=75 healthy | 55-74 watch | 35-54 at_risk | <35 critical.
Velocity = score_today - score_30d_ago. Runs on any write touching usage,
activity, risk or sentiment (and on POST /api/jobs/recompute).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from models import (
    Account,
    Activity,
    Contact,
    HealthSnapshot,
    Risk,
    UsageMetric,
)

WEIGHTS = {"usage": 0.40, "engagement": 0.25, "support": 0.20, "sentiment": 0.15}
DEFAULT_SENTIMENT = 70

# Thresholds relative to the account, on two axes.
#
# MAGNITUDE thresholds key on `size_band`, derived from where the account's
# quoted_total falls in the book. That is the original intent: a 15% usage drop
# means something different on a small deal than on a large one. It is not about
# pilot status, which says nothing about deal size.
#
# The NO-CONTACT window keys on `mode` instead, and only that: a fragile six-week
# pilot dies of silence faster than an established customer does.
SIZE_THRESHOLDS: dict[str, dict[str, float]] = {
    "large": {
        "health_drop": -12,           # a big engagement sliding is the bigger story
        "usage_decline_ratio": 0.70,  # more surface area, more normal noise
    },
    "mid": {
        "health_drop": -15,
        "usage_decline_ratio": 0.75,
    },
    "small": {
        "health_drop": -18,
        "usage_decline_ratio": 0.85,  # a 15% drop on a small deal matters
    },
}

# Silence tolerance by engagement mode.
MODE_THRESHOLDS: dict[str, dict[str, float]] = {
    "pilot": {"no_contact_days": 7, "neglect_days": 7},
    "customer": {"no_contact_days": 14, "neglect_days": 14},
}

SIZE_BANDS = ("small", "mid", "large")


def size_band_for(quoted_total: int, ladder: list[int]) -> str:
    """Which third of the book's quoted values this account sits in.

    Quantiles, not fixed rupee cuts, so the bands stay meaningful as the book
    grows. A book too small to have quantiles is all `mid`.
    """
    ordered = sorted(v for v in ladder if v > 0)
    if len(ordered) < 3 or quoted_total <= 0:
        return "mid"
    lower = ordered[len(ordered) // 3]
    upper = ordered[2 * len(ordered) // 3]
    if quoted_total <= lower:
        return "small"
    if quoted_total >= upper:
        return "large"
    return "mid"


def thresholds(size_band: str, mode: str) -> dict:
    """Merged view of both axes for one account."""
    merged = dict(SIZE_THRESHOLDS.get(size_band, SIZE_THRESHOLDS["mid"]))
    merged.update(MODE_THRESHOLDS.get(mode, MODE_THRESHOLDS["customer"]))
    return merged


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def band_for(score: int) -> str:
    if score >= 75:
        return "healthy"
    if score >= 55:
        return "watch"
    if score >= 35:
        return "at_risk"
    return "critical"


BAND_LABELS = {
    "healthy": "Healthy",
    "watch": "Watch",
    "at_risk": "At Risk",
    "critical": "Critical",
}


# --- components --------------------------------------------------------------

def usage_component(
    session: Session, account: Account, on_day: Optional[date] = None
) -> int:
    """14-day average active users over entitled seats, normalised to 0-100."""
    on_day = on_day or date.today()
    window_start = on_day - timedelta(days=13)
    rows = session.exec(
        select(UsageMetric).where(
            UsageMetric.account_id == account.id,
            UsageMetric.captured_on >= window_start,
            UsageMetric.captured_on <= on_day,
        )
    ).all()
    if not rows or not account.entitled_seats:
        return DEFAULT_SENTIMENT
    avg_active = sum(r.active_users for r in rows) / len(rows)
    return int(round(_clamp(avg_active / account.entitled_seats * 100)))


def engagement_component(
    session: Session, account: Account, on_day: Optional[date] = None
) -> int:
    """Recency of contact, meeting cadence, and executive touch over 90 days."""
    on_day = on_day or date.today()
    horizon = datetime.combine(on_day, datetime.max.time())
    since = horizon - timedelta(days=90)
    acts = session.exec(
        select(Activity).where(
            Activity.account_id == account.id,
            Activity.occurred_at <= horizon,
            Activity.occurred_at >= since,
        )
    ).all()
    contactful = [a for a in acts if a.type in ("email", "call", "meeting", "qbr")]

    if contactful:
        last = max(a.occurred_at for a in contactful)
        days_since = max(0, (horizon - last).days)
    else:
        days_since = 90
    grace = MODE_THRESHOLDS.get(account.mode, MODE_THRESHOLDS["customer"])["neglect_days"] // 2
    recency = _clamp(100 - max(0, days_since - grace) * 3)

    meetings = len([a for a in acts if a.type in ("meeting", "qbr")])
    meeting_score = _clamp(meetings * 20)

    buyer_ids = {
        c.id
        for c in session.exec(
            select(Contact).where(
                Contact.account_id == account.id,
                Contact.is_economic_buyer == True,  # noqa: E712
            )
        ).all()
    }
    exec_touch = any(a.type == "qbr" or a.contact_id in buyer_ids for a in acts)
    exec_score = 100 if exec_touch else 55

    return int(round(_clamp(0.55 * recency + 0.30 * meeting_score + 0.15 * exec_score)))


def support_component(session: Session, account: Account) -> int:
    """100 minus a penalty for open risks, weighted by severity."""
    risks = session.exec(
        select(Risk).where(Risk.account_id == account.id, Risk.status == "open")
    ).all()
    penalty = 0
    for r in risks:
        base = {"high": 25, "medium": 12, "low": 6}.get(r.severity, 12)
        if r.type != "escalation":
            base = int(base * 0.7)
        penalty += base
    return int(round(_clamp(100 - penalty)))


def sentiment_component(account: Account) -> int:
    """NPS (-100..100) mapped to 0-100; 70 when unknown."""
    if account.last_nps is None:
        return DEFAULT_SENTIMENT
    return int(round(_clamp((account.last_nps + 100) / 2)))


def compose(usage: int, engagement: int, support: int, sentiment: int) -> int:
    return int(
        round(
            WEIGHTS["usage"] * usage
            + WEIGHTS["engagement"] * engagement
            + WEIGHTS["support"] * support
            + WEIGHTS["sentiment"] * sentiment
        )
    )


def solve_usage_for(target: int, engagement: int, support: int, sentiment: int) -> int:
    """Inverse of compose() — used by the seed to calibrate usage to a target score."""
    rest = (
        WEIGHTS["engagement"] * engagement
        + WEIGHTS["support"] * support
        + WEIGHTS["sentiment"] * sentiment
    )
    return int(round(_clamp((target - rest) / WEIGHTS["usage"])))


# --- snapshot + recompute ----------------------------------------------------

def compute_components(session: Session, account: Account) -> dict:
    usage = usage_component(session, account)
    engagement = engagement_component(session, account)
    support = support_component(session, account)
    sentiment = sentiment_component(account)
    return {
        "usage": usage,
        "engagement": engagement,
        "support": support,
        "sentiment": sentiment,
        "score": compose(usage, engagement, support, sentiment),
    }


def recompute_account(session: Session, account: Account, commit: bool = True) -> Account:
    """Recompute cached health for one account and upsert today's snapshot."""
    # last_contact_at is derived: notes and updates are not customer engagement.
    last_contact = session.exec(
        select(Activity)
        .where(
            Activity.account_id == account.id,
            Activity.type.in_(("email", "call", "meeting", "qbr")),  # type: ignore[attr-defined]
        )
        .order_by(Activity.occurred_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    account.last_contact_at = last_contact.occurred_at if last_contact else None

    parts = compute_components(session, account)
    account.health_score = parts["score"]
    account.health_band = band_for(parts["score"])
    account.updated_at = datetime.utcnow()

    today = date.today()
    snap = session.exec(
        select(HealthSnapshot).where(
            HealthSnapshot.account_id == account.id,
            HealthSnapshot.captured_on == today,
        )
    ).first()
    if snap is None:
        snap = HealthSnapshot(account_id=account.id, captured_on=today, **parts)
        session.add(snap)
    else:
        snap.score = parts["score"]
        snap.usage = parts["usage"]
        snap.engagement = parts["engagement"]
        snap.support = parts["support"]
        snap.sentiment = parts["sentiment"]
        snap.updated_at = datetime.utcnow()
        session.add(snap)

    session.add(account)
    if commit:
        session.commit()
        session.refresh(account)
    return account


def recompute_all(session: Session) -> int:
    accounts = session.exec(select(Account)).all()
    for a in accounts:
        recompute_account(session, a, commit=False)
    session.commit()
    return len(accounts)


def velocity(session: Session, account_id: str, days: int = 30) -> Optional[int]:
    """score_today - score_{days}d_ago. None when there is no history to compare."""
    today = date.today()
    then = today - timedelta(days=days)
    now_snap = session.exec(
        select(HealthSnapshot)
        .where(
            HealthSnapshot.account_id == account_id,
            HealthSnapshot.captured_on <= today,
        )
        .order_by(HealthSnapshot.captured_on.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    then_snap = session.exec(
        select(HealthSnapshot)
        .where(
            HealthSnapshot.account_id == account_id,
            HealthSnapshot.captured_on <= then,
        )
        .order_by(HealthSnapshot.captured_on.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    if not now_snap or not then_snap:
        return None
    return now_snap.score - then_snap.score


def effective_band(account: Account) -> str:
    """Manual override wins over the computed band everywhere in the UI."""
    return account.health_manual_override or account.health_band


def override_age_days(account: Account) -> Optional[int]:
    if not account.health_override_at:
        return None
    return (datetime.utcnow() - account.health_override_at).days

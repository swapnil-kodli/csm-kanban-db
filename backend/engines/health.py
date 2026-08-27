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

from datetime import date, datetime, timedelta, timezone

from dbtypes import days_between, days_since, utcnow
from typing import Optional

from sqlmodel import Session, select

from models import Deal, HealthSnapshot, Risk, UsageMetric

WEIGHTS = {"usage": 0.40, "engagement": 0.25, "support": 0.20, "sentiment": 0.15}
DEFAULT_SENTIMENT = 70

# Thresholds relative to the deal, on two axes.
#
# MAGNITUDE thresholds key on `size_band`, derived from where the deal's
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

# Below this many active DEALS, quantiles stop describing anything. With three
# deals one of them is always "large" and another always "small", purely by
# position — so the band would be an artefact of the count, not of the deal.
# Under the floor every deal takes the neutral middle band, which is
# null-is-neutral again: the rule degrades to off rather than to wrong.
#
# Counted in deals rather than companies since the split, which is the correct
# unit: a company running three 3L engagements should not band like one 9L
# client. It also means the floor clears sooner, so the fallback engages less.
MIN_DEALS_FOR_QUANTILES = 8
DEFAULT_SIZE_BAND = "mid"


def size_band_for(quoted_total: int, ladder: list[int]) -> str:
    """Which third of the book's quoted values this deal sits in.

    Quantiles, not fixed rupee cuts, so the bands stay meaningful as the book
    grows — but only once the book is large enough for thirds to mean anything.
    """
    ordered = sorted(v for v in ladder if v > 0)
    if len(ordered) < MIN_DEALS_FOR_QUANTILES or quoted_total <= 0:
        return DEFAULT_SIZE_BAND
    lower = ordered[len(ordered) // 3]
    upper = ordered[2 * len(ordered) // 3]
    if quoted_total <= lower:
        return "small"
    if quoted_total >= upper:
        return "large"
    return "mid"


def thresholds(size_band: str, mode: str) -> dict:
    """Merged view of both axes for one deal."""
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
    session: Session, deal: Deal, on_day: Optional[date] = None
) -> int:
    """14-day average active users over entitled seats, normalised to 0-100."""
    on_day = on_day or date.today()
    window_start = on_day - timedelta(days=13)
    rows = session.exec(
        select(UsageMetric).where(
            UsageMetric.deal_id == deal.id,
            UsageMetric.captured_on >= window_start,
            UsageMetric.captured_on <= on_day,
        )
    ).all()
    if not rows or not deal.entitled_seats:
        return DEFAULT_SENTIMENT
    avg_active = sum(r.active_users for r in rows) / len(rows)
    return int(round(_clamp(avg_active / deal.entitled_seats * 100)))


# Recency curve. `last_contact_at` is hand-maintained, so engagement is recency
# alone — the meeting-cadence and executive-touch terms were deleted with
# activity logging rather than left reading a table nothing writes.
#
# CEIL and SLOPE are calibrated, not chosen: they are set so that migrating from
# the old three-part composite leaves the health bands where they were. See
# `scripts/calibrate_engagement.py`.
RECENCY_CEIL = 78
RECENCY_SLOPE = 2.4
NEUTRAL_ENGAGEMENT = 70


def engagement_component(
    session: Session, deal: Deal, on_day: Optional[date] = None
) -> int:
    """Recency of the last recorded contact, and nothing else.

    Unset is unknown, not neglected: it scores NEUTRAL_ENGAGEMENT rather than 0.
    A deal nobody has filled in must not read as a deal nobody has
    called. See the standing principle in engines/__init__.py.
    """
    if deal.last_contact_at is None:
        return NEUTRAL_ENGAGEMENT

    on_day = on_day or date.today()
    # Aware, because last_contact_at comes back aware from Postgres and naive
    # from a pre-v5 SQLite row; days_between normalises both sides.
    horizon = datetime.combine(on_day, datetime.max.time(), tzinfo=timezone.utc)
    elapsed = max(0, days_between(horizon, deal.last_contact_at) or 0)

    # A pilot is given a shorter grace period than an established customer.
    grace = MODE_THRESHOLDS.get(deal.mode, MODE_THRESHOLDS["customer"])["neglect_days"] // 2
    return int(round(_clamp(RECENCY_CEIL - max(0, elapsed - grace) * RECENCY_SLOPE)))


def support_component(session: Session, deal: Deal) -> int:
    """100 minus a penalty for open risks, weighted by severity."""
    risks = session.exec(
        select(Risk).where(Risk.deal_id == deal.id, Risk.status == "open")
    ).all()
    penalty = 0
    for r in risks:
        base = {"high": 25, "medium": 12, "low": 6}.get(r.severity, 12)
        if r.type != "escalation":
            base = int(base * 0.7)
        penalty += base
    return int(round(_clamp(100 - penalty)))


def sentiment_component(deal: Deal) -> int:
    """NPS (-100..100) mapped to 0-100; 70 when unknown."""
    if deal.last_nps is None:
        return DEFAULT_SENTIMENT
    return int(round(_clamp((deal.last_nps + 100) / 2)))


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

def compute_components(session: Session, deal: Deal) -> dict:
    usage = usage_component(session, deal)
    engagement = engagement_component(session, deal)
    support = support_component(session, deal)
    sentiment = sentiment_component(deal)
    return {
        "usage": usage,
        "engagement": engagement,
        "support": support,
        "sentiment": sentiment,
        "score": compose(usage, engagement, support, sentiment),
    }


def recompute_deal(session: Session, deal: Deal, commit: bool = True) -> Deal:
    """Recompute cached health for one deal and upsert today's snapshot."""
    # last_contact_at is hand-maintained in the drawer now; the engine reads it
    # and never overwrites it.
    parts = compute_components(session, deal)
    deal.health_score = parts["score"]
    deal.health_band = band_for(parts["score"])
    deal.updated_at = utcnow()

    today = date.today()
    snap = session.exec(
        select(HealthSnapshot).where(
            HealthSnapshot.deal_id == deal.id,
            HealthSnapshot.captured_on == today,
        )
    ).first()
    if snap is None:
        snap = HealthSnapshot(deal_id=deal.id, captured_on=today, **parts)
        session.add(snap)
    else:
        snap.score = parts["score"]
        snap.usage = parts["usage"]
        snap.engagement = parts["engagement"]
        snap.support = parts["support"]
        snap.sentiment = parts["sentiment"]
        snap.updated_at = utcnow()
        session.add(snap)

    session.add(deal)
    if commit:
        session.commit()
        session.refresh(deal)
    return deal


def recompute_all(session: Session) -> int:
    deals = session.exec(
        select(Deal).where(
            Deal.archived_at == None,  # noqa: E711
            Deal.outcome == "active",
        )
    ).all()
    for d in deals:
        recompute_deal(session, d, commit=False)
    session.commit()
    return len(deals)


def velocity(session: Session, deal_id: str, days: int = 30) -> Optional[int]:
    """score_today - score_{days}d_ago. None when there is no history to compare."""
    today = date.today()
    then = today - timedelta(days=days)
    now_snap = session.exec(
        select(HealthSnapshot)
        .where(
            HealthSnapshot.deal_id == deal_id,
            HealthSnapshot.captured_on <= today,
        )
        .order_by(HealthSnapshot.captured_on.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    then_snap = session.exec(
        select(HealthSnapshot)
        .where(
            HealthSnapshot.deal_id == deal_id,
            HealthSnapshot.captured_on <= then,
        )
        .order_by(HealthSnapshot.captured_on.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    if not now_snap or not then_snap:
        return None
    return now_snap.score - then_snap.score


def effective_band(deal: Deal) -> str:
    """Manual override wins over the computed band everywhere in the UI."""
    return deal.health_manual_override or deal.health_band


def override_age_days(deal: Deal) -> Optional[int]:
    if not deal.health_override_at:
        return None
    return days_since(deal.health_override_at)

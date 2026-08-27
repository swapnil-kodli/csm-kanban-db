"""Alert engine — rules evaluate to owned tasks, or to board state.

The governing rule (spec 01 §7): an alert is only allowed to exist if it becomes
a task someone owns. Anything that fails that test changes board state instead.
There is no bell icon and no unread count anywhere in this product.

Idempotent by construction: never a second *open* task for the same
(deal_id, rule_key) pair.

Thresholds are relative to the deal on two axes (see engines/health.py):
magnitude keys on `size_band`, derived from quoted_total quantiles across the
book, because a 15% usage drop means something different on a small deal than a
large one; the no-contact window keys on `mode`, because a fragile pilot dies of
silence faster than an established customer.

Task-creating rules:  health_drop · high_value_at_risk · margin_negative ·
                      champion_departed · usage_decline · escalation_open
State-only signals:   no_contact · stalled_handoff · column_stalled

`renewal_90/60/30` are gone with the renewal model. `milestone_overdue` is gone
with the milestone table and is deliberately NOT replaced: `column_stalled` on
the onboarding column already covers that visibility gap, and a second stall
rule would double-fire on the same deal.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from dbtypes import days_since, utcnow
from typing import Optional

from sqlmodel import Session, select

from models import Contact, Deal, Risk, Task, UsageMetric, User
from engines import health as health_engine
from engines import pnl as pnl_engine
from engines.attention import STALLED_COLUMN_DAYS, BookContext

CRITICAL = "critical"
IMPORTANT = "important"
STATE = "state"


def _open_rule_task(session: Session, deal_id: str, rule_key: str) -> Optional[Task]:
    return session.exec(
        select(Task).where(
            Task.deal_id == deal_id,
            Task.rule_key == rule_key,
            Task.status == "open",
        )
    ).first()


def _emit(
    session: Session,
    deal: Deal,
    owner_id: str,
    rule_key: str,
    title: str,
    provenance: str,
    task_type: str,
    bucket: str,
    priority: str,
    due_in_days: int,
) -> Optional[Task]:
    """Create the owned task for a rule, unless one is already open."""
    if _open_rule_task(session, deal.id, rule_key):
        return None
    task = Task(
        deal_id=deal.id,
        title=title,
        type=task_type,
        bucket=bucket,
        due_date=date.today() + timedelta(days=due_in_days),
        status="open",
        priority=priority,
        owner_id=owner_id,
        provenance=provenance,
        rule_key=rule_key,
        sort_index=float(utcnow().timestamp()),
    )
    session.add(task)
    return task


# --- usage helper ------------------------------------------------------------

def usage_decline_ratio(session: Session, deal_id: str) -> Optional[float]:
    """14d active-user average over the prior 14d average."""
    today = date.today()
    recent = session.exec(
        select(UsageMetric).where(
            UsageMetric.deal_id == deal_id,
            UsageMetric.captured_on > today - timedelta(days=14),
            UsageMetric.captured_on <= today,
        )
    ).all()
    prior = session.exec(
        select(UsageMetric).where(
            UsageMetric.deal_id == deal_id,
            UsageMetric.captured_on > today - timedelta(days=28),
            UsageMetric.captured_on <= today - timedelta(days=14),
        )
    ).all()
    if not recent or not prior:
        return None
    prior_avg = sum(r.active_users for r in prior) / len(prior)
    if prior_avg <= 0:
        return None
    recent_avg = sum(r.active_users for r in recent) / len(recent)
    return recent_avg / prior_avg


# --- board state (badges, never a push) --------------------------------------

def state_flags(ctx: BookContext, deal: Deal) -> dict:
    """Info-tier signals. These change board state; they never create a task."""
    days_since_contact = days_since(deal.last_contact_at)
    size_band = ctx.size_band_by_deal.get(deal.id, "mid")
    th = health_engine.thresholds(size_band, deal.mode)
    days_in_column = ctx.days_in_column(deal)
    column = ctx.column_of(deal)

    # The column new work lands in IS the handoff inbox — one flag, not two
    # ideas. Stalling anywhere, including there, is one per-column threshold.
    is_entry = bool(column and column.is_default_entry)
    stalled = ctx.is_stalled(deal)

    return {
        "no_contact": days_since_contact is not None
        and days_since_contact > th["no_contact_days"],
        "stalled_handoff": stalled and is_entry,
        "column_stalled": stalled and not is_entry,
        "days_since_contact": days_since_contact,
        "days_in_column": days_in_column,
        "size_band": size_band,
    }


# --- rule evaluation ---------------------------------------------------------

def evaluate(session: Session) -> dict:
    """Run every rule across the book. Returns a summary of what was created."""
    owner = session.exec(select(User)).first()
    if owner is None:
        return {"created": 0, "rules": []}

    ctx = BookContext(session)
    created: list[dict] = []

    contacts_by_company: dict[str, list[Contact]] = {}
    for c in session.exec(select(Contact)).all():
        contacts_by_company.setdefault(c.company_id, []).append(c)

    escalations_by_deal: dict[str, list[Risk]] = {}
    for r in session.exec(
        select(Risk).where(Risk.status == "open", Risk.type == "escalation")
    ).all():
        escalations_by_deal.setdefault(r.deal_id, []).append(r)

    top_quartile = ctx.top_quartile_quote()

    for deal in ctx.deals:
        size_band = ctx.size_band_by_deal.get(deal.id, "mid")
        th = health_engine.thresholds(size_band, deal.mode)
        band = health_engine.effective_band(deal)
        delta = ctx.velocity_by_deal.get(deal.id)

        def emit(**kw):
            t = _emit(session, deal, owner.id, **kw)
            if t is not None:
                created.append(
                    {"deal": deal.key, "rule_key": kw["rule_key"], "title": t.title}
                )

        # --- critical -------------------------------------------------------
        if delta is not None and delta <= th["health_drop"]:
            emit(
                rule_key="health_drop",
                title=f"Diagnose {abs(delta)}-point health drop",
                provenance=f"Alert: health dropped {abs(delta)} pts in 30d",
                task_type="risk",
                bucket="today",
                priority="critical",
                due_in_days=0,
            )

        # top_quartile is None below the client-count floor: the rule is skipped
        # entirely rather than firing on whoever is merely biggest.
        if (
            top_quartile is not None
            and band in ("at_risk", "critical")
            and deal.quoted_total >= top_quartile
        ):
            emit(
                rule_key="high_value_at_risk",
                title=f"Run risk playbook — {deal.name}",
                provenance=(
                    f"Alert: top-quartile engagement moved to "
                    f"{health_engine.BAND_LABELS[band]}"
                ),
                task_type="risk",
                bucket="today",
                priority="critical",
                due_in_days=0,
            )

        # A known-negative margin is a commercial emergency; a null margin
        # (nothing billed yet) is not, and must not fire.
        margin = ctx.pnl_by_deal.get(deal.id, {}).get("margin_pct")
        if margin is not None and pnl_engine.compute(deal)["gross_margin"] < 0:
            emit(
                rule_key="margin_negative",
                title=f"Margin underwater — {deal.name}",
                provenance=f"Alert: gross margin negative at {margin}%",
                task_type="admin",
                bucket="today",
                priority="critical",
                due_in_days=1,
            )

        departed_champions = [
            c
            for c in contacts_by_company.get(deal.id, [])
            if c.is_champion and c.status == "departed"
        ]
        if departed_champions:
            who = departed_champions[0].name
            emit(
                rule_key="champion_departed",
                title=f"Map new champion after {who} exit",
                provenance="Alert: champion contact departed",
                task_type="risk",
                bucket="today",
                priority="critical",
                due_in_days=1,
            )

        # --- important ------------------------------------------------------
        ratio = usage_decline_ratio(session, deal.id)
        if ratio is not None and ratio <= th["usage_decline_ratio"]:
            emit(
                rule_key="usage_decline",
                title="Investigate sustained usage decline",
                provenance=f"Alert: usage down {int(round((1 - ratio) * 100))}% over 14d",
                task_type="risk",
                bucket="this_week",
                priority="high",
                due_in_days=3,
            )

        for esc in escalations_by_deal.get(deal.id, []):
            emit(
                rule_key="escalation_open",
                title="Escalation follow-up with support",
                provenance=f"Alert: escalation opened — {esc.note or 'support escalation'}",
                task_type="escalation",
                bucket="this_week",
                priority="high",
                due_in_days=2,
            )
            break

    session.commit()
    return {"created": len(created), "rules": created}

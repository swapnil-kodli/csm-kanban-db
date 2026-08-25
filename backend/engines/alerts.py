"""Alert engine — rules evaluate to owned tasks, or to board state.

The governing rule (spec 01 §7): an alert is only allowed to exist if it becomes
a task someone owns. Anything that fails that test changes board state instead.
There is no bell icon and no unread count anywhere in this product.

Idempotent by construction: never a second *open* task for the same
(account_id, rule_key) pair.

Thresholds are relative to the account on two axes (see engines/health.py):
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
rule would double-fire on the same account.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from models import Account, Contact, Risk, Task, UsageMetric, User
from engines import health as health_engine
from engines import pnl as pnl_engine
from engines.attention import STALLED_COLUMN_DAYS, BookContext

CRITICAL = "critical"
IMPORTANT = "important"
STATE = "state"


def _open_rule_task(session: Session, account_id: str, rule_key: str) -> Optional[Task]:
    return session.exec(
        select(Task).where(
            Task.account_id == account_id,
            Task.rule_key == rule_key,
            Task.status == "open",
        )
    ).first()


def _emit(
    session: Session,
    account: Account,
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
    if _open_rule_task(session, account.id, rule_key):
        return None
    task = Task(
        account_id=account.id,
        title=title,
        type=task_type,
        bucket=bucket,
        due_date=date.today() + timedelta(days=due_in_days),
        status="open",
        priority=priority,
        owner_id=owner_id,
        provenance=provenance,
        rule_key=rule_key,
        sort_index=float(datetime.utcnow().timestamp()),
    )
    session.add(task)
    return task


# --- usage helper ------------------------------------------------------------

def usage_decline_ratio(session: Session, account_id: str) -> Optional[float]:
    """14d active-user average over the prior 14d average."""
    today = date.today()
    recent = session.exec(
        select(UsageMetric).where(
            UsageMetric.account_id == account_id,
            UsageMetric.captured_on > today - timedelta(days=14),
            UsageMetric.captured_on <= today,
        )
    ).all()
    prior = session.exec(
        select(UsageMetric).where(
            UsageMetric.account_id == account_id,
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

def state_flags(ctx: BookContext, account: Account) -> dict:
    """Info-tier signals. These change board state; they never create a task."""
    days_since_contact = (
        (datetime.utcnow() - account.last_contact_at).days
        if account.last_contact_at
        else None
    )
    size_band = ctx.size_band_by_account.get(account.id, "mid")
    th = health_engine.thresholds(size_band, account.mode)
    days_in_column = ctx.days_in_column(account)

    # v2 keeps the v1 handoff treatment, still keyed to the entry column.
    stalled_handoff = False
    if account.column == "ready_for_onboarding" and account.handoff_received_at:
        stalled_handoff = (datetime.utcnow() - account.handoff_received_at).days > 3

    return {
        "no_contact": days_since_contact is not None
        and days_since_contact > th["no_contact_days"],
        "stalled_handoff": stalled_handoff,
        # Launch is the terminal column: sitting there is delivery, not drift.
        # Flagging it would put a stalled badge on every healthy engagement and
        # the signal would stop meaning anything.
        "column_stalled": account.column != "launch"
        and days_in_column is not None
        and days_in_column > STALLED_COLUMN_DAYS,
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

    contacts_by_account: dict[str, list[Contact]] = {}
    for c in session.exec(select(Contact)).all():
        contacts_by_account.setdefault(c.account_id, []).append(c)

    escalations_by_account: dict[str, list[Risk]] = {}
    for r in session.exec(
        select(Risk).where(Risk.status == "open", Risk.type == "escalation")
    ).all():
        escalations_by_account.setdefault(r.account_id, []).append(r)

    top_quartile = ctx.top_quartile_quote()

    for account in ctx.accounts:
        size_band = ctx.size_band_by_account.get(account.id, "mid")
        th = health_engine.thresholds(size_band, account.mode)
        band = health_engine.effective_band(account)
        delta = ctx.velocity_by_account.get(account.id)

        def emit(**kw):
            t = _emit(session, account, owner.id, **kw)
            if t is not None:
                created.append(
                    {"account": account.key, "rule_key": kw["rule_key"], "title": t.title}
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

        if band in ("at_risk", "critical") and account.quoted_total >= top_quartile:
            emit(
                rule_key="high_value_at_risk",
                title=f"Run risk playbook — {account.name}",
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
        margin = ctx.pnl_by_account.get(account.id, {}).get("margin_pct")
        if margin is not None and pnl_engine.compute(account)["gross_margin"] < 0:
            emit(
                rule_key="margin_negative",
                title=f"Margin underwater — {account.name}",
                provenance=f"Alert: gross margin negative at {margin}%",
                task_type="admin",
                bucket="today",
                priority="critical",
                due_in_days=1,
            )

        departed_champions = [
            c
            for c in contacts_by_account.get(account.id, [])
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
        ratio = usage_decline_ratio(session, account.id)
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

        for esc in escalations_by_account.get(account.id, []):
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

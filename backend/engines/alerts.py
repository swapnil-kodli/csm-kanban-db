"""Alert engine — rules evaluate to owned tasks, or to board state.

The governing rule (spec 01 §7): an alert is only allowed to exist if it becomes
a task someone owns. Anything that fails that test changes board state instead.
There is no bell icon and no unread count anywhere in this product.

Idempotent by construction: never a second *open* task for the same
(account_id, rule_key) pair. Thresholds are relative to the account via
`SEGMENT_THRESHOLDS` — a 15% usage drop on a single-product SMB is not the same
event as on a multi-product enterprise.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from models import Account, Contact, Milestone, Risk, Subscription, Task, UsageMetric, User
from engines import health as health_engine
from engines.attention import BookContext

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
    dtr = ctx.days_to_renewal(account.id)
    days_since_contact = (
        (datetime.utcnow() - account.last_contact_at).days
        if account.last_contact_at
        else None
    )
    th = health_engine.thresholds(account.segment)

    stalled_handoff = False
    if account.lifecycle_stage == "ready_for_onboarding" and account.handoff_received_at:
        stalled_handoff = (datetime.utcnow() - account.handoff_received_at).days > 3

    return {
        "renewal_90": dtr is not None and 0 <= dtr <= 90,
        "no_contact": days_since_contact is not None
        and days_since_contact > th["no_contact_days"],
        "stalled_handoff": stalled_handoff,
        "days_since_contact": days_since_contact,
        "days_to_renewal": dtr,
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

    milestones_by_account: dict[str, list[Milestone]] = {}
    for m in session.exec(select(Milestone)).all():
        milestones_by_account.setdefault(m.account_id, []).append(m)

    escalations_by_account: dict[str, list[Risk]] = {}
    for r in session.exec(
        select(Risk).where(Risk.status == "open", Risk.type == "escalation")
    ).all():
        escalations_by_account.setdefault(r.account_id, []).append(r)

    top_quartile = ctx.top_quartile_arr()
    today = date.today()

    for account in ctx.accounts:
        if account.lifecycle_stage == "closed":
            continue  # a churned or renewed account is not work in flight

        th = health_engine.thresholds(account.segment)
        band = health_engine.effective_band(account)
        delta = ctx.velocity_by_account.get(account.id)
        dtr = ctx.days_to_renewal(account.id)

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

        if band in ("at_risk", "critical") and account.arr >= top_quartile:
            emit(
                rule_key="high_value_at_risk",
                title=f"Run risk playbook — {account.name}",
                provenance=(
                    f"Alert: top-quartile account moved to "
                    f"{health_engine.BAND_LABELS[band]}"
                ),
                task_type="risk",
                bucket="today",
                priority="critical",
                due_in_days=0,
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
        # Consolidate related signals (research §15): a usage slide on an
        # account that already carries an open alert task is the same story
        # told twice. Adding a second to-do is how alert fatigue starts.
        already_alerted = session.exec(
            select(Task).where(
                Task.account_id == account.id,
                Task.rule_key != None,  # noqa: E711
                Task.status == "open",
            )
        ).first()

        ratio = usage_decline_ratio(session, account.id)
        if (
            ratio is not None
            and ratio <= th["usage_decline_ratio"]
            and not already_alerted
        ):
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

        for ms in milestones_by_account.get(account.id, []):
            if ms.status == "pending" and ms.target_date and ms.target_date < today:
                emit(
                    rule_key="milestone_overdue",
                    title=f"Unblock milestone — {ms.label}",
                    provenance=f"Alert: onboarding milestone overdue ({ms.label})",
                    task_type="onboarding",
                    bucket="this_week",
                    priority="high",
                    due_in_days=2,
                )
                break

        if dtr is not None and dtr >= 0:
            for threshold_days in sorted(th["renewal_task_days"]):
                if dtr <= threshold_days:
                    emit(
                        rule_key=f"renewal_{threshold_days}",
                        title=f"Prep renewal — {account.name}",
                        provenance=f"Alert: renewal in {threshold_days} days",
                        task_type="renewal",
                        bucket="this_week",
                        priority="high" if threshold_days <= 30 else "normal",
                        due_in_days=min(5, max(1, dtr - 5)),
                    )
                    break

    session.commit()
    return {"created": len(created), "rules": created}

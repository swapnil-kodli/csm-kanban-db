"""SQLModel tables for Signal CS.

Every table carries `id` (uuid str), `created_at`, `updated_at` per the data model.
Enums are stored as plain strings so SQLite stays inspectable with sqlite3.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Stamped(SQLModel):
    id: str = Field(default_factory=_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# --- enums as literal string sets (validated in schemas, stored as str) -------
SEGMENTS = ("enterprise", "mid_market", "smb")
LIFECYCLE_STAGES = (
    "ready_for_onboarding",
    "onboarding",
    "adopting",
    "healthy",
    "renewal",
    "closed",
)
CLOSED_REASONS = ("renewed", "churned")
HEALTH_BANDS = ("healthy", "watch", "at_risk", "critical")
TASK_TYPES = (
    "onboarding",
    "risk",
    "renewal",
    "expansion",
    "checkin",
    "escalation",
    "admin",
)
TASK_BUCKETS = ("today", "this_week", "follow_up", "waiting", "done")
TASK_PRIORITIES = ("critical", "high", "normal")
ACTIVITY_TYPES = ("email", "call", "meeting", "note", "qbr", "update")
CONTACT_ACTIVITY_TYPES = ("email", "call", "meeting", "qbr")
RISK_TYPES = ("escalation", "payment", "champion_loss", "adoption", "other")
RISK_SEVERITIES = ("high", "medium", "low")


class User(Stamped, table=True):
    name: str
    initials: str
    avatar_color: str = "#111111"


class Account(Stamped, table=True):
    key: str = Field(index=True, unique=True)          # Jira-style, e.g. SBP-01
    name: str = Field(index=True)
    segment: str
    city: Optional[str] = None
    lifecycle_stage: str = Field(default="adopting", index=True)
    closed_reason: Optional[str] = None
    arr: int = 0                                        # whole rupees, server-computed
    owner_id: str = Field(foreign_key="user.id", index=True)

    # health engine outputs (cached)
    health_score: int = 70
    health_band: str = "watch"
    health_manual_override: Optional[str] = None
    health_override_reason: Optional[str] = None
    health_override_at: Optional[datetime] = None

    # health engine inputs
    entitled_seats: int = 20                            # denominator for usage_score
    last_nps: Optional[int] = None                      # maps to sentiment_score

    expansion_flag: bool = False
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    handoff_received_at: Optional[datetime] = None
    last_contact_at: Optional[datetime] = None          # derived from activities
    attention_score: float = 0.0                        # cached, for card ordering
    pinned: bool = False                                # human judgement outranks the formula

    industry: Optional[str] = None                      # stub, no UI
    region: Optional[str] = None                        # stub, no UI


class Contact(Stamped, table=True):
    account_id: str = Field(foreign_key="account.id", index=True)
    name: str
    role: str
    email: Optional[str] = None
    phone: Optional[str] = None
    is_champion: bool = False
    is_economic_buyer: bool = False
    status: str = "active"                              # active | departed
    sentiment: Optional[int] = None                     # stub, no UI


class Subscription(Stamped, table=True):
    account_id: str = Field(foreign_key="account.id", index=True)
    start_date: Optional[date] = None
    renewal_date: date
    auto_renew: bool = True
    status: str = "active"
    line_items: list = Field(default_factory=list, sa_column=Column(JSON))


class Task(Stamped, table=True):
    account_id: str = Field(foreign_key="account.id", index=True)
    title: str
    type: str = "admin"
    bucket: str = Field(default="today", index=True)
    due_date: date
    status: str = Field(default="open", index=True)
    priority: str = "normal"
    owner_id: str = Field(foreign_key="user.id", index=True)
    provenance: Optional[str] = None
    rule_key: Optional[str] = Field(default=None, index=True)  # alert-engine idempotency
    completed_at: Optional[datetime] = None
    sort_index: float = 0.0


class Activity(Stamped, table=True):
    account_id: str = Field(foreign_key="account.id", index=True)
    contact_id: Optional[str] = Field(default=None, foreign_key="contact.id")
    type: str
    occurred_at: datetime = Field(index=True)
    summary: str
    body: Optional[str] = None
    created_task_id: Optional[str] = Field(default=None, foreign_key="task.id")


class HealthSnapshot(Stamped, table=True):
    account_id: str = Field(foreign_key="account.id", index=True)
    captured_on: date = Field(index=True)
    score: int
    usage: int
    engagement: int
    support: int
    sentiment: int


class Risk(Stamped, table=True):
    account_id: str = Field(foreign_key="account.id", index=True)
    type: str
    severity: str = "medium"
    status: str = Field(default="open", index=True)
    note: Optional[str] = None
    opened_at: datetime = Field(default_factory=_now)


class UsageMetric(Stamped, table=True):
    account_id: str = Field(foreign_key="account.id", index=True)
    captured_on: date = Field(index=True)
    active_users: int = 0
    sessions: int = 0
    feature_adoption_pct: int = 0


class SavedView(Stamped, table=True):
    name: str
    filter_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    pinned: bool = False
    is_default: bool = False
    sort_index: float = 0.0


class Milestone(Stamped, table=True):
    account_id: str = Field(foreign_key="account.id", index=True)
    label: str
    status: str = "pending"                             # pending | done
    target_date: Optional[date] = None
    sort_index: float = 0.0

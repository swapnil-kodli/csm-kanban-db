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
# Two independent axes, deliberately not collapsed into one field:
#   column     = where the engagement sits in the delivery pipeline (drag-drop)
#   workstream = what the team is actively doing on it right now (drawer only)
COLUMNS = ("ready_for_onboarding", "onboarding", "working", "approval", "launch")
WORKSTREAMS = ("bot_making", "data_procurement", "voice_ai_calling")
MODES = ("pilot", "customer")
CLIENT_TYPES = ("voice_ai_only", "data_plus_voice_ai")
COMM_MODES = ("whatsapp", "email")
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

    # --- the two axes ------------------------------------------------------
    column: str = Field(default="ready_for_onboarding", index=True)
    workstream: str = Field(default="bot_making", index=True)
    column_changed_at: Optional[datetime] = None        # drives `column_stalled`

    # --- commercial shape --------------------------------------------------
    mode: str = Field(default="pilot", index=True)      # pilot | customer
    client_type: str = Field(default="voice_ai_only")   # voice_ai_only | data_plus_voice_ai

    city: Optional[str] = None
    owner_id: str = Field(foreign_key="user.id", index=True)

    # --- health engine outputs (cached) ------------------------------------
    health_score: int = 70
    health_band: str = "watch"
    health_manual_override: Optional[str] = None
    health_override_reason: Optional[str] = None
    health_override_at: Optional[datetime] = None
    health_note: Optional[str] = None                   # free text, set during a check

    # --- health engine inputs ----------------------------------------------
    entitled_seats: int = 20
    last_nps: Optional[int] = None

    # --- primary POC (the drawer leads with this; `contact` holds the rest) -
    poc_name: Optional[str] = None
    poc_email: Optional[str] = None
    poc_phone: Optional[str] = None
    comm_modes: list = Field(default_factory=list, sa_column=Column(JSON))

    # --- costing: what was quoted -----------------------------------------
    quoted_total: int = 0
    quoted_line_items: list = Field(default_factory=list, sa_column=Column(JSON))
    quoted_at: Optional[date] = None
    quote_notes: Optional[str] = None

    # --- pnl: the reality against that quote -------------------------------
    # total_cost / gross_margin / margin_pct are computed server-side on read,
    # never stored, so they cannot drift from cost_items.
    revenue_recognised: int = 0
    cost_items: list = Field(default_factory=list, sa_column=Column(JSON))

    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    handoff_received_at: Optional[datetime] = None
    last_contact_at: Optional[datetime] = None
    attention_score: float = 0.0
    pinned: bool = False


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


class GoogleCredential(Stamped, table=True):
    """Single-row Gmail OAuth credential store (single-user MVP)."""

    email: Optional[str] = None
    refresh_token: str
    access_token: Optional[str] = None
    access_token_expires_at: Optional[datetime] = None
    scope: str = "https://www.googleapis.com/auth/gmail.readonly"

"""Request/response models. Responses are plain dicts built in serializers.py;
these classes cover the write side plus the few typed reads worth pinning down.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Workstream = Literal["bot_making", "data_procurement", "voice_ai_calling"]
Mode = Literal["pilot", "customer"]
ClientType = Literal["voice_ai_only", "data_plus_voice_ai"]
CommMode = Literal["whatsapp", "email"]
HealthBand = Literal["healthy", "watch", "at_risk", "critical"]
TaskBucket = Literal["today", "this_week", "follow_up", "waiting", "done"]
TaskStatus = Literal["open", "done"]
TaskType = Literal[
    "onboarding", "risk", "renewal", "expansion", "checkin", "escalation", "admin"
]
TaskPriority = Literal["critical", "high", "normal"]
ActivityType = Literal["email", "call", "meeting", "note", "qbr", "update"]
GroupBy = Literal["none", "priority", "mode", "client_type", "workstream"]


class HealthResponse(BaseModel):
    status: str
    version: str


class LineItem(BaseModel):
    offering: str
    qty: int = Field(ge=0)
    rate: int = Field(ge=0)


class CostItem(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    amount: int = Field(ge=0)


class AccountPatch(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    column_id: Optional[str] = None
    workstream: Optional[Workstream] = None
    mode: Optional[Mode] = None
    client_type: Optional[ClientType] = None
    tags: Optional[list[str]] = None
    pinned: Optional[bool] = None
    last_nps: Optional[int] = None
    health_note: Optional[str] = None

    # POC
    poc_name: Optional[str] = None
    poc_email: Optional[str] = None
    poc_phone: Optional[str] = None
    comm_modes: Optional[list[CommMode]] = None

    # costing — quoted_total is derived from the line items, never accepted raw
    quoted_line_items: Optional[list[LineItem]] = None
    quoted_at: Optional[date] = None
    quote_notes: Optional[str] = None

    # pnl
    revenue_recognised: Optional[int] = Field(default=None, ge=0)
    cost_items: Optional[list[CostItem]] = None


class HealthOverrideIn(BaseModel):
    band: HealthBand
    reason: str = Field(min_length=3, max_length=280)


class TaskCreate(BaseModel):
    account_id: str
    title: str = Field(min_length=1, max_length=200)
    type: TaskType = "admin"
    bucket: TaskBucket = "today"
    due_date: Optional[date] = None
    priority: TaskPriority = "normal"
    provenance: Optional[str] = None


class TaskPatch(BaseModel):
    title: Optional[str] = None
    type: Optional[TaskType] = None
    bucket: Optional[TaskBucket] = None
    due_date: Optional[date] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    sort_index: Optional[float] = None


class InlineTaskCreate(BaseModel):
    """The 'also create next action' toggle on the activity composer."""

    title: str = Field(min_length=1, max_length=200)
    due_date: Optional[date] = None
    bucket: TaskBucket = "this_week"
    type: TaskType = "checkin"
    priority: TaskPriority = "normal"


class ActivityCreate(BaseModel):
    type: ActivityType
    summary: str = Field(min_length=1, max_length=280)
    body: Optional[str] = None
    occurred_at: Optional[datetime] = None
    contact_id: Optional[str] = None
    create_task: Optional[InlineTaskCreate] = None


class ContactCreate(BaseModel):
    account_id: str
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    email: Optional[str] = None
    phone: Optional[str] = None
    is_champion: bool = False
    is_economic_buyer: bool = False


class ContactPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_champion: Optional[bool] = None
    is_economic_buyer: Optional[bool] = None
    status: Optional[Literal["active", "departed"]] = None


class ColumnCreate(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    color: Optional[str] = None
    position: Optional[float] = None
    description: Optional[str] = None
    stalled_after_days: Optional[int] = Field(default=None, ge=1, le=365)


class ColumnPatch(BaseModel):
    """`key` is absent on purpose — it is immutable, so saved views and filters
    survive a rename."""

    label: Optional[str] = Field(default=None, min_length=1, max_length=60)
    color: Optional[str] = None
    position: Optional[float] = None
    description: Optional[str] = None
    stalled_after_days: Optional[int] = Field(default=None, ge=1, le=365)
    clear_stalled_after_days: bool = False
    is_default_entry: Optional[bool] = None
    is_archived: Optional[bool] = None


class ColumnReorder(BaseModel):
    ordered_ids: list[str]


class ColumnDelete(BaseModel):
    reassign_to: Optional[str] = None

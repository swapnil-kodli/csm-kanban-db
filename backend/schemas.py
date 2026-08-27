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


Outcome = Literal["active", "completed", "lost"]


class CompanyCreate(BaseModel):
    """The client organisation. Two required fields, because two is all the
    company itself needs — everything about the WORK belongs to a Deal."""

    name: str = Field(min_length=1, max_length=120)
    client_type: ClientType

    city: Optional[str] = Field(default=None, max_length=120)
    tags: Optional[list[str]] = None

    # The first contact, created alongside the company. Not required, but a
    # company with no contact cannot have a deal — deal.poc_id is mandatory —
    # so the New Deal flow will ask for one the moment it is needed.
    primary_contact_name: Optional[str] = Field(default=None, max_length=120)
    primary_contact_role: Optional[str] = Field(default=None, max_length=120)
    primary_contact_email: Optional[str] = None
    primary_contact_phone: Optional[str] = None


class CompanyPatch(BaseModel):
    """`key` is absent on purpose — immutable, so filters and shared URLs
    survive a rename."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    client_type: Optional[ClientType] = None
    city: Optional[str] = Field(default=None, max_length=120)
    tags: Optional[list[str]] = None


class DealCreate(BaseModel):
    """An engagement. `company_id` and `poc_id` are both mandatory.

    `poc_id` must name a contact belonging to `company_id`; that is checked in
    the router, not just the picker. A cross-company POC would put one client's
    contact — and their correspondence — on another client's drawer.

    `key` and `column_id` are absent: the key is derived per company, and new
    work lands in the default entry column, which the drawer shows read-only.
    """

    company_id: str
    poc_id: str
    name: str = Field(min_length=1, max_length=120)
    mode: Mode
    workstream: Workstream

    comm_modes: Optional[list[CommMode]] = None
    last_contact_at: Optional[datetime] = None
    quoted_total: Optional[int] = Field(default=None, ge=0)
    quoted_at: Optional[date] = None
    quote_notes: Optional[str] = None


class DealPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    column_id: Optional[str] = None
    workstream: Optional[Workstream] = None
    mode: Optional[Mode] = None
    poc_id: Optional[str] = None
    pinned: Optional[bool] = None
    last_nps: Optional[int] = None
    health_note: Optional[str] = None

    # POC
    last_contact_at: Optional[datetime] = None
    comm_modes: Optional[list[CommMode]] = None

    # Costing is fully manual. quoted_total is an independent field: the UI
    # shows a soft hint when it disagrees with the line items rather than
    # overwriting what someone typed.
    quoted_total: Optional[int] = Field(default=None, ge=0)
    quoted_line_items: Optional[list[LineItem]] = None
    quoted_at: Optional[date] = None
    quote_notes: Optional[str] = None

    # pnl
    revenue_recognised: Optional[int] = Field(default=None, ge=0)
    cost_items: Optional[list[CostItem]] = None


class DealOutcomeIn(BaseModel):
    """Marking a deal done or dead.

    A reason is required for `lost` and optional otherwise: "why did we lose
    this" is the whole value of recording the loss, while "why did we finish"
    is usually just "we finished".
    """

    outcome: Outcome
    reason: Optional[str] = Field(default=None, max_length=280)


class HardDeleteIn(BaseModel):
    """Typed confirmation for the irreversible path.

    A company owns contacts and deals, and each deal owns tasks, health
    snapshots, costing and PNL history. With the demo seed off there is nothing
    to restore from, so the key must be typed back exactly and the destructive
    action cannot be reached by clicking through.
    """

    confirm_key: str = Field(min_length=1, max_length=40)


class HealthOverrideIn(BaseModel):
    band: HealthBand
    reason: str = Field(min_length=3, max_length=280)


class TaskCreate(BaseModel):
    # A task belongs to a DEAL, not a client: "chase the contract" is about one
    # engagement, and a client with three deals would otherwise collect tasks
    # with no way to tell which work they belong to.
    #
    # This field was the last `account_id` left in the backend after the split.
    # routers/tasks.py was renamed, the frontend was renamed, and this one line
    # was not — so every manual task creation 422'd on a missing `account_id`
    # while sending a perfectly good `deal_id`. Found by driving the New Task
    # dialog rather than by reading, because the router and the model agreed
    # with each other; only the wire contract disagreed.
    deal_id: str
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
    company_id: str
    is_primary: bool = False
    name: str = Field(min_length=1, max_length=120)
    # Blank on purpose: a contact is added as an empty row and filled in inline,
    # so requiring a role here would reject the row that creates it.
    role: str = Field(default="", max_length=120)
    email: Optional[str] = None
    phone: Optional[str] = None
    is_champion: bool = False
    is_economic_buyer: bool = False


class ContactPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = None
    phone: Optional[str] = None
    is_champion: Optional[bool] = None
    is_economic_buyer: Optional[bool] = None
    is_primary: Optional[bool] = None
    status: Optional[Literal["active", "departed"]] = None


class ColumnCreate(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    color: Optional[str] = None
    position: Optional[float] = None
    description: Optional[str] = None
    stalled_after_days: Optional[int] = Field(default=None, ge=1, le=365)


class ColumnPatch(BaseModel):
    """`key` is absent on purpose — it is immutable, so filters and shared URLs
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

"""Request/response models. Responses are plain dicts built in serializers.py;
these classes cover the write side plus the few typed reads worth pinning down.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Segment = Literal["enterprise", "mid_market", "smb"]
LifecycleStage = Literal[
    "ready_for_onboarding", "onboarding", "adopting", "healthy", "renewal", "closed"
]
HealthBand = Literal["healthy", "watch", "at_risk", "critical"]
TaskBucket = Literal["today", "this_week", "follow_up", "waiting", "done"]
TaskStatus = Literal["open", "done"]
TaskType = Literal[
    "onboarding", "risk", "renewal", "expansion", "checkin", "escalation", "admin"
]
TaskPriority = Literal["critical", "high", "normal"]
ActivityType = Literal["email", "call", "meeting", "note", "qbr", "update"]
BoardView = Literal["work", "health", "lifecycle"]
GroupBy = Literal["none", "priority", "segment", "renewal_month"]


class HealthResponse(BaseModel):
    status: str
    version: str


class AccountPatch(BaseModel):
    name: Optional[str] = None
    segment: Optional[Segment] = None
    city: Optional[str] = None
    lifecycle_stage: Optional[LifecycleStage] = None
    closed_reason: Optional[Literal["renewed", "churned"]] = None
    expansion_flag: Optional[bool] = None
    tags: Optional[list[str]] = None
    pinned: Optional[bool] = None
    last_nps: Optional[int] = None


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


class SavedViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    filter_json: dict[str, Any] = Field(default_factory=dict)
    pinned: bool = False


class MilestonePatch(BaseModel):
    status: Optional[Literal["pending", "done"]] = None
    target_date: Optional[date] = None

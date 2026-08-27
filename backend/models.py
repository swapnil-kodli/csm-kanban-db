"""SQLModel tables for Signal CS.

Every table carries `id` (uuid str), `created_at`, `updated_at` per the data model.
Enums are stored as plain strings so SQLite stays inspectable with sqlite3.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlmodel import Field, SQLModel

from dbtypes import JSONColumn, TZDateTime, utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    # Timezone-aware everywhere; see dbtypes.utcnow().
    return utcnow()


# NOTE: these use sa_type, never sa_column. A Column() object may belong to
# only one Table, so a shared instance on this base class is claimed by the
# first table that inherits it and raises ArgumentError on the second.
class Stamped(SQLModel):
    id: str = Field(default_factory=_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=_now, sa_type=TZDateTime)
    updated_at: datetime = Field(default_factory=_now, sa_type=TZDateTime)


# --- enums as literal string sets (validated in schemas, stored as str) -------
# Two independent axes, deliberately not collapsed into one field:
#   column     = where the engagement sits in the delivery pipeline (drag-drop)
#   workstream = what the team is actively doing on it right now (drawer only)
# Column keys are no longer an enum — they live in the board_column table and
# are user-defined. These are the seeded defaults, kept as constants only so the
# seed and the v3 migration agree on what "the v2 board" was.
DEFAULT_COLUMN_KEYS = (
    "ready_for_onboarding",
    "onboarding",
    "working",
    "approval",
    "launch",
)

# Recolouring is restricted to the token palette, not a free colour picker —
# the board's restraint is a feature, and one saturated channel is reserved for
# health.
COLUMN_PALETTE = (
    "#9d50dd",  # s-handoff
    "#2bb4d6",  # s-onboarding
    "#6b6b6b",  # s-adopting
    "#f5b400",  # s-renewal
    "#00c875",  # s-healthy
    "#df2f4a",  # s-churned
)
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
    # `user` is a reserved word in Postgres. SQLAlchemy quotes it so it works,
    # but anyone writing raw SQL later would trip over it.
    __tablename__ = "app_user"

    # Google's subject claim is the identity key, NOT the email. A person can
    # change their address inside a Workspace and `sub` stays the same; keying
    # on email would silently create a second account and orphan everything the
    # first one owns. Nullable only so the bootstrap CSM row can exist before
    # anyone has signed in.
    google_sub: Optional[str] = Field(default=None, unique=True, index=True)
    email: Optional[str] = Field(default=None, index=True)
    avatar_url: Optional[str] = None
    is_active: bool = True
    last_login_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)

    name: str
    initials: str
    avatar_color: str = "#111111"


class UserSession(Stamped, table=True):
    """Server-side session. The cookie carries only an opaque id.

    The Google tokens never go anywhere near the browser: the cookie is a
    random handle, everything else is looked up here. That is what makes the
    cookie safe to hand out as httpOnly+Secure+SameSite=Lax — stealing it gets
    you a session that can be revoked, not a refresh token that cannot.
    """

    user_id: str = Field(foreign_key="app_user.id", index=True)
    expires_at: datetime = Field(sa_type=TZDateTime, index=True)
    # Coarse, for a "signed in from" line. Never used for auth decisions.
    user_agent: Optional[str] = None


class Company(Stamped, table=True):
    """The client organisation. Owns the relationship, never sits on the board.

    Everything here describes WHO the client is. Everything describing what is
    being delivered for them lives on Deal, because one company can have several
    engagements running at once — and one of them going badly is not a fact
    about the company's address or its account owner.
    """

    key: str = Field(index=True, unique=True)          # PRE-04, immutable
    name: str = Field(index=True)
    client_type: str = Field(default="voice_ai_only")  # voice_ai_only | data_plus_voice_ai
    city: Optional[str] = None
    owner_id: str = Field(foreign_key="app_user.id", index=True)
    tags: list = Field(default_factory=list, sa_type=JSONColumn)

    # Soft delete. A company owns contacts and deals, and each deal owns tasks,
    # snapshots, costing and PNL history — with no seed to restore from a hard
    # delete is unrecoverable, so it happens only from Trash, on purpose.
    archived_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)


# A deal is either being worked, finished, or dead. `outcome` is business truth
# and feeds the won/lost history on the company view; it is deliberately NOT the
# same axis as `column_id`, because a deal can be lost from any column.
DEAL_OUTCOMES = ("active", "completed", "lost")


class Deal(Stamped, table=True):
    """One engagement. THIS is the board card.

    Two independent axes, same as before the split:
      column_id   where the engagement sits in the delivery pipeline (drag-drop)
      workstream  what the team is actively doing on it right now (drawer only)

    And now a third that is neither: `outcome`. Only `active` deals appear on
    the board. `completed` and `lost` drop off but stay queryable, which is what
    makes "how many won, how many lost" answerable per company.
    """

    key: str = Field(index=True, unique=True)          # PRE-04-01, per company
    company_id: str = Field(foreign_key="company.id", index=True)

    # Mandatory. The Gmail panel keys off this contact's email, and a deal
    # without a named counterpart is not an engagement anyone can work.
    # API-enforced invariant: this contact's company_id MUST equal company_id
    # above. A cross-company POC would leak one client's contact — and their
    # correspondence — onto another client's drawer.
    poc_id: str = Field(foreign_key="contact.id", index=True)

    # Its own name, not the company's. Seeded from the company name at
    # migration. Without it, two deals for one company render as identical
    # cards distinguishable only by decoding the key suffix.
    name: str = Field(index=True)

    # --- the two axes ------------------------------------------------------
    column_id: str = Field(foreign_key="boardcolumn.id")
    workstream: str = Field(default="bot_making", index=True)
    # drives `column_stalled`
    column_changed_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)

    mode: str = Field(default="pilot", index=True)      # pilot | customer

    # --- health engine outputs (cached) ------------------------------------
    # Health lives here, not on Company. A client with one engagement going well
    # and another failing has no single meaningful score — averaging them hides
    # exactly the deal you need to look at. The company view rolls these up by
    # taking the WORST active band, never a mean.
    health_score: int = 70
    health_band: str = "watch"
    health_manual_override: Optional[str] = None
    health_override_reason: Optional[str] = None
    health_override_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)
    health_note: Optional[str] = None

    # --- health engine inputs ----------------------------------------------
    entitled_seats: int = 20
    last_nps: Optional[int] = None
    comm_modes: list = Field(default_factory=list, sa_type=JSONColumn)

    # --- costing: what was quoted -----------------------------------------
    quoted_total: int = 0
    quoted_line_items: list = Field(default_factory=list, sa_type=JSONColumn)
    quoted_at: Optional[date] = None
    quote_notes: Optional[str] = None

    # --- pnl: the reality against that quote -------------------------------
    # total_cost / gross_margin / margin_pct are computed server-side on read,
    # never stored, so they cannot drift from cost_items.
    revenue_recognised: int = 0
    cost_items: list = Field(default_factory=list, sa_type=JSONColumn)

    handoff_received_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)
    last_contact_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)
    attention_score: float = 0.0
    pinned: bool = False

    # --- outcome -----------------------------------------------------------
    outcome: str = Field(default="active", index=True)
    outcome_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)
    outcome_reason: Optional[str] = None

    # Distinct from outcome="lost" on purpose. `lost` is a real result and
    # belongs in the won/lost counts; `archived_at` means the record should not
    # exist. Folding the second into the first would corrupt the exact number
    # this split was made to produce.
    archived_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)


class Contact(Stamped, table=True):
    """Belongs to a Company, and is reusable across all of that company's deals.

    Contacts are company-scoped rather than deal-scoped because the same person
    is the counterpart on every engagement you run with that client — making
    them re-enter the POC per deal would guarantee three spellings of one email.
    """

    company_id: str = Field(foreign_key="company.id", index=True)
    name: str
    role: str
    # Exactly one primary per company: the default POC offered when a new deal
    # is created. A deal's actual POC is deal.poc_id and can be anyone else on
    # this company.
    is_primary: bool = False
    email: Optional[str] = None
    phone: Optional[str] = None
    is_champion: bool = False
    is_economic_buyer: bool = False
    status: str = "active"                              # active | departed
    sentiment: Optional[int] = None                     # stub, no UI


class Task(Stamped, table=True):
    deal_id: str = Field(foreign_key="deal.id", index=True)
    title: str
    type: str = "admin"
    bucket: str = Field(default="today", index=True)
    due_date: date
    status: str = Field(default="open", index=True)
    priority: str = "normal"
    owner_id: str = Field(foreign_key="app_user.id", index=True)
    provenance: Optional[str] = None
    rule_key: Optional[str] = Field(default=None, index=True)  # alert-engine idempotency
    completed_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)
    sort_index: float = 0.0


class Activity(Stamped, table=True):
    deal_id: str = Field(foreign_key="deal.id", index=True)
    contact_id: Optional[str] = Field(default=None, foreign_key="contact.id")
    type: str
    occurred_at: datetime = Field(sa_type=TZDateTime, index=True)
    summary: str
    body: Optional[str] = None
    created_task_id: Optional[str] = Field(default=None, foreign_key="task.id")


class HealthSnapshot(Stamped, table=True):
    deal_id: str = Field(foreign_key="deal.id", index=True)
    captured_on: date = Field(index=True)
    score: int
    usage: int
    engagement: int
    support: int
    sentiment: int


class Risk(Stamped, table=True):
    deal_id: str = Field(foreign_key="deal.id", index=True)
    type: str
    severity: str = "medium"
    status: str = Field(default="open", index=True)
    note: Optional[str] = None
    opened_at: datetime = Field(default_factory=_now, sa_type=TZDateTime)


class UsageMetric(Stamped, table=True):
    deal_id: str = Field(foreign_key="deal.id", index=True)
    captured_on: date = Field(index=True)
    active_users: int = 0
    sessions: int = 0
    feature_adoption_pct: int = 0


class BoardColumn(Stamped, table=True):
    """A user-defined board column.

    `key` is a slug, immutable after create, so filters and shared URLs that
    reference it keep working across a rename.

    Two flags carry behaviour that v2 hardcoded to the literal
    "ready_for_onboarding" / "launch" column keys:

      is_default_entry    exactly one column has it. New accounts land here,
                          and it IS the handoff inbox — same idea, one flag.
      stalled_after_days  nullable. When set, cards sitting in this column
                          longer than N days get the stalled badge and the
                          dashed left border. NULL means no stall tracking at
                          all, which is how a terminal column opts out.
    """

    key: str = Field(unique=True)
    label: str
    color: str = "#6b6b6b"
    position: float = 0.0
    is_archived: bool = False
    is_default_entry: bool = False
    description: Optional[str] = None
    stalled_after_days: Optional[int] = None


class GoogleCredential(Stamped, table=True):
    """One Gmail grant, per user.

    Per-user and never pooled: the thread panel shows correspondence between the
    SIGNED-IN user and the deal's POC, and nothing else. A teammate's threads
    with the same POC never appear. That is the intended behaviour, not a gap to
    engineer around — pooling would mean one person's consent exposing their
    mailbox to everyone else on the team.

    `refresh_token` is stored ENCRYPTED (see crypto.py). It is the long-lived
    secret here: an access token expires in an hour, a refresh token does not.
    """

    user_id: str = Field(foreign_key="app_user.id", unique=True, index=True)
    email: Optional[str] = None
    refresh_token: str                      # ciphertext, never plaintext
    access_token: Optional[str] = None      # in-memory lifetime only, an hour
    access_token_expires_at: Optional[datetime] = Field(default=None, sa_type=TZDateTime)
    scope: str = "https://www.googleapis.com/auth/gmail.readonly"

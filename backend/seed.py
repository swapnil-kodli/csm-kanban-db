"""Idempotent seed. Runs only when the `account` table is empty.

Real-estate GTM flavour, continuous with the PropSignal pipeline. Rupee amounts
are stored as integers; the UI formats them in Indian short scale.

The health curves are calibrated rather than hand-written: each account declares
a target score curve, and the seed back-solves the daily active-user series that
makes the live health engine reproduce that curve. The engine stays pure — no
scores are written by hand, so `POST /api/jobs/recompute` is a no-op on a fresh
database rather than a rewrite of the story.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

from models import (
    Account,
    Activity,
    Contact,
    HealthSnapshot,
    Milestone,
    Risk,
    SavedView,
    Subscription,
    Task,
    UsageMetric,
    User,
)
from engines import health as health_engine
from engines.attention import refresh_cached_scores

TODAY = date.today()
NOW = datetime.utcnow()

RATES = {
    "QLs": 500,
    "VLs": 500,
    "SLs": 500,
    "Raw Data profiles": 100,
    "Voice AI minutes": 100,
}
SEATS_BY_SEGMENT = {"enterprise": 500, "mid_market": 250, "smb": 120}

USAGE_HISTORY_DAYS = 105       # 90 days of curve + 14 days of warm-up
SNAPSHOT_DAYS = 90


def _dt(days_ago: float, hour: int = 10) -> datetime:
    return datetime.combine(TODAY - timedelta(days=int(days_ago)), time(hour, 0))


# --- accounts ----------------------------------------------------------------
# key, name, segment, city, stage, closed_reason, renewal offset, expansion,
# handoff days ago, health curve control points [(days_ago, score)]
ACCOUNTS = [
    dict(
        key="SBP-01", name="SBP Group", segment="enterprise", city="Chandigarh",
        stage="ready_for_onboarding", renewal=365, handoff_days_ago=5,
        curve=[(90, 78), (0, 78)],
        line_items=[("QLs", 1600), ("Raw Data profiles", 4000)],
    ),
    dict(
        key="BRM-02", name="Brick Mentor", segment="mid_market", city="Bengaluru",
        stage="ready_for_onboarding", renewal=365, handoff_days_ago=1,
        curve=[(90, 75), (0, 75)],
        line_items=[("VLs", 1200), ("Voice AI minutes", 3000)],
    ),
    dict(
        key="SQY-03", name="Square Yards", segment="enterprise", city="Gurugram",
        stage="onboarding", renewal=330,
        curve=[(90, 74), (30, 74), (0, 68)],
        line_items=[("QLs", 3000), ("VLs", 2000)],
    ),
    dict(
        key="PRE-04", name="Prestige Group", segment="enterprise", city="Bengaluru",
        stage="renewal", renewal=18,
        curve=[(90, 76), (30, 76), (0, 62)],
        line_items=[("QLs", 2400), ("Voice AI minutes", 12000)],
    ),
    dict(
        key="NFS-05", name="Next Foot Steps", segment="mid_market", city="Pune",
        stage="adopting", renewal=210, expansion=True,
        curve=[(90, 77), (30, 77), (0, 81)],
        line_items=[("SLs", 1000), ("Raw Data profiles", 3000)],
    ),
    dict(
        key="HOU-06", name="Houzay", segment="mid_market", city="Srinagar",
        stage="adopting", renewal=150,
        curve=[(90, 67), (30, 67), (0, 58)],
        line_items=[("Voice AI minutes", 7000)],
    ),
    dict(
        key="SET-07", name="Settlin", segment="smb", city="Bengaluru",
        stage="healthy", renewal=240,
        curve=[(90, 87), (30, 86), (0, 88)],
        line_items=[("VLs", 1000)],
    ),
    dict(
        key="DIG-08", name="Diggaj Realty", segment="smb", city="Ahmedabad",
        stage="adopting", renewal=190,
        curve=[(90, 55), (30, 55), (0, 44)],
        line_items=[("QLs", 900), ("Raw Data profiles", 1000)],
    ),
    dict(
        key="KRH-09", name="Krishna Homes", segment="smb", city="Bhopal",
        stage="healthy", renewal=280,
        curve=[(90, 79), (0, 79)],
        line_items=[("SLs", 700)],
    ),
    dict(
        key="VPS-10", name="Valuepersqft", segment="smb", city="Bengaluru",
        stage="renewal", renewal=52,
        curve=[(90, 49), (30, 49), (0, 31)],
        line_items=[("VLs", 600), ("Voice AI minutes", 1500)], last_nps=-60,
        override=("critical", "champion left, budget frozen"),
    ),
    dict(
        key="PRO-11", name="Prospen Estates", segment="mid_market", city="Hyderabad",
        stage="onboarding", renewal=350,
        curve=[(90, 68), (30, 68), (0, 71)],
        line_items=[("QLs", 800), ("Raw Data profiles", 2000)],
    ),
    dict(
        key="FBP-12", name="Full Basket Property", segment="smb", city="Mumbai",
        stage="closed", closed_reason="churned", renewal=-20,
        curve=[(90, 43), (30, 43), (0, 22)],
        line_items=[("SLs", 400), ("Voice AI minutes", 1000)], last_nps=-100,
    ),
]

CONTACTS = [
    ("SBP-01", "Akash", "Head of Growth", True, False, "active"),
    ("SBP-01", "Ritu Bansal", "Ops Manager", False, False, "active"),
    ("BRM-02", "Ankit", "Founder", True, True, "active"),
    ("SQY-03", "Abhay", "VP Marketing", True, False, "active"),
    ("SQY-03", "Neha Gupta", "Program Manager", False, False, "active"),
    ("PRE-04", "Akash Rao", "Marketing Lead", True, False, "active"),
    ("PRE-04", "Priya M", "CFO", False, True, "active"),
    ("NFS-05", "Pratik", "Director", True, False, "active"),
    ("HOU-06", "Sunil Handoo", "Ops Head", True, False, "active"),
    ("SET-07", "Ashish", "Co-founder", True, True, "active"),
    ("DIG-08", "Dhaval", "Sales Head", True, False, "active"),
    ("KRH-09", "Ashish Sharma", "Owner", True, False, "active"),
    ("VPS-10", "Sanjay", "Growth Lead", True, False, "departed"),
    ("VPS-10", "Rahul K", "Interim Ops", False, False, "active"),
    ("PRO-11", "Indra", "Founder", True, True, "active"),
    ("FBP-12", "Manish", "Head of Sales", True, False, "active"),
]

RISKS = [
    ("DIG-08", "escalation", "high", "Lead delivery quality complaints, 3 weeks unresolved", 21),
    ("PRE-04", "adoption", "medium", "Voice AI minutes underused vs contract", 34),
    ("VPS-10", "champion_loss", "high", "Sanjay departed, no replacement identified", 26),
    ("FBP-12", "payment", "high", "Non-payment at cancellation, contract terminated", 26),
    ("FBP-12", "other", "high", "Budget pulled for the category", 40),
]

MILESTONE_LABELS = [
    "Kickoff scheduled",
    "Data handoff complete",
    "Integration live",
    "First value delivered",
    "Onboarding complete",
]
# account key -> (done_count, overdue_index or None)
MILESTONE_PLAN = {
    "SQY-03": (2, 2),
    "PRO-11": (2, None),
    "SBP-01": (0, None),
    "BRM-02": (0, None),
}

# account key -> [(days_ago, type, summary, body)]
ACTIVITIES = {
    "SBP-01": [
        (3, "email", "Sent kickoff scheduling options for next week", None),
        (5, "meeting", "Sales-to-CS handoff review with Akash", "Sold on QLs volume plus Raw Data profiles for the Tricity micro-markets. Wants first leads inside 30 days."),
        (12, "note", "Closed Won in PropSignal — handoff pending", None),
    ],
    "BRM-02": [
        (1, "call", "Welcome call with Ankit, kickoff booked for Thursday", None),
        (2, "email", "Shared onboarding checklist and data requirements", None),
        (9, "note", "Closed Won — Bengaluru builder, VLs plus Voice AI", None),
    ],
    "SQY-03": [
        (2, "email", "Chased Gurugram team for API keys", None),
        (7, "meeting", "Integration working session with Neha", "Sandbox connected; production keys still blocked on their security review."),
        (16, "qbr", "Q2 business review with Abhay", "Reviewed lead quality across NCR. Agreed on 3,000 QLs run-rate and a VLs pilot in Noida."),
        (28, "call", "Weekly sync — integration timeline slipping", None),
        (44, "email", "Shared implementation plan and milestone dates", None),
        (61, "meeting", "Kickoff call", None),
    ],
    "PRE-04": [
        (6, "call", "Checked in with Akash Rao on Voice AI adoption", "Team has not staffed the calling desk. Minutes burn is roughly a third of contract."),
        (13, "email", "Sent September usage summary", None),
        (21, "meeting", "Renewal planning with Priya M", "CFO wants a cost-per-qualified-lead comparison before signing."),
        (33, "qbr", "Q2 business review", "Strong QLs performance in Bengaluru. Voice AI underused — flagged as the renewal risk."),
        (47, "call", "Escalation debrief on lead routing", None),
        (68, "email", "Shared Voice AI enablement guide", None),
    ],
    "NFS-05": [
        (4, "call", "Pratik asked about VLs add-on pricing", None),
        (11, "email", "Shared VLs sample output for Pune", None),
        (24, "meeting", "Adoption review — SLs performing well", None),
        (52, "email", "Monthly usage recap", None),
    ],
    "HOU-06": [
        (19, "email", "Sent Voice AI usage nudge — no reply", None),
        (31, "call", "Sunil flagged bandwidth issues on their side", None),
        (48, "meeting", "Adoption check-in", None),
        (70, "email", "Onboarding wrap-up note", None),
    ],
    "SET-07": [
        (3, "email", "Shared new feature note, Ashish acknowledged", None),
        (14, "call", "Quarterly check-in — steady VLs usage", None),
        (38, "meeting", "Business review with Ashish", None),
        (63, "email", "Renewal terms confirmed", None),
    ],
    "DIG-08": [
        (7, "call", "Dhaval escalated lead quality again", "Third week without a resolution. Asked for a product fix ETA by Friday."),
        (15, "email", "Shared interim filtering workaround", None),
        (21, "note", "Escalation opened with support", None),
        (40, "meeting", "Adoption review — QLs conversion below benchmark", None),
    ],
    "KRH-09": [
        (5, "email", "Shared Bhopal market benchmark", None),
        (18, "call", "Routine check-in, no issues", None),
        (46, "meeting", "Half-yearly review", None),
    ],
    "VPS-10": [
        (26, "email", "Sanjay out-of-office auto-reply — has left the company", None),
        (27, "note", "LinkedIn shows Sanjay moved on. No handover named.", None),
        (39, "call", "Sanjay raised budget freeze for next quarter", None),
        (58, "meeting", "Adoption review with Sanjay", None),
        (80, "email", "Renewal runway note", None),
    ],
    "PRO-11": [
        (8, "email", "Chased data handoff files from Indra's team", None),
        (17, "meeting", "Integration kickoff with Hyderabad team", None),
        (35, "call", "Onboarding planning", None),
        (55, "email", "Welcome pack sent", None),
    ],
    "FBP-12": [
        (30, "note", "Cancellation confirmed, access ends this month", None),
        (44, "call", "Churn conversation — budget pulled", None),
        (72, "meeting", "Last adoption review", None),
    ],
}

# bucket, account key, title, type, priority, due offset days,
# provenance, rule_key, completed days ago
TASKS = [
    ("today", "PRE-04", "Call Akash re: usage drop", "risk", "critical", 0,
     "Alert: health dropped 14 pts in 30d", "health_drop", None),
    ("today", "VPS-10", "Map new champion after Sanjay exit", "risk", "critical", 0,
     "Alert: champion contact departed", "champion_departed", None),
    ("today", "SBP-01", "Run kickoff call", "onboarding", "high", -2, None, None, None),
    ("today", "DIG-08", "Escalation follow-up with support", "escalation", "high", 0,
     "Alert: escalation opened — Lead delivery quality complaints, 3 weeks unresolved",
     "escalation_open", None),

    ("this_week", "PRE-04", "Prep renewal deck", "renewal", "high", 3,
     "Alert: renewal in 30 days", "renewal_30", None),
    ("this_week", "SQY-03", "Chase integration milestone", "onboarding", "high", -3,
     "Alert: onboarding milestone overdue (Integration live)", "milestone_overdue", None),
    ("this_week", "HOU-06", "Re-engage — no contact 19d", "checkin", "normal", 2, None, None, None),
    ("this_week", "NFS-05", "Scope expansion — VLs add-on", "expansion", "normal", 4, None, None, None),
    ("this_week", "BRM-02", "Send onboarding welcome pack", "onboarding", "normal", 1, None, None, None),

    ("follow_up", "SET-07", "Quarterly check-in", "checkin", "normal", 12, None, None, None),
    ("follow_up", "KRH-09", "Share new feature note", "checkin", "normal", 9, None, None, None),
    ("follow_up", "PRO-11", "Confirm data handoff", "onboarding", "normal", 7, None, None, None),
    ("follow_up", "VPS-10", "Payment terms clarification", "admin", "normal", 10, None, None, None),

    ("waiting", "SQY-03", "Waiting on client API keys", "onboarding", "normal", 5, None, None, None),
    ("waiting", "DIG-08", "Waiting on product fix ETA", "escalation", "normal", 6, None, None, None),

    ("done", "PRE-04", "Log Q2 QBR outcomes", "renewal", "normal", -2, None, None, 2),
    ("done", "SET-07", "Send usage summary", "checkin", "normal", -4, None, None, 4),
    ("done", "NFS-05", "Share VLs pricing sheet", "expansion", "normal", -6, None, None, 6),
]

SAVED_VIEWS = [
    ("My At-Risk", {"bands": ["at_risk", "critical"]}, True),
    ("Renewals in 30", {"renewal_window": 30}, True),
    ("Needs Follow-Up", {"overdue": True}, False),
    ("No Contact Recently", {"last_contact_gt": 14}, False),
    ("High Value", {"high_value": True}, False),
    ("Onboarding", {"stages": ["ready_for_onboarding", "onboarding"]}, False),
    ("Expansion Opportunities", {"expansion": True}, False),
]


# --- health curve calibration ------------------------------------------------

def interpolate(curve: list[tuple[int, int]], days_ago: int) -> float:
    """Linear interpolation between control points, flat outside their range."""
    pts = sorted(curve, key=lambda p: -p[0])  # oldest first
    if days_ago >= pts[0][0]:
        return float(pts[0][1])
    if days_ago <= pts[-1][0]:
        return float(pts[-1][1])
    for (d0, s0), (d1, s1) in zip(pts, pts[1:]):
        if d1 <= days_ago <= d0:
            span = d0 - d1
            if span == 0:
                return float(s1)
            frac = (d0 - days_ago) / span
            return s0 + (s1 - s0) * frac
    return float(pts[-1][1])


def build_usage_series(targets: list[float], eng: int, sup: int, sent: int, seats: int):
    """Back-solve daily active users so the engine's trailing-14d average
    reproduces the target health curve.

    The engine reads a 14-day average, so the daily series is recovered from the
    average series by  u[i] = u[i-14] + 14 * (A[i] - A[i-1]).
    """
    avg = [
        float(health_engine.solve_usage_for(int(round(t)), eng, sup, sent))
        for t in targets
    ]
    daily = [avg[13]] * 14
    for i in range(14, len(avg)):
        daily.append(max(0.0, daily[i - 14] + 14 * (avg[i] - avg[i - 1])))

    users = [max(0, int(round(v / 100 * seats))) for v in daily]

    # Correct rounding drift so today's 14-day window lands exactly on target.
    want = int(round(avg[-1] / 100 * seats * 14))
    have = sum(users[-14:])
    diff = want - have
    step = 1 if diff > 0 else -1
    idx = len(users) - 1
    while diff != 0 and idx >= len(users) - 14:
        if users[idx] + step >= 0:
            users[idx] += step
            diff -= step
        idx -= 1
        if idx < len(users) - 14 and diff != 0:
            idx = len(users) - 1  # wrap and keep spreading
            if all(u == 0 for u in users[-14:]) and step < 0:
                break
    return avg, users


# --- seed --------------------------------------------------------------------

def seed_if_empty(session: Session) -> bool:
    if session.exec(select(Account)).first() is not None:
        return False

    csm = User(name="Shivam Singh", initials="SS", avatar_color="#111111")
    session.add(csm)
    session.commit()
    session.refresh(csm)

    by_key: dict[str, Account] = {}

    for spec in ACCOUNTS:
        line_items = [
            {"offering": offering, "qty": qty, "rate": RATES[offering]}
            for offering, qty in spec["line_items"]
        ]
        arr = sum(li["qty"] * li["rate"] for li in line_items)  # never trust the client
        account = Account(
            key=spec["key"],
            name=spec["name"],
            segment=spec["segment"],
            city=spec["city"],
            lifecycle_stage=spec["stage"],
            closed_reason=spec.get("closed_reason"),
            arr=arr,
            owner_id=csm.id,
            entitled_seats=SEATS_BY_SEGMENT[spec["segment"]],
            last_nps=spec.get("last_nps"),
            expansion_flag=spec.get("expansion", False),
            tags=[],
            handoff_received_at=(
                _dt(spec["handoff_days_ago"]) if spec.get("handoff_days_ago") else None
            ),
        )
        session.add(account)
        session.flush()
        by_key[spec["key"]] = account

        session.add(
            Subscription(
                account_id=account.id,
                start_date=TODAY + timedelta(days=spec["renewal"] - 365),
                renewal_date=TODAY + timedelta(days=spec["renewal"]),
                auto_renew=spec["stage"] != "closed",
                status="churned" if spec["stage"] == "closed" else "active",
                line_items=line_items,
            )
        )

    for key, name, role, champion, buyer, status in CONTACTS:
        slug = "".join(ch for ch in name.split()[0].lower() if ch.isalpha())
        domain = by_key[key].name.split()[0].lower()
        session.add(
            Contact(
                account_id=by_key[key].id,
                name=name,
                role=role,
                email=f"{slug}@{domain}.in",
                phone=f"+91 9{7000 + len(name) * 13:04d} {10000 + len(role) * 371:05d}",
                is_champion=champion,
                is_economic_buyer=buyer,
                status=status,
            )
        )

    for key, rtype, severity, note, days_ago in RISKS:
        session.add(
            Risk(
                account_id=by_key[key].id,
                type=rtype,
                severity=severity,
                status="open",
                note=note,
                opened_at=_dt(days_ago),
            )
        )

    for key, (done_count, overdue_idx) in MILESTONE_PLAN.items():
        for i, label in enumerate(MILESTONE_LABELS):
            if i < done_count:
                status, target = "done", TODAY - timedelta(days=20 - i * 5)
            elif overdue_idx is not None and i == overdue_idx:
                status, target = "pending", TODAY - timedelta(days=6)
            else:
                status, target = "pending", TODAY + timedelta(days=7 + (i - done_count) * 12)
            session.add(
                Milestone(
                    account_id=by_key[key].id,
                    label=label,
                    status=status,
                    target_date=target,
                    sort_index=float(i),
                )
            )

    contacts_by_account = {}
    for c in session.exec(select(Contact)).all():
        contacts_by_account.setdefault(c.account_id, []).append(c)

    for key, rows in ACTIVITIES.items():
        account = by_key[key]
        champion = next(
            (c for c in contacts_by_account.get(account.id, []) if c.is_champion), None
        )
        buyer = next(
            (c for c in contacts_by_account.get(account.id, []) if c.is_economic_buyer),
            None,
        )
        for days_ago, atype, summary, body in rows:
            linked = None
            if atype in ("email", "call", "meeting", "qbr"):
                linked = buyer if atype == "qbr" and buyer else champion
            session.add(
                Activity(
                    account_id=account.id,
                    contact_id=linked.id if linked else None,
                    type=atype,
                    occurred_at=_dt(days_ago),
                    summary=summary,
                    body=body,
                )
            )

    session.commit()

    # --- calibrate usage + health history ------------------------------------
    for spec in ACCOUNTS:
        account = by_key[spec["key"]]
        eng = health_engine.engagement_component(session, account)
        sup = health_engine.support_component(session, account)
        sent = health_engine.sentiment_component(account)

        days = list(range(USAGE_HISTORY_DAYS - 1, -1, -1))  # oldest -> today
        targets = [interpolate(spec["curve"], d) for d in days]

        # Nudge the final target so integer rounding still composes exactly.
        want_today = int(round(targets[-1]))
        for bump in (0, 1, -1, 2, -2):
            probe = health_engine.solve_usage_for(want_today + bump, eng, sup, sent)
            if health_engine.compose(probe, eng, sup, sent) == want_today:
                targets[-1] = want_today + bump
                break

        avg, users = build_usage_series(targets, eng, sup, sent, account.entitled_seats)

        for offset, (day_ago, active) in enumerate(zip(days, users)):
            captured = TODAY - timedelta(days=day_ago)
            session.add(
                UsageMetric(
                    account_id=account.id,
                    captured_on=captured,
                    active_users=active,
                    sessions=active * 3 + (offset % 5),
                    feature_adoption_pct=min(100, int(round(avg[offset] * 0.9))),
                )
            )

        # Snapshots for the last 90 days; today's row is written by the engine.
        for day_ago in range(SNAPSHOT_DAYS, 0, -1):
            i = days.index(day_ago)
            usage = int(round(avg[i]))
            session.add(
                HealthSnapshot(
                    account_id=account.id,
                    captured_on=TODAY - timedelta(days=day_ago),
                    score=int(round(interpolate(spec["curve"], day_ago))),
                    usage=usage,
                    engagement=eng,
                    support=sup,
                    sentiment=sent,
                )
            )

    session.commit()

    for bucket, key, title, ttype, priority, due_offset, provenance, rule_key, done_days in TASKS:
        account = by_key[key]
        session.add(
            Task(
                account_id=account.id,
                title=title,
                type=ttype,
                bucket=bucket,
                due_date=TODAY + timedelta(days=due_offset),
                status="done" if bucket == "done" else "open",
                priority=priority,
                owner_id=csm.id,
                provenance=provenance,
                rule_key=rule_key,
                completed_at=_dt(done_days) if done_days is not None else None,
                sort_index=float(due_offset),
            )
        )

    for i, (name, filters, pinned) in enumerate(SAVED_VIEWS):
        session.add(
            SavedView(name=name, filter_json=filters, pinned=pinned, sort_index=float(i))
        )

    session.commit()

    # Compute cached health from the seeded raw data, then apply the one manual
    # override the story calls for, then rank.
    health_engine.recompute_all(session)

    for spec in ACCOUNTS:
        if spec.get("override"):
            band, reason = spec["override"]
            account = by_key[spec["key"]]
            account.health_manual_override = band
            account.health_override_reason = reason
            account.health_override_at = _dt(4)
            session.add(account)
    session.commit()

    from engines import alerts as alert_engine

    alert_engine.evaluate(session)
    refresh_cached_scores(session)
    return True

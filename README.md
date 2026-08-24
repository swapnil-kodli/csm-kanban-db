# Signal CS

A personal Customer Success workspace that answers "who needs me right now and
what do I do about it" in under 60 seconds. Not an analytics dashboard.

Marketplace slug: `signal-cs`.

## Run it

```bash
docker compose up --build
# app:  http://localhost:8080/p/signal-cs/
# api:  http://localhost:8080/p/signal-cs/api/health
```

The backend auto-seeds on an empty database, so the board loads with a full book
of 12 accounts on first start. SQLite lives on the `signal-data` volume, so the
board survives restarts.

### Local development

```bash
# backend
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --reload --port 8000

# frontend (proxies /api to 127.0.0.1:8000)
cd frontend && npm install && npm run dev
```

## Layout

```
frontend/          Vite + React 18 + TS, plain CSS, nginx image
backend/           FastAPI + SQLModel + SQLite
docker-compose.yml frontend (public gateway) + backend (internal)
```

The frontend container is the public gateway: nginx serves the build and proxies
`/api` to `http://backend:8000` on the internal Docker network. `BASE_PATH` and
`VITE_API_URL` are build args, baked in at `npm run build` — no domain or slug is
hardcoded anywhere in app code.

## The three board views

| View | Columns | Cards | Drag writes |
|---|---|---|---|
| **My Work** (default) | Today · This Week · Follow-Up · Waiting · Done | Tasks | `PATCH /api/tasks/{id} {bucket}` |
| **Health** | Healthy · Watch · At Risk · Critical | Accounts | Nothing — opens the override dialog, writes only on confirm with a reason |
| **Lifecycle** | Ready for Onboarding · Onboarding · Adopting · Healthy · Renewal · Closed | Accounts | `PATCH /api/accounts/{id} {lifecycle_stage}` |

Grouping mode and swimlane collapse state persist in `localStorage`; the active
filter set lives in the URL query string so a view is shareable.

## Engines

- **`engines/health.py`** — `.40 usage + .25 engagement + .20 support + .15 sentiment`,
  banded at 75 / 55 / 35. Velocity is `score_today − score_30d_ago`. A manual
  override replaces the band everywhere but leaves the score visible, and prompts
  for review after 60 days.
- **`engines/attention.py`** — the composite that ranks the Needs Attention queue
  and orders cards inside every column. It ships its contributing terms with the
  score, and the drawer renders them, so the ranking is never a black box. A
  pinned account outranks the formula.
- **`engines/alerts.py`** — rules evaluate to owned tasks, or to board state.
  Idempotent on `(account_id, rule_key)`. Thresholds are relative to the account
  via `SEGMENT_THRESHOLDS`.

There is no notification bell. An alert is only allowed to exist if it becomes a
task someone owns; everything else changes a badge.

## Keyboard

`⌘K`/`Ctrl-K` command palette · `/` search · `1` `2` `3` views · `g` cycle
swimlanes · `c` new task · `n` log activity on the open account · `j`/`k` move
card selection · `Enter` open drawer · `Esc` close. Every keyboard action has a
mouse path, and drag-drop has a keyboard path (`Space` grab, arrows, `Space` drop).

## When the backend is down

Reads fall back to the last payload this browser cached, the source dot in the
topbar flips from green `LIVE` to amber `LOCAL`, and a banner says changes will
not save. The board degrades; it never goes blank. Writes never fall back — a
silent no-op would lie about what was saved.

See `FUTURE.md` for what was deliberately left out, and for the handful of
documented deviations from the specs.

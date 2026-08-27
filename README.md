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

## Sign-in and Gmail

Both are **off by default**. The app is fully usable, demo-able and deployable
with neither, running as a single CSM. Turn them on deliberately.

### Google Cloud Console, once

1. **APIs & Services → OAuth consent screen → Internal.**
   Not External. External + Testing expires every refresh token after 7 days,
   so the integration dies a week after each demo with no visible cause.
   *Internal* is only selectable when the project belongs to the Workspace org.
2. **Credentials → Create OAuth client ID → Web application.**
3. **Authorised redirect URIs — register BOTH.** Google matches these exactly,
   with no wildcards or pattern matching:

   ```
   https://marketplace.revspot.ai/p/signal-cs/api/google/callback
   http://localhost:8080/api/google/callback
   ```

   Set `GOOGLE_REDIRECT_URI` to whichever one the deployment actually serves.
   It is explicit configuration rather than something derived per request: the
   frontend's nginx strips `/p/{slug}` before proxying so the backend cannot see
   the slug, and building it from the `Host` header would be an open redirect.
4. **Enable the Gmail API** for the project.

### backend/.env

```sh
AUTH_ENABLED=true
ALLOWED_EMAIL_DOMAINS=revspot.ai      # empty means NOBODY, not everybody
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(32))">

GMAIL_ENABLED=true
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://marketplace.revspot.ai/p/signal-cs/api/google/callback
```

`SECRET_KEY` encrypts the stored Gmail refresh token. It is required before
Gmail can be connected, and is deliberately not generated at boot — a key that
lived only in memory would invalidate every grant on restart and send everyone
back through consent with no explanation.

### Two grants, on purpose

| | Scopes | When |
|---|---|---|
| Sign-in | `openid email profile` | At login. Non-sensitive, no Google review. |
| Gmail | `gmail.readonly` | Later, per person, from the thread panel itself. |

Asking for `gmail.readonly` at sign-in would put a restricted-scope consent
screen in front of people who may never open the panel, and would make declining
it look like failing to log in.

### What the thread panel shows

Correspondence between **the signed-in user** and **the deal's POC**. Nothing
else. Query:

```
from:{poc} OR to:{poc} OR cc:{poc}
```

`cc:` is required and is not implied by `to:` — Gmail treats them as separate
headers, so without it every group thread where the POC was copied rather than
addressed goes missing, which is exactly the context history the panel exists
for. `bcc:` is not searchable at all; that gap is accepted rather than worked
around.

Metadata only: subject, snippet, participants, message count, last message
date, unread. Message bodies are never fetched or stored beyond the snippet
Gmail itself returns.

**Each person sees only their own mail.** A teammate's threads with the same POC
never appear, even on the same deal. That is intended, not a limitation to
engineer around — pooling would mean one person's consent exposing their mailbox
to the whole team.

### The states the panel renders

`disabled` · `not_signed_in` · `no_poc_email` · `not_connected` ·
`needs_reconnect` · `empty` · `ok` · `error`

The server decides which applies and the panel renders it, so the two cannot
drift. A Gmail outage — a 401, a revoked grant, Google being down — never blocks
the drawer or the board: the panel sits behind an error boundary as well.

## Troubleshooting a deployment

See `WHITE-SCREEN-RUNBOOK.md` for the full playbook on blank-page failures under
path-based routing — triage commands, the four distinct causes hit during this
build, and the guards that stop them recurring.

**Blank page, nothing renders.** Check what `index.html` references:

```bash
curl -s https://<host>/p/<slug>/ | grep -o 'src="[^"]*"'
```

- *`src="/assets/…"`* (root-absolute) — the build did not receive `BASE_PATH`.
  Anything outside `/p/{slug}/` is routed to the marketplace app, not to this
  deployment, so no JavaScript ever loads. This is why the build now falls back
  to **relative** asset URLs: `vite.config.ts` resolves `BASE_PATH` from the
  build arg, then from `frontend/.env` via `loadEnv` (Vite does not put `.env`
  onto `process.env`, which is the trap), and finally emits `./assets/…`, which
  resolves correctly under any slug.
- *`src="./assets/…"`* — correct and slug-independent. Expected.
- *`src="/p/some-other-slug/assets/…"`* — a slug was pinned at build time and it
  does not match where the app is served. Unset `BASE_PATH` and rebuild.

The app does not depend on knowing its slug: the router basename and the API
base are both derived from `window.location` at runtime, with the build-time
values used only as a fallback.

**Board is empty / amber `LOCAL` dot / "board could not load".** The `/api` route
is not reaching the backend. Open the network tab and check one API request:

- *Request URL contains `//api`* — the injected `VITE_API_URL` carried a trailing
  slash and was concatenated naively. `frontend/src/lib/api.ts` strips trailing
  slashes for exactly this reason, so a doubled slash means an older build is
  still deployed. `INSTRUCTIONS.md` is itself inconsistent here: §6 injects
  `/p/{slug}` while §7's compose example uses `/p/{slug}/`. Both must work.
- *Response is `200 text/html`* — the request fell through to the SPA fallback
  instead of the proxy. That looks like success to `fetch`, so the client raises
  it explicitly: "returned text/html instead of JSON — the /api proxy route is
  not reaching the backend (resolved base: …)". Check the nginx `location` blocks.
- *Response is `502`* — nginx is up and the backend is not. Check the backend
  container logs; the first boot seeds the database.

**Frontend container restarting.** nginx resolves `backend` while loading its
config and refuses to start if that name does not exist yet. The image's
entrypoint waits up to 30s for it before starting nginx.

See `FUTURE.md` for what was deliberately left out, and for the handful of
documented deviations from the specs.

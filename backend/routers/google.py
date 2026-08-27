"""Gmail integration — read-only thread listing for a deal's POC.

Auth is OAuth2 authorization-code flow, server-side. There is no API-key path to
a user's Gmail. The client secret and refresh token never leave the backend and
are never present in the frontend bundle.

Redirect URI
------------
`GOOGLE_REDIRECT_URI` is explicit configuration in backend/.env, not a hardcoded
domain, for three reasons that together rule out deriving it per-request:

  * Google requires an EXACT match against a pre-registered absolute URI, so it
    must be stable and known before any request arrives.
  * The frontend's nginx strips `/p/{slug}` before proxying, so the backend
    cannot see the slug in the request path at all.
  * Building it from Host / X-Forwarded-Host instead would be an open redirect:
    an attacker-controlled header would steer where the OAuth code lands.

State
-----
The frontend never supplies the post-callback target. The server mints an opaque
random nonce, stores {nonce -> app_base} with a 10-minute TTL, and sends only the
nonce as `state`. The callback looks the nonce up, uses it once, and deletes it.
That is CSRF protection and redirect validation in one, and nothing
attacker-influenceable ever reaches the redirect.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from db import get_session
from dbtypes import as_utc, utcnow
from models import Deal, GoogleCredential

log = logging.getLogger("signal.google")
router = APIRouter(prefix="/google", tags=["google"])

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

STATE_TTL_SECONDS = 600
THREAD_CACHE_TTL_SECONDS = 300

# nonce -> (app_base, expires_at). Single-process, single-user MVP.
_pending_states: dict[str, tuple[str, float]] = {}
# deal_id -> (fetched_at, payload)
_thread_cache: dict[str, tuple[float, dict]] = {}


def gmail_enabled() -> bool:
    return os.getenv("GMAIL_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def _cfg(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _require_config() -> tuple[str, str, str]:
    client_id, secret, redirect = (
        _cfg("GOOGLE_CLIENT_ID"),
        _cfg("GOOGLE_CLIENT_SECRET"),
        _cfg("GOOGLE_REDIRECT_URI"),
    )
    missing = [
        n
        for n, v in (
            ("GOOGLE_CLIENT_ID", client_id),
            ("GOOGLE_CLIENT_SECRET", secret),
            ("GOOGLE_REDIRECT_URI", redirect),
        )
        if not v
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Gmail is enabled but not configured: missing {', '.join(missing)}",
        )
    return client_id, secret, redirect


def _sweep_states() -> None:
    now = time.time()
    for nonce, (_, expires) in list(_pending_states.items()):
        if expires < now:
            _pending_states.pop(nonce, None)


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _credential(session: Session) -> Optional[GoogleCredential]:
    return session.exec(select(GoogleCredential)).first()


def _access_token(session: Session, cred: GoogleCredential) -> str:
    """Refresh the access token when it is missing or within a minute of expiry."""
    fresh = (
        cred.access_token
        and cred.access_token_expires_at
        and as_utc(cred.access_token_expires_at) > utcnow() + timedelta(seconds=60)
    )
    if fresh:
        return cred.access_token  # type: ignore[return-value]

    client_id, secret, _ = _require_config()
    payload = _post_form(
        TOKEN_URI,
        {
            "client_id": client_id,
            "client_secret": secret,
            "refresh_token": cred.refresh_token,
            "grant_type": "refresh_token",
        },
    )
    cred.access_token = payload["access_token"]
    cred.access_token_expires_at = utcnow() + timedelta(
        seconds=int(payload.get("expires_in", 3600))
    )
    cred.updated_at = utcnow()
    session.add(cred)
    session.commit()
    return cred.access_token


# --- endpoints ---------------------------------------------------------------

@router.get("/status")
def status(session: Session = Depends(get_session)):
    if not gmail_enabled():
        return {"enabled": False, "connected": False, "reason": "GMAIL_ENABLED is off"}
    cred = _credential(session)
    configured = all(
        _cfg(n) for n in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")
    )
    return {
        "enabled": True,
        "configured": configured,
        "connected": cred is not None,
        "email": cred.email if cred else None,
    }


@router.get("/authorize")
def authorize(app_base: str = Query("/", max_length=200)):
    """Mint a single-use nonce and hand the browser to Google's consent screen."""
    if not gmail_enabled():
        raise HTTPException(status_code=503, detail="Gmail integration is disabled")
    client_id, _, redirect_uri = _require_config()

    _sweep_states()
    nonce = secrets.token_urlsafe(32)
    # Only a same-origin path is ever stored, never a full URL: even though the
    # client supplies it, it cannot become an off-site redirect.
    safe_base = app_base if app_base.startswith("/") else "/"
    _pending_states[nonce] = (safe_base, time.time() + STATE_TTL_SECONDS)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": nonce,
    }
    return RedirectResponse(f"{AUTH_URI}?{urllib.parse.urlencode(params)}", status_code=302)


@router.get("/callback")
def callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    session: Session = Depends(get_session),
):
    if not gmail_enabled():
        raise HTTPException(status_code=503, detail="Gmail integration is disabled")

    _sweep_states()
    # Single use: pop, never read-and-leave.
    entry = _pending_states.pop(state or "", None)
    if entry is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    app_base, _ = entry

    if error or not code:
        return RedirectResponse(f"{app_base}?gmail=error", status_code=302)

    client_id, secret, redirect_uri = _require_config()
    try:
        payload = _post_form(
            TOKEN_URI,
            {
                "client_id": client_id,
                "client_secret": secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
    except urllib.error.HTTPError as exc:
        log.warning("Google token exchange failed: %s", exc)
        return RedirectResponse(f"{app_base}?gmail=error", status_code=302)

    refresh = payload.get("refresh_token")
    if not refresh:
        # Google only returns a refresh token on first consent.
        return RedirectResponse(f"{app_base}?gmail=no_refresh_token", status_code=302)

    email = None
    try:
        profile = _get_json(f"{GMAIL_API}/users/me/profile", payload["access_token"])
        email = profile.get("emailAddress")
    except Exception:  # profile is a nicety, never a reason to fail the connect
        pass

    cred = _credential(session)
    if cred is None:
        cred = GoogleCredential(refresh_token=refresh)
    cred.refresh_token = refresh
    cred.access_token = payload.get("access_token")
    cred.access_token_expires_at = utcnow() + timedelta(
        seconds=int(payload.get("expires_in", 3600))
    )
    cred.email = email
    cred.updated_at = utcnow()
    session.add(cred)
    session.commit()
    _thread_cache.clear()
    return RedirectResponse(f"{app_base}?gmail=connected", status_code=302)


@router.post("/disconnect")
def disconnect(session: Session = Depends(get_session)):
    cred = _credential(session)
    if cred is not None:
        session.delete(cred)
        session.commit()
    _thread_cache.clear()
    return {"connected": False}


def invalidate_deal_threads(deal_id: str) -> None:
    """Drop one deal's cached threads.

    Called whenever the deal's POC changes or that contact's address is edited.
    The cache is keyed on the deal but the query is built from the POC's email,
    so a stale entry would keep answering for the wrong person.
    """
    _thread_cache.pop(deal_id, None)


def poc_email(session: Session, deal: Deal) -> Optional[str]:
    """The email the thread query is built from: this DEAL's POC.

    Not the company's primary contact. Two deals with the same client can have
    different counterparts, and the panel has to show the correspondence that
    belongs to the engagement being looked at.
    """
    from models import Contact

    poc = session.get(Contact, deal.poc_id)
    return poc.email if poc else None


def fetch_threads(session: Session, deal: Deal, limit: int = 20) -> dict:
    """The states the panel must handle, all resolved server-side."""
    if not gmail_enabled():
        return {"state": "disabled", "threads": []}
    address = poc_email(session, deal)
    if not address:
        return {"state": "no_poc_email", "threads": []}
    cred = _credential(session)
    if cred is None:
        return {"state": "not_connected", "threads": []}

    cached = _thread_cache.get(deal.id)
    if cached and time.time() - cached[0] < THREAD_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        token = _access_token(session, cred)
        # `cc:` is required and is not implied by `to:` — Gmail treats them as
        # separate headers, so without it every group thread where the POC was
        # copied rather than addressed goes missing, which is precisely the
        # context history this panel exists to surface.
        # `bcc:` is not searchable at all; that gap is accepted, not worked around.
        query = urllib.parse.quote(
            f"from:{address} OR to:{address} OR cc:{address}"
        )
        listing = _get_json(
            f"{GMAIL_API}/users/me/threads?maxResults={limit}&q={query}", token
        )
        threads = []
        for stub in listing.get("threads", [])[:limit]:
            detail = _get_json(
                f"{GMAIL_API}/users/me/threads/{stub['id']}?format=metadata"
                "&metadataHeaders=Subject&metadataHeaders=From"
                "&metadataHeaders=To&metadataHeaders=Date",
                token,
            )
            messages = detail.get("messages", [])
            if not messages:
                continue
            headers = {
                h["name"].lower(): h["value"]
                for h in messages[-1].get("payload", {}).get("headers", [])
            }
            participants = sorted(
                {
                    p.strip()
                    for m in messages
                    for h in m.get("payload", {}).get("headers", [])
                    if h["name"].lower() in ("from", "to")
                    for p in h["value"].split(",")
                }
            )
            last_ms = int(messages[-1].get("internalDate", "0"))
            threads.append(
                {
                    "thread_id": stub["id"],
                    "subject": headers.get("subject") or "(no subject)",
                    "snippet": stub.get("snippet") or messages[-1].get("snippet", ""),
                    "last_message_at": datetime.utcfromtimestamp(last_ms / 1000).isoformat()
                    if last_ms
                    else None,
                    "message_count": len(messages),
                    "participants": participants,
                    "unread": any("UNREAD" in m.get("labelIds", []) for m in messages),
                }
            )
        payload = {"state": "ok", "threads": threads}
        _thread_cache[deal.id] = (time.time(), payload)
        return payload
    except urllib.error.HTTPError as exc:
        log.warning("Gmail fetch failed for %s: %s", deal.key, exc)
        state = "token_expired" if exc.code in (401, 403) else "error"
        return {"state": state, "threads": [], "detail": f"Gmail returned {exc.code}"}
    except Exception as exc:  # never let Gmail break the drawer
        log.warning("Gmail fetch failed for %s: %s", deal.key, exc)
        return {"state": "error", "threads": [], "detail": str(exc)}


@router.get("/deals/{deal_id}/threads")
def deal_threads(
    deal_id: str, limit: int = Query(20, ge=1, le=50), session: Session = Depends(get_session)
):
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return fetch_threads(session, deal, limit)

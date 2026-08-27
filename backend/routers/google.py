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
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from auth import (
    LOGIN_SCOPES,
    SESSION_COOKIE,
    auth_enabled,
    allowed_domains,
    current_user,
    domain_allowed,
    end_session,
    start_session,
    upsert_user,
    verify_id_token,
)
from crypto import decrypt, encrypt, secret_key_configured
from db import get_session
from dbtypes import as_utc, utcnow
from models import Deal, GoogleCredential, User

log = logging.getLogger("signal.google")
router = APIRouter(prefix="/google", tags=["google"])

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

STATE_TTL_SECONDS = 600
THREAD_CACHE_TTL_SECONDS = 300

# nonce -> (app_base, nonce_for_id_token, kind, expires_at). Single process.
_pending_states: dict[str, tuple[str, str, str, float]] = {}

# (user_id, deal_id) -> (fetched_at, payload). Keyed by USER as well as deal,
# because the panel shows the signed-in user's own correspondence: a cache keyed
# by deal alone would serve one person's mailbox to the next person who opened
# the same card.
_thread_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def gmail_enabled() -> bool:
    return os.getenv("GMAIL_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def _cfg(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _require_config(need_secret_key: bool = False) -> tuple[str, str, str]:
    """Every missing prerequisite at once, not the first one found.

    Reported one at a time, an operator fixes GOOGLE_CLIENT_ID, retries, learns
    about the secret, retries, learns about SECRET_KEY — three round trips
    through a redeploy to discover facts that were all knowable at the first
    request.
    """
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
    if need_secret_key and not secret_key_configured():
        missing.append("SECRET_KEY (encrypts the stored refresh token)")
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Gmail is enabled but not configured: missing {', '.join(missing)}",
        )
    return client_id, secret, redirect


def _sweep_states() -> None:
    """Expire pending states. The entry is (app_base, nonce, kind, expires_at);
    the expiry is the LAST element, read by index so widening the tuple again
    cannot silently break this the way positional unpacking did."""
    now = time.time()
    for state, entry in list(_pending_states.items()):
        if entry[-1] < now:
            _pending_states.pop(state, None)


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


def _credential(session: Session, user_id: str) -> Optional[GoogleCredential]:
    return session.exec(
        select(GoogleCredential).where(GoogleCredential.user_id == user_id)
    ).first()


class TokenUnreadable(RuntimeError):
    """The stored refresh token cannot be decrypted — reconnect is the fix."""


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
    refresh = decrypt(cred.refresh_token)
    if not refresh:
        # A rotated or missing SECRET_KEY. Recoverable in one click by
        # reconnecting, so it must not become a 500 that takes the drawer down.
        raise TokenUnreadable()
    payload = _post_form(
        TOKEN_URI,
        {
            "client_id": client_id,
            "client_secret": secret,
            "refresh_token": refresh,
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

def _mint_state(app_base: str, kind: str) -> tuple[str, str]:
    """One single-use nonce for `state`, one for the ID token's `nonce` claim.

    Two values, not one: `state` ties the callback to the browser that started
    it, and `nonce` ties the ID TOKEN to this request so a token obtained
    elsewhere cannot be replayed into our flow. Reusing one value for both would
    put the state — which travels in a URL and lands in logs and Referer
    headers — inside the signed token as well.
    """
    _sweep_states()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    # Only a same-origin path is ever stored, never a full URL: even though the
    # client supplies it, it cannot become an off-site redirect.
    safe_base = app_base if app_base.startswith("/") else "/"
    _pending_states[state] = (safe_base, nonce, kind, time.time() + STATE_TTL_SECONDS)
    return state, nonce


@router.get("/status")
def status(
    session: Session = Depends(get_session),
    user: Optional[User] = Depends(current_user),
):
    """Everything the panel needs to pick one of its five states, in one call."""
    configured = all(
        _cfg(n) for n in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")
    )
    cred = _credential(session, user.id) if user else None
    return {
        "enabled": gmail_enabled(),
        "configured": configured,
        "encryption_ready": secret_key_configured(),
        "auth_enabled": auth_enabled(),
        "signed_in": user is not None,
        "user": {"id": user.id, "name": user.name, "email": user.email} if user else None,
        # Per user, never pooled. Someone else's grant does not make this one connected.
        "connected": cred is not None,
        "email": cred.email if cred else None,
    }


# --- sign-in (openid/email/profile only) -------------------------------------

@router.get("/login")
def login(app_base: str = Query("/", max_length=200)):
    """Non-sensitive scopes only. gmail.readonly is a separate, later grant."""
    if not auth_enabled():
        raise HTTPException(status_code=503, detail="Sign-in is disabled")
    client_id, _, redirect_uri = _require_config()
    state, nonce = _mint_state(app_base, "login")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": LOGIN_SCOPES,
        "state": state,
        "nonce": nonce,
        # Sign-in does not need offline access: there is no background work to
        # do on the user's behalf, so asking for a refresh token here would take
        # a long-lived credential we would never use.
        "access_type": "online",
        "prompt": "select_account",
    }
    return RedirectResponse(f"{AUTH_URI}?{urllib.parse.urlencode(params)}", status_code=302)


@router.post("/logout")
def logout(
    response: Response,
    session: Session = Depends(get_session),
    signal_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
):
    end_session(session, signal_session, response)
    return {"signed_in": False}


# --- gmail grant (restricted scope, per user) --------------------------------

@router.get("/authorize")
def authorize(
    app_base: str = Query("/", max_length=200),
    user: Optional[User] = Depends(current_user),
):
    """Mint a single-use state and hand the browser to Google's consent screen.

    `access_type=offline` + `prompt=consent` together: Google returns a refresh
    token only on the FIRST consent for a client/user pair, so without the
    forced prompt a re-connect silently yields no refresh token and the grant
    dies at the first access-token expiry, an hour later, with no clue why.
    """
    if not gmail_enabled():
        raise HTTPException(status_code=503, detail="Gmail integration is disabled")
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in before connecting Gmail")
    # need_secret_key: this flow ends by STORING a refresh token, so a missing
    # encryption key is as blocking as a missing client id — and the operator
    # should hear about both in the same breath.
    client_id, _, redirect_uri = _require_config(need_secret_key=True)
    state, nonce = _mint_state(app_base, f"gmail:{user.id}")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "nonce": nonce,
    }
    return RedirectResponse(f"{AUTH_URI}?{urllib.parse.urlencode(params)}", status_code=302)


@router.get("/callback")
def callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    scope: Optional[str] = None,
    session: Session = Depends(get_session),
    user: Optional[User] = Depends(current_user),
):
    """One callback for both flows; `kind` in the stored state says which."""
    _sweep_states()
    entry = _pending_states.pop(state or "", None)   # single use: pop, never peek
    if entry is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    app_base, nonce, kind, _ = entry

    if error or not code:
        # The user declining at the consent screen arrives here as
        # error=access_denied. That is a choice, not a fault, and the panel says
        # so rather than showing a failure.
        reason = "declined" if error == "access_denied" else "error"
        return RedirectResponse(f"{app_base}?gmail={reason}", status_code=302)

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

    if kind == "login":
        return _finish_login(session, response, request, payload, client_id, nonce, app_base)
    return _finish_gmail(session, payload, kind, user, app_base, scope)


def _finish_login(session, response, request, payload, client_id, nonce, app_base):
    id_token = payload.get("id_token")
    if not id_token:
        return RedirectResponse(f"{app_base}?auth=error", status_code=302)
    try:
        claims = verify_id_token(id_token, audience=client_id, nonce=nonce)
    except Exception as exc:
        log.warning("ID token rejected: %s", exc)
        return RedirectResponse(f"{app_base}?auth=invalid_token", status_code=302)

    if not domain_allowed(claims["email"]):
        log.warning("Sign-in refused for %s (allowlist: %s)", claims["email"], allowed_domains())
        return RedirectResponse(f"{app_base}?auth=domain", status_code=302)

    user = upsert_user(session, claims)
    if not user.is_active:
        return RedirectResponse(f"{app_base}?auth=disabled", status_code=302)

    redirect = RedirectResponse(f"{app_base}?auth=ok", status_code=302)
    # The cookie has to be set on the response that is actually returned, not on
    # the injected one — FastAPI only merges headers from the returned object.
    start_session(session, user, redirect, request.headers.get("user-agent", ""))
    return redirect


def _finish_gmail(session, payload, kind, user, app_base, granted_scope):
    owner_id = kind.split(":", 1)[1] if ":" in kind else (user.id if user else None)
    if not owner_id:
        return RedirectResponse(f"{app_base}?gmail=error", status_code=302)

    # Google grants scopes individually. Someone can approve sign-in and refuse
    # gmail.readonly on the same screen, and the callback still arrives with a
    # perfectly valid code — so the granted scope is checked rather than assumed.
    if granted_scope is not None and SCOPE not in granted_scope.split():
        return RedirectResponse(f"{app_base}?gmail=scope_declined", status_code=302)

    refresh = payload.get("refresh_token")
    if not refresh:
        return RedirectResponse(f"{app_base}?gmail=no_refresh_token", status_code=302)

    email = None
    try:
        profile = _get_json(f"{GMAIL_API}/users/me/profile", payload["access_token"])
        email = profile.get("emailAddress")
    except Exception:  # a nicety, never a reason to fail the connect
        pass

    cred = _credential(session, owner_id)
    if cred is None:
        cred = GoogleCredential(user_id=owner_id, refresh_token="")
    cred.refresh_token = encrypt(refresh)      # ciphertext at rest, always
    cred.access_token = payload.get("access_token")
    cred.access_token_expires_at = utcnow() + timedelta(
        seconds=int(payload.get("expires_in", 3600))
    )
    cred.email = email
    cred.updated_at = utcnow()
    session.add(cred)
    session.commit()
    _drop_user_cache(owner_id)
    return RedirectResponse(f"{app_base}?gmail=connected", status_code=302)


@router.post("/disconnect")
def disconnect(
    session: Session = Depends(get_session),
    user: Optional[User] = Depends(current_user),
):
    """Revokes only the caller's own grant, never anyone else's."""
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    cred = _credential(session, user.id)
    if cred is not None:
        session.delete(cred)
        session.commit()
    _drop_user_cache(user.id)
    return {"connected": False}


def _drop_user_cache(user_id: str) -> None:
    for key in [k for k in _thread_cache if k[0] == user_id]:
        _thread_cache.pop(key, None)


def invalidate_deal_threads(deal_id: str) -> None:
    """Drop one deal's cached threads, for every user.

    Called whenever the deal's POC changes or that contact's address is edited.
    The cache is keyed on (user, deal) but the query is built from the POC's
    email, so a stale entry would keep answering for the wrong person — and it
    would do so for every user who had already opened that card, which is why
    this sweeps rather than popping a single key.
    """
    for key in [k for k in _thread_cache if k[1] == deal_id]:
        _thread_cache.pop(key, None)


def poc_email(session: Session, deal: Deal) -> Optional[str]:
    """The email the thread query is built from: this DEAL's POC.

    Not the company's primary contact. Two deals with the same client can have
    different counterparts, and the panel has to show the correspondence that
    belongs to the engagement being looked at.
    """
    from models import Contact

    poc = session.get(Contact, deal.poc_id)
    return poc.email if poc else None


def fetch_threads(
    session: Session, deal: Deal, user: Optional[User] = None, limit: int = 20
) -> dict:
    """Every state the panel must handle, all resolved server-side.

    The panel renders whatever comes back and never has to work out which case
    it is in — the alternative is the same five-way decision duplicated in the
    client, drifting from this one.

      disabled        GMAIL_ENABLED is off; the panel is absent entirely
      not_signed_in   auth is on and nobody is signed in
      no_poc_email    this deal's POC has no address to search for
      not_connected   this user has not granted gmail.readonly
      needs_reconnect the stored token is unusable (revoked, expired, or the
                      SECRET_KEY changed) — one click fixes it
      empty           connected and searched, no correspondence yet
      ok              threads
      error           anything else; the drawer still opens
    """
    if not gmail_enabled():
        return {"state": "disabled", "threads": []}
    if user is None:
        return {"state": "not_signed_in", "threads": []}
    address = poc_email(session, deal)
    if not address:
        return {"state": "no_poc_email", "threads": []}
    cred = _credential(session, user.id)
    if cred is None:
        return {"state": "not_connected", "threads": []}

    cache_key = (user.id, deal.id)
    cached = _thread_cache.get(cache_key)
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
                    "last_message_at": datetime.fromtimestamp(last_ms / 1000, tz=timezone.utc).isoformat()
                    if last_ms
                    else None,
                    "message_count": len(messages),
                    "participants": participants,
                    "unread": any("UNREAD" in m.get("labelIds", []) for m in messages),
                }
            )
        # "connected but nothing found" is its own answer. Rendering it as an
        # empty ok-state looks like a failure to load.
        payload = {
            "state": "ok" if threads else "empty",
            "threads": threads,
            "poc_email": address,
        }
        _thread_cache[cache_key] = (time.time(), payload)
        return payload
    except TokenUnreadable:
        log.warning("Refresh token for %s could not be decrypted", user.email or user.id)
        return {
            "state": "needs_reconnect",
            "threads": [],
            "detail": "Stored access could not be read. Reconnecting fixes it.",
        }
    except urllib.error.HTTPError as exc:
        log.warning("Gmail fetch failed for %s: %s", deal.key, exc)
        # 401/403 here means revoked, expired or scope withdrawn — all of which
        # the user resolves by reconnecting, so they get one message, not three.
        state = "needs_reconnect" if exc.code in (401, 403) else "error"
        return {"state": state, "threads": [], "detail": f"Gmail returned {exc.code}"}
    except Exception as exc:  # never let Gmail break the drawer
        log.warning("Gmail fetch failed for %s: %s", deal.key, exc)
        return {"state": "error", "threads": [], "detail": str(exc)}


@router.get("/deals/{deal_id}/threads")
def deal_threads(
    deal_id: str,
    limit: int = Query(20, ge=1, le=50),
    session: Session = Depends(get_session),
    user: Optional[User] = Depends(current_user),
):
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return fetch_threads(session, deal, user, limit)

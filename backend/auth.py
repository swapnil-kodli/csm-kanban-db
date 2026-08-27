"""Sign-in: Google OIDC, server-side sessions, and the domain allowlist.

Two grants, deliberately separate:

  LOGIN     openid + email + profile. Non-sensitive scopes, no Google review,
            no admin dependency. This is all it takes to know who someone is.
  GMAIL     gmail.readonly, requested later and only from the thread panel, per
            user. A restricted scope, and asking for it at sign-in would put a
            scary consent screen in front of people who may never open the
            panel — and would make declining it look like failing to log in.

The session cookie holds an opaque id and nothing else. Google's tokens stay
server-side, so the cookie is a revocable handle rather than a bearer credential
worth stealing.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import timedelta
from typing import Optional

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, Response
from jwt import PyJWKClient
from sqlmodel import Session, select

from db import get_session
from dbtypes import as_utc, utcnow
from models import User, UserSession

log = logging.getLogger("signal.auth")

SESSION_COOKIE = "signal_session"
SESSION_TTL_DAYS = 14

GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
LOGIN_SCOPES = "openid email profile"

# Cached across requests: Google rotates signing keys slowly, and refetching the
# key set on every sign-in would add a network round trip to the critical path
# and hand Google a trivial way to rate-limit logins.
_jwks_client: Optional[PyJWKClient] = None


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(JWKS_URI, cache_keys=True)
    return _jwks_client


def auth_enabled() -> bool:
    """Sign-in is opt-in, exactly like Gmail.

    With it off the app runs as the single bootstrap CSM — which is what every
    demo, every local run and every existing deployment expects. Turning it on
    must be a decision, not something a dependency bump imposes.
    """
    return os.getenv("AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def allowed_domains() -> list[str]:
    raw = os.getenv("ALLOWED_EMAIL_DOMAINS", "") or ""
    return [d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()]


def domain_allowed(email: str) -> bool:
    """Empty allowlist means allow nothing, not allow everything.

    The inverted reading is the classic misconfiguration: someone enables
    sign-in, forgets the variable, and the app quietly accepts every Google
    account on the internet. Failing closed makes that mistake visible on the
    first login attempt instead of never.
    """
    domains = allowed_domains()
    if not domains:
        return False
    return email.lower().rsplit("@", 1)[-1] in domains


def verify_id_token(id_token: str, audience: str, nonce: str) -> dict:
    """Full verification against Google's published keys.

    Every one of these matters, and `email_verified` alone replaces none of
    them — it is a claim inside the very token whose authenticity is in
    question, so trusting it before checking the signature is circular:

      signature  the token is really Google's and unmodified
      iss        it came from Google's issuer, not a look-alike
      aud        it was minted for THIS client, not another app that could
                 otherwise replay its user's token here
      exp        it has not expired
      nonce      it answers the request we actually started, which is what
                 stops a token captured elsewhere being replayed into our flow
    """
    signing_key = _jwks().get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=GOOGLE_ISSUERS[0],
        options={"require": ["exp", "iat", "aud", "iss", "sub"]},
    )
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise jwt.InvalidIssuerError(f"unexpected issuer {claims.get('iss')!r}")
    if not nonce or claims.get("nonce") != nonce:
        raise jwt.InvalidTokenError("nonce mismatch — token does not answer this request")
    if not claims.get("email"):
        raise jwt.InvalidTokenError("no email claim")
    # Checked, but only AFTER the signature — never instead of it.
    if not claims.get("email_verified", False):
        raise jwt.InvalidTokenError("Google has not verified this address")
    return claims


def initials_for(name: str, email: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return (email or "?")[:2].upper()


def upsert_user(session: Session, claims: dict) -> User:
    """Find or create the user by `sub`, then refresh the mutable profile.

    Matched on `sub` first and email only as a fallback, so a Workspace address
    change updates the existing row instead of stranding it. The email fallback
    exists to adopt the bootstrap CSM row on the first real sign-in rather than
    leaving a duplicate beside it.
    """
    sub, email = claims["sub"], claims["email"]
    user = session.exec(select(User).where(User.google_sub == sub)).first()
    if user is None:
        user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        # The bootstrap CSM has no google_sub and no email; adopt it rather than
        # create a second owner that every existing company does not point at.
        user = session.exec(
            select(User).where(User.google_sub == None, User.email == None)  # noqa: E711
        ).first()
    if user is None:
        user = User(name=claims.get("name") or email, initials="", avatar_color="#111111")

    user.google_sub = sub
    user.email = email
    user.name = claims.get("name") or user.name or email
    user.initials = initials_for(user.name, email)
    user.avatar_url = claims.get("picture")
    user.is_active = True
    user.last_login_at = utcnow()
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def start_session(session: Session, user: User, response: Response, user_agent: str = "") -> UserSession:
    row = UserSession(
        user_id=user.id,
        expires_at=utcnow() + timedelta(days=SESSION_TTL_DAYS),
        user_agent=(user_agent or "")[:200] or None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    response.set_cookie(
        SESSION_COOKIE,
        row.id,
        httponly=True,     # unreadable from JS, so XSS cannot exfiltrate it
        secure=True,       # HTTPS only
        samesite="lax",    # survives the OAuth redirect back from Google;
                           # "strict" would drop the cookie on that navigation
                           # and land the user straight back on the login page
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        path="/",
    )
    return row


def end_session(session: Session, session_id: Optional[str], response: Response) -> None:
    if session_id:
        row = session.get(UserSession, session_id)
        if row is not None:
            session.delete(row)
            session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


def _bootstrap_user(session: Session) -> Optional[User]:
    return session.exec(select(User)).first()


def current_user(
    request: Request,
    signal_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),
) -> Optional[User]:
    """The signed-in user, or the single bootstrap CSM when auth is off.

    Returns None rather than raising, because almost every endpoint here is
    perfectly usable without knowing who is asking. Only the Gmail panel needs a
    real identity, and it says so itself instead of making the whole board 401.
    """
    if not auth_enabled():
        return _bootstrap_user(session)
    if not signal_session:
        return None
    row = session.get(UserSession, signal_session)
    if row is None:
        return None
    if as_utc(row.expires_at) < utcnow():
        session.delete(row)
        session.commit()
        return None
    user = session.get(User, row.user_id)
    return user if (user and user.is_active) else None


def require_user(user: Optional[User] = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return user

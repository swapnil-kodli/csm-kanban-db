"""Encryption for the one secret this app stores at rest: the Gmail refresh token.

Why only that one. An access token expires in an hour and is re-obtainable; a
refresh token does not expire and grants a user's mailbox until it is revoked.
If the database file is copied — a backup, a volume snapshot, a laptop — every
other row is business data, but a plaintext refresh token is a live credential.

Fernet (AES-128-CBC + HMAC-SHA256, from `cryptography`) rather than something
hand-rolled: authenticated, versioned, and a wrong key fails loudly instead of
returning plausible garbage.

THE KEY IS NOT OPTIONAL, and it is deliberately not auto-generated on boot.
An auto-generated key would live in memory only, so every restart would silently
invalidate every stored grant and send users back through consent with no
explanation. Better to refuse to start.
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

_ENV = "SECRET_KEY"


class MissingSecretKey(RuntimeError):
    pass


def _derive(secret: str) -> bytes:
    """A urlsafe-base64 32-byte key from whatever the operator typed.

    Accepts a real Fernet key verbatim; anything else is hashed to length so a
    human-typed passphrase works without a separate key-generation step. SHA-256
    with no salt is right here and only here: the input is a high-entropy
    deployment secret, not a user password, and the key has to be reproducible
    across restarts from the same env var alone.
    """
    raw = secret.strip().encode()
    try:
        if len(base64.urlsafe_b64decode(raw)) == 32:
            return raw
    except Exception:
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


def _fernet() -> Fernet:
    secret = (os.getenv(_ENV) or "").strip()
    if not secret:
        raise MissingSecretKey(
            f"{_ENV} is not set. It encrypts stored Gmail refresh tokens, and a "
            "generated-per-boot key would silently invalidate every grant on "
            "restart. Set it in backend/.env — `python -c \"import secrets; "
            "print(secrets.token_urlsafe(32))\"` produces a good one."
        )
    return Fernet(_derive(secret))


def secret_key_configured() -> bool:
    return bool((os.getenv(_ENV) or "").strip())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """None when the value cannot be read.

    A rotated or mistyped SECRET_KEY makes every stored token undecryptable.
    Returning None lets the caller degrade to "reconnect Gmail" — which is
    recoverable in one click — instead of raising a 500 that takes the drawer
    and the board down with it.
    """
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, MissingSecretKey, ValueError):
        return None

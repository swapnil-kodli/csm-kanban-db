"""Derivation of the Jira-style account key (SBP-01, ACM-02, ...).

The key is the client's stable public identifier: it prints on the card, it is
what someone types into search, and it is what the hard-delete confirmation asks
you to type back. So it has three properties, in this order:

  1. Unique. `account.key` carries a unique index. A duplicate is not a cosmetic
     problem, it is a 500 at insert time.
  2. Immutable. Nothing in the API can change it after create. Renaming a client
     from "Sunbeam" to "Sunbeam Retail" must not orphan a filter or a bookmark.
  3. Derived, not typed. Nobody should have to invent one.

CASE IS THE SUBTLE PART. SQLite's unique index on a TEXT column is
case-sensitive by default and so is Postgres's, which means 'SBP-01' and
'sbp-01' are two different keys to the database but one key to a human — and a
board with both on it is indistinguishable nonsense. Every key is therefore
normalised to upper case on generation, and uniqueness is checked against the
upper-cased set rather than against a raw equality query, so the check and the
constraint agree. A `LIKE`/`ilike` probe would not be enough: it would find a
clash but still let a differently-cased one through on a race.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from sqlmodel import Session, select

from models import Account

# Three letters is the house style (SBP, ACM). Two is allowed for a one-word,
# short name; anything shorter is padded from the alphabet rather than left
# ambiguous.
PREFIX_LEN = 3
FALLBACK_PREFIX = "CLI"
_WORD = re.compile(r"[A-Za-z0-9]+")


def prefix_for(name: str) -> str:
    """Initials of the first words, falling back to the leading letters.

    "Sunbeam Retail Partners" -> SRP
    "Sunbeam"                 -> SUN   (one word: take its first letters)
    "3M"                      -> 3M    (short, but unambiguous; padded below)
    ""                        -> CLI
    """
    words = _WORD.findall(name or "")
    if not words:
        return FALLBACK_PREFIX

    if len(words) >= 2:
        candidate = "".join(w[0] for w in words[:PREFIX_LEN])
    else:
        candidate = words[0][:PREFIX_LEN]

    candidate = candidate.upper()
    if len(candidate) < 2:
        candidate = (candidate + FALLBACK_PREFIX)[:PREFIX_LEN]
    return candidate


def _taken(session: Session) -> set[str]:
    """Every key already in use, upper-cased.

    Archived clients are INCLUDED on purpose. A soft-deleted client can be
    restored, and restoring it must not collide with a key handed out while it
    sat in Trash.
    """
    return {
        (k or "").upper()
        for k in session.exec(select(Account.key)).all()
    }


def next_key(session: Session, name: str, extra_taken: Optional[Iterable[str]] = None) -> str:
    """First free `PREFIX-NN` for this name. Upper-cased, zero-padded to two."""
    taken = _taken(session)
    if extra_taken:
        taken |= {k.upper() for k in extra_taken}

    prefix = prefix_for(name)
    n = 1
    while True:
        candidate = f"{prefix}-{n:02d}"
        if candidate not in taken:
            return candidate
        n += 1
        if n > 9999:  # pragma: no cover - a book this size is not a real case
            raise RuntimeError(f"no free key for prefix {prefix}")

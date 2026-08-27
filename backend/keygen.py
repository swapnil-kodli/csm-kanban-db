"""Derivation of the Jira-style keys: Company (PRE-04) and Deal (PRE-04-01).

A key is the stable public identifier: it prints on the card, it is what someone
types into search, and it is what the hard-delete confirmation asks you to type
back. So it has three properties, in this order:

  1. Unique. Both `company.key` and `deal.key` carry a unique index. A duplicate
     is not a cosmetic problem, it is a 500 at insert time.
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

from models import Company, Deal

# Three letters is the house style (SBP, ACM). Two is allowed for a one-word,
# short name; anything shorter is padded from the alphabet rather than left
# ambiguous.
PREFIX_LEN = 3
FALLBACK_PREFIX = "CLI"
_WORD = re.compile(r"[A-Za-z0-9]+")


def prefix_for(name: str) -> str:
    """Three characters, always. The house style is uniformly three (SBP, PRE,
    NFS), and a shorter prefix both looks wrong beside them and collides far
    sooner — two-letter prefixes exhaust their -01..-99 range across a book
    much faster than three-letter ones.

    Three cases, because two words is the common one and initials alone are too
    thin for it:

      3+ words   initials of the first three     Next Foot Steps      -> NFS
      2 words    two letters of the first, then  Brick Mentor         -> BRM
                 one of the second               Square Yards         -> SQY
      1 word     its first three letters         Prestige             -> PRE

    Padded from a fallback when the name is too short to yield three, so the
    output length never varies.

      "3M"  -> 3MC        "" -> CLI
    """
    words = _WORD.findall(name or "")
    if not words:
        return FALLBACK_PREFIX

    if len(words) >= 3:
        candidate = "".join(w[0] for w in words[:PREFIX_LEN])
    elif len(words) == 2:
        candidate = words[0][:2] + words[1][0]
    else:
        candidate = words[0][:PREFIX_LEN]

    candidate = candidate.upper()
    # Never shorter than three: pad rather than emit a stubby prefix.
    return (candidate + FALLBACK_PREFIX)[:PREFIX_LEN]


def _taken_company_keys(session: Session) -> set[str]:
    """Every company key in use, upper-cased.

    Archived companies are INCLUDED on purpose. A soft-deleted company can be
    restored, and restoring it must not collide with a key handed out while it
    sat in Trash.
    """
    return {(k or "").upper() for k in session.exec(select(Company.key)).all()}


def next_company_key(
    session: Session, name: str, extra_taken: Optional[Iterable[str]] = None
) -> str:
    """First free `PREFIX-NN` for this name. Upper-cased, zero-padded to two."""
    taken = _taken_company_keys(session)
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


def next_deal_key(session: Session, company: Company) -> str:
    """`{company.key}-NN`, sequential within the company.

    Derived from the highest suffix already issued rather than from a count, so
    deleting the middle deal of three does not hand the next one a key that is
    already on someone's calendar invite. Deals in every outcome and every
    archive state are counted, for the same reason.

    The trailing number IS reusable after a hard delete of the highest deal —
    the same tradeoff company keys already make, and hard delete is the one
    operation that requires typing the key back precisely because it is final.
    """
    prefix = company.key.upper()
    highest = 0
    for key in session.exec(select(Deal.key).where(Deal.company_id == company.id)).all():
        suffix = (key or "").upper().removeprefix(prefix + "-")
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{prefix}-{highest + 1:02d}"

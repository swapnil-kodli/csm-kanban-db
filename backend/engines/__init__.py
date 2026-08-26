"""Scoring engines: health, attention, alerts, PNL.

STANDING PRINCIPLE — an unmaintained input degrades a feature to OFF, never to WRONG
------------------------------------------------------------------------------------
Wherever an input can be absent, absence means "unknown" and must be neutral. It
must never be scored as a bad value, and never silently substituted with one.

Applied in three places so far, and the rule for every future one:

  * `margin_pct` is None when nothing has been billed. It renders as an em dash
    on a neutral token, does not fire `margin_negative`, and contributes 0 to
    `margin_risk` — an engagement with no invoices is not a commercial emergency.

  * A column with `stalled_after_days = NULL` does not track stalling at all.
    That is how a terminal column opts out, rather than a second flag saying the
    same thing. An account whose column key no longer exists falls back to the
    entry column and is logged by name, never dropped.

  * `last_contact_at` is hand-maintained since activity logging was removed. When
    it is unset the engagement component scores neutral, `no_contact` does not
    fire, and `neglect_weight` is 0.

The failure this prevents: a field nobody fills in quietly turning every account
red, every badge on, and every ranking meaningless — noise indistinguishable from
signal. A feature that is off is obvious and recoverable. A feature that is
confidently wrong is neither.

Corollary: when you delete a write path, find every reader. A reader left pointed
at a source nothing writes does not freeze — it collapses to the worst value the
formula allows.
"""

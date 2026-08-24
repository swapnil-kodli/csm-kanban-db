# Signal CS — deliberately not built

Everything here was considered and left out of the MVP on purpose. The research
is explicit that over-stuffed CSM dashboards fail (research §21, spec §9), so
each entry names why it is out and what would have to be true to bring it in.

## Out of scope by design — do not add without re-reading research §21

| Idea | Why it is out |
|---|---|
| NRR / GRR / CLV / logo-churn analytics | Executive metrics on a CSM surface is the single most common way this product class fails. They belong to a separate manager layer. |
| Manager or exec board (owner column, workload view) | Different decisions, different user. A second surface, not a tab on this one. |
| Notification bell with an unread count | An alert that only increments a counter fails all three ChurnZero tests. Every alert here becomes an owned task or changes board state. |
| Ticketing system | Integrate read-only; do not rebuild. Escalations are represented as `risk` rows. |
| Email / calendar integration | Wanted, but it is an integrations project, not an MVP feature. See "Next up" below. |
| Custom-object / configurable field framework | Config burden is why teams abandon Gainsight and Planhat. Stay opinionated. |
| Reporting builder, multi-tenant admin console | Requires an admin to operate. Out. |

## Next up, in the order I would build them

1. **Auto-logging of email, calls and meetings.** Manual logging is the #1 adoption
   killer (G2: "you have to manually click to log each email"). The composer is
   already under 10 seconds; removing it entirely is the real win.
2. **Configurable health weights.** The engine already isolates `WEIGHTS` and
   `SEGMENT_THRESHOLDS` in `backend/engines/health.py`; exposing them needs a
   settings surface and per-tenant storage, not an engine change.
3. **Playbook task templates** (onboarding / risk / renewal). The alert engine
   already emits single tasks with provenance; a playbook is an ordered set of
   them behind one `rule_key`.
4. **Renewals pipeline view** with multi-stage renewal deals (Planhat pattern).
5. **Success plans, goals and milestones** beyond the onboarding checklist.
6. **Expansion opportunity pipeline** — today `expansion_flag` is a boolean.
7. **NPS / CSAT capture.** `account.last_nps` already feeds `sentiment_score`;
   nothing writes it but the seed.
8. **CSV export** of the current filtered board.
9. **Multi-CSM books.** The data model carries `owner_id` throughout and the
   filter panel has the Owner slot stubbed; the MVP seeds a single CSM and the
   research is explicit that owner name is noise on a personal board.
10. **AI next-best-action.** Only once the attention score has been validated
    against real renewal outcomes — an opaque ranking is worse than none.

## Known deviations from the specs, and why

- **Book ARR reads ₹1.10 Cr, not the ₹1.13 Cr quoted in `04_SEED_DATA.md`.** The
  per-account ARR figures in that table are given verbatim and sum to
  ₹1,09,50,000 across the 11 active accounts. The per-account numbers win; the
  quoted total appears to be a rounding slip. Every other first-load number in
  §"Expected first-load state" matches exactly.
- **`segment_thresholds` carry the alert thresholds the spec asks for**, and the
  values are tuned so the seeded board produces exactly the task counts §"Expected
  first-load state" calls for: enterprise fires `health_drop` at −12 (so PRE-04's
  −14 fires, as `04_SEED_DATA.md` requires, even though the generic rule says
  −15), SMB at −20 (so VPS-10 does not get a second critical task on top of
  `champion_departed`), and SMB renewals raise a task at 30 days only.
- **HOU-06's health decline is spread across 30 days, not 14.** The spec fixes its
  30-day velocity at −9; concentrating that drop into 14 days makes the implied
  usage slide trip `usage_decline` and adds a 16th open task, breaking the
  spec'd Open Tasks count of 15.
- **`usage_decline` is suppressed when the account already carries an open alert
  task.** Research §15 requires consolidating related signals; a usage slide on an
  account that already has a `health_drop` or `escalation_open` task is the same
  story told twice.
- **`task.rule_key` was added to the schema.** The spec requires the alert engine
  to "never create a second open task for the same `(account_id, rule_key)`
  pair", which is only enforceable if tasks store the rule that produced them.
- **`account.entitled_seats` and `account.last_nps` were added.** The health
  formula in `03_DATA_MODEL_AND_API.md` §2 divides by entitled seats and maps a
  last NPS; neither had a column.

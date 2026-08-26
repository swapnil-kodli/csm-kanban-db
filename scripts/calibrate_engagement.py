"""Calibrate the recency curve so rebuilding engagement does not move health bands.

Engagement was a three-part composite (recency, meeting cadence, executive
touch) read from the activity table. With activity logging removed it becomes
recency alone, read from the hand-maintained `last_contact_at`. That is a
thinner signal by design — but it must not silently re-band the whole book.

This measures a REAL database (usage, risks and sentiment untouched) under the
old and new formulas and reports the health delta per account. Seeded health is
calibration-invariant, because the seed back-solves usage from a target curve,
so only a migrated database tells the truth.

    python scripts/calibrate_engagement.py <path-to.db> [CEIL] [SLOPE]
"""
import sys, sqlite3, statistics
from datetime import datetime

DB = sys.argv[1]
CEIL = float(sys.argv[2]) if len(sys.argv) > 2 else 78.0
SLOPE = float(sys.argv[3]) if len(sys.argv) > 3 else 2.4
WEIGHTS = {"usage": 0.40, "engagement": 0.25, "support": 0.20, "sentiment": 0.15}
GRACE = {"pilot": 3, "customer": 7}


def band(score):
    return ("healthy" if score >= 75 else "watch" if score >= 55
            else "at_risk" if score >= 35 else "critical")


c = sqlite3.connect(DB)
now = datetime.utcnow()
rows = []
for key, mode, lc, usage, eng_old, sup, sent in c.execute("""
    SELECT a.key, a.mode, a.last_contact_at, h.usage, h.engagement, h.support, h.sentiment
    FROM account a JOIN healthsnapshot h ON h.account_id = a.id
    WHERE h.captured_on = (SELECT max(captured_on) FROM healthsnapshot WHERE account_id = a.id)
    ORDER BY a.key"""):
    if lc is None:
        eng_new = 70.0                      # unset is neutral, never a penalty
    else:
        days = max(0, (now - datetime.fromisoformat(lc)).days)
        eng_new = max(0.0, min(100.0, CEIL - max(0, days - GRACE.get(mode, 7)) * SLOPE))
    def compose(e):
        return round(WEIGHTS["usage"] * usage + WEIGHTS["engagement"] * e
                     + WEIGHTS["support"] * sup + WEIGHTS["sentiment"] * sent)
    rows.append((key, eng_old, round(eng_new), compose(eng_old), compose(eng_new)))

print(f"  CEIL={CEIL}  SLOPE={SLOPE}\n")
print("  %-8s %-13s %-13s %s" % ("acct", "engagement", "health", "band"))
moved = 0
for key, eo, en, ho, hn in rows:
    shift = "" if band(ho) == band(hn) else f"  {band(ho)} -> {band(hn)}  BAND MOVED"
    if shift:
        moved += 1
    print("  %-8s %3d -> %3d    %3d -> %3d    %s%s" % (key, eo, en, ho, hn, band(hn), shift))
print()
print("  mean engagement %.1f -> %.1f" % (
    statistics.mean(r[1] for r in rows), statistics.mean(r[2] for r in rows)))
print("  mean health     %.1f -> %.1f" % (
    statistics.mean(r[3] for r in rows), statistics.mean(r[4] for r in rows)))
print("  max |delta|     %d points" % max(abs(r[4] - r[3]) for r in rows))
print("  bands moved     %d of %d" % (moved, len(rows)))
sys.exit(1 if moved else 0)

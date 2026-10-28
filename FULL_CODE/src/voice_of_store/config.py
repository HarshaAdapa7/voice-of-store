"""All tunable constants in one place. No dates, ids or paths are hard-coded here."""
from __future__ import annotations

ISSUE_TYPES = [f"IT{i:02d}" for i in range(1, 31)] + ["NI01", "NI02", "NI03"]
NON_ISSUE = ("NI01", "NI02", "NI03")
SEVERITIES = ("low", "medium", "high", "critical")
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
STORELESS_OK = tuple(f"IT{i}" for i in range(23, 30))  # order/app/payment/refund/loyalty issues need no store

PRED_COLS = ["feedback_id", "issue_type_id", "severity", "actionable"]
FLAG_COLS = ["as_of_week_start", "store_id", "issue_type_id", "confidence", "evidence_feedback_ids"]

# classifier
CHAR_NGRAM = (2, 5)
WORD_NGRAM = (1, 2)
C_ISSUE = 10.0
C_SEVERITY = 5.0
C_ACTIONABLE = 5.0
SEED = 7

# detector
HISTORY_WEEKS = 14        # weeks of history used for a store's own baseline
PRIOR_STRENGTH = 6.0      # Gamma prior strength, in expected reports (shrinks a store toward the chain rate)
ALT_MULTIPLIER = 3.0      # CUSUM alternative: the store's rate is this many times its baseline
LLR_THRESHOLD = 5.0       # flag when the cumulative log-likelihood ratio reaches this
MIN_WEEK_COUNT = 2        # a flag needs >= 2 reports this week (the evidence rule needs 2 valid ids)
MIN_BASE_WEEKS = 3        # weeks of history required before any flag is raised
COOLDOWN_WEEKS = 2        # do not re-flag the same store and issue type for this many weeks
MAX_FLAGS_PER_WEEK = 3
EVIDENCE_MAX = 5

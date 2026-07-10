"""Central configuration and TTB reference constants.

Everything tunable lives here so the review rules and model choice are easy to
find and audit. Values can be overridden with environment variables.
"""
from __future__ import annotations

import os

# --- Model -----------------------------------------------------------------
# Default to the most capable model. The 5-second latency target from the
# stakeholder interviews is a real constraint (see README "Assumptions &
# trade-offs"): for the fastest turnaround set LABEL_MODEL to a faster tier,
# e.g. "claude-sonnet-5" or "claude-haiku-4-5".
DEFAULT_MODEL: str = os.getenv("LABEL_MODEL", "claude-opus-4-8")

# Extraction output is a small structured record, so a modest cap keeps
# latency low while leaving headroom.
MAX_TOKENS: int = int(os.getenv("LABEL_MAX_TOKENS", "1024"))

# How many labels to analyse concurrently in batch mode. Kept conservative to
# stay well under API rate limits; raise it if your account's limits allow.
BATCH_MAX_WORKERS: int = int(os.getenv("BATCH_MAX_WORKERS", "6"))

# --- Matching thresholds ---------------------------------------------------
# Text fields (brand, class/type) that normalise to the same string PASS.
# Between these thresholds we flag for human REVIEW rather than auto-fail —
# this is Dave's "STONE'S THROW vs Stone's Throw is obviously the same" rule.
TEXT_REVIEW_THRESHOLD: float = 0.82

# ABV numeric tolerance (percentage points).
ABV_TOLERANCE: float = 0.1

# Government-warning wording similarity required to be considered a match.
# The statement is mandated verbatim, so this is strict.
WARNING_WORDING_THRESHOLD: float = 0.97

# --- TTB reference ---------------------------------------------------------
# The mandatory Government Health Warning, 27 CFR 16.21, verbatim.
# This is the single source of truth we compare every label against.
CANONICAL_GOVERNMENT_WARNING: str = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should "
    "not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your "
    "ability to drive a car or operate machinery, and may cause health "
    "problems."
)

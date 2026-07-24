"""Static configuration: profile presets and field-value distributions.

Distribution *shapes* here are defaults derived from the existing 180 seed
Cases in Prime_SDO (see NOTES.md "Field templates captured from the existing
180 Cases"). Org-specific *identifiers* (User Ids, BusinessHours Id, Account/
Contact Ids, etc.) are never hardcoded here -- see org_context.py, which
discovers them at runtime so this tool works against any org.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    name: str
    case_count: int
    lookback_months: int
    description: str


PROFILES = {
    "quick": Profile(
        name="quick",
        case_count=200,
        lookback_months=3,
        description="Small smoke-test volume for validating the tool against an org before a full run.",
    ),
    "standard": Profile(
        name="standard",
        case_count=2500,
        lookback_months=24,
        description="Default volume this project was scoped around.",
    ),
    "enterprise": Profile(
        name="enterprise",
        case_count=10000,
        lookback_months=36,
        description="Larger volume for a 'mature org' demo story.",
    ),
}

DEFAULT_PROFILE = "standard"

# Batch tag prefix used for External_ID__c on every generated Case, and as the
# run manifest / undo lookup key. Format: f"{BATCH_PREFIX}{run_id}-{seq}"
BATCH_PREFIX = "SI-GEN-"

# --- Case field distributions (weights sum to 1.0 within each dict) ---

ORIGIN_WEIGHTS = {
    "Chat": 0.50,
    "Community": 0.055,
    "Email": 0.10,
    "Mobile Device": 0.045,
    "Phone": 0.15,
    "Website": 0.045,
    "Facebook": 0.022,
    "Instagram": 0.011,
    "LinkedIn": 0.011,
    "Twitter": 0.05,
    "Case": 0.006,
    "Text": 0.005,
}

# Calendar-month multipliers layered on top of ORIGIN_WEIGHTS, so channel mix
# wobbles with the season (e.g. phone support spikes over the holidays,
# social/chat volume dips) rather than being flat all year. Origins not
# listed for a given month default to 1.0 (no adjustment).
ORIGIN_SEASONAL_MULTIPLIER = {
    "Phone": {11: 1.3, 12: 1.5, 1: 1.25},       # holiday call-volume spike
    "Chat": {11: 0.9, 12: 0.85, 1: 0.9},
    "Twitter": {6: 1.2, 7: 1.3, 8: 1.2},        # summer social bump
    "Facebook": {6: 1.15, 7: 1.2, 8: 1.15},
    "Email": {12: 1.15, 1: 1.1},
}

# Slow multi-month drift applied across the lookback window, oldest Case to
# newest, so the channel mix visibly trends over the 24-month history (e.g.
# a gradual shift toward Chat and away from Phone) instead of being static
# generation to generation. Values are (oldest_multiplier, newest_multiplier);
# origins not listed default to (1.0, 1.0) -- no trend.
ORIGIN_TREND_RANGE = {
    "Chat": (0.75, 1.25),
    "Phone": (1.3, 0.8),
    "Website": (0.85, 1.15),
}

# None (null) is included explicitly as a weighted option to match the ~45%
# null rate observed on the existing 180 Cases.
TYPE_WEIGHTS = {
    None: 0.45,
    "General": 0.183,
    "Account Support": 0.211,
    "Product Support": 0.15,
    "Technical Issue": 0.006,
}

PRIORITY_WEIGHTS = {
    "Critical": 0.044,
    "High": 0.156,
    "Low": 0.133,
    "Medium": 0.667,
}

REASON_WEIGHTS = {
    None: 0.644,
    "Problem Resolved": 0.289,
    "New problem": 0.033,
    "Feature Request": 0.022,
    "Documentation Issue": 0.006,
    "Mail delivery issue": 0.006,
}

# Fraction of the cohort that ends up closed vs still open. Open Cases skew
# toward recent CreatedDates (handled in the generator, not here).
CLOSED_FRACTION = 0.85

# Status picklist for open (non-closed) Cases, weighted. "Escalated" is a
# Status value independent of the IsEscalated boolean -- see NOTES.md.
OPEN_STATUS_WEIGHTS = {
    "New": 0.55,
    "Working": 0.25,
    "Waiting on Customer": 0.12,
    "Reply Received": 0.05,
    "Escalated": 0.03,
}

# The Status value used for closed Cases. Confirmed via describe: Case.Status
# picklist is New/Reply Received/Working/Waiting on Customer/Escalated/Closed.
CLOSED_STATUS = "Closed"

# Fraction of Cases getting IsEscalated=true, drawn independently of Status.
ESCALATED_FRACTION = 0.08

# Priority -> mean/stddev close lag in hours (business-hours-ish; the
# semantic model's BH_TimeToClose_clc will translate wall-clock ClosedDate
# into business hours on its own, so this is calendar-time lag, not BH lag).
PRIORITY_CLOSE_LAG_HOURS = {
    "Critical": (6, 3),
    "High": (18, 8),
    "Low": (60, 30),
    "Medium": (30, 15),
}

# Of the closed Cases, the fraction routed through Path B (insert Open, then
# a follow-up UPDATE to Closed) purely to generate a real CaseHistory Status
# row for Avg Time to 1st Close. These Cases' ClosedDate will read as "now"
# (the moment the update ran) rather than a realistic backdated value -- see
# NOTES.md "ClosedDate vs CaseHistory conflict". Kept small deliberately so
# Avg Time to Close's variance across the full cohort stays intact.
PATH_B_FRACTION = 0.15

# Fraction of FCR-eligible closed Cases (Path A, since Path B's ClosedDate is
# unreliable for time-based tiles) that get exactly one EmailMessage attached.
EMAIL_ATTACH_FRACTION = 0.6

# Fraction of closed Cases that get a CaseArticle (Knowledge attach) link.
KNOWLEDGE_ATTACH_FRACTION = 0.4

# Fraction of all generated Cases that get a call-logging Task (WhatId ->
# Case) for CRMA's ServiceActivity dataset.
TASK_ATTACH_FRACTION = 0.35

# CSAT__c is a Number field, 0-100 scale (confirmed via describe + observed
# existing values). Modeled as a rough bell skewed toward satisfied.
CSAT_MEAN = 82
CSAT_STDDEV = 12
CSAT_MIN = 30
CSAT_MAX = 100

# Extra CRMA-specific Case fields worth setting for realism (see NOTES.md
# CRMA track). Product_Name__c is excluded: confirmed createable=false.
TYPE_OF_SUPPORT_WEIGHTS = {
    None: 0.53,
    "Standard": 0.30,
    "Premium": 0.17,
}

# --- Owner (service rep) pool + per-rep performance variance ---

# Cap the pool of Case owners so the generated cohort reads as a small,
# real team rather than being spread across every active User in the org
# (which would include admins/integration users and dilute any per-rep
# story). org_context.py discovers the real existing-Case owner pool first;
# this is the ceiling applied on top of that.
MAX_OWNER_POOL_SIZE = 10

# Each rep in the capped pool gets a randomly assigned performance tier so
# "Service Rep Performance" / "My Service Performance" tiles show some reps
# closing faster and with higher CSAT than others, instead of every rep
# looking statistically identical. Multipliers apply to close lag (lower is
# faster) and to CSAT mean shift (added directly to config.CSAT_MEAN).
REP_PERFORMANCE_TIER_WEIGHTS = {
    "top": 0.2,
    "average": 0.6,
    "below_average": 0.2,
}
REP_TIER_CLOSE_LAG_MULTIPLIER = {
    "top": 0.65,
    "average": 1.0,
    "below_average": 1.5,
}
REP_TIER_CSAT_SHIFT = {
    "top": 8,
    "average": 0,
    "below_average": -12,
}

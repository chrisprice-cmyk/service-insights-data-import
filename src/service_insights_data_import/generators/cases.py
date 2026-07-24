"""The Case generator.

Builds the historical cohort per NOTES.md "Historical Case cohort —
generation design" and resolves the hybrid Path A/B close-date design per
NOTES.md "ClosedDate vs CaseHistory conflict — resolved":

- Path A (majority of closed Cases): inserted directly with Status=Closed +
  a backdated ClosedDate in the same insert call. Accurate "Avg Time to
  Close" variance; no CaseHistory Status row.
- Path B (a smaller subset of closed Cases, config.PATH_B_FRACTION):
  inserted as Status=New with no ClosedDate, then flagged for a follow-up
  Status=Closed UPDATE (issued later by the loader through a BatchGuard).
  That update produces the CaseHistory row "Avg Time to 1st Close" needs, at
  the cost of ClosedDate reading as "now" instead of backdated.

This module only builds Python data structures -- no Salesforce calls happen
here. The loader (load.py) is responsible for actually inserting
`insert_rows` and then issuing the Path B status-flip update.

Two other realism layers live here:
- **Per-rep performance tiers**: each owner in org_ctx.owner_ids (already
  capped to a small team, see config.MAX_OWNER_POOL_SIZE) gets one stable
  tier (top/average/below_average) for the whole run, shifting both their
  close-lag speed and their Cases' CSAT mean -- so Service Rep Performance
  tiles show real spread between reps instead of everyone looking the same.
- **Channel (Origin) seasonality + trend**: Origin weights are adjusted per
  Case by calendar-month multipliers (config.ORIGIN_SEASONAL_MULTIPLIER) and
  a slow multi-month drift across the lookback window
  (config.ORIGIN_TREND_RANGE), so channel mix visibly varies month to month
  and trends over the generated history instead of being flat.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .. import config
from ..batch import case_external_id
from ..sampling import clamp, weighted_choice

SEASONALITY_MULTIPLIER = {
    12: 0.75,  # Dec dip
    1: 1.15,   # Jan bump
    9: 1.15,   # Sep bump
}

SUBJECT_TEMPLATES = {
    "Account Support": [
        "Please expedite my order.",
        "Need to update billing details on my account.",
        "Question about my account renewal.",
    ],
    "Product Support": [
        "Turbine not reaching operating speed",
        "Product stopped responding after latest update",
        "How do I configure the new device?",
    ],
    "General": [
        "How do I obtain your annual report?",
        "General question about your services.",
        "Requesting a callback at a convenient time.",
    ],
    "Technical Issue": [
        "Integration failing with authentication error",
        "System returning unexpected error code",
    ],
    None: [
        "Need some help with my recent case.",
        "Following up on an earlier request.",
    ],
}


@dataclass
class CaseCohort:
    run_id: str
    insert_rows: list = field(default_factory=list)
    seqs: list = field(default_factory=list)
    path_b_seqs: set = field(default_factory=set)
    email_seqs: set = field(default_factory=set)
    knowledge_seqs: set = field(default_factory=set)
    task_seqs: set = field(default_factory=set)
    created_dates: dict = field(default_factory=dict)
    closed_dates: dict = field(default_factory=dict)
    is_closed: dict = field(default_factory=dict)


def _seasonal_created_date(lookback_months: int, now: datetime, rng: random.Random) -> datetime:
    month_offsets = list(range(lookback_months))
    weights = []
    for offset in month_offsets:
        approx_month = ((now.month - 1 - offset) % 12) + 1
        weights.append(SEASONALITY_MULTIPLIER.get(approx_month, 1.0))
    offset_months = rng.choices(month_offsets, weights=weights, k=1)[0]
    anchor = now - timedelta(days=offset_months * 30)
    jitter_days = rng.uniform(0, 30)
    jitter_seconds = rng.uniform(0, 86400)
    return anchor - timedelta(days=jitter_days, seconds=jitter_seconds)


def _decide_closed(age_days: float, rng: random.Random) -> bool:
    """Open Cases skew toward recent CreatedDates -- an 18-month-old Case
    still New would look broken, so recent Cases are far less likely closed."""
    if age_days < 3:
        p_closed = 0.05
    elif age_days < 14:
        p_closed = config.CLOSED_FRACTION * (age_days / 14)
    else:
        p_closed = config.CLOSED_FRACTION
    return rng.random() < p_closed


def _close_lag_hours(priority: str, age_hours: float, tier: str, rng: random.Random) -> float:
    mean, stddev = config.PRIORITY_CLOSE_LAG_HOURS[priority]
    multiplier = config.REP_TIER_CLOSE_LAG_MULTIPLIER[tier]
    lag = rng.gauss(mean * multiplier, stddev * multiplier)
    lag = clamp(lag, 1.0, age_hours - 1.0 if age_hours > 2 else age_hours)
    return max(lag, 1.0)


def _assign_rep_tiers(owner_ids: list, rng: random.Random) -> dict:
    """One stable performance tier per owner for the whole run, so a given
    rep is consistently faster/slower and higher/lower CSAT across every
    Case they own -- not re-rolled per Case."""
    return {owner_id: weighted_choice(config.REP_PERFORMANCE_TIER_WEIGHTS, rng) for owner_id in owner_ids}


def _origin_weights_for(created: datetime, lookback_months: int, now: datetime) -> dict:
    """ORIGIN_WEIGHTS adjusted by calendar-month seasonality and a slow
    multi-month trend across the lookback window, so channel mix isn't flat
    across the whole generated history."""
    age_months = (now - created).days / 30.0
    trend_progress = clamp(1.0 - (age_months / max(lookback_months, 1)), 0.0, 1.0)  # 0=oldest, 1=newest

    weights = {}
    for origin, base_weight in config.ORIGIN_WEIGHTS.items():
        seasonal = config.ORIGIN_SEASONAL_MULTIPLIER.get(origin, {}).get(created.month, 1.0)
        oldest_mult, newest_mult = config.ORIGIN_TREND_RANGE.get(origin, (1.0, 1.0))
        trend = oldest_mult + (newest_mult - oldest_mult) * trend_progress
        weights[origin] = base_weight * seasonal * trend
    return weights


def _account_contact_pair(org_ctx, rng: random.Random):
    if rng.random() > 0.53:  # ~96/180 non-null rate observed on seed data
        return None, None
    accounts_with_contacts = [a for a in org_ctx.account_ids if org_ctx.contact_ids_by_account.get(a)]
    if not accounts_with_contacts:
        return None, None
    account_id = rng.choice(accounts_with_contacts)
    contact_id = rng.choice(org_ctx.contact_ids_by_account[account_id])
    return account_id, contact_id


def generate_cohort(profile, org_ctx, run_id: str, seed: int | None = None) -> CaseCohort:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    cohort = CaseCohort(run_id=run_id)
    rep_tiers = _assign_rep_tiers(org_ctx.owner_ids, rng)

    for seq in range(1, profile.case_count + 1):
        created = _seasonal_created_date(profile.lookback_months, now, rng)
        age_days = (now - created).total_seconds() / 86400.0
        age_hours = age_days * 24.0

        case_type = weighted_choice(config.TYPE_WEIGHTS, rng)
        priority = weighted_choice(config.PRIORITY_WEIGHTS, rng)
        origin_weights = _origin_weights_for(created, profile.lookback_months, now)
        origin = weighted_choice(origin_weights, rng)
        reason = weighted_choice(config.REASON_WEIGHTS, rng)
        subject = rng.choice(SUBJECT_TEMPLATES.get(case_type, SUBJECT_TEMPLATES[None]))
        account_id, contact_id = _account_contact_pair(org_ctx, rng)
        owner_id = rng.choice(org_ctx.owner_ids)
        created_by_id = rng.choice(org_ctx.created_by_ids)
        tier = rep_tiers[owner_id]
        is_escalated = rng.random() < config.ESCALATED_FRACTION
        csat_mean = config.CSAT_MEAN + config.REP_TIER_CSAT_SHIFT[tier]
        csat = round(clamp(rng.gauss(csat_mean, config.CSAT_STDDEV), config.CSAT_MIN, config.CSAT_MAX))
        type_of_support = weighted_choice(config.TYPE_OF_SUPPORT_WEIGHTS, rng)

        closed = _decide_closed(age_days, rng)
        is_path_b = closed and rng.random() < config.PATH_B_FRACTION

        row = {
            "Subject": subject,
            "Type": case_type,
            "Priority": priority,
            "Origin": origin,
            "Reason": reason,
            "IsEscalated": is_escalated,
            "CSAT__c": csat,
            "Type_of_Support__c": type_of_support,
            "External_ID__c": case_external_id(run_id, seq),
            "CreatedDate": created.isoformat(),
            "OwnerId": owner_id,
            "CreatedById": created_by_id,
        }
        if org_ctx.business_hours_id:
            row["BusinessHoursId"] = org_ctx.business_hours_id
        if account_id:
            row["AccountId"] = account_id
        if contact_id:
            row["ContactId"] = contact_id

        closed_date = None
        is_closed_now = closed and not is_path_b
        if is_closed_now:
            lag_hours = _close_lag_hours(priority, age_hours, tier, rng)
            closed_date = created + timedelta(hours=lag_hours)
            row["Status"] = config.CLOSED_STATUS
            row["ClosedDate"] = closed_date.isoformat()
            row["First_Contact_Close__c"] = True
        elif closed and is_path_b:
            # No ClosedDate here -- Status stays New at insert so ClosedDate
            # isn't silently dropped; the loader flips Status via UPDATE later.
            row["Status"] = "New"
            row["First_Contact_Close__c"] = False
        else:
            row["Status"] = weighted_choice(config.OPEN_STATUS_WEIGHTS, rng)
            row["First_Contact_Close__c"] = False

        # CRMA's Service Open Cases / Service Agent Performance / Service
        # Channel Review / Service Agent Activity dashboards all plot this
        # field (via a "Time Open" duration selector) -- it's 0% filled on
        # the existing 180 seed Cases, which is why those charts render
        # blank today (see NOTES.md "Time_Open__c"). Mirrors the dataflow's
        # own duration logic (compute_CalculatedCaseDuration): closed Cases
        # get wall-clock CreatedDate->ClosedDate days, open Cases get
        # CreatedDate->now days. Field scale is 0 (whole days), hence round().
        duration_days = ((closed_date if is_closed_now else now) - created).total_seconds() / 86400.0
        row["Time_Open__c"] = round(duration_days)

        cohort.insert_rows.append(row)
        cohort.seqs.append(seq)
        cohort.created_dates[seq] = created
        cohort.closed_dates[seq] = closed_date
        cohort.is_closed[seq] = closed and not is_path_b  # Path B isn't "closed" until the follow-up update runs

        if is_path_b:
            cohort.path_b_seqs.add(seq)
        if closed and not is_path_b and rng.random() < config.EMAIL_ATTACH_FRACTION:
            cohort.email_seqs.add(seq)
        if closed and rng.random() < config.KNOWLEDGE_ATTACH_FRACTION:
            cohort.knowledge_seqs.add(seq)
        if rng.random() < config.TASK_ATTACH_FRACTION:
            cohort.task_seqs.add(seq)

    return cohort

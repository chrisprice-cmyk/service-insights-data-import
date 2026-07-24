"""EmailMessage generator -- the Tableau Next FCR fix.

Per NOTES.md: FCR_Flag_clc fires only when a closed Case has exactly one
related EmailMessage. So exactly one EmailMessage per selected Case, dated
shortly after that Case's CreatedDate -- never zero, never two.
"""

import random
from datetime import timedelta


def build_rows(cohort, case_ids_by_seq: dict, rng_seed: int | None = None) -> list:
    rng = random.Random(rng_seed)
    rows = []
    for seq in sorted(cohort.email_seqs):
        case_id = case_ids_by_seq[seq]
        created = cohort.created_dates[seq]
        message_date = created + timedelta(hours=rng.uniform(0.5, 6))
        rows.append({
            "ParentId": case_id,
            "Subject": "Re: your case",
            "TextBody": "Thanks for reaching out -- this has been resolved on our end.",
            "Incoming": False,
            "Status": "3",  # Sent
            "MessageDate": message_date.isoformat(),
            "CreatedDate": message_date.isoformat(),
        })
    return rows

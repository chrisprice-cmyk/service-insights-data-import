"""Task generator -- call-activity flavor for CRMA's ServiceActivity dataset.

Per NOTES.md: ServiceActivity is built from Task/Event joined to Case via
WhatId; the org currently has zero of either pointing at a Case. This
generator links a Task to a realistic subset of generated Cases via
WhatId so CRMA's Service Agent Activity / Telephony-adjacent tiles have
real rows to aggregate.
"""

import random
from datetime import timedelta

CALL_DISPOSITIONS = ["Resolved", "Escalated", "Follow-up Required", "No Answer"]


def build_rows(cohort, case_ids_by_seq: dict, org_ctx, rng_seed: int | None = None) -> list:
    rng = random.Random(rng_seed)
    rows = []
    for seq in sorted(cohort.task_seqs):
        case_id = case_ids_by_seq[seq]
        created = cohort.created_dates[seq]
        activity_date = created + timedelta(hours=rng.uniform(0.1, 4))
        owner_id = rng.choice(org_ctx.owner_ids)
        rows.append({
            "WhatId": case_id,
            "OwnerId": owner_id,
            "Subject": "Call",
            "ActivityDate": activity_date.date().isoformat(),
            "CreatedDate": activity_date.isoformat(),
            # LastModifiedDate itself is system-managed and always stamps to
            # the real insert time -- Salesforce silently ignores any value
            # sent for it, confirmed via live probe inserts against
            # Prime_SDO. This custom shadow field IS createable/updateable,
            # and the dataflow's own Extract_Task_get_Demo_Data_rename_fields
            # node already prefers it over the real LastModifiedDate when
            # populated (see NOTES.md "sum_last_activity" section) -- it's
            # what drives CRMA's "Number_Days Since Last Activity" metric.
            "LastModifiedDate__c": activity_date.isoformat(),
            "Status": "Completed",
            "Priority": "Normal",
            "TaskSubtype": "Call",
            "CallType": "Inbound",
            "CallDurationInSeconds": rng.randint(60, 900),
            "CallDisposition": rng.choice(CALL_DISPOSITIONS),
        })
    return rows

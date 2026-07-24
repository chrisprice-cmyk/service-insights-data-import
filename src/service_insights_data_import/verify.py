"""--verify: post-load sanity check.

Per NOTES.md "Additional build requirements", item 3: re-query the key
aggregates both tracks' dashboards actually use and print a pass/fail
summary against expected ranges, so an SE can confirm the load worked
without manually opening every dashboard.
"""

from dataclasses import dataclass

from .batch import run_prefix


@dataclass
class Check:
    name: str
    value: float
    expected_min: float
    expected_max: float

    @property
    def passed(self) -> bool:
        return self.expected_min <= self.value <= self.expected_max


def run_checks(sf, run_id: str) -> list:
    prefix = run_prefix(run_id)
    checks = []

    total = sf.query(f"SELECT COUNT(Id) c FROM Case WHERE External_ID__c LIKE '{prefix}'")["records"][0]["c"]
    checks.append(Check("Total generated Cases", total, 1, float("inf")))

    escalated = sf.query(
        f"SELECT COUNT(Id) c FROM Case WHERE External_ID__c LIKE '{prefix}' AND IsEscalated = true"
    )["records"][0]["c"]
    escalated_rate = (escalated / total * 100) if total else 0
    checks.append(Check("Escalated Case rate (%)", escalated_rate, 2, 20))

    closed = sf.query(
        f"SELECT COUNT(Id) c FROM Case WHERE External_ID__c LIKE '{prefix}' AND IsClosed = true"
    )["records"][0]["c"]
    closed_rate = (closed / total * 100) if total else 0
    checks.append(Check("Closed Case rate (%)", closed_rate, 60, 95))

    # SOQL doesn't allow GROUP BY/HAVING inside a subquery, so this is done
    # in two passes: fetch closed-Case Ids for this batch, then count
    # EmailMessages per ParentId in Python to find exactly-one matches. The
    # Case Id list is chunked -- at standard/enterprise profile scale a
    # single IN (...) clause with every Id is long enough to blow past
    # SOQL's request-size limit and gets the connection reset outright.
    closed_case_ids = [
        r["Id"] for r in sf.query(
            f"SELECT Id FROM Case WHERE External_ID__c LIKE '{prefix}' AND IsClosed = true"
        )["records"]
    ]
    CHUNK_SIZE = 200
    counts = {}
    for start in range(0, len(closed_case_ids), CHUNK_SIZE):
        chunk = closed_case_ids[start:start + CHUNK_SIZE]
        id_list = ",".join(f"'{cid}'" for cid in chunk)
        email_parents = [
            r["ParentId"] for r in sf.query(
                f"SELECT ParentId FROM EmailMessage WHERE ParentId IN ({id_list})"
            )["records"]
        ]
        for pid in email_parents:
            counts[pid] = counts.get(pid, 0) + 1
    fcr_eligible = sum(1 for c in counts.values() if c == 1)
    fcr_rate = (fcr_eligible / closed * 100) if closed else 0
    checks.append(Check("FCR-eligible rate among closed Cases (%)", fcr_rate, 10, 90))

    knowledge_linked = sf.query(
        f"SELECT COUNT(Id) c FROM CaseArticle WHERE Case.External_ID__c LIKE '{prefix}'"
    )["records"][0]["c"]
    checks.append(Check("CaseArticle-linked Cases", knowledge_linked, 1, float("inf")))

    task_linked = sf.query(
        f"SELECT COUNT(Id) c FROM Task WHERE WhatId IN "
        f"(SELECT Id FROM Case WHERE External_ID__c LIKE '{prefix}')"
    )["records"][0]["c"]
    checks.append(Check("Task-linked Cases", task_linked, 1, float("inf")))

    csat_filled = sf.query(
        f"SELECT COUNT(Id) c FROM Case WHERE External_ID__c LIKE '{prefix}' AND CSAT__c != null"
    )["records"][0]["c"]
    csat_fill_rate = (csat_filled / total * 100) if total else 0
    checks.append(Check("CSAT__c fill rate (%)", csat_fill_rate, 95, 100))

    # Time_Open__c drives the "big chart" (scatter) on 4 CRMA dashboards --
    # Service Open Cases, Service Agent Performance, Service Channel Review,
    # Service Agent Activity. It's 0% filled on the org's original 180 seed
    # Cases (a pre-existing gap, not this tool's to fix), so this check is
    # scoped to only the Cases from this run.
    time_open_filled = sf.query(
        f"SELECT COUNT(Id) c FROM Case WHERE External_ID__c LIKE '{prefix}' AND Time_Open__c != null"
    )["records"][0]["c"]
    time_open_fill_rate = (time_open_filled / total * 100) if total else 0
    checks.append(Check("Time_Open__c fill rate (%)", time_open_fill_rate, 95, 100))

    return checks


def print_report(checks: list) -> bool:
    all_passed = True
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        if not check.passed:
            all_passed = False
        print(f"[{status}] {check.name}: {check.value:.1f} (expected {check.expected_min}-{check.expected_max})")
    return all_passed

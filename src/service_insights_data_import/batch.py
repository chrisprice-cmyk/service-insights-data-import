"""Batch identity: run ids and the External_ID__c tag format.

External_ID__c is unique per record (confirmed via describe), so the batch
tag can't be one shared literal across every generated Case -- it's a
per-record-unique value that shares a common, greppable prefix instead:

    SI-GEN-<run_id>-<seq>

`run_id` identifies one execution of the tool; `seq` makes each Case's value
unique within that run. `LIKE 'SI-GEN-<run_id>-%'` finds a whole batch;
`LIKE 'SI-GEN-%'` finds every batch this tool has ever created in the org.
"""

from datetime import datetime, timezone

from .config import BATCH_PREFIX


def new_run_id() -> str:
    """A sortable, human-readable id for one tool execution, e.g. 20260724-153045."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def case_external_id(run_id: str, seq: int) -> str:
    """The unique External_ID__c value for the seq-th Case in a run."""
    return f"{BATCH_PREFIX}{run_id}-{seq}"


def run_prefix(run_id: str) -> str:
    """The SOQL LIKE prefix that finds every Case belonging to one run."""
    return f"{BATCH_PREFIX}{run_id}-%"



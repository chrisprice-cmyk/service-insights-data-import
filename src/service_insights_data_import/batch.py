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


def any_batch_prefix() -> str:
    """The SOQL LIKE prefix that finds every Case this tool has ever created."""
    return f"{BATCH_PREFIX}%"


def run_id_from_external_id(external_id: str) -> str | None:
    """Recover the run_id from a Case's External_ID__c value, or None if it
    doesn't look like one of ours."""
    if not external_id or not external_id.startswith(BATCH_PREFIX):
        return None
    remainder = external_id[len(BATCH_PREFIX):]
    run_id, _, _seq = remainder.rpartition("-")
    return run_id or None

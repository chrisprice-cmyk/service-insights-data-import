"""Downstream refresh: Data Cloud data streams (Tableau Next) and the CRM
Analytics Service Analytics dataflow (CRMA).

This tool writes straight to Salesforce via Bulk API 2.0 -- neither Data
Cloud nor CRMA pick up new/deleted Case, EmailMessage, or Task rows until
their own ingestion/ETL runs again. Both refreshes are documented, supported
async APIs (not UI-only actions):

- Data Cloud: POST /ssot/data-streams/{id}/actions/run starts an ingestion
  job for one data stream (Connect REST API, "Run data streams"). Confirmed
  live against Prime_SDO's CRM-connector streams (datastreamType SFDC) that
  a hard-deleted source record is removed from Data Cloud on the *next*
  refresh, no separate full-refresh step required (per Salesforce Help,
  "Delete Ingested Records in Data 360").
- CRMA: POST /wave/dataflowjobs {"command": "start", "dataflowId": ...}
  starts a dataflow/recipe run (CRM Analytics REST API, "Dataflow Jobs List
  Resource"). Confirmed live against Prime_SDO that every sfdcDigest node in
  Service_Analytics_eltDataflow touching Case/EmailMessage/CaseArticle/Task
  runs with incremental=False, i.e. a full re-extract every run -- so a run
  after `undo` fully drops deleted records from the dataset, no stale rows.

Neither API exposes a job-id-keyed status-polling endpoint for data stream
runs (data-transform runs have one; data-stream runs don't, confirmed against
the Data 360 Connect REST API reference), so streams are polled via their own
`lastRunStatus` field on GET /ssot/data-streams instead. Dataflow jobs do
have a per-job status via GET /wave/dataflowjobs/{jobId}.
"""

import time

# Source objects this tool ever inserts/updates/deletes. Only data streams
# whose connectorInfo.sourceObject is one of these are refreshed -- refreshing
# the whole org's stream list on every run would be slow and touches data
# this tool has nothing to do with.
REFRESH_SOURCE_OBJECTS = {"Case", "EmailMessage", "CaseArticle", "Task"}

SERVICE_ANALYTICS_DATAFLOW_NAME = "Service_Analytics_eltDataflow"

POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 300


def _api(sf) -> str:
    return f"https://{sf.sf_instance}/services/data/v{sf.sf_version}"


def find_relevant_data_streams(sf) -> list:
    """Data streams sourced from an object this tool writes to, e.g.
    Case_Home / EmailMessage_Home / Task_Home. Not every object this tool
    touches necessarily has its own stream (e.g. this org has none for
    CaseArticle) -- callers should treat an empty result as "nothing to do"
    rather than an error."""
    relevant = []
    offset = 0
    while True:
        resp = sf._call_salesforce(
            "GET", f"{_api(sf)}/ssot/data-streams?limit=50&offset={offset}"
        )
        page = resp.json().get("dataStreams", [])
        for stream in page:
            source_object = stream.get("connectorInfo", {}).get("connectorDetails", {}).get("sourceObject")
            if source_object in REFRESH_SOURCE_OBJECTS:
                relevant.append(stream)
        if len(page) < 50:
            break
        offset += 50
    return relevant


def run_data_stream(sf, stream_id: str) -> str | None:
    """Starts an ingestion run for one data stream. Returns the jobId if the
    org's API version includes one in the response -- observed live against
    Prime_SDO (API v67.0) that the response is just {"errors": [], "success":
    true} with no jobId, despite the documented response shape including it,
    so this is best-effort and may return None."""
    resp = sf._call_salesforce(
        "POST", f"{_api(sf)}/ssot/data-streams/{stream_id}/actions/run"
    )
    return resp.json().get("jobId")


def refresh_data_streams(sf) -> dict:
    """Kick off a refresh for every data stream this tool's writes could
    affect. Fire-and-forget -- there's no documented per-jobId status
    endpoint for data stream runs, so this doesn't block on completion (see
    module docstring). Returns {stream_name: job_id_or_None}."""
    streams = find_relevant_data_streams(sf)
    started = {}
    for stream in streams:
        stream_id = stream.get("id") or stream.get("name")
        job_id = run_data_stream(sf, stream_id)
        started[stream.get("name", stream_id)] = job_id
    return started


def find_dataflow_id(sf, dataflow_name: str = SERVICE_ANALYTICS_DATAFLOW_NAME) -> str | None:
    resp = sf._call_salesforce("GET", f"{_api(sf)}/wave/dataflows")
    for dataflow in resp.json().get("dataflows", []):
        if dataflow.get("name") == dataflow_name:
            return dataflow["id"]
    return None


def start_dataflow_job(sf, dataflow_id: str) -> str:
    resp = sf._call_salesforce(
        "POST",
        f"{_api(sf)}/wave/dataflowjobs",
        json={"command": "start", "dataflowId": dataflow_id},
    )
    return resp.json()["id"]


def get_dataflow_job_status(sf, job_id: str) -> str:
    resp = sf._call_salesforce("GET", f"{_api(sf)}/wave/dataflowjobs/{job_id}")
    return resp.json()["status"]


def refresh_crma_dataflow(sf, wait: bool = False) -> dict:
    """Starts a Service Analytics dataflow run. If wait=True, polls
    /wave/dataflowjobs/{jobId} until a terminal status or POLL_TIMEOUT_SECONDS
    elapses. Returns {"dataflow_id", "job_id", "status"} -- status is
    whatever the last poll observed, or "Queued" if wait=False."""
    dataflow_id = find_dataflow_id(sf)
    if not dataflow_id:
        return {"dataflow_id": None, "job_id": None, "status": "NOT_FOUND"}

    job_id = start_dataflow_job(sf, dataflow_id)
    status = "Queued"
    if wait:
        elapsed = 0
        while elapsed < POLL_TIMEOUT_SECONDS:
            status = get_dataflow_job_status(sf, job_id)
            if status in ("Success", "Failed", "Warning"):
                break
            time.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS
    return {"dataflow_id": dataflow_id, "job_id": job_id, "status": status}

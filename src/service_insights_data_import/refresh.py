"""Downstream refresh: Data Cloud data streams (Tableau Next) and the CRM
Analytics Service Analytics dataflow (CRMA).

This tool writes straight to Salesforce via Bulk API 2.0 -- neither Data
Cloud nor CRMA pick up new/deleted Case, EmailMessage, CaseArticle, or Task
rows until their own ingestion/ETL runs again. There are THREE layers here,
and they must run in this order, waiting for each to finish before starting
the next:

1. **CRMA local replication (SFDC_LOCAL connector)**. This org's CRM
   Analytics has a legacy "SFDC_LOCAL" connector (Data Manager Home >
   Connections in the UI) that replicates ~70 Salesforce objects -- Case,
   Task, CaseArticle, CaseHistory among them -- into their own CRMA-native
   replicated datasets *before* any dataflow runs. Confirmed live against
   Prime_SDO: the Service_Analytics_eltDataflow's `Extract_Case`/
   `Extract_Task`/`Extract_CaseArticleKnowledge` nodes are `sfdcDigest`
   nodes, which read this replica, not live Salesforce directly. Running the
   analytics dataflow without refreshing the replica first silently rebuilds
   the CRMA dataset from stale data (observed: dataflow reported "Warning"
   -- not an error -- while `ServiceCase` still held the pre-load row count).
   Each replicated object has its own tiny "Replication dataflow"
   (`GET /wave/replicatedDatasets` -> `replicationDataflowId`), started the
   same way as any other dataflow job: `POST /wave/dataflowjobs
   {"command": "start", "dataflowId": <replicationDataflowId>}`.
2. **CRMA Service Analytics dataflow**. `POST /wave/dataflowjobs
   {"command": "start", "dataflowId": ...}` (CRM Analytics REST API,
   "Dataflow Jobs List Resource"). Confirmed live against Prime_SDO that
   every sfdcDigest node in Service_Analytics_eltDataflow touching
   Case/EmailMessage/CaseArticle/Task runs with incremental=False, i.e. a
   full re-extract every run -- so a run after `undo` fully drops deleted
   records from the dataset, no stale rows, *provided* step 1 already ran.
3. **Data Cloud data streams** (Tableau Next). `POST
   /ssot/data-streams/{id}/actions/run` starts an ingestion job for one data
   stream (Connect REST API, "Run data streams"). This is a separate
   ingestion pipeline from CRMA's SFDC_LOCAL replica -- it reads live
   Salesforce directly, not the replica -- so it has no dependency on step 1
   and can run independently. Confirmed live against Prime_SDO's
   CRM-connector streams (datastreamType SFDC) that a hard-deleted source
   record is removed from Data Cloud on the *next* refresh, no separate
   full-refresh step required (per Salesforce Help, "Delete Ingested
   Records in Data 360").

Both dataflow-job-based steps (1 and 2) share one status-polling endpoint,
GET /wave/dataflowjobs/{jobId}, so step 1 can be waited on before starting
step 2. Data stream runs (step 3) have no equivalent per-job status
endpoint (data-transform runs have one; data-stream runs don't, confirmed
against the Data 360 Connect REST API reference) -- fire-and-forget only.
"""

import time

# Source objects this tool ever inserts/updates/deletes. Only Data Cloud
# streams whose connectorInfo.sourceObject is one of these are refreshed --
# refreshing the whole org's stream list on every run would be slow and
# touches data this tool has nothing to do with. CaseHistory is included for
# the CRMA replication step (not a stream source) because this tool's Path B
# status-flip generates real CaseHistory rows that ServiceCaseHistory (Avg
# Time to 1st Close) depends on.
REFRESH_SOURCE_OBJECTS = {"Case", "EmailMessage", "CaseArticle", "Task"}
CRMA_REPLICATION_SOURCE_OBJECTS = {"Case", "CaseArticle", "Task", "CaseHistory"}

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


def find_crma_replication_dataflow_ids(sf) -> dict:
    """Replication dataflow Ids for the SFDC_LOCAL-replicated objects this
    tool's writes affect (see module docstring, step 1). Returns
    {source_object: replication_dataflow_id}. An object missing from the
    result means this org's SFDC_LOCAL connector doesn't replicate it (e.g.
    EmailMessage isn't part of SFDC_LOCAL in this org -- the analytics
    dataflow reads it some other way), which callers should treat as
    nothing-to-do, not an error."""
    resp = sf._call_salesforce("GET", f"{_api(sf)}/wave/replicatedDatasets")
    found = {}
    for rd in resp.json().get("replicatedDatasets", []):
        source = rd.get("sourceObjectName")
        if source in CRMA_REPLICATION_SOURCE_OBJECTS:
            found[source] = rd.get("replicationDataflowId")
    return found


def refresh_crma_replication(sf, wait: bool = True) -> dict:
    """Runs the SFDC_LOCAL replication dataflow for each relevant object,
    so the CRMA analytics dataflow (which reads this replica, not live
    Salesforce) sees current data. Waits for each to reach a terminal status
    by default -- the analytics dataflow run that follows depends on these
    having actually finished, not just started."""
    dataflow_ids = find_crma_replication_dataflow_ids(sf)
    results = {}
    for source_object, dataflow_id in dataflow_ids.items():
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
        results[source_object] = {"dataflow_id": dataflow_id, "job_id": job_id, "status": status}
    return results


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
    """Refreshes the SFDC_LOCAL replication for Case/Task/CaseArticle/
    CaseHistory (always waited on -- see module docstring, step 1; the
    analytics dataflow below reads this replica, so starting it before the
    replica has finished silently rebuilds the dataset from stale data),
    then starts the Service Analytics dataflow itself. If wait=True, also
    polls /wave/dataflowjobs/{jobId} for the analytics dataflow until a
    terminal status or POLL_TIMEOUT_SECONDS elapses. Returns
    {"replication": {source_object: {...}}, "dataflow_id", "job_id",
    "status"} -- "status" is whatever the last poll observed, or "Queued"
    if wait=False."""
    replication_results = refresh_crma_replication(sf, wait=True)

    dataflow_id = find_dataflow_id(sf)
    if not dataflow_id:
        return {"replication": replication_results, "dataflow_id": None, "job_id": None, "status": "NOT_FOUND"}

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
    return {"replication": replication_results, "dataflow_id": dataflow_id, "job_id": job_id, "status": status}

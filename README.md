# Service Insights Data Import

Generates and loads realistic Case (and related) demo data into a Salesforce
org so both **Tableau Next's "Service Insights"** app and **CRM Analytics'
"Service Analytics"** app have enough data for their dashboards to look
meaningful — without ever touching data that's already in the org.

- **Strictly additive.** Every record this tool creates is tagged; it never
  updates or deletes anything it didn't insert itself in the same run.
- **Undoable.** A companion `undo` command removes exactly what a given run
  created, leaf-to-root, and nothing else.
- **Realistic, not random.** Seasonality in Case volume, channel/Origin mix
  that shifts by month and drifts over the lookback window, and a small
  capped pool of service reps with stable per-rep performance tiers (some
  reps close faster and score higher CSAT than others).
- **Sets the CRMA-specific fields dashboards actually chart**, not just the
  fields you'd guess from the object's obvious columns — e.g. `Time_Open__c`
  (a real, `createable` custom field that four CRM Analytics "Service
  Analytics" dashboards plot but is 0% filled on this org's original seed
  data) and `CSAT__c`.
- **Reusable.** Nothing is hardcoded to a specific org — it discovers Users,
  BusinessHours, Accounts/Contacts, and Knowledge articles at runtime via
  the target org's own data.

## Prerequisites

- Python 3.11+
- The [`sf` CLI](https://developer.salesforce.com/tools/salesforcecli),
  already authenticated against the target org (`sf org login web -a
  <alias>` or equivalent) — this tool reuses that session rather than
  running its own OAuth flow.
- `pip install -r requirements.txt` (installs `simple-salesforce`).
- The target org needs `Case.External_ID__c` (custom field, createable,
  `unique=true`) — this is what every generated record is tagged with. If
  your org doesn't have it, create it before running.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

All commands take `--org <alias>`, the `sf` CLI alias of the target org.

### 1. Dry run (default) — inspect before touching the org

```bash
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> run --profile standard
```

Generates the full cohort in memory and writes it to CSV under
`data/dry-runs/<run_id>/` — no Salesforce API calls at all. Use this to
sanity-check volumes and eyeball field distributions before going live.

### 2. Live run — actually insert

```bash
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> run --profile standard --live
```

Prints a pre-flight summary (existing Case count, what's about to be
inserted) and asks for confirmation before doing anything. Pass `--yes` to
skip the prompt (e.g. in CI). After inserting, it automatically triggers a
refresh of the relevant Data Cloud data streams and the CRM Analytics
Service Analytics dataflow (see [Downstream refresh](#downstream-refresh)
below) — pass `--no-refresh` to skip that.

Every live run writes a manifest to `data/runs/<run_id>.json` — this is the
authoritative record `undo` uses later.

### 3. Verify

```bash
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> verify <run_id>
```

Re-queries the aggregates both apps' dashboards actually use (Case volume,
escalation rate, closed rate, FCR-eligible rate, CaseArticle/Task linkage,
CSAT fill rate, Time_Open__c fill rate) and prints a pass/fail summary
against expected ranges, so
you can confirm the load worked without opening every dashboard by hand.

### 4. Undo

```bash
# Preview what would be removed, without removing anything:
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> undo --last --dry-run

# Actually remove it:
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> undo --last
```

`--last` targets the most recently completed run; pass a specific `run_id`
instead to target an older one. Undo deletes Task → CaseArticle →
EmailMessage → Case (leaf-to-root) using only Ids recorded in that run's
manifest — it is structurally incapable of deleting anything it didn't
create itself in that run, even by accident. Also triggers the same
downstream refresh as a live run (`--no-refresh` / `--wait-for-crma` apply
here too) so deleted rows drop out of Data Cloud and CRM Analytics on the
next ingestion cycle, not just out of core Salesforce.

**If you decide the generated data isn't right** (wrong volumes, wrong
distributions, whatever), the loop is: `undo --last` → adjust
`config.py`/profile → `run --live` again. Nothing needs manual cleanup in
Data Cloud or CRM Analytics — see below.

## Profiles

| Profile      | Cases  | Lookback | Use case                                   |
|--------------|--------|----------|---------------------------------------------|
| `quick`      | 200    | 3 months | Smoke-test the tool against a new org first |
| `standard`   | 2,500  | 24 months| Default — what this project was scoped for  |
| `enterprise` | 10,000 | 36 months| Larger volume for a "mature org" demo story |

Pass with `--profile <name>` on `run`. `standard` is the default.

## Downstream refresh

This tool writes straight to Salesforce via Bulk API 2.0. Neither **Data
Cloud** (which feeds Tableau Next) nor **CRM Analytics** picks up new or
deleted records until their own ingestion/ETL runs again — a live `run` or
an `undo` automatically triggers all of the following, in order:

- **CRM Analytics local replication (`SFDC_LOCAL` connector)**: some orgs
  have a legacy CRMA connector (visible in the UI at Data Manager Home >
  Connections) that replicates Salesforce objects — Case, Task,
  CaseArticle, CaseHistory — into their own CRMA-native snapshot on a
  schedule, and the Service Analytics dataflow's extract nodes read *that
  snapshot*, not live Salesforce. Skipping this step doesn't error; it
  silently rebuilds CRMA's dataset from stale data. This tool always
  triggers and waits for this replication before touching the dataflow
  below — it's not optional, since the dataflow depends on it having
  actually finished.
- **CRM Analytics dataflow**: starts the `Service_Analytics_eltDataflow`
  dataflow (`POST .../wave/dataflowjobs`). This *can* be polled to
  completion — pass `--wait-for-crma` on `run --live` or `undo` to block
  until the job finishes instead of firing and moving on. This dataflow's
  Case/EmailMessage/CaseArticle/Task extracts all run as full re-extracts
  (not incremental), so deleted records disappear from the dataset the next
  time it runs.
- **Data Cloud**: starts a run (`POST .../ssot/data-streams/{id}/actions/run`)
  for every data stream in the org sourced from an object this tool writes
  to (Case, EmailMessage, CaseArticle, Task). This is a separate ingestion
  pipeline from the CRMA replication above — it reads live Salesforce
  directly, with no dependency on it. It's also fire-and-forget — Salesforce
  doesn't expose a way to poll a data stream run's completion, so there's
  nothing to wait on. Confirmed against Salesforce's own docs that a
  hard-deleted source record (e.g. from `undo`) is removed from Data Cloud
  on the very next refresh — no special full-refresh step needed.

Pass `--no-refresh` to skip all of the above (useful for fast iteration
while tuning generator config, when you don't care about dashboards
updating yet).

If your org doesn't have the `SFDC_LOCAL` connector, a matching data
stream for some object, or the Service Analytics dataflow at all, the
corresponding refresh step just reports "not found"/skips it — it's not an
error.

## Deploying to a new org

This is the checklist an SE should follow end-to-end the first time they
point this tool at a new org — not just running the generator, but
confirming both dashboard apps actually render afterward. Everything below
was worked out live against two separate orgs (`Prime_SDO`, then
`Probation_Digital`); full technical detail and the exact API calls behind
each step are in `NOTES.md` if you need to go deeper than this summary.

### 1. Prerequisites checklist

Before the first run against a new org, confirm:

- [ ] `Case.External_ID__c` exists (custom, createable, `unique=true`) — see
  [Prerequisites](#prerequisites) above. The tool will fail loudly on the
  first insert if this is missing.
- [ ] `Case.Time_Open__c` and `Case.CSAT__c` exist and are createable — both
  are plotted by CRM Analytics "Service Analytics" dashboards.
- [ ] `Task.LastModifiedDate__c` exists and is createable — CRMA's
  "Number_Days Since Last Activity" metric depends on it (see step 3 below
  for what happens if it's missing or the dataflow doesn't prefer it).
- [ ] The CRM Analytics "Service Analytics" app (dataflow + dashboards) is
  already installed on the org. This tool refreshes an existing dataflow; it
  does not install the app itself.
- [ ] If you also care about Tableau Next: the "Service Insights" app is
  already provisioned (Setup → check for a workspace built from the
  `sfdc_internal__ServiceInsights` template). Same story — this tool doesn't
  install it.
- [ ] **Each org has its own copy** of the dataflow, dashboards, and any
  live patches applied to them (different `02K...`/dashboard Ids per org).
  A fix applied to one org's live definition does nothing for any other org
  — steps 3–4 below need to be repeated per org, not just once ever.

### 2. Dry run → live run → verify

```bash
# 1. Dry run first, always — inspect the CSVs under data/dry-runs/ before touching the org
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> run --profile quick

# 2. Live run. --yes skips the confirmation prompt (needed for CI/scripted use).
#    --wait-for-crma blocks until the CRMA dataflow job finishes instead of
#    firing and moving on -- use it here so step 3 has a job to inspect.
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> run --profile quick --live --yes --wait-for-crma

# 3. Verify
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> verify <run_id>
```

Use the `quick` profile (200 Cases) for this first pass on a new org — it's
enough to prove the pipeline end-to-end without waiting on a large load.
Re-run with `standard` or `enterprise` once you've confirmed the checks
below pass.

### 3. Check for the two known CRMA symptoms

The live run's output prints the CRMA dataflow job status. `Warning` is
**not** automatically a problem — this dataflow throws benign warnings on
some orgs (e.g. LiveChatTranscript, Knowledge__kav, or Opportunity join
warnings unrelated to Case data) — so don't treat the status alone as a
signal. Instead, check for these two specific symptoms after the run:

- **"Service Open Cases" dashboard's scatter/bubble chart is blank or shows
  almost no points.** Root cause: on some orgs, CRMA's SAQL sorts `null`
  values to the front on `order by desc`, so Cases with a null
  `Time_Open__c` (typically pre-existing seed data) fill the chart's
  `limit` entirely and crowd out real rows.
- **`sum_last_activity` / "Number_Days Since Last Activity" clusters near
  0 or 0.01 for every row**, instead of showing a spread of values. Root
  cause: `Case.LastModifiedDate` and `Task.LastModifiedDate` are
  system-managed fields — Salesforce silently ignores any backdated value
  sent on insert, so a dataflow node computing "days since last activity"
  from the raw field sees everything as just-modified.

Confirm with a direct query rather than trusting the dashboard tile alone:
query the CRMA dataset (`ServiceCase` or equivalent) for the affected
metric and check for a spread of values. **Before you conclude either bug
is present, re-fetch the dataset's current `currentVersionId`
(`GET /wave/datasets?q=<name>`)** — every dataflow run changes it, and
querying a stale version returns a snapshot from *before* the run, which
looks identical to these bugs but isn't. This cost real time to debug
twice; don't skip it.

### 4. If either symptom is genuinely present

There is no automated fix command for this yet — these are manual,
per-org, live edits against the dataflow/dashboard definitions via the
CRM Analytics REST API. Broad shape of the fix, in order:

1. **Back up first.** `GET` the current live dataflow (`/wave/dataflows/{id}`)
   and/or dashboard (`/wave/dashboards/{id}`) definition and save the raw
   JSON under `data/dataflow-backups/<OrgAlias>_<what>_<date>_pre_<fix>.json`
   before changing anything.
2. **Null-sort-order fix (scatter chart)**: in the dashboard's step that
   plots `Time_Open__c` (look for a `pigql` query with `order q by ...` and
   `limit q ...` referencing `Total_Duration`), insert a filter immediately
   before the order/limit: `q = filter q by 'Total_Duration' >= 0;`. Then
   `PATCH /wave/dashboards/{id}` with the edited `state`.
3. **`sum_last_activity` clustering fix**: find the dataflow node(s) that
   compute days-since-last-activity from `LastModifiedDate_sec_epoch` (look
   in `computeJoin_*` nodes feeding the Case/Task register step) and swap
   the reference to a real per-record timestamp that isn't system-managed —
   on the orgs seen so far, a `LastModifiedDate__c` shadow field on Task
   (already preferred by the dataflow's own extract node when populated)
   covers the Task side for free once the generator sets it; the Case side
   needs the dataflow's fallback SAQL literally repointed at
   `CreatedDate_sec_epoch` instead. Then `PATCH /wave/dataflows/{id}`
   (add `?wave.syncConfigCleanup=Cleanup` if the PATCH is rejected for a
   deprecated `"incremental"` property).
4. **Watch for HTML entity escaping.** Both `GET` responses above return
   HTML-entity-encoded text (`&#39;` for `'`, etc.) — recursively
   `html.unescape()` the whole tree before editing, or re-escape on the way
   back out, or unrelated nodes will double-escape and break.
5. **Redeploy and re-run** the dataflow (or trigger it via a fresh `run
   --live --wait-for-crma`), then re-verify per step 3 above — using a
   freshly re-fetched dataset version, not the one you started with.

Full worked examples of both fixes (exact SAQL/pigql diffs, the specific
node names patched on each org so far) are in `NOTES.md`.

### 5. Confirm the Tableau Next side, if in scope

If the org also needs Tableau Next's "Service Insights" app:

- Confirm the app is provisioned: `GET /services/data/v{ver}/tableau/dashboards`
  should list dashboards with `templateSource.name` =
  `sfdc_internal__ServiceInsights`.
- Confirm Data Cloud is actually ingesting, not just fired-and-forgotten:
  `GET /services/data/v{ver}/ssot/data-streams` and check `lastRefreshDate`
  / `lastRunStatus` for `Case_Home`, `CaseHistory2_Home`,
  `EmailMessage_Home` (or whichever streams your org has) — a recent
  timestamp with `SUCCESS` confirms the pipeline actually ran, not just that
  this tool asked it to.
- Cross-check against the [Known blockers](#known-blockers-things-this-tool-cannot-fix)
  table below — Omni-Channel and Tableau Next CSAT tiles will stay blank on
  every org regardless of data volume; that's expected, not a failure of
  this checklist.

## Known blockers (things this tool cannot fix)

Some dashboard tiles in both apps depend on objects that **cannot be
bulk-seeded** through any supported API — they require the actual product
feature to run (Omni-Channel routing, Survey invitations). This tool works
around what it can and leaves the rest genuinely blank; don't expect these
tiles to populate no matter how much Case data you load.

| Symptom (tile still blank after a run) | Root cause | Affected areas |
|---|---|---|
| Omni-Channel dashboard, Cases1 Cost/FCR-cost tiles, "Omni" half of My Service Performance | `AgentWork`/Omni-Channel routing records can only be created by real Omni-Channel presence/routing activity, not direct insert | Tableau Next: Omni-Channel dashboard, parts of Cases1 and My Service Performance |
| Service Omni, Service Agent Activity/Telephony Omni-adjacent tiles | Same `AgentWork` limitation | CRM Analytics: Service Omni, Service Agent Activity |
| Tableau Next CSAT tiles specifically (not CRMA's `CSAT__c`-based tiles) | `Survey`/`SurveyResponse` records require a real survey invitation flow; direct insert isn't supported | Tableau Next only — CRMA's own CSAT tiles use the `Case.CSAT__c` field this tool does set, so those are unaffected |

CRMA's "Service Open Cases", "Service Agent Performance", "Service Channel
Review", and "Service Agent Activity" dashboards each have one large
scatter/bubble chart plotting `Case.Time_Open__c` — a plain, `createable`
custom field that's 0% filled on this org's original seed Cases (not a
platform blocker, just never set by anything in the org). This tool sets it
on every Case it generates, so those charts populate for generated data;
the seed Cases simply won't have a point on them.

## Safety model

- Every generated Case gets a per-record-unique `External_ID__c` of the form
  `SI-GEN-<run_id>-<seq>` (the field is `unique=true`, so a single shared tag
  per run isn't possible). Related EmailMessage/CaseArticle/Task rows link
  back to those Case Ids.
- A `BatchGuard` enforces, at the code level, that this tool can never
  UPDATE or DELETE a record it didn't itself register earlier in the same
  run (or load from that run's manifest, for `undo`) — not just documented
  intent, an actual runtime assertion.
- `data/runs/<run_id>.json` is the authoritative source for `undo`; the
  `External_ID__c` tag is a secondary/backup lookup path if the manifest
  file itself is ever lost (e.g. a fresh checkout on another machine).

## License

TBD.

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
CSAT fill rate) and prints a pass/fail summary against expected ranges, so
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
an `undo` automatically triggers both:

- **Data Cloud**: starts a run (`POST .../ssot/data-streams/{id}/actions/run`)
  for every data stream in the org sourced from an object this tool writes
  to (Case, EmailMessage, CaseArticle, Task). This is fire-and-forget —
  Salesforce doesn't expose a way to poll a data stream run's completion, so
  there's nothing to wait on. Confirmed against Salesforce's own docs that a
  hard-deleted source record (e.g. from `undo`) is removed from Data Cloud
  on the very next refresh — no special full-refresh step needed.
- **CRM Analytics**: starts the `Service_Analytics_eltDataflow` dataflow
  (`POST .../wave/dataflowjobs`). Unlike Data Cloud, this *can* be polled to
  completion — pass `--wait-for-crma` on `run --live` or `undo` to block
  until the job finishes instead of firing and moving on. This dataflow's
  Case/EmailMessage/CaseArticle/Task extracts all run as full re-extracts
  (not incremental), so deleted records disappear from the dataset the next
  time it runs, same as Data Cloud.

Pass `--no-refresh` to skip both (useful for fast iteration while tuning
generator config, when you don't care about dashboards updating yet).

If your org doesn't have a matching data stream for some object, or doesn't
have the Service Analytics dataflow at all, the refresh step just reports
"not found" and skips it — it's not an error.

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

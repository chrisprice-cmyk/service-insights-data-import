# Deploy Service Insights demo data

This command walks an SE through running `service_insights_data_import`
against a target org end-to-end. It follows the runbook already documented
in this repo's `README.md` — treat that file and `NOTES.md` as the source
of truth if anything here seems out of date; do not duplicate their
content, read them.

(This is the Cursor copy of the Claude Code skill at
`.claude/skills/deploy-service-insights/SKILL.md` — keep both in sync if
you edit one.)

## Before doing anything: ask these questions up front

Ask all of the following before running any command, so the user sees the
full shape of what's about to happen and nothing gets assumed silently.

### A. Is the Python environment set up?

Check whether `.venv` exists and `simple_salesforce` is importable (e.g.
`.venv/bin/python3 -c "import simple_salesforce"`). If not, ask the user
whether they want you to run the [Install](#install) steps now
(`python3 -m venv .venv && source .venv/bin/activate && pip install -r
requirements.txt`) before continuing, or whether they've already got an
environment set up elsewhere they'll activate themselves. Don't just run
`pip install` unasked — it's a local environment change the user should
confirm, especially if they already have a venv elsewhere.

### B. Is the `sf` CLI already authenticated against the target org?

This tool reuses an existing `sf` CLI session rather than running its own
OAuth flow, and neither Claude Code nor Cursor can drive an interactive
browser login for the user. Ask the user to confirm the target org alias
is already authenticated (`sf org list`), and if not, ask them to run `sf
org login web -a <alias>` themselves first — flag this as a hard blocker
up front rather than letting them discover it several steps in.

### C. Which dashboard app(s)?

Ask the user which dashboard app(s) they want this run confirmed
against:

- **CRM Analytics "Service Analytics" only**
- **Tableau Next "Service Insights" only**
- **Both**

Note for the user up front: the live run itself always *attempts* to
refresh both CRM Analytics and Data Cloud — the underlying tool has no flag
to split that (see README's "Downstream refresh" section). This is safe
either way, on any org, regardless of which app(s) are actually installed:

- If the **CRMA Service Analytics dataflow** doesn't exist in this org,
  `refresh_crma_dataflow` returns `status: "NOT_FOUND"` and the CLI prints
  `Service Analytics dataflow not found in this org -- skipping.`
- If this org's **SFDC_LOCAL replication** doesn't cover Case/Task/
  CaseArticle/CaseHistory, the CLI prints
  `No matching CRMA SFDC_LOCAL replicated objects found -- skipping.`
- If there are **no matching Data Cloud data streams** (Tableau Next not
  provisioned, or provisioned without streams sourced from Case/
  EmailMessage/CaseArticle/Task), the CLI prints
  `No matching Data Cloud data streams found -- skipping.`

All three are non-fatal by design (`cli.py`'s `_refresh_downstream` wraps
each in its own try/except) — a missing app never makes the load itself
fail. So picking any scope, on an org where the *other* app isn't
installed, is always safe to attempt: worst case you see a "not
found"/"skipping" line for the app you didn't select, and can ignore it.
This choice only controls which app(s) get the post-load
confirmation/verification steps (Steps 5–7 below) and which app's known
quirks get checked for.

### D. How much data — which profile?

Ask which **profile** to use — this is a separate, equally explicit
choice, not a default to slide past. Show the actual numbers from
README's "Profiles" table so it's not a blind pick:

- **`quick`** — 200 Cases, 3-month lookback. Best for a first run against a
  new org, or a fast smoke test.
- **`standard`** — 2,500 Cases, 24-month lookback. What this project was
  scoped for — the default for an established demo.
- **`enterprise`** — 10,000 Cases, 36-month lookback. Larger volume for a
  "mature org" demo story.

Recommend `quick` if this is the first run against this org (per README's
"Deploying to a new org" guidance — prove the pipeline end-to-end before
loading volume), but let the user override.

### E. Target org, and is this the first run against it?

Ask for the target org alias (`--org <alias>`), and explicitly ask whether
this tool has already been run and verified working against this org
before. This decides whether Steps 6/7 (the one-time dashboard-rendering
checks) run at all — don't assume based on conversation history, since
that's not reliable across sessions; ask directly.

### Then: print the agenda

Print the agenda, trimmed to what was chosen in C, and to whether E was
answered "first time" (include steps 6/7) or "already confirmed" (skip
them). Example for "Both" + first time:

```
Service Insights deployment — planned steps:
  1. Confirm prerequisites (fields, sf CLI auth, CRMA/Tableau Next apps installed)
  2. Dry run — generate the cohort, no org writes
  3. Live run — insert into Salesforce (asks for confirmation first)
  4. Downstream refresh — CRMA replication -> dataflow -> Data Cloud (automatic, part of the live run)
  5. Verify CRMA — re-query dashboard aggregates and check against expected ranges
  6. Confirm CRMA dashboards render — check for two known CRMA quirks
  7. Confirm Tableau Next — app provisioned, Data Cloud streams actually ingesting
  8. Report back: what was inserted, run_id, verify/confirm results, anything needing manual attention
```

If the user chose CRMA only, drop step 7. If Tableau Next only, drop steps
5–6 (there is no separate `verify` check for Tableau Next beyond the
provisioning/ingestion confirmation in step 7 — say this plainly rather
than inventing one). If E was answered "already confirmed working," drop
whichever of 6/7 apply and say so in the agenda.

## Step 1 — Prerequisites

Read the "Prerequisites" and "Deploying to a new org → 1. Prerequisites
checklist" sections of `README.md`. `sf` CLI auth and the local Python
environment were already confirmed in questions A/B above — no need to
recheck those. Confirm:

- `Case.External_ID__c`, `Case.Time_Open__c`, `Case.CSAT__c`,
  `Task.LastModifiedDate__c` exist on the target org (query field
  describes, or ask the user to confirm if you don't have direct API
  access to check). These are required regardless of which app(s) are in
  scope — the generator sets them on every Case/Task it inserts.
- If CRMA is in scope: the CRM Analytics Service Analytics app (dataflow +
  dashboards) is already installed.
- If Tableau Next is in scope: the Service Insights app is already
  provisioned, and Data Cloud has data streams sourced from Case/
  EmailMessage/CaseArticle/Task.
- This tool does not install either app itself, and does not provision
  Data Cloud streams — it only loads data into an org that already has
  them.

If a required *field* is missing, stop and tell the user what to fix
before continuing — that will make the load itself fail, not just one
app's confirmation.

If an entire *app* (CRMA's dataflow, or Tableau Next's Service Insights
app / Data Cloud streams) is missing for the chosen scope, that's a softer
stop: tell the user plainly that the load will still succeed, but that
app's downstream refresh will report "not found"/"skipping" (see the
non-fatal cases listed above) and its confirmation steps (5–6 or 7) will
have nothing to check. Ask whether they want to proceed anyway — e.g. to
just generate baseline Case data before the app gets installed later — or
narrow scope to the app(s) that are actually present, or stop to get the
missing app installed first. Don't decide this for them.

## Step 2 — Dry run

```bash
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> run --profile <profile>
```

This only writes to `data/dry-runs/` — no Salesforce API calls. Show the
user the printed summary (volumes, distributions) before proposing to go
live.

## Step 3 — Live run (requires explicit confirmation)

This step inserts real records into the target org. Before running it,
state plainly what will be created (approximate record counts by object,
based on the dry run) and get explicit user confirmation — this is exactly
the kind of action that requires pausing for, even though the tool's own
`BatchGuard` makes it safely undoable.

```bash
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> run --profile <profile> --live --yes --wait-for-crma
```

`--wait-for-crma` blocks until the CRMA dataflow job finishes — needed if
CRMA verification (Step 5) is in scope; harmless to include even if CRMA
isn't installed (it just resolves quickly to `NOT_FOUND`) or if scope is
Tableau Next only. Record the `run_id` this prints — you'll need it for
verify and any future undo.

## Step 4 — Downstream refresh

This happens automatically as part of the live run above (CRMA local
replication → CRMA dataflow → Data Cloud data streams, in that order — see
README's "Downstream refresh" section for what each does and why the order
matters, and why it can't be split by app). Read the printed output
carefully and relay any "not found"/"skipping" lines to the user as
informational, not as errors — see the non-fatal cases listed above. Note
the CRMA dataflow job's final status for Step 6.

## Step 5 — Verify CRMA (skip entirely if scope is "Tableau Next only")

```bash
PYTHONPATH=src python3 -m service_insights_data_import --org <alias> verify <run_id>
```

Report the pass/fail summary to the user. If anything fails, do not
proceed to a patch without first re-reading README's "Deploying to a new
org → 3. Check for the two known CRMA symptoms" section — a failure here
can also just mean a stale dataset version (see that section) rather than
a real problem; re-check before assuming a bug.

## Step 6 — Confirm CRMA dashboards render (skip if scope is "Tableau Next only", or if question E was answered "already confirmed working")

Follow README's "Deploying to a new org" section, steps 3–4, in full:

- Check the CRMA dataflow job status text (not just "Warning" vs
  "Success") for the two known symptoms (blank/near-empty "Service Open
  Cases" scatter chart; `sum_last_activity` clustered near 0).
- If either symptom is genuinely present (confirmed against a freshly
  re-fetched dataset version, not a stale one — see README), **stop and
  ask the user** before applying the manual dataflow/dashboard patch
  described in README step 4 — that's a live PATCH to a shared org asset
  and needs the same backup-first discipline and explicit go-ahead as any
  other hard-to-reverse change. Do not apply it silently.

## Step 7 — Confirm Tableau Next (skip if scope is "CRMA only", or if question E was answered "already confirmed working")

Follow README's "Deploying to a new org → 5. Confirm the Tableau Next
side" section:

- Confirm the Service Insights app is provisioned
  (`GET /services/data/v{ver}/tableau/dashboards`, check
  `templateSource.name`). If no dashboards come back at all, the app isn't
  provisioned on this org — tell the user rather than treating it as a
  data issue.
- Confirm Data Cloud is actually ingesting, not just fired-and-forgotten
  (`GET /services/data/v{ver}/ssot/data-streams`, check
  `lastRefreshDate`/`lastRunStatus` for the relevant streams). If this
  returns no streams sourced from Case/EmailMessage/CaseArticle/Task at
  all, that matches the "No matching Data Cloud data streams found"
  message from Step 4 — tell the user Data Cloud isn't set up to ingest
  this data yet, rather than assuming the load failed.
- Cross-check against README's "Known blockers" table — Omni-Channel and
  Tableau Next CSAT tiles stay blank on every org regardless of data
  volume; that's expected, not a failure of this checklist.

## Step 8 — Report back

Summarize for the user: org, profile, run_id, record counts inserted,
which app(s) were in scope, verify/confirmation results for each
(including any "not found"/"not provisioned" findings from Steps 1, 4, 6,
or 7), and anything that needed manual attention or is still open. Do not
commit, push, or otherwise touch git as part of this skill unless the user
separately asks.

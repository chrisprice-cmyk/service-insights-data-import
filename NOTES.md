# Project Notes

## Org / Semantic Model

- Target org: alias `Prime_SDO` (username `trailsignup.d3d6728ea51c14@salesforce.com`, orgId `00DKA000000H2yN2AS`).
  Originally aliased `imperial-crma`; renamed since this org is now being used for the Service Insights build.
- Service Insights app: `Service_Insights_App_07_23_2026`.
- Semantic models found (via `sf api request rest`, since the Tableau Next MCP connector is
  locked to a different org — see "Tooling constraints" below):
  - `C360SemanticModel_c360` (base C360 model, locked)
  - `Service_Insights_SDM_fd7` / `Service_Insights_SDM_fd71` (locked, 2nd layer)
  - `Extended_Service_Insights_SDM_fd7` / `Extended_Service_Insights_SDM_fd71` (editable, 3rd layer)
  - **Note:** there are duplicate `_fd7` / `_fd71` pairs, created minutes apart on 2026-07-23 —
    looks like the Service Insights app setup was run twice. Worth cleaning up / confirming
    which pair is actually wired to the live dashboards before doing further work.

## Data gaps identified (as of 2026-07-23)

Already populated: Case (180), Account (91), Contact (144), User (113), ServiceAppointment (241),
WorkOrder (322), ServiceTerritory (11), OperatingHours (22), EmailMessage (46), Survey (10),
SurveyVersion (11), SurveyQuestion (35).

Empty (0 rows): **AgentWork**, CaseComment, SurveyInvitation, SurveySubject, SurveyResponse,
SurveyQuestionResponse.

These gaps directly explain blank/empty metrics on dashboards:
- AgentWork = 0 rows → Speed to Answer, Avg Handle Time, Avg Wait Time, SLA Adherence, Declined/Accepted Items all blank (see calculated measures `My_Speed_to_Answer_Minutes_clc`, `Avg_Wait_Time_Hours_SI_clc`, `Speed_To_Answer_Minutes_clc`, `Work_Item_SLA_Adherence_SI_clc`).
- SurveyInvitation/SurveySubject/SurveyResponse/SurveyQuestionResponse = 0 rows → CSAT blank
  (see `Avg_CSAT_for_Case_SI_clc`).

## ⚠️ BLOCKER: Survey/CSAT data cannot be bulk-seeded via normal means

Investigated how to programmatically create `SurveyResponse` and `SurveyQuestionResponse`
records (the objects that drive CSAT metrics). Findings:

- Described both objects via API (`sf sobject describe`): **every field on both objects is
  `createable=false` and `updateable=false`**. Standard SObject `insert()` / Data Loader /
  Bulk API 2.0 cannot write to them directly.
- These are part of Salesforce Feedback Management (Surveys), which appears to route response
  submission through a real-time capture flow (survey-taking UI / Connect API tied to a live
  invitation session), not a documented batch-insert path.
- Researched Connect REST API (`/connect/surveys/...`) and `ConnectApi.Surveys` Apex namespace —
  could not confirm a documented, supported bulk/backfill submission endpoint or method
  signature from official Salesforce docs. This needs a more thorough deep-dive (developer.salesforce.com
  authenticated docs, or a Salesforce Support/SE escalation) — treat prior research as
  inconclusive, not a final "impossible" verdict.
- Ruled out: Data Loader, Bulk API 2.0 (both exclude non-createable objects), manual UI seeding
  is the only officially-documented path today, which doesn't scale to "hundreds of realistic
  responses."

**Action for later:** figure out a supported or semi-supported way to backfill realistic CSAT
survey response volume (e.g. via the actual survey-taking UI at small scale, browser automation
against that UI, an internal/undocumented API used by SE tooling, or escalating to Salesforce
Support for sandbox-only relaxation of the createable restriction). Until resolved, CSAT-related
dashboard tiles will stay empty no matter what we do to Case/Account/Contact data.

## Tooling constraints encountered

- The Tableau Next MCP connector (`mcp__tableau-next-trailsignup-6d45c4fe716033__*`) is hard-wired
  to org `trailsignup.6d45c4fe716033@salesforce.com` (alias `nr-demo`), not `Prime_SDO`. Can't be
  repointed via alias tricks — needs a separate MCP authorization if we want native access to
  Prime_SDO's semantic model via that tool.
- Workaround in use: `sf api request rest` against `/services/data/v67.0/ssot/semantic/models/...`
  directly, targeting `Prime_SDO` by alias. This works fine for read-only semantic model
  inspection (data objects, relationships, calculated measures).
- The `salesforce-dx` MCP tool's `run_soql_query` did **not** recognize the `Prime_SDO` alias or
  even the full username, despite `sf org list --all` showing it as Connected. Root cause unclear
  (possibly a separate org allow-list in that MCP server's startup config). Fell back to
  `sf data query` via the CLI directly for SOQL, which works fine.

## Dashboard being targeted first: "Cases" (Cases1)

URL: `https://trailsignup-d3d6728ea51c14.lightning.force.com/tableau/dashboard/Cases1/edit`

Full layout (confirmed by scrolling the whole rendered dashboard, not just the top fold):
- Filters: Created Date (default Last 30 Days), Case Origin, Case Type, Case Priority,
  Contact Reason, Service Reps.
- **Service Health** panel — Escalated Cases, Open Cases, CSAT (3 KPI tiles)
- **Resolution Trends** panel — % First Time Resolution, Avg. Time to 1st Close, Avg. Time to Close (3 KPI tiles)
- **Team Pressure** — Channel x Case Status heatmap, Case Volume Low/High
- **Cost and FCR Trends** — First Contact Resolution % vs Avg. Cost scatter, by Case Created Date
- **Team Impact / "What should I focus on?"** — tabs: Escalated, Open, CSAT, All (Service Reps stacked bar)
- **Top Case Escalations and Priority** — Contact Reason x Case Priority table
- **What causes friction?** — Contact Reason stacked bar by Case Status
- **What cases are the highest cost?** — Contact Reason vs Cost scatter
- **Total Cases** / **Total Cases Closed** KPI tiles
- **Case Trend by Status** — stacked area by Case Created Date
- **Where is the traffic coming from?** — Case Origin donut
- **Case Satisfaction** panel — Satisfaction Trend, Case Origin, Score by Priority (3 tiles)
- **Service Rep Performance** — Highest Avg Time to Close, Lowest Avg 1st Time to Close, Highest First Call Resolution %

### Tile-by-tile status (as of 2026-07-23, Last 30 Days filter, org has 180 seed Cases all created 2026-06-24)

**Populated / working now:** Open Cases (128), Avg. Time to 1st Close (21.4h), Avg. Time to Close (21.59h),
Team Pressure heatmap, Team Impact "Open"/"All" tabs, "What causes friction?", Total Cases (180),
Case Trend by Status, "Where is the traffic coming from?", Total Cases Closed (52), Service Rep Performance's
"Highest Avg Time to Close" and "Lowest Avg 1st Time to Close" charts.

**Blank/zero, with confirmed root cause (10 tiles, 3 root causes):**

1. **`Case.IsEscalated` boolean is false on all 180 Cases** (even the 3 with `Status = "Escalated"` —
   status and the IsEscalated flag are independent fields; the semantic model's escalation measures all
   key off `IsEscalated`, not `Status`). Breaks:
   - Escalated Cases KPI (Service Health) = 0
   - Team Impact → "Escalated" tab = No results
   - Top Case Escalations and Priority table = all zeros
   - Calculated measures: `Escalated_Cases_clc`, `Escalation_Rate_clc`, `My_Escalated_Cases_SI_clc`

2. **`AgentWork` = 0 rows**, so `Cost_SI_clc` (`{FIXED Case.Case_Id : SUM(AgentWork.Active_Time)} / 3600 * Agent_Cost_prm`)
   has nothing to sum per Case. Breaks:
   - Cost and FCR Trends chart (empty on both axes, not just zero)
   - "What cases are the highest cost?" chart (empty)
   - Also blocks Speed to Answer / SLA measures used elsewhere (see Data gaps section above)

3. **Only 46 `EmailMessage` rows exist across 180 Cases** (52 of which are closed). `FCR_Flag_clc` only
   fires when `Case.IsClosed = true` AND that Case has **exactly one** related EmailMessage
   (`Email_Count_clc = {FIXED Case.Case_Id : COUNT(Email_Message.Email_Message_Id)}`). Almost no Case
   currently satisfies both conditions. Breaks:
   - % First Time Resolution KPI (Resolution Trends) = 0%
   - Service Rep Performance → "Highest First Call Resolution %" = all 0%
   - Calculated measures: `FCR_Flag_clc`, `First_Contact_Resolution_Percentage_clc`, `My_First_Contact_Resolution_Percentage_SI_clc`

**Blank, blocked on the Survey/CSAT issue (4 tiles)** — see blocker section above:
- CSAT KPI (Service Health) = "–"
- Team Impact → "CSAT" tab = No results
- Case Satisfaction panel — all 3 tiles (Satisfaction Trend, Case Origin, Score by Priority) = No results

### Fix plan for this dashboard (dependency order)

1. Flip `IsEscalated = true` on a realistic subset of Cases (e.g. the 3 already `Status = Escalated`,
   plus more for volume/variety across Contact Reason and Priority).
2. Create `AgentWork` records tied to Cases (also feeds Speed to Answer/SLA measures on other dashboards).
3. Attach exactly one `EmailMessage` to a realistic subset of closed Cases, to move FCR% off 0%.
4. CSAT/Survey chain stays blocked until the API blocker above is resolved — explicitly deferred.

Steps 1–3 fix 6 of the 10 blank tiles; CSAT-driven tiles (4) remain blank until step 4 is unblocked.

## Repo

Public repo created for this project: https://github.com/chrisprice-cmyk/service-insights-data-import
(personal account `chrisprice-cmyk`, chosen over the internal `chrisprice_sfemu` account since the
goal is a reusable tool other people can pick up).

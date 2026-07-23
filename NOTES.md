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

## Historical Case cohort — generation design (confirmed 2026-07-23)

Goal: give the Cases dashboard genuine time-series/trend variance (Avg Time to
Close/1st Close, YoY, Case Trend by Status, etc.) by adding a large, historically
spread batch of new Cases. **Strictly additive** — the existing 180 seed Cases
(all created 2026-06-24) are left completely untouched, no updates or deletes.

- **Volume:** 2,500 new Case records.
- **Date spread:** `CreatedDate` distributed across the trailing 24 months, mild
  seasonality (slight dip in Dec, slight bump in Jan/Sep) rather than pure uniform
  random, so month-over-month/YoY charts look organic.
- **Status / close mix:** ~85% closed, ~15% open/in-progress (New, Working, Waiting
  on Customer, Escalated). Open cases skew toward recent CreatedDates (an 18-month-old
  Case still "New" would look broken).
- **Close-date lag:** for closed Cases, `ClosedDate = CreatedDate + lag`, where lag is
  drawn from a distribution that varies by Priority (Critical/High resolve faster on
  average, Low slower) plus noise — this is what drives believable Avg Time to
  Close/1st Close spread.
- **Field flavor:** reuse the existing 180 Cases' distributions so new records blend in —
  Origin (Chat-heavy, some Phone/Email/Website/social), Type (Product Support/Account
  Support/General, ~45% null matching current rate), Priority (Medium-heavy, Critical rare).
- **Dashboard fixes layered in at generation time (same pass, not a separate follow-up):**
  1. `IsEscalated = true` on a realistic subset (Status=Escalated cases plus more for
     volume/variety across Contact Reason and Priority). ✅ Viable — plain field set on insert.
  2. ~~`AgentWork` records created tied to each new Case.~~ ❌ **Blocked** — see new blocker below.
  3. Exactly one `EmailMessage` attached to a realistic subset of closed Cases (drives FCR%). ✅ Viable.
- CSAT/Survey chain remains explicitly deferred (see blocker section above).
- Audit-field backdating confirmed viable via test insert (see "Errors and fixes" — Case.CreatedDate
  is createable=true and the org's "Set Audit Fields upon Record Creation" permission is enabled).

## ⚠️ BLOCKER: AgentWork cannot be bulk-seeded via normal insert either

Same category of problem as the Survey/CSAT blocker above, discovered while designing the
historical Case cohort's AgentWork fix:

- Test insert (`sf data create record -s AgentWork -v "UserId=... WorkItemId=<CaseId>
  ServiceChannelId=<Cases channel Id>"`) failed with `FIELD_INTEGRITY_EXCEPTION: The agent's
  status is not associated with the channel for this work.` — AgentWork rows are only created
  by the live Omni-Channel routing engine when a real agent is actively in a Presence status
  on that channel. Not a plain-insert-friendly object.
- Even if that validation were worked around (e.g. scripting a Presence status change first),
  the fields the Cost/Speed-to-Answer measures actually depend on — `Status`, `ActiveTime`,
  `HandleTime`, `AcceptDateTime`, `CloseDateTime` — are all **createable=false**. A successful
  insert would still leave those null/zero.
- **Decision:** drop AgentWork seeding from the historical-cohort generation pass. Cost and FCR
  Trends / "What cases are the highest cost?" / Speed to Answer / Avg Handle Time / SLA
  Adherence tiles remain blocked, grouped with the CSAT/Survey deferral for future investigation
  (possible paths: real Omni-Channel Presence scripting via browser automation at small scale,
  or a Support/SE escalation, same as the Survey approach).

**Tooling decided:** Python + Bulk API 2.0, via the `simple-salesforce` library (installed locally
with `pip3 install --user simple-salesforce`; `SFBulk2Type.insert()` takes `records: List[Dict]`
plus `batch_size`/`concurrency`/`wait` params — this is what the loader will call).

## Field templates captured from the existing 180 Cases (for the new cohort to match)

- **Origin:** Chat=90, Community=10, Email=18, Mobile Device=8, Phone=27, Website=8, Facebook=4,
  Instagram=2, LinkedIn=2, Twitter=9, Case=1, Text=1.
- **Type:** Product Support=27, Account Support=38, General=33, Technical Issue=1, null=81.
- **Priority:** Critical=8, High=28, Low=24, Medium=120.
- **Status:** New=103, Closed=52, Working=15, Waiting on Customer=7, Escalated=3.
- **Reason:** null=116, Problem Resolved=52, New problem=6, Feature Request=4, Documentation Issue=1,
  Mail delivery issue=1.
- **BusinessHoursId:** existing Cases all use the org default `01mKA000000Gp9GYAS` ("24/7
  Follow-The-Sun Service") — reuse this for new Cases too, avoids needing per-region logic.
- **OwnerId pool** (8 users): `005KA000000Uj9UYAS` (Automated Process, 64), `005KA0000013WMCYA2`
  (Chris Price, 27), `005KA000000UjAOYA0` (Tim Service, 24), `005KA000000UjAPYA0` (Quentin Engineer, 16),
  `005KA000000UjAQYA0` (Linda Service, 15), `005KA000000UjANYA0` (Steven Service, 13),
  `005KA000000UjARYA0` (Jay Service, 11), `005KA000000UjASYA0` (Brenda Service, 9).
- **CreatedById:** existing Cases use only 2 values — `005KA0000013WMCYA2` (116) and `005KA000000Uj9UYAS`
  (64). Reuse this pair for new Cases' CreatedById (separate from OwnerId).
- **AccountId/ContactId:** only 96 of 180 existing Cases have a non-null Account/Contact pair (rest are
  null — fine to leave a similar fraction null on the new cohort). Org has 91 Accounts / 144 Contacts
  total; Contact.AccountId gives valid Account/Contact pairs to draw from when a new Case needs one.
- **Subject/Description flavor:** short, realistic per-Type subject lines exist as samples in this
  session's scrollback (e.g. "Please expedite my order.", "Turbine not reaching operating speed",
  "How do I obtain your annual report?") — reuse this style when generating new Subjects; note
  `Description` is not SOQL-filterable (can't `!= null` it) so exact fill-rate wasn't measured, treat
  as optional/sparse like the original data.

## EmailMessage field notes (for the FCR fix)

Createable fields confirmed via describe: `ParentId` (→ Case), `CreatedById`, `CreatedDate`,
`LastModifiedDate`, `LastModifiedById`, `TextBody`, `HtmlBody`, `Subject`, `FromAddress`, `ToAddress`,
`Incoming`, `Status` (required, picklist), `MessageDate`, `FromId` (→ Contact/Lead/User). Plan: one
EmailMessage per FCR-eligible closed Case, `ParentId` = the Case, dated shortly after CreatedDate.

## Project scaffold started

Created `src/service_insights_data_import/` (Python package, empty so far) and `data/` (for any
CSV/lookup files the generator needs) under the project root. Not yet committed. `simple-salesforce`
installed locally via `pip3 install --user simple-salesforce` for prototyping — **not yet added to
a requirements.txt/pyproject.toml** (still needs proper packaging).

## ⏸️ Paused here (2026-07-23) — resume point

Session paused mid-scaffolding at user's request (laptop shutdown for power). Nothing destructive in
flight; org (Prime_SDO) untouched beyond the two throwaway test inserts (Case, already deleted) and
one intentionally-failed AgentWork test insert (which never actually created a record, per the
FIELD_INTEGRITY_EXCEPTION above).

**Next steps to pick back up:**
1. Turn the `src/service_insights_data_import/` scaffold into real modules: a config/constants module
   holding the field-template distributions above, a `generate_cases.py` (builds the 2,500-record
   list per the design in "Historical Case cohort — generation design" above), a
   `generate_email_messages.py` (FCR fix), and a `load.py` wrapping `simple_salesforce.bulk2` for the
   actual inserts (with a `--dry-run` flag that just writes the generated records to CSV under `data/`
   instead of hitting the org, and a hard safety check that it only ever INSERTs, never
   updates/deletes, to honor the "leave the existing 180 Cases alone" constraint).
2. Add a `requirements.txt` (simple-salesforce) and a small CLI entrypoint.
3. Dry-run first, eyeball the generated CSV for realism, then live-run against Prime_SDO.
4. Re-check the Cases1 dashboard tiles after the load (Total Cases, Total Cases Closed, Avg Time to
   Close/1st Close, Escalated Cases, % First Time Resolution, Case Trend by Status, Where is the
   traffic coming from — expect these to visibly improve; Cost/FCR-cost tiles and CSAT tiles remain
   blocked per the two documented blockers above).
5. Commit the working generator + docs, push to GitHub.

## Repo

Public repo created for this project: https://github.com/chrisprice-cmyk/service-insights-data-import
(personal account `chrisprice-cmyk`, chosen over the internal `chrisprice_sfemu` account since the
goal is a reusable tool other people can pick up).

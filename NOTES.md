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

## Calculated-fields audit (2026-07-24) — do our planned fields feed every relevant measure?

Requested by user: walk every calculated measure/dimension in `Extended_Service_Insights_SDM_fd7`
and confirm the underlying CRM fields we plan to populate actually satisfy them.

**Confirmed OK, no changes needed:**
- Escalation family (`Escalated_Cases_clc`, `Escalation_Rate_clc`, `My_Escalated_Cases_SI_clc`) →
  `Case.Escalated` (IsEscalated). Matches plan (step 1 of fix plan).
- FCR family (`FCR_Flag_clc`, `First_Contact_Resolution_Percentage_clc`) → `Case.Closed` +
  `Email_Count_clc` (COUNT of related EmailMessage via `ParentId`) — fires only when a closed
  Case has **exactly one** EmailMessage. Matches plan (step 3).
- Cost/Speed-to-Answer/Handle-Time family → all depend on `AgentWork.ActiveTime/HandleTime/etc.`
  — already known-blocked, no new info.
- "Avg Time to Close" (`Avg_Time_to_Close_Hours_clc` → `BH_TimeToClose_clc`) → cleanly depends on
  `Case.Created_Date` / `Case.Closed_Date_Time` + Operating Hours boundaries. Matches plan.

**New finding — changes the generation design:**
- "Avg Time to 1st Close" (`Avg_Time_to_1st_Close_Hours_clc` → `BH_TimeToFirstClose_clc` →
  `First_Close_Date_clc`) is defined as:
  `IF [Case_Update].[Status] = "Closed" THEN {FIXED [Case_Update].[Case] : MIN([Case_Update].[Previous_Update_Date])} END`
  — i.e. it reads the **`Case_Update` DMO**, which is fed by Salesforce `CaseHistory`, not
  `Case.ClosedDate` directly.
- **Verified empirically (test Case created and deleted, org otherwise untouched):**
  - Inserting a Case directly with `Status='Closed'` set at create time produces **no `CaseHistory`
    row for the `Status` field** (only Owner/Asset/created noise rows). `First_Close_Date_clc`
    would stay null for every Case built this way.
  - Creating a Case as `Status='New'`, then issuing a **separate** `UPDATE Status='Closed'` DML
    call, **does** produce a real `CaseHistory` row (`Field='Status', OldValue='New',
    NewValue='Closed'`), which Data Cloud can sync into `Case_Update`/`Previous_Update_Date`.
  - Also confirmed: `ClosedDate` cannot be set directly via update (`INVALID_FIELD_FOR_INSERT_UPDATE`
    — it's system-derived once Status moves to a closed value); only settable at **insert** time.
    So the sequence has to be: insert with `ClosedDate` pre-set (createable) + `Status='New'`, then
    a second update flips `Status='Closed'` to generate the history row the metric needs.
- **Design change required:** the Case generator cannot be a single Bulk API insert pass for
  closed Cases. It needs two passes: (1) bulk insert all 2,500 Cases as Open/New with
  `CreatedDate` and `ClosedDate` pre-set on the ones destined to be closed, (2) a second bulk
  **update** pass that flips `Status` to the target closed value for that subset, in a separate
  transaction, to generate the CaseHistory row `Case_Update` depends on. `CreatedDate` on the
  update call should be left alone (already fixed by audit-field permission at insert); only
  `Status` needs to move.
- Note: the `CreatedDate` of the resulting `CaseHistory` row is "now" (real wall-clock time of the
  update), not backdated — this is expected and fine; the semantic model only needs
  `Previous_Update_Date` to exist and be resolvable per-Case, not to be historically accurate to
  the same backdated window. Worth eyeballing this on the dashboard once loaded, but no known
  Salesforce mechanism exists to backdate CaseHistory.CreatedDate on a plain update.

**Out-of-scope family discovered (needs user confirmation, not yet actioned):**
- A set of Knowledge-Article-attachment measures (`Cases_With_Knowledge_Attachments_SI_clc`,
  `Case_Attachment_Rate_SI_clc`, `Knowledge_Time_To_Close_P10/P90_SI_clc`, and ~9 others) depend on
  `Knowledge_Engagements_with_Linked_Knowledge_lv` — not part of the Cases1 tile inventory we
  documented. Likely feeds a Knowledge/Case-Attachment view not currently in scope. Flagged, not
  yet built or ignored by explicit agreement.

## Other two dashboards in the Service Insights app (2026-07-24)

Full app has 3 dashboards, all in workspace `Service_Insights1` (confirmed via
`/services/data/v67.0/tableau/dashboards`): **Cases** (`Cases1`, already fully mapped above),
**Omni-Channel** (`Omni_Channel1`), **My Service Performance** (`MyPerformance1`).

### Omni-Channel (`Omni_Channel1`) — 58 widgets

Entirely Omni-Channel/AgentWork-driven. Every metric and visualization traces back to
`AgentWork`/Presence data: Total Work Items, Cost to Serve, Accepted/Declined Work Items, Avg
Wait Time, Omni Utilization (+ Max), Avg Handle Time — plus visualizations for Queue by Avg
Handle/Wait Time, Queue by Cost to Serve, Service Reps by Utilization/Handle Time/Wait Time, Work
Volume by Status/Channel, Routing Effectiveness, Category by Time, Cost by Channel, Detailed Table.

**Verdict: 100% blocked by the existing AgentWork blocker.** Case/EmailMessage generation gives
this dashboard zero benefit. Nothing to build here until the AgentWork/Presence-scripting problem
is solved (same blocker as Cost/FCR-cost tiles on Cases1).

### My Service Performance (`MyPerformance1`) — 73 widgets

A "my work" personal-performance view (filtered to the logged-in Service Rep via a Service Reps
parameter), **genuinely hybrid**:

- **Case-driven (benefits directly from our generator, same fields as Cases1):** Total Cases, Open
  Cases, Total Cases Closed, Escalated Cases, Avg. Time to Close, Avg. Time to 1st Close, % First
  Time Resolution, plus visualizations: Case by Channel, Case by Priority, Cases Detail Table,
  Case Efficiency, Case Trend, Time to Close by Channel, Time to Close by Priority. (7 metrics + 7
  visualizations.)
- **Omni/AgentWork-driven (blocked, same as Omni-Channel dashboard):** Total Work Items, Accepted
  Work Items, Declined Items, Avg. Wait Time, Avg. Speed to Answer, Avg. Handle Time, plus Omni
  Efficiency Trend, Avg Handle Time vs Channel, Omni Detailed Table, Presence Status Duration, Max
  Omni Utilization, Omni Utilization. (6 metrics + 6 visualizations.)

**Verdict:** roughly half of this dashboard improves automatically once the Case/EmailMessage
generator runs (same underlying Case data, just filtered to whichever Owner is viewing) — no
separate work needed. The other half is blocked by AgentWork, same root cause as Omni-Channel.
Because it filters by Owner, the generator's existing OwnerId-pool distribution (8 users) matters
here: each rep needs a plausible personal case load, not just an even split — current design
(reuse the real 180-Case Owner distribution) already gives that.

## Reframe (2026-07-24): build for reuse by other SEs, not just Prime_SDO

User's direction: this tool should work well enough that other SEs deploying the Service Insights
app in their own orgs can pick it up and run it — not a one-off fix for Prime_SDO. Design
implications, not yet built:

- **No hardcoded org-specific IDs.** Prime_SDO-specific record Ids used so far (OwnerId pool,
  BusinessHoursId, CreatedById pair, ServiceChannel Id, Account/Contact pairs) must become
  **runtime lookups** against whichever org the tool is pointed at (SOQL queries at startup: active
  Users, default BusinessHours, existing Accounts/Contacts), not constants baked into config.
  Distribution *shapes* (percentages/weights) can stay as defaults, but the actual Ids must be
  discovered per-org.
- **Config-driven, not hardcoded volume/date range.** Cohort size (2,500) and lookback window (24
  months) should be CLI flags/config values with sensible defaults, since another SE's org may
  already have a different seed volume or want a different window.
- **Two-step Case creation is now a required loader primitive**, not a one-off: bulk insert Open
  Cases (with `ClosedDate` pre-set where applicable) → bulk update `Status` to closed values for
  the target subset, per the CaseHistory finding above. The loader needs this as a built-in
  pattern, not something re-derived by each user of the tool.
- **Safety must be self-evident to a stranger running this against their own org**: dry-run mode
  (CSV preview, no API calls), an explicit insert-only guarantee (never touches existing rows),
  and a pre-flight summary (org name, existing Case count, planned insert count) with a
  confirmation prompt before the live Bulk API run.
- **Document the two known permanent blockers up front** (AgentWork/Omni-Channel dashboard, CSAT/
  Survey tiles) in the README so a new SE doesn't waste time thinking the tool should have fixed
  them — it can't, for the platform reasons documented above.
- Needs a clear README aimed at a first-time user: prerequisites (Python 3.x, `simple-salesforce`,
  an authenticated `sf` CLI org alias or equivalent), what the tool does/doesn't do, how to point
  it at a different org, how to run dry-run vs live.

---

# Track 2: CRMA Service Analytics (2026-07-24)

**Kept deliberately separate from the Tableau Next "Service Insights" analysis above.** Same org
(Prime_SDO), different app, different underlying architecture. Goal here is to independently map
what data CRMA Service Analytics needs, then compare the two tracks side by side so we can decide
whether to ship one joined data-generation pass or two separate ones.

App: **CRM Analytics — Service Analytics**, `https://trailsignup-d3d6728ea51c14.lightning.force.com/analytics/application/00lKA000000tPGnYAM/edit`
(folder id `00lKA000000tPGnYAM`, workspace label "Service Analytics").

## Architecture — how this differs from Tableau Next

CRMA does **not** use the Data Cloud DMO/semantic-model layer at all. Instead:

- A **Wave dataflow** (`Service_Analytics_eltDataflow`, id `02KKA000000cN2b2AE`) runs `sfdcDigest`
  extracts directly against CRM SObjects (Case, CaseHistory, AgentWork, Task, Event,
  LiveChatTranscript, LiveChatTranscriptEvent, UserServicePresence, Opportunity, Knowledge__kav,
  Knowledge__ka, ServiceChannel, ServicePresenceStatus, Account, Contact, User, UserRole, Group,
  RecordType, CaseArticle, Knowledge__ViewStat, Knowledge__VoteStat, Knowledge__DataCategorySelection).
- These get joined/computed/registered into **10 Wave datasets** (folder `Service_Analytics`):
  `ServiceCase`, `ServiceCaseHistory`, `ServiceOmniAgentWork`, `ServiceChatTranscript`,
  `ServiceChatTranscriptEvent`, `ServiceActivity`, `ServiceOpportunity`, `ServiceKnowledge`,
  `ServiceKnowledgeAttached`, `ServiceOmniUserPresence`.
- Dashboards query these Wave datasets directly (SAQL/query steps), no separate metric-layer
  indirection like Tableau Next's `_clc` calculated measures. This means **field lineage is much
  more direct** here — what you see in the dataflow extract is what the dashboard gets, no
  business-hours/FIXED-aggregation chains to trace.
- Confirmed via `/services/data/v67.0/wave/dataflows/<id>` (full definition fetched, ~190 nodes)
  and cross-checked each `Register_*` node's `source` back to its `Extract_*` origin.

## App structure — 13 dashboards

Full list confirmed via `/services/data/v67.0/wave/folders/00lKA000000tPGnYAM` featuredAssets:

| Dashboard (name) | Label | Backing dataset(s) |
|---|---|---|
| `Service_Overview1` | Service Analytics Overview | ServiceCase |
| `Service_By_OpenCases1` | Service Open Cases | ServiceOpportunities, ServiceCase |
| `Service_Backlog_Analysis1` | Service Backlog | ServiceCase |
| `Service_By_TeamEfficiency1` | Service Agent Performance | ServiceCase |
| `Service_Agent_Activity1` | Service Agent Activity | ServiceActivity |
| `Service_By_EngagementEfficiency1` | Service Channel Review | ServiceCase |
| `Service_Omni1` | Service Omni | ServiceOmniAgentWork |
| `Service_Live_Agent_Chat1` | Service Live Agent Chat | ServiceChatTranscript |
| `Service_Telephony1` | Service Telephony | ServiceActivity |
| `Service_Knowledge1` | Service Knowledge Efficiency | ServiceCase |
| `Service_Knowledge_Metrics1` | Service Knowledge Usage | ServiceKnowledge, ServiceKnowledgeAttached, ServiceCase |
| `Service_Account_Profile1` | Service Account Profile | ServiceOpportunities, ServiceActivity, ServiceCase, ServiceCaseHistory |
| `Service_Customer_Satisfaction1` | Service Customer Satisfaction | ServiceCase |

**Key structural finding: 9 of 13 dashboards depend only on `ServiceCase`** (Overview, Backlog,
Team Efficiency, Channel Review, Knowledge Efficiency, Customer Satisfaction, plus contributing to
Open Cases/Knowledge Usage/Account Profile). `ServiceCase` is a near-direct extract of the `Case`
object — this is the single highest-leverage dataset in this whole app, same as Cases1 was for
Tableau Next.

## Per-dashboard findings

### CSAT — resolved cleanly, better than Tableau Next's path

CRMA's CSAT does **not** go through Salesforce Feedback Management Surveys at all (the blocked
chain from the Tableau Next track). It reads straight off a custom field:

- `Case.CSAT__c` — custom Number field, **`createable=true`**, already **100% populated** on the
  existing 180 Cases (confirmed via SOQL: `COUNT(Id) WHERE CSAT__c != null` = 180/180).
- Dataflow nodes `Case_CSAT_Mea`, `compute_AgentWorkCSAT`, `compute_LiveChatTranscriptCSAT` all
  just pass `Case.CSAT__c` through (with a `-999` sentinel for null/no-case joins).
- **This means Service Customer Satisfaction (and any other CSAT-driven tiles here) can be fully
  solved just by setting `CSAT__c` on our generated Cases** — no Survey/SurveyResponse blocker,
  no separate object chain. Genuinely easier here than on the Tableau Next side.

### Service Omni (`Service_Omni1`) — blocked, same root cause as Tableau Next

Backed by `ServiceOmniAgentWork`, which extracts `AgentWork.AcceptDateTime/ActiveTime/HandleTime/
SpeedToAnswer/Status/...` directly. **Same AgentWork blocker already documented** (org has 0
AgentWork rows; the fields needed are createable=false regardless; Omni-Channel routing engine
required for real records). No new information, but confirms the blocker applies identically here.

### Service Agent Activity + Service Telephony — new, real, and fixable gap

Both driven by `ServiceActivity`, built from `Task`/`Event` records joined to their parent Case via
`WhatId`. Checked live: **87 Tasks and 26 Events have some `WhatId` set, but 0 of either point at a
Case** (`SELECT COUNT(Id) FROM Task WHERE What.Type = 'Case'` = 0). Unlike AgentWork, this is a
**plain, fully createable gap** — Task/Event are normal SObjects, `WhatId` pointing at a Case Id is
just a lookup field. If we want these two dashboards to populate, the generator needs to also
create some Task/Event records with `WhatId` = one of our generated Case Ids (e.g. call-logging
Tasks with `CallDurationInSeconds`, `CallDisposition`). Not yet decided whether this is in scope.

### Service Live Agent Chat — separate, smaller gap

Backed by `ServiceChatTranscript`/`ServiceChatTranscriptEvent`, sourced from `LiveChatTranscript`/
`LiveChatTranscriptEvent`. Org already has real rows here (64 LiveChatTranscript, 193
LiveChatTranscriptEvent) — both objects are mostly createable (41/57 and 10/18 fields
respectively). Not audited in depth (lower priority — single dashboard, org already has some
volume), but no platform-level blocker found the way AgentWork has one.

### Service Knowledge Efficiency + Service Knowledge Usage — separate, smaller track

`Service_Knowledge1` runs off `ServiceCase` alone (benefits automatically from our Case generator,
same as the other 8 Case-only dashboards) — but its actual tiles (Attach Rate, % Has Articles
Attached) need Cases to be linked to Knowledge articles via `CaseArticle`, which our current plan
doesn't populate. `Service_Knowledge_Metrics1` additionally needs `ServiceKnowledge`/
`ServiceKnowledgeAttached`, sourced from `Knowledge__kav`/`Knowledge__ka`/`CaseArticle` — mixed
createability (`Knowledge__kav` 32/68 createable, `Knowledge__ka` 0/19, `CaseArticle` 4/11). This
lines up with the Knowledge-Article-attachment measure family we already flagged as out-of-scope
on the Tableau Next side — same underlying gap, appears on both tracks, still needs a scope
decision from you.

### Everything else (Overview, Open Cases, Backlog, Team Efficiency, Channel Review, Customer
Satisfaction, Account Profile's Case/CaseHistory portion)

All resolve to fields already on our Case generation plan: `Origin`, `Reason`, `Type`, `Status`,
`Priority`, `IsClosed`, `IsEscalated`, `CreatedDate`, `ClosedDate`, `OwnerId`, `AccountId`,
`ContactId`, `CaseNumber`, `RecordTypeId`, plus the `CSAT__c` field above. **These should all
populate correctly from the same generated Case cohort already designed for Tableau Next — no
separate generation logic needed**, just confirmed field overlap.

One extra CRMA-specific field worth setting for realism, all createable and already used by the
existing 180 Cases: `Type_of_Support__c` (85/180 filled), `Product_Name__c` (85/180 filled, but
`createable=false` — a formula/rollup, skip it), `Product_Family_KB__c` (8/180 filled, sparse is
fine), `External_ID__c` (101/180 filled), `First_Contact_Close__c` (144/180 filled — a boolean,
likely CRMA's own First-Contact-Resolution flag, worth setting deliberately rather than leaving
random, since it's a closer FCR signal than the EmailMessage-count proxy Tableau Next uses).
Three fields (`Time_Open__c`, `CreatedDate__c`, `ClosedDate__c`) exist and are createable but are
**0% filled on the existing 180 Cases** — likely legacy/unused template fields shadowing the
standard `CreatedDate`/`ClosedDate`; leave them null to match current org convention rather than
guessing they're load-bearing.

`ServiceCaseHistory` (feeding Service Account Profile's trend tiles) is a direct extract of
`CaseHistory` (7 fields) — this is a real SObject the org already has 18,974 rows in (confirmed via
`SELECT COUNT() FROM CaseHistory`), and it gets populated automatically by any Case field change,
including the Status-flip update our Tableau Next design already does for the `Case_Update`/
Avg-Time-to-1st-Close fix. **No extra work needed here — it's a side effect of the two-step
create-then-update pattern already designed for the other track.**

## Side-by-side comparison — Tableau Next Service Insights vs CRMA Service Analytics

| | Tableau Next Service Insights | CRMA Service Analytics |
|---|---|---|
| Dashboards | 3 (Cases, Omni-Channel, My Service Performance) | 13 |
| Architecture | Data Cloud DMOs + semantic model (`_clc` calculated measures) | Wave dataflow + datasets, direct SObject extracts |
| Core data need | Case + EmailMessage (for FCR) | Case only, for 9/13 dashboards |
| CSAT | **Blocked** — Salesforce Feedback Management Survey/SurveyResponse chain, all fields non-createable | **Solved** — plain `Case.CSAT__c` custom field, createable, already 100% filled |
| AgentWork/Omni | **Blocked** — Omni-Channel routing validation + non-createable metric fields | **Same blocker** — identical root cause, 1 dashboard fully blocked (Service Omni) + partial (My Service Performance / Service Agent Activity) |
| First Contact Resolution | Needs exactly-one-EmailMessage-per-closed-Case (proxy signal) | Has a dedicated `First_Contact_Close__c` boolean field already on Case — more direct, no EmailMessage dependency |
| Avg Time to 1st Close | Needs real `CaseHistory` Status-change row (two-step create+update design) | `ServiceCaseHistory` dataset is a direct `CaseHistory` extract — same two-step design produces the history rows this needs too, for free |
| Knowledge-Article scope | Flagged out-of-scope family found in semantic model, unconfirmed | Same underlying gap (CaseArticle/Knowledge linkage), affects 2 dashboards, unconfirmed |
| Extra gap not on the other track | — | `ServiceActivity` (Task/Event linked to Case via `WhatId`) — currently 0 records, needed for Service Agent Activity + Service Telephony (2 dashboards) |

**Overlap is very high**: both tracks are fundamentally "generate realistic Case records with the
right fields," and the CaseHistory-producing two-step insert-then-update pattern already designed
for Tableau Next happens to be exactly what CRMA's `ServiceCaseHistory` dataset needs too. The
divergences are narrow and additive, not conflicting:
- CRMA needs a few extra Case fields set (`CSAT__c`, `Type_of_Support__c`, `First_Contact_Close__c`,
  `External_ID__c`, `Product_Family_KB__c`) that Tableau Next doesn't touch, but setting them
  causes no harm to the Tableau Next side.
- CRMA optionally wants Task/Event records with Case `WhatId` links (2 dashboards) — genuinely new
  scope, not required by Tableau Next at all.
- Both tracks hit the identical AgentWork wall and the identical Knowledge-Article-attachment
  question mark.
- EmailMessage generation (for Tableau Next FCR) has no CRMA dependency, but doesn't conflict with
  it either.

**This looks like a strong candidate for a single joined data-generation pass** (one Case cohort,
with the union of both tracks' field requirements set at generation time) rather than two separate
tools — the "two separate deployments" version would mean generating the *same* 2,500 Cases twice
with slightly different field sets, which is wasted duplication with no isolation benefit, since
neither track's fields conflict with the other's. Final call is yours — no code committed to
either approach yet.

## Scope decisions — confirmed by user 2026-07-24

1. **Joined single deployment.** One generator, one Case cohort, superset of both tracks' field
   requirements. No separate "CRMA-only" vs "Tableau-Next-only" tool.
2. **Knowledge-Article scope: IN.** Both the Tableau Next out-of-scope family
   (`Cases_With_Knowledge_Attachments_SI_clc` etc.) and CRMA's `Service_Knowledge_Metrics1`/
   `Service_Knowledge1` tiles get addressed via `CaseArticle` linkage.
   - Org has 69 `Knowledge__kav` articles (68 Online/published) and only 16 existing `CaseArticle`
     links — plenty of published article inventory to attach to new Cases.
   - `CaseArticle` createable fields confirmed: `CaseId`, `KnowledgeArticleId`, `ArticleLanguage`,
     `ArticleVersionNumber` — a plain junction insert, no blockers. Plan: attach 1 (rarely 2)
     published Knowledge article to a realistic subset of closed Cases (drives Attach
     Rate/Knowledge-Time-to-Close measures on both tracks).
3. **Task/Event (ServiceActivity) scope: IN.** Needed for CRMA's Service Agent Activity + Service
   Telephony dashboards (currently 0 Task/Event rows link to a Case via `WhatId`).
   - `Task` createable fields confirmed: `WhatId`, `WhoId`, `Subject`, `ActivityDate`, `Status`,
     `Priority`, `OwnerId`, `CreatedDate`, `CallDurationInSeconds`, `CallType`, `CallDisposition`,
     `TaskSubtype` — all plain, insertable. `CallDisposition` has no constrained picklist values
     defined in this org (free text) so any reasonable value works.
   - Plan: create Task records (call-logging flavor, `WhatId` = generated Case, plausible
     `CallDurationInSeconds`/`CallType`) against a subset of generated Cases, dated near the
     Case's `CreatedDate`.

Net effect: the generator now produces (per closed Case, layered): Case → optional EmailMessage
(FCR, Tableau Next) → optional CaseArticle link (Knowledge attach) → optional Task (call activity,
CRMA) → Status-flip update (CaseHistory, both tracks). All additive, all confirmed createable, no
platform blockers in this expanded scope. Remaining permanent blockers unchanged: AgentWork/Omni
(both tracks) and Salesforce Feedback Management Survey/SurveyResponse (Tableau Next CSAT only —
CRMA's CSAT is unaffected, see `Case.CSAT__c` finding above).

## Additional build requirements — confirmed by user 2026-07-24 (all four accepted)

Suggested proactively, all four accepted for this build (not deferred):

1. **Idempotency / batch marker.** Every record this tool creates gets tagged with a recognizable
   batch identifier — plan: reuse `Case.External_ID__c` (createable, already exists, currently
   101/180 filled on organic data so partial reuse is fine) with a value like
   `SI-GEN-<run-timestamp>`, or a dedicated custom field if `External_ID__c` turns out to collide
   with other tooling. On startup, the tool queries for existing `SI-GEN-*` batches and offers to
   skip/top-up/report rather than blindly re-running. This also gives a safe, explicit way to
   identify (and later delete, if ever needed) a specific generated batch without touching organic
   Case data.
2. **Enforced additive-only guarantee, at the code level, not just documented intent.** The loader
   must refuse — as a hard assertion, not a comment — to send any UPDATE or DELETE against a Case
   Id that isn't in the batch it just inserted in the same run. The only UPDATE this tool ever
   issues is the Status-flip on its own freshly-inserted Cases (see CaseHistory design above); it
   should be structurally incapable of touching the original 180 seed Cases or any other existing
   data.
3. **Built-in `--verify` post-load check.** After a live run, re-query the key aggregates that
   both tracks' dashboards actually use — Total Cases, Escalated Cases, EmailMessage-per-closed-Case
   rate, CaseArticle-linked-Case count, Task-linked-to-Case count, CSAT__c fill rate — and print a
   pass/fail summary against expected ranges. Lets an SE (or CI) confirm the load worked without
   manually opening every dashboard.
4. **Named `--profile` presets.** `quick` (small smoke-test volume, e.g. 200 Cases / 3 months),
   `standard` (the 2,500 / 24-month default this project was scoped around), `enterprise` (larger
   volume for a "mature org" demo story, e.g. 10,000 / 36 months) — thin wrappers over the same
   underlying config flags, so most users never need to touch raw volume/window numbers directly.
5. **README symptom→cause table.** A single table mapping "if dashboard tile X is still blank
   after running this tool, here's why" — covering every tile affected by the two permanent
   blockers (AgentWork/Omni-Channel: Cases1 Cost/FCR-cost tiles, Omni-Channel dashboard, My Service
   Performance's Omni half, CRMA's Service Omni + Service Agent Activity/Telephony Omni-adjacent
   tiles; Survey/SurveyResponse: Tableau Next CSAT tiles only, not CRMA's `CSAT__c`-based tiles) —
   so future SEs don't have to re-derive this from scratch.

## ClosedDate vs CaseHistory conflict — resolved (2026-07-24)

Before writing any generator code, re-verified the two-step Case design end-to-end and found a
real conflict between it and the original "Avg Time to Close" design, not just a re-confirmation
of earlier findings:

- **`ClosedDate` can only be set at INSERT time, and only if `Status` is already a closed value in
  that same insert call.** Verified: inserting with `Status='New'` and `ClosedDate=<backdated>`
  set simultaneously **silently drops** the `ClosedDate` (comes back null) — Salesforce does not
  error, it just ignores the field.
- **Once a Case exists, `ClosedDate` can never be set or corrected via UPDATE, under any
  combination of fields** — confirmed again by attempting `Status='Closed'` + `ClosedDate=<backdated>`
  together in a single UPDATE call: `INVALID_FIELD_FOR_INSERT_UPDATE` on `ClosedDate`, same error
  as setting it alone.
- **Flipping `Status` to Closed via UPDATE (with no ClosedDate in that call) auto-sets `ClosedDate`
  to the real current timestamp** (confirmed again: "now" at time of test, not backdated).
- **Net effect: the two paths are mutually exclusive per Case.**
  - **Path A** — insert directly with `Status=<closed value>` + backdated `ClosedDate` together.
    Gives accurate, backdated `ClosedDate` (correct "Avg Time to Close" variance). Produces **no**
    `CaseHistory` Status row (confirmed earlier), so `Case_Update`/`First_Close_Date_clc`/"Avg Time
    to 1st Close" stays null for these Cases.
  - **Path B** — insert as `Status='New'`, then a later UPDATE to `Status=<closed value>`.
    Produces a real `CaseHistory` Status row (fixes "Avg Time to 1st Close"). `ClosedDate` collapses
    to "whenever the update ran" — not backdated, not variable per-Case, which would flatten "Avg
    Time to Close" to a single wrong duration across every Path-B Case.
  - Confirmed org-wide there is effectively **zero existing real Status-history data to lean on**
    instead (`SELECT COUNT(Id) FROM CaseHistory WHERE Field='Status'` = 1, across the whole org,
    all objects, all time) — this isn't a gap our synthetic data happens to share with the real
    seed data, it's a genuine platform mechanic every close-flow has to contend with.
- Also confirmed **`CaseHistory` itself has zero createable fields** (checked via describe) — there
  is no possible direct-insert workaround; the field-history row can only ever be produced as a
  side effect of a real field-value UPDATE.

**Decision (confirmed by user 2026-07-24): hybrid split.** Most of the 2,500-Case cohort's closed
Cases use **Path A** (direct insert with backdated `Status`+`ClosedDate` together) — this is the
majority case and preserves accurate "Avg Time to Close" variance across the full cohort, which is
the more heavily-used metric (appears on Cases1, My Service Performance, Service Analytics
Overview/Backlog/Team Efficiency/Channel Review/Account Profile — i.e. most of both apps). A
smaller, deliberately-sized subset of closed Cases instead uses **Path B** (insert Open, then a
follow-up UPDATE to the closed Status) purely to give "Avg Time to 1st Close" some genuine
non-null signal on both dashboards, accepting that those specific Cases' `ClosedDate` will read as
"now" rather than a realistic backdated value. Exact subset size/ratio still to be decided during
implementation — something in the range of 10-20% of closed Cases should be enough to populate the
metric with real variance without meaningfully diluting the main "Avg Time to Close" trend, but
this should be tuned by eye once dry-run output is in hand, not fixed in advance.

## Undo / rollback process (2026-07-24)

User asked for a way to revert/remove everything this tool deploys if something goes wrong. This
plugs directly into the batch-tagging mechanism already agreed above (see "Additional build
requirements," item 1) — the batch tag is what makes a clean undo possible at all, so the two are
being designed together:

- Every record the tool creates in a run (Case, EmailMessage, CaseArticle, Task) gets stamped with
  the same batch identifier — plan: `Case.External_ID__c = 'SI-GEN-<run-id>'` on every generated
  Case, and the related EmailMessage/CaseArticle/Task records get linked back to those Case Ids
  (so they're findable via the Case relationship even without their own tag field).
- A separate CLI subcommand, e.g. `python -m service_insights_data_import undo --batch SI-GEN-<run-id>`
  (or `--last` to target the most recent run without having to look up the id), does the reverse in
  strict dependency order: delete Task/CaseArticle/EmailMessage rows tied to the batch's Cases
  first, then delete the Cases themselves last (deleting a Case first would cascade-orphan or block
  on the children depending on object config — safer to go leaf-to-root).
- **Same enforced-safety principle as the forward path**: the undo command must only ever delete
  records it can trace back to a specific, named batch tag — never a bare "delete all Cases" or
  anything that could reach the original 180 seed Cases (which were never tagged, since they
  predate this tool). This makes undo the mirror image of the additive-only guarantee: the loader
  can't touch pre-existing data going in, and undo can't touch it coming out either.
- Every run's tool output (dry-run or live) should log the batch id clearly and, for live runs,
  write a small local manifest file (e.g. `data/runs/<run-id>.json` — Case Ids, related record Ids,
  timestamp, org, profile used) so `undo --last` doesn't have to depend on `External_ID__c` still
  being intact/unmodified to find its own work; the manifest is the authoritative undo source, the
  `External_ID__c` tag is a secondary/backup lookup path (useful if the manifest file itself is
  lost, e.g. a fresh checkout of the repo on another machine pointed at the same org).
- This also gives a natural non-destructive alternative to a true delete: `undo --dry-run` can
  first print exactly what a real undo would remove, so an SE can sanity-check scope before
  confirming, mirroring the same dry-run-first pattern used for the forward load.

## Repo

Public repo created for this project: https://github.com/chrisprice-cmyk/service-insights-data-import
(personal account `chrisprice-cmyk`, chosen over the internal `chrisprice_sfemu` account since the
goal is a reusable tool other people can pick up).

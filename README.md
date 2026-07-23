# Service Insights Data Import

Tooling to generate and import realistic demo data into a Salesforce org running
the **Tableau Next Service Insights** application, so its dashboards (Speed to
Answer, CSAT, Agent Utilization, First Contact Resolution, etc.) have enough
data to look meaningful.

## Why

The Service Insights semantic model (built on Data Cloud DMOs on top of core
Service Cloud objects) needs populated data across a specific object graph —
Cases, Agent Work, Agent Service Presence, Surveys/Responses, and their
relationships to Accounts, Contacts, and Users. A fresh SDO/demo org typically
has some Case/Account/Contact data but is missing the operational and survey
objects entirely, leaving key metrics blank.

## Status

Early design phase — mapping the semantic model's object graph and data gaps
before building the import scripts. See project notes for details.

## License

TBD.

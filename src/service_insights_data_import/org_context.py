"""Runtime org discovery.

Every generator needs real Ids from the target org (Users, BusinessHours,
Accounts/Contacts, published Knowledge articles, ...). Nothing here is
hardcoded to Prime_SDO -- this module queries whatever org the CLI is pointed
at via its Salesforce CLI alias, so the tool works unmodified for any SE's
org.
"""

import json
import subprocess
from dataclasses import dataclass, field

from simple_salesforce import Salesforce

from . import config


class OrgContextError(RuntimeError):
    """Raised when the target org is missing data this tool depends on."""


def connect(alias: str) -> Salesforce:
    """Build a simple_salesforce session from an authenticated `sf` CLI alias.

    Reuses the CLI's existing auth (instanceUrl + accessToken) rather than
    running a separate OAuth flow, so this only requires `sf org login` (or
    equivalent) to already have been done for `alias`. Recent `sf` versions
    redact the token from `org display`, so the token itself comes from the
    dedicated `org auth show-access-token` command instead.
    """
    display = subprocess.run(
        ["sf", "org", "display", "-o", alias, "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    org = json.loads(display.stdout)["result"]

    token_result = subprocess.run(
        ["sf", "org", "auth", "show-access-token", "-o", alias, "-p", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    access_token = json.loads(token_result.stdout)["result"]["accessToken"]

    return Salesforce(
        instance_url=org["instanceUrl"],
        session_id=access_token,
        version=org.get("apiVersion") or "59.0",
    )


@dataclass
class OrgContext:
    alias: str
    user_ids: list = field(default_factory=list)
    owner_ids: list = field(default_factory=list)
    created_by_ids: list = field(default_factory=list)
    business_hours_id: str | None = None
    account_ids: list = field(default_factory=list)
    contact_ids_by_account: dict = field(default_factory=dict)
    service_channel_id: str | None = None
    knowledge_article_ids: list = field(default_factory=list)


def discover(sf: Salesforce, alias: str) -> OrgContext:
    """Query the org for every dynamic Id the generators need.

    Raises OrgContextError with an actionable message if the org is missing
    a prerequisite (e.g. no Accounts at all) rather than letting generators
    fail later with an opaque Id-not-found error.
    """
    ctx = OrgContext(alias=alias)

    users = sf.query("SELECT Id FROM User WHERE IsActive = true")["records"]
    if not users:
        raise OrgContextError("No active Users found -- cannot assign Case OwnerId.")
    ctx.user_ids = [u["Id"] for u in users]

    # Owner pool is drawn from Users who already own real Cases -- a handful
    # of actual service reps, not every active User org-wide (admins,
    # integration users, etc). Ranked by existing case count and capped at
    # MAX_OWNER_POOL_SIZE, so the generated cohort reads as a small, real
    # team (some reps with heavier real caseloads first) rather than being
    # spread thin. Falls back to the full active-User set only if the org
    # has no pre-existing Cases to learn a pool from.
    existing_owners = sf.query(
        "SELECT OwnerId, COUNT(Id) cnt FROM Case WHERE OwnerId IN (SELECT Id FROM User) "
        "GROUP BY OwnerId ORDER BY COUNT(Id) DESC LIMIT 4000"
    )["records"]
    ranked_owners = [o["OwnerId"] for o in existing_owners]
    ctx.owner_ids = (ranked_owners or ctx.user_ids)[: config.MAX_OWNER_POOL_SIZE]

    existing_creators = sf.query("SELECT CreatedById FROM Case LIMIT 4000")["records"]
    ctx.created_by_ids = list({c["CreatedById"] for c in existing_creators}) or ctx.user_ids

    bh = sf.query("SELECT Id FROM BusinessHours WHERE IsDefault = true")["records"]
    ctx.business_hours_id = bh[0]["Id"] if bh else None

    accounts = sf.query("SELECT Id FROM Account LIMIT 2000")["records"]
    if not accounts:
        raise OrgContextError("No Accounts found -- cannot assign Case AccountId.")
    ctx.account_ids = [a["Id"] for a in accounts]

    contacts = sf.query(
        "SELECT Id, AccountId FROM Contact WHERE AccountId != null LIMIT 4000"
    )["records"]
    for c in contacts:
        ctx.contact_ids_by_account.setdefault(c["AccountId"], []).append(c["Id"])

    channel = sf.query(
        "SELECT Id FROM ServiceChannel WHERE DeveloperName = 'Case'"
    )["records"]
    ctx.service_channel_id = channel[0]["Id"] if channel else None

    articles = sf.query(
        "SELECT KnowledgeArticleId FROM Knowledge__kav WHERE PublishStatus = 'Online'"
    )["records"]
    ctx.knowledge_article_ids = [a["KnowledgeArticleId"] for a in articles]

    return ctx

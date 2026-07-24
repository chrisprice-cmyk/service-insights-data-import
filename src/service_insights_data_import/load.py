"""Bulk API 2.0 load orchestration.

Ties the generators, org discovery, batch tagging, run manifest, and the
additive-only safety guard together into one load. Two modes:

- dry_run=True: builds every record in memory and writes them to CSV under
  data/dry-runs/<run_id>/ for eyeballing. No Salesforce API calls at all.
- dry_run=False: does the real Bulk API 2.0 insert/update sequence, saving a
  run manifest as it goes so `undo` always has a trustworthy record of what
  this run created.
"""

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .batch import new_run_id
from .generators import case_articles, cases, email_messages, tasks
from .manifest import RunManifest
from .safety import BatchGuard

DRY_RUN_DIR = Path(__file__).resolve().parents[2] / "data" / "dry-runs"


def _write_csv(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames = sorted({k for row in rows for k in row.keys()})
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _parse_result_csv(csv_text: str) -> list:
    return list(csv.DictReader(io.StringIO(csv_text)))


def _bulk_insert_and_collect(sf, object_name: str, records: list) -> list:
    """Insert via Bulk API 2.0 and return the successful-record rows across
    every job (a large record list can be split into multiple ingest jobs,
    so the insert() call always returns a list, even for one job)."""
    bulk_type = getattr(sf.bulk2, object_name)
    job_results = bulk_type.insert(records=records, wait=15)
    successful = []
    for job in job_results:
        successful.extend(_parse_result_csv(bulk_type.get_successful_records(job["job_id"])))
    return successful


def preflight_summary(sf, org_alias: str, profile) -> dict:
    """Counts an operator should see before confirming a live run."""
    existing_cases = sf.query("SELECT COUNT(Id) total FROM Case")["records"][0]["total"]
    prior_batches = sf.query(
        f"SELECT COUNT(Id) total FROM Case WHERE External_ID__c LIKE '{config.BATCH_PREFIX}%'"
    )["records"][0]["total"]
    return {
        "org_alias": org_alias,
        "existing_case_count": existing_cases,
        "prior_generated_case_count": prior_batches,
        "profile": profile.name,
        "planned_case_count": profile.case_count,
        "planned_lookback_months": profile.lookback_months,
    }


def dry_run(profile, org_ctx, seed: int | None = None) -> dict:
    run_id = new_run_id()
    cohort = cases.generate_cohort(profile, org_ctx, run_id, seed=seed)

    # Dry-run mode has no real Case Ids yet -- use the External_ID__c tag as
    # a stand-in so the related-record CSVs are still inspectable.
    placeholder_ids = {seq: row["External_ID__c"] for seq, row in zip(cohort.seqs, cohort.insert_rows)}
    emails = email_messages.build_rows(cohort, placeholder_ids, rng_seed=seed)
    articles = case_articles.build_rows(cohort, placeholder_ids, org_ctx.knowledge_article_ids, rng_seed=seed)
    task_rows = tasks.build_rows(cohort, placeholder_ids, org_ctx, rng_seed=seed)

    out_dir = DRY_RUN_DIR / run_id
    _write_csv(out_dir / "cases.csv", cohort.insert_rows)
    _write_csv(out_dir / "email_messages.csv", emails)
    _write_csv(out_dir / "case_articles.csv", articles)
    _write_csv(out_dir / "tasks.csv", task_rows)

    return {
        "run_id": run_id,
        "output_dir": str(out_dir),
        "case_count": len(cohort.insert_rows),
        "path_b_count": len(cohort.path_b_seqs),
        "email_count": len(emails),
        "case_article_count": len(articles),
        "task_count": len(task_rows),
    }


def live_run(sf, org_alias: str, profile, org_ctx, seed: int | None = None) -> RunManifest:
    run_id = new_run_id()
    cohort = cases.generate_cohort(profile, org_ctx, run_id, seed=seed)
    guard = BatchGuard()

    manifest = RunManifest(
        run_id=run_id,
        org_alias=org_alias,
        profile=profile.name,
        started_at=run_id,
    )
    manifest.save()  # save early so a crash mid-run still leaves a trace

    successful = _bulk_insert_and_collect(sf, "Case", cohort.insert_rows)

    case_ids_by_external_id = {r["External_ID__c"]: r["sf__Id"] for r in successful}
    case_ids_by_seq = {}
    for seq, row in zip(cohort.seqs, cohort.insert_rows):
        case_id = case_ids_by_external_id.get(row["External_ID__c"])
        if case_id:
            case_ids_by_seq[seq] = case_id

    manifest.case_ids = list(case_ids_by_seq.values())
    guard.register(manifest.case_ids)
    manifest.save()

    # Path B: flip Status to Closed on its own subset, via the guard, to
    # generate the CaseHistory row Avg Time to 1st Close depends on.
    path_b_case_ids = [case_ids_by_seq[seq] for seq in cohort.path_b_seqs if seq in case_ids_by_seq]
    if path_b_case_ids:
        guard.guarded_update(
            sf,
            "Case",
            [{"Id": cid, "Status": config.CLOSED_STATUS} for cid in path_b_case_ids],
        )
        manifest.path_b_case_ids = path_b_case_ids
        manifest.save()

    emails = email_messages.build_rows(cohort, case_ids_by_seq, rng_seed=seed)
    if emails:
        successful_emails = _bulk_insert_and_collect(sf, "EmailMessage", emails)
        manifest.email_message_ids = [r["sf__Id"] for r in successful_emails]
        manifest.save()

    articles = case_articles.build_rows(cohort, case_ids_by_seq, org_ctx.knowledge_article_ids, rng_seed=seed)
    if articles:
        successful_articles = _bulk_insert_and_collect(sf, "CaseArticle", articles)
        manifest.case_article_ids = [r["sf__Id"] for r in successful_articles]
        manifest.save()

    task_rows = tasks.build_rows(cohort, case_ids_by_seq, org_ctx, rng_seed=seed)
    if task_rows:
        successful_tasks = _bulk_insert_and_collect(sf, "Task", task_rows)
        manifest.task_ids = [r["sf__Id"] for r in successful_tasks]
        manifest.save()

    manifest.completed_at = datetime.now(timezone.utc).isoformat()
    manifest.save()
    return manifest

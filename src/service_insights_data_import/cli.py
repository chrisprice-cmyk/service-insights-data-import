"""CLI entrypoint: python -m service_insights_data_import <command> ...

Commands:
  run    Generate and load the Case/EmailMessage/CaseArticle/Task cohort.
         Defaults to --dry-run (CSV preview, no org calls). Pass --live to
         actually insert, after a pre-flight summary + confirmation prompt.
  undo   Reverse a previous live run via its manifest.
  verify Re-query dashboard-relevant aggregates for a given run.
"""

import argparse
import sys

from . import load, org_context, refresh as refresh_mod, undo as undo_mod, verify as verify_mod
from .config import DEFAULT_PROFILE, PROFILES


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="service_insights_data_import")
    parser.add_argument("--org", required=True, help="sf CLI org alias to target")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Generate and optionally load the cohort")
    run_p.add_argument("--profile", choices=sorted(PROFILES), default=DEFAULT_PROFILE)
    run_p.add_argument("--live", action="store_true", help="Actually insert into the org (default: dry-run)")
    run_p.add_argument("--yes", action="store_true", help="Skip the pre-flight confirmation prompt")
    run_p.add_argument("--seed", type=int, default=None, help="Random seed, for reproducible dry-runs")
    run_p.add_argument(
        "--no-refresh", action="store_true",
        help="Skip refreshing Data Cloud data streams / the CRMA Service Analytics dataflow after a live load",
    )
    run_p.add_argument(
        "--wait-for-crma", action="store_true",
        help="Block until the CRMA dataflow run finishes (default: fire-and-forget)",
    )

    undo_p = sub.add_parser("undo", help="Reverse a previous live run")
    undo_p.add_argument("run_id", nargs="?", default=None)
    undo_p.add_argument("--last", action="store_true", help="Target the most recent local run manifest")
    undo_p.add_argument("--dry-run", action="store_true", help="Print what would be deleted, without deleting")
    undo_p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    undo_p.add_argument(
        "--no-refresh", action="store_true",
        help="Skip refreshing Data Cloud data streams / the CRMA Service Analytics dataflow after deleting",
    )
    undo_p.add_argument(
        "--wait-for-crma", action="store_true",
        help="Block until the CRMA dataflow run finishes (default: fire-and-forget)",
    )

    verify_p = sub.add_parser("verify", help="Re-check dashboard-relevant aggregates for a run")
    verify_p.add_argument("run_id")

    return parser


def _confirm(prompt: str) -> bool:
    reply = input(f"{prompt} [y/N] ").strip().lower()
    return reply in ("y", "yes")


def _refresh_downstream(sf, wait_for_crma: bool) -> None:
    """Kick off the Data Cloud data-stream refresh and CRMA dataflow run this
    tool's writes affect. Best-effort and non-fatal -- a refresh failure
    (e.g. Data Cloud not provisioned in this org) shouldn't make an otherwise
    successful load/undo look like it failed."""
    try:
        started_streams = refresh_mod.refresh_data_streams(sf)
        if started_streams:
            print("Data Cloud data streams refreshing:")
            for name, job_id in started_streams.items():
                print(f"  {name}" + (f" (job {job_id})" if job_id else ""))
        else:
            print("No matching Data Cloud data streams found -- skipping.")
    except Exception as exc:
        print(f"Data Cloud data stream refresh failed (non-fatal): {exc}")

    try:
        result = refresh_mod.refresh_crma_dataflow(sf, wait=wait_for_crma)
        if result["dataflow_id"]:
            print(f"CRMA Service Analytics dataflow job {result['job_id']}: {result['status']}")
        else:
            print("Service Analytics dataflow not found in this org -- skipping.")
    except Exception as exc:
        print(f"CRMA dataflow refresh failed (non-fatal): {exc}")


def cmd_run(args) -> int:
    profile = PROFILES[args.profile]
    sf = org_context.connect(args.org)
    ctx = org_context.discover(sf, args.org)

    if not args.live:
        summary = load.dry_run(profile, ctx, seed=args.seed)
        print(f"Dry run complete -- run_id {summary['run_id']}")
        print(f"  Cases:          {summary['case_count']} (Path B subset: {summary['path_b_count']})")
        print(f"  EmailMessages:  {summary['email_count']}")
        print(f"  CaseArticles:   {summary['case_article_count']}")
        print(f"  Tasks:          {summary['task_count']}")
        print(f"  CSV output:     {summary['output_dir']}")
        print("Re-run with --live to insert into the org.")
        return 0

    preflight = load.preflight_summary(sf, args.org, profile)
    print(f"Org:                      {preflight['org_alias']}")
    print(f"Existing Cases:           {preflight['existing_case_count']}")
    print(f"Already-generated Cases:  {preflight['prior_generated_case_count']}")
    print(f"Profile:                  {preflight['profile']}")
    print(f"About to insert:          {preflight['planned_case_count']} Cases "
          f"over {preflight['planned_lookback_months']} months")
    print("This only ever INSERTs new records; existing data is never updated or deleted.")

    if not args.yes and not _confirm("Proceed with the live load?"):
        print("Aborted.")
        return 1

    manifest = load.live_run(sf, args.org, profile, ctx, seed=args.seed)
    print(f"Live run complete -- run_id {manifest.run_id}")
    print(f"  Cases inserted:         {len(manifest.case_ids)}")
    print(f"  Path B status-flipped:  {len(manifest.path_b_case_ids)}")
    print(f"  EmailMessages:          {len(manifest.email_message_ids)}")
    print(f"  CaseArticles:           {len(manifest.case_article_ids)}")
    print(f"  Tasks:                  {len(manifest.task_ids)}")
    print(f"  Manifest saved to data/runs/{manifest.run_id}.json")

    if not args.no_refresh:
        _refresh_downstream(sf, args.wait_for_crma)

    print(f"Run `service_insights_data_import --org {args.org} verify {manifest.run_id}` to check dashboard aggregates.")
    return 0


def cmd_undo(args) -> int:
    run_id = undo_mod.resolve_run_id(args.run_id, args.last)
    manifest = undo_mod.plan(run_id)

    print(f"Undo plan for run {run_id} (org {manifest.org_alias}, profile {manifest.profile}):")
    print(f"  Cases:          {len(manifest.case_ids)}")
    print(f"  EmailMessages:  {len(manifest.email_message_ids)}")
    print(f"  CaseArticles:   {len(manifest.case_article_ids)}")
    print(f"  Tasks:          {len(manifest.task_ids)}")

    if args.dry_run:
        print("Dry run -- nothing deleted.")
        return 0

    if not args.yes and not _confirm("Delete all of the above from the org?"):
        print("Aborted.")
        return 1

    sf = org_context.connect(args.org)
    undo_mod.execute(sf, run_id)
    print(f"Undo complete for run {run_id}.")

    if not args.no_refresh:
        _refresh_downstream(sf, args.wait_for_crma)

    return 0


def cmd_verify(args) -> int:
    sf = org_context.connect(args.org)
    checks = verify_mod.run_checks(sf, args.run_id)
    passed = verify_mod.print_report(checks)
    return 0 if passed else 1


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "undo":
        return cmd_undo(args)
    if args.command == "verify":
        return cmd_verify(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())

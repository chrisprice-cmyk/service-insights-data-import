"""Undo / rollback for a previous run.

Manifest-driven (manifest.py's RunManifest is authoritative, per NOTES.md
"Undo / rollback process"). Deletes leaf-to-root -- Task/CaseArticle/
EmailMessage before Case -- and goes through the same BatchGuard as the
forward load, seeded only from the manifest's own Ids, so it is
structurally incapable of reaching a record the manifest doesn't list
(in particular, the original 180 seed Cases, which predate this tool and
were never in any manifest).
"""

from .manifest import RunManifest, latest_run_id
from .safety import BatchGuard


def resolve_run_id(run_id: str | None, use_last: bool) -> str:
    if use_last:
        found = latest_run_id()
        if not found:
            raise RuntimeError("No local run manifests found under data/runs/ -- nothing to undo.")
        return found
    if not run_id:
        raise RuntimeError("Must pass either a run_id or --last.")
    return run_id


def plan(run_id: str) -> RunManifest:
    """Load the manifest for a run -- this is also what --dry-run prints."""
    return RunManifest.load(run_id)


def execute(sf, run_id: str) -> RunManifest:
    manifest = RunManifest.load(run_id)
    guard = BatchGuard()
    guard.register(manifest.case_ids)
    guard.register(manifest.email_message_ids)
    guard.register(manifest.case_article_ids)
    guard.register(manifest.task_ids)

    if manifest.task_ids:
        guard.guarded_delete(sf, "Task", manifest.task_ids)
    if manifest.case_article_ids:
        guard.guarded_delete(sf, "CaseArticle", manifest.case_article_ids)
    if manifest.email_message_ids:
        guard.guarded_delete(sf, "EmailMessage", manifest.email_message_ids)
    if manifest.case_ids:
        guard.guarded_delete(sf, "Case", manifest.case_ids)

    return manifest

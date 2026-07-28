"""Run manifests: the sole undo source.

Per NOTES.md "Undo / rollback process", the manifest file is the only
thing `undo` reads from. If it's missing (e.g. a fresh checkout on
another machine), that run can't be undone by this tool -- the
External_ID__c batch tag (see batch.py) still identifies the records for
manual cleanup, but there's no automated fallback lookup.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parents[2] / "data" / "runs"

# batch.new_run_id() always produces this format. Filtering on it before
# sorting keeps list_run_ids()/latest_run_id() correct even if a
# non-conforming file (e.g. a hand-made test manifest) ends up in
# data/runs/ -- plain alphabetical sort would otherwise let a stray name
# like "TEST-RUN-1" sort after every real date-based run_id and get picked
# as "latest".
RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}$")


@dataclass
class RunManifest:
    run_id: str
    org_alias: str
    profile: str
    started_at: str
    case_ids: list = field(default_factory=list)
    email_message_ids: list = field(default_factory=list)
    case_article_ids: list = field(default_factory=list)
    task_ids: list = field(default_factory=list)
    path_b_case_ids: list = field(default_factory=list)
    completed_at: str | None = None

    def path(self) -> Path:
        return RUNS_DIR / f"{self.run_id}.json"

    def save(self) -> Path:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        p = self.path()
        p.write_text(json.dumps(asdict(self), indent=2, sort_keys=False))
        return p

    @classmethod
    def load(cls, run_id: str) -> "RunManifest":
        p = RUNS_DIR / f"{run_id}.json"
        data = json.loads(p.read_text())
        return cls(**data)


def list_run_ids() -> list:
    """All run ids with a manifest on disk, most recent last (sorted by the
    sortable run_id format from batch.new_run_id)."""
    if not RUNS_DIR.exists():
        return []
    return sorted(p.stem for p in RUNS_DIR.glob("*.json") if RUN_ID_PATTERN.match(p.stem))


def latest_run_id() -> str | None:
    ids = list_run_ids()
    return ids[-1] if ids else None

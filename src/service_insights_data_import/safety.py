"""The enforced additive-only guarantee.

Per NOTES.md "Additional build requirements", item 2: this is a hard
assertion at the code level, not just documented intent. Every UPDATE or
DELETE this tool issues -- forward-path Status flips (Path B) or undo
deletes -- must go through a BatchGuard so it is structurally incapable of
touching a Case Id the guard doesn't already know about (i.e. anything that
predates this tool, like the original 180 seed Cases).
"""


class UnauthorizedRecordError(RuntimeError):
    """Raised when code attempts to UPDATE or DELETE a record this run/undo
    did not itself insert or was not told about via a run manifest."""


class BatchGuard:
    """Tracks which Ids this run is allowed to mutate.

    The forward loader registers Ids immediately after each successful
    insert, before issuing any follow-up UPDATE (e.g. the Path B Status
    flip). The undo command instead seeds the guard from a run manifest, so
    it can only ever delete records that manifest actually lists.
    """

    def __init__(self):
        self._allowed_ids = set()

    def register(self, ids) -> None:
        self._allowed_ids.update(ids)

    def assert_allowed(self, ids) -> None:
        unknown = set(ids) - self._allowed_ids
        if unknown:
            raise UnauthorizedRecordError(
                f"Refusing to mutate {len(unknown)} record(s) not created/known by this "
                f"run: {sorted(unknown)[:5]}{'...' if len(unknown) > 5 else ''}. "
                "This tool only ever modifies records it created itself."
            )

    def guarded_update(self, sf, object_name: str, records: list) -> list:
        """records: list of dicts each containing 'Id' plus fields to update."""
        ids = [r["Id"] for r in records]
        self.assert_allowed(ids)
        return getattr(sf.bulk2, object_name).update(records=records, wait=15)

    def guarded_delete(self, sf, object_name: str, ids: list) -> list:
        self.assert_allowed(ids)
        return getattr(sf.bulk2, object_name).delete(records=[{"Id": i} for i in ids], wait=15)

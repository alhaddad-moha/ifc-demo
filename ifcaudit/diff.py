"""Run-to-run diff on the stable issue ids.

Because Issue.id is a hash of rule + element GUIDs + discriminator, the same
defect has the same id in both runs, so set arithmetic is the whole diff.

One wrinkle: when a fix gives an element a new GlobalId, every *other* issue
on that element changes id too. Those are reported as `carried` rather than
`new`, since they are the same defects under a new GUID.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


def compare(before: list[dict], after: list[dict],
            regenerated_guids: Iterable[str] = (),
            applied: Optional[list[dict]] = None) -> dict[str, Any]:
    before_ids = {i["id"] for i in before}
    after_ids = {i["id"] for i in after}
    fresh = set(regenerated_guids)

    new, carried = [], []
    for issue in after:
        if issue["id"] in before_ids:
            continue
        guids = {e.get("guid") for e in issue.get("elements") or []}
        (carried if guids & fresh else new).append(issue["id"])

    out: dict[str, Any] = {
        "before": len(before_ids),
        "after": len(after_ids),
        "resolved": len(before_ids - after_ids),
        "new": len(set(new)),
        "carried": len(set(carried)),
        "persisting": len(before_ids & after_ids),
        "resolved_ids": sorted(before_ids - after_ids),
        "new_ids": sorted(set(new)),
    }
    sev = {i["id"]: i.get("severity") for i in after}
    out["new_by_severity"] = {s: sum(1 for i in set(new) if sev.get(i) == s)
                              for s in ("error", "warning", "info")}
    if applied is not None:
        # A fix is verified only if its issue is gone from the re-audit.
        out["unresolved_fixes"] = [c["issue_id"] for c in applied
                                   if c["status"] == "applied"
                                   and c["issue_id"] in after_ids]
    return out

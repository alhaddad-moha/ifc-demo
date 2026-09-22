"""Terminal summary — what you actually read while iterating on rules."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from ..issues import AuditResult, Severity

MARK = {"error": "[ERROR]", "warning": "[WARN ]", "info": "[INFO ]"}


def write(result: AuditResult, ids_summary: Optional[dict[str, Any]] = None,
          limit: int = 6) -> None:
    counts = result.counts()
    print()
    print("=" * 74)
    print(f" IFC AUDIT  ·  {result.project_name or '(unnamed)'}")
    print("=" * 74)
    print(f" File     : {result.model_path}")
    print(f" Schema   : {result.schema}")
    print(f" Units    : {result.units.get('length')} "
          f"(1 unit = {result.units.get('length_to_metre')} m)")
    print(f" Elements : {result.stats.get('elements', 0)}  "
          f"Storeys: {result.stats.get('storeys', 0)}  "
          f"Spaces: {result.stats.get('spaces', 0)}")
    print(f" Rules    : {len(result.rules_run)} run in {result.duration_s:.2f}s")
    print("-" * 74)
    print(f" RESULT   : {counts['error']} error(s), {counts['warning']} warning(s), "
          f"{counts['info']} info")
    print("-" * 74)

    if ids_summary:
        print(f" IDS: {ids_summary['title']}")
        for spec in ids_summary["specifications"]:
            state = "PASS" if spec["status"] else "FAIL"
            print(f"   [{state}] {spec['name']:<42} "
                  f"{spec['passed']}/{spec['applicable']} passed")
        print("-" * 74)

    grouped: dict[str, list] = defaultdict(list)
    for issue in result.sorted_issues():
        grouped[issue.rule_id].append(issue)

    for rule_id, issues in sorted(
        grouped.items(),
        key=lambda kv: (kv[1][0].severity.rank, -len(kv[1]))
    ):
        first = issues[0]
        print(f" {MARK[first.severity.value]} {rule_id:<30} {len(issues):>4} ×  "
              f"{first.title[:60]}")
        for issue in issues[:limit]:
            for el in issue.elements[:2]:
                print(f"          └─ {el.label()[:80]}")
        if len(issues) > limit:
            print(f"          … and {len(issues) - limit} more")

    if not result.issues:
        print(" No issues found.")
    print("=" * 74)

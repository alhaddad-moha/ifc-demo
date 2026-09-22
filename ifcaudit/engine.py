"""Rule registry and runner.

A rule is a generator function that takes an AuditContext and yields Issues.
Registration is by decorator, so adding a check means writing one function —
no wiring, no central list to update.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from .context import AuditContext
from .issues import AuditResult, Category, Issue, Severity


@dataclass
class Rule:
    id: str
    fn: Callable[[AuditContext], Iterator[Issue]]
    title: str
    category: Category
    severity: Severity
    needs_geometry: bool = False
    enabled: bool = True


REGISTRY: dict[str, Rule] = {}


def rule(id: str, title: str, category: Category | str,
         severity: Severity | str = Severity.WARNING,
         needs_geometry: bool = False, enabled: bool = True):
    """Decorator registering a check.

    needs_geometry drives whether the expensive tessellation pass runs at all.
    In this demo nothing sets it, so a 300 MB model still audits in seconds.
    """
    def wrap(fn):
        REGISTRY[id] = Rule(
            id=id, fn=fn, title=title,
            category=Category(category), severity=Severity(severity),
            needs_geometry=needs_geometry, enabled=enabled,
        )
        return fn
    return wrap


def selected_rules(include: Optional[list[str]] = None,
                   exclude: Optional[list[str]] = None) -> list[Rule]:
    rules = [r for r in REGISTRY.values() if r.enabled]
    if include:
        rules = [r for r in rules
                 if any(r.id == p or r.id.startswith(p.rstrip("*")) for p in include)]
    if exclude:
        rules = [r for r in rules
                 if not any(r.id == p or r.id.startswith(p.rstrip("*")) for p in exclude)]
    return sorted(rules, key=lambda r: r.id)


def run(ctx: AuditContext,
        include: Optional[list[str]] = None,
        exclude: Optional[list[str]] = None,
        extra_issues: Optional[list[Issue]] = None,
        verbose: bool = False) -> AuditResult:
    started = time.time()
    issues: list[Issue] = []
    ran: list[str] = []

    for r in selected_rules(include, exclude):
        try:
            produced = list(r.fn(ctx))
        except Exception:
            # A broken rule must never kill the audit — report it as an issue.
            produced = [Issue(
                rule_id="ENGINE.RULE_FAILED",
                severity=Severity.WARNING,
                category=Category.INTEGRITY,
                title=f"Rule '{r.id}' crashed",
                description="This check could not complete. The rest of the audit "
                            "is unaffected.",
                evidence={"rule": r.id, "traceback": traceback.format_exc()[-800:]},
            )]
        issues.extend(produced)
        ran.append(r.id)
        if verbose:
            print(f"  {r.id:<28} {len(produced):>4} issue(s)")

    if extra_issues:
        issues.extend(extra_issues)

    return AuditResult(
        model_path=ctx.path,
        schema=ctx.schema,
        project_name=ctx.project_name,
        units=ctx.units,
        stats=ctx.stats,
        issues=issues,
        rules_run=ran,
        duration_s=time.time() - started,
    )

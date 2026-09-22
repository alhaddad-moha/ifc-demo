"""L2 — IDS (Information Delivery Specification) adapter.

IfcTester does the validating; this module's only job is translating its
results into our Issue schema so IDS failures sit in the same report, with
the same severity vocabulary, as everything else.

This is the pattern to copy for any future external checker.
"""

from __future__ import annotations

import os
from typing import Iterator, Optional

from ..context import AuditContext
from ..issues import Category, ElementRef, Issue, Severity


def _requirement_label(req) -> str:
    """A short human description of what the requirement demanded."""
    kind = type(req).__name__
    if kind == "Property":
        return f"{req.propertySet}.{req.baseName}"
    if kind == "Attribute":
        return f"attribute '{req.name}'"
    if kind == "Classification":
        return f"classification '{req.value or 'any'}'"
    if kind == "Material":
        return f"material '{getattr(req, 'value', None) or 'any'}'"
    if kind == "Entity":
        return f"entity {getattr(req, 'name', '?')}"
    if kind == "PartOf":
        return f"part of {getattr(req, 'entity', '?')}"
    return kind


def run_ids(ctx: AuditContext, ids_path: str,
            severity: Severity = Severity.ERROR) -> Iterator[Issue]:
    """Validate the model against an .ids file and yield Issues."""
    from ifctester import ids as ids_mod

    if not os.path.isfile(ids_path):
        yield Issue(
            rule_id="IDS.FILE_MISSING",
            severity=Severity.WARNING,
            category=Category.IDS,
            title="IDS file not found",
            description=f"No IDS applied — '{ids_path}' does not exist.",
            evidence={"key": ids_path, "path": ids_path},
        )
        return

    specs = ids_mod.open(ids_path)
    specs.validate(ctx.model)

    for spec in specs.specifications:
        spec_ref = spec.identifier or spec.name
        rule_id = f"IDS.{spec_ref}"

        # A spec that matched nothing is worth knowing about — usually it means
        # the applicability filter is wrong, not that the model is clean.
        if not spec.applicable_entities:
            yield Issue(
                rule_id=rule_id,
                severity=Severity.INFO,
                category=Category.IDS,
                title=f"IDS specification matched no elements: {spec.name}",
                description=(
                    "Nothing in the model satisfied this specification's "
                    "applicability filter. Either the model has none of these "
                    "elements, or the filter does not match how they were exported."
                ),
                evidence={"key": f"{spec_ref}|empty", "specification": spec.name},
            )
            continue

        for req in spec.requirements:
            if req.status:
                continue
            label = _requirement_label(req)
            for failure in getattr(req, "failures", []):
                element = failure.get("element")
                reason = failure.get("reason", "Requirement not met")
                yield Issue(
                    rule_id=rule_id,
                    severity=severity,
                    category=Category.IDS,
                    title=f"{spec.name} — {label}",
                    description=(
                        f"{reason}. "
                        + (spec.instructions or getattr(req, "instructions", "") or "")
                    ).strip(),
                    elements=[ctx.ref(element)] if element is not None else [],
                    evidence={
                        "key": (element.GlobalId if element is not None
                                else f"{spec_ref}|{label}"),
                        "specification": spec.name,
                        "requirement": label,
                        "reason": reason,
                        "expected": getattr(req, "value", None),
                    },
                )


def ids_summary(ids_path: str, ctx: AuditContext) -> Optional[dict]:
    """Per-specification pass/fail counts for the report header."""
    from ifctester import ids as ids_mod

    if not os.path.isfile(ids_path):
        return None
    specs = ids_mod.open(ids_path)
    specs.validate(ctx.model)
    return {
        "title": specs.info.get("title", os.path.basename(ids_path)),
        "path": ids_path,
        "specifications": [
            {
                "name": s.name,
                "status": bool(s.status),
                "applicable": len(s.applicable_entities),
                "passed": len(s.passed_entities),
                "failed": len(s.failed_entities),
            }
            for s in specs.specifications
        ],
    }

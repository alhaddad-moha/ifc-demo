"""L0 — schema validity via ifcopenshell.validate.

Kept out of the normal rule registry because it is comparatively slow and
answers a different question ("is this a valid IFC file?") from the rest of
the audit ("does this model meet requirements?"). Enable with --schema-check.
"""

from __future__ import annotations

from typing import Iterator

from ..context import AuditContext
from ..issues import Category, ElementRef, Issue, Severity

MAX_REPORTED = 200


def run_schema_check(ctx: AuditContext) -> Iterator[Issue]:
    import ifcopenshell.validate as validate

    logger = validate.json_logger()
    failure: str | None = None

    # EXPRESS rule evaluation needs pytest installed (ifcopenshell uses it to
    # run the generated rule modules). If it is missing we still get every
    # attribute/type violation from the plain pass.
    try:
        validate.validate(ctx.model, logger, express_rules=True)
    except ModuleNotFoundError:
        try:
            validate.validate(ctx.model, logger, express_rules=False)
            failure = ("EXPRESS rule checking was skipped — install pytest to "
                       "enable it (`pip install pytest`). Attribute and type "
                       "validation still ran.")
        except Exception as exc:
            failure = str(exc)[:400]
    except Exception as exc:
        failure = str(exc)[:400]

    # statements are populated as validation proceeds, so read them even when
    # the call raised part-way through.
    entries = getattr(logger, "statements", None) or []

    if failure:
        yield Issue(
            rule_id="SCHEMA.CHECK_PARTIAL",
            severity=Severity.INFO,
            category=Category.SCHEMA,
            title="Schema validation ran with reduced coverage",
            description=failure,
            evidence={"key": "schema_check_partial"},
        )

    for i, entry in enumerate(entries[:MAX_REPORTED]):
        message = str(entry.get("message", "")).strip()
        instance = entry.get("instance")
        elements = []
        if instance is not None and hasattr(instance, "is_a"):
            elements = [ElementRef.from_entity(instance, source_file=ctx.filename)]
        yield Issue(
            rule_id="SCHEMA.INVALID",
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            title="Schema violation",
            description=message[:500] or "The file violates the IFC schema.",
            elements=elements,
            evidence={"key": f"{message[:80]}|{i}", "attribute": entry.get("attribute")},
        )

    if len(entries) > MAX_REPORTED:
        yield Issue(
            rule_id="SCHEMA.INVALID",
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            title=f"{len(entries) - MAX_REPORTED} further schema violations truncated",
            description="Only the first 200 schema violations are reported.",
            evidence={"key": "truncated", "total": len(entries)},
        )

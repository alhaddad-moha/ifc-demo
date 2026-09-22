"""Project-level and spatial-structure checks.

These run once per model rather than per element. They are cheap and they
catch the failures that invalidate every other result — wrong units and bad
georeferencing above all.
"""

from __future__ import annotations

import ifcopenshell.util.element as ue

from ..context import AuditContext
from ..engine import rule
from ..issues import Category, Issue, Severity


@rule(id="PRJ.SCHEMA_VERSION", title="IFC schema version",
      category=Category.SCHEMA, severity=Severity.INFO)
def schema_version(ctx: AuditContext):
    if ctx.schema.upper().startswith("IFC2X3"):
        yield Issue(
            rule_id="PRJ.SCHEMA_VERSION",
            severity=Severity.WARNING,
            category=Category.SCHEMA,
            title="Model is IFC2X3",
            description=(
                "IFC2X3 is superseded. Several property sets, the IDS "
                "facet vocabulary and all IFC4 quantity definitions behave "
                "differently. Request IFC4 (or IFC4.3 for infrastructure)."
            ),
            evidence={"key": "schema", "schema": ctx.schema},
        )


@rule(id="PRJ.NO_PROJECT", title="Missing IfcProject",
      category=Category.SCHEMA, severity=Severity.ERROR)
def no_project(ctx: AuditContext):
    projects = ctx.model.by_type("IfcProject")
    if not projects:
        yield Issue(
            rule_id="PRJ.NO_PROJECT",
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            title="File contains no IfcProject",
            description="Every valid IFC file has exactly one IfcProject root.",
            evidence={"key": "no_project"},
        )
    elif len(projects) > 1:
        yield Issue(
            rule_id="PRJ.NO_PROJECT",
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            title=f"File contains {len(projects)} IfcProject entities",
            description="Exactly one IfcProject is allowed per file.",
            elements=[ctx.ref(p) for p in projects],
            evidence={"key": "multi_project", "count": len(projects)},
        )


@rule(id="PRJ.UNITS", title="Project units",
      category=Category.INTEGRITY, severity=Severity.ERROR)
def units(ctx: AuditContext):
    if ctx.project is None:
        return
    assignment = getattr(ctx.project, "UnitsInContext", None)
    if assignment is None or not getattr(assignment, "Units", None):
        yield Issue(
            rule_id="PRJ.UNITS",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            title="No unit assignment on the project",
            description=(
                "Without IfcUnitAssignment every length in the file is ambiguous. "
                "All quantities, tolerances and clash results are meaningless."
            ),
            evidence={"key": "no_units"},
        )
        return

    length = ctx.units.get("length")
    if length and not any(t in str(length).upper()
                          for t in ("METRE", "METER", "MILLI", "CENTI")):
        yield Issue(
            rule_id="PRJ.UNITS",
            severity=Severity.WARNING,
            category=Category.INTEGRITY,
            title=f"Project length unit is non-metric ({length})",
            description=(
                "Imperial units in a metric-region project. Confirm this is "
                "intentional before trusting any quantity."
            ),
            evidence={"key": "non_metric", "length_unit": str(length)},
        )


@rule(id="PRJ.GEOREFERENCE", title="Georeferencing",
      category=Category.INTEGRITY, severity=Severity.WARNING)
def georeference(ctx: AuditContext):
    """The single biggest cause of garbage federated-clash results.
    Two models that are not georeferenced the same way will either produce
    zero clashes or a million, and neither is a real answer."""
    has_map_conversion = bool(ctx.model.by_type("IfcMapConversion"))
    site = ctx.sites[0] if ctx.sites else None
    has_site_coords = bool(
        site and (getattr(site, "RefLatitude", None)
                  or getattr(site, "RefLongitude", None))
    )
    if not has_map_conversion and not has_site_coords:
        yield Issue(
            rule_id="PRJ.GEOREFERENCE",
            severity=Severity.WARNING,
            category=Category.INTEGRITY,
            title="Model is not georeferenced",
            description=(
                "No IfcMapConversion and no site latitude/longitude. The model "
                "cannot be reliably federated with other disciplines or placed "
                "against survey data. Fix this before running any clash."
            ),
            elements=[ctx.ref(site)] if site else [],
            evidence={"key": "no_georef",
                      "map_conversion": has_map_conversion,
                      "site_coords": has_site_coords},
        )


@rule(id="SPA.NO_STOREYS", title="Building has no storeys",
      category=Category.INTEGRITY, severity=Severity.ERROR)
def no_storeys(ctx: AuditContext):
    for building in ctx.buildings:
        children = [c for c in ue.get_decomposition(building)
                    if c.is_a("IfcBuildingStorey")]
        if not children:
            yield Issue(
                rule_id="SPA.NO_STOREYS",
                severity=Severity.ERROR,
                category=Category.INTEGRITY,
                title="Building contains no storeys",
                description=(
                    "Without IfcBuildingStorey there is no level structure, so "
                    "nothing can be scheduled or viewed by floor."
                ),
                elements=[ctx.ref(building)],
                evidence={"key": building.GlobalId},
            )


@rule(id="SPA.STOREY_ELEVATION", title="Storey without elevation",
      category=Category.INTEGRITY, severity=Severity.WARNING)
def storey_elevation(ctx: AuditContext):
    for storey in ctx.storeys:
        if getattr(storey, "Elevation", None) is None:
            yield Issue(
                rule_id="SPA.STOREY_ELEVATION",
                severity=Severity.WARNING,
                category=Category.INTEGRITY,
                title="Storey has no Elevation value",
                description=(
                    "Level elevation is required to sort floors, generate sections "
                    "and validate floor-to-floor heights."
                ),
                elements=[ctx.ref(storey)],
                evidence={"key": storey.GlobalId},
            )


@rule(id="SPA.DUPLICATE_STOREY_ELEVATION", title="Two storeys at the same level",
      category=Category.INTEGRITY, severity=Severity.WARNING)
def duplicate_storey_elevation(ctx: AuditContext):
    seen: dict[float, list] = {}
    for storey in ctx.storeys:
        elev = getattr(storey, "Elevation", None)
        if elev is None:
            continue
        seen.setdefault(round(float(elev), 3), []).append(storey)
    for elev, group in seen.items():
        if len(group) > 1:
            yield Issue(
                rule_id="SPA.DUPLICATE_STOREY_ELEVATION",
                severity=Severity.WARNING,
                category=Category.INTEGRITY,
                title=f"{len(group)} storeys share elevation {elev}",
                description=(
                    "Duplicated level elevations usually mean a linked model was "
                    "merged twice or a level was copied."
                ),
                elements=[ctx.ref(s) for s in group],
                evidence={"key": f"elev{elev}", "elevation": elev},
            )


@rule(id="SPA.NO_SPACES", title="Model defines no spaces",
      category=Category.INTEGRITY, severity=Severity.INFO)
def no_spaces(ctx: AuditContext):
    if not ctx.spaces and ctx.storeys:
        yield Issue(
            rule_id="SPA.NO_SPACES",
            severity=Severity.INFO,
            category=Category.INTEGRITY,
            title="No IfcSpace entities in the model",
            description=(
                "Spaces drive area schedules, occupancy load, egress checks and "
                "most code-compliance rules. An architectural model without them "
                "cannot be checked against area-based requirements."
            ),
            evidence={"key": "no_spaces"},
        )

"""L1 — data integrity and sanity checks.

These are schema-agnostic "is this model even usable" checks. They are the
ones that catch 80% of real-world rubbish before anyone opens an IDS.
"""

from __future__ import annotations

from collections import defaultdict

import ifcopenshell.util.element as ue

from ..context import CONTAINER_EXEMPT, AuditContext
from ..engine import rule
from ..issues import Category, Issue, Severity

# Elements that legitimately carry no material.
MATERIAL_EXEMPT = ("IfcSpace", "IfcOpeningElement", "IfcAnnotation",
                   "IfcDistributionPort", "IfcFurnishingElement")


@rule(id="INT.DUPLICATE_GUID", title="Duplicate GlobalId",
      category=Category.INTEGRITY, severity=Severity.ERROR)
def duplicate_guid(ctx: AuditContext):
    seen = defaultdict(list)
    for el in ctx.model.by_type("IfcRoot"):
        if el.GlobalId:
            seen[el.GlobalId].append(el)
    for guid, group in seen.items():
        if len(group) > 1:
            yield Issue(
                rule_id="INT.DUPLICATE_GUID",
                severity=Severity.ERROR,
                category=Category.INTEGRITY,
                title="Duplicate GlobalId",
                description=(
                    f"{len(group)} entities share the GlobalId {guid}. GUIDs must be "
                    "unique across the file — duplicates break issue tracking, "
                    "federation and any downstream round-trip."
                ),
                elements=[ctx.ref(e) for e in group],
                evidence={"key": guid, "guid": guid, "count": len(group)},
            )


@rule(id="INT.MISSING_CONTAINER", title="Element not in spatial structure",
      category=Category.INTEGRITY, severity=Severity.ERROR)
def missing_container(ctx: AuditContext):
    for el in ctx.elements:
        if any(el.is_a(c) for c in CONTAINER_EXEMPT):
            continue
        try:
            container = ue.get_container(el)
        except Exception:
            container = None
        if container is None:
            yield Issue(
                rule_id="INT.MISSING_CONTAINER",
                severity=Severity.ERROR,
                category=Category.INTEGRITY,
                title="Element is not assigned to any storey or space",
                description=(
                    "The element has no IfcRelContainedInSpatialStructure. It will be "
                    "invisible in storey-based views, excluded from quantity take-off "
                    "by level, and unassignable in most coordination tools."
                ),
                elements=[ctx.ref(el)],
                evidence={"key": el.GlobalId},
            )


@rule(id="INT.EMPTY_NAME", title="Element has no name",
      category=Category.INTEGRITY, severity=Severity.WARNING)
def empty_name(ctx: AuditContext):
    for el in ctx.checkable_elements:
        name = getattr(el, "Name", None)
        if name is None or not str(name).strip():
            yield Issue(
                rule_id="INT.EMPTY_NAME",
                severity=Severity.WARNING,
                category=Category.INTEGRITY,
                title="Element has a blank Name",
                description=(
                    "Unnamed elements cannot be identified in schedules, issue "
                    "reports or BCF topics."
                ),
                elements=[ctx.ref(el)],
                evidence={"key": el.GlobalId},
            )


@rule(id="INT.NO_GEOMETRY", title="Element has no geometry",
      category=Category.INTEGRITY, severity=Severity.WARNING)
def no_geometry(ctx: AuditContext):
    for el in ctx.checkable_elements:
        rep = getattr(el, "Representation", None)
        if rep is None or not getattr(rep, "Representations", None):
            yield Issue(
                rule_id="INT.NO_GEOMETRY",
                severity=Severity.WARNING,
                category=Category.INTEGRITY,
                title="Element carries no geometric representation",
                description=(
                    "The element exists as data only. It will not appear in any "
                    "viewer and cannot participate in clash detection."
                ),
                elements=[ctx.ref(el)],
                evidence={"key": el.GlobalId},
            )


@rule(id="INT.NO_MATERIAL", title="Element has no material",
      category=Category.INTEGRITY, severity=Severity.WARNING)
def no_material(ctx: AuditContext):
    for el in ctx.checkable_elements:
        if any(el.is_a(c) for c in MATERIAL_EXEMPT):
            continue
        try:
            material = ue.get_material(el)
        except Exception:
            material = None
        if material is None:
            yield Issue(
                rule_id="INT.NO_MATERIAL",
                severity=Severity.WARNING,
                category=Category.INTEGRITY,
                title="No material assigned",
                description=(
                    "Without a material association the element cannot be costed, "
                    "carbon-assessed or filtered by build-up."
                ),
                elements=[ctx.ref(el)],
                evidence={"key": el.GlobalId},
            )


@rule(id="INT.NO_TYPE", title="Element has no type object",
      category=Category.INTEGRITY, severity=Severity.INFO)
def no_type_object(ctx: AuditContext):
    for el in ctx.checkable_elements:
        try:
            type_obj = ue.get_type(el)
        except Exception:
            type_obj = None
        if type_obj is None:
            yield Issue(
                rule_id="INT.NO_TYPE",
                severity=Severity.INFO,
                category=Category.INTEGRITY,
                title="Element is not linked to an IfcTypeObject",
                description=(
                    "Type objects carry the shared, catalogue-level properties. "
                    "Occurrence-only elements duplicate data and drift apart."
                ),
                elements=[ctx.ref(el)],
                evidence={"key": el.GlobalId},
            )


@rule(id="INT.PROXY_ELEMENT", title="Unclassified proxy element",
      category=Category.INTEGRITY, severity=Severity.WARNING)
def proxy_element(ctx: AuditContext):
    for el in ctx.model.by_type("IfcBuildingElementProxy"):
        yield Issue(
            rule_id="INT.PROXY_ELEMENT",
            severity=Severity.WARNING,
            category=Category.INTEGRITY,
            title="Element exported as a generic proxy",
            description=(
                "IfcBuildingElementProxy means the authoring tool could not map the "
                "element to a real IFC class. Downstream rules, schedules and code "
                "checks that target IfcWall, IfcDoor etc. will silently skip it."
            ),
            elements=[ctx.ref(el)],
            evidence={"key": el.GlobalId},
        )


@rule(id="INT.DUPLICATE_PLACEMENT", title="Elements stacked at the same point",
      category=Category.INTEGRITY, severity=Severity.WARNING)
def duplicate_placement(ctx: AuditContext):
    """Cheap duplicate-element detector that needs no geometry engine:
    same class + same name + identical placement coordinates."""
    import ifcopenshell.util.placement as up

    buckets = defaultdict(list)
    for el in ctx.checkable_elements:
        placement = getattr(el, "ObjectPlacement", None)
        if placement is None:
            continue
        try:
            matrix = up.get_local_placement(placement)
            origin = tuple(round(float(v), 4) for v in matrix[:3, 3])
        except Exception:
            continue
        buckets[(el.is_a(), getattr(el, "Name", None), origin)].append(el)

    for (ifc_class, name, origin), group in buckets.items():
        if len(group) > 1:
            yield Issue(
                rule_id="INT.DUPLICATE_PLACEMENT",
                severity=Severity.WARNING,
                category=Category.INTEGRITY,
                title="Possible duplicated elements at identical coordinates",
                description=(
                    f"{len(group)} × {ifc_class} named '{name}' share the exact same "
                    "insertion point. This is almost always a copy-paste or a "
                    "double export, and it doubles quantities."
                ),
                elements=[ctx.ref(e) for e in group],
                location=origin,
                evidence={"key": f"{ifc_class}|{name}|{origin}", "origin": list(origin)},
            )


@rule(id="INT.ORPHAN_OPENING", title="Opening voids nothing",
      category=Category.INTEGRITY, severity=Severity.WARNING)
def orphan_opening(ctx: AuditContext):
    for op in ctx.model.by_type("IfcOpeningElement"):
        voids = getattr(op, "VoidsElements", None)
        if not voids:
            yield Issue(
                rule_id="INT.ORPHAN_OPENING",
                severity=Severity.WARNING,
                category=Category.INTEGRITY,
                title="Opening is not subtracted from any element",
                description=(
                    "An IfcOpeningElement with no IfcRelVoidsElement is dead data. "
                    "It usually means a hosted door or window lost its host."
                ),
                elements=[ctx.ref(op)],
                evidence={"key": op.GlobalId},
            )


@rule(id="INT.MISSING_COMMON_PSET", title="Missing Pset_<Class>Common",
      category=Category.INTEGRITY, severity=Severity.INFO)
def missing_common_pset(ctx: AuditContext):
    """Most classes have a standard 'common' pset. Its absence is the single
    best early indicator that the exporter's property mapping was never set up."""
    for el in ctx.checkable_elements:
        expected = f"Pset_{el.is_a()[3:]}Common"
        try:
            psets = ue.get_psets(el, psets_only=True)
        except Exception:
            continue
        if expected not in psets:
            yield Issue(
                rule_id="INT.MISSING_COMMON_PSET",
                severity=Severity.INFO,
                category=Category.INTEGRITY,
                title="Missing the buildingSMART common property set",
                description=(
                    "The standard Pset_<Class>Common for this element's class is "
                    "absent (see the Evidence column for the exact pset expected). "
                    "Any IDS or code check relying on its properties will fail."
                ),
                elements=[ctx.ref(el)],
                evidence={"key": el.GlobalId, "expected_pset": expected,
                          "found": sorted(psets.keys())},
            )

"""Built-in fixers, one per rule that can be repaired inside the IFC.

Element references in `ops` are STEP ids (#123), not GlobalIds: they are
unambiguous even when GUIDs are duplicated, and they stay valid because fixes
are always applied to a byte-identical copy of the audited file.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Optional

import ifcopenshell.util.element as ue

from ..context import AuditContext
from . import AUTO, INPUT, Field, Fix, fixer


def _entities(ctx: AuditContext, issue: dict) -> list:
    """All entities an issue points at, deduplicated, in file order."""
    found: dict[int, object] = {}
    for ref in issue.get("elements") or []:
        for el in ctx.guid_index.get(ref.get("guid") or "", []):
            found[el.id()] = el
    return [found[k] for k in sorted(found)]


def _name(el) -> str:
    name = getattr(el, "Name", None)
    return f"{el.is_a()} '{name}' (#{el.id()})" if name else f"{el.is_a()} #{el.id()}"


def _length_unit(ctx: AuditContext) -> Optional[str]:
    unit = ctx.units.get("length")
    return str(unit).lower() if unit else None


def _z(el) -> Optional[float]:
    import ifcopenshell.util.placement as up
    placement = getattr(el, "ObjectPlacement", None)
    if placement is None:
        return None
    try:
        return float(up.get_local_placement(placement)[2, 3])
    except Exception:
        return None


def _fmt(v: float) -> str:
    return f"{v:g}"


# --------------------------------------------------------------------------
# auto: no input needed
# --------------------------------------------------------------------------

@fixer("INT.DUPLICATE_GUID")
def duplicate_guid(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    group = ctx.guid_index.get(issue["evidence"].get("guid") or "", [])
    if len(group) < 2:
        return None
    keep, rest = group[0], group[1:]
    return Fix(
        issue_id=issue["id"], rule_id=issue["rule_id"], kind=AUTO,
        summary=f"Give {len(rest)} element(s) a new GlobalId",
        detail=(f"{_name(keep)} keeps {keep.GlobalId}. New GUIDs for: "
                + ", ".join(_name(e) for e in rest)
                + ". Anything outside this file that referenced the shared GUID "
                  "will now point at the kept element."),
        ops=[{"op": "regen_guid", "id": e.id()} for e in rest],
    )


@fixer("INT.DUPLICATE_PLACEMENT")
def duplicate_placement(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    group = _entities(ctx, issue)
    if len(group) < 2:
        return None
    # Keep the copy carrying the most property sets, then the earliest one.
    ranked = sorted(group, key=lambda e: (-len(ue.get_psets(e)), e.id()))
    keep, rest = ranked[0], ranked[1:]
    return Fix(
        issue_id=issue["id"], rule_id=issue["rule_id"], kind=AUTO,
        destructive=True,
        summary=f"Delete {len(rest)} stacked duplicate(s)",
        detail=f"Keeps {_name(keep)}. Deletes: " + ", ".join(_name(e) for e in rest),
        ops=[{"op": "remove", "id": e.id()} for e in rest],
    )


@fixer("INT.ORPHAN_OPENING")
def orphan_opening(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    group = _entities(ctx, issue)
    if not group:
        return None
    return Fix(
        issue_id=issue["id"], rule_id=issue["rule_id"], kind=AUTO,
        destructive=True,
        summary="Delete the opening",
        detail=f"Deletes {_name(group[0])}. It cuts nothing, so no geometry changes.",
        ops=[{"op": "remove", "id": e.id()} for e in group],
    )


# --------------------------------------------------------------------------
# input: a person supplies (or confirms) a value
# --------------------------------------------------------------------------

@fixer("INT.MISSING_CONTAINER")
def missing_container(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    group = _entities(ctx, issue)
    if not group or not ctx.storeys:
        return None
    storeys = sorted(ctx.storeys, key=lambda s: (s.Elevation is None,
                                                 s.Elevation or 0.0))
    unit = _length_unit(ctx) or "project units"
    options = [{"value": s.id(),
                "label": (s.Name or f"#{s.id()}")
                + (f" (elev {_fmt(s.Elevation)})" if s.Elevation is not None else "")}
               for s in storeys]

    default, inferred = None, None
    z = _z(group[0])
    levelled = [s for s in storeys if s.Elevation is not None]
    if z is not None and levelled:
        below = [s for s in levelled if s.Elevation <= z + 1e-9]
        pick = below[-1] if below else levelled[0]
        default = pick.id()
        inferred = (f"Element sits at z = {_fmt(z)} {unit}; the highest storey at "
                    f"or below that is {pick.Name} (elevation {_fmt(pick.Elevation)}).")
    return Fix(
        issue_id=issue["id"], rule_id=issue["rule_id"], kind=INPUT,
        summary="Assign to a storey",
        inferred=inferred,
        fields=[Field(name="storey", label="Storey", type="select",
                      options=options, default=default)],
        ops=[{"op": "assign_container", "id": e.id(), "storey": {"$field": "storey"}}
             for e in group],
    )


@fixer("SPA.STOREY_ELEVATION")
def storey_elevation(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    group = _entities(ctx, issue)
    if not group:
        return None
    known = sorted(s.Elevation for s in ctx.storeys if s.Elevation is not None)
    unit = _length_unit(ctx)
    default, inferred = None, None
    if len(known) >= 2:
        step = median(b - a for a, b in zip(known, known[1:]))
        if step > 0:
            default = known[-1] + step
            inferred = (f"Other storeys sit at {', '.join(_fmt(k) for k in known)}; "
                        f"typical spacing {_fmt(step)}, so the next level up would be "
                        f"{_fmt(default)}. Only right if this is the top storey.")
    return Fix(
        issue_id=issue["id"], rule_id=issue["rule_id"], kind=INPUT,
        summary="Set the storey elevation",
        inferred=inferred,
        fields=[Field(name="elevation", label="Elevation", type="number",
                      default=default, unit=unit)],
        ops=[{"op": "set_attr", "id": group[0].id(), "attr": "Elevation",
              "value": {"$field": "elevation"}}],
    )


@fixer("INT.EMPTY_NAME")
def empty_name(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    group = _entities(ctx, issue)
    if not group:
        return None
    return Fix(
        issue_id=issue["id"], rule_id=issue["rule_id"], kind=INPUT,
        summary="Give the element a name",
        fields=[Field(name="name", label="Name")],
        ops=[{"op": "set_attr", "id": e.id(), "attr": "Name",
              "value": {"$field": "name"}} for e in group],
    )


@fixer("INT.NO_MATERIAL")
def no_material(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    group = _entities(ctx, issue)
    if not group:
        return None
    existing = sorted({m.Name for m in ctx.model.by_type("IfcMaterial") if m.Name})
    return Fix(
        issue_id=issue["id"], rule_id=issue["rule_id"], kind=INPUT,
        summary="Assign a material",
        detail="An existing material with this name is reused; otherwise one is created.",
        fields=[Field(name="material", label="Material", suggestions=existing)],
        ops=[{"op": "assign_material", "id": e.id(), "value": {"$field": "material"}}
             for e in group],
    )


@fixer("PRJ.GEOREFERENCE")
def georeference(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    if not ctx.sites:
        return None
    site = ctx.sites[0]
    return Fix(
        issue_id=issue["id"], rule_id=issue["rule_id"], kind=INPUT,
        summary="Set the site latitude and longitude",
        element=_name(site),
        detail=("Decimal degrees, WGS84. This places the site on the globe; it is "
                "not a full IfcMapConversion to a projected CRS."),
        fields=[Field(name="lat", label="Latitude", type="number", min=-90, max=90),
                Field(name="lon", label="Longitude", type="number", min=-180, max=180)],
        ops=[{"op": "set_georef", "id": site.id(),
              "lat": {"$field": "lat"}, "lon": {"$field": "lon"}}],
    )


# --------------------------------------------------------------------------
# proxies: suggest a real class from the exported family / type name
# --------------------------------------------------------------------------

# First match wins, so specific words come before general ones ("Trim-Window"
# is a trim, not a window). Matched against Name, ObjectType and the type's
# name, which is where Revit puts "Family:Type".
CLASS_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("mullion", "muntin"), "IfcMember"),
    (("trim", "casing", "cornice", "corniche", "moulding", "molding", "skirting",
      "baseboard", "fascia", "soffit", "cladding", "ceiling"), "IfcCovering"),
    (("curtain wall", "curtainwall"), "IfcCurtainWall"),
    (("railing", "handrail", "balustrade", "guardrail", "baluster"), "IfcRailing"),
    (("stair",), "IfcStair"),
    (("ramp",), "IfcRamp"),
    (("door",), "IfcDoor"),
    (("window",), "IfcWindow"),
    (("wall",), "IfcWall"),
    (("roof",), "IfcRoof"),
    (("slab", "floor"), "IfcSlab"),
    (("column", "pillar", "post"), "IfcColumn"),
    (("beam", "joist", "girder", "lintel", "purlin"), "IfcBeam"),
    (("footing", "foundation", "pile"), "IfcFooting"),
    (("plate",), "IfcPlate"),
    (("brace", "strut", "member"), "IfcMember"),
    (("furniture", "chair", "table", "desk", "sofa", "bed", "cabinet",
      "casework", "shelf", "wardrobe"), "IfcFurniture"),
    (("sink", "toilet", "wc", "basin", "lavatory", "urinal", "shower",
      "bath"), "IfcSanitaryTerminal"),
    (("light", "lamp", "luminaire"), "IfcLightFixture"),
    (("duct",), "IfcDuctSegment"),
    (("pipe",), "IfcPipeSegment"),
]
COMMON_CLASSES = ["IfcWall", "IfcSlab", "IfcRoof", "IfcColumn", "IfcBeam",
                  "IfcMember", "IfcPlate", "IfcCovering", "IfcDoor", "IfcWindow",
                  "IfcCurtainWall", "IfcRailing", "IfcStair", "IfcRamp",
                  "IfcFooting", "IfcFurniture", "IfcSanitaryTerminal",
                  "IfcLightFixture", "IfcDuctSegment", "IfcPipeSegment"]


def _suggest_class(texts: list[str]) -> tuple[Optional[str], Optional[str]]:
    for text in texts:
        low = text.lower()
        for words, cls in CLASS_HINTS:
            for w in words:
                if re.search(rf"(?<![a-z]){re.escape(w)}", low):
                    return cls, f"'{text}' contains '{w}'"
    return None, None


@fixer("INT.PROXY_ELEMENT")
def proxy_element(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    group = _entities(ctx, issue)
    if not group:
        return None
    el = group[0]
    classes = [c for c in COMMON_CLASSES if _declared(ctx, c)]

    element_type = ue.get_type(el)
    texts = [t for t in (getattr(el, "Name", None), getattr(el, "ObjectType", None),
                         getattr(element_type, "Name", None)) if t and str(t).strip()]
    suggested, why = _suggest_class(texts)
    if suggested not in classes:
        suggested, why = None, None

    detail = "Keeps its GlobalId, geometry, properties and relationships."
    if element_type is not None:
        siblings = len(ue.get_types(element_type))
        if siblings > 1:
            detail += (f" Its type is reclassified too, which also changes the "
                       f"other {siblings - 1} element(s) of that type.")
    return Fix(
        issue_id=issue["id"], rule_id=issue["rule_id"], kind=INPUT,
        summary="Change to a real IFC class",
        detail=detail,
        inferred=(f"{suggested}, because {why}." if suggested else None),
        fields=[Field(name="cls", label="IFC class", type="select",
                      default=suggested,
                      options=[{"value": c, "label": c} for c in classes])],
        ops=[{"op": "reclass", "id": el.id(), "value": {"$field": "cls"}}],
    )


def _declared(ctx: AuditContext, ifc_class: str) -> bool:
    import ifcopenshell
    try:
        ifcopenshell.schema_by_name(ctx.model.schema).declaration_by_name(ifc_class)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# IDS: the requirement names exactly what is missing
# --------------------------------------------------------------------------

TEXT_MEASURES = {"IfcLabel", "IfcText", "IfcIdentifier"}
BOOL_MEASURES = {"IfcBoolean", "IfcLogical"}
_TEMPLATES: dict[str, object] = {}


def _property_field(ctx: AuditContext, pset: str, prop: str, expected) -> Field:
    import ifcopenshell.util.pset as up

    schema = ctx.schema.upper()
    if schema not in _TEMPLATES:
        try:
            _TEMPLATES[schema] = up.get_template(schema)
        except Exception:
            _TEMPLATES[schema] = None
    template = _TEMPLATES[schema]

    measure, enum = None, None
    pset_t = template.get_by_name(pset) if template else None
    for p in (getattr(pset_t, "HasPropertyTemplates", None) or []):
        if p.Name == prop:
            measure = p.PrimaryMeasureType
            if p.TemplateType == "P_ENUMERATEDVALUE" and p.Enumerators:
                enum = [v.wrappedValue for v in p.Enumerators.EnumerationValues]
            break

    default = expected if isinstance(expected, (str, int, float, bool)) else None
    label = f"{pset}.{prop}"
    if enum:
        return Field(name="value", label=label, type="select", default=default,
                     options=[{"value": v, "label": v} for v in enum])
    if measure in BOOL_MEASURES:
        return Field(name="value", label=label, type="bool", default=default,
                     options=[{"value": True, "label": "True"},
                              {"value": False, "label": "False"}])
    if measure and measure not in TEXT_MEASURES:
        unit = (_length_unit(ctx) if measure in ("IfcLengthMeasure",
                                                 "IfcPositiveLengthMeasure")
                else measure.removeprefix("Ifc").removesuffix("Measure"))
        return Field(name="value", label=label, type="number", default=default,
                     unit=unit)
    return Field(name="value", label=label, default=default)


@fixer("IDS.*")
def ids_requirement(ctx: AuditContext, issue: dict) -> Optional[Fix]:
    group = _entities(ctx, issue)
    requirement = (issue.get("evidence") or {}).get("requirement") or ""
    expected = (issue.get("evidence") or {}).get("expected")
    if not group or not requirement:
        return None

    attr = re.fullmatch(r"attribute '(\w+)'", requirement)
    if attr:
        name = attr.group(1)
        return Fix(
            issue_id=issue["id"], rule_id=issue["rule_id"], kind=INPUT,
            summary=f"Set the {name} attribute",
            fields=[Field(name="value", label=name,
                          default=expected if isinstance(expected, str) else None)],
            ops=[{"op": "set_attr", "id": e.id(), "attr": name,
                  "value": {"$field": "value"}} for e in group],
        )

    if "." in requirement:
        pset, prop = requirement.split(".", 1)
        return Fix(
            issue_id=issue["id"], rule_id=issue["rule_id"], kind=INPUT,
            summary=f"Set {pset}.{prop}",
            detail="Written on the element itself, not its type, so other "
                   "elements of the same type are unaffected.",
            fields=[_property_field(ctx, pset, prop, expected)],
            ops=[{"op": "set_prop", "id": e.id(), "pset": pset, "prop": prop,
                  "value": {"$field": "value"}} for e in group],
        )
    return None

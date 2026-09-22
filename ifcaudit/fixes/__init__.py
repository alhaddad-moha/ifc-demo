"""Fixes: turn an Issue into a proposed, reviewable change to the model.

A fixer never changes anything by itself. It *proposes* a Fix: what it will
change, which values it needs from a person, and whether it deletes anything.
Only fixes a person approves are applied, and always to a copy of the file.
The web layer (webapp/jobs.py) is responsible for that copy.

A Fix carries its operations as plain data (`ops`), generated on the server
from the model. The client only ever sends back issue ids and typed values,
never operations, so it cannot ask for an edit no fixer proposed.

Values are never invented. A fixer may *suggest* a value it can derive
deterministically from the model (a storey from an element's height) and says
how it got there in `inferred`; a person still confirms it. Anything that is a
design or safety decision (a fire rating, a material, a site coordinate)
comes from the user.

Registering a fixer mirrors registering a rule:

    @fixer("INT.ORPHAN_OPENING")
    def remove_opening(ctx, issue) -> Fix | None: ...

Returning None falls back to a MANUAL fix carrying the rule's advice.
"""

from __future__ import annotations

import datetime
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from ..context import AuditContext

AUTO = "auto"        # no input needed, a person only approves
INPUT = "input"      # needs one or more values from a person
MANUAL = "manual"    # cannot be fixed in the IFC, advice only


@dataclass
class Field:
    name: str
    label: str
    type: str = "text"                 # text | number | bool | select
    options: list[dict] = field(default_factory=list)   # [{"value", "label"}]
    suggestions: list[str] = field(default_factory=list)  # free text hints
    default: Any = None
    unit: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    required: bool = True


@dataclass
class Fix:
    issue_id: str
    rule_id: str
    kind: str
    summary: str
    title: str = ""
    severity: str = ""
    element: str = ""
    detail: str = ""
    inferred: Optional[str] = None
    destructive: bool = False
    fields: list[Field] = field(default_factory=list)
    ops: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FIXERS: dict[str, Callable[[AuditContext, dict], Optional[Fix]]] = {}

# Shown for issues that cannot be repaired inside the IFC. Matched exactly,
# then by prefix ending in ".".
ADVICE: dict[str, str] = {
    "INT.NO_GEOMETRY": "Geometry can't be created here. Model the element, or "
                       "enable geometry export for its category, and re-export.",
    "INT.PROXY_ELEMENT": "Map this family/category to a real IFC class in the "
                         "exporter's class mapping and re-export.",
    "INT.NO_TYPE": "Enable type export in the authoring tool (or assign a type "
                   "there) and re-export.",
    "INT.MISSING_COMMON_PSET": "Enable the buildingSMART common property sets "
                               "in the exporter settings and re-export.",
    "SPA.NO_SPACES": "Place rooms/spaces in the authoring model and enable "
                     "room export.",
    "SPA.NO_STOREYS": "Create levels in the authoring model and re-export.",
    "SPA.DUPLICATE_STOREY_ELEVATION": "Check for a merged or copied level in the "
                                      "authoring model; decide which one is real.",
    "PRJ.UNITS": "Set the project units in the authoring tool and re-export. "
                 "Rewriting units here would silently rescale every dimension.",
    "PRJ.NO_PROJECT": "The file structure is broken; re-export it.",
    "PRJ.SCHEMA_VERSION": "Re-export as IFC4 (or IFC4.3 for infrastructure).",
    "SCHEMA.": "Schema violations come from the exporter. Report them to the "
               "authoring-tool vendor or re-export with different settings.",
    "IDS.": "No automatic fix for this requirement. Add the data in the "
            "authoring tool, or check the IDS applicability filter.",
    "ENGINE.": "This is a crash in a check, not a defect in the model.",
}
DEFAULT_ADVICE = "No automatic fix. Correct it in the authoring tool and re-export."


def fixer(*rule_ids: str):
    """Register a proposer. A rule id ending in '*' matches by prefix."""
    def wrap(fn):
        for rid in rule_ids:
            FIXERS[rid] = fn
        return fn
    return wrap


def _lookup(table: dict, rule_id: str, star: str):
    if rule_id in table:
        return table[rule_id]
    for key, value in table.items():
        if key.endswith(star) and rule_id.startswith(key.rstrip("*")):
            return value
    return None


def element_label(issue: dict) -> str:
    els = issue.get("elements") or []
    if not els:
        return "model-wide"
    e = els[0]
    bits = [e.get("ifc_class") or "?"]
    if e.get("name") and str(e["name"]).strip():
        bits.append(f"'{e['name']}'")
    if len(els) > 1:
        bits.append(f"+{len(els) - 1} more")
    return " ".join(bits)


def propose(ctx: AuditContext, issue: dict) -> Fix:
    fn = _lookup(FIXERS, issue["rule_id"], "*")
    fix = None
    if fn is not None:
        try:
            fix = fn(ctx, issue)
        except Exception:
            # A broken fixer degrades to advice; it never breaks the list.
            fix = None
    if fix is None:
        fix = Fix(issue_id=issue["id"], rule_id=issue["rule_id"], kind=MANUAL,
                  summary=_lookup(ADVICE, issue["rule_id"], ".") or DEFAULT_ADVICE)
    fix.issue_id = issue["id"]
    fix.rule_id = issue["rule_id"]
    fix.title = fix.title or issue.get("title", "")
    fix.severity = issue.get("severity", "")
    fix.element = fix.element or element_label(issue)
    return fix


def propose_all(ctx: AuditContext, issues: list[dict]) -> list[Fix]:
    from . import builtin  # noqa: F401  (registers the built-in fixers)
    seen: set[str] = set()
    out = []
    for issue in issues:
        # Two issues can share an id (same defect reported twice through a
        # duplicated GUID); one fix covers both.
        if issue["id"] in seen:
            continue
        seen.add(issue["id"])
        out.append(propose(ctx, issue))
    return out


# --------------------------------------------------------------------------
# values
# --------------------------------------------------------------------------

TRUE = {"true", "1", "yes"}
FALSE = {"false", "0", "no"}


def coerce(fix: Fix, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and type the values a person supplied. Raises ValueError."""
    out: dict[str, Any] = {}
    for f in fix.fields:
        value = raw.get(f.name, f.default)
        if value is None or (isinstance(value, str) and not value.strip()):
            if f.required:
                raise ValueError(f"{f.label} is required")
            continue
        if f.type == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{f.label} must be a number")
            if f.min is not None and value < f.min:
                raise ValueError(f"{f.label} must be ≥ {f.min}")
            if f.max is not None and value > f.max:
                raise ValueError(f"{f.label} must be ≤ {f.max}")
        elif f.type == "bool":
            text = str(value).strip().lower()
            if text not in TRUE | FALSE:
                raise ValueError(f"{f.label} must be true or false")
            value = text in TRUE
        elif f.type == "select":
            match = [o["value"] for o in f.options if str(o["value"]) == str(value)]
            if not match:
                raise ValueError(f"{f.label}: '{value}' is not one of the options")
            value = match[0]
        else:
            value = str(value).strip()[:255]
        out[f.name] = value
    return out


def _bind(op: dict, values: dict[str, Any]) -> dict:
    bound = {}
    for k, v in op.items():
        if isinstance(v, dict) and "$field" in v:
            bound[k] = values[v["$field"]]
        else:
            bound[k] = v
    return bound


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------

# Edits first, GUID changes next, deletions last, so a fix that edits an
# element is not lost because another fix deleted it first.
PRIORITY = {"regen_guid": 1, "remove": 2}


class _Skip(Exception):
    pass


def apply(model, fixes: list[Fix], values: dict[str, dict]) -> dict[str, Any]:
    """Apply approved fixes to `model` in place (the caller passes a copy).

    One fix failing never stops the others; each is recorded in the change
    log with its outcome.
    """
    changes: list[dict] = []
    plan = []
    for fix in fixes:
        entry = {"issue_id": fix.issue_id, "rule_id": fix.rule_id,
                 "element": fix.element, "summary": fix.summary,
                 "values": {}, "status": "applied", "message": ""}
        changes.append(entry)
        if fix.kind == MANUAL:
            entry.update(status="skipped", message="Manual fix; nothing to apply")
            continue
        try:
            vals = coerce(fix, values.get(fix.issue_id, {}))
        except ValueError as exc:
            entry.update(status="failed", message=str(exc))
            continue
        entry["values"] = vals
        ops = [_bind(op, vals) for op in fix.ops]
        plan.append((max((PRIORITY.get(o["op"], 0) for o in ops), default=0),
                     len(plan), entry, ops))

    plan.sort(key=lambda p: (p[0], p[1]))
    removed: set[int] = set()
    guids: list[dict] = []

    for _, _, entry, ops in plan:
        try:
            if any(op.get("id") in removed for op in ops):
                raise _Skip("element was already deleted by another fix")
            for op in ops:
                _run_op(model, op, removed, guids)
        except _Skip as exc:
            entry.update(status="skipped", message=str(exc))
        except Exception as exc:
            entry.update(status="failed",
                         message=f"{type(exc).__name__}: {exc}"[:300])
            entry["traceback"] = traceback.format_exc()[-600:]

    counts = {"applied": 0, "failed": 0, "skipped": 0}
    for c in changes:
        counts[c["status"]] += 1
    return {
        "applied_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "counts": counts,
        "changes": changes,
        "regenerated_guids": guids,
        "removed_ids": sorted(removed),
    }


def _run_op(model, op: dict, removed: set[int], guids: list[dict]) -> None:
    import ifcopenshell.api.attribute
    import ifcopenshell.api.material
    import ifcopenshell.api.pset
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.guid
    import ifcopenshell.util.element as ue

    kind = op["op"]
    el = model.by_id(op["id"])

    if kind == "set_attr":
        ifcopenshell.api.attribute.edit_attributes(
            model, product=el, attributes={op["attr"]: op["value"]})
    elif kind == "set_prop":
        # Occurrence-level only: editing an inherited type pset would silently
        # change every sibling of the same type.
        psets = ue.get_psets(el, psets_only=True, should_inherit=False)
        if op["pset"] in psets:
            pset = model.by_id(psets[op["pset"]]["id"])
        else:
            pset = ifcopenshell.api.pset.add_pset(model, product=el, name=op["pset"])
        ifcopenshell.api.pset.edit_pset(model, pset=pset,
                                        properties={op["prop"]: op["value"]})
    elif kind == "assign_container":
        ifcopenshell.api.spatial.assign_container(
            model, products=[el], relating_structure=model.by_id(op["storey"]))
    elif kind == "assign_material":
        name = op["value"]
        material = next((m for m in model.by_type("IfcMaterial") if m.Name == name),
                        None)
        if material is None:
            material = ifcopenshell.api.material.add_material(model, name=name)
        ifcopenshell.api.material.assign_material(model, products=[el],
                                                  material=material)
    elif kind == "set_georef":
        el.RefLatitude = _dms(op["lat"])
        el.RefLongitude = _dms(op["lon"])
    elif kind == "regen_guid":
        old = el.GlobalId
        el.GlobalId = ifcopenshell.guid.new()
        guids.append({"id": el.id(), "old": old, "new": el.GlobalId})
    elif kind == "remove":
        ifcopenshell.api.root.remove_product(model, product=el)
        removed.add(op["id"])
    else:
        raise ValueError(f"unknown operation {kind!r}")


def _dms(dd: float) -> tuple[int, int, int, int]:
    """Decimal degrees -> IfcCompoundPlaneAngleMeasure. Every component
    carries the sign, as IFC requires."""
    sign = -1 if dd < 0 else 1
    micro_total = round(abs(dd) * 3600 * 1_000_000)
    deg, rem = divmod(micro_total, 3600 * 1_000_000)
    minutes, rem = divmod(rem, 60 * 1_000_000)
    seconds, micro = divmod(rem, 1_000_000)
    return (sign * deg, sign * minutes, sign * seconds, sign * micro)

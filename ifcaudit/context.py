"""AuditContext — the model plus the indexes every rule needs.

Built once, passed to every rule. Rules never call ifcopenshell.open()
themselves and never re-scan the file; they query these indexes.
"""

from __future__ import annotations

import os
from functools import cached_property
from typing import Any, Optional

import ifcopenshell
import ifcopenshell.util.element as ue
import ifcopenshell.util.unit as uu

# IFC classes that represent something physically built. Used everywhere,
# so it lives here rather than being re-derived in each rule.
PHYSICAL_ROOT = "IfcElement"

# Classes we deliberately do NOT expect to be contained in a storey.
CONTAINER_EXEMPT = (
    "IfcOpeningElement",
    "IfcFeatureElement",
    "IfcFeatureElementSubtraction",
    "IfcFeatureElementAddition",
    "IfcVirtualElement",
    "IfcGrid",
    "IfcAnnotation",
)


class AuditContext:
    def __init__(self, model: ifcopenshell.file, path: str):
        self.model = model
        self.path = path
        self.filename = os.path.basename(path)

    # ---------- basic project facts ----------

    @property
    def schema(self) -> str:
        return self.model.schema

    @cached_property
    def project(self):
        projects = self.model.by_type("IfcProject")
        return projects[0] if projects else None

    @cached_property
    def project_name(self) -> Optional[str]:
        return getattr(self.project, "Name", None) if self.project else None

    @cached_property
    def unit_scale(self) -> float:
        """Metres per project length unit. NEVER hardcode mm or m."""
        try:
            return uu.calculate_unit_scale(self.model)
        except Exception:
            return 1.0

    @cached_property
    def units(self) -> dict[str, Any]:
        info: dict[str, Any] = {"length_to_metre": self.unit_scale}
        try:
            length = uu.get_project_unit(self.model, "LENGTHUNIT")
            info["length"] = uu.get_full_unit_name(length) if length else None
        except Exception:
            info["length"] = None
        try:
            area = uu.get_project_unit(self.model, "AREAUNIT")
            info["area"] = uu.get_full_unit_name(area) if area else None
        except Exception:
            info["area"] = None
        return info

    # ---------- indexes ----------

    @cached_property
    def elements(self) -> list:
        """All physical elements (walls, doors, pipes...), not spatial containers."""
        return list(self.model.by_type(PHYSICAL_ROOT))

    @cached_property
    def checkable_elements(self) -> list:
        """Physical elements a human would expect to see in a model tree."""
        return [e for e in self.elements if not e.is_a(CONTAINER_EXEMPT[0])
                and not any(e.is_a(c) for c in CONTAINER_EXEMPT)]

    @cached_property
    def storeys(self) -> list:
        return list(self.model.by_type("IfcBuildingStorey"))

    @cached_property
    def buildings(self) -> list:
        return list(self.model.by_type("IfcBuilding"))

    @cached_property
    def sites(self) -> list:
        return list(self.model.by_type("IfcSite"))

    @cached_property
    def spaces(self) -> list:
        return list(self.model.by_type("IfcSpace"))

    @cached_property
    def guid_index(self) -> dict[str, list]:
        """GlobalId -> entities. A list, because duplicated GUIDs are exactly
        what some rules find — by_guid() would silently return just one."""
        out: dict[str, list] = {}
        for el in self.model.by_type("IfcRoot"):
            if el.GlobalId:
                out.setdefault(el.GlobalId, []).append(el)
        return out

    @cached_property
    def storey_of(self) -> dict[int, str]:
        """element id -> storey name. Resolved once, reused by every rule."""
        out: dict[int, str] = {}
        for el in self.elements:
            try:
                container = ue.get_container(el)
            except Exception:
                container = None
            if container is not None:
                out[el.id()] = getattr(container, "Name", None) or container.is_a()
        return out

    def storey_name(self, element) -> Optional[str]:
        return self.storey_of.get(element.id())

    def ref(self, element):
        from .issues import ElementRef
        return ElementRef.from_entity(
            element, storey=self.storey_name(element), source_file=self.filename
        )

    # ---------- stats for the report header ----------

    @cached_property
    def stats(self) -> dict[str, Any]:
        by_class: dict[str, int] = {}
        for el in self.elements:
            by_class[el.is_a()] = by_class.get(el.is_a(), 0) + 1
        return {
            "total_entities": len(self.model.by_type("IfcRoot")),
            "elements": len(self.elements),
            "storeys": len(self.storeys),
            "buildings": len(self.buildings),
            "spaces": len(self.spaces),
            "by_class": dict(sorted(by_class.items(), key=lambda kv: -kv[1])),
        }


def load(path: str) -> AuditContext:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"IFC file not found: {path}")
    model = ifcopenshell.open(path)
    return AuditContext(model, path)

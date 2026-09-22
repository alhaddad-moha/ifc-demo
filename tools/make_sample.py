"""Generate a small IFC4 model with deliberate, known defects.

This exists so you can run the auditor immediately without hunting for a
real project file. Every defect it injects is listed in DEFECTS below, so
you can check the report catches what it should.

    python tools/make_sample.py examples/sample_model.ifc
    python tools/make_sample.py examples/clean_model.ifc --clean

--clean builds a defect-free model instead: the baseline that should audit
with zero issues.
"""

from __future__ import annotations

import sys
import os

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.api.unit

DEFECTS = [
    "Duplicate GlobalId shared by two walls",
    "One pipe segment with no spatial container",
    "One wall with a blank Name",
    "One door with no geometric representation",
    "One IfcBuildingElementProxy (unclassified export)",
    "Two identical walls at the same insertion point",
    "One IfcOpeningElement that voids nothing",
    "One storey with no Elevation",
    "No georeferencing (no IfcMapConversion, no site lat/long)",
    "Doors missing FireRating -> IDS failure",
    "External walls missing IsExternal -> IDS failure",
    "No materials on most elements",
]


def box_representation(f, context, x=1.0, y=0.2, z=3.0):
    """A simple extruded rectangle, enough to count as real geometry."""
    profile = f.create_entity(
        "IfcRectangleProfileDef", ProfileType="AREA", XDim=x, YDim=y
    )
    direction = f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
    point = f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axis = f.create_entity("IfcAxis2Placement3D", Location=point)
    solid = f.create_entity(
        "IfcExtrudedAreaSolid", SweptArea=profile, Position=axis,
        ExtrudedDirection=direction, Depth=z,
    )
    shape = f.create_entity(
        "IfcShapeRepresentation", ContextOfItems=context,
        RepresentationIdentifier="Body", RepresentationType="SweptSolid",
        Items=[solid],
    )
    return f.create_entity("IfcProductDefinitionShape", Representations=[shape])


def placement(f, xyz=(0.0, 0.0, 0.0)):
    point = f.create_entity("IfcCartesianPoint",
                            Coordinates=tuple(float(v) for v in xyz))
    axis = f.create_entity("IfcAxis2Placement3D", Location=point)
    return f.create_entity("IfcLocalPlacement", RelativePlacement=axis)


def build(path: str) -> None:
    f = ifcopenshell.api.project.create_file(version="IFC4")

    project = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcProject", name="RND Demo Tower"
    )
    ifcopenshell.api.unit.assign_unit(f)

    ctx = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=ctx,
    )

    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuilding", name="Tower A"
    )
    l00 = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuildingStorey", name="L00 Ground"
    )
    l01 = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuildingStorey", name="L01 First"
    )
    l02 = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuildingStorey", name="L02 Second"
    )
    l00.Elevation = 0.0
    l01.Elevation = 4.0
    # DEFECT: l02 deliberately left with no Elevation

    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(
        f, products=[l00, l01, l02], relating_object=building
    )

    def make(ifc_class, name, storey, geometry=True, xyz=(0.0, 0.0, 0.0),
             predefined_type=None):
        el = ifcopenshell.api.root.create_entity(
            f, ifc_class=ifc_class, name=name, predefined_type=predefined_type
        )
        el.ObjectPlacement = placement(f, xyz)
        if geometry:
            el.Representation = box_representation(f, body)
        if storey is not None:
            ifcopenshell.api.spatial.assign_container(
                f, products=[el], relating_structure=storey
            )
        return el

    # --- healthy-ish elements -------------------------------------------
    good_walls = []
    for i in range(6):
        w = make("IfcWall", f"WAL-EXT-{i + 1:02d}", l00, xyz=(i * 5.0, 0.0, 0.0))
        good_walls.append(w)

    # Two of them get a proper common pset so the IDS has something to pass on
    for w in good_walls[:2]:
        pset = ifcopenshell.api.pset.add_pset(f, product=w, name="Pset_WallCommon")
        ifcopenshell.api.pset.edit_pset(
            f, pset=pset, properties={"IsExternal": True, "LoadBearing": True}
        )

    doors = []
    for i in range(4):
        d = make("IfcDoor", f"DR-{i + 1:02d}", l01, xyz=(i * 3.0, 2.0, 0.0))
        doors.append(d)
    # Only the first door gets a FireRating -> the other three fail the IDS
    pset = ifcopenshell.api.pset.add_pset(f, product=doors[0], name="Pset_DoorCommon")
    ifcopenshell.api.pset.edit_pset(
        f, pset=pset, properties={"FireRating": "EI60", "IsExternal": False}
    )

    for i in range(3):
        make("IfcSlab", f"SLB-{i + 1:02d}", l01, xyz=(0.0, i * 6.0, 0.0),
             predefined_type="FLOOR")

    for i in range(4):
        make("IfcWindow", f"WIN-{i + 1:02d}", l01, xyz=(i * 4.0, 8.0, 1.0))

    # --- deliberate defects ---------------------------------------------

    # 1. duplicate GlobalId
    twin_a = make("IfcWall", "WAL-DUP-GUID", l00, xyz=(40.0, 0.0, 0.0))
    twin_b = make("IfcWall", "WAL-DUP-GUID-B", l00, xyz=(41.0, 0.0, 0.0))
    twin_b.GlobalId = twin_a.GlobalId

    # 2. element with no spatial container
    make("IfcPipeSegment", "PIP-ORPHAN-01", None, xyz=(2.0, 2.0, 3.5))

    # 3. blank name
    blank = make("IfcWall", None, l00, xyz=(50.0, 0.0, 0.0))
    blank.Name = "   "

    # 4. door with no geometry
    make("IfcDoor", "DR-NOGEO-01", l01, geometry=False, xyz=(20.0, 2.0, 0.0))

    # 5. unclassified proxy
    make("IfcBuildingElementProxy", "UNKNOWN-ASSEMBLY-01", l02, xyz=(1.0, 1.0, 0.0))

    # 6. two identical walls at the same point
    make("IfcWall", "WAL-CLONE", l02, xyz=(10.0, 10.0, 0.0))
    make("IfcWall", "WAL-CLONE", l02, xyz=(10.0, 10.0, 0.0))

    # 7. opening that voids nothing
    orphan_opening = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcOpeningElement", name="OPN-ORPHAN-01"
    )
    orphan_opening.ObjectPlacement = placement(f, (3.0, 0.0, 1.0))
    orphan_opening.Representation = box_representation(f, body, 0.9, 0.3, 2.1)

    # 8. a few MEP items so the model has more than one discipline
    for i in range(3):
        make("IfcDuctSegment", f"DCT-{i + 1:02d}", l01, xyz=(i * 2.0, 5.0, 3.2))

    f.write(path)


def build_clean(path: str) -> None:
    """The same tower with no defects: the baseline that proves the ruleset
    raises nothing on a model that has nothing wrong with it.

    Only classes with a real buildingSMART Pset_<Class>Common are used, so
    INT.MISSING_COMMON_PSET has something legitimate to find. Project units are
    millimetres, so every dimension below is in mm.
    """
    f = ifcopenshell.api.project.create_file(version="IFC4")

    project = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcProject", name="RND Demo Tower (clean)"
    )
    ifcopenshell.api.unit.assign_unit(f)

    ctx = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=ctx,
    )

    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    site.RefLatitude = (24, 42, 50, 0)
    site.RefLongitude = (46, 40, 30, 0)
    site.RefElevation = 612000.0
    building = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuilding", name="Tower A"
    )
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)

    storeys = []
    for i, name in enumerate(("L00 Ground", "L01 First", "L02 Second")):
        s = ifcopenshell.api.root.create_entity(
            f, ifc_class="IfcBuildingStorey", name=name
        )
        s.Elevation = i * 4000.0
        storeys.append(s)
    ifcopenshell.api.aggregate.assign_object(
        f, products=storeys, relating_object=building
    )

    concrete = ifcopenshell.api.material.add_material(f, name="Concrete C40", category="concrete")
    steel = ifcopenshell.api.material.add_material(f, name="Steel S355", category="steel")
    timber = ifcopenshell.api.material.add_material(f, name="Oak", category="wood")
    glass = ifcopenshell.api.material.add_material(f, name="Double glazing", category="glass")

    def make_type(ifc_class, name, material, predefined_type, **attrs):
        t = ifcopenshell.api.root.create_entity(
            f, ifc_class=ifc_class, name=name, predefined_type=predefined_type
        )
        for k, v in attrs.items():
            setattr(t, k, v)
        ifcopenshell.api.material.assign_material(f, products=[t], material=material)
        return t

    types = {
        "IfcWall": make_type("IfcWallType", "WT-200 Concrete", concrete, "SOLIDWALL"),
        "IfcDoor": make_type("IfcDoorType", "DT-900 Oak", timber, "DOOR",
                             OperationType="SINGLE_SWING_LEFT"),
        "IfcWindow": make_type("IfcWindowType", "WNT-1200 DG", glass, "WINDOW",
                               PartitioningType="SINGLE_PANEL"),
        "IfcSlab": make_type("IfcSlabType", "ST-250 Concrete", concrete, "FLOOR"),
        "IfcColumn": make_type("IfcColumnType", "CT-400 Concrete", concrete, "COLUMN"),
        "IfcBeam": make_type("IfcBeamType", "BT-IPE300", steel, "BEAM"),
    }

    common = {
        "IfcWall": {"IsExternal": True, "LoadBearing": True},
        "IfcDoor": {"FireRating": "EI60", "IsExternal": False},
        "IfcWindow": {"ThermalTransmittance": 1.6, "IsExternal": True},
        "IfcSlab": {"IsExternal": False, "LoadBearing": True},
        "IfcColumn": {"IsExternal": False, "LoadBearing": True},
        "IfcBeam": {"IsExternal": False, "LoadBearing": True},
    }

    def make(ifc_class, name, storey, xyz, size, predefined_type=None):
        el = ifcopenshell.api.root.create_entity(
            f, ifc_class=ifc_class, name=name, predefined_type=predefined_type
        )
        el.ObjectPlacement = placement(f, xyz)
        el.Representation = box_representation(f, body, *size)
        ifcopenshell.api.spatial.assign_container(
            f, products=[el], relating_structure=storey
        )
        ifcopenshell.api.type.assign_type(
            f, related_objects=[el], relating_type=types[ifc_class]
        )
        pset = ifcopenshell.api.pset.add_pset(
            f, product=el, name=f"Pset_{ifc_class[3:]}Common"
        )
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties=common[ifc_class])
        return el

    for level, storey in enumerate(storeys):
        tag = f"L{level:02d}"
        for i in range(4):
            make("IfcWall", f"WAL-{tag}-{i + 1:02d}", storey,
                 (i * 5000.0, 0.0, 0.0), (5000.0, 200.0, 3000.0), "SOLIDWALL")
        for i in range(2):
            make("IfcDoor", f"DR-{tag}-{i + 1:02d}", storey,
                 (1000.0 + i * 10000.0, 0.0, 0.0), (900.0, 200.0, 2100.0), "DOOR")
        for i in range(2):
            make("IfcWindow", f"WIN-{tag}-{i + 1:02d}", storey,
                 (3000.0 + i * 10000.0, 0.0, 900.0), (1200.0, 200.0, 1500.0), "WINDOW")
        make("IfcSlab", f"SLB-{tag}-01", storey,
             (0.0, 0.0, -250.0), (20000.0, 8000.0, 250.0), "FLOOR")
        for i in range(2):
            make("IfcColumn", f"COL-{tag}-{i + 1:02d}", storey,
                 (i * 10000.0, 4000.0, 0.0), (400.0, 400.0, 3750.0), "COLUMN")
        make("IfcBeam", f"BM-{tag}-01", storey,
             (0.0, 4000.0, 3450.0), (10000.0, 150.0, 300.0), "BEAM")

        space = ifcopenshell.api.root.create_entity(
            f, ifc_class="IfcSpace", name=f"SP-{tag}-01", predefined_type="INTERNAL"
        )
        space.LongName = "Open office"
        space.ObjectPlacement = placement(f, (0.0, 200.0, 0.0))
        space.Representation = box_representation(f, body, 20000.0, 7800.0, 3000.0)
        ifcopenshell.api.aggregate.assign_object(f, products=[space], relating_object=storey)
        pset = ifcopenshell.api.pset.add_pset(f, product=space, name="Pset_SpaceCommon")
        ifcopenshell.api.pset.edit_pset(
            f, pset=pset, properties={"IsExternal": False, "Reference": "OFF"}
        )

    f.write(path)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    clean = "--clean" in sys.argv[1:]
    default = "examples/clean_model.ifc" if clean else "examples/sample_model.ifc"
    out = args[0] if args else default
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    if clean:
        build_clean(out)
        print(f"Wrote {out} (clean: no defects injected)")
        return
    build(out)
    print(f"Wrote {out}")
    print("\nDeliberate defects injected:")
    for d in DEFECTS:
        print(f"  - {d}")


if __name__ == "__main__":
    main()

"""Generate the example IDS file.

IDS is XML, and hand-writing it is miserable — which is exactly why this
script exists. It uses ifctester's own object model, so the output always
matches the IDS version shipped with your IfcOpenShell install.

    python tools/make_ids.py examples/project_requirements.ids

Once generated, examples/project_requirements.ids is a normal file you can
edit by hand or open in any IDS editor.
"""

from __future__ import annotations

import os
import sys
import datetime

from ifctester import ids


def build() -> ids.Ids:
    spec_set = ids.Ids(
        title="RND Demo — Employer Information Requirements",
        description="Minimum information requirements for handover models.",
        author="fortech.sa7@gmail.com",
        version="1.0",
        date=datetime.date.today().isoformat(),
        purpose="Demonstration ruleset for the ifc-demo auditor",
    )

    # --- 1. Every door must carry a fire rating -------------------------
    doors = ids.Specification(
        name="Doors carry a fire rating",
        ifcVersion=["IFC4"],
        identifier="REQ-DR-001",
        description="All doors must declare Pset_DoorCommon.FireRating.",
        instructions="Set the fire rating parameter before export.",
    )
    doors.applicability.append(ids.Entity(name="IFCDOOR"))
    doors.requirements.append(
        ids.Property(
            propertySet="Pset_DoorCommon",
            baseName="FireRating",
            dataType="IFCLABEL",
            cardinality="required",
            instructions="Required for fire-strategy review.",
        )
    )

    # --- 2. Every wall must declare whether it is external ---------------
    walls = ids.Specification(
        name="Walls declare IsExternal",
        ifcVersion=["IFC4"],
        identifier="REQ-WAL-001",
        description="All walls must declare Pset_WallCommon.IsExternal.",
    )
    walls.applicability.append(ids.Entity(name="IFCWALL"))
    walls.requirements.append(
        ids.Property(
            propertySet="Pset_WallCommon",
            baseName="IsExternal",
            dataType="IFCBOOLEAN",
            cardinality="required",
            instructions="Drives the thermal envelope take-off.",
        )
    )

    # --- 3. Every element must be named ----------------------------------
    naming = ids.Specification(
        name="Slabs are named",
        ifcVersion=["IFC4"],
        identifier="REQ-GEN-001",
        description="All slabs must carry a Name attribute.",
    )
    naming.applicability.append(ids.Entity(name="IFCSLAB"))
    naming.requirements.append(
        ids.Attribute(name="Name", cardinality="required")
    )

    # --- 4. Windows must declare a thermal transmittance -----------------
    windows = ids.Specification(
        name="Windows declare thermal transmittance",
        ifcVersion=["IFC4"],
        identifier="REQ-WIN-001",
        description="Windows must declare Pset_WindowCommon.ThermalTransmittance.",
        instructions="Required for the SBC energy compliance submission.",
    )
    windows.applicability.append(ids.Entity(name="IFCWINDOW"))
    windows.requirements.append(
        ids.Property(
            propertySet="Pset_WindowCommon",
            baseName="ThermalTransmittance",
            dataType="IFCTHERMALTRANSMITTANCEMEASURE",
            cardinality="required",
        )
    )

    for spec in (doors, walls, naming, windows):
        spec_set.specifications.append(spec)

    return spec_set


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "examples/project_requirements.ids"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    build().to_xml(out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

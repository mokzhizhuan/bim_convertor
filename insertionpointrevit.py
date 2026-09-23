# RevitPythonShell / pyRevit script (run inside Revit)
# Exports ElementId, Family, Type, XYZ (mm), Rotation (deg) for "Tile Setting Out Point" instances.

import csv, os, math
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilyInstance,
    LocationPoint,
    XYZ,
)

doc = __revit__.ActiveUIDocument.Document  # pyRevit / RPS
out_path = os.path.join(
    os.path.expanduser("~"), "Desktop", "Tile_Setting_Out_Points_3D.csv"
)


def ft_to_mm(x):
    return x * 304.8


def is_tile_point(fi):
    try:
        fam = fi.Symbol.Family.Name or ""
        typ = fi.Symbol.Name or ""
        n1 = fi.Name or ""
        key = "tile setting out point"
        s = f"{fam} {typ} {n1}".lower()
        return key in s
    except:
        return False


rows = []
elems = (
    FilteredElementCollector(doc)
    .OfClass(FamilyInstance)
    .WhereElementIsNotElementType()
    .ToElements()
)
for fi in elems:
    if not is_tile_point(fi):
        continue
    loc = fi.Location
    if isinstance(loc, LocationPoint):
        p = loc.Point  # model coordinates (internal feet)
        # Orientation (optional): facing dir gives you rotation
        try:
            facing = fi.FacingOrientation  # XYZ
            rot_rad = math.atan2(facing.Y, facing.X)
            rot_deg = math.degrees(rot_rad)
        except:
            rot_deg = 0.0

        rows.append(
            {
                "ElementId": int(fi.Id.IntegerValue),
                "Family": (
                    fi.Symbol.Family.Name if fi.Symbol and fi.Symbol.Family else ""
                ),
                "Type": fi.Symbol.Name if fi.Symbol else "",
                "X_mm": round(ft_to_mm(p.X), 3),
                "Y_mm": round(ft_to_mm(p.Y), 3),
                "Z_mm": round(ft_to_mm(p.Z), 3),
                "Rotation_deg": round(rot_deg, 3),
            }
        )
    else:
        # Non-point (e.g., curve) or annotation-only items won’t have 3D model points
        rows.append(
            {
                "ElementId": int(fi.Id.IntegerValue),
                "Family": (
                    fi.Symbol.Family.Name if fi.Symbol and fi.Symbol.Family else ""
                ),
                "Type": fi.Symbol.Name if fi.Symbol else "",
                "X_mm": "",
                "Y_mm": "",
                "Z_mm": "",
                "Rotation_deg": "",
            }
        )

with open(out_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "ElementId",
            "Family",
            "Type",
            "X_mm",
            "Y_mm",
            "Z_mm",
            "Rotation_deg",
        ],
    )
    w.writeheader()
    w.writerows(rows)

print("Wrote:", out_path)

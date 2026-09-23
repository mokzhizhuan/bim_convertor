import ifcopenshell
import numpy as np
import math

# --- Open IFC and find target object ---
ifc = ifcopenshell.open("SGHPH9A2_187ME3DCOM0C_PBU TYPE Dr-BD-R-FT1.ifc")
target_name = "Furn_Shower Curtain_CTT301A1:. 2:1372710"
target_obj = next((e for e in ifc.by_type("IfcElement") if target_name in e.Name), None)
if not target_obj:
    raise Exception("❌ Target object not found")

# --- Find the mapped extrusion solid ---
extruded = None
for rep in target_obj.Representation.Representations:
    for item in rep.Items:
        if item.is_a("IfcMappedItem"):
            mapped = item.MappingSource.MappedRepresentation
            for geom in mapped.Items:
                if geom.is_a("IfcExtrudedAreaSolid") and geom.SweptArea.is_a("IfcArbitraryClosedProfileDef"):
                    extruded = geom

if not extruded:
    raise Exception("❌ No extrusion found")

# --- Extract 2D profile points from IfcPolyline ---
profile = extruded.SweptArea
polyline = profile.OuterCurve
points_2d = [tuple(pt.Coordinates) for pt in polyline.Points]

# --- Extrude to 3D ---
height = extruded.Depth
points_3d = [(x, y, 0.0) for x, y in points_2d] + [(x, y, height) for x, y in points_2d]

# --- Apply transformation (placement) ---
placement = extruded.Position
location = placement.Location.Coordinates
ref_dir = placement.RefDirection.DirectionRatios if placement.RefDirection else (1, 0, 0)
axis = placement.Axis.DirectionRatios if placement.Axis else (0, 0, 1)

def local_to_world(pt, origin, x_dir, z_dir):
    y_dir = np.cross(z_dir, x_dir)
    matrix = np.array([x_dir, y_dir, z_dir]).T  # 3x3
    return tuple(np.dot(matrix, pt) + origin)

origin = np.array(location)
x_dir = np.array(ref_dir) / np.linalg.norm(ref_dir)
z_dir = np.array(axis) / np.linalg.norm(axis)

world_points = [local_to_world(np.array(p), origin, x_dir, z_dir) for p in points_3d]

# --- Optional: visualize with PyVista ---
try:
    import pyvista as pv
    cloud = pv.PolyData(np.array(world_points))
    cloud.plot(point_size=6)
except ImportError:
    print("🔹 PyVista not installed; skipping visualization")

# --- Done: output preview ---
print(f"✅ Extracted {len(world_points)} curtain vertices:")
for pt in world_points:
    print(f"{pt} ...")

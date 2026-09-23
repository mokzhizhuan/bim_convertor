import numpy as np
import pyvista as pv
import ifcopenshell
import ifcopenshell.geom
import methodifcfindings as ifc_findings
from ifcopenshell.util.placement import get_local_placement


# Load IFC file
ifc = ifcopenshell.open("TERRAHL2-FP-MB-T1am(JMB).ifc")
settings = ifcopenshell.geom.settings()
settings.set(settings.USE_WORLD_COORDS, True)

# Select the first wall
wall = ifc.by_type("IfcWall")[0]

# Get elements to check (embedded or placed in wall)
items = ifc.by_type("IfcBuildingElementProxy") + ifc.by_type("IfcDistributionElement")


# Utilities
def get_mesh(element):
    shape = ifcopenshell.geom.create_shape(settings, element)
    verts = np.array(shape.geometry.verts).reshape(-1, 3)
    faces = np.array(shape.geometry.faces).reshape(-1, 3)
    return pv.PolyData(verts, np.hstack([np.full((faces.shape[0], 1), 3), faces]))


def is_facing_into_wall(wall_matrix, obj_matrix, threshold_cos=-0.9):
    wall_z = wall_matrix[:3, 2]
    obj_z = obj_matrix[:3, 2]
    return np.dot(wall_z, obj_z) <= threshold_cos


def is_inside_bounds(wall_bounds, obj_bounds):
    return np.all(obj_bounds[0] >= wall_bounds[0]) and np.all(
        obj_bounds[1] <= wall_bounds[1]
    )


# Get wall info
wall_matrix = get_local_placement(wall.ObjectPlacement)
wall_mesh = get_mesh(wall)
wall_bounds = np.array(wall_mesh.bounds).reshape(3, 2).T

# Detect embedded items
embedded = []

for item in items:
    try:
        item_matrix = get_local_placement(item.ObjectPlacement)
        item_mesh = get_mesh(item)
        item_bounds = np.array(item_mesh.bounds).reshape(3, 2).T

        if is_facing_into_wall(wall_matrix, item_matrix) and is_inside_bounds(
            wall_bounds, item_bounds
        ):
            embedded.append((item.GlobalId, item.Name, item.is_a()))
    except:
        continue

print("Top embedded/inward-facing items:")
for gid, name, type_name in embedded[:10]:
    print(f"→ {type_name}: {name} (GlobalId: {gid})")

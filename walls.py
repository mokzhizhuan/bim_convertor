import ifcopenshell
import numpy as np
import pandas as pd
import re

# Load the IFC file
ifc_file = ifcopenshell.open("SGHPH9A2_187ME3DCOM0C_PBU TYPE Dr-BD-R-FT1.ifc")

# Extract walls
walls = ifc_file.by_type("IfcWallStandardCase")

# Pick one wall (first wall)
wall = walls[0]

# Get placement origin
placement = wall.ObjectPlacement
while hasattr(placement, "PlacementRelTo") and placement.PlacementRelTo:
    placement = placement.PlacementRelTo
origin = np.array(placement.RelativePlacement.Location.Coordinates)

# Get geometry dimensions
rep = wall.Representation
width, height = None, None
for item in rep.Representations:
    if item.RepresentationType == "SweptSolid":
        solid = item.Items[0]
        if solid.is_a("IfcExtrudedAreaSolid"):
            profile = solid.SweptArea
            if profile.is_a("IfcRectangleProfileDef"):
                width = profile.XDim  # along X
                print(f"Width: {width}")
                height = solid.Depth  # along Z (extrusion direction)

# Generate tiles on the wall face
search_name = "Basic Wall:BSS.300x600 MM - 20mm Finishes"

# Filter matching IfcWallStandardCase elements
matching_walls = [
    wall
    for wall in ifc_file.by_type("IfcWallStandardCase")
    if search_name.lower() in wall.Name.lower()
]


def get_tile_size_from_name(name):
    match = re.search(r"BSS\.(\d+)[xX](\d+)\s*MM", name)
    if match:
        width = int(match.group(1))
        height = int(match.group(2))
        return width, height
    return None, None


for wall in matching_walls:
    tile_width, tile_height = get_tile_size_from_name(wall.Name)

print(f"Tile width: {tile_width}, Tile height: {tile_height}")

tile_coords = []
for i in range(int(width // tile_height)):
    for j in range(int(height // tile_width) - 1):
        tile_x = origin[0] + tile_height + i * tile_height  # horizontal shift
        tile_z = tile_width + j * tile_width  # start from Z = 0, not origin[2]
        tile_coords.append((tile_x, tile_z))

# Save or print result
df = pd.DataFrame(tile_coords)
print(df)
df.to_excel("wall_tile_coordinates.xlsx", index=False)

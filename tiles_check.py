import ifcopenshell
import ifcopenshell.geom
import pandas as pd
import os
import numpy as np

# --- Configuration ---
IFC_FILE_PATH = "SGHPH9A2_187ME3DCOM0C_PBU TYPE Dr-BD-R-FT1.ifc"  # << Change this to your IFC file path
EXPECTED_TILES = {
    "600x600mm": (600, 600),
    "600x150mm": (600, 150),
    "450x450mm": (450, 450),
    "150x150mm": (150, 150),
    "700 x 1350mm": (700, 1350),
}

SCALE = 1000.0
OUTPUT_CSV = "tile_check_output.csv"

# --- IFC Setup ---
settings = ifcopenshell.geom.settings()
settings.set(settings.USE_WORLD_COORDS, True)

ifc_file = ifcopenshell.open(IFC_FILE_PATH)

for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
    for obj in rel.RelatedObjects:
        props = rel.RelatingPropertyDefinition
        if hasattr(props, "HasProperties"):
            for p in props.HasProperties:
                print(p)
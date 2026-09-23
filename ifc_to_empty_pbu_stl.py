#!/usr/bin/env python3
import sys, re
from pathlib import Path
import numpy as np
import meshio

try:
    import ifcopenshell
    import ifcopenshell.geom as geom
except Exception as e:
    print(f"[ERROR] ifcopenshell import failed: {e}")
    sys.exit(1)

# Exclude if Name/ObjectType contains these terms (case-insensitive)
EXCLUDE_RE = re.compile(r"(glass|box)", re.IGNORECASE)

def _exclude(prod) -> bool:
    name = getattr(prod, "Name", "") or ""
    objt = getattr(prod, "ObjectType", "") or ""
    return EXCLUDE_RE.search(name) or EXCLUDE_RE.search(objt)

def extract_mesh(model, types=("IfcWall","IfcWallStandardCase","IfcSlab")):
    prods = []
    for t in types:
        prods.extend(model.by_type(t))
    prods = [p for p in prods if not _exclude(p)]  # <- filter out glass/box

    settings = geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    try: settings.set(settings.USE_PYTHON_OPENCASCADE, True)
    except Exception: pass

    all_vertices, all_faces = [], []

    def add(verts, faces):
        base = len(all_vertices)
        all_vertices.extend(verts.reshape(-1,3).tolist())
        f = faces.reshape(-1,3) if faces.ndim==1 or faces.shape[-1]!=3 else faces
        all_faces.extend((f + base).tolist())

    processed = skipped = 0
    for p in prods:
        try:
            s = geom.create_shape(settings, p)
            g = s.geometry
            verts = np.array(g.verts, float)
            faces = np.array(g.faces, int)
            if verts.size==0 or faces.size==0:
                skipped += 1
                continue
            add(verts, faces)
            processed += 1
        except Exception as e:
            skipped += 1
            print(f"[WARN] Skip {getattr(p,'GlobalId','?')} {p.is_a()}: {e}")

    return np.array(all_vertices,float), np.array(all_faces,int), processed, skipped

def main():
    if len(sys.argv) < 3:
        print("Usage: python ifc_to_empty_pbu_stl.py input.ifc output.stl")
        sys.exit(2)

    in_ifc = Path(sys.argv[1]).resolve()
    out_stl = Path(sys.argv[2]).resolve()
    if not in_ifc.exists():
        print(f"[ERROR] IFC not found: {in_ifc}")
        sys.exit(3)

    model = ifcopenshell.open(str(in_ifc))
    V, F, processed, skipped = extract_mesh(model)
    print(f"[INFO] Processed: {processed}, Skipped: {skipped}")
    print(f"[INFO] Vertices: {len(V):,}, Faces: {len(F):,}")

    if len(V)==0 or len(F)==0:
        print("[ERROR] No geometry extracted (after filtering).")
        sys.exit(4)

    mesh = meshio.Mesh(points=V, cells=[('triangle', F)])
    out_stl.parent.mkdir(parents=True, exist_ok=True)
    meshio.write(out_stl, mesh, file_format="stl")
    print(f"[OK] Wrote STL: {out_stl}")

if __name__ == "__main__":
    main()

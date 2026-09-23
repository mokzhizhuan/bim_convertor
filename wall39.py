import ifcopenshell
import math
import numpy as np

IFC_PATH = "TERRAHL2-FP-MB-T1am(JMB).ifc"  # <- change me
ifc = ifcopenshell.open(IFC_PATH)

def get(id_):
    obj = ifc.by_id(id_)
    if obj is None:
        print(f"[WARN] #{id_} not found")
    return obj

def axis2placement3d_to_matrix(a2p):
    L = np.array(a2p.Location.Coordinates, dtype=float)
    z = np.array(a2p.Axis.DirectionRatios if a2p.Axis else (0.0, 0.0, 1.0), dtype=float)
    x = np.array(a2p.RefDirection.DirectionRatios if a2p.RefDirection else (1.0, 0.0, 0.0), dtype=float)
    z = z / np.linalg.norm(z)
    x = x - np.dot(x, z) * z
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    M = np.eye(4)
    M[0:3, 0] = x
    M[0:3, 1] = y
    M[0:3, 2] = z
    M[0:3, 3] = L
    return M

def local_placement_to_world(lp):
    M = axis2placement3d_to_matrix(lp.RelativePlacement)
    return local_placement_to_world(lp.PlacementRelTo) @ M if lp.PlacementRelTo else M

def pvec(name, v):
    print(f"{name}: ({v[0]:.6f}, {v[1]:.6f}, {v[2]:.6f})")

def pmatrix(M):
    for r in range(4):
        print("  " + " ".join(f"{M[r,c]: .6f}" for c in range(4)))

# --- #28777 IFCCARTESIANPOINT (3D)
pt3 = get(28777)
if pt3:
    x, y, z = pt3.Coordinates
    print(f"#28777 IfcCartesianPoint -> ({x:.6f}, {y:.6f}, {z:.6f})")

# --- #28778 IFCAXIS2PLACEMENT3D
a2p = get(28778)
if a2p:
    loc = a2p.Location.Coordinates
    axis = a2p.Axis.DirectionRatios if a2p.Axis else (0.0, 0.0, 1.0)
    refd = a2p.RefDirection.DirectionRatios if a2p.RefDirection else (1.0, 0.0, 0.0)
    print("\n#28778 IfcAxis2Placement3D")
    pvec("  Location", loc + (0,)) if len(loc)==2 else pvec("  Location", loc)
    pvec("  Z (Axis)", axis + (0,)) if len(axis)==2 else pvec("  Z (Axis)", axis)
    pvec("  X (RefDirection)", refd + (0,)) if len(refd)==2 else pvec("  X (RefDirection)", refd)

# --- #28779 IFCLOCALPLACEMENT -> World transform
lp = get(28779)
if lp:
    print("\n#28779 IfcLocalPlacement -> World transform (4x4)")
    M = local_placement_to_world(lp)
    pmatrix(M)
    T = M[0:3,3]
    xw, yw, zw = M[0:3,0], M[0:3,1], M[0:3,2]
    pvec("  World Translation", T)
    pvec("  World X axis", xw)
    pvec("  World Y axis", yw)
    pvec("  World Z axis", zw)

# --- #28780 IFCCARTESIANPOINT (2D)
pt2 = get(28780)
if pt2:
    u, v = pt2.Coordinates
    print(f"\n#28780 IfcCartesianPoint (2D) -> ({u:.6f}, {v:.6f})")

# --- #28781 IFCPOLYLINE and length
pline = get(28781)
if pline:
    pts = pline.Points
    (x1, y1) = pts[0].Coordinates
    (x2, y2) = pts[1].Coordinates
    L = math.hypot(x2 - x1, y2 - y1)
    print("\n#28781 IfcPolyline (2 points)")
    print(f"  P0: ({x1:.6f}, {y1:.6f})")
    print(f"  P1: ({x2:.6f}, {y2:.6f})")
    print(f"  Length: {L:.6f}")

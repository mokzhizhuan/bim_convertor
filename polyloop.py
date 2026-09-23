# Requires: ifcopenshell (pip install ifcopenshell)
# File: find_600x600_polyloops.py

import math
import ifcopenshell

IFC_PATH = r"TERRAHL2-FP-MB-T1am(JMB).ifc"  # <-- change if needed
TOL_LEN_MM = 5.0  # +/- mm tolerance for each edge
TOL_ANG_DEG = 3.0  # orthogonality tolerance
TARGET_MM = 131


def to_vec(a, b):
    return (b[0] - a[0], b[1] - a[1], b[2] - a[2])


def length(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def angle_deg(a, b):
    la, lb = length(a), length(b)
    if la == 0 or lb == 0:
        return 0.0
    c = max(-1.0, min(1.0, dot(a, b) / (la * lb)))
    return math.degrees(math.acos(c))


def get_length_scale_to_mm(ifc):
    """Return multiplier to convert model length units to mm."""
    ua = ifc.by_type("IfcUnitAssignment")
    if not ua:
        # IFC2x3 default is mm; IFC4 often explicit. Fall back to mm.
        return 1.0
    for u in ua[0].Units:
        # IfcSIUnit for length (METRE with optional Prefix)
        if u.is_a("IfcSIUnit") and u.UnitType == "LENGTHUNIT":
            # Base is METRE
            prefix = getattr(u, "Prefix", None)
            # Convert metres to mm then apply prefix
            # mm per metre = 1000
            m_to_mm = 1000.0
            # If prefix is MILLI, the model unit is millimetre => 1 mm per unit
            if prefix == "MILLI":
                return 1.0
            elif prefix == "CENTI":
                # centimetre -> 10 mm per unit
                return 10.0
            elif prefix in (None, "NONE"):
                # metre -> 1000 mm per unit
                return m_to_mm
            elif prefix == "DECI":
                return 100.0
            elif prefix == "DECA":
                return 10000.0
            elif prefix == "HECTO":
                return 100000.0
            elif prefix == "KILO":
                return 1000000.0
        # IfcConversionBasedUnit (rare for length)
        if u.is_a("IfcConversionBasedUnit") and u.UnitType == "LENGTHUNIT":
            # Try to read conversion to SI metre and then to mm
            # Some files store: ConversionFactor.ValueComponent = IfcMeasureWithUnit(IfcSIUnit(METRE), factor)
            # If not available, be conservative and assume mm
            try:
                cf = u.ConversionFactor
                si = cf.UnitComponent
                if (
                    si.is_a("IfcSIUnit")
                    and si.UnitType == "LENGTHUNIT"
                    and si.Name == "METRE"
                ):
                    factor_to_metres = float(cf.ValueComponent.wrappedValue)
                    return factor_to_metres * 1000.0
            except Exception:
                pass
    return 1.0  # fallback


def is_square_600x600_mm(points, to_mm):
    """points: list of (x,y,z) in model units. Check 4 edges ~600mm, angles ~90°."""
    if len(points) != 4:
        return False

    # Ensure we close the loop
    P = points + points[:1]

    # Edge vectors and lengths (to mm)
    vecs = [to_vec(P[i], P[i + 1]) for i in range(4)]
    lens_mm = [length(v) * to_mm for v in vecs]

    # Each length ~ 600 ± tol
    for L in lens_mm:
        if abs(L - TARGET_MM) > TOL_LEN_MM:
            return False

    # Right angles between consecutive edges
    for i in range(4):
        ang = angle_deg(vecs[i], vecs[(i + 1) % 4])
        if abs(ang - 90.0) > TOL_ANG_DEG:
            return False

    return True


def xyz(pt):
    # IfcCartesianPoint.Coordinates may be 2D or 3D; pad to 3D
    coords = list(pt.Coordinates)
    if len(coords) == 2:
        coords.append(0.0)
    return (float(coords[0]), float(coords[1]), float(coords[2]))


def main():
    ifc = ifcopenshell.open(IFC_PATH)
    to_mm = get_length_scale_to_mm(ifc)

    # Pre-index for context: PolyLoop -> FaceBound -> Face -> ClosedShell -> BRep
    face_bounds = ifc.by_type("IfcFaceBound") + ifc.by_type("IfcFaceOuterBound")
    polyloop_to_facebound = {}
    for fb in face_bounds:
        try:
            if fb.Bound:  # IfcFaceBound has attribute "Bound"
                polyloop_to_facebound.setdefault(fb.Bound.id(), []).append(fb)
        except Exception:
            pass

    faces = ifc.by_type("IfcFace")
    face_to_shell = {}
    for shell in ifc.by_type("IfcClosedShell"):
        for f in getattr(shell, "CfsFaces", []) or []:
            face_to_shell[f.id()] = shell

    shell_to_brep = {}
    for brep in ifc.by_type("IfcFacetedBrep") + ifc.by_type("IfcManifoldSolidBrep"):
        if getattr(brep, "Outer", None):
            shell_to_brep[brep.Outer.id()] = brep

    results = []
    for pl in ifc.by_type("IfcPolyLoop"):
        pts = [xyz(p) for p in (pl.Polygon or [])]
        if len(pts) != 4:
            continue
        if not is_square_600x600_mm(pts, to_mm):
            continue

        # Build a small context chain
        fb_ids = [fb.id() for fb in polyloop_to_facebound.get(pl.id(), [])]
        face_ids = []
        shell_ids = []
        brep_ids = []

        for fb in polyloop_to_facebound.get(pl.id(), []) or []:
            # fb belongs to one or more faces (Faces include fb in FaceBounds)
            # We'll search faces that reference this fb
            for f in faces:
                try:
                    if fb in (f.Bounds or []):
                        face_ids.append(f.id())
                        sh = face_to_shell.get(f.id())
                        if sh:
                            shell_ids.append(sh.id())
                            br = shell_to_brep.get(sh.id())
                            if br:
                                brep_ids.append(br.id())
                except Exception:
                    pass

        results.append(
            {
                "polyloop_id": pl.id(),
                "points_mm": [[c * to_mm for c in p] for p in pts],
                "facebound_ids": sorted(set(fb_ids)),
                "face_ids": sorted(set(face_ids)),
                "shell_ids": sorted(set(shell_ids)),
                "brep_ids": sorted(set(brep_ids)),
            }
        )

    # Print a compact report
    print(f"Found {len(results)} PolyLoops that look like 600x600 squares:")
    for r in results:
        print(
            f"- IfcPolyLoop #{r['polyloop_id']}  faces={r['face_ids']}  breps={r['brep_ids']}"
        )
        for i, p in enumerate(r["points_mm"], 1):
            print(f"    P{i}: ({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f}) mm")


if __name__ == "__main__":
    main()

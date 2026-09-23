import ifcopenshell
import ifcopenshell.util.element as uel
import ifcopenshell.util.placement as upl
import math

IFC_PATH = r"TERRAHL2-FP-MB-T1am(JMB).ifc"


def cartesian_coords(pt):
    # Works for 2D or 3D IfcCartesianPoint
    coords = [float(c) for c in pt.Coordinates]
    if len(coords) == 2:
        coords.append(0.0)
    return coords[:3]


def apply_transform(M, p):
    # M is 4x3 from ifcopenshell (x,y,z,origin columns), p is (x,y,z) in local
    # Transform: world = origin + xaxis*p.x + yaxis*p.y + zaxis*p.z
    xaxis = M[0]
    yaxis = M[1]
    zaxis = M[2]
    origin = M[3]
    return [
        origin[0] + xaxis[0] * p[0] + yaxis[0] * p[1] + zaxis[0] * p[2],
        origin[1] + xaxis[1] * p[0] + yaxis[1] * p[1] + zaxis[1] * p[2],
        origin[2] + xaxis[2] * p[0] + yaxis[2] * p[1] + zaxis[2] * p[2],
    ]


def length3(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def is_tile_like(covering):
    name = (covering.Name or "").lower()
    ptype = covering.PredefinedType.name if covering.PredefinedType else None
    return ("tile" in name) or (ptype == "FINISHING")


def get_axis_polyline_points2d(repr_item):
    # Return first two 2D points from an IfcPolyline inside a Curve2D/GeometricCurveSet
    items = getattr(repr_item, "Items", None) or []
    for it in items:
        if it.is_a("IfcPolyline"):
            pts = [cartesian_coords(p) for p in it.Points]
            if len(pts) >= 2:
                # Take XY; (z is 0 in 2D)
                return pts[0], pts[1]
        elif it.is_a("IfcGeometricCurveSet"):
            for sub in it.Elements:
                if sub.is_a("IfcPolyline") and len(sub.Points) >= 2:
                    pts = [cartesian_coords(p) for p in sub.Points]
                    return pts[0], pts[1]
    return None


def find_axis_curve2d(covering):
    pds = covering.Representation
    if not pds:
        return None
    for rep in pds.Representations or []:
        if rep.RepresentationIdentifier == "Axis" and rep.RepresentationType in (
            "Curve2D",
            "GeometricCurveSet",
        ):
            return rep
    return None


def world_matrix_for_product(prod):
    # 4x3 matrix (x, y, z, origin) as rows
    return upl.get_local_placement(prod.ObjectPlacement)


def format_pt(p):
    return f"({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f})"


# --- Fallback: when no Axis/Curve2D is available but style says TILES ---
def style_name_contains_tiles(prod):
    # Scan styled items connected to this product for a SurfaceStyle with 'TILE'
    # This is conservative and may miss some cases; good enough as a fallback.
    styled = prod.Representation
    if not styled:
        return False
    reps = styled.Representations or []
    for rep in reps:
        for it in rep.Items or []:
            # IfcStyledItem may be attached at face-level, but often present on items
            si = getattr(it, "StyledByItem", None)
            if si:
                if not isinstance(si, (list, tuple)):
                    si = [si]
                for s in si:
                    for psa in s.Styles or []:
                        if psa.is_a("IfcPresentationStyleAssignment"):
                            for sty in psa.Styles:
                                if sty.is_a("IfcSurfaceStyle"):
                                    name = (sty.Name or "").lower()
                                    if "tile" in name:
                                        return True
    return False


def longest_edge_heuristic(prod):
    """
    If you have ifcopenshell.geom available locally, replace this with a real
    topology query and return the longest straight edge in world coords.
    For a lightweight heuristic without geom:
    - Use the product’s bounding box (from util.element.calculate_bbox if available).
    - Use the wall/floor local X or Y span as a 'start line'.
    """
    try:
        bbox = uel.calculate_bbox(prod)
        # Use the longest dimension on the base plane as a start line
        dims = [
            (abs(bbox["x"]["max"] - bbox["x"]["min"]), "x"),
            (abs(bbox["y"]["max"] - bbox["y"]["min"]), "y"),
        ]
        dims.sort(reverse=True)
        axis = dims[0][1]
        z = bbox["z"]["min"]
        if axis == "x":
            p0 = [bbox["x"]["min"], bbox["y"]["min"], z]
            p1 = [bbox["x"]["max"], bbox["y"]["min"], z]
        else:
            p0 = [bbox["x"]["min"], bbox["y"]["min"], z]
            p1 = [bbox["x"]["min"], bbox["y"]["max"], z]
        return p0, p1
    except Exception:
        return None


def main():
    ifc = ifcopenshell.open(IFC_PATH)

    results = []
    for cov in ifc.by_type("IfcCovering"):
        if not is_tile_like(cov) and not style_name_contains_tiles(cov):
            continue

        axis_rep = find_axis_curve2d(cov)
        M = world_matrix_for_product(cov)

        used_fallback = False
        if axis_rep:
            pts2d = get_axis_polyline_points2d(axis_rep)
            if pts2d:
                p0_local = pts2d[0]  # (x,y,0) in local 2D
                p1_local = pts2d[1]
                p0_world = apply_transform(M, p0_local)
                p1_world = apply_transform(M, p1_local)
            else:
                used_fallback = True
        else:
            used_fallback = True

        if used_fallback:
            pair = longest_edge_heuristic(cov)
            if not pair:
                continue
            p0_world, p1_world = pair

        results.append(
            {
                "id": cov.id(),
                "name": cov.Name,
                "start_point_world": p0_world,
                "end_point_world": p1_world,
                "start_line_length": length3(p0_world, p1_world),
                "source": "Axis/Curve2D" if not used_fallback else "Fallback-Heuristic",
            }
        )

    # Pretty print
    for r in results:
        print(f"Covering #{r['id']}  {r['name']}")
        print(f"  start: {format_pt(r['start_point_world'])}")
        print(f"  end  : {format_pt(r['end_point_world'])}")
        print(f"  length: {r['start_line_length']:.3f} (source: {r['source']})")
        print()


if __name__ == "__main__":
    main()

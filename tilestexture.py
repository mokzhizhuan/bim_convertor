import ifcopenshell

ifc = ifcopenshell.open("TERRAHL2-FP-MB-T1am(JMB).ifc")

def rgb01_to_255(v): return int(round(v * 255))

def surface_styles_from_styled_item(styled_item):
    for psa in getattr(styled_item, "Styles", []) or []:
        for st in getattr(psa, "Styles", []) or []:
            if st.is_a("IfcSurfaceStyle") and "tiles" in (st.Name or "").lower():
                for comp in getattr(st, "Styles", []) or []:
                    if comp.is_a("IfcSurfaceStyleRendering"):
                        col = comp.SurfaceColour
                        return st.Name, tuple(rgb01_to_255(x) for x in (col.Red, col.Green, col.Blue))
    return None

def brep_points_from_item(item):
    if not item or not item.is_a("IfcFacetedBrep"):
        return None
    shell = item.Outer
    faces = []
    for face in shell.CfsFaces:
        loops = []
        bounds = []
        if getattr(face, "OuterBound", None):
            bounds.append(face.OuterBound)
        if getattr(face, "Bounds", None):
            bounds.extend([b for b in face.Bounds if b is not getattr(face, "OuterBound", None)])
        for b in bounds:
            loop = b.Bound
            pts = []
            for p in loop.Polygon:
                coords = p.Coordinates
                x = float(coords[0])
                y = float(coords[1]) if len(coords) > 1 else 0.0
                z = float(coords[2]) if len(coords) > 2 else 0.0
                pts.append((x, y, z))
            loops.append(pts)
        faces.append(loops)
    return faces

for si in ifc.by_type("IfcStyledItem"):
    style_info = surface_styles_from_styled_item(si)
    if style_info:
        name, rgb = style_info
        points = brep_points_from_item(getattr(si, "Item", None))
        print(f"StyledItem #{si.id()}  Style={name}  RGB={rgb}")
        if points:
            print(f"  Faces: {len(points)}")
            print(f"  First face points: {points[0][0] if points[0] else []}")

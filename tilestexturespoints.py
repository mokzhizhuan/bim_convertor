import ifcopenshell
import ifcopenshell.geom as geom

IFC_PATH = "TERRAHL2-FP-MB-T1am(JMB).ifc"
ifc = ifcopenshell.open(IFC_PATH)


def rgb01_to_255(v):
    return int(round(float(v) * 255))


def _extract_rgb_from_rendering(r):
    """
    Try SurfaceColour first, then DiffuseColour (which may itself be a colour or ratio).
    Returns (r,g,b) in 0-255 if found, else None.
    """
    def rgb_from_obj(obj):
        if not obj:
            return None
        # IfcColourRgb
        if hasattr(obj, "Red") and hasattr(obj, "Green") and hasattr(obj, "Blue"):
            return tuple(rgb01_to_255(x) for x in (obj.Red, obj.Green, obj.Blue))
        # If it's a SELECT that unwraps to a colour, try common attr 'Name' or nested .Value
        # (Some files put a scalar or reference here; we ignore non-RGB cases.)
        return None

    # SurfaceColour is the cleanest
    col = getattr(r, "SurfaceColour", None)
    rgb = rgb_from_obj(col)
    if rgb:
        return rgb

    # DiffuseColour can be colour or scalar. Only accept when it yields RGB.
    diff = getattr(r, "DiffuseColour", None)
    rgb = rgb_from_obj(diff)
    return rgb


def surface_style_from_styled_item(styled_item):
    """
    Return (name, rgb_tuple) for a 'tiles' IfcSurfaceStyle on this styled_item, else None.
    Handles both direct IfcSurfaceStyle and IfcPresentationStyleAssignment.
    """
    styles = getattr(styled_item, "Styles", []) or []

    def visit_surface_style(s):
        name = (getattr(s, "Name", "") or "")
        if "tiles" not in name.lower():
            return None
        for comp in getattr(s, "Styles", []) or []:
            if comp.is_a("IfcSurfaceStyleRendering"):
                rgb = _extract_rgb_from_rendering(comp)
                if rgb:
                    return name, rgb
        # No rendering component with color; still return name with a neutral RGB if you want
        return (name, (127, 127, 127))

    for s in styles:
        if s.is_a("IfcPresentationStyleAssignment"):
            for st in getattr(s, "Styles", []) or []:
                if st.is_a("IfcSurfaceStyle"):
                    got = visit_surface_style(st)
                    if got:
                        return got
        elif s.is_a("IfcSurfaceStyle"):
            got = visit_surface_style(s)
            if got:
                return got

    return None


def all_points_from_brep(item, eps=1e-9):
    """
    Extract ALL unique Cartesian points from a faceted BRep.
    Deduplicate with an epsilon to avoid float noise.
    """

    seen = set()
    out = []
    shell = getattr(item, "Outer", None)
    if not shell:
        return out

    for face in getattr(shell, "CfsFaces", []) or []:
        for fb in getattr(face, "Bounds", []) or []:
            loop = getattr(fb, "Bound", None)
            if not loop or not loop.is_a("IfcPolyLoop"):
                continue
            for cp in getattr(loop, "Polygon", []) or []:
                coords = getattr(cp, "Coordinates", [])
                # Pad to 3D if needed
                x = float(coords[0]) if len(coords) > 0 else 0.0
                y = float(coords[1]) if len(coords) > 1 else 0.0
                z = float(coords[2]) if len(coords) > 2 else 0.0
                out.append((x, y, z))
    return out


def all_points_from_item_with_engine(elem):
    """
    Generic fallback: use geometry engine and return verts in WORLD coords.
    """
    try:
        settings = geom.settings()
        # Old API: settings.set("USE_WORLD_COORDS", True)
        # Newer ifcopenshell: attribute assignment also works:
        try:
            settings.USE_WORLD_COORDS = True
        except AttributeError:
            settings.set("USE_WORLD_COORDS", True)
        shape = geom.create_shape(settings, elem)
        verts = shape.geometry.verts  # flat list [x0,y0,z0, x1,y1,z1, ...]
        return [(float(verts[i]), float(verts[i + 1]), float(verts[i + 2]))
                for i in range(0, len(verts), 3)]
    except Exception:
        return []


# ---- main ----
for si in ifc.by_type("IfcStyledItem"):
    style_info = surface_style_from_styled_item(si)
    if not style_info:
        continue
    name, rgb = style_info
    item = getattr(si, "Item", None)
    if not item:
        continue

    # Prefer explicit BRep walk; else use engine fallback (handles MappedItems, SweptSolids, etc.)
    if item.is_a("IfcFacetedBrep"):
        points = all_points_from_brep(item)
    else:
        points = all_points_from_item_with_engine(item)

    print(f"StyledItem #{si.id()}  Style={name}  RGB={rgb}")
    print(f"  Total points: {len(points)}")
    if points:
        print(f"  Points {points}")

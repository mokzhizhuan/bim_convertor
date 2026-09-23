import os, math, argparse
import numpy as np
import ifcopenshell
import ifcopenshell.util.element
from math import isclose

SCALE = 1000.0


def validate_file(path, ext):
    if not path.lower().endswith(ext) or not os.path.exists(path):
        raise argparse.ArgumentTypeError(f"Invalid or missing file: {path}")
    return path



def get_vertices(obj):
    if obj.Representation:
        settings = ifcopenshell.geom.settings()
        shape = ifcopenshell.geom.create_shape(settings, obj)
        verts = shape.geometry.verts
        grouped = np.array(
            [[verts[i], verts[i + 1], verts[i + 2]] for i in range(0, len(verts), 3)]
        )
        return (grouped * SCALE).astype(int)
    

def get_posxyz(obj):
    if obj.ObjectPlacement and obj.ObjectPlacement.RelativePlacement:
        placement = obj.ObjectPlacement.RelativePlacement
        loc = getattr(placement, "Location", None)
        ref_dir = getattr(placement, "RefDirection", None)
        origin = tuple(loc.Coordinates) if loc else None
        direction = tuple(ref_dir.DirectionRatios) if ref_dir else (1.0, 0.0, 0.0)
        return origin, direction


def classify_direction(direction_vector):
    dx, dy, dz = direction_vector
    if abs(dx) == 1.0 and dy == 0.0:
        return ("X", "+X") if dx > 0 else ("X", "-X")
    elif abs(dy) == 1.0 and dx == 0.0:
        return ("Y", "+Y") if dy > 0 else ("Y", "-Y")
    elif abs(dz) == 1.0 and dx == 0.0 and dy == 0.0:
        return ("Z", "")
    return ("Unknown", "")


def process_elements(elements, name_filter):
    data = []
    for obj in elements:
        name = getattr(obj, "Name", "") or ""
        ptype = (getattr(obj, "PredefinedType", "") or "").lower()
        area = get_area(obj)
        if name_filter in name.lower():
            origin, dir = get_posxyz(obj)
            if obj.is_a("IfcSlab"):
                if ptype == "notdefined":
                    continue
                origin = get_floorpos(obj)
            elif (
                (obj.is_a("IfcFurnishingElement") and "bin" not in name)
                or (obj.is_a("IfcBuildingElementProxy") and "mirror" not in name)
                or (obj.is_a("IfcFlowTerminal") and "floor" not in name)
            ):
                origin = change_z(origin, obj)
            if is_origin_none_or_zero(origin) == True:
                origin, dir  = get_posxyz(obj)
            axis, facing_axis = classify_direction(dir)
            data.append(
                {
                    "name": name,
                    "type": obj.is_a(),
                    "x": round(origin[0]),
                    "y": round(origin[1]),
                    "z": round(origin[2]),
                    "axis": axis,
                    "facingaxis": facing_axis,
                    "area": area,
                    "vertices": get_vertices(obj),
                }
            )
    return data

def _as_xyz(origin):
    if origin is None:
        return None
    if isinstance(origin, (tuple, list, np.ndarray)) and len(origin) == 3:
        return float(origin[0]), float(origin[1]), float(origin[2])
    if isinstance(origin, dict):
        for keys in (("x","y","z"), ("X","Y","Z")):
            if all(k in origin for k in keys):
                return float(origin[keys[0]]), float(origin[keys[1]]), float(origin[keys[2]])
    for keys in (("x","y","z"), ("X","Y","Z")):
        if all(hasattr(origin, k) for k in keys):
            return float(getattr(origin, keys[0])), float(getattr(origin, keys[1])), float(getattr(origin, keys[2]))
    return None

def is_origin_none_or_zero(origin, tol=0.0):
    xyz = _as_xyz(origin)
    if xyz is None:
        return True  
    x, y, z = xyz
    return isclose(x, 0.0, abs_tol=tol) and isclose(y, 0.0, abs_tol=tol) and isclose(z, 0.0, abs_tol=tol)


def change_z(origin, obj):
    if len(origin) == 3 and round(origin[2]) <= 0.0:
        placement = obj.ObjectPlacement
        while hasattr(placement, "PlacementRelTo") and placement.PlacementRelTo:
            placement = placement.PlacementRelTo
        shape = obj.Representation
        for item in shape.Representations:
            for mapped in item.Items:
                if mapped.is_a("IfcMappedItem"):
                    mapping_source = mapped.MappingSource
                    for subitem in mapping_source.MappedRepresentation.Items:
                        if subitem.is_a() in {
                            "IfcExtrudedAreaSolid",
                            "IfcFacetedBrep",
                            "IfcFaceBasedSurfaceModel",
                        }:
                            return set_origin_z(origin, extract_z(subitem), subitem)
    return origin


def set_origin_z(origin, new_z, shape_item):
    if round(origin[2]) < 0.0 and shape_item.is_a("IfcExtrudedAreaSolid"):
        point = (origin[0], origin[1], origin[2] + new_z)
    else:
        point = (origin[0], origin[1], new_z)
    return point


def extract_z(shape_item):
    if shape_item.is_a("IfcExtrudedAreaSolid"):
        return shape_item.Position.Location.Coordinates[2]
    if shape_item.is_a("IfcFacetedBrep"):
        for face in shape_item.Outer.CfsFaces:
            all_z = collect_bounds(face.Bounds)
    if shape_item.is_a("IfcFaceBasedSurfaceModel"):
        for connected in shape_item.FbsmFaces:
            for face in connected.CfsFaces:
                all_z = collect_bounds(face.Bounds)
    return min(all_z, default=None)


def collect_bounds  (bounds):
    all_z = []
    for b in bounds:
        for pt in b.Bound.Polygon:
            all_z.append(pt.Coordinates[2])
    return all_z


def get_area(obj):

    def iter_items(rep):
        for r in (getattr(rep, "Representations", None) or []):
            for it in (getattr(r, "Items", None) or []):
                yield it

    def find_extruded(item):
        if item.is_a("IfcExtrudedAreaSolid") or item.is_a("IfcExtrudedAreaSolidTapered"):
            return item
        if item.is_a("IfcSweptAreaSolid"):
            return item
        if item.is_a("IfcBooleanResult") or item.is_a("IfcBooleanClippingResult"):
            for op in (item.FirstOperand, item.SecondOperand):
                es = find_extruded(op)
                if es:
                    return es
        if item.is_a("IfcMappedItem"):
            src = getattr(item, "MappingSource", None)
            rep = getattr(src, "MappedRepresentation", None) if src else None
            if rep:
                for sub in (rep.Items or []):
                    es = find_extruded(sub)
                    if es:
                        return es
        return None

    def profile_dims(p):
        if not p:
            return 0.0, 0.0
        t = p.is_a()
        if t == "IfcRectangleProfileDef":
            return float(p.XDim or 0), float(p.YDim or 0)
        if t == "IfcCircleProfileDef":
            d = 2.0 * float(p.Radius or 0); return d, d
        if t == "IfcEllipseProfileDef":
            return 2.0 * float(p.SemiAxis1 or 0), 2.0 * float(p.SemiAxis2 or 0)
        if t in ("IfcArbitraryClosedProfileDef", "IfcArbitraryProfileDefWithVoids"):
            crv = getattr(p, "OuterCurve", None)
            if crv and crv.is_a("IfcPolyline"):
                xs = [float(pt.Coordinates[0]) for pt in crv.Points]
                ys = [float(pt.Coordinates[1]) for pt in crv.Points]
                return (max(xs) - min(xs), max(ys) - min(ys))
        return 0.0, 0.0

    rep = getattr(obj, "Representation", None)
    if not rep:
        return (0, 0, 0)

    w = h = d = 0.0
    for it in iter_items(rep):
        es = find_extruded(it)
        if es:
            d = float(getattr(es, "Depth", 0.0) or 0.0)
            w, h = profile_dims(getattr(es, "SweptArea", None))
            break

    return (round(w), round(h), round(d))



def _pos_from_local_placement(plc):
    while plc and plc.is_a("IfcLocalPlacement"):
        rel = plc.RelativePlacement
        if rel and getattr(rel, "Location", None):
            return tuple(rel.Location.Coordinates)
        plc = plc.PlacementRelTo
    return None

def get_floorpos(obj):
    rep = getattr(obj, "Representation", None)
    if rep:
        for r in rep.Representations or []:
            for item in r.Items or []:
                p = _pos_from_geom(item)
                if p is not None:
                    return p
    p = _pos_from_local_placement(getattr(obj, "ObjectPlacement", None))
    if p is not None:
        return p
    return (0.0, 0.0, 0.0)

def _pos_from_geom(g):
    if g.is_a("IfcSweptAreaSolid") or g.is_a("IfcExtrudedAreaSolid"):
        return tuple(g.Position.Location.Coordinates)
    if g.is_a("IfcBooleanResult"):
        for op in (g.FirstOperand, g.SecondOperand):
            p = _pos_from_geom(op)
            if p is not None:
                return p
    if g.is_a("IfcMappedItem"):
        src = getattr(g, "MappingSource", None)
        if src and getattr(src, "MappingOrigin", None):
            return tuple(src.MappingOrigin.Location.Coordinates)
    return None


def find_closest_wall(current, pool):
    cx, cy = float(current["x"]), float(current["y"])
    return min(
        (
            (w, math.hypot(w["x"] - cx, w["y"] - cy))
            for w in pool
            if w["name"] != current["name"]
        ),
        key=lambda x: x[1],
        default=(None, float("inf")),
    )


def find_closest_wall_rotation(current, pool):
    cx, cy = float(current["x"]), float(current["y"])
    return min(
        (
            (inner, math.hypot(inner["x"] - cx, inner["y"] - cy))
            for wrapper in pool
            for inner in wrapper.values()   # <--- unpack inner dict
            if inner["name"] != current["name"] and inner["axis"] == current["axis"]
        ),
        key=lambda x: x[1],
        default=(None, float("inf")),
    )


def compute_area(area_tuple):
    x, y = 0, 0
    if area_tuple and len(area_tuple) >= 2:
        x, y = area_tuple[0], area_tuple[1]
    return x * y


def extract_storeys(ifc_file):
    storeys = []
    for storey in ifc_file.by_type("IfcBuildingStorey"):
        name, elevation = storey.Name or "Unnamed", storey.Elevation
        if any(k in name.upper() for k in ["CEILING"]):
            storeys.append({"name": name, "elevation": elevation})
    return storeys


def log_info(message):
    with open("log.txt", "a") as log_file:
        log_file.write(message + "\n")


def swap_first_two(a):
    if len(a) > 1:
        a[:2] = a[:2][::-1]


def swap_last_two(a):
    if len(a) > 1:
        a[-2:] = a[-2:][::-1]

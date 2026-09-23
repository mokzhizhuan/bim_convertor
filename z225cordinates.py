# Diagnose why 0 hits: inspect units and global Z ranges for the IFC
import ifcopenshell, ifcopenshell.geom as geom
from collections import Counter, defaultdict
import math, json, statistics as stats, itertools

IFC_PATH = "TERRAHL2-FP-MB-T1am(JMB).ifc"

def get_length_unit_scale(ifc):
    proj = ifc.by_type("IfcProject")
    if not proj:
        return 1.0, "UNKNOWN"
    proj = proj[0]
    uctx = getattr(proj, "UnitsInContext", None)
    if not uctx or not getattr(uctx, "Units", None):
        return 1.0, "UNKNOWN"
    for u in uctx.Units:
        # IfcSIUnit or IfcConversionBasedUnit
        if u.is_a("IfcSIUnit") and getattr(u, "UnitType", None) == "LENGTHUNIT":
            # SI base unit is metre, with optional prefixes (milli, etc.)
            prefix = getattr(u, "Prefix", None)
            if prefix == "MILLI":
                return 0.001, "millimetre (mm)"
            elif prefix == "CENTI":
                return 0.01, "centimetre (cm)"
            elif prefix == "DECI":
                return 0.1, "decimetre (dm)"
            else:
                return 1.0, "metre (m)"
        if u.is_a("IfcConversionBasedUnit") and getattr(u, "UnitType", None) == "LENGTHUNIT":
            # Best attempt: read conversion factor to SI (metre)
            cf = getattr(u, "ConversionFactor", None)
            if cf and hasattr(cf, "ValueComponent"):
                try:
                    si_per_unit = float(cf.ValueComponent.wrappedValue)  # metres per 'unit'
                    return si_per_unit, f"conversion-based (1 unit = {si_per_unit} m)"
                except Exception:
                    pass
    return 1.0, "UNKNOWN"

ifc = ifcopenshell.open(IFC_PATH)
scale_to_m, unit_desc = get_length_unit_scale(ifc)

settings = geom.settings()
settings.set(settings.USE_WORLD_COORDS, True)

# Gather Z stats over all IfcElement with geometry
zs_all = []
elem_bounds = []
errors = 0
total = 0

def verts_of(elem):
    shape = geom.create_shape(settings, elem)
    verts = shape.geometry.verts
    return [verts[i+2] for i in range(0, len(verts), 3)]

for elem in ifc.by_type("IfcElement"):
    if not getattr(elem, "Representation", None):
        continue
    total += 1
    try:
        zs = verts_of(elem)
        if not zs:
            continue
        mn, mx = min(zs), max(zs)
        elem_bounds.append((elem.is_a(), elem.id(), mn, mx))
        zs_all.extend(zs)
    except Exception as e:
        errors += 1

summary = {}
if zs_all:
    summary = {
        "count_elements_with_geom": len(elem_bounds),
        "total_elements_seen": total,
        "errors": errors,
        "unit_detected": unit_desc,
        "global_minZ": min(zs_all),
        "global_maxZ": max(zs_all),
        "approx_ground_levels_sample": sorted(list(set(round(z, 3) for z in itertools.islice(sorted(zs_all), 0, 300))))[:10],
    }
else:
    summary = {
        "count_elements_with_geom": 0,
        "total_elements_seen": total,
        "errors": errors,
        "unit_detected": unit_desc,
    }

# Compute how many vertices lie near each target assuming (A) model is in mm, targets=225,825,...
targets_mm = [225.0, 825.0, 1425.0, 2025.0]
targets_m  = [x/1000.0 for x in targets_mm]
def count_near(zs, targets, tol):
    return {t: sum(1 for z in zs if abs(z - t) <= tol) for t in targets}

near_counts_mm = count_near(zs_all, targets_mm, 2.0)
near_counts_m  = count_near(zs_all, targets_m, 0.002)

# Also check bounding boxes crossing each target
def count_bbox_cross(bounds, targets, tol):
    d = defaultdict(int)
    for (_typ, _id, mn, mx) in bounds:
        for t in targets:
            if (mn - tol) <= t <= (mx + tol):
                d[t] += 1
    return dict(d)

bbox_counts_mm = count_bbox_cross(elem_bounds, targets_mm, 2.0)
bbox_counts_m  = count_bbox_cross(elem_bounds, targets_m, 0.002)

print("=== IFC Z Diagnostics ===")
print(json.dumps(summary, indent=2))
print("\n-- Vertex counts within tol of targets (assuming mm):")
print(near_counts_mm)
print("\n-- Vertex counts within tol of targets (assuming metres):")
print(near_counts_m)
print("\n-- BBox crossings (assuming mm):")
print(bbox_counts_mm)
print("\n-- BBox crossings (assuming metres):")
print(bbox_counts_m)

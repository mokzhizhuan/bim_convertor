# -*- coding: utf-8 -*-
"""
Export merged STL(s) from IFC, scaled ×1000 (mm), grouped by:
  - storey (one STL per storey), or
  - wall label (Wall 1..6, Floor F) inferred from names/tags.

Version-safe for IfcOpenShell geometry settings.

Usage:
  python ifc_to_grouped_stl_x1000.py input.ifc out_dir --group by_storey
  python ifc_to_grouped_stl_x1000.py input.ifc out_dir --group by_wall
  python ifc_to_grouped_stl_x1000.py input.ifc out_dir --group by_wall --only IfcWall,IfcSlab
"""

import sys, os, re, argparse
from pathlib import Path
import numpy as np

try:
    import ifcopenshell
    import ifcopenshell.geom
    from ifcopenshell.util.unit import calculate_unit_scale
    from ifcopenshell.util.element import get_container
except Exception as e:
    print("Missing IfcOpenShell. Install with: pip install ifcopenshell")
    sys.exit(1)

try:
    import trimesh
except Exception as e:
    print("Missing trimesh. Install with: pip install trimesh")
    sys.exit(1)


# ---------- helpers ----------


def _set_opt(settings, name, value):
    """Set a geometry setting only if it exists in this build."""
    if hasattr(settings, name):
        settings.set(getattr(settings, name), value)


def _safe(s: str, fallback: str = "Untitled"):
    if not s:
        return fallback
    s = str(s).strip()
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", "_", s)
    return s[:120] or fallback


def _iter_products(ifc, only_classes=None):
    """Yield geometric products (skip 2D annotations/spaces)."""
    if only_classes:
        for c in only_classes:
            for p in ifc.by_type(c):
                if getattr(p, "ObjectPlacement", None) and getattr(
                    p, "Representation", None
                ):
                    yield p
    else:
        for p in ifc.by_type("IfcProduct"):
            if not (
                getattr(p, "ObjectPlacement", None)
                and getattr(p, "Representation", None)
            ):
                continue
            if p.is_a("IfcAnnotation") or p.is_a("IfcSpace"):
                continue
            yield p


def _storey_name(product):
    """Containing IfcBuildingStorey name if any."""
    try:
        st = get_container(product, ifc_class="IfcBuildingStorey")
        if st:
            return getattr(st, "Name", None) or getattr(st, "LongName", None)
    except Exception:
        pass
    return None


_WALL_PATTERNS = [
    r"\bW(?:all)?\s*([1-9]\d*)\b",  # "W1", "Wall 3"
    r"\b([1-9]\d*)\b",  # bare number "1", "2" (be cautious)
]


def _extract_wall_label(product):
    """
    Try to infer a wall label like '1'..'6' or 'F' (floor) from common fields/names.
    Returns '1'.. or 'F' or None.
    """
    txts = []
    for attr in ("Name", "LongName", "ObjectType", "Tag", "Description"):
        val = getattr(product, attr, None)
        if val:
            txts.append(str(val))

    full = " ".join(txts).upper()

    # Floor detection (for IfcSlab etc.)
    if product.is_a("IfcSlab"):
        pre = getattr(product, "PredefinedType", None)
        if (isinstance(pre, str) and pre.upper() == "FLOOR") or "FLOOR" in full:
            return "F"

    # Common naming: "W1", "Wall 1", or just "1"
    for pat in _WALL_PATTERNS:
        m = re.search(pat, full, flags=re.IGNORECASE)
        if m:
            num = m.group(1)
            # sanity: avoid catching storey numbers by accident when clearly a wall is intended
            return num

    # Some projects mark floor as 'F' in name/tag
    if re.search(r"\bF(LOOR)?\b", full):
        return "F"

    return None


def _accumulate(mesh_map, key, verts, faces):
    """Append vertices/faces into a merged accumulator for 'key'."""
    if key not in mesh_map:
        mesh_map[key] = {"V": [], "F": [], "ofs": 0}
    acc = mesh_map[key]
    if verts.size == 0 or faces.size == 0:
        return
    acc["F"].append(faces + acc["ofs"])
    acc["V"].append(verts)
    acc["ofs"] += verts.shape[0]


def _to_trimesh(acc):
    V = np.vstack(acc["V"]) if acc["V"] else np.zeros((0, 3))
    F = np.vstack(acc["F"]) if acc["F"] else np.zeros((0, 3), dtype=np.int64)
    return trimesh.Trimesh(vertices=V, faces=F, process=False)


# ---------- main exporter ----------


def export_grouped_stl(
    ifc_path: Path,
    out_dir: Path,
    group_mode: str,
    only: str = None,
    deflection: float = None,
):
    ifc = ifcopenshell.open(str(ifc_path))

    # Geometry settings (guarded)
    settings = ifcopenshell.geom.settings()
    _set_opt(settings, "USE_WORLD_COORDS", True)
    _set_opt(settings, "DISABLE_OPENING_SUBTRACTIONS", False)
    _set_opt(settings, "SEW_SHELLS", True)
    _set_opt(settings, "TRIANGULATE_NGONS", True)
    if deflection is not None:
        _set_opt(settings, "DEFLECTION_TOLERANCE", float(deflection))
    _set_opt(settings, "MAX_FACES_PER_MESH", 0)

    # Scale: IFC → meters → ×1000 to mm
    scale = calculate_unit_scale(ifc) * 1000.0

    out_dir.mkdir(parents=True, exist_ok=True)

    only_classes = None
    if only:
        only_classes = [c.strip() for c in only.split(",") if c.strip()]

    mesh_map = {}  # key -> accumulator
    n_ok, n_skip = 0, 0

    for prod in _iter_products(ifc, only_classes):
        # Decide grouping key
        if group_mode == "by_storey":
            key = _storey_name(prod) or "NoStorey"
            key = f"Storey_{key}"
        elif group_mode == "by_wall":
            # only consider likely wall/floor elements for labeling
            if (
                prod.is_a("IfcSlab")
                or prod.is_a("IfcWall")
                or prod.is_a("IfcWallStandardCase")
                or prod.is_a("IfcBuildingElementProxy")
            ):
                label = _extract_wall_label(prod)
            else:
                label = None
            if not label:
                # not identifiable as a specific wall — skip to keep files clean
                n_skip += 1
                continue
            key = f"Wall_{label}"
        else:
            key = "All"

        # Create shape and accumulate geometry
        try:
            shape = ifcopenshell.geom.create_shape(settings, prod)
        except Exception:
            n_skip += 1
            continue

        geom = shape.geometry
        v = np.asarray(geom.verts, dtype=float).reshape(-1, 3)
        f = np.asarray(geom.faces, dtype=np.int64).reshape(-1, 3)
        if v.size == 0 or f.size == 0:
            n_skip += 1
            continue

        v *= scale  # mm
        _accumulate(mesh_map, key, v, f)
        n_ok += 1

    # Write merged meshes
    wrote = 0
    for key, acc in mesh_map.items():
        m = _to_trimesh(acc)
        if m.is_empty:
            continue
        name = _safe(key)
        path = out_dir / f"{name}.stl"
        m.export(str(path))
        wrote += 1

    print(
        f"Done. Considered {n_ok} elements; skipped {n_skip}. Wrote {wrote} STL(s) to: {out_dir}"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc", help="Path to IFC")
    ap.add_argument("out", help="Output directory for STLs")
    ap.add_argument(
        "--group",
        choices=["by_storey", "by_wall", "all"],
        default="by_storey",
        help="Grouping mode: by_storey (default), by_wall, or all",
    )
    ap.add_argument(
        "--only",
        help="Comma-separated IFC classes to process (e.g. 'IfcWall,IfcSlab')",
        default=None,
    )
    ap.add_argument(
        "--deflection",
        type=float,
        default=None,
        help="Optional tessellation deflection (smaller = finer) if supported by your build",
    )
    args = ap.parse_args()

    ifc_path = Path(args.ifc)
    out_dir = Path(args.out)
    if not ifc_path.exists():
        print("IFC not found:", ifc_path)
        sys.exit(1)

    export_grouped_stl(
        ifc_path=ifc_path,
        out_dir=out_dir,
        group_mode=args.group,
        only=args.only,
        deflection=args.deflection,
    )


if __name__ == "__main__":
    main()

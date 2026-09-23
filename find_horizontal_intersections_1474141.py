#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find HORIZONTAL Model Lines that intersect a specific Model Line in an IFC.
Target: "Model Lines:1474141"

Usage:
  python find_horizontal_intersections_1474141.py /path/to/model.ifc

Notes:
- Requires: ifcopenshell (and numpy, which ships with ifcopenshell wheels)
- Works best with Revit-authored IFCs where Model Lines are IfcAnnotation
  with Name like "Model Lines:<ElementId>" and polyline/curve items.
"""

import sys
import math
from typing import Iterable, List, Tuple, Dict

import ifcopenshell
import numpy as np

# Tolerances
TOL_Y = 1e-6   # colinearity check on Y for horizontal
TOL_X = 1e-6   # for endpoint comparisons / merging
TOL_Z = 1e-4   # keep Z noise out; most model lines sit on a plane

DEFAULT_TARGET_TAG = "Model Lines:1474141"


# ---------------------- Transform utilities ----------------------

def _axis2placement3d_to_matrix(ax) -> np.ndarray:
    """Make a 4x4 transform from IfcAxis2Placement3D (OpenCascade-style basis)."""
    # Origin
    O = np.array([ax.Location.X, ax.Location.Y, getattr(ax.Location, "Z", 0.0)], dtype=float)

    # Local axes (Z=Axis, X derived from RefDirection, Y = Z x X)
    if ax.Axis is not None:
        Z = np.array([ax.Axis.DirectionRatios[0], ax.Axis.DirectionRatios[1], ax.Axis.DirectionRatios[2]], dtype=float)
    else:
        Z = np.array([0.0, 0.0, 1.0], dtype=float)

    if ax.RefDirection is not None:
        X = np.array([ax.RefDirection.DirectionRatios[0], ax.RefDirection.DirectionRatios[1], ax.RefDirection.DirectionRatios[2]], dtype=float)
    else:
        X = np.array([1.0, 0.0, 0.0], dtype=float)

    # Orthonormalize
    Z = Z / (np.linalg.norm(Z) or 1.0)
    X = X - np.dot(X, Z) * Z
    X = X / (np.linalg.norm(X) or 1.0)
    Y = np.cross(Z, X)

    M = np.eye(4, dtype=float)
    M[:3, 0] = X
    M[:3, 1] = Y
    M[:3, 2] = Z
    M[:3, 3] = O
    return M


def _local_placement_chain(product) -> np.ndarray:
    """Accumulate 4x4 transform up to root for an IfcProduct (ObjectPlacement)."""
    M = np.eye(4, dtype=float)
    pl = getattr(product, "ObjectPlacement", None)
    while pl is not None:
        # IfcLocalPlacement(RelativePlacement = IfcAxis2Placement3D/2D)
        rel = pl.RelativePlacement
        if rel.is_a("IfcAxis2Placement3D"):
            M = M @ _axis2placement3d_to_matrix(rel)
        elif rel.is_a("IfcAxis2Placement2D"):
            # Upgrade 2D to 3D
            loc = rel.Location
            O = np.array([loc.X, loc.Y, 0.0], dtype=float)
            # RefDirection only; up is Z
            if rel.RefDirection is not None:
                rx, ry = rel.RefDirection.DirectionRatios[0], rel.RefDirection.DirectionRatios[1]
                X = np.array([rx, ry, 0.0], dtype=float)
            else:
                X = np.array([1.0, 0.0, 0.0], dtype=float)
            X = X / (np.linalg.norm(X) or 1.0)
            Z = np.array([0.0, 0.0, 1.0], dtype=float)
            Y = np.cross(Z, X)
            M2 = np.eye(4, dtype=float)
            M2[:3, 0] = X
            M2[:3, 1] = Y
            M2[:3, 2] = Z
            M2[:3, 3] = O
            M = M @ M2
        else:
            # Unknown placement; ignore
            pass
        pl = getattr(pl, "PlacementRelTo", None)
    return M


def _hom(p):
    if len(p) == 2:
        return np.array([p[0], p[1], 0.0, 1.0], dtype=float)
    return np.array([p[0], p[1], p[2], 1.0], dtype=float)


def _to_world(pts: Iterable[Tuple[float, float, float]], M: np.ndarray) -> List[Tuple[float, float, float]]:
    out = []
    for p in pts:
        v = _hom(p)
        w = (M @ v)[:3]
        out.append((float(w[0]), float(w[1]), float(w[2])))
    return out


# ---------------------- Geometry extraction ----------------------

def _segments_from_polyline(pl) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    pts = [(c.Coordinates[0], c.Coordinates[1], (c.Coordinates[2] if len(c.Coordinates) > 2 else 0.0)) for c in pl.Points]
    segs = []
    for a, b in zip(pts[:-1], pts[1:]):
        segs.append((a, b))
    return segs


def _pt_from_ifc_cartesian_point(cp) -> Tuple[float, float, float]:
    arr = cp.Coordinates
    if len(arr) == 2:
        return float(arr[0]), float(arr[1]), 0.0
    return float(arr[0]), float(arr[1]), float(arr[2])


def _segments_from_trimmed_curve(tc) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    # Expect an underlying IfcLine; trims as points.
    c = tc.BasisCurve
    segs = []
    # Extract endpoints
    p0 = None
    p1 = None
    # Prefer cartesian point trims
    for t in tc.Trim1:
        if hasattr(t, "is_a") and t.is_a("IfcCartesianPoint"):
            p0 = _pt_from_ifc_cartesian_point(t)
            break
    for t in tc.Trim2:
        if hasattr(t, "is_a") and t.is_a("IfcCartesianPoint"):
            p1 = _pt_from_ifc_cartesian_point(t)
            break
    if p0 is None or p1 is None:
        # Fall back to parameterization (rare for model lines); skip if unavailable
        return segs
    segs.append((p0, p1))
    return segs


def _flatten_items(item) -> List:
    """Return a flat list of curve items from various container types."""
    out = []
    if item.is_a("IfcGeometricCurveSet"):
        for e in item.Elements:
            out.extend(_flatten_items(e))
    elif item.is_a("IfcGeometricSet"):
        for e in (item.Elements or []):
            out.extend(_flatten_items(e))
    else:
        out.append(item)
    return out


def _segments_from_item(item) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    segs = []
    for it in _flatten_items(item):
        if it.is_a("IfcPolyline"):
            segs.extend(_segments_from_polyline(it))
        elif it.is_a("IfcTrimmedCurve"):
            segs.extend(_segments_from_trimmed_curve(it))
        # You can add IfcCompositeCurve, IfcCurveBoundedPlane, etc. as needed.
    return segs


def collect_model_line_segments(ifc) -> Dict[str, List[Tuple[float, float, float, float, float, float]]]:
    """Return {tag -> list of world-space segments (x1,y1,z1,x2,y2,z2)} for Model Lines."""
    result: Dict[str, List[Tuple[float, float, float, float, float, float]]] = {}
    for ann in ifc.by_type("IfcAnnotation"):
        name = (ann.Name or "").strip()
        if not name.startswith("Model Lines:"):
            continue
        if not ann.Representation:
            continue
        M = _local_placement_chain(ann)
        for rep in ann.Representation.Representations or []:
            for item in rep.Items or []:
                segs = _segments_from_item(item)
                if not segs:
                    continue
                wsegs = []
                for a, b in segs:
                    (x1, y1, z1), (x2, y2, z2) = _to_world([a, b], M)
                    wsegs.append((x1, y1, z1, x2, y2, z2))
                if wsegs:
                    result.setdefault(name, []).extend(wsegs)
    return result


# ---------------------- Intersection helpers ----------------------

def _is_horizontal(seg) -> bool:
    x1, y1, z1, x2, y2, z2 = seg
    return abs(y2 - y1) <= TOL_Y and abs(z2 - z1) <= TOL_Z and abs(x2 - x1) > TOL_X


def _overlap_1d(a1, a2, b1, b2) -> Tuple[float, float] | None:
    lo = max(min(a1, a2), min(b1, b2))
    hi = min(max(a1, a2), max(b1, b2))
    if hi >= lo + TOL_X:
        return (lo, hi)
    return None


def find_horizontal_intersections(segments: Dict[str, List[Tuple[float, float, float, float, float, float]]],
                                  target_tag: str):
    tgt = [s for s in segments.get(target_tag, []) if _is_horizontal(s)]
    if not tgt:
        print(f"[WARN] No horizontal segments found for target '{target_tag}'.")
        return

    # We'll test each target horizontal segment individually.
    others = {k: [s for s in v if _is_horizontal(s)] for k, v in segments.items() if k != target_tag}

    print(f"Target tag: {target_tag}")
    for i, s in enumerate(tgt, 1):
        x1, y1, *_ = s
        x2 = s[3]
        a1, a2 = (x1, x2) if x1 <= x2 else (x2, x1)
        print(f"  [T{i}] y={y1:.6f}, x-span=({a1:.3f} → {a2:.3f})")

    any_hit = False
    for ti, ts in enumerate(tgt, 1):
        tx1, ty, *_ = ts
        tx2 = ts[3]
        for tag, segs in others.items():
            for s in segs:
                sx1, sy, *_ = s
                sx2 = s[3]
                # colinear on Y?
                if abs(sy - ty) > TOL_Y:
                    continue
                # overlap on X
                ov = _overlap_1d(tx1, tx2, sx1, sx2)
                if ov:
                    any_hit = True
                    lo, hi = ov
                    print(f"  -> Intersects with [{tag}] at y={ty:.6f}, overlap x=({lo:.3f} → {hi:.3f})")

    if not any_hit:
        print("No horizontal intersections found (no colinear overlaps).")


def main():
    if len(sys.argv) < 2:
        print("Usage: python find_horizontal_intersections_1474141.py /path/to/model.ifc")
        return
    ifc_path = sys.argv[1]
    ifc = ifcopenshell.open(ifc_path)
    segs = collect_model_line_segments(ifc)

    # Use a local variable for target, avoid `global`
    target_tag = DEFAULT_TARGET_TAG
    if target_tag not in segs:
        # Heuristic: some exports store tag on ObjectType or GlobalId label; try fuzzy match
        alt = [k for k in segs.keys() if k.endswith(":1474141")]
        if alt:
            target_tag = alt[0]

    find_horizontal_intersections(segs, target_tag)


if __name__ == "__main__":
    main()

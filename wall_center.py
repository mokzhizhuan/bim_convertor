from __future__ import annotations
import json
import csv
from typing import Dict, Any, Iterable, Tuple

def _span(vals: Iterable[float]) -> float:
    vals = list(vals)
    if not vals:
        return 0.0
    return float(max(vals) - min(vals))

def _infer_LTH_from_vertices(w: Dict[str, Any]) -> Tuple[float, float, float]:
    """Infer (L, T, H) from vertices when area == (0,0,0).
    L is span along declared axis; T is span along the orthogonal axis; H is span in Z.
    """
    V = w.get("vertices")
    if V is None:
        return (0.0, 0.0, 0.0)
    # Support both numpy arrays and python lists
    try:
        xs = [float(p[0]) for p in V]
        ys = [float(p[1]) for p in V]
        zs = [float(p[2]) for p in V]
    except Exception:
        return (0.0, 0.0, 0.0)

    dx = _span(xs)
    dy = _span(ys)
    dz = _span(zs)
    axis = w.get("axis", "X")

    if axis == "X":
        L, T = dx, dy
    else:  # axis == 'Y'
        L, T = dy, dx
    H = dz
    return (L, T, H)

def wall_center_from_area_sign_only(w):
    x = float(w.get("x", 0.0))
    y = float(w.get("y", 0.0))
    z = float(w.get("z", 0.0))
    axis = w.get("axis", "X")           # 'X' or 'Y'
    facing = w.get("facingaxis", "+X")  # e.g. '+X','-Y'
    sign_char = facing[:1] if isinstance(facing, str) else '+'
    face_axis = facing[-1] if isinstance(facing, str) else axis

    sgn_normal = +1.0 if sign_char == '+' else -1.0

    # Unpack or infer (L, T, H)
    L, T, H = w.get("area", (0, 0, 0))
    try:
        L = float(L); T = float(T); H = float(H)
    except Exception:
        L = T = H = 0.0

    if L == 0.0 or T == 0.0 or H == 0.0:
        import numpy as np
        V = w.get("vertices") or []
        xs = [float(p[0]) for p in V] if V else []
        ys = [float(p[1]) for p in V] if V else []
        zs = [float(p[2]) for p in V] if V else []
        dx = (max(xs)-min(xs)) if xs else 0.0
        dy = (max(ys)-min(ys)) if ys else 0.0
        dz = (max(zs)-min(zs)) if zs else 0.0
        if axis == 'X':
            L = L or dx; T = T or dy
        else:
            L = L or dy; T = T or dx
        H = H or dz

    # Along-axis sign rule:
    # if facingaxis letter matches the wall axis, use its sign for along; else +L/2
    along_sign = sgn_normal if face_axis == axis else +1.0

    if axis == 'X':
        cx = x + along_sign * 0.5 * L
        cy = y + sgn_normal * 0.5 * T  # normal on Y
    else:  # axis == 'Y'
        cx = x + sgn_normal * 0.5 * T  # normal on X
        cy = y + along_sign * 0.5 * L

    cz = z + 0.5 * H
    return (cx, cy, cz)


def compute_centers(walls: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Return {name: {'x': cx, 'y': cy, 'z': cz}} for each wall."""
    out = {}
    for w in walls:
        name = w.get("name", "<unnamed>")
        cx, cy, cz = wall_center_from_area_sign_only(w)
        out[name] = {"x": cx, "y": cy, "z": cz}
    return out

def write_csv(centers: Dict[str, Dict[str, float]], fp: str) -> None:
    with open(fp, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["name", "x", "y", "z"])
        for name, xyz in centers.items():
            wr.writerow([name, xyz["x"], xyz["y"], xyz["z"]])

def write_json(centers: Dict[str, Dict[str, float]], fp: str) -> None:
    with open(fp, "w") as f:
        json.dump(centers, f, indent=2)

# -------------------------
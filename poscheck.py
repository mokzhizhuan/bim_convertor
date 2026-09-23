import numpy as np
from collections import Counter, defaultdict, OrderedDict
import re


def _column_has_any_point(
    *, pos, opening, a_min, a_max, z_min, z_max, z_base, repeatcount, tile_h
):
    if not opening or a_min is None:
        return True
    for r in range(repeatcount):
        z = z_base + tile_h * r
        inside_open = (a_min <= pos <= a_max) and (z_min <= z <= z_max)
        if not inside_open:
            return True
    return False

def _is_in_edge_band(pos, *, edge_max, thickness, origin ,eps=1e-9):
    if thickness is None or thickness <= 0 or edge_max is None:
        return False
    left_band  = (0 - eps - origin) <= pos <= (thickness + eps - origin)
    right_band = (edge_max - thickness - eps - origin) <= pos <= (edge_max + eps - origin)
    return left_band or right_band

def _partition_by_two_spans(pos_list, span1, span2):
    s1, e1, w1, _ = span1
    s2, e2, w2, _ = span2
    c1 = (s1 + e1) / 2.0
    c2 = (s2 + e2) / 2.0
    pos_a, pos_b = [], []
    for p in pos_list:
        inside1 = s1 <= p <= e1
        inside2 = s2 <= p <= e2
        if inside1 and not inside2:
            pos_a.append(p)
        elif inside2 and not inside1:
            pos_b.append(p)
        elif inside1 and inside2:
            if abs(p - c1) <= abs(p - c2):
                pos_a.append(p)
            else:
                pos_b.append(p)
        else:
            d1 = min(abs(p - s1), abs(p - e1))
            d2 = min(abs(p - s2), abs(p - e2))
            if d1 <= d2:
                pos_a.append(p)
            else:
                pos_b.append(p)
    return pos_a, pos_b


def getopeningvert(opening_match, axis):
    if not opening_match:
        return None, None, None, None
    vertices = np.array(opening_match.get("vertices", []))
    idx = {"x": 0, "y": 1, "z": 2}[axis.lower()]
    axis_coords, z_coords = vertices[:, idx], vertices[:, 2]
    return axis_coords.min(), axis_coords.max(), z_coords.min(), z_coords.max()


def _alpha_index_from_eligible(pos, eligible_all, tol=1e-6):
    for i, p in enumerate(eligible_all):
        if abs(p - pos) <= tol:
            return i
    return min(range(len(eligible_all)), key=lambda i: abs(eligible_all[i] - pos))


def _wall_span(w, axis_obj):
    axis_letter = axis_obj.lower()  # 'x' or 'y'
    area = w.get("area")
    width = float(area[0]) if (area and len(area) >= 1) else 0.0
    if width == 0.0:
        verts = w.get("vertices")
        if isinstance(verts, np.ndarray) and verts.size > 0:
            ax = 0 if axis_letter == "x" else 1
            width = float(verts[:, ax].max() - verts[:, ax].min())
    base = float(w.get(axis_letter, 0.0))
    facing = str(w.get("facingaxis", "") or "")
    sign = 1
    if facing.endswith(axis_obj):
        sign = 1 if facing.startswith("+") else -1
    start, end = sorted((base, base + sign * width))
    return start, end, width, base


def _unique_in_order(vals, tol=0):
    if not vals:
        return []
    if tol <= 0:
        seen = OrderedDict()
        for v in vals:
            seen[v] = True
        return list(seen.keys())
    out = [vals[0]]
    for v in vals[1:]:
        if abs(v - out[-1]) > tol:
            out.append(v)
    return out


def get_width_heights_interval(next_w):
    match = re.search(r"\((\d+)x(\d+)mm\)", next_w)
    width, height = int(match.group(1)), int(match.group(2))
    return width, height


def get_width_heights_interval_dict(next_w):
    match = re.search(r"\((\d+)x(\d+)mm\)", next_w.get("name", ""))
    width, height = int(match.group(1)), int(match.group(2))
    return width, height


def bbox_xy(verts):
    v = np.asarray(verts)
    xs, ys = v[:, 0], v[:, 1]
    return xs.min(), ys.min(), xs.max(), ys.max()


def lengths_xyz(V):
    V = np.asarray(V, float)
    mins = V.min(axis=0)
    maxs = V.max(axis=0)
    Lx, Ly, Lz = (maxs - mins).tolist()
    return (round(Lx), round(Ly), round(Lz))


def collect_tiles(current, end, step, minv, maxv, key):
    tiles = []
    while current < end:
        if minv < current < maxv:
            tiles.append({key: current})
        current += step
    return tiles


def unique_numbers(seq):
    seen, out = set(), []
    for v in seq:
        if v is None:
            continue
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _safe_boxup_extents(verts):
    if isinstance(verts, np.ndarray) and verts.size > 0:
        xs, zs = verts[:, 0], verts[:, 2]
        return float(xs.max() - xs.min()), float(zs.max() - zs.min())
    if verts:
        xs = [float(v[0]) for v in verts]
        zs = [float(v[2]) for v in verts]
        return (max(xs) - min(xs)), (max(zs) - min(zs))
    return 0.0, 0.0


def _opening_dims_area(op):
    a = op.get("area", (0, 0, 0))
    w = float(a[0] or 0.0)
    h = float(a[1] or 0.0)
    return w * h


def _x_gate_ok(p, cap_x, boxup_x, EPS):
    return (p > boxup_x + EPS) and (p <= cap_x + EPS)

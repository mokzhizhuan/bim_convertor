#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
import math
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


def iter_step_entities(s: str):
    i = 0
    n = len(s)
    while True:
        i = s.find("#", i)
        if i == -1:
            break
        j = i + 1
        while j < n and s[j].isdigit():
            j += 1
        if j == i + 1:
            i = j
            continue
        ent_id = int(s[i + 1 : j])
        if j >= n or s[j] != "=":
            i = j
            continue
        j += 1
        k = j
        while k < n and (s[k].isalpha() or s[k] == "_" or s[k].isdigit()):
            k += 1
        ent_type = s[j:k].strip().upper()
        if k >= n or s[k] != "(":
            i = k
            continue
        depth = 0
        start = k
        m = k
        while m < n:
            ch = s[m]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    m2 = m + 1
                    while m2 < n and s[m2].isspace():
                        m2 += 1
                    if m2 < n and s[m2] == ";":
                        attrs_text = s[start + 1 : m]
                        yield ent_id, ent_type, attrs_text, i, m2 + 1
                        i = m2 + 1
                        break
            m += 1
        else:
            break


def split_top_level_commas(s: str) -> List[str]:
    parts = []
    buf = []
    depth = 0
    in_str = False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "'":
            in_str = not in_str
            buf.append(ch)
        elif not in_str:
            if ch == "(":
                depth += 1
                buf.append(ch)
            elif ch == ")":
                depth -= 1
                buf.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        else:
            buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return parts


def parse_ref(s: str) -> Optional[int]:
    s = s.strip()
    return int(s[1:]) if s.startswith("#") and s[1:].isdigit() else None


def parse_float_list_inside(par: str) -> List[float]:
    inner = par.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    out = []
    for t in split_top_level_commas(inner):
        t = t.strip()
        if t.upper() in {".F.", ".T.", "$"}:
            continue
        m = re.match(r"[A-Z_0-9]+\((.*)\)", t, flags=re.I)
        if m:
            t = m.group(1).strip()
        try:
            out.append(float(t))
        except Exception:
            pass
    return out


class IfcLite:
    def __init__(self, text: str):
        self.entities: Dict[int, Tuple[str, str]] = {}
        for eid, etype, attrs, _, _ in iter_step_entities(text):
            self.entities[eid] = (etype, attrs)

        self.cp_coords: Dict[int, Tuple[float, float, float]] = {}
        for eid, (etype, attrs) in self.entities.items():
            if etype == "IFCCARTESIANPOINT":
                nums = parse_float_list_inside(attrs)
                if len(nums) >= 2:
                    x, y = nums[0], nums[1]
                    z = nums[2] if len(nums) >= 3 else 0.0
                    self.cp_coords[eid] = (x, y, z)

        self.dir_ratios: Dict[int, Tuple[float, float, float]] = {}
        for eid, (etype, attrs) in self.entities.items():
            if etype == "IFCDIRECTION":
                nums = parse_float_list_inside(attrs)
                if len(nums) >= 2:
                    dx, dy = nums[0], nums[1]
                    dz = nums[2] if len(nums) >= 3 else 0.0
                    self.dir_ratios[eid] = (dx, dy, dz)

        self.vectors: Dict[int, Tuple[Tuple[float, float, float], float]] = {}
        for eid, (etype, attrs) in self.entities.items():
            if etype == "IFCVECTOR":
                parts = split_top_level_commas(attrs)
                if len(parts) >= 2:
                    dref = parse_ref(parts[0])
                    try:
                        mag = float(parts[1])
                    except Exception:
                        mag = None
                    if dref in self.dir_ratios and mag is not None:
                        self.vectors[eid] = (self.dir_ratios[dref], mag)

        self.lines_basis: Dict[int, Tuple[int, Optional[int], Optional[int]]] = {}
        for eid, (etype, attrs) in self.entities.items():
            if etype == "IFCLINE":
                parts = split_top_level_commas(attrs)
                if len(parts) >= 2:
                    pref = parse_ref(parts[0])
                    dref = parse_ref(parts[1])
                    dir_id = dref if dref in self.dir_ratios else None
                    vec_id = dref if dref in self.vectors else None
                    if pref:
                        self.lines_basis[eid] = (pref, dir_id, vec_id)

        self.polyline_points: Dict[int, List[int]] = {}
        for eid, (etype, attrs) in self.entities.items():
            if etype == "IFCPOLYLINE":
                inner = attrs.strip()
                if inner.startswith("(") and inner.endswith(")"):
                    inner = inner[1:-1].strip()
                lst = inner
                if lst.startswith("(") and lst.endswith(")"):
                    lst = lst[1:-1]
                refs = []
                for tok in split_top_level_commas(lst):
                    r = parse_ref(tok)
                    if r:
                        refs.append(r)
                if len(refs) >= 2:
                    self.polyline_points[eid] = refs

        self.trimmed_line_endpoints: Dict[
            int, Tuple[Tuple[float, float, float], Tuple[float, float, float]]
        ] = {}
        for eid, (etype, attrs) in self.entities.items():
            if etype == "IFCTRIMMEDCURVE":
                parts = split_top_level_commas(attrs)
                if len(parts) < 3:
                    continue
                bref = parse_ref(parts[0])
                if not bref or bref not in self.lines_basis:
                    continue
                t1s = parts[1]
                t2s = parts[2]

                def trim_to_point(tp):
                    tp = tp.strip()
                    r = parse_ref(tp.strip("() "))
                    if r and r in self.cp_coords:
                        return self.cp_coords[r]
                    nums = parse_float_list_inside(tp)
                    if len(nums) == 0:
                        return None
                    tval = nums[0]
                    pnt_id, dir_id, vec_id = self.lines_basis[bref]
                    p0 = self.cp_coords.get(pnt_id, (0.0, 0.0, 0.0))
                    if dir_id and dir_id in self.dir_ratios:
                        d = self.dir_ratios[dir_id]
                        norm = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2) or 1.0
                        dnorm = (d[0] / norm, d[1] / norm, d[2] / norm)
                        return (
                            p0[0] + dnorm[0] * tval,
                            p0[1] + dnorm[1] * tval,
                            p0[2] + dnorm[2] * tval,
                        )
                    if vec_id and vec_id in self.vectors:
                        d, mag = self.vectors[vec_id]
                        norm = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2) or 1.0
                        dnorm = (d[0] / norm, d[1] / norm, d[2] / norm)
                        return (
                            p0[0] + dnorm[0] * tval,
                            p0[1] + dnorm[1] * tval,
                            p0[2] + dnorm[2] * tval,
                        )
                    return None

                a = trim_to_point(t1s)
                b = trim_to_point(t2s)
                if a and b:
                    self.trimmed_line_endpoints[eid] = (a, b)

        self.shape_rep_items: Dict[int, Dict] = {}
        for eid, (etype, attrs) in self.entities.items():
            if etype == "IFCSHAPEREPRESENTATION":
                parts = split_top_level_commas(attrs)
                if len(parts) >= 4:
                    ctx = parse_ref(parts[0])
                    items_raw = parts[3].strip()
                    item_refs = []
                    if items_raw.startswith("(") and items_raw.endswith(")"):
                        items_raw = items_raw[1:-1]
                        for tok in split_top_level_commas(items_raw):
                            r = parse_ref(tok)
                            if r:
                                item_refs.append(r)
                    self.shape_rep_items[eid] = {"context": ctx, "items": item_refs}

        self.pdefshape_reps: Dict[int, List[int]] = {}
        for eid, (etype, attrs) in self.entities.items():
            if etype == "IFCPRODUCTDEFINITIONSHAPE":
                parts = split_top_level_commas(attrs)
                if len(parts) >= 3:
                    reps_part = parts[2].strip()
                    rep_ids = []
                    if reps_part.startswith("(") and reps_part.endswith(")"):
                        reps_part = reps_part[1:-1]
                        for tok in split_top_level_commas(reps_part):
                            r = parse_ref(tok)
                            if r:
                                rep_ids.append(r)
                    self.pdefshape_reps[eid] = rep_ids

        self.rep_to_owner: Dict[int, List[Tuple[str, int, str]]] = {}
        for pid, (ptype, pattrs) in self.entities.items():
            parts = split_top_level_commas(pattrs)
            if len(parts) >= 7:
                r = parse_ref(parts[6])
                if r and r in self.pdefshape_reps:
                    for rep_id in self.pdefshape_reps[r]:
                        owners = self.rep_to_owner.setdefault(rep_id, [])
                        name = ""
                        if len(parts) >= 3 and parts[2] and parts[2] != "$":
                            name = parts[2].strip("'")
                        owners.append((ptype, pid, name))

    def extract_target_segments_by_name(self, name_exact: str):
        target_pid = None
        for pid, (ptype, pattrs) in self.entities.items():
            if f"'{name_exact}'" in pattrs:
                target_pid = pid
                break
        if target_pid is None:
            raise RuntimeError(f"Could not find element named exactly '{name_exact}'.")
        parts = split_top_level_commas(self.entities[target_pid][1])
        if len(parts) < 7:
            raise RuntimeError(
                "Target entity missing standard product attributes (no representation)."
            )
        pdef_id = parse_ref(parts[6])
        if not pdef_id or pdef_id not in self.pdefshape_reps:
            raise RuntimeError("Target has no resolvable IfcProductDefinitionShape.")
        rep_ids = self.pdefshape_reps[pdef_id]
        target_contexts = set()
        target_segments = []
        for rid in rep_ids:
            info = self.shape_rep_items.get(rid)
            if not info:
                continue
            if info["context"]:
                target_contexts.add(info["context"])
            for it in info["items"]:
                if it in self.polyline_points:
                    pts = [self.cp_coords.get(i) for i in self.polyline_points[it]]
                    pts = [p for p in pts if p is not None]
                    for i in range(len(pts) - 1):
                        target_segments.append((pts[i], pts[i + 1], it, "IFCPOLYLINE"))
                elif it in self.trimmed_line_endpoints:
                    a, b = self.trimmed_line_endpoints[it]
                    target_segments.append((a, b, it, "IFCTRIMMEDCURVE/IFCLINE"))
                else:
                    it_type = self.entities.get(it, (None, None))[0]
                    it_attrs = self.entities.get(it, (None, None))[1]
                    if it_type == "IFCGEOMETRICCURVESET" and it_attrs:
                        elems_part = split_top_level_commas(it_attrs)[0].strip()
                        if elems_part.startswith("(") and elems_part.endswith(")"):
                            elems_part = elems_part[1:-1]
                            for tok in split_top_level_commas(elems_part):
                                r = parse_ref(tok)
                                if r in self.polyline_points:
                                    pts = [
                                        self.cp_coords.get(i)
                                        for i in self.polyline_points[r]
                                    ]
                                    pts = [p for p in pts if p is not None]
                                    for j in range(len(pts) - 1):
                                        target_segments.append(
                                            (pts[j], pts[j + 1], r, "IFCPOLYLINE")
                                        )
                                elif r in self.trimmed_line_endpoints:
                                    a, b = self.trimmed_line_endpoints[r]
                                    target_segments.append(
                                        (a, b, r, "IFCTRIMMEDCURVE/IFCLINE")
                                    )
        return target_pid, sorted(list(target_contexts)), target_segments


# ---- scan logic ----
ANGLE_TOL_DEG = 5.0
ANGLE_TOL_RAD = math.radians(ANGLE_TOL_DEG)
DX_ABS_TOL = 1.0
Y_INTERSECT_TOL = 2.0
X_INTERSECT_TOL = 2.0
Z_CLOSE_TOL = 5.0


def is_verticalish(a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if abs(dx) <= DX_ABS_TOL and abs(dy) > 1e-9:
        return True
    ang = math.atan2(abs(dx), abs(dy))
    return ang <= ANGLE_TOL_RAD and abs(dy) > 1e-9


def try_intersection_with_horizontal(a, b, y0, x_span, z_horiz):
    x1, y1, z1 = a
    x2, y2, z2 = b
    ymin = min(y1, y2) - Y_INTERSECT_TOL
    ymax = max(y1, y2) + Y_INTERSECT_TOL
    if not (ymin <= y0 <= ymax):
        return (False, None, None, None, None)
    den = y2 - y1
    if abs(den) < 1e-9:
        return (False, None, None, None, None)
    t = (y0 - y1) / den
    if not (-0.05 <= t <= 1.05):
        return (False, None, None, None, None)
    x_at = x1 + (x2 - x1) * t
    z_at = z1 + (z2 - z1) * t
    xmin, xmax = x_span
    if (xmin - X_INTERSECT_TOL) <= x_at <= (xmax + X_INTERSECT_TOL):
        dz = abs(z_at - z_horiz)
        return (True, x_at, y0, z_at, dz)
    return (False, None, None, None, None)


def get_target_horizontals(model: IfcLite, name_exact: str):
    target_pid, target_contexts, target_segments = (
        model.extract_target_segments_by_name(name_exact)
    )
    horizontals = []
    for a, b, item_id, kind in target_segments:
        dy = b[1] - a[1]
        dx = b[0] - a[0]
        if abs(dy) <= 1e-9 and abs(dx) > 1e-9:
            y0 = a[1]
            z0 = a[2]
            x_span = (min(a[0], b[0]), max(a[0], b[0]))
            horizontals.append(
                {
                    "item_step_id": item_id,
                    "kind": kind,
                    "y": y0,
                    "z": z0,
                    "x_min": x_span[0],
                    "x_max": x_span[1],
                }
            )
    return target_pid, target_contexts, horizontals, target_segments


def scan_verticalish(model: IfcLite, horizontals, target_contexts=None):
    rows = []
    for rid, info in model.shape_rep_items.items():
        if (target_contexts is not None) and (
            info["context"] not in set(target_contexts)
        ):
            continue
        owners = model.rep_to_owner.get(rid, [])
        for it in info["items"]:
            segs = []
            if it in model.polyline_points:
                pts = [model.cp_coords.get(i) for i in model.polyline_points[it]]
                pts = [p for p in pts if p is not None]
                for i in range(len(pts) - 1):
                    segs.append((pts[i], pts[i + 1], "IFCPOLYLINE"))
            elif it in model.trimmed_line_endpoints:
                a, b = model.trimmed_line_endpoints[it]
                segs.append((a, b, "IFCTRIMMEDCURVE/IFCLINE"))
            else:
                it_type = model.entities.get(it, (None, None))[0]
                it_attrs = model.entities.get(it, (None, None))[1]
                if it_type == "IFCGEOMETRICCURVESET" and it_attrs:
                    elems_part = split_top_level_commas(it_attrs)[0].strip()
                    if elems_part.startswith("(") and elems_part.endswith(")"):
                        elems_part = elems_part[1:-1]
                        for tok in split_top_level_commas(elems_part):
                            r = parse_ref(tok)
                            if r in model.polyline_points:
                                pts = [
                                    model.cp_coords.get(i)
                                    for i in model.polyline_points[r]
                                ]
                                pts = [p for p in pts if p is not None]
                                for j in range(len(pts) - 1):
                                    segs.append((pts[j], pts[j + 1], "IFCPOLYLINE"))
                            elif r in model.trimmed_line_endpoints:
                                a, b = model.trimmed_line_endpoints[r]
                                segs.append((a, b, "IFCTRIMMEDCURVE/IFCLINE"))
            for a, b, kind in segs:
                if not is_verticalish(a, b):
                    continue
                for h in horizontals:
                    ok, ix, iy, iz, dz = try_intersection_with_horizontal(
                        a, b, y0=h["y"], x_span=(h["x_min"], h["x_max"]), z_horiz=h["z"]
                    )
                    if not ok:
                        continue
                    if owners:
                        for otype, opid, oname in owners:
                            rows.append(
                                {
                                    "shape_rep_id": rid,
                                    "owner_type": otype,
                                    "owner_step_id": opid,
                                    "owner_name": oname,
                                    "item_step_id": it,
                                    "item_kind": kind,
                                    "x1": a[0],
                                    "y1": a[1],
                                    "z1": a[2],
                                    "x2": b[0],
                                    "y2": b[1],
                                    "z2": b[2],
                                    "crosses_horizontal_item": h["item_step_id"],
                                    "crosses_y": h["y"],
                                    "x_at_cross": ix,
                                    "y_at_cross": iy,
                                    "z_at_cross": iz,
                                    "z_of_horizontal": h["z"],
                                    "z_close(≤5mm)": abs(iz - h["z"]) <= Z_CLOSE_TOL,
                                }
                            )
                    else:
                        rows.append(
                            {
                                "shape_rep_id": rid,
                                "owner_type": "",
                                "owner_step_id": 0,
                                "owner_name": "",
                                "item_step_id": it,
                                "item_kind": kind,
                                "x1": a[0],
                                "y1": a[1],
                                "z1": a[2],
                                "x2": b[0],
                                "y2": b[1],
                                "z2": b[2],
                                "crosses_horizontal_item": h["item_step_id"],
                                "crosses_y": h["y"],
                                "x_at_cross": ix,
                                "y_at_cross": iy,
                                "z_at_cross": iz,
                                "z_of_horizontal": h["z"],
                                "z_close(≤5mm)": abs(iz - h["z"]) <= Z_CLOSE_TOL,
                            }
                        )
    return rows


def run(ifc_path: str, target_name: str, out_same: str, out_all: str, out_inside: str):
    text = Path(ifc_path).read_text(encoding="utf-8", errors="ignore")
    model = IfcLite(text)
    target_pid, target_contexts, horizontals, target_segments = get_target_horizontals(
        model, target_name
    )
    rows_same = scan_verticalish(
        model, horizontals, target_contexts=set(target_contexts)
    )
    rows_all = scan_verticalish(model, horizontals, target_contexts=None)

    # inside vertical-ish
    rows_inside = []
    for a, b, item_id, kind in target_segments:
        if not is_verticalish(a, b):
            continue
        for h in horizontals:
            ok, ix, iy, iz, dz = try_intersection_with_horizontal(
                a, b, y0=h["y"], x_span=(h["x_min"], h["x_max"]), z_horiz=h["z"]
            )
            if not ok:
                continue
            rows_inside.append(
                {
                    "item_step_id": item_id,
                    "kind": kind,
                    "x1": a[0],
                    "y1": a[1],
                    "z1": a[2],
                    "x2": b[0],
                    "y2": b[1],
                    "z2": b[2],
                    "crosses_horizontal_item": h["item_step_id"],
                    "crosses_y": h["y"],
                    "x_at_cross": ix,
                    "y_at_cross": iy,
                    "z_at_cross": iz,
                    "z_of_horizontal": h["z"],
                    "z_close(≤5mm)": abs(iz - h["z"]) <= Z_CLOSE_TOL,
                }
            )

    cols_scan = [
        "shape_rep_id",
        "owner_type",
        "owner_step_id",
        "owner_name",
        "item_step_id",
        "item_kind",
        "x1",
        "y1",
        "z1",
        "x2",
        "y2",
        "z2",
        "crosses_horizontal_item",
        "crosses_y",
        "x_at_cross",
        "y_at_cross",
        "z_at_cross",
        "z_of_horizontal",
        "z_close(≤5mm)",
    ]
    import pandas as pd

    df_same = pd.DataFrame(rows_same, columns=cols_scan)
    df_all = pd.DataFrame(rows_all, columns=cols_scan)
    df_inside_cols = [
        "item_step_id",
        "kind",
        "x1",
        "y1",
        "z1",
        "x2",
        "y2",
        "z2",
        "crosses_horizontal_item",
        "crosses_y",
        "x_at_cross",
        "y_at_cross",
        "z_at_cross",
        "z_of_horizontal",
        "z_close(≤5mm)",
    ]
    df_inside = pd.DataFrame(rows_inside, columns=df_inside_cols)

    if not df_same.empty:
        df_same = df_same.sort_values(
            ["owner_type", "owner_step_id", "x_at_cross", "crosses_y"]
        ).reset_index(drop=True)
    if not df_all.empty:
        df_all = df_all.sort_values(
            ["owner_type", "owner_step_id", "x_at_cross", "crosses_y"]
        ).reset_index(drop=True)
    if not df_inside.empty:
        df_inside = df_inside.sort_values(["x_at_cross", "crosses_y"]).reset_index(
            drop=True
        )

    Path(out_same).parent.mkdir(parents=True, exist_ok=True)
    Path(out_all).parent.mkdir(parents=True, exist_ok=True)
    Path(out_inside).parent.mkdir(parents=True, exist_ok=True)
    df_same.to_csv(out_same, index=False)
    df_all.to_csv(out_all, index=False)
    df_inside.to_csv(out_inside, index=False)

    print(f"Target '{target_name}' STEP id computed.")
    print(
        f"Intersections — same ctx: {len(df_same)} | all ctx: {len(df_all)} | inside: {len(df_inside)}"
    )
    print(f"CSV:\n - {out_same}\n - {out_all}\n - {out_inside}")


# If run as a script:
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--ifc", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out_same", required=True)
    parser.add_argument("--out_all", required=True)
    parser.add_argument("--out_inside", required=True)
    args = parser.parse_args()
    run(args.ifc, args.name, args.out_same, args.out_all, args.out_inside)

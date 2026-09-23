#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract horizontal segments inside a target IFC element (by Name)
and report whether each segment intersects the target's vertical Z-axis.
This uses a lightweight STEP parser (no ifcopenshell dependency).

Usage:
  python extract_horizontal_segments_inside_axis.py \
      --ifc "/mnt/data/TERRAHL2-FP-MB-T1am(JMB).ifc" \
      --name "Model Lines:1472219" \
      --out "/mnt/data/horizontal_segments_inside_Model_Lines_1472219.csv"
"""

import re
import math
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


# -------------------- STEP parsing helpers --------------------
def iter_step_entities(s: str):
    """Yield (ent_id, ent_type, attrs_text, start_idx, end_idx) for each #id=TYPE(...); block."""
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
    """Split a STEP argument list by commas that are not nested within (...) and not inside quotes."""
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


def strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1]
    return s


def parse_ref(s: str) -> Optional[int]:
    s = s.strip()
    if s.startswith("#"):
        try:
            return int(s[1:])
        except Exception:
            return None
    return None


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


# -------------------- Model extraction --------------------
class IfcLite:
    def __init__(self, text: str):
        self.entities: Dict[int, Tuple[str, str]] = {}
        for eid, etype, attrs, _, _ in iter_step_entities(text):
            self.entities[eid] = (etype, attrs)

        # Indices we care about
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
                    magnitude = None
                    try:
                        magnitude = float(parts[1])
                    except Exception:
                        pass
                    if dref in self.dir_ratios and magnitude is not None:
                        self.vectors[eid] = (self.dir_ratios[dref], magnitude)

        # Basis lines (point + direction or vector)
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

        # Polylines
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

        # Trimmed lines -> endpoints
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

                def trim_to_point(tp) -> Optional[Tuple[float, float, float]]:
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

        # Shape reps and product definitions
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

    # ------------- geometry utilities -------------
    def extract_target_segments_by_name(self, name_exact: str):
        # find a product whose third attribute (Name) equals name_exact
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
        target_segments = []  # (a,b,item_id,kind)

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
                        a, b = pts[i], pts[i + 1]
                        target_segments.append((a, b, it, "IFCPOLYLINE"))
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
                                        a, b = pts[j], pts[j + 1]
                                        target_segments.append((a, b, r, "IFCPOLYLINE"))
                                elif r in self.trimmed_line_endpoints:
                                    a, b = self.trimmed_line_endpoints[r]
                                    target_segments.append(
                                        (a, b, r, "IFCTRIMMEDCURVE/IFCLINE")
                                    )
        return target_pid, sorted(list(target_contexts)), target_segments


# -------------------- Core logic --------------------
def compute_horizontal_inside_with_axis_intersections(target_segments):
    """
    From a list of target segments (a,b,item_id,kind), find all horizontal segments and whether each
    intersects the target's vertical Z-axis (a segment with dx≈0, dy≈0, dz>0). Returns a list of dicts.
    """
    # vertical Z-axis: constant x,y; varying z
    vertical_axis = None
    for a, b, item_id, kind in target_segments:
        dx = abs(b[0] - a[0])
        dy = abs(b[1] - a[1])
        dz = abs(b[2] - a[2])
        if dx <= 1e-9 and dy <= 1e-9 and dz > 1e-9:
            vertical_axis = (a, b, item_id, kind)
            break

    rows = []
    for a, b, item_id, kind in target_segments:
        # horizontal in XY (dy≈0), const Z (dz≈0), non-zero length
        if (
            abs(b[1] - a[1]) <= 1e-9
            and abs(b[2] - a[2]) <= 1e-9
            and abs(b[0] - a[0]) > 1e-9
        ):
            z = a[2]
            y = a[1]
            # intersection with vertical axis (if present)
            if vertical_axis is not None:
                (va, vb, vid, vkind) = vertical_axis
                ix, iy = va[0], va[1]
                on_span = (min(a[0], b[0]) - 1e-9 <= ix <= max(a[0], b[0]) + 1e-9) and (
                    abs(iy - y) <= 1e-9
                )
                ipt = (ix, iy, z) if on_span else None
            else:
                ipt = None
            rows.append(
                {
                    "item_step_id": item_id,
                    "kind": kind,
                    "z": z,
                    "y": y,
                    "x1": a[0],
                    "x2": b[0],
                    "intersects_vertical_axis": bool(ipt),
                    "intersection_point_x": ipt[0] if ipt else None,
                    "intersection_point_y": ipt[1] if ipt else None,
                    "intersection_point_z": ipt[2] if ipt else None,
                }
            )
    return rows, (vertical_axis[2] if vertical_axis else None)


def run(ifc_path: str, target_name: str, out_csv: str):
    p = Path(ifc_path)
    if not p.exists():
        raise FileNotFoundError(f"IFC not found: {p}")
    text = p.read_text(encoding="utf-8", errors="ignore")
    model = IfcLite(text)

    target_pid, target_contexts, target_segments = (
        model.extract_target_segments_by_name(target_name)
    )
    rows, axis_step_id = compute_horizontal_inside_with_axis_intersections(
        target_segments
    )

    df = pd.DataFrame(rows).sort_values(["z"]).reset_index(drop=True)
    out = Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    print(f"Target '{target_name}' STEP id: #{target_pid}")
    print(f"Segments found in target: {len(target_segments)}")
    print(f"Horizontal segments: {len(df)}")
    print(f"Vertical axis STEP id: {axis_step_id}")
    print(f"Saved CSV to: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract horizontal segments inside a target IFC element and report intersection with its vertical axis."
    )
    parser.add_argument(
        "--ifc",
        required=False,
        default="TERRAHL2-FP-MB-T1am(JMB).ifc",
        help="Path to .ifc file",
    )
    parser.add_argument(
        "--name",
        required=False,
        default="Model Lines:1472219",
        help="Exact Name of target element",
    )
    parser.add_argument(
        "--out",
        required=False,
        default="horizontal_segments_inside_Model_Lines_1472219.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    run(args.ifc, args.name, args.out)

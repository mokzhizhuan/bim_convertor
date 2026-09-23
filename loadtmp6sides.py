import re
import string
import numpy as np
from collections import Counter, defaultdict
import methodifcfindings as ifc_findings
import poscheck as poscheckPBU


class loadTMP6sides:
    def __init__(
        self,
        all_objs,
        stage2_rows,
        walls,
        wall_bss20,
        walls_bss_no_tile,
        materials,
        model_lines_walls,
        floor,
        storeys,
        opening,
        box_up,
        walls_bss_wall_num,
        externalxmax_width,
        externalymax_width,
        origin_x,
        origin_y,
    ):
        self.all_objs = all_objs
        self.stage2_rows = stage2_rows
        self.walls = walls
        self.wall_bss20 = wall_bss20
        self.walls_bss_no_tile = walls_bss_no_tile
        self.opening = opening
        self.label_openings_by_area_only()
        self.height20 = self.wall_bss20[1]["area"][1]
        self.materials = materials
        self.width, self.height = poscheckPBU.get_width_heights_interval(self.materials)
        self.model_lines_walls = model_lines_walls
        self.wallsheight50 = list(self.walls[0].values())[0]["area"][1]
        self.height_notile = self.walls_bss_no_tile[0]["area"][1]
        self.thickness = self.height20 + self.wallsheight50
        self.alphabet_list = list(string.ascii_lowercase)
        self.box_up = box_up
        self.floor = floor
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.wall_bss_wall_num = walls_bss_wall_num
        self.max_depth = max(wall["area"][2] for wall in self.wall_bss20)
        self.center_depth = (self.max_depth - self.height20) / 2
        self.center_depth_wall = self.center_depth - (self.wallsheight50 * 2)
        self.counts = Counter(
            w.get("Wall Number") for w in self.wall_bss_wall_num if "Wall Number" in w
        )
        self.duplicates = {num: cnt for num, cnt in self.counts.items() if cnt > 1}
        self.dupe_details = defaultdict(list)
        for i, w in enumerate(self.wall_bss_wall_num):
            num = w.get("Wall Number")
            name = w.get("Name")
            if num in self.duplicates:
                self.dupe_details[num].append({"index": i, "name": name})
        self.internalmax_width =[]
        self.externalxmax_width = externalxmax_width
        self.externalymax_width = externalymax_width
        self.storey_min_height = min(
            storeys, key=lambda s: s["elevation"], default={"elevation": 0}
        )["elevation"]
        self.index, self.tmptemp = 0, []
        self.lowest_z = min((w.get("z", 0) for w in self.wall_bss20), default=0)
        self.shower_walls = [
            w for w in self.wall_bss20 if w.get("z", 0) == self.lowest_z
        ]
        self.EPS = 1e-6
        self.build_all_tmp()

    def find_opening_by_name(self, wall_name):
        return next((o for o in self.opening if o["name"] == wall_name), None)

    def returnalpha(self, count):
        for index, item in enumerate(self.alphabet_list):
            if index == (count):
                return item

    def label_openings_by_area_only(self):
        if not getattr(self, "opening", None):
            return
        scored = [
            {"op": op, "area2d": poscheckPBU._opening_dims_area(op)}
            for op in self.opening
        ]
        if not scored:
            return
        door_rec = max(scored, key=lambda r: r["area2d"])
        for r in scored:
            r["op"]["opening_type"] = "door" if r is door_rec else "window"

    def _append_unique_point(self, row):
        wn = row.get("Wall Number")
        if wn is None:
            return
        self._seen_xyz_per_wall.setdefault(wn, set())
        self._seen_name_per_wall.setdefault(wn, set())
        name_key = row.get("Name")
        xyz_key = (row.get("GX"), row.get("GY"), row.get("GZ"))
        if (name_key in self._seen_name_per_wall[wn]) or (
            xyz_key in self._seen_xyz_per_wall[wn]
        ):
            return
        self._seen_name_per_wall[wn].add(name_key)
        self._seen_xyz_per_wall[wn].add(xyz_key)
        self.tmptemp.append(row)

    def setgetwall(self, w, wall_idx):
        if not hasattr(self, "_seen_wall_rows"):
            self._seen_wall_rows = set()
        wall_name = w.get("name", "")
        wall_key = (wall_idx, wall_name)
        if wall_key in self._seen_wall_rows:
            return
        self._seen_wall_rows.add(wall_key)
        area = w.get("area", (0, 0, 0))
        if isinstance(area, (tuple, list, np.ndarray)) and len(area) >= 3:
            width, height = area[0], area[2]
        else:
            width = height = 0
        if not width or not height:
            verts = w.get("vertices")
            if isinstance(verts, np.ndarray) and verts.size > 0:
                width, _, height = poscheckPBU.lengths_xyz(verts)
        self.tmptemp.append(
            {
                "Marking Type": "Wall",
                "Name": wall_name,
                "GX": w.get("x", 0),
                "GY": w.get("y", 0),
                "GZ": w.get("z", 0),
                "Wall Number": wall_idx + 1,
                "Shape Type": "",
                "Status": "blank",
                "Quadrant": 1,
                "Unnamed": "",
                "Width": width,
                "Height": height,
                "Orientation": "",
                "Diameter": "",
            }
        )

    def _append_unique_point(self, row):
        wn = row.get("Wall Number")
        if wn is None:
            return
        self._seen_xyz_per_wall.setdefault(wn, set())
        self._seen_name_per_wall.setdefault(wn, set())
        name_key = row.get("Name")
        xyz_key = (row.get("GX"), row.get("GY"), row.get("GZ"))
        if (name_key in self._seen_name_per_wall[wn]) or (
            xyz_key in self._seen_xyz_per_wall[wn]
        ):
            return
        self._seen_name_per_wall[wn].add(name_key)
        self._seen_xyz_per_wall[wn].add(xyz_key)
        self.tmptemp.append(row)

    def _get_duplicate_alpha(self, wall):
        if not wall:
            return None
        num = wall.get("Wall Number")
        name = wall.get("name", "")
        duplicates = getattr(self, "duplicates", {}) or {}
        dupe_details = getattr(self, "dupe_details", {}) or {}
        if num in duplicates:
            lst = dupe_details.get(num, [])
            idx = next((i for i, d in enumerate(lst) if d.get("name") == name), None)
            if idx is None:
                idx = 0
            return self.returnalpha(idx)
        return None

    def _get_model_lines_for_wall(self, wall_idx):
        wn = wall_idx + 1
        return [row for row in self.model_lines_walls if row.get("Wall Number") == wn]

    def _num(self, v, default=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def minmax_x(self, rows, tol=0.0, ignore_zeros=True, lower_bound=None):
        xs = []
        for r in rows:
            if not (str(r.get("Type","")).lower()=="line" or str(r.get("Name","")).startswith("Model Lines")):
                continue
            for x in (r.get("SGX"), r.get("EGX")):
                if x is None:
                    continue
                xv = float(x)
                if ignore_zeros and xv == 0.0:
                    continue
                if lower_bound is not None and xv < lower_bound:
                    continue
                xs.append(xv)
        return (min(xs), max(xs)) if xs else (None, None)

    def _build_wall(self, wall_idx):
        wall_dict = self.walls[wall_idx]
        wall_obj = list(wall_dict.values())[0]
        opening = self.find_opening_by_name(wall_obj["name"])
        axis_obj = wall_obj["axis"]
        main_area = wall_obj.get("area", (0, 0, 0))
        width = main_area[0]
        axis_letter = axis_obj.lower()
        model_lines = self._get_model_lines_for_wall(wall_idx)
        z_ref = min(
            (r.get("SGZ", 0) for r in model_lines if r.get("SGZ", 0) > 0), default=0
        )
        edge_max = (
            self.externalxmax_width if axis_letter == "x" else self.externalymax_width
        )
        shape_type = 1
        origin = self.origin_x if axis_letter == "x" else self.origin_y
        a_min, a_max, z_min, z_max = poscheckPBU.getopeningvert(opening, axis_obj)
        added_wall_names = set()
        if width > (self.externalxmax_width-(self.thickness*2)):
            first_w, _ = ifc_findings.find_closest_wall(wall_obj, self.wall_bss20)
            second_w, _ = (
                ifc_findings.find_closest_wall(first_w, self.wall_bss20)
                if first_w
                else (None, None)
            )
            candidates = [
                w for w in (first_w, second_w) if w and w.get("axis") == axis_obj
            ]
            if candidates:
                for w in candidates:  # for the wall x largest wall value
                    wname = w.get("name", "")
                    model_lines.append(
                        {
                            "Wall Number": wall_idx + 1,
                            "Name": wname,
                            "Marking Type": "Wall",
                            "SGX": w.get("x", 0),
                            "SGY": model_lines[0].get("SGY", 0),
                            "SGZ": z_ref,
                            "EGX": w.get("x", 0),
                            "EGY": model_lines[0].get("SGY", 0),
                            "EGZ": z_ref,
                            "Width": w.get("width", 0),
                            "Height": w.get("height", 0),
                        }
                    )
                    if wname not in added_wall_names:
                        self.setgetwall(w, wall_idx)
                        added_wall_names.add(wname)
                min_x, max_x = self.minmax_x(model_lines)
                internal_length = max_x - min_x 
                self.internalmax_width.append({
                    "Wall Number": wall_idx + 1,
                    "Internal Max Width": internal_length,
                    "Axis": axis_letter.upper(),
                    "Facing_Axis": wall_obj.get("facingaxis", ""),
                })
                axis_vals = [
                    (
                        self._num(r.get("EGX", r.get("SGX", 0)))
                        if axis_letter == "x"
                        else self._num(r.get("EGY", r.get("SGY", 0)))
                    )
                    for r in model_lines
                ]
                axis_vals = [v for v in axis_vals if v > self.EPS]
                pos_list = poscheckPBU._unique_in_order(axis_vals, tol=0)
                pos_list = sorted(pos_list)
                pos_list = [
                    p
                    for p in pos_list
                    if not poscheckPBU._is_in_edge_band(
                        p, edge_max=edge_max, thickness=self.thickness, origin=origin
                    )
                ]
                if pos_list:
                    anchor_x = model_lines[0].get("SGX", 0) if model_lines else 0
                    anchor_y = model_lines[0].get("SGY", 0) if model_lines else 0
                    z_base = z_ref
                    repeatcount = (
                        int((self.storey_min_height - z_ref) / self.height) + 1
                    )
                    eligible_all = [
                        p
                        for p in pos_list
                        if p > self.EPS
                        and poscheckPBU._column_has_any_point(
                            pos=p,
                            opening=opening,
                            a_min=a_min,
                            a_max=a_max,
                            z_min=z_min,
                            z_max=z_max,
                            z_base=z_base,
                            repeatcount=repeatcount,
                            tile_h=self.height,
                        )
                    ]
                    if len(candidates) >= 2:
                        span1 = poscheckPBU._wall_span(candidates[0], axis_obj)
                        span2 = poscheckPBU._wall_span(candidates[1], axis_obj)
                        pos_a, pos_b = poscheckPBU._partition_by_two_spans(
                            pos_list, span1, span2
                        )
                        pos_a = [p for p in pos_a if p in eligible_all]
                        pos_b = [p for p in pos_b if p in eligible_all]
                        for pos in pos_a:
                            count = poscheckPBU._alpha_index_from_eligible(
                                pos, eligible_all
                            )
                            if pos == candidates[0].get("x", 0):
                                shape_type = 4
                            else:
                                shape_type = 1
                            col_alpha = self.returnalpha(count)
                            for r in range(repeatcount):
                                z = z_base + self.height * r
                                if (
                                    opening
                                    and a_min is not None
                                    and a_min <= pos <= a_max
                                    and z_min <= z <= z_max
                                    and opening["opening_type"] == "door"
                                ):
                                    continue
                                self._append_unique_point(
                                    {
                                        "Marking Type": "Tiles Point",
                                        "Name": f"TW{wall_idx + 1}aMP{col_alpha}{r+1}",
                                        "GX": pos if axis_letter == "x" else anchor_x,
                                        "GY": anchor_y if axis_letter == "x" else pos,
                                        "GZ": z,
                                        "Wall Number": wall_idx + 1,
                                        "Shape Type": shape_type,
                                        "Status": "blank",
                                        "Quadrant": 1,
                                        "Unnamed": "",
                                    }
                                )
                        for pos in pos_b:
                            count = poscheckPBU._alpha_index_from_eligible(
                                pos, eligible_all
                            )
                            if pos == candidates[1].get("x", 0):
                                shape_type = 4
                            else:
                                shape_type = 1
                            col_alpha = self.returnalpha(count)
                            for r in range(repeatcount):
                                z = z_base + self.height * r
                                if (
                                    opening
                                    and a_min is not None
                                    and a_min <= pos <= a_max
                                    and z_min <= z <= z_max
                                    and opening["opening_type"] == "door"
                                ):
                                    continue
                                self._append_unique_point(
                                    {
                                        "Marking Type": "Tiles Point",
                                        "Name": f"TW{wall_idx + 1}bMP{col_alpha}{r+1}",
                                        "GX": pos if axis_letter == "x" else anchor_x,
                                        "GY": anchor_y if axis_letter == "x" else pos,
                                        "GZ": z,
                                        "Wall Number": wall_idx + 1,
                                        "Shape Type": shape_type,
                                        "Status": "blank",
                                        "Quadrant": 1,
                                        "Unnamed": "",
                                    }
                                )
        else:
            w2, _ = ifc_findings.find_closest_wall(
                wall_obj, self.wall_bss20 + self.walls_bss_no_tile
            )
            if w2 and w2.get("axis") == axis_obj:
                wname2 = w2.get("name", "")
                if wname2 not in added_wall_names:
                    self.setgetwall(w2, wall_idx)
                    added_wall_names.add(wname2)
                area, facing = w2.get("area"), w2.get("facingaxis")
                wall_width = (area[0] if area else 0) or 0
                if wall_width == 0:
                    verts = w2.get("vertices")
                    if isinstance(verts, np.ndarray) and verts.size > 0:
                        wall_width = float(verts[:, 0].max() - verts[:, 0].min())
                sweep_axis = "x" if str(facing).endswith("X") else "y"
                sign = 1 if str(facing).startswith("+") else -1
                base = w2.get(sweep_axis, 0)
                start, end = sorted((base, base + sign * wall_width))
                key = "SGX" if sweep_axis == "x" else "SGY"
                endkey = "EGX" if sweep_axis == "x" else "EGY"
                seen_vals, tiles = set(), []
                length , maxlength = 0, 0
                for r in model_lines:
                    v = r.get(key, 0)
                    vend = r.get(endkey, 0)
                    length = r.get("Length", 0) 
                    if length > maxlength:
                        maxlength = length
                    if v in seen_vals:
                        continue
                    seen_vals.add(v)
                    inside = (
                        (start < v < end)
                        if sweep_axis == "x"
                        else (start <= v < end - self.thickness)
                    )
                    insideend = (
                        (start < vend - self.thickness <= end)
                        if sweep_axis == "x"
                        else (start <= vend < end - self.thickness)
                    )
                    if inside:
                        tiles.append(
                            {"x": r.get("SGX", 0), "y": r.get("SGY", 0), "z": z_ref}
                        )
                        if round((end - start) / self.width) <= 1 and sweep_axis == "y":
                            shape_type = 4
                        if insideend:
                            if round((end - start) / self.width) > 1:
                                tiles.append(
                                    {
                                        "x": r.get("EGX", 0),
                                        "y": r.get("EGY", 0),
                                        "z": z_ref,
                                    }
                                )
                boxup_x, boxup_z, boxup_verts = 0.0, 0.0, []
                for box in self.box_up:
                    if wall_idx + 1 == box.get("Wall Number"):
                        boxup_verts = box.get("vertices", [])
                        boxup_x = float(box.get("GX", 0) or 0.0)
                        boxup_z = float(box.get("GZ", 0) or 0.0)
                        maxlength = w2.get("area")[0]
                        break
                self.internalmax_width.append({
                    "Wall Number": wall_idx + 1,
                    "Internal Max Width": maxlength,
                    "Axis": axis_letter.upper(),
                    "Facing_Axis": wall_obj.get("facingaxis", ""),
                })
                boxupx_span, boxupz_span = poscheckPBU._safe_boxup_extents(boxup_verts)
                cap_x = boxup_x + boxupx_span
                cap_z = boxup_z + boxupz_span
                has_boxup = bool(
                    (isinstance(boxup_verts, np.ndarray) and boxup_verts.size > 0)
                    or boxup_verts
                )
                tiles.sort(key=lambda t: t[sweep_axis])
                vals_sorted = [t[sweep_axis] for t in tiles]
                vals_sorted = [v for v in vals_sorted if v > self.EPS]
                pos_list = poscheckPBU._unique_in_order(vals_sorted, tol=0)
                pos_list = [
                    p
                    for p in pos_list
                    if not poscheckPBU._is_in_edge_band(
                        p, edge_max=edge_max, thickness=self.thickness, origin=origin
                    )
                ]
                if pos_list:
                    anchor_x = tiles[0]["x"] if tiles else 0
                    anchor_y = tiles[0]["y"] if tiles else 0
                    z_base = z_ref
                    repeatcount = (
                        int((self.storey_min_height - z_ref) / self.height) + 1
                    )
                    if has_boxup:
                        r_max = int((cap_z - z_base + self.EPS) // self.height)
                    else:
                        r_max = repeatcount - 1
                    if r_max < 0:
                        return
                    openingcheckpos = []
                    for col_i, pos in enumerate(pos_list):
                        alpha = self.returnalpha(col_i)
                        if (
                            has_boxup
                            and sweep_axis == "x"
                            and not poscheckPBU._x_gate_ok(
                                pos, cap_x, boxup_x, self.EPS
                            )
                        ):
                            continue
                        if pos > w2.get("x", 0) and sweep_axis == "x":
                            shape_type = 4
                        if has_boxup and  boxup_x + ((cap_x - boxup_x)/2) <= pos <= cap_x:
                            shape_type = 2
                        for r in range(r_max + 1):
                            z = z_base + self.height * r
                            if (
                                opening
                                and a_min is not None
                                and a_min <= pos <= a_max
                                and z_min <= z <= z_max
                            ):
                                openingcheckpos.append(
                                    {
                                        "x": pos if axis_obj == "X" else anchor_x,
                                        "y": anchor_y if axis_obj == "X" else pos,
                                        "z": z,
                                    }
                                )
                                continue
                            row = {
                                "Marking Type": "Tiles Point",
                                "Name": f"TW{wall_idx + 1}MP{alpha}{r+1}",
                                "GX": pos if axis_obj == "X" else anchor_x,
                                "GY": anchor_y if axis_obj == "X" else pos,
                                "GZ": z,
                                "Wall Number": wall_idx + 1,
                                "Shape Type": shape_type,
                                "Status": "blank",
                                "Quadrant": 1,
                                "Unnamed": "",
                            }
                            self._append_unique_point(row)
                    if openingcheckpos and opening["opening_type"] == "window":
                        ymax_val = max(p["y"] for p in openingcheckpos)
                        windowy_vals = [
                            p for p in openingcheckpos if p["y"] == ymax_val
                        ]
                        alpha_last = (
                            self.returnalpha(len(pos_list)) if pos_list else "a"
                        )
                        for i, p in enumerate(windowy_vals):
                            if ymax_val > w2.get("y", 0) and facing == "-Y":
                                continue
                            elif (
                                ymax_val > w2.get("y", 0) + wall_width
                                and facing == "+Y"
                            ):
                                continue
                            row = {
                                "Marking Type": "Tiles Point",
                                "Wall Number": wall_idx + 1,
                                "Name": f"TW{wall_idx + 1}MP{alpha_last}{i+1}",
                                "GX": (
                                    (p["x"] + w2.get("x", 0)) / 2
                                    if axis_obj == "X"
                                    else p["x"]
                                ),
                                "GY": (
                                    p["y"]
                                    if axis_obj == "X"
                                    else (p["y"] + w2.get("y", 0)) / 2
                                ),
                                "GZ": p["z"],
                                "Shape Type": 6,
                                "Status": "blank",
                                "Quadrant": 1,
                                "Unnamed": "",
                            }
                            self._append_unique_point(row)

    def build_all_tmp(self):
        self.tmptemp = []
        self._seen_xyz_per_wall = {}
        self._seen_name_per_wall = {}
        for wall_idx in range(len(self.walls)):
            self._build_wall(wall_idx)
        self.getTMPFloor()

    def getTMPFloor(self):
        floor_finishes = sorted(
            [
                obj
                for obj in self.floor
                if "floor finishes" in obj["name"].lower()
                and obj.get("area") != (0, 0, 0)
                and obj.get("z", 0) < 0
            ],
            key=lambda obj: obj["x"],
        )
        counter = 0
        for i, floor in enumerate(floor_finishes):
            xs, ys = [], []
            for wall in self.model_lines_walls:
                wn = wall.get("Wall Number", "")
                if str(wn).strip().upper() == "F":
                    if wall["SGZ"] == floor.get("z", 0):
                        xs.append(wall.get("SGX"))
                        xs.append(wall.get("EGX"))
                        ys.append(wall.get("SGY"))
                        ys.append(wall.get("EGY"))
            xs = [v for v in xs if v > self.EPS]
            ys = [v for v in ys if v > self.EPS]
            xs = poscheckPBU.unique_numbers(xs)
            ys = poscheckPBU.unique_numbers(ys)
            xs.sort()
            ys.sort()
            main_alpha = self.returnalpha(i)
            minx, miny, maxx, maxy = poscheckPBU.bbox_xy(floor.get("vertices", []))
            if (self.lowest_z + self.height20) == floor.get("z", 0):
                shape_type = 3
                for x in xs:
                    count = 0
                    appended = False
                    alpha = self.returnalpha(counter)
                    for y in ys:
                        if not (minx < x < maxx) or not (miny < y < maxy):
                            continue
                        self.tmptemp.append(
                            {
                                "Marking Type": "Tiles Point",
                                "Name": f"TW{len(self.walls) + 1}{main_alpha}MP{alpha}{count+1}",
                                "GX": x,
                                "GY": y,
                                "GZ": floor.get("z", 0),
                                "Wall Number": "F",
                                "Shape Type": shape_type,
                                "Status": "blank",
                                "Quadrant": 1,
                                "Unnamed": "",
                            }
                        )
                        count += 1
                        appended = True
                    if appended:
                        shape_type +=1
                        counter += 1
            else:
                repeatcount = int((max(ys) - min(ys)) / self.height)
                for x in xs:
                    alpha = self.returnalpha(counter)
                    if x < floor.get("x", 0) or x >= maxx:
                        continue
                    for i in range(repeatcount):
                        y = min(ys) + self.height * (i + 1)
                        self.tmptemp.append(
                            {
                                "Marking Type": "Tiles Point",
                                "Name": f"TW{len(self.walls) + 1}{main_alpha}MP{alpha}{i+1}",
                                "GX": x,
                                "GY": y,
                                "GZ": floor.get("z", 0),
                                "Wall Number": "F",
                                "Shape Type": 1,
                                "Status": "blank",
                                "Quadrant": 1,
                                "Unnamed": "",
                            }
                        )
                    counter += 1
        self.returnalltmps()

    def returnalltmps(self):
        return self.tmptemp, self.thickness , self.internalmax_width

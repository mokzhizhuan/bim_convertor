import heapq
import pandas as pd
import methodifcfindings as ifc_findings
from collections import defaultdict
import numpy as np

def assign_nearest_fitting(
    walls,
    fittings,
    storeys,
    floor,
    wall_info,
    glass_walls,
    count_minus_y,
    count_plus_y,
    centerpoint_rows,
    wall_bss20,
    wall_bss12,
):
    stage3_results, width, height = [], 0, 0
    floor_zs = [f.get("z", 0) for f in floor]
    top_twofloor_z = heapq.nlargest(2, floor_zs) if floor_zs else []
    lowest_floor = abs(min(floor_zs, default=0))
    storey_min_height = min((s.get("elevation", 0) for s in storeys), default=0)
    wall_finishes_lowest_height = min((w.get("z", 0) for w in wall_bss20), default=0)
    combined_walls = wall_bss20 + wall_bss12
    shower_walls = [
        w for w in combined_walls if w.get("z", 0) == wall_finishes_lowest_height
    ]
    glass_x_pos = glass_walls[0]["x"] if glass_walls else None
    for fitting in fittings:
        fx, fy, fz = fitting["x"], fitting["y"], fitting["z"]
        min_dist, nearestwallindex = float("inf"), 0
        walls_len = len(walls)
        rows_by_wall = {r["Wall Number"]: r for r in centerpoint_rows}
        for i, wall_dict in enumerate(walls):
            w = next(iter(wall_dict.values()))
            wx, wy, axis = w["x"], w["y"], w["axis"]
            dist = abs((fy - wy) if axis == "X" else (fx - wx))
            if walls_len == 6 and i > 0:
                cond = (count_minus_y == 2 and wx < glass_x_pos) or (
                    count_plus_y == 2 and wx > glass_x_pos
                )
                if cond:
                    row = rows_by_wall.get(i + 1)
                    if row is not None:
                        row["floortileheight"] = 1000 + lowest_floor + top_twofloor_z[0]
            if dist < min_dist:
                min_dist, nearestwallindex = dist, i + 1
        if fz >= storey_min_height:
            continue
        else:
            if w in shower_walls:
                if w["z"] + w["area"][1] >= fz <= w["z"]:
                    nearestwallindex = "F"
            elif fz < 0:
                nearestwallindex = "F"
        match = next(
            (w for w in wall_info if w["Wall Number"] == nearestwallindex), None
        )
        if match:
            width, height = match["Width"], match["Height"]
        stage3_results.append(
            {   
                "Marking Type": "Fitting",
                "Name": fitting["name"],
                "Marking Type": 1,
                "GX": fx,
                "GY": fy,
                "GZ": fz,
                "Wall Number": nearestwallindex,
                "Shape Type": 1,
                "Status" : "blank",
                "Quadrant" : 1,
                "Unnamed" : "",
                "Width": width,
                "Height": height,
                "Orientation" : "",
                "Diameter" : "",
            }
        )
    return stage3_results

def perp_dist(wall_axis,fittingaxis, wx, wy, fx, fy):
    if wall_axis == "X" and fittingaxis == "X":
        return abs(fy - wy)
    elif wall_axis == "Y" and fittingaxis == "Y":
        return abs(fx - wx)

def assign_nearest_fitting_rotation(
    walls,
    fittings,
    floor,
    wall_info,
    glass_walls,
    count_minus_y,
    count_plus_y,
    centerpoint_rows,
):
    stage3_results, width, height = [], 0, 0
    floor_zs = [f.get("z", 0) for f in floor]
    top_twofloor_z = heapq.nlargest(2, floor_zs) if floor_zs else []
    lowest_floor = abs(min(floor_zs, default=0))
    glass_x_pos = glass_walls[0]["x"] if glass_walls else None
    for fitting in fittings:
        fx, fy, fz = fitting["x"], fitting["y"], fitting["z"]
        name = fitting["name"]
        typenames = ""
        if "box" in name.lower():
            typenames = "boxup"
        else:
            typenames = "walls"
        verts = fitting.get("vertices", None)
        fittingaxis = fitting["axis"]
        min_dist, nearestwallindex = float("inf"), 0
        walls_len = len(walls)
        rows_by_wall = {r["Wall Number"]: r for r in centerpoint_rows}
        for i, wall_dict in enumerate(walls):
            w = next(iter(wall_dict.values()))
            wx, wy, axis = w["x"], w["y"], w["axis"]
            dist = perp_dist(axis, fittingaxis,wx, wy, fx, fy)
            if walls_len == 6 and i > 0:
                cond = (count_minus_y == 2 and wx < glass_x_pos) or (
                    count_plus_y == 2 and wx > glass_x_pos
                )
                if cond:
                    row = rows_by_wall.get(i + 1)
                    if row is not None:
                        row["floortileheight"] = 1000 + lowest_floor + top_twofloor_z[0]
            if dist is not None and dist < min_dist:
                min_dist, nearestwallindex = dist, i + 1
        match = next(
            (w for w in wall_info if w["Wall Number"] == nearestwallindex), None
        )
        if match:
            width, height = match["Width"], match["Height"]                
        if verts is None:
            verts_out = []
        else:
            verts_out = np.asarray(verts).tolist()
            if len(verts_out) == 0:
                print(f"[WARN] {fitting.get('name')} vertices array is empty")
        stage3_results.append(
            {
                "Wall Number": nearestwallindex,
                "Name": fitting["name"],
                "Type": typenames,
                "GX": fx,
                "GY": fy,
                "GZ": fz,
                "Width": width,
                "Height": height,
                "vertices": verts,
            }
        )
    return stage3_results


def _mean(vals):
    return sum(vals) / len(vals) if vals else 0.0


def _build_name_centers(lines):
    acc_x = defaultdict(list)
    acc_y = defaultdict(list)
    for ln in lines:
        cx = ln.get("CenterX_local")
        cy = ln.get("CenterY_local")
        if cx is None or cy is None:
            sx, sy = ln["StartX_local"], ln["StartY_local"]
            ex, ey = ln["EndX_local"], ln["EndY_local"]
            cx = (sx + ex) * 0.5
            cy = (sy + ey) * 0.5
        acc_x[ln["name"]].append(cx)
        acc_y[ln["name"]].append(cy)
    out = {}
    for name in acc_x:
        out[name] = (_mean(acc_x[name]), _mean(acc_y[name]), len(acc_x[name]))
    return out


def assign_nearest_line(
    walls,
    lines,
    storeys,
    floor,
    wall_info,
    glass_walls,
    count_minus_y,
    count_plus_y,
    centerpoint_rows,
    wall_bss20,
    wall_bss12,
):
    stage3_results, width, height = [], 0, 0
    name_center = _build_name_centers(lines)
    floor_zs = [f.get("z", 0) for f in floor]
    top_twofloor_z = heapq.nlargest(2, floor_zs) if floor_zs else []
    lowest_floor = abs(min(floor_zs, default=0))
    storey_min_height = min((s.get("elevation", 0) for s in storeys), default=0)
    wall_finishes_lowest_height = min((w.get("z", 0) for w in wall_bss20), default=0)
    combined_walls = wall_bss20 + wall_bss12
    shower_walls = [
        w for w in combined_walls if w.get("z", 0) == wall_finishes_lowest_height
    ]
    glass_x_pos = glass_walls[0]["x"] if glass_walls else None
    walls_len = len(walls)
    rows_by_wall = {r["Wall Number"]: r for r in centerpoint_rows}
    for line in lines:
        if name_center.get(line["name"], (None, None, 0))[2] > 1:
            lx, ly = name_center[line["name"]][:2]
        else:
            lx = line.get("CenterX_local")
            ly = line.get("CenterY_local")
            if lx is None or ly is None:
                lx = (line["StartX_local"] + line["EndX_local"]) * 0.5
                ly = (line["StartY_local"] + line["EndY_local"]) * 0.5
        lz = line["CenterZ_local"]
        min_dist, nearestwallindex = float("inf"), None
        nearest_wall_data = None
        for i, wall_dict in enumerate(walls):
            wdat = next(iter(wall_dict.values()))
            wx, wy, axis = wdat["x"], wdat["y"], wdat["axis"]
            dist = abs((ly - wy) if axis == "X" else (lx - wx))
            if walls_len == 6 and i > 0 and glass_x_pos is not None and top_twofloor_z:
                cond = (count_minus_y == 2 and wx < glass_x_pos) or (
                    count_plus_y == 2 and wx > glass_x_pos
                )
                if cond:
                    row = rows_by_wall.get(i + 1)
                    if row is not None:
                        row["floortileheight"] = 1000 + lowest_floor + top_twofloor_z[0]
            if dist < min_dist:
                min_dist = dist
                nearestwallindex = i + 1
                nearest_wall_data = wdat
        if nearestwallindex is None:
            nearestwallindex = "F"
        if lz >= storey_min_height:
            continue
        else:
            choose_floor = False
            if nearest_wall_data in shower_walls:
                z0 = nearest_wall_data.get("z", 0)
                thickness = nearest_wall_data.get("area", (0, 0, 0))[1]
                if z0 <= lz <= (z0 + thickness):
                    choose_floor = True
            if lz < 0:
                choose_floor = True
            if choose_floor:
                nearestwallindex = "F"
        match = next(
            (w for w in wall_info if w["Wall Number"] == nearestwallindex), None
        )
        wall_info_axis = None
        if match:
            width, height = match["Width"], match["Height"]
            wall_info_axis = match.get("Axis", None)
        else:
            width, height = (0, 0) if nearestwallindex == "F" else (width, height)
        length = line["EndX_local"] - line["StartX_local"] if wall_info_axis == "X" else line["EndY_local"] - line["StartY_local"]
        stage3_results.append(
            {
                "Wall Number": nearestwallindex,
                "Name": line["name"],
                "Type": "line",
                "SGX": line["StartX_local"],
                "SGY": line["StartY_local"],
                "SGZ": line["StartZ_local"],
                "EGX": line["EndX_local"],
                "EGY": line["EndY_local"],
                "EGZ": line["EndZ_local"],
                "Length": length,
            }
        )
    return stage3_results


def compare_width_y(walls_facing_y, internal_y_width, count_plus_y, count_minus_y):
    for i in range(len(walls_facing_y)):
        wall_i = walls_facing_y[i]
        xi = wall_i["area"][0]
        for j in range(i + 1, len(walls_facing_y)):
            wall_j = walls_facing_y[j]
            xj = wall_j["area"][0]
            if xi > xj:
                if count_minus_y == 2:
                    internal_y_width[0], internal_y_width[1] = (
                        internal_y_width[1],
                        internal_y_width[0],
                    )
                elif count_plus_y == 2:
                    internal_y_width[-2], internal_y_width[-1] = (
                        internal_y_width[-1],
                        internal_y_width[-2],
                    )
                return internal_y_width
            elif xi < xj:
                return internal_y_width
            else:
                return internal_y_width


def get_internal_width(walls, startingwall, wall20, wall12):
    xwidths, ywidths, min_heights = [], [], []
    for wall in walls:
        area, axis = wall["area"], wall["axis"]
        width, height, ____ = area
        min_heights.append(height)
        if axis == "X":
            xwidths.append(width)
        else:
            ywidths.append(width)
    min_height_value = min(min_heights) if min_heights else None
    internalx_width, internaly_width = 0, 0
    xwidths_sorted = sorted(xwidths, reverse=True)
    ywidths_sorted = sorted(ywidths, reverse=True)
    internal_x_width, internal_y_width = [], []
    external_x_width, external_y_width = 0, 0
    if max(xwidths) > max(ywidths):
        starting_area = startingwall["area"]
        xstarting, height50, ___ = starting_area
        if xstarting >= max(xwidths):
            internalx_width = max(xwidths)
            internaly_width = max(ywidths)
        else:
            internalx_width = min(xwidths)
            internaly_width = min(ywidths)
        height = max(w["area"][1] for w in wall20)
        internalx_width = (internalx_width / 2) - height
        external_x_width = (internalx_width + height + height50) * 2
        if height50 + height > min_height_value + height:
            external_x_width = (internalx_width + height50) * 2
        external_y_width = max(ywidths)
        internaly_width = identifywall12(wall12, wall20, external_y_width, height50)
        internal_x_width, internal_y_width = identifyinternal(
            wall20,
            walls,
            height50,
            internalx_width,
            internaly_width,
            xwidths_sorted,
            ywidths_sorted,
        )
        xwidths_sorted[1] += height50
        ywidths_sorted[1] += height50
        xwidths_sorted[0] += height50 * 2
    elif max(ywidths) > max(xwidths):
        starting_area = startingwall["area"]
        height = max(w["area"][1] for w in wall20)
        y_starting, height50, ___ = starting_area
        if y_starting >= max(ywidths):
            internaly_width = max(ywidths)
        else:
            internaly_width = min(ywidths)
        internaly_width = (internaly_width / 2) - height
        max_x_width = max(xwidths)
        internalx_width = identifywall12(wall12, wall20, max_x_width, height50)
        external_y_width = (internal_y_width + height50 + height) * 2
        external_x_width = max_x_width
        internal_x_width, internal_y_width = identifyinternal(
            wall20,
            walls,
            height50,
            internalx_width,
            internaly_width,
            xwidths_sorted,
            ywidths_sorted,
        )
        xwidths_sorted[1] += height50
        ywidths_sorted[1] += height50
        ywidths_sorted[0] += height50 * 2
    return (
        round(internalx_width),
        round(internaly_width),
        round(internalx_width) * 2,
        round(internaly_width) * 2,
        internal_x_width,
        internal_y_width,
        external_x_width,
        external_y_width,
        xwidths_sorted,
        ywidths_sorted,
    )


def identifyinternal(
    wall20,
    walls,
    height50,
    internalx_width,
    internaly_width,
    xwidths_sorted,
    ywidths_sorted,
):
    internal_x_width, internal_y_width, n = [], [], len(walls)
    if n == 6:
        h20 = max((w["area"][1] for w in wall20), default=0)
        x2 = xwidths_sorted[1] if len(xwidths_sorted) > 1 else 0
        y2 = ywidths_sorted[1] if len(ywidths_sorted) > 1 else 0
        second_x = x2 - (h20 * 2) - height50
        last_x = (internalx_width * 2) - second_x
        second_y = y2 - (h20 * 2) - height50
        last_y = (internaly_width * 2) - second_y
        internal_x_width = [round(internalx_width * 2), round(second_x), round(last_x)]
        internal_y_width = [round(internaly_width * 2), round(second_y), round(last_y)]
    elif n == 4:
        internal_x_width = [round(internalx_width * 2)]
        internal_y_width = [round(internaly_width * 2)]
    return internal_x_width, internal_y_width


def identifywall12(wall12, wall20, maxwidth, height50):
    height20 = max(w["area"][1] for w in wall20)
    if wall12:
        height12 = max(w["area"][1] for w in wall12)
        maxwidth = (maxwidth - (height50 * 2) - height20 - height12) / 2
    else:
        maxwidth = maxwidth / 2 - height50
    return maxwidth


def compute_area_from_vertices(obj):
    vertices = obj["vertices"]
    if len(vertices) == 0:
        return (0, 0, 0)
    width, depth, height = vertices.ptp(axis=0)
    return (width, depth, height)


def applyexternal(row, internalmax_width, walls):
    width, height = row["Width"], row["Height"]
    internal_map = {
        d["Wall Number"]: float(d["Internal Max Width"])
        for d in internalmax_width
    }
    max_x_width = max(float(d["Internal Max Width"]) for d in internalmax_width if str(d["Axis"]).upper() == "X")
    max_y_width = max(float(d["Internal Max Width"]) for d in internalmax_width if str(d["Axis"]).upper() == "Y")
    wall_number, name = row["Wall Number"], str(row.get("Name", "")).lower()
    if ("basic wall" in name) or ("floor" in name) or ("box-up" in name):
        return pd.Series([width, height])
    if isinstance(wall_number, int):
        width = internal_map.get(wall_number, width)
    for i, wall_dict in enumerate(walls):
        height = list(wall_dict.values())[0]["area"][2]
    if wall_number == "F":
        width, height = max_x_width, max_y_width
    return pd.Series([width, height])

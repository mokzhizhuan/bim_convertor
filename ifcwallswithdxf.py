from pathlib import Path
import re, math, statistics
import pandas as pd

IFC_PATH = Path("TERRAHL2-FP-MB-T1am(JMB).ifc")
DXF_PATH = Path("TERRAHL2-FP-MB-T1am(JMB)-A88.dxf")


# -------------------- IFC parsing helpers --------------------
def read_ifc_statements(path: Path):
    stmts = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        buf = []
        in_str = False
        for line in f:
            s = line.rstrip("\n\r")
            i = 0
            while i < len(s):
                ch = s[i]
                if ch == "'":
                    if in_str and i + 1 < len(s) and s[i + 1] == "'":
                        buf.append("''")
                        i += 2
                        continue
                    in_str = not in_str
                    buf.append(ch)
                    i += 1
                    continue
                if ch == ";" and not in_str:
                    buf.append(ch)
                    stmts.append("".join(buf))
                    buf = []
                    i += 1
                    continue
                buf.append(ch)
                i += 1
            buf.append("\n")
        if buf:
            tail = "".join(buf).strip()
            if tail:
                stmts.append("".join(buf))
    return stmts


def parse_entity(stmt: str):
    m = re.match(
        r"\s*#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;\s*$",
        stmt,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper(), m.group(3)


def split_top_level_commas(s: str):
    parts, depth, cur, in_str = [], 0, [], False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "'":
            if in_str and i + 1 < len(s) and s[i + 1] == "'":
                cur.append("''")
                i += 2
                continue
            in_str = not in_str
            cur.append(ch)
            i += 1
            continue
        if not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth > 0:
                    depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(cur).strip())
                cur = []
                i += 1
                continue
        cur.append(ch)
        i += 1
    parts.append("".join(cur).strip())
    return parts


def unquote(s: str):
    s = s.strip()
    if s == "$":
        return None
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


# Parse IFC
stmts = read_ifc_statements(IFC_PATH)

# Maps
cart = {}  # IfcCartesianPoint id -> (x,y,z)
polyline_points = {}  # IfcPolyline id -> [pt ids]
ax2p3_loc = {}  # IfcAxis2Placement3D id -> location point id
localplace = (
    {}
)  # IfcLocalPlacement id -> (relative_to_localplacement_id or None, axis2place3d_id)
shaperep = {}  # IfcShapeRepresentation id -> dict(identifier, type, items=[ids])
proddef = {}  # IfcProductDefinitionShape id -> [representation ids]

walls = {}  # wall id -> dict + raw args
rel_type = {}  # wall id -> type id
wall_types = {}  # type id -> dict(name, predefined)
rel_props = {}  # wall id -> set(pset ids)
psets = {}  # pset id -> dict(name, prop ids)
prop_single = {}  # prop id -> dict(name, value)

for st in stmts:
    pe = parse_entity(st)
    if not pe:
        continue
    eid, etype, args = pe

    if etype == "IFCCARTESIANPOINT":
        parts = (
            split_top_level_commas(args.strip()[1:-1])
            if args.strip().startswith("(")
            else split_top_level_commas(args)
        )
        # There are two forms: (x,y,z) or nested ((x,y,z))
        nums = re.findall(r"[-+]?\d*\.\d+|[-+]?\d+", args)
        if nums:
            vals = [float(v) for v in nums]
            if len(vals) == 2:
                vals.append(0.0)
            cart[eid] = tuple(vals[:3])

    elif etype == "IFCPOLYLINE":
        fields = split_top_level_commas(args)
        ptlist = fields[0] if fields else ""
        ids = [int(x) for x in re.findall(r"#(\d+)", ptlist)]
        polyline_points[eid] = ids

    elif etype == "IFCAXIS2PLACEMENT3D":
        fields = split_top_level_commas(args)
        loc_field = fields[0] if fields else ""
        m = re.match(r"#(\d+)", loc_field.strip())
        if m:
            ax2p3_loc[eid] = int(m.group(1))

    elif etype == "IFCLOCALPLACEMENT":
        fields = split_top_level_commas(args)
        relto = fields[0].strip() if len(fields) > 0 else "$"
        r = re.match(r"#(\d+)", relto)
        relto_id = int(r.group(1)) if r else None
        relpl = fields[1].strip() if len(fields) > 1 else "$"
        m2 = re.match(r"#(\d+)", relpl)
        ax_id = int(m2.group(1)) if m2 else None
        localplace[eid] = (relto_id, ax_id)

    elif etype == "IFCSHAPEREPRESENTATION":
        fields = split_top_level_commas(args)
        repid = unquote(fields[1]) if len(fields) > 1 else None
        reptype = unquote(fields[2]) if len(fields) > 2 else None
        items = [
            int(x) for x in re.findall(r"#(\d+)", fields[3] if len(fields) > 3 else "")
        ]
        shaperep[eid] = {
            "identifier": (repid or "").strip(),
            "type": (reptype or "").strip(),
            "items": items,
        }

    elif etype == "IFCPRODUCTDEFINITIONSHAPE":
        fields = split_top_level_commas(args)
        reps = [
            int(x) for x in re.findall(r"#(\d+)", fields[2] if len(fields) > 2 else "")
        ]
        proddef[eid] = reps

    elif etype in ("IFCWALL", "IFCWALLSTANDARDCASE"):
        fields = split_top_level_commas(args)
        name = unquote(fields[2]) if len(fields) > 2 else None
        objtype = unquote(fields[4]) if len(fields) > 4 else None
        walls[eid] = {
            "Name": name,
            "ObjectType": objtype,
            "Entity": etype,
            "args": args,
        }

    elif etype == "IFCRELDEFINESBYTYPE":
        fields = split_top_level_commas(args)
        if len(fields) >= 7:
            related = fields[5].strip()
            m = re.findall(r"#(\d+)", related)
            relating = fields[6].strip()
            mtype = re.match(r"#(\d+)", relating)
            if m and mtype:
                tid = int(mtype.group(1))
                for wid_s in m:
                    rel_type[int(wid_s)] = tid

    elif etype == "IFCWALLTYPE":
        fields = split_top_level_commas(args)
        name = unquote(fields[2]) if len(fields) > 2 else None
        predefined = None
        if fields:
            last = fields[-1].strip()
            if last.startswith(".") and last.endswith("."):
                predefined = last.strip(".").upper()
        wall_types[eid] = {"TypeName": name, "PredefinedType": predefined}

    elif etype == "IFCRELDEFINESBYPROPERTIES":
        fields = split_top_level_commas(args)
        if len(fields) >= 6:
            related = fields[5].strip()
            relps = fields[4].strip()
            objs = re.findall(r"#(\d+)", related)
            mps = re.match(r"#(\d+)", relps)
            if objs and mps:
                pid = int(mps.group(1))
                for wid_s in objs:
                    rel_props.setdefault(int(wid_s), set()).add(pid)

    elif etype == "IFCPROPERTYSET":
        fields = split_top_level_commas(args)
        pname = unquote(fields[2]) if len(fields) > 2 else None
        hasprops = fields[4] if len(fields) > 4 else ""
        prop_ids = [int(x) for x in re.findall(r"#(\d+)", hasprops)]
        psets[eid] = {"Name": pname, "PropIds": prop_ids}

    elif etype == "IFCPROPERTYSINGLEVALUE":
        fields = split_top_level_commas(args)
        pname = unquote(fields[0]) if len(fields) > 0 else None
        nominal = fields[2] if len(fields) > 2 else None
        val = None
        if nominal:
            m = re.search(r"\(\s*'([^']*(?:''[^']*)*)'\s*\)", nominal, re.IGNORECASE)
            if m:
                val = m.group(1).replace("''", "'")
            else:
                uq = unquote(nominal)
                if uq is not None:
                    val = uq
        prop_single[eid] = {"Name": pname, "Value": val}


# Resolve wall placements and axis centers
def world_translation_from_localplacement(lp_id):
    # Sum locations up the placement chain (ignore rotations)
    tx = ty = tz = 0.0
    seen = set()
    cur = lp_id
    while cur and cur not in seen:
        seen.add(cur)
        relto, ax_id = localplace.get(cur, (None, None))
        if ax_id in ax2p3_loc:
            pt_id = ax2p3_loc[ax_id]
            if pt_id in cart:
                x, y, z = cart[pt_id]
                tx += x
                ty += y
                tz += z
        cur = relto
    return tx, ty, tz


# Find for each wall: its IfcProductDefinitionShape and IfcLocalPlacement
wall_geom = []
for wid, winfo in walls.items():
    args = winfo["args"]
    # find any referenced IfcLocalPlacement id
    lp_id = None
    for m in re.finditer(r"#(\d+)", args):
        rid = int(m.group(1))
        if rid in localplace:
            lp_id = rid
            break
    # find any referenced IfcProductDefinitionShape id
    pds_id = None
    for m in re.finditer(r"#(\d+)", args):
        rid = int(m.group(1))
        if rid in proddef:
            pds_id = rid
            break

    cx = cy = cz = None
    axis_len = None
    if pds_id is not None:
        reps = proddef.get(pds_id, [])
        # pick first Axis rep with Curve2D and a polyline
        axis_poly = None
        for rep_id in reps:
            rep = shaperep.get(rep_id, {})
            if (
                rep.get("identifier", "").lower() == "axis"
                and "curve" in rep.get("type", "").lower()
            ):
                # find first polyline item
                for it in rep.get("items", []):
                    if it in polyline_points:
                        axis_poly = it
                        break
            if axis_poly is not None:
                break
        if axis_poly is not None:
            pts_ids = polyline_points[axis_poly]
            pts = [cart.get(pid) for pid in pts_ids if pid in cart]
            pts = [
                (x, y, z if z is not None else 0.0)
                for (x, y, *rest) in pts
                for z in [rest[0] if rest else 0.0]
            ]
            print(pts)
            if pts:
                # centroid of axis polyline = mean of vertices
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                cz = sum(p[2] for p in pts) / len(pts)
                # length along polyline
                L = 0.0
                for i in range(1, len(pts)):
                    dx = pts[i][0] - pts[i - 1][0]
                    dy = pts[i][1] - pts[i - 1][1]
                    L += math.hypot(dx, dy)
                axis_len = L

    # apply placement translation
    if cx is not None and lp_id is not None:
        tx, ty, tz = world_translation_from_localplacement(lp_id)
        cx += tx
        cy += ty
        cz += tz

    wall_geom.append(
        {
            "WallId": wid,
            "AxisCenterX": cx,
            "AxisCenterY": cy,
            "AxisCenterZ": cz,
            "AxisLength": axis_len,
            "LocalPlacement": lp_id,
            "PDS": pds_id,
        }
    )

df_ifc_geom = pd.DataFrame(wall_geom)

# Build IFC metadata table (as before)
rows_meta = []
for wid, winfo in walls.items():
    t_id = rel_type.get(wid)
    t = wall_types.get(t_id, {})
    pset_ref = None
    for psid in rel_props.get(wid, set()):
        pset = psets.get(psid)
        if not pset:
            continue
        if (pset.get("Name") or "").strip().lower() == "pset_wallcommon":
            for prop_id in pset.get("PropIds", []):
                p = prop_single.get(prop_id, {})
                if (p.get("Name") or "").strip().lower() == "reference":
                    pset_ref = p.get("Value")
                    break
        if pset_ref:
            break
    name = winfo.get("Name") or ""
    msz = re.search(r"\((\d+)\s*[xX]\s*(\d+)\s*mm\)", name)
    tile = f"({msz.group(1)}x{msz.group(2)}mm)" if msz else None

    rows_meta.append(
        {
            "WallId": wid,
            "Entity": winfo.get("Entity"),
            "WallName": name,
            "ObjectType": winfo.get("ObjectType"),
            "TypeId": t_id,
            "TypeName": t.get("TypeName"),
            "PredefinedType": t.get("PredefinedType"),
            "Pset_WallCommon.Reference": pset_ref,
            "TileSizeHint": tile,
        }
    )
df_ifc_meta = pd.DataFrame(rows_meta)

df_ifc = df_ifc_meta.merge(df_ifc_geom, on="WallId", how="left")


# -------------------- DXF HATCH parsing for wall layers --------------------
def load_dxf_pairs(path: Path):
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        lines = [line.rstrip("\n\r") for line in f]
    pairs = []
    i = 0
    while i + 1 < len(lines):
        code = lines[i].strip()
        value = lines[i + 1]
        pairs.append((code, value))
        i += 2
    return pairs


pairs = load_dxf_pairs(DXF_PATH)

# Entities as (etype, start, end)
entities = []
j = 0
while j < len(pairs):
    code, value = pairs[j]
    if code == "0":
        etype = value.strip()
        start = j
        k = j + 1
        while k < len(pairs) and pairs[k][0] != "0":
            k += 1
        entities.append((etype, start, k))
        j = k
    else:
        j += 1


def polygon_centroid_area(points):
    # Shoelace for centroid of a non-self-intersecting polygon
    if len(points) < 3:
        return (
            (
                sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points),
                0.0,
            )
            if points
            else (None, None, 0.0)
        )
    A = 0.0
    Cx = 0.0
    Cy = 0.0
    for i in range(len(points)):
        x1, y1 = points[i][:2]
        x2, y2 = points[(i + 1) % len(points)][:2]
        cross = x1 * y2 - x2 * y1
        A += cross
        Cx += (x1 + x2) * cross
        Cy += (y1 + y2) * cross
    A *= 0.5
    if abs(A) < 1e-9:
        # fallback to mean
        return (
            sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points),
            0.0,
        )
    Cx /= 6 * A
    Cy /= 6 * A
    return (Cx, Cy, abs(A))


wall_hatches = []
for etype, a, b in entities:
    if etype != "HATCH":
        continue
    layer = None
    handle = None
    pattern = None
    for code, val in pairs[a:b]:
        if code == "8":
            layer = val.strip()
        elif code == "5":
            handle = val.strip()
        elif code == "2":
            pattern = val.strip()
    if not layer or "WALL" not in layer.upper():
        continue
    # collect boundary vertices using 93
    k = a
    loop_id = 0
    while k < b:
        code, val = pairs[k]
        if code == "93":
            try:
                nverts = int(val.strip())
            except:
                nverts = 0
            if nverts > 0:
                verts = []
                x = y = z = None
                got = 0
                m = k + 1
                while m < b and got < nverts:
                    c2, v2 = pairs[m]
                    if c2 == "10":
                        try:
                            x = float(v2.strip())
                        except:
                            x = None
                    elif c2 == "20":
                        try:
                            y = float(v2.strip())
                        except:
                            y = None
                    elif c2 == "30":
                        try:
                            z = float(v2.strip())
                        except:
                            z = 0.0
                    if x is not None and y is not None:
                        verts.append((x, y, 0.0 if z is None else z))
                        got += 1
                        x = y = z = None
                    m += 1
                if verts:
                    loop_id += 1
                    cx, cy, area = polygon_centroid_area(verts)
                    wall_hatches.append(
                        {
                            "HatchHandle": handle,
                            "Layer": layer,
                            "Pattern": pattern or "",
                            "LoopID": loop_id,
                            "CentroidX": cx,
                            "CentroidY": cy,
                            "Area": area,
                        }
                    )
                k = m
                continue
        k += 1

df_dxf = pd.DataFrame(wall_hatches)
out_csv = Path("dxf_wall_hatches.csv")
df_dxf.to_csv(out_csv, index=False)

# -------------------- Unit normalization --------------------
if not df_ifc.empty and not df_dxf.empty:
    ifc_median = statistics.median(
        [abs(x) for x in df_ifc["AxisCenterX"].dropna().tolist() if x is not None]
        or [1.0]
    )
    dxf_median = statistics.median(
        [abs(x) for x in df_dxf["CentroidX"].dropna().tolist() if x is not None]
        or [1.0]
    )
    scale = 1.0
    if ifc_median > 0 and dxf_median > 0:
        ratio = dxf_median / ifc_median
        # If ratio is close to 1000, scale IFC up (m -> mm)
        if 800 <= ratio <= 1200:
            scale = 1000.0
    # apply scale
    if scale != 1.0:
        df_ifc["AxisCenterX"] = df_ifc["AxisCenterX"] * scale
        df_ifc["AxisCenterY"] = df_ifc["AxisCenterY"] * scale
        df_ifc["AxisCenterZ"] = df_ifc["AxisCenterZ"] * scale


# -------------------- Nearest neighbor join --------------------
def nearest_dxf(x, y, df):
    best = None
    bestd = None
    for idx, r in df.iterrows():
        cx, cy = r["CentroidX"], r["CentroidY"]
        if pd.isna(cx) or pd.isna(cy):
            continue
        d = math.hypot(cx - x, cy - y)
        if best is None or d < bestd:
            best, bestd = idx, d
    return (best, bestd)


joined_rows = []
if not df_ifc.empty and not df_dxf.empty:
    for idx, w in df_ifc.iterrows():
        x, y = w["AxisCenterX"], w["AxisCenterY"]
        if pd.isna(x) or pd.isna(y):
            continue
        jidx, dist = nearest_dxf(x, y, df_dxf)
        if jidx is None:
            continue
        drow = df_dxf.loc[jidx]
        joined_rows.append(
            {
                **w.to_dict(),
                "NearestHatchHandle": drow["HatchHandle"],
                "NearestHatchLayer": drow["Layer"],
                "NearestHatchPattern": drow["Pattern"],
                "NearestHatchLoop": drow["LoopID"],
                "NearestHatchCentroidX": drow["CentroidX"],
                "NearestHatchCentroidY": drow["CentroidY"],
                "NearestHatchArea": drow["Area"],
                "NearestDistance": dist,
            }
        )

df_join = pd.DataFrame(joined_rows)

out_csv = Path("ifc_walls__joined_to_dxf_wall_hatches.csv")
df_join.to_csv(out_csv, index=False)

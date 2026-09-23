# Regenerate a full table of Model Lines where the geometry is inside IFcGeometricCurveSet,
# descending to pull out IFCPOLYLINE items; compute WORLD coordinates via placement chain.
from pathlib import Path
import re
import math


def getannotation(ifc_file):
    IFC_PATH = Path(ifc_file)
    txt = IFC_PATH.read_text(encoding="utf-8", errors="ignore")
    records = {}
    buf = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s:
            continue
        buf.append(s)
        if s.endswith(";"):
            block = " ".join(buf)
            buf = []
            m = re.match(
                r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\);",
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if m:
                rid = int(m.group(1))
                rtype = m.group(2).upper()
                args = m.group(3).strip()
                records[rid] = (rtype, args)

    def split_top_level_commas(s: str):
        out = []
        cur = []
        depth = 0
        for ch in s:
            if ch == "(":
                depth += 1
                cur.append(ch)
            elif ch == ")":
                depth -= 1
                cur.append(ch)
            elif ch == "," and depth == 0:
                out.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        if cur:
            out.append("".join(cur).strip())
        return out

    def strip_outer_parens(s: str):
        s = s.strip()
        if s.startswith("(") and s.endswith(")"):
            depth = 0
            ok = True
            for ch in s:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth < 0:
                        ok = False
                        break
            if ok and depth == 0:
                return s[1:-1].strip()
        return s

    def parse_ref(tok: str):
        m = re.match(r"#(\d+)$", tok.strip())
        return int(m.group(1)) if m else None

    def parse_string(tok: str):
        m = re.match(r"'(.*)'$", tok.strip())
        return m.group(1) if m else None

    def coords_from_point_id(pid: int):
        rec = records.get(pid)
        if not rec or rec[0] != "IFCCARTESIANPOINT":
            return None
        inner = strip_outer_parens(rec[1])
        inner = strip_outer_parens(inner)
        nums = [float(x) for x in split_top_level_commas(inner)]
        if len(nums) == 2:
            nums.append(0.0)
        return tuple(nums[:3])

    item_to_layers = {}
    for rid, (rtype, args) in records.items():
        if rtype == "IFCPRESENTATIONLAYERASSIGNMENT":
            parts = split_top_level_commas(args)
            name = parse_string(parts[0]) if parts else None
            if len(parts) >= 3:
                items_list = strip_outer_parens(parts[2])
                for tok in split_top_level_commas(items_list):
                    ref = parse_ref(tok)
                    if ref:
                        item_to_layers.setdefault(ref, []).append(name)

    rows = []

    for ann_id, (rtype, args) in records.items():
        if rtype != "IFCANNOTATION":
            continue
        parts = split_top_level_commas(args)
        name = parse_string(parts[2]) if len(parts) >= 3 else None
        if not (name and name.lower().startswith("model lines:")):
            continue
        gid = parse_string(parts[0]) if parts else None
        objtype = parse_string(parts[4]) if len(parts) >= 5 else "Model Lines"

        pds_id = None
        for tok in parts:
            ref = parse_ref(tok)
            if ref and records.get(ref, (None, None))[0] == "IFCPRODUCTDEFINITIONSHAPE":
                pds_id = ref
                break
        if not pds_id:
            continue

        _, pds_args = records[pds_id]
        pds_parts = split_top_level_commas(pds_args)
        reps_list = strip_outer_parens(pds_parts[2]) if len(pds_parts) >= 3 else ""
        rep_ids = [
            parse_ref(t) for t in split_top_level_commas(reps_list) if parse_ref(t)
        ]

        for srid in rep_ids:
            stype, sargs = records.get(srid, (None, None))
            if stype != "IFCSHAPEREPRESENTATION":
                continue
            sra = split_top_level_commas(sargs)
            items_list = strip_outer_parens(sra[3]) if len(sra) >= 4 else ""
            item_ids = [
                parse_ref(t) for t in split_top_level_commas(items_list) if parse_ref(t)
            ]

            for iid in item_ids:
                itype, iargs = records.get(iid, (None, None))
                if itype == "IFCPOLYLINE":
                    iparts = split_top_level_commas(iargs)
                    pts_list = strip_outer_parens(iparts[0]) if iparts else ""
                    pt_ids = [
                        parse_ref(t.strip())
                        for t in split_top_level_commas(pts_list)
                        if parse_ref(t.strip())
                    ]
                    if len(pt_ids) >= 2:
                        p0 = coords_from_point_id(pt_ids[0])
                        p1 = coords_from_point_id(pt_ids[-1])
                        if p0 and p1:
                            L = math.dist(p0, p1)
                            layers = item_to_layers.get(iid)
                            rows.append(
                                {
                                    "AnnotationId": ann_id,
                                    "GlobalId": gid,
                                    "name": name,
                                    "ObjectType": objtype,
                                    "CurveItemType": "IFCPOLYLINE",
                                    "PolylineId": iid,
                                    "LayerNames": ";".join(layers) if layers else None,
                                    "StartX_local": round(p0[0]),
                                    "StartY_local": round(p0[1]),
                                    "StartZ_local": round(p0[2]),
                                    "CenterX_local": round((p0[0] + p1[0]) / 2),
                                    "CenterY_local": round((p0[1] + p1[1]) / 2),
                                    "CenterZ_local": round((p0[2] + p1[2]) / 2),
                                    "EndX_local": round(p1[0]),
                                    "EndY_local": round(p1[1]),
                                    "EndZ_local": round(p1[2]),
                                    "Length_local": round(L),
                                }
                            )
                elif itype == "IFCGEOMETRICCURVESET":
                    parts_geo = split_top_level_commas(iargs)
                    elements = strip_outer_parens(parts_geo[0]) if parts_geo else ""
                    sub_ids = [
                        parse_ref(t)
                        for t in split_top_level_commas(elements)
                        if parse_ref(t)
                    ]
                    for sid in sub_ids:
                        st, sa = records.get(sid, (None, None))
                        if st == "IFCPOLYLINE":
                            iparts = split_top_level_commas(sa)
                            pts_list = strip_outer_parens(iparts[0]) if iparts else ""
                            pt_ids = [
                                parse_ref(t.strip())
                                for t in split_top_level_commas(pts_list)
                                if parse_ref(t.strip())
                            ]
                            if len(pt_ids) >= 2:
                                p0 = coords_from_point_id(pt_ids[0])
                                p1 = coords_from_point_id(pt_ids[-1])
                                if p0 and p1:
                                    L = math.dist(p0, p1)
                                    layers = item_to_layers.get(
                                        sid
                                    ) or item_to_layers.get(iid)
                                    rows.append(
                                        {
                                            "AnnotationId": ann_id,
                                            "GlobalId": gid,
                                            "name": name,
                                            "ObjectType": objtype,
                                            "CurveItemType": "IFCPOLYLINE",
                                            "PolylineId": sid,
                                            "LayerNames": (
                                                ";".join(layers) if layers else None
                                            ),
                                            "StartX_local": round(p0[0]),
                                            "StartY_local": round(p0[1]),
                                            "StartZ_local": round(p0[2]),
                                            "CenterX_local": round((p0[0] + p1[0]) / 2),
                                            "CenterY_local": round((p0[1] + p1[1]) / 2),
                                            "CenterZ_local": round((p0[2] + p1[2]) / 2),
                                            "EndX_local": round(p1[0]),
                                            "EndY_local": round(p1[1]),
                                            "EndZ_local": round(p1[2]),
                                            "Length_local": round(L),
                                        }
                                    )

    return rows

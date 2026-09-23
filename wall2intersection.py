# find_intersections_with_inventory.py
# Robust search for "Model Lines:1475320" + inventory + CSV/XLSX outputs
from __future__ import annotations
import math, csv, os, re
from dataclasses import dataclass
from typing import Iterable, List, Tuple, Optional, Dict, Any
from datetime import datetime

import ifcopenshell

# === CONFIG ===
IFC_PATH = r"TERRAHL2-FP-MB-T1am(JMB)27-8-2025.ifc"
TARGET_NAME = "Model Lines:1475320"
TARGET_NUMBER_HINT = "1475320"  # extracted from the target; keep as string

# Tolerances (mm, degrees)
ANGLE_TOL_DEG = 5.0
DX_ABS_TOL = 1.0
DY_ABS_TOL = 1.0
X_INTERSECT_TOL = 2.0
Y_INTERSECT_TOL = 2.0
Z_CLOSE_TOL = 5.0
EPS = 1e-9
ANGLE_TOL_RAD = math.radians(ANGLE_TOL_DEG)

# === Matrix helpers ===
def mat_identity():
    return [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

def mat_mul(A,B):
    C=[[0]*4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            C[i][j]=sum(A[i][k]*B[k][j] for k in range(4))
    return C

def mat_apply(M, p):
    x,y,z = p
    w = M[3][0]*x + M[3][1]*y + M[3][2]*z + M[3][3]
    if abs(w) < EPS: w = 1.0
    X = (M[0][0]*x + M[0][1]*y + M[0][2]*z + M[0][3]) / w
    Y = (M[1][0]*x + M[1][1]*y + M[1][2]*z + M[1][3]) / w
    Z = (M[2][0]*x + M[2][1]*y + M[2][2]*z + M[2][3]) / w
    return (X,Y,Z)

def axis2placement3d_to_mat(a2p):
    loc = a2p.Location.Coordinates
    Zdir = getattr(a2p, "Axis", None)
    Z = tuple(Zdir.DirectionRatios) if Zdir else (0.0,0.0,1.0)
    R = getattr(a2p, "RefDirection", None)
    X = tuple(R.DirectionRatios) if R else (1.0,0.0,0.0)
    Y = (Z[1]*X[2]-Z[2]*X[1], Z[2]*X[0]-Z[0]*X[2], Z[0]*X[1]-Z[1]*X[0])
    def norm(v):
        m = math.sqrt(sum(c*c for c in v))
        return v if m < EPS else tuple(c/m for c in v)
    X = norm(X); Y = norm(Y); Z = norm(Z)
    M = mat_identity()
    M[0][0],M[0][1],M[0][2],M[0][3] = X[0],Y[0],Z[0],loc[0]
    M[1][0],M[1][1],M[1][2],M[1][3] = X[1],Y[1],Z[1],loc[1]
    M[2][0],M[2][1],M[2][2],M[2][3] = X[2],Y[2],Z[2],(loc[2] if len(loc)>2 else 0.0)
    return M

def local_placement_chain(obj):
    M = mat_identity()
    pl = getattr(obj, "ObjectPlacement", None)
    while pl:
        a2p = pl.RelativePlacement
        M_local = axis2placement3d_to_mat(a2p)
        M = mat_mul(M, M_local)
        pl = getattr(pl, "PlacementRelTo", None)
    return M

# === Segment extraction across likely containers ===
def cp_xyz(cp) -> Tuple[float,float,float]:
    c = cp.Coordinates
    return (c[0], c[1], c[2] if len(c)>2 else 0.0)

def polyline_segments(ipl, M):
    pts = [mat_apply(M, cp_xyz(p)) for p in ipl.Points]
    for i in range(len(pts)-1):
        yield pts[i], pts[i+1]

def trimmed_line_segments(tcv, M):
    base = tcv.BasisCurve
    if not base or not base.is_a("IfcLine"):
        return
    def trim_to_pt(t):
        for x in (t or []):
            if hasattr(x, "Coordinates"):
                return cp_xyz(x)
        return None
    p1 = trim_to_pt(tcv.Trim1)
    p2 = trim_to_pt(tcv.Trim2)
    if p1 and p2:
        yield mat_apply(M, p1), mat_apply(M, p2)

def indexed_polycurve_segments(ipc, M):
    # Conservative: extract straight segments between consecutive points if provided
    pts = []
    if hasattr(ipc, "Points") and ipc.Points and hasattr(ipc.Points, "Coordinates"):
        for cp in ipc.Points.Coordinates:
            pts.append(mat_apply(M, (cp[0], cp[1], cp[2] if len(cp)>2 else 0.0)))
    elif hasattr(ipc, "Points") and ipc.Points and hasattr(ipc.Points, "Points"):
        for cp in ipc.Points.Points:
            pts.append(mat_apply(M, cp_xyz(cp)))
    for i in range(len(pts)-1):
        yield pts[i], pts[i+1]

def get_layer_names(item) -> List[str]:
    names = []
    for la in getattr(item, "LayerAssignment", []) or []:
        nm = getattr(la, "Name", None)
        if nm: names.append(nm)
    return names

def get_style_names(item) -> List[str]:
    out = []
    st = getattr(item, "StyledByItem", []) or []
    if not isinstance(st, (list, tuple)):
        st = [st]
    for sbi in st:
        for psa in getattr(sbi, "Styles", []) or []:
            for stx in getattr(psa, "Styles", []) or []:
                nm = getattr(stx, "Name", None)
                if nm: out.append(nm)
    return out

@dataclass
class Seg:
    a: Tuple[float,float,float]
    b: Tuple[float,float,float]
    owner_id: int
    owner_ifc: str
    name: str
    object_type: str
    tag: str
    layer_names: Tuple[str, ...]
    style_names: Tuple[str, ...]
    item_type: str  # IfcPolyline / IfcTrimmedCurve / IfcIndexedPolyCurve

def collect_all_segments(ifc) -> List[Seg]:
    segs: List[Seg] = []
    # 1) Primary: IfcAnnotation (typical for Revit Model/Detail lines)
    for ann in ifc.by_type("IfcAnnotation"):
        nm = (getattr(ann, "Name", "") or "").strip()
        ot = (getattr(ann, "ObjectType", "") or "").strip()
        tg = (getattr(ann, "Tag", "") or "").strip()
        rep = getattr(ann, "Representation", None)
        if not rep: continue
        M = local_placement_chain(ann)
        for r in rep.Representations or []:
            for it in r.Items or []:
                layers = tuple(get_layer_names(it))
                styles = tuple(get_style_names(it))
                if it.is_a("IfcPolyline"):
                    for a,b in polyline_segments(it, M):
                        segs.append(Seg(a,b,ann.id(),"IfcAnnotation",nm,ot,tg,layers,styles,"IfcPolyline"))
                elif it.is_a("IfcTrimmedCurve"):
                    for a,b in trimmed_line_segments(it, M):
                        segs.append(Seg(a,b,ann.id(),"IfcAnnotation",nm,ot,tg,layers,styles,"IfcTrimmedCurve"))
                elif it.is_a("IfcIndexedPolyCurve"):
                    for a,b in indexed_polycurve_segments(it, M):
                        segs.append(Seg(a,b,ann.id(),"IfcAnnotation",nm,ot,tg,layers,styles,"IfcIndexedPolyCurve"))

    # 2) Fallback: some exports store 2D curves inside IfcGeometricCurveSet under IfcAnnotation or even under IfcProduct reps
    for prod in ifc.by_type("IfcProduct"):
        rep = getattr(prod, "Representation", None)
        if not rep: continue
        M = local_placement_chain(prod)
        nm = (getattr(prod, "Name", "") or "").strip()
        ot = (getattr(prod, "ObjectType", "") or "").strip()
        tg = (getattr(prod, "Tag", "") or "").strip()
        for r in rep.Representations or []:
            for it in r.Items or []:
                # IfcGeometricCurveSet contains a set of curves in Items
                if it.is_a("IfcGeometricCurveSet"):
                    for sub in it.Elements or []:
                        layers = tuple(get_layer_names(sub))
                        styles = tuple(get_style_names(sub))
                        if sub.is_a("IfcPolyline"):
                            for a,b in polyline_segments(sub, M):
                                segs.append(Seg(a,b,prod.id(),prod.is_a(),nm,ot,tg,layers,styles,"IfcPolyline"))
                        elif sub.is_a("IfcTrimmedCurve"):
                            for a,b in trimmed_line_segments(sub, M):
                                segs.append(Seg(a,b,prod.id(),prod.is_a(),nm,ot,tg,layers,styles,"IfcTrimmedCurve"))
                        elif sub.is_a("IfcIndexedPolyCurve"):
                            for a,b in indexed_polycurve_segments(sub, M):
                                segs.append(Seg(a,b,prod.id(),prod.is_a(),nm,ot,tg,layers,styles,"IfcIndexedPolyCurve"))
    return segs

# === Intersection helpers ===
def is_verticalish(a,b) -> bool:
    dx = b[0]-a[0]; dy = b[1]-a[1]
    if abs(dx) <= DX_ABS_TOL and abs(dy) > EPS: return True
    ang = math.atan2(abs(dx), abs(dy))  # 0 = vertical
    return ang <= ANGLE_TOL_RAD

def is_horizontalish(a,b) -> bool:
    dx = b[0]-a[0]; dy = b[1]-a[1]
    if abs(dy) <= DY_ABS_TOL and abs(dx) > EPS: return True
    ang = math.atan2(abs(dy), abs(dx))  # 0 = horizontal
    return ang <= ANGLE_TOL_RAD

def z_close(seg1, seg2, tol=Z_CLOSE_TOL) -> bool:
    z1 = 0.5*(seg1[0][2] + seg1[1][2]); z2 = 0.5*(seg2[0][2] + seg2[1][2])
    return abs(z1 - z2) <= tol

def seg_intersection_2d(a,b,c,d) -> Optional[Tuple[float,float]]:
    (x1,y1),(x2,y2) = (a[0],a[1]), (b[0],b[1])
    (x3,y3),(x4,y4) = (c[0],c[1]), (d[0],d[1])
    denom = (x1-x2)*(y3-y4) - (y1-y2)*(x3-x4)
    if abs(denom) < EPS: return None
    px = ((x1*y2 - y1*x2)*(x3-x4) - (x1-x2)*(x3*y4 - y3*x4)) / denom
    py = ((x1*y2 - y1*x2)*(y3-y4) - (y1-y2)*(x3*y4 - y3*x4)) / denom
    def between(p,a,b,xtol,ytol):
        return (min(a[0],b[0]) - xtol <= p[0] <= max(a[0],b[0]) + xtol and
                min(a[1],b[1]) - ytol <= p[1] <= max(a[1],b[1]) + ytol)
    if (between((px,py),(x1,y1),(x2,y2),X_INTERSECT_TOL,Y_INTERSECT_TOL) and
        between((px,py),(x3,y3),(x4,y4),X_INTERSECT_TOL,Y_INTERSECT_TOL)):
        return (px,py)
    return None

def seg_len(a,b): return math.dist(a,b)
def seg_angle_deg(a,b):
    dx = b[0]-a[0]; dy = b[1]-a[1]
    ang = math.degrees(math.atan2(dy, dx))
    if ang < 0: ang += 180
    return ang
def round3(x): return round(x,3)

# === Matching logic ===
def norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()

def contains_number_hint(fields: List[str], hint: str) -> bool:
    hint = (hint or "").strip()
    if not hint: return False
    for f in fields:
        if hint in (f or ""):
            return True
    return False

def try_match_targets(segs: List[Seg]) -> List[Seg]:
    # 0) exact name
    exact = [s for s in segs if s.name == TARGET_NAME]
    if exact: return exact
    # 1) case/space-insensitive
    tn = norm(TARGET_NAME)
    approx = [s for s in segs if norm(s.name) == tn]
    if approx: return approx
    # 2) number hint across multiple fields (Name, ObjectType, Tag, layer/style names)
    if TARGET_NUMBER_HINT:
        hint = TARGET_NUMBER_HINT
        hint_hits = []
        for s in segs:
            if contains_number_hint([s.name, s.object_type, s.tag], hint):
                hint_hits.append(s)
                continue
            if any(hint in ln for ln in s.layer_names):
                hint_hits.append(s); continue
            if any(hint in sn for sn in s.style_names):
                hint_hits.append(s); continue
        if hint_hits: return hint_hits
    # 3) last resort: anything whose name contains "model lines"
    ml = [s for s in segs if "model" in norm(s.name) and "line" in norm(s.name)]
    return ml

def write_inventory_csv(segs: List[Seg], path="model_line_segments_inventory.csv"):
    cols = ["owner_ifc","owner_id","name","object_type","tag","item_type",
            "a_x","a_y","a_z","b_x","b_y","b_z",
            "layer_names","style_names","length_mm","angle_deg"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for s in segs:
            w.writerow({
                "owner_ifc": s.owner_ifc,
                "owner_id": s.owner_id,
                "name": s.name,
                "object_type": s.object_type,
                "tag": s.tag,
                "item_type": s.item_type,
                "a_x": round3(s.a[0]), "a_y": round3(s.a[1]), "a_z": round3(s.a[2]),
                "b_x": round3(s.b[0]), "b_y": round3(s.b[1]), "b_z": round3(s.b[2]),
                "layer_names": ";".join(s.layer_names),
                "style_names": ";".join(s.style_names),
                "length_mm": round3(seg_len(s.a, s.b)),
                "angle_deg": round3(seg_angle_deg(s.a, s.b)),
            })
    return os.path.abspath(path)

def run_intersections(all_segs: List[Seg], targets: List[Seg]):
    others = [s for s in all_segs if s not in targets]
    rows = []
    for ti, t in enumerate(targets, start=1):
        for s in others:
            if not z_close((t.a,t.b),(s.a,s.b), Z_CLOSE_TOL):
                continue
            ip = seg_intersection_2d(t.a, t.b, s.a, s.b)
            if not ip:
                continue
            vhit = is_verticalish(s.a, s.b)
            hhit = is_horizontalish(s.a, s.b)
            if not (vhit or hhit):
                continue
            hit_type = "vertical" if vhit else "horizontal"
            rows.append({
                "hit_type": hit_type,
                "target_name": t.name, "target_owner": t.owner_ifc, "target_owner_id": t.owner_id,
                "target_a_x": round3(t.a[0]), "target_a_y": round3(t.a[1]), "target_a_z": round3(t.a[2]),
                "target_b_x": round3(t.b[0]), "target_b_y": round3(t.b[1]), "target_b_z": round3(t.b[2]),
                "hit_name": s.name, "hit_owner": s.owner_ifc, "hit_owner_id": s.owner_id,
                "hit_item_type": s.item_type,
                "hit_a_x": round3(s.a[0]), "hit_a_y": round3(s.a[1]), "hit_a_z": round3(s.a[2]),
                "hit_b_x": round3(s.b[0]), "hit_b_y": round3(s.b[1]), "hit_b_z": round3(s.b[2]),
                "intersect_x": round3(ip[0]), "intersect_y": round3(ip[1]),
                "plane_z_mid": round3(0.5*(t.a[2]+t.b[2])),
                "hit_length": round3(seg_len(s.a, s.b)),
                "hit_angle_deg": round3(seg_angle_deg(s.a, s.b)),
                "layers": ";".join(s.layer_names),
                "styles": ";".join(s.style_names),
            })
    # de-dup by hit_owner_id + XY
    seen=set(); dedup=[]
    for r in rows:
        key=(r["hit_type"], r["hit_owner_id"], r["intersect_x"], r["intersect_y"])
        if key in seen: continue
        seen.add(key); dedup.append(r)
    return dedup

def save_results(rows: List[Dict[str,Any]], base_csv, base_xlsx):
    # CSV
    if rows:
        with open(base_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    # XLSX
    made_xlsx=False
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        df_v = df[df["hit_type"]=="vertical"].reset_index(drop=True)
        df_h = df[df["hit_type"]=="horizontal"].reset_index(drop=True)
        with pd.ExcelWriter(base_xlsx, engine="openpyxl") as xw:
            df_v.to_excel(xw, sheet_name="vertical", index=False)
            df_h.to_excel(xw, sheet_name="horizontal", index=False)
        made_xlsx=True
    except Exception as e:
        print(f"[Note] Excel not written ({e}). CSV still created.")
    return made_xlsx

def main():
    ifc = ifcopenshell.open(IFC_PATH)
    all_segs = collect_all_segments(ifc)

    inv_path = write_inventory_csv(all_segs)
    print(f"[Inventory] Wrote: {inv_path}")
    print(f"  Segments found: {len(all_segs)}")

    targets = try_match_targets(all_segs)
    if not targets:
        print(f"[!] Could not auto-find '{TARGET_NAME}' (or number hint {TARGET_NUMBER_HINT}).")
        print("    Open the inventory CSV and pick the exact 'name' you want; then set TARGET_NAME to match.")
        return

    print(f"[OK] Target candidates matched: {len(targets)}")
    # If more than one matched (e.g., multiple segments for the same line), that’s fine.

    rows = run_intersections(all_segs, targets)
    base_csv  = "model_lines_1475320_intersections.csv"
    base_xlsx = "model_lines_1475320_intersections.xlsx"
    made_xlsx = save_results(rows, base_csv, base_xlsx)

    nV = sum(1 for r in rows if r["hit_type"]=="vertical")
    nH = sum(1 for r in rows if r["hit_type"]=="horizontal")
    print(f"Done. {len(rows)} total intersections → {nV} vertical, {nH} horizontal.")
    print(f"CSV: {os.path.abspath(base_csv)}")
    if made_xlsx:
        print(f"XLSX: {os.path.abspath(base_xlsx)}")

if __name__ == "__main__":
    main()

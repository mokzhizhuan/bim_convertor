#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find "Model Lines" that intersect target Model Lines:1472219
- Auto-detects the target's orientation (horizontal/vertical/angled)
- Searches the complementary orientation (H<->V). If angled, checks both.
- Also detects collinear overlaps (e.g., two horizontals at same Z)
- Looser default Z tolerance (±25 mm), adjustable via --z-tol
- Writes CSV with intersection/overlap details

Usage:
  python find_model_line_intersections.py <path_to_ifc> [--out OUTPUT.csv] [--z-tol 25] [--xy-tol 2]

Requires: ifcopenshell
"""

from __future__ import annotations
import sys, math, argparse, csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional, Dict

# --------- Defaults ----------
EPS_LEN = 1e-6
DEFAULT_XY_TOL = 2.0
DEFAULT_Z_TOL = 25.0       # was 5.0 before — now more forgiving
DY_HORIZ_TOL = 2.0
DX_VERT_TOL  = 2.0
PARALLEL_ANGLE_DEG = 5.0   # collinearity/parallel test
TARGET_NAME = "Model Lines:1472219"

# ---------- Basics ----------
@dataclass
class P:
    x: float; y: float; z: float
    def __iter__(self): yield self.x; yield self.y; yield self.z

@dataclass
class Seg:
    name: str
    step_id: int
    a: P
    b: P
    def dir(self) -> Tuple[float,float]:
        return (self.b.x - self.a.x, self.b.y - self.a.y)
    def len2d(self) -> float:
        return math.hypot(self.b.x - self.a.x, self.b.y - self.a.y)
    def midz(self) -> float:
        return 0.5*(self.a.z + self.b.z)

def _norm(v: Tuple[float,float,float]) -> Tuple[float,float,float]:
    x,y,z = v; L = math.sqrt(x*x+y*y+z*z) or 1.0
    return (x/L, y/L, z/L)

def _cross(a, b):
    ax,ay,az = a; bx,by,bz = b
    return (ay*bz-az*by, az*bx-ax*bz, ax*by-ay*bx)

def _axis2placement3d(ap3):
    loc = ap3.Location.Coordinates
    zdir = (0.0,0.0,1.0); xdir = (1.0,0.0,0.0)
    if getattr(ap3, "Axis", None):        zdir = _norm(tuple(ap3.Axis.DirectionRatios))
    if getattr(ap3, "RefDirection", None): xdir = _norm(tuple(ap3.RefDirection.DirectionRatios))
    ydir = _cross(zdir, xdir); xdir = _cross(ydir, zdir)
    xdir = _norm(xdir); ydir = _norm(ydir); zdir = _norm(zdir)
    x,y,z = loc
    return [[xdir[0], ydir[0], zdir[0], x],
            [xdir[1], ydir[1], zdir[1], y],
            [xdir[2], ydir[2], zdir[2], z],
            [0,0,0,1]]

def _mat_mul(A,B):
    out = [[0]*4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            out[i][j] = sum(A[i][k]*B[k][j] for k in range(4))
    return out

def _apply(M, p: P) -> P:
    x = M[0][0]*p.x + M[0][1]*p.y + M[0][2]*p.z + M[0][3]
    y = M[1][0]*p.x + M[1][1]*p.y + M[1][2]*p.z + M[1][3]
    z = M[2][0]*p.x + M[2][1]*p.y + M[2][2]*p.z + M[2][3]
    return P(x,y,z)

def _local_placement_chain(obj):
    M = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    lp = getattr(obj, "ObjectPlacement", None)
    while lp:
        rel = lp.RelativePlacement
        if rel.is_a("IfcAxis2Placement3D"):
            A = _axis2placement3d(rel)
        else:
            loc = rel.Location.Coordinates
            A = [[1,0,0,loc[0]],[0,1,0,loc[1]],[0,0,1,0],[0,0,0,1]]
        M = _mat_mul(A, M)
        lp = getattr(lp, "PlacementRelTo", None)
    return M

# ---------- Item → points ----------
def _pts_of_item(item) -> List[P]:
    pts: List[P] = []
    if item.is_a("IfcPolyline"):
        for cp in item.Points:
            x,y,*rest = cp.Coordinates; z = rest[0] if rest else 0.0
            pts.append(P(float(x), float(y), float(z)))

    elif item.is_a("IfcTrimmedCurve") and item.BasisCurve.is_a("IfcLine"):
        def _trim_to_point(t):
            if t and t[0].is_a("IfcCartesianPoint"):
                c = t[0].Coordinates
                x,y,*rest = c; z = rest[0] if rest else 0.0
                return P(float(x), float(y), float(z))
        p1 = _trim_to_point(item.Trim1); p2 = _trim_to_point(item.Trim2)
        if p1 and p2: pts = [p1, p2]

    elif item.is_a("IfcCompositeCurve"):
        for seg in item.Segments:
            pts.extend(_pts_of_item(seg.ParentCurve))

    elif item.is_a("IfcIndexedPolyCurve"):
        plist = item.Points
        if plist.is_a("IfcCartesianPointList3D"):
            coords = [P(float(x),float(y),float(z)) for x,y,z in plist.CoordList]
        else:
            coords = [P(float(x),float(y),0.0) for x,y in plist.CoordList]
        if item.Segments:
            for seg in item.Segments:
                idxs = list(seg.Segments or seg.PointIndexes or [])
                if len(idxs) >= 2:
                    for i in range(len(idxs)-1):
                        a = coords[idxs[i]-1]; b = coords[idxs[i+1]-1]
                        if math.hypot(b.x-a.x, b.y-a.y) > EPS_LEN: pts.extend([a,b])
        else:
            pts.extend(coords)

    elif item.is_a("IfcGeometricCurveSet") or item.is_a("IfcGeometricSet"):
        for el in item.Elements or []:
            pts.extend(_pts_of_item(el))

    return pts

def _chain_to_segments(pts: List[P]) -> List[Tuple[P,P]]:
    segs = []
    if len(pts) < 2: return segs
    # If ABAB... pairs present, keep as pairs; else chain
    paired = (len(pts) % 2 == 0)
    if paired:
        made = 0
        for i in range(0, len(pts), 2):
            a,b = pts[i], pts[i+1]
            if math.hypot(b.x-a.x, b.y-a.y) > EPS_LEN:
                segs.append((a,b)); made += 1
        if made: return segs
    for i in range(len(pts)-1):
        a,b = pts[i], pts[i+1]
        if math.hypot(b.x-a.x, b.y-a.y) > EPS_LEN:
            segs.append((a,b))
    return segs

def collect_model_line_segments(ifc) -> List[Seg]:
    out: List[Seg] = []
    anns = [a for a in ifc.by_type("IfcAnnotation")]
    total_items = total_segs = 0
    for ann in anns:
        name = (ann.Name or "").strip()
        M = _local_placement_chain(ann)
        reps = getattr(ann, "Representation", None)
        if not reps: continue
        for rep in reps.Representations:
            for item in rep.Items or []:
                total_items += 1
                pts = _pts_of_item(item)
                for a,b in _chain_to_segments(pts):
                    A = _apply(M, a); B = _apply(M, b)
                    if math.hypot(B.x-A.x, B.y-A.y) <= EPS_LEN: continue
                    out.append(Seg(name=name or "IfcAnnotation", step_id=ann.id(), a=A, b=B))
                    total_segs += 1
    print(f"[Diag] IfcAnnotation count: {len(anns)}, items scanned: {total_items}, segments built: {total_segs}")
    names = sorted({(a.Name or '').strip() for a in anns})
    print(f"[Diag] Sample annotation names: {names[:8]}{' ...' if len(names)>8 else ''}")
    return out

# ---------- Orientation & tests ----------
def is_horizontalish(seg: Seg) -> bool:
    return abs(seg.b.y - seg.a.y) <= DY_HORIZ_TOL and seg.len2d() > EPS_LEN

def is_verticalish(seg: Seg) -> bool:
    return abs(seg.b.x - seg.a.x) <= DX_VERT_TOL and seg.len2d() > EPS_LEN

def angle_between(d1: Tuple[float,float], d2: Tuple[float,float]) -> float:
    (ax,ay),(bx,by) = d1,d2
    a = math.atan2(ay,ax); b = math.atan2(by,bx)
    ang = abs(a-b)
    if ang > math.pi: ang = 2*math.pi - ang
    return math.degrees(ang)

def seg_intersection_2d(a: P, b: P, c: P, d: P) -> Optional[Tuple[float,float]]:
    Ax,Ay = a.x, a.y; Bx,By = b.x, b.y
    Cx,Cy = c.x, c.y; Dx,Dy = d.x, d.y
    r_x, r_y = (Bx-Ax), (By-Ay)
    s_x, s_y = (Dx-Cx), (Dy-Cy)
    denom = r_x * s_y - r_y * s_x
    if abs(denom) < 1e-12: return None
    t = ((Cx-Ax)*s_y - (Cy-Ay)*s_x) / denom
    u = ((Cx-Ax)*r_y - (Cy-Ay)*r_x) / denom
    if -1e-6 <= t <= 1+1e-6 and -1e-6 <= u <= 1+1e-6:
        return (Ax + t*r_x, Ay + t*r_y)
    return None

def collinear_overlap(a: Seg, b: Seg, xy_tol: float, ang_tol_deg: float) -> Optional[Tuple[float,float]]:
    # Are they parallel and nearly on the same infinite line, with overlapping projections?
    d1 = a.dir(); d2 = b.dir()
    if a.len2d() <= EPS_LEN or b.len2d() <= EPS_LEN: return None
    ang = min(angle_between(d1,d2), 180.0 - angle_between(d1,d2))
    if ang > ang_tol_deg: return None  # not parallel

    # Line distance test: distance from one endpoint of b to line a ≤ xy_tol
    # Line a: A + t*(B-A)
    Ax,Ay = a.a.x, a.a.y; Bx,By = a.b.x, a.b.y
    vx,vy = (Bx-Ax, By-Ay)
    L2 = vx*vx + vy*vy
    def point_line_dist(x0,y0):
        t = ((x0-Ax)*vx + (y0-Ay)*vy) / (L2 if L2>0 else 1.0)
        px,py = Ax + t*vx, Ay + t*vy
        return math.hypot(x0-px, y0-py)
    if point_line_dist(b.a.x,b.a.y) > xy_tol and point_line_dist(b.b.x,b.b.y) > xy_tol:
        return None

    # 1D overlap on the major axis
    if abs(vx) >= abs(vy):
        a_min, a_max = sorted([a.a.x, a.b.x])
        b_min, b_max = sorted([b.a.x, b.b.x])
    else:
        a_min, a_max = sorted([a.a.y, a.b.y])
        b_min, b_max = sorted([b.a.y, b.b.y])

    left = max(a_min, b_min); right = min(a_max, b_max)
    if right + xy_tol < left:  # no overlap
        return None

    # Return representative mid of the overlap interval on XY (no single “cross” point)
    mid = 0.5*(left + right)
    if abs(vx) >= abs(vy):
        # y is ~constant; use average y of the two closest endpoints
        y_rep = 0.5*( (a.a.y+a.b.y)/2 + (b.a.y+b.b.y)/2 )
        return (mid, y_rep)
    else:
        x_rep = 0.5*( (a.a.x+a.b.x)/2 + (b.a.x+b.b.x)/2 )
        return (x_rep, mid)

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc_path")
    ap.add_argument("--out", help="Output CSV path (optional)")
    ap.add_argument("--z-tol", type=float, default=DEFAULT_Z_TOL)
    ap.add_argument("--xy-tol", type=float, default=DEFAULT_XY_TOL)
    args = ap.parse_args()

    try:
        import ifcopenshell
    except ImportError:
        print("ERROR: pip install ifcopenshell"); sys.exit(2)

    ifc_path = Path(args.ifc_path)
    out_csv = Path(args.out) if args.out else ifc_path.with_name("intersections_ModelLines_1472219.csv")
    if not ifc_path.exists():
        print(f"ERROR: IFC not found: {ifc_path}"); sys.exit(2)

    ifc = ifcopenshell.open(str(ifc_path))
    segs = collect_model_line_segments(ifc)
    if not segs:
        print("No segments found under IfcAnnotation."); sys.exit(0)

    # Gather target segments
    targets = [s for s in segs if s.name.strip() == TARGET_NAME] or [s for s in segs if TARGET_NAME in s.name]
    if not targets:
        print(f"Target '{TARGET_NAME}' not found among annotation names."); sys.exit(0)

    # Classify target orientation (majority vote)
    nH = sum(is_horizontalish(t) for t in targets)
    nV = sum(is_verticalish(t) for t in targets)
    target_mode = "horizontal" if nH >= max(nV, 1) else ("vertical" if nV >= 1 else "angled")
    print(f"[Diag] Target mode: {target_mode} (H={nH}, V={nV}, total segs for target={len(targets)})")

    # Candidate pool (complementary orientation if possible)
    if target_mode == "horizontal":
        pool = [s for s in segs if is_verticalish(s)]
    elif target_mode == "vertical":
        pool = [s for s in segs if is_horizontalish(s)]
    else:
        # angled: check both
        pool = segs[:]

    rows: List[Dict] = []

    for t in targets:
        tz = t.midz()
        for s in pool:
            if s.name == t.name and s.step_id == t.step_id and s.a.x==t.a.x and s.a.y==t.a.y and s.b.x==t.b.x and s.b.y==t.b.y:
                continue  # same exact seg
            sz = s.midz()
            if abs(sz - tz) > args.z_tol:
                # allow collinear horizontals/verticals only if same Z-ish
                # so if Z too far, skip entirely
                continue

            # Try cross intersection first
            xy = seg_intersection_2d(s.a, s.b, t.a, t.b)
            if xy:
                X,Y = xy
                rows.append({
                    "Relation": "cross",
                    "IntersectX": X, "IntersectY": Y, "IntersectZ": 0.5*(sz+tz),
                    "OtherName": s.name, "OtherSTEP": s.step_id,
                    "O_Ax": s.a.x, "O_Ay": s.a.y, "O_Az": s.a.z,
                    "O_Bx": s.b.x, "O_By": s.b.y, "O_Bz": s.b.z,
                    "TargetName": t.name, "TargetSTEP": t.step_id,
                    "T_Ax": t.a.x, "T_Ay": t.a.y, "T_Az": t.a.z,
                    "T_Bx": t.b.x, "T_By": t.b.y, "T_Bz": t.b.z,
                })
                continue

            # If parallel to target, check collinear overlap
            if target_mode in ("horizontal","vertical"):
                d = collinear_overlap(t, s, args.xy_tol, PARALLEL_ANGLE_DEG)
                if d:
                    X,Y = d
                    rows.append({
                        "Relation": "collinear-overlap",
                        "IntersectX": X, "IntersectY": Y, "IntersectZ": 0.5*(sz+tz),
                        "OtherName": s.name, "OtherSTEP": s.step_id,
                        "O_Ax": s.a.x, "O_Ay": s.a.y, "O_Az": s.a.z,
                        "O_Bx": s.b.x, "O_By": s.b.y, "O_Bz": s.b.z,
                        "TargetName": t.name, "TargetSTEP": t.step_id,
                        "T_Ax": t.a.x, "T_Ay": t.a.y, "T_Az": t.a.z,
                        "T_Bx": t.b.x, "T_By": t.b.y, "T_Bz": t.b.z,
                    })

    if not rows:
        print(f"No crossings/overlaps with '{TARGET_NAME}' under Z±{args.z_tol} mm.")
        sys.exit(0)

    # Dedup near-identical XY(Z)
    seen = set(); dedup = []
    for r in rows:
        key = (round(r["IntersectX"]/args.xy_tol), round(r["IntersectY"]/args.xy_tol), round(r["IntersectZ"]/args.z_tol), r["Relation"])
        if key in seen: continue
        seen.add(key); dedup.append(r)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "Relation",
            "IntersectX","IntersectY","IntersectZ",
            "OtherName","OtherSTEP","O_Ax","O_Ay","O_Az","O_Bx","O_By","O_Bz",
            "TargetName","TargetSTEP","T_Ax","T_Ay","T_Az","T_Bx","T_By","T_Bz"
        ])
        w.writeheader(); w.writerows(dedup)

    print(f"Wrote {len(dedup)} results to: {out_csv}")
    print("Tip: if still empty, try a bigger Z window, e.g. --z-tol 60")
    
if __name__ == "__main__":
    main()

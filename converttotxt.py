import ezdxf
import pandas as pd
import re
from pathlib import Path
from math import isfinite

DXF_PATH = "TERRAHL2-FP-MB-T1am(JMB)-A88-Rev01.dxf"  # <- change if needed

WALL_LAYER_REGEX = r"\b(WALL|A-?WALL|WALLS?)\b"
TILE_NAME_HINT = "tile"  # hatch pattern name contains this

def layer_ok(layer_name: str, regex: str | None):
    return True if regex is None else bool(re.search(regex, layer_name, re.IGNORECASE))

def fmt_pts(pts, ndigits=3):
    out = []
    for p in pts:
        if len(p) == 3:
            x, y, z = p
            out.append(f"{round(x, ndigits)} {round(y, ndigits)} {round(z, ndigits)}")
        else:
            x, y = p[:2]
            out.append(f"{round(x, ndigits)} {round(y, ndigits)}")
    return "; ".join(out)

# -------------------------
# Geometry helpers (no deps)
# -------------------------
def _clean_xy(x, y):
    # robust float conversion; DXF can sometimes carry non-finite values
    fx = float(x) if isfinite(float(x)) else 0.0
    fy = float(y) if isfinite(float(y)) else 0.0
    return fx, fy

def point_in_polygon(pt, poly_xy):
    """Ray-casting point in polygon test in XY plane (poly_xy: list[(x,y)])."""
    x, y = pt
    inside = False
    n = len(poly_xy)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = poly_xy[i]
        x2, y2 = poly_xy[(i + 1) % n]
        # Check if point intersects edge
        cond = ((y1 > y) != (y2 > y)) and (
            x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1
        )
        if cond:
            inside = not inside
    return inside

def lwpolyline_xy(e):
    """Return XY vertices for an LWPOLYLINE."""
    return [tuple(_clean_xy(vx[0], vx[1])) for vx in e.get_points()]

def polyline_xy(e):
    """Return XY vertices for a classic POLYLINE by projecting to XY."""
    pts = []
    for v in e.vertices():
        x = v.dxf.location.x
        y = v.dxf.location.y
        pts.append(tuple(_clean_xy(x, y)))
    return pts

def hatch_loop_polylines(e):
    """Yield XY point lists for each loop we can read as polyline-like."""
    loops = []
    for p in e.paths:
        if p.PATH_TYPE == "PolylinePath":
            pts = [tuple(_clean_xy(v[0], v[1])) for v in p.vertices]
            if pts:
                loops.append(pts)
        elif p.PATH_TYPE == "EdgePath":
            # Only line edges; arcs ignored for simplicity
            pts = []
            for edge in p.edges:
                if edge.EDGE_TYPE == "LineEdge":
                    pts.append(tuple(_clean_xy(edge.start[0], edge.start[1])))
                    pts.append(tuple(_clean_xy(edge.end[0], edge.end[1])))
            if pts:
                loops.append(pts)
    return loops

# -------------------------
# Text & block extraction
# -------------------------
def collect_texts(msp):
    """Collect TEXT and MTEXT with their insertion points and content."""
    labels = []
    # TEXT
    for t in msp.query("TEXT"):
        try:
            s = (t.dxf.text or "").strip()
            if not s:
                continue
            px, py = _clean_xy(t.dxf.insert.x, t.dxf.insert.y)
            labels.append({"content": s, "pt": (px, py), "layer": t.dxf.layer, "type": "TEXT"})
        except Exception:
            pass
    # MTEXT
    for mt in msp.query("MTEXT"):
        try:
            s = (mt.text or "").strip()
            if not s:
                continue
            px, py = _clean_xy(mt.dxf.insert.x, mt.dxf.insert.y)
            labels.append({"content": s, "pt": (px, py), "layer": mt.dxf.layer, "type": "MTEXT"})
        except Exception:
            pass
    return labels

FITTING_ATTR_CANDIDATES = ("NAME", "MARK", "TAG", "TYPE", "ID", "NUMBER", "CODE")

def pick_best_attr_name(attribs):
    """Pick first non-empty attribute value from common tags; else None."""
    # attribs: dict(tag -> value)
    for key in FITTING_ATTR_CANDIDATES:
        if key in attribs and attribs[key]:
            v = str(attribs[key]).strip()
            if v:
                return v
    # else maybe take any attribute with non-empty value
    for k, v in attribs.items():
        v = str(v).strip()
        if v:
            return v
    return None

def collect_fittings_from_inserts(msp, texts):
    rows = []
    for e in msp.query("INSERT"):
        try:
            ly = e.dxf.layer
            blkname = (e.dxf.name or "").strip()
            px, py = _clean_xy(e.dxf.insert.x, e.dxf.insert.y)

            attribs = {}
            try:
                for att in e.attribs:
                    tag = (att.dxf.tag or "").strip().upper()
                    val = (att.dxf.text or "").strip()
                    if tag:
                        attribs[tag] = val
            except Exception:
                pass

            name = pick_best_attr_name(attribs) or blkname or ""
            if not name:
                # fallback to nearest label text
                name = nearest_label((px, py), texts, max_dist=1000.0)

            row = {
                "Name": name,
                "Entity": "INSERT",
                "Layer": ly,
                "BlockName": blkname,
                "PosX": px, "PosY": py,
            }
            for k, v in attribs.items():
                row[f"ATT_{k}"] = v
            rows.append(row)
        except Exception:
            pass
    return rows


# -------------------------
# Your original collectors, adapted to use names
# -------------------------

def nearest_label(pt, texts, max_dist=1000.0):
    if not texts:
        return ""
    x, y = pt
    best_text, best_d2 = "", float("inf")
    for lab in texts:
        lx, ly = lab["pt"]
        dx, dy = x - lx, y - ly
        d2 = dx*dx + dy*dy
        if d2 < best_d2 and d2**0.5 <= max_dist:
            best_text, best_d2 = lab["content"], d2
    return best_text

def poly_centroid(pts):
    # pts: [(x,y), ...]
    if not pts:
        return (0.0, 0.0)
    # polygon centroid (robust for closed or open polyline)
    area = 0.0
    cx = 0.0
    cy = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i+1) % n]
        cross = x1*y2 - x2*y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area) < 1e-12:
        # fallback: average
        sx = sum(p[0] for p in pts)
        sy = sum(p[1] for p in pts)
        m = max(1, len(pts))
        return (sx/m, sy/m)
    area *= 0.5
    cx /= (6.0 * area)
    cy /= (6.0 * area)
    return (cx, cy)


def collect_lines(msp, layer_regex, texts):
    rows = []
    for e in msp.query("LINE"):
        try:
            ly = e.dxf.layer
            if not layer_ok(ly, None):
                continue
            s = e.dxf.start
            t = e.dxf.end
            sx, sy = float(getattr(s, "x", 0.0)), float(getattr(s, "y", 0.0))
            tx, ty = float(getattr(t, "x", 0.0)), float(getattr(t, "y", 0.0))
            mx, my = (sx + tx) / 2.0, (sy + ty) / 2.0
            name = nearest_label((mx, my), texts, max_dist=1000.0)

            rows.append({
                "Name": name,
                "Entity": e.dxftype(),
                "Layer": ly,
                "StartX": sx, "StartY": sy, "StartZ": float(getattr(s, "z", 0.0)),
                "EndX":   tx, "EndY":   ty, "EndZ":   float(getattr(t, "z", 0.0)),
            })
        except Exception:
            pass
    return rows

def collect_walls_from_polylines(msp, layer_regex, texts):
    """
    Closed polylines as walls. 'Name' = first TEXT/MTEXT whose insertion point lies inside the polygon.
    """
    rows = []

    # LWPOLYLINE
    for e in msp.query("LWPOLYLINE"):
        try:
            ly = e.dxf.layer
            if not layer_ok(ly, layer_regex):
                continue
            if not e.closed:
                continue
            poly = lwpolyline_xy(e)
            # pick first label inside
            wall_name = ""
            for lab in texts:
                if point_in_polygon(lab["pt"], poly):
                    wall_name = lab["content"]
                    break
            rows.append({
                "Name": wall_name,
                "Entity": "LWPOLYLINE",
                "Layer": ly,
                "Closed": True,
                "VerticesXY": fmt_pts(poly),
                "VertexCount": len(poly),
            })
        except Exception:
            pass

    # POLYLINE
    for e in msp.query("POLYLINE"):
        try:
            ly = e.dxf.layer
            if not layer_ok(ly, layer_regex):
                continue
            if not e.is_closed:
                continue
            poly = polyline_xy(e)
            wall_name = ""
            for lab in texts:
                if point_in_polygon(lab["pt"], poly):
                    wall_name = lab["content"]
                    break
            rows.append({
                "Name": wall_name,
                "Entity": "POLYLINE",
                "Layer": ly,
                "Closed": True,
                "VerticesXYZ": fmt_pts([(x, y, 0.0) for x, y in poly]),
                "VertexCount": len(poly),
            })
        except Exception:
            pass
    return rows

def collect_tiles_from_hatch(msp, layer_regex, name_hint, walls_polys, texts):
    rows = []
    for e in msp.query("HATCH"):
        try:
            ly = e.dxf.layer
            if not layer_ok(ly, None):
                continue
            pname = (e.dxf.pattern_name or "").lower()
            if name_hint and name_hint.lower() not in pname:
                continue
            loops = hatch_loop_polylines(e)
            if not loops:
                continue
            for idx, pts in enumerate(loops, 1):
                # which wall?
                wall_name = ""
                for wp in walls_polys:
                    if point_in_polygon(pts[0], wp["poly"]):
                        inside_count = sum(point_in_polygon(p, wp["poly"]) for p in pts[::max(1, len(pts)//10)])
                        if inside_count >= 1:
                            wall_name = wp["name"]
                            break
                # name: prefer nearest text to loop centroid; else pattern_loop
                cx, cy = poly_centroid(pts)
                label = nearest_label((cx, cy), texts, max_dist=1000.0)
                name = label if label else f"{pname}_loop{idx}"
                rows.append({
                    "Name": name,
                    "Entity": "HATCH",
                    "Layer": ly,
                    "PatternName": pname,
                    "LoopIndex": idx,
                    "LoopVerticesXY": fmt_pts(pts),
                    "LoopVertexCount": len(pts),
                    "WallName": wall_name,
                })
        except Exception:
            pass
    return rows

# -------------------------
# Main
# -------------------------
def main():
    doc = ezdxf.readfile(DXF_PATH)
    msp = doc.modelspace()
    texts = collect_texts(msp)
    wall_rows = collect_walls_from_polylines(msp, layer_regex=WALL_LAYER_REGEX, texts=texts)
    wall_polys = []
    for r in wall_rows:
        if r["Entity"] == "LWPOLYLINE" and r.get("VerticesXY"):
            pts = []
            for token in str(r["VerticesXY"]).split(";"):
                token = token.strip()
                if not token:
                    continue
                sx, sy = token.split()
                pts.append((_clean_xy(float(sx), float(sy))))
            wall_polys.append({"name": r.get("Name", ""), "poly": pts})
    lines_rows = collect_lines(msp, layer_regex=None, texts=texts)
    fittings_rows = collect_fittings_from_inserts(msp, texts=texts)
    tile_rows = collect_tiles_from_hatch(msp, layer_regex=None, name_hint=TILE_NAME_HINT, walls_polys=wall_polys, texts=texts)
    pd.DataFrame(lines_rows).to_csv("lines.csv", index=False, float_format="%.0f")
    pd.DataFrame(wall_rows).to_csv("walls.csv", index=False)
    pd.DataFrame(fittings_rows).to_csv("fittings.csv", index=False)
    pd.DataFrame(tile_rows).to_csv("tiles.csv", index=False)
    print("Wrote: lines.csv, walls.csv, fittings.csv, tiles.csv")



if __name__ == "__main__":
    main()

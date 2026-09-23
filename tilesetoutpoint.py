from pathlib import Path
import math
import numpy as np
import pandas as pd

def getdata(dxffile):
    DXF_PATH = Path(dxffile)
    PHRASE = "BSS_Tile Setting Out Point"

    # --- Load raw lines ---
    with DXF_PATH.open("r", encoding="utf-8", errors="ignore") as f:
        raw = [ln.rstrip("\r\n") for ln in f]
    n = len(raw)

    def is_int(s:str)->bool:
        try:
            int(s.strip()); return True
        except:
            return False

    # --- Parse to (code, value) pairs robustly ---
    pairs = []
    i = 0
    while i < n - 1:
        if is_int(raw[i]):
            pairs.append((raw[i].strip(), raw[i+1].strip()))
            i += 2
        else:
            i += 1

    # --- Extract CIRCLEs on A-_ANOT----_A ---
    circles = []
    cur = None
    for code, val in pairs:
        if code == "0":
            if cur and cur.get("type") == "CIRCLE" and cur.get("8") == "A-_ANOT----_A":
                try:
                    circles.append({
                        "handle_circle": cur.get("5"),
                        "center_x": float(cur.get("10")) if cur.get("10") else None,
                        "center_y": float(cur.get("20")) if cur.get("20") else None,
                        "radius": float(cur.get("40")) if cur.get("40") else None,
                    })
                except: pass
            cur = {"type": val}
        else:
            if cur is None: continue
            cur[code] = val
    # flush last
    if cur and cur.get("type") == "CIRCLE" and cur.get("8") == "A-_ANOT----_A":
        try:
            circles.append({
                "handle_circle": cur.get("5"),
                "center_x": float(cur.get("10")) if cur.get("10") else None,
                "center_y": float(cur.get("20")) if cur.get("20") else None,
                "radius": float(cur.get("40")) if cur.get("40") else None,
            })
        except: pass
    df_cir = pd.DataFrame(circles)

    # --- Extract INSERTs where block name (code 2) contains the phrase ---
    inserts = []
    cur = None
    for code, val in pairs:
        if code == "0":
            if cur and cur.get("type") == "INSERT":
                name = cur.get("2") or ""
                if PHRASE.lower() in name.lower():
                    try:
                        inserts.append({
                            "handle_bss": cur.get("5"),
                            "block_name": name,
                            "layer_bss": cur.get("8"),
                            "ins_x": float(cur.get("10")) if cur.get("10") else None,
                            "ins_y": float(cur.get("20")) if cur.get("20") else None,
                        })
                    except: pass
            cur = {"type": val}
        else:
            if cur is None: continue
            cur[code] = val
    # flush last
    if cur and cur.get("type") == "INSERT":
        name = cur.get("2") or ""
        if PHRASE.lower() in name.lower():
            try:
                inserts.append({
                    "handle_bss": cur.get("5"),
                    "block_name": name,
                    "layer_bss": cur.get("8"),
                    "ins_x": float(cur.get("10")) if cur.get("10") else None,
                    "ins_y": float(cur.get("20")) if cur.get("20") else None,
                })
            except: pass
    df_bss = pd.DataFrame(inserts)

    # --- Prefix2 utilities ---
    def prefix2(s):
        if pd.isna(s): return None
        s = str(s).strip()
        return s[:2].upper() if len(s) >= 2 else None

    if not df_cir.empty:
        df_cir["handle_prefix2"] = df_cir["handle_circle"].apply(prefix2)
    if not df_bss.empty:
        df_bss["handle_prefix2"] = df_bss["handle_bss"].apply(prefix2)

    # --- Prefix-join and choose nearest BSS per circle ---
    if not df_cir.empty and not df_bss.empty:
        merged = df_cir.merge(df_bss, on="handle_prefix2", how="left")
        merged["distance"] = np.sqrt((merged["center_x"] - merged["ins_x"])**2 + (merged["center_y"] - merged["ins_y"])**2)
        best = merged.sort_values(["handle_circle","distance"], na_position="last").groupby("handle_circle", as_index=False).first()
    else:
        best = df_cir.copy()
        best["block_name"] = np.nan
        best["handle_bss"] = np.nan
        best["ins_x"] = np.nan
        best["ins_y"] = np.nan
        best["distance"] = np.nan

    # --- Extract wall lines on A-_WALL----_E / A-_WALL----_H ---
    lines = []
    cur = None
    for code, val in pairs:
        if code == "0":
            if cur and cur.get("type") == "LINE" and cur.get("8") in ("A-_WALL----_E", "A-_WALL----_H"):
                try:
                    lines.append({
                        "handle": cur.get("5"),
                        "layer": cur.get("8"),
                        "x1": float(cur.get("10")) if cur.get("10") else None,
                        "y1": float(cur.get("20")) if cur.get("20") else None,
                        "x2": float(cur.get("11")) if cur.get("11") else None,
                        "y2": float(cur.get("21")) if cur.get("21") else None,
                    })
                except: pass
            cur = {"type": val}
        else:
            if cur is None: continue
            cur[code] = val
    # flush last
    if cur and cur.get("type") == "LINE" and cur.get("8") in ("A-_WALL----_E", "A-_WALL----_H"):
        try:
            lines.append({
                "handle": cur.get("5"),
                "layer": cur.get("8"),
                "x1": float(cur.get("10")) if cur.get("10") else None,
                "y1": float(cur.get("20")) if cur.get("20") else None,
                "x2": float(cur.get("11")) if cur.get("11") else None,
                "y2": float(cur.get("21")) if cur.get("21") else None,
            })
        except: pass
    df_lines = pd.DataFrame(lines)

    def point_to_segment_distance(px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        seg_len2 = dx*dx + dy*dy
        if seg_len2 == 0:
            return math.hypot(px - x1, py - y1)
        t = ((px - x1)*dx + (py - y1)*dy) / seg_len2
        t = max(0.0, min(1.0, t))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.hypot(px - proj_x, py - proj_y)

    # Attach nearest wall to each circle row (based on BSS point)
    best_rows = []
    for _, r in best.iterrows():
        px, py = r.get("ins_x"), r.get("ins_y")
        if pd.isna(px) or pd.isna(py) or df_lines.empty:
            best_rows.append({
                "nearest_wall_layer": np.nan, "nearest_wall_handle": np.nan, "nearest_wall_distance": np.nan,
                "wall_x1": np.nan, "wall_y1": np.nan, "wall_x2": np.nan, "wall_y2": np.nan
            })
            continue
        dmin = None; rec = None
        for _, ln in df_lines.iterrows():
            if pd.isna(ln["x1"]) or pd.isna(ln["y1"]) or pd.isna(ln["x2"]) or pd.isna(ln["y2"]):
                continue
            d = point_to_segment_distance(px, py, ln["x1"], ln["y1"], ln["x2"], ln["y2"])
            if (dmin is None) or (d < dmin):
                dmin = d; rec = ln
        if rec is None:
            best_rows.append({
                "nearest_wall_layer": np.nan, "nearest_wall_handle": np.nan, "nearest_wall_distance": np.nan,
                "wall_x1": np.nan, "wall_y1": np.nan, "wall_x2": np.nan, "wall_y2": np.nan
            })
        else:
            best_rows.append({
                "nearest_wall_layer": rec["layer"], "nearest_wall_handle": rec["handle"], "nearest_wall_distance": dmin,
                "wall_x1": rec["x1"], "wall_y1": rec["y1"], "wall_x2": rec["x2"], "wall_y2": rec["y2"]
            })

    df_near = pd.DataFrame(best_rows)
    df_final = pd.concat([best, df_near], axis=1)

    # --- ROUND all numeric columns to nearest whole number ---
    num_cols = df_final.select_dtypes(include=[np.number]).columns.tolist()
    df_final[num_cols] = df_final[num_cols].round(0)
    # normalize -0.0 -> 0 and cast to Int64 where possible
    for c in num_cols:
        df_final[c] = df_final[c].astype(float).replace(-0.0, 0.0)
        if df_final[c].dropna().apply(float.is_integer).all():
            df_final[c] = df_final[c].astype("Int64")
    return df_final

    

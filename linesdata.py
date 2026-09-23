import pandas as pd
import numpy as np

tol = 1e-3
targets = [11507.0854, 12107.0854]

df_all = pd.read_csv("Lines_ANOT_A_Color170.csv")  # This only has a subset.
# We need the full parsed df; reparse quickly:
from pathlib import Path

DXF_PATH = Path("TERRAHL2-FP-MB-T1am(JMB)-A88dxf.dxf")
text = DXF_PATH.read_text(encoding="utf-8", errors="ignore")
lines = text.splitlines()
n = len(lines)


def get_pair(i):
    return lines[i].rstrip("\n"), lines[i + 1].rstrip("\n")


parsed = []
i = 0
while i < n - 1:
    c, v = get_pair(i)
    if c.strip() == "0" and v.strip() == "LINE":
        i += 2
        handle = ""
        layer = ""
        linetype = ""
        color = None
        x1 = y1 = z1 = x2 = y2 = z2 = None
        while i < n - 1:
            c2, v2 = get_pair(i)
            cs = c2.strip()
            vs = v2.strip()
            if cs == "0":
                break
            if cs == "5":
                handle = vs
            elif cs == "8":
                layer = v2.strip()
            elif cs == "6":
                linetype = v2.strip()
            elif cs == "62":
                try:
                    color = int(vs)
                except:
                    color = None
            elif cs == "10":
                try:
                    x1 = float(vs)
                except:
                    pass
            elif cs == "20":
                try:
                    y1 = float(vs)
                except:
                    pass
            elif cs == "30":
                try:
                    z1 = float(vs)
                except:
                    pass
            elif cs == "11":
                try:
                    x2 = float(vs)
                except:
                    pass
            elif cs == "21":
                try:
                    y2 = float(vs)
                except:
                    pass
            elif cs == "31":
                try:
                    z2 = float(vs)
                except:
                    pass
            i += 2
        parsed.append(
            {
                "handle": handle,
                "layer": layer,
                "linetype": linetype,
                "color": color,
                "startx": x1,
                "starty": y1,
                "endx": x2,
                "endy": y2,
            }
        )
        continue
    else:
        i += 2

df_all = pd.DataFrame(parsed)


def near(a, b, eps=tol):
    return (a is not None) and (b is not None) and abs(a - b) <= eps


rows = []
for t in targets:
    sub = df_all[
        (df_all["startx"].notna())
        & (df_all["endx"].notna())
        & (np.isclose(df_all["startx"], df_all["endx"], atol=tol))
        & (np.isclose(df_all["startx"], t, atol=tol))
    ][
        ["handle", "layer", "linetype", "color", "startx", "starty", "endx", "endy"]
    ].copy()
    sub["target_x"] = t
    rows.append(sub)

vert_hits = pd.concat(rows, ignore_index=True)
out_csv = "Vertical_Lines_Near_11507_12107_AllLayers.csv"
vert_hits.to_csv(out_csv, index=False)

(vert_hits.head(20), len(vert_hits), out_csv)

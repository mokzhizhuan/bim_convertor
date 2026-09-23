# The previous cell "Code execution state reset." indicates the kernel restarted.
# Re-run the extraction code to produce the CSV and preview rows.

from pathlib import Path
import pandas as pd

DXF_PATH = Path("TERRAHL2-FP-MB-T1am(JMB)-A88dxf.dxf")
OUT_CSV = "All_Block_Inserts.csv"


def parse_all_inserts(dxf_path: Path):
    rows = []
    with dxf_path.open("r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()

    n = len(lines)
    i = 0

    def get_pair(idx):
        return lines[idx].rstrip("\n"), lines[idx + 1].rstrip("\n")

    while i < n - 1:
        code, val = get_pair(i)
        if code.strip() == "0" and val.strip() == "INSERT":
            ent = {
                "handle": "",
                "owner": "",
                "layer": "",
                "name": "",
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "scale_x": 1.0,
                "scale_y": 1.0,
                "scale_z": 1.0,
                "rotation_deg": 0.0,
                "revit_pairs": [],
            }
            i += 2
            in_revit = False
            pending_key = None

            while i < n - 1:
                c, v = get_pair(i)
                cs = c.strip()
                vs = v.strip()

                if cs == "0":
                    break

                if cs == "5":
                    ent["handle"] = vs
                elif cs == "330":
                    ent["owner"] = vs
                elif cs == "8":
                    ent["layer"] = v
                elif cs == "2":
                    ent["name"] = v
                elif cs == "10":
                    try:
                        ent["x"] = float(vs)
                    except:
                        pass
                elif cs == "20":
                    try:
                        ent["y"] = float(vs)
                    except:
                        pass
                elif cs == "30":
                    try:
                        ent["z"] = float(vs)
                    except:
                        pass
                elif cs == "41":
                    try:
                        ent["scale_x"] = float(vs)
                    except:
                        pass
                elif cs == "42":
                    try:
                        ent["scale_y"] = float(vs)
                    except:
                        pass
                elif cs == "43":
                    try:
                        ent["scale_z"] = float(vs)
                    except:
                        pass
                elif cs == "50":
                    try:
                        ent["rotation_deg"] = float(vs)
                    except:
                        pass

                if cs == "1001":
                    in_revit = vs.upper() == "REVIT"
                    pending_key = None
                elif in_revit and cs == "1002":
                    pass
                elif in_revit and cs == "1070":
                    try:
                        pending_key = int(vs)
                    except:
                        pending_key = None
                elif in_revit and cs == "1000" and pending_key is not None:
                    ent["revit_pairs"].append((pending_key, v))
                    pending_key = None

                i += 2

            rows.append(
                {
                    "handle": ent["handle"],
                    "layer": ent["layer"],
                    "block_name": ent["name"],
                    "x": ent["x"],
                    "y": ent["y"],
                    "z": ent["z"],
                    "rotation_deg": ent["rotation_deg"],
                    "scale_x": ent["scale_x"],
                    "scale_y": ent["scale_y"],
                    "scale_z": ent["scale_z"],
                    "revit_pairs": (
                        ";".join(f"{k}={v}" for k, v in ent["revit_pairs"])
                        if ent["revit_pairs"]
                        else ""
                    ),
                }
            )
            continue
        else:
            i += 2

    return rows


rows = parse_all_inserts(DXF_PATH)
df = pd.DataFrame(rows)
df.to_csv(OUT_CSV, index=False)

df.head(25), OUT_CSV

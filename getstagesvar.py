import pandas as pd
import compute_wall_center as wc


def getstage2andstage3(
    all_objs,
    args,
    visited,
    origin_x,
    origin_y,
    internalx_width,
    internalxmax_width,
    internalymax_width,
    offset,
    internaly_width,
    other_floor,
    top_twofloor_z,
    floor_offset,
    thickness
):
    def _first_kv(d):
        k = next(iter(d))
        return k, d[k]
    stage2_rows, centerpoint_rows = [], []
    for i, wall_dict in enumerate(visited):
        posz_cp = 1000
        name, w = _first_kv(wall_dict)
        axis = w["axis"]
        width_val = w["area"][0]
        row = {
            "Marking Type": "Wall",
            "Name": name,
            "GX": w["x"],
            "GY": w["y"],
            "GZ": w["z"],
            "Wall Number": i + 1,
            "Shape Type" : "",
            "Width": width_val,
            "Height": w["area"][2],
        }
        stage2_rows.append(row)
        if axis == "X":
            dist_needed = -(w["y"] + origin_y)
            y_wallsurface = (w["y"] + origin_y) + dist_needed
            stage2_rows.append({
                "Marking Type": "Center Point",
                "Name": f"CP{i + 1}S2",
                "GX": (internalxmax_width / 2)+ thickness,
                "GY": y_wallsurface,
                "GZ": posz_cp,
                "Wall Number": i + 1,
                "Shape Type" : "",
                "Width": width_val,
                "Height": w["area"][2],
            })
            centerpoint_rows.append({
                "Wall Number": i + 1,
                "Name": name,
                "centerpointwidth": internalx_width,  
                "centerpointhheight": posz_cp,        
                "floortileheight": posz_cp + offset,
                "AxisDirection": w["facingaxis"],
            })
        elif axis == "Y":  
            dist_needed = -(w["x"] + origin_x)
            x_wallsurface = (w["x"] + origin_x) + dist_needed
            stage2_rows.append({
                "Marking Type": "Center Point",
                "Name": f"CP{i + 1}S2",
                "GX": x_wallsurface,
                "GY": (internalymax_width / 2)+thickness,
                "GZ": posz_cp,
                "Wall Number": i + 1,
                "Shape Type" : "",
                "Width":  width_val, 
                "Height": w["area"][2],
            })
            centerpoint_rows.append({
                "Wall Number": i + 1,
                "Name": name,
                "centerpointwidth": internaly_width,
                "centerpointhheight": posz_cp,
                "floortileheight": posz_cp + offset,
                "AxisDirection": w["facingaxis"],
            })
    for floor_obj in other_floor:
        stage2_rows.append({
            "Wall Number": "F",
            "Name": floor_obj["name"],
            "Marking Type": "Floor",
            "Shape Type" : "",
            "GX": floor_obj["x"],
            "GY": floor_obj["y"],
            "GZ": floor_obj["z"],
            "Width": internalxmax_width,
            "Height": internalymax_width,
        })
        if len(visited) == 6:
            centerpoint_rows.append({
                "Wall Number": "F",
                "Name": floor_obj["name"],
                "centerpointwidth": internalx_width,
                "centerpointheight": internaly_width,
                "floortileheight": [1000 + abs(top_twofloor_z[0]), 1000 + abs(top_twofloor_z[1])],
                "AxisDirection": floor_obj["facingaxis"],
            })
        else:
            centerpoint_rows.append({
                "Wall Number": "F",
                "Name": floor_obj["name"],
                "centerpointwidth": internalx_width,
                "centerpointheight": internaly_width,
                "floortileheight": [1000 + abs(floor_offset)],
                "AxisDirection": floor_obj["facingaxis"],
            })
    floor_z_off = -abs(1000)
    stage2_rows.append({
        "Marking Type" : "Center Point",
        "Name": f"CP{len(visited) + 1}S2",
        "GX": (internalxmax_width / 2)+ thickness,
        "GY": (internalymax_width / 2)+ thickness,
        "GZ": floor_z_off,
        "Wall Number": "F",
        "Shape Type" : "",
        "Width": internalxmax_width,
        "Height": internalymax_width,
    })
    checklist_file = pd.ExcelFile(args.excel_checklist)

    print("[EXCEL] Available sheets:", checklist_file.sheet_names)

    preferred_sheets = [
        "Sheet1",
        "Checklist",
        "checklist",
        "BOM",
        "bom",
    ]

    selected_sheet = None

    for sheet in preferred_sheets:
        if sheet in checklist_file.sheet_names:
            selected_sheet = sheet
            break

    if selected_sheet is None:
        selected_sheet = checklist_file.sheet_names[0]
        print(f"[EXCEL] Sheet1 not found. Using first sheet: {selected_sheet}")

    df_checklist = checklist_file.parse(selected_sheet)
    item_names = df_checklist.iloc[1:, 3].dropna().unique().tolist()
    filtered_item_names = [n for n in item_names
                        if "bss.10 glass" not in n.lower()
                        and "wall finishes" not in n.lower()
                        and "floor finishes" not in n.lower()]
    stage3_objects = [
        {"name": o["name"], "x": o["x"], "y": o["y"], "z": o["z"]}
        for o in all_objs
        if any(f in o["name"] for f in filtered_item_names)
    ]
    return stage2_rows, centerpoint_rows, stage3_objects, df_checklist 